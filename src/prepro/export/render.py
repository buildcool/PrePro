"""Render a Timeline to MP4: per-item video segments → transitions → overlays + captions (libass) →
numpy audio mix (ducking, fades, bleeps, voice polish) normalised to −14 LUFS → mux. Also renders a
storyboard contact sheet used for self-review.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..assist.looks import lut_path
from ..config import assets_dir
from ..media import encoders as enc
from ..media.ffmpeg import ffmpeg_bin, run_ffmpeg
from ..project import Project
from ..schema.analysis import ProjectAnalysis
from ..schema.timeline import Item, Timeline, Transform, TransformKey
from ..timeline.captions import write_ass

SR = 48000


@dataclass
class RenderResult:
    video: Path
    audio: Path
    duration: float
    lufs: float | None
    true_peak_db: float | None
    speech_to_music_db: float | None
    storyboard: Path | None = None
    encoder: str = "cpu"                 # nvenc | qsv | amf | cpu — what encoded the final picture
    encoder_note: str = ""               # in words, incl. a GPU → CPU fallback and why


def ff_escape(p: Path | str) -> str:
    s = str(p).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _still_input(src: Path, dur: float) -> list[str]:
    """Input options to hold an image for `dur` seconds. An animated GIF loops (the GIF reader has no `-loop`
    option, so the image-style `-loop 1` made every GIF meme fail to render)."""
    if Path(src).suffix.lower() == ".gif":
        return ["-stream_loop", "-1", "-t", f"{dur:.3f}", "-i", str(src)]
    return ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(src)]


def _panel(place: tuple[float, float, float, float], W: int, H: int) -> tuple[int, int, int, int]:
    """A layout panel in output pixels: (x, y, w, h), even sizes, inside the frame."""
    x, y, w, h = place
    pw, ph = min(_even(w * W), W), min(_even(h * H), H)
    return min(int(round(x * W)), W - pw), min(int(round(y * H)), H - ph), pw, ph


# ------------------------------------------------------------------ video
def _crop_filter(it: Item, sw: int, sh: int, W: int, H: int, dur: float) -> str:
    ar = W / H
    if sw / sh > ar:
        ch, cw = sh, sh * ar
    else:
        cw, ch = sw, sw / ar
    tf = it.transform
    cx, cy, z = (tf.cx, tf.cy, tf.zoom) if tf else (0.5, 0.5, 1.0)
    if tf and tf.keys and len(tf.keys) >= 2:
        k0, k1 = tf.keys[0], tf.keys[-1]
        z0, z1 = k0.zoom, k1.zoom
        D = max(k1.t - k0.t, 0.1)
        if abs(z1 - z0) > 1e-3:
            # scale the picture up from the smaller zoom and crop a fixed window: the frame never shrinks under the
            # crop, so a pull-out (z0 > z1) works as well as a push-in
            zr = max(min(z0, z1), 1.0)
            cw0, ch0 = _even(cw / zr * 0.999), _even(ch / zr * 0.999)
            zexpr = f"({z0}+({z1 - z0})*t/{D:.3f})/{zr}"
            return (f"scale=w='iw*{zexpr}':h='ih*{zexpr}':eval=frame:flags=bicubic,"
                    f"crop={cw0}:{ch0}:x='(iw-ow)*{cx:.4f}':y='(ih-oh)*{cy:.4f}'")
        # operator reframing: piecewise-linear crop centre through every key (x in source pixels, clamped)
        cw2, ch2 = _even(cw / max(z, 1.0) * 0.999), _even(ch / max(z, 1.0) * 0.999)
        ks = [(k.t, k.cx * sw - cw2 / 2) for k in tf.keys]
        expr = f"{ks[-1][1]:.1f}"
        for (ta, xa), (tb, xb) in reversed(list(zip(ks, ks[1:], strict=False))):
            span = max(tb - ta, 1e-3)
            expr = f"if(lt(t,{tb:.3f}),{xa:.1f}+({xb - xa:.1f})*(t-{ta:.3f})/{span:.3f},{expr})"
        y = int(min(max(cy * sh - ch2 / 2, 0), sh - ch2))
        return f"crop={cw2}:{ch2}:x='max(0,min(iw-ow,{expr}))':y={y}"
    cw2, ch2 = _even(cw / max(z, 1.0) * 0.999), _even(ch / max(z, 1.0) * 0.999)
    x = int(min(max(cx * sw - cw2 / 2, 0), sw - cw2))
    y = int(min(max(cy * sh - ch2 / 2, 0), sh - ch2))
    return f"crop={cw2}:{ch2}:{x}:{y}"


def photo_frames(src: Path, it: Item, W: int, H: int, fps: float, nframes: int):
    """The frames of a photo on screen (BGR arrays): a frame-shaped window moved along the item's keys (pan and zoom)
    with sub-pixel precision, so a slow Ken Burns glides instead of stepping a whole pixel at a time. ``fit``: the
    whole photo on a soft, darkened blurred copy of itself, the composition moving as one."""
    import cv2
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        img = cv2.cvtColor(np.asarray(ImageOps.exif_transpose(im).convert("RGB")), cv2.COLOR_RGB2BGR)
    tf = it.transform or Transform()
    keys = tf.keys or [TransformKey(t=0.0, cx=tf.cx, cy=tf.cy, zoom=tf.zoom)]
    if tf.fit:
        # compose once at the output size: a soft wash of the photo's own colours (blurred hard, darker, a little
        # desaturated, so no shape in it competes with the photo), then the photo whole, a little above the middle,
        # with a soft shadow under it like a print on a table
        sh, sw = img.shape[:2]
        # the wash: the whole photo boiled down to a 2×4 grid of its colours, then spread smoothly over the frame — a
        # gradient in the photo's own palette (as Instagram fills a Story), with no shapes left to compete
        cells = cv2.resize(img, (2, 4), interpolation=cv2.INTER_AREA).astype(np.float32)
        grey = cells.mean(axis=2, keepdims=True)
        cells = (0.8 * cells + 0.2 * grey) * 0.6
        small = cv2.resize(cells, (max(8, W // 20), max(8, H // 20)), interpolation=cv2.INTER_LINEAR)
        small = cv2.GaussianBlur(small, (0, 0), sigmaX=small.shape[1] / 6)
        bg = cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
        s_fit = min(W / sw, H / sh) * (0.94 if sw / sh > W / H else 1.0)     # a margin at the sides: a print, not a strip
        fw, fh = max(2, int(round(sw * s_fit))), max(2, int(round(sh * s_fit)))
        top = int(min(max((H - fh) * 0.45, 0), H - fh))
        left = (W - fw) // 2
        shadow = np.zeros((H, W), np.float32)
        off = max(2, H // 120)
        shadow[min(H, top + off):min(H, top + fh + off), left:left + fw] = 1.0
        shadow = cv2.GaussianBlur(shadow, (0, 0), sigmaX=max(2.0, H / 70))
        bg *= (1 - 0.55 * shadow)[:, :, None]
        bg[top:top + fh, left:left + fw] = cv2.resize(img, (fw, fh), interpolation=cv2.INTER_AREA)
        img = bg.clip(0, 255).astype(np.uint8)
    sh, sw = img.shape[:2]
    ar = W / H
    cw, ch = (sh * ar, sh) if sw / sh > ar else (sw, sw / ar)          # the frame-shaped window at zoom 1
    zmin = max(1.0, min(k.zoom for k in keys))
    pre = min(1.0, 1.25 * W / (cw / zmin))                              # shrink once (area filter): no shimmer on fine detail
    if pre < 0.999:
        img = cv2.resize(img, (max(2, int(round(sw * pre))), max(2, int(round(sh * pre)))), interpolation=cv2.INTER_AREA)
        sh, sw = img.shape[:2]
        cw, ch = cw * pre, ch * pre
    for i in range(nframes):
        cx, cy, z = tf.at(i / fps) if tf.keys else (keys[0].cx, keys[0].cy, keys[0].zoom)
        z = max(1.0, z)
        vw, vh = cw / z, ch / z
        x0 = min(max(cx * sw - vw / 2, 0.0), sw - vw)
        y0 = min(max(cy * sh - vh / 2, 0.0), sh - vh)
        s = W / vw
        m = np.float32([[s, 0, -x0 * s], [0, H / vh, -y0 * H / vh]])
        yield cv2.warpAffine(img, m, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _segment(pa: ProjectAnalysis, proj: Project, it: Item, W: int, H: int, fps: float, *, crf: int, preset: str, look: Path | None,
             cache: Path, encoder: enc.Encoder = enc.CPU) -> tuple[Path, str]:
    """One V1 item as a clip at the timeline's size and frame rate. Returns (file, encoder name). Cached per item;
    the encoder is part of the file name so pieces from different encoders are never stream-copied together."""
    # frames from the rounded cut points, not the rounded length: pieces joined end to end then stay on the timeline's
    # clock (independent rounding drifts a frame every few cuts — off the beat by the end of a photo reel)
    nframes = max(1, int(round(it.rec_out * fps)) - int(round(it.rec_in * fps)))
    key = hashlib.sha1(json.dumps([it.model_dump(exclude={"id", "rec_in", "suggestion_ids", "section", "role", "note"}), W, H, fps, crf, preset,
                                   str(look), nframes], sort_keys=True, default=str).encode()).hexdigest()[:16]
    want = encoder.name
    # "auto" reuses a piece from any encoder; a forced encoder (e.g. cpu) only its own
    for name in dict.fromkeys((want, "cpu", *enc.GPU_ORDER) if enc.preference() == "auto" else (want,)):
        hit = cache / f"seg_{key}_{name}.mp4"
        if hit.exists() and hit.stat().st_size > 1000:
            return hit, name
    a = pa.asset(it.asset_id)
    src = proj.path(a.path)
    dur = it.rec_dur
    lut = f",lut3d=file='{ff_escape(look)}'" if look else ""
    tail = f",fps={fps},format=yuv420p,setsar=1{lut}"
    if it.kind == "image" and it.transform is not None and a.kind.value == "image":
        # a photo that moves like a camera: every frame drawn at sub-pixel precision from the upright working copy
        from ..analyze.pipeline import photo_copy

        wc = photo_copy(proj, a)
        tmp = cache / f"seg_{key}.part.mp4"
        used = enc.encode_frames(lambda: photo_frames(wc if wc.exists() else src, it, W, H, fps, nframes), (W, H), fps,
                                 lambda e: ["-frames:v", str(nframes), "-vf", f"format=yuv420p,setsar=1{lut}", "-an", *e.args(crf, preset),
                                            "-r", f"{fps}", str(tmp)], prefer=encoder, timeout=1800)
        out = cache / f"seg_{key}_{used.name}.mp4"
        os.replace(tmp, out)
        return out, used.name
    elif it.kind == "image":
        vf = (f"[0:v]split[bg0][fg0];[bg0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2[bg];"
              f"[fg0]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2{tail}[v]")
        args = [*_still_input(src, dur + 0.2), "-filter_complex", vf, "-map", "[v]"]
    else:
        ds = a.info.display_size or (W, H)
        src_dur = it.src_out - it.src_in
        speed = f"setpts=(PTS-STARTPTS)/{it.speed}," if abs(it.speed - 1) > 1e-3 else "setpts=PTS-STARTPTS,"
        if a.kind.value in ("meme_video",) and abs(ds[0] / ds[1] - W / H) > 0.05:
            vf = (f"[0:v]{speed}split[bg0][fg0];[bg0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2[bg];"
                  f"[fg0]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2{tail}[v]")
        elif it.place:                                   # one panel of a layout; the rest of the frame stays black
            px, py, pw, ph = _panel(it.place, W, H)
            vf = (f"[0:v]{speed}{_crop_filter(it, ds[0], ds[1], pw, ph, dur)},scale={pw}:{ph}:flags=bicubic,"
                  f"pad={W}:{H}:{px}:{py}:color=black{tail}[v]")
        else:
            vf = f"[0:v]{speed}{_crop_filter(it, ds[0], ds[1], W, H, dur)},scale={W}:{H}:flags=bicubic{tail}[v]"
        args = ["-ss", f"{max(0.0, it.src_in):.3f}", "-t", f"{src_dur + 0.1:.3f}", "-i", str(src), "-filter_complex", vf, "-map", "[v]"]
    tmp = cache / f"seg_{key}.part.mp4"
    used = enc.encode(lambda e: [*args, "-frames:v", str(nframes), "-an", *e.args(crf, preset), "-r", f"{fps}", str(tmp)],
                      prefer=encoder, timeout=1800)
    out = cache / f"seg_{key}_{used.name}.mp4"
    os.replace(tmp, out)
    return out, used.name


def _combine(segs: list[tuple[Item, Path]], out: Path, fps: float, crf: int, preset: str, *, reencode: bool = False,
             encoder: enc.Encoder = enc.CPU) -> str:
    """Join the V1 pieces: a stream copy when every cut is hard and the pieces are x264's, else one more encode.
    Returns the encoder ("copy" for a stream copy)."""
    if not reencode and not any(it.transition_in != "cut" and it.transition_dur > 0 for it, _ in segs[1:]):
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for _, p in segs), encoding="utf-8")
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)], timeout=1800)
        return "copy"
    xf = {"whip": "hblur", "dissolve": "fade", "zoom": "zoomin", "fade_black": "fadeblack", "slide": "slideleft"}
    args, chain = [], []
    for _, p in segs:
        args += ["-i", str(p)]
    for k in range(len(segs)):   # one clock for every input, or xfade/concat refuse to link
        chain.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={fps},format=yuv420p,settb=AVTB[n{k}]")
    acc = "[n0]"
    for k, (it, _) in enumerate(segs[1:], start=1):
        lab = f"[x{k}]"
        if it.transition_in != "cut" and it.transition_dur > 0:
            chain.append(f"{acc}[n{k}]xfade=transition={xf.get(it.transition_in, 'fade')}:duration={it.transition_dur:.3f}:offset={it.rec_in:.3f}{lab}")
        else:
            chain.append(f"{acc}[n{k}]concat=n=2:v=1:a=0,settb=AVTB{lab}")
        acc = lab
    args += ["-filter_complex", ";".join(chain), "-map", acc]
    return enc.encode(lambda e: [*args, *e.args(crf, preset), "-r", f"{fps}", str(out)], prefer=encoder, timeout=3600).name


def _overlay_pass(pa: ProjectAnalysis, proj: Project, tl: Timeline, base: Path, ass: Path | None, out: Path, W: int, H: int, fps: float,
                  crf: int, preset: str, look: Path | None, encoder: enc.Encoder = enc.CPU) -> str | None:
    """B-roll/meme overlays + captions over the joined picture. Returns the encoder (None when nothing to add)."""
    ovs = [i for i in tl.items if i.track in ("V2", "V3") and i.kind in ("video", "image")]
    args = ["-i", str(base)]
    chain = []
    acc = "[0:v]"
    sx, sy = W / tl.width, H / tl.height
    for k, it in enumerate(ovs, start=1):
        a = pa.asset(it.asset_id)
        ds = a.info.display_size or (W, H)
        lut = f",lut3d=file='{ff_escape(look)}'" if look else ""
        if it.kind == "image":
            args += _still_input(proj.path(a.path), it.rec_dur)
            pre = f"[{k}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,format=yuva420p,setpts=PTS-STARTPTS+{it.rec_in:.3f}/TB[o{k}]"
        else:
            args += ["-ss", f"{it.src_in:.3f}", "-t", f"{it.src_out - it.src_in:.3f}", "-i", str(proj.path(a.path))]
            px, py, pw, ph = _panel(it.place, W, H) if it.place else (0, 0, W, H)
            pre = (f"[{k}:v]setpts=(PTS-STARTPTS)/{it.speed}+{it.rec_in:.3f}/TB,{_crop_filter(it, ds[0], ds[1], pw, ph, it.rec_dur)},"
                   f"scale={pw}:{ph},fps={fps},format=yuv420p{lut}[o{k}]")
        chain.append(pre)
        ox, oy = (_panel(it.place, W, H)[:2] if it.place and it.kind != "image" else (0, 0))
        chain.append(f"{acc}[o{k}]overlay={ox}:{oy}:enable='between(t,{it.rec_in:.3f},{it.rec_out:.3f})':eof_action=pass[ov{k}]")
        acc = f"[ov{k}]"
    if ass is not None:
        chain.append(f"{acc}ass=filename='{ff_escape(ass)}':fontsdir='{ff_escape(assets_dir() / 'fonts')}'[vout]")
        acc = "[vout]"
    if not chain:
        os.replace(base, out)
        return None
    args += ["-filter_complex", ";".join(chain), "-map", acc]
    _ = (sx, sy)
    return enc.encode(lambda e: [*args, *e.args(crf, preset), "-r", f"{fps}", str(out)], prefer=encoder, timeout=3600).name


# ------------------------------------------------------------------ audio
def _decode(src: Path, start: float, dur: float, *, speed: float = 1.0, polish: str = "") -> np.ndarray:
    af = []
    if abs(speed - 1) > 1e-3:
        s = speed
        while s > 2.0:
            af.append("atempo=2.0")
            s /= 2.0
        while s < 0.5:
            af.append("atempo=0.5")
            s /= 0.5
        af.append(f"atempo={s:.4f}")
    if polish:
        af.append(polish)
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True, timeout=600)
    if p.returncode != 0 or not p.stdout:
        return np.zeros((0, 2), np.float32)
    return np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()


def _builtin(name: str, dur: float) -> np.ndarray:
    from ..fixtures.audio import sfx

    if name == "bleep":
        t = np.arange(int(dur * SR)) / SR
        y = (np.sin(2 * np.pi * 1000 * t) * 0.5).astype(np.float32)
    else:
        try:
            y = sfx(name)
        except ValueError:
            y = sfx("pop")
    return np.stack([y, y], -1)


def _fades(y: np.ndarray, fin: float, fout: float) -> np.ndarray:
    n = len(y)
    a, b = min(n, int(fin * SR)), min(n, int(fout * SR))
    if a > 1:
        y[:a] *= np.linspace(0, 1, a, dtype=np.float32)[:, None]
    if b > 1:
        y[-b:] *= np.linspace(1, 0, b, dtype=np.float32)[:, None]
    return y


def voice_polish_filter(pa: ProjectAnalysis, asset_id: str) -> str:
    rep = pa.clips[asset_id].audio
    parts = ["highpass=f=75"]
    if rep.noise_floor_db is not None and rep.noise_floor_db > -50:
        parts.append("afftdn=nf=-30:tn=1")
    if rep.hum_hz:
        parts.append(f"bandreject=f={rep.hum_hz:.0f}:width_type=h:w=6")
    parts.append("deesser=i=0.4")
    parts.append("acompressor=threshold=-20dB:ratio=3:attack=10:release=150:makeup=2")
    return ",".join(parts)


def mix_audio(pa: ProjectAnalysis, proj: Project, tl: Timeline, out: Path, *, target_lufs: float = -14.0, true_peak: float = -1.0,
              stems_dir: Path | None = None, polish_voice: bool = True, music: bool = True) -> tuple[float | None, float | None, float | None]:
    total = tl.duration + 0.25
    n = int(total * SR) + SR
    stems = {k: np.zeros((n, 2), np.float32) for k in ("dialogue", "music", "sfx")}
    bleeps = []
    for it in tl.items:
        if it.kind != "audio" or (not music and it.track == "A2"):
            continue
        if it.note.startswith("builtin:"):
            name = it.note.split(":", 1)[1]
            y = _builtin(name, it.src_out - it.src_in)
            if name == "bleep":
                bleeps.append((it.rec_in, it.rec_in + 0.4))
        else:
            a = pa.asset(it.asset_id)
            pol = voice_polish_filter(pa, a.id) if (polish_voice and it.track == "A1" and it.role not in ("natural",) and a.kind.value in ("aroll", "voiceover", "screen")) else ""
            y = _decode(proj.path(a.path), it.src_in, it.src_out - it.src_in, speed=it.speed, polish=pol)
        if not len(y):
            continue
        y = _fades(y.copy(), it.fade_in, it.fade_out)
        g = np.full(len(y), 10 ** (it.gain_db / 20), np.float32)
        if it.envelope:
            tt = it.rec_in + np.arange(len(y)) / SR
            et = np.array([e[0] for e in it.envelope])
            ed = np.array([e[1] for e in it.envelope])
            g *= (10 ** (np.interp(tt, et, ed) / 20)).astype(np.float32)
        y = y * g[:, None]
        s0 = int(it.rec_in * SR)
        e = min(n, s0 + len(y))
        stem = "music" if it.track == "A2" else "sfx" if it.track in ("A3", "A4") else "dialogue"
        stems[stem][s0:e] += y[: e - s0]
    for b0, b1 in bleeps:
        stems["dialogue"][int(b0 * SR): int(b1 * SR)] = 0
    mix = mix_raw = (stems["dialogue"] + stems["music"] + stems["sfx"])[: int(total * SR)]
    try:
        import pyloudnorm as pyln

        meter = pyln.Meter(SR)
    except Exception:
        meter = None

    def loud(x: np.ndarray) -> float | None:
        try:
            v = float(meter.integrated_loudness(x.astype(np.float64))) if meter is not None else None
            return v if v is not None and np.isfinite(v) else None
        except Exception:
            return None

    # loudness to target, then the true-peak limiter. Limiting a dense mix (music only, a loud drop) takes loudness
    # with it, so the gain is topped up and the limiter run again — at most +3 dB more, or it would sound squashed
    ceiling = 10 ** (true_peak / 20)
    lufs = loud(mix_raw)
    gain = first = 10 ** ((target_lufs - lufs) / 20) if lufs is not None else 1.0
    mix = _limit(mix_raw * gain, ceiling)
    after = loud(mix)
    for _ in range(2):
        if after is None or abs(after - target_lufs) <= 0.4:
            break
        gain = min(gain * 10 ** ((target_lufs - after) / 20), first * 10 ** (3 / 20))
        mix = _limit(mix_raw * gain, ceiling)
        after = loud(mix)
    for k in stems:
        stems[k] *= gain
    tp = float(20 * np.log10(max(1e-9, _true_peak(mix))))
    out_lufs = round(after, 2) if after is not None else None
    # speech-to-music ratio while someone talks (only where someone does: the sounds of a place — steps, a pan, waves —
    # share the dialogue stem, and music over them is meant to be the louder one)
    sm = None
    d, m = stems["dialogue"][: len(mix)], stems["music"][: len(mix)]
    hop = SR // 10
    k = len(mix) // hop
    if k > 5:
        dr = np.sqrt((d[: k * hop].reshape(k, hop, 2) ** 2).mean(axis=(1, 2)))
        mr = np.sqrt((m[: k * hop].reshape(k, hop, 2) ** 2).mean(axis=(1, 2)))
        spoken = np.zeros(k, dtype=bool)
        for it in tl.items:
            if it.track == "A1" and it.role != "natural":
                spoken[max(0, int(it.rec_in * 10)): max(0, int(np.ceil(it.rec_out * 10)))] = True
        talk = (dr > 10 ** (-40 / 20)) & spoken
        if talk.sum() > 3 and (mr[talk] > 1e-6).any():
            sm = round(float(np.median(20 * np.log10(dr[talk] + 1e-9) - 20 * np.log10(mr[talk] + 1e-9))), 1)
    sf.write(str(out), mix, SR, subtype="PCM_16")
    if stems_dir:
        stems_dir.mkdir(parents=True, exist_ok=True)
        for k2, y in stems.items():
            if np.abs(y).max() > 1e-5:
                sf.write(str(stems_dir / f"{k2}.wav"), np.clip(y[: len(mix)], -1, 1), SR, subtype="PCM_16")
    return out_lufs, round(tp, 2), sm


def _true_peak(x: np.ndarray) -> float:
    from scipy.signal import resample_poly

    seg = x if len(x) < SR * 120 else x[:: max(1, len(x) // (SR * 120))]
    up = resample_poly(seg, 4, 1, axis=0)
    return float(np.max(np.abs(up))) if up.size else 0.0


def _limit(x: np.ndarray, ceiling: float) -> np.ndarray:
    """Look-ahead true-peak limiter: peaks are measured between the samples too (4× oversampled), the gain dips
    over a 2 ms ramp instead of a step (a step would itself overshoot between samples) and recovers smoothly."""
    from scipy.ndimage import maximum_filter1d, minimum_filter1d
    from scipy.signal import resample_poly

    c = ceiling * 0.97
    if not len(x):
        return x
    up = np.max(np.abs(resample_poly(x, 4, 1, axis=0)), axis=1)
    peak = np.maximum(np.max(np.abs(x), axis=1), np.pad(up, (0, max(0, 4 * len(x) - len(up))))[: 4 * len(x)].reshape(-1, 4).max(axis=1))
    if peak.max() <= c:
        return x
    look = int(0.002 * SR)
    env = maximum_filter1d(peak, size=2 * look + 1)
    gain = minimum_filter1d(np.minimum(1.0, c / np.maximum(env, 1e-9)), size=2 * look + 1)
    gain = np.convolve(gain, np.ones(2 * look + 1) / (2 * look + 1), mode="same")
    rel = np.exp(-1.0 / (0.08 * SR))
    g = gain.copy()
    for i in range(1, len(g)):   # release smoothing (attack is instant thanks to look-ahead)
        if g[i] > g[i - 1]:
            g[i] = g[i - 1] * rel + g[i] * (1 - rel)
    return (x * g[:, None]).astype(np.float32)


# ------------------------------------------------------------------ main
def render(tl: Timeline, pa: ProjectAnalysis, out: Path, *, quality: str = "preview", preview_height: int = 540, project_root=None,
           stems: bool = False, storyboard: bool = True, captions: bool = True, music: bool = True, progress=None) -> RenderResult:
    proj = Project(project_root or pa.root)

    def step(i: float, msg: str) -> None:                    # where the render is, for the progress bar
        if progress:
            progress("render", i, 1, msg)

    short = preview_height if quality == "preview" else min(tl.width, tl.height)
    scale = short / min(tl.width, tl.height)
    W, H = _even(tl.width * scale), _even(tl.height * scale)
    crf, preset = (30, "veryfast") if quality == "preview" else (19, "medium")
    look = lut_path(tl.look) if tl.look else None
    work = proj.sub(f"renders/work_{quality}")
    encoder = enc.choose(min(W, H))                  # the GPU when it is measurably faster here, else the CPU
    segs, made_by = [], []
    pieces = sorted((i for i in tl.items if i.track == "V1" and i.kind in ("video", "image")), key=lambda i: i.rec_in)
    for k, it in enumerate(pieces):
        step(0.75 * k / max(1, len(pieces)), f"cutting piece {k + 1} of {len(pieces)}")
        path, by = _segment(pa, proj, it, W, H, tl.fps, crf=crf if quality == "preview" else 16, preset=preset, look=look, cache=work,
                            encoder=encoder)
        segs.append((it, path))
        made_by.append(by)
    if not segs:
        raise ValueError("timeline has no picture")
    out.parent.mkdir(parents=True, exist_ok=True)
    step(0.76, "joining the pieces")
    base = out.with_name(out.stem + ".base.mp4")
    # Pieces from different encoders can't be stream-copied together, and GPU pieces end a timestamp tick short
    # (NVENC: 3.233008 s for 97 frames at 30 fps), which a copy-join turns into a not-quite-constant frame rate that
    # phone editors reject. So those are joined with one more (GPU) encode; x264 pieces keep the free copy-join.
    joined = _combine(segs, base, tl.fps, crf, preset, reencode=len(set(made_by)) > 1 or any(m != "cpu" for m in made_by),
                      encoder=encoder)
    scaled = tl.model_copy(deep=True)
    scaled.width, scaled.height = W, H
    if not captions:
        scaled.captions = []
        scaled.items = [i for i in scaled.items if i.kind != "text"]
    ass = write_ass(scaled, out.with_suffix(".ass")) if (scaled.captions or any(i.kind == "text" for i in scaled.items)) else None
    vid = out.with_name(out.stem + ".video.mp4")
    step(0.8, "captions, text and overlays")
    final = _overlay_pass(pa, proj, tl, base, ass, vid, W, H, tl.fps, crf, preset, look, encoder=encoder)
    wav = out.with_suffix(".wav")
    step(0.9, "mixing the sound")
    lufs, tp, sm = mix_audio(pa, proj, tl, wav, stems_dir=(out.parent / f"{out.stem}_stems") if stems else None, music=music)
    run_ffmpeg(["-i", str(vid), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", str(out)], timeout=1800)
    for p in (base, vid):
        p.unlink(missing_ok=True)
    last = final or (joined if joined != "copy" else made_by[-1])     # the encoder of the picture you actually see
    used = [enc.LABEL[n] for n in dict.fromkeys([*made_by, *(x for x in (joined, final) if x and x != "copy")])]
    note = " + ".join(used)
    if any(enc.failed_reason(n) for n in enc.GPU_ORDER):
        note += " — the GPU encoder failed, so the CPU took over: " + "; ".join(
            f"{n}: {enc.failed_reason(n)}" for n in enc.GPU_ORDER if enc.failed_reason(n))
    res = RenderResult(video=out, audio=wav, duration=tl.duration, lufs=lufs, true_peak_db=tp, speech_to_music_db=sm,
                       encoder=last, encoder_note=note)
    if storyboard:
        step(0.97, "a storyboard for the review")
        try:
            res.storyboard = make_storyboard(tl, out, proj.sub("qa") / f"{out.stem}_storyboard.jpg", scale=scale)
        except Exception:
            res.storyboard = None
    return res


def make_storyboard(tl: Timeline, video: Path, dst: Path, *, scale: float = 1.0, max_frames: int = 24) -> Path:
    from ..media.proxy import contact_sheet, grab_frame

    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    picks = v1 if len(v1) <= max_frames else [v1[int(k * len(v1) / max_frames)] for k in range(max_frames)]
    frames, labels = [], []
    tmp = dst.parent / (dst.stem + "_f")
    tmp.mkdir(parents=True, exist_ok=True)
    for k, it in enumerate(picks):
        t = it.rec_in + min(it.rec_dur * 0.55, max(0.2, it.rec_dur - 0.2))
        f = grab_frame(video, t, tmp / f"{k:03d}.jpg", width=360)
        frames.append(f)
        extra = []
        if it.transform and it.transform.zoom > 1.01:
            extra.append(f"z{it.transform.zoom:.2f}")
        if abs(it.speed - 1) > 1e-3:
            extra.append(f"{it.speed:g}x")
        if it.transition_in != "cut":
            extra.append(it.transition_in)
        labels.append(f"{t:5.1f}s {it.role or ''} {' '.join(extra)}".strip())
    return contact_sheet(frames, dst, cols=6 if tl.width > tl.height else 8, width=360, labels=labels)
