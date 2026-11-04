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
from ..schema.timeline import Item, Timeline
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
            cw0, ch0 = _even(cw / max(z0, 1.0) * 0.999), _even(ch / max(z0, 1.0) * 0.999)
            zexpr = f"({z0}+({z1 - z0})*t/{D:.3f})/{z0}"
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


def _segment(pa: ProjectAnalysis, proj: Project, it: Item, W: int, H: int, fps: float, *, crf: int, preset: str, look: Path | None,
             cache: Path, encoder: enc.Encoder = enc.CPU) -> tuple[Path, str]:
    """One V1 item as a clip at the timeline's size and frame rate. Returns (file, encoder name). Cached per item;
    the encoder is part of the file name so pieces from different encoders are never stream-copied together."""
    key = hashlib.sha1(json.dumps([it.model_dump(exclude={"id", "rec_in", "suggestion_ids", "section", "role", "note"}), W, H, fps, crf, preset,
                                   str(look)], sort_keys=True, default=str).encode()).hexdigest()[:16]
    want = encoder.name
    # "auto" reuses a piece from any encoder; a forced encoder (e.g. cpu) only its own
    for name in dict.fromkeys((want, "cpu", *enc.GPU_ORDER) if enc.preference() == "auto" else (want,)):
        hit = cache / f"seg_{key}_{name}.mp4"
        if hit.exists() and hit.stat().st_size > 1000:
            return hit, name
    a = pa.asset(it.asset_id)
    src = proj.path(a.path)
    dur = it.rec_dur
    nframes = max(1, int(round(dur * fps)))
    lut = f",lut3d=file='{ff_escape(look)}'" if look else ""
    tail = f",fps={fps},format=yuv420p,setsar=1{lut}"
    if it.kind == "image":
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
    mix = stems["dialogue"] + stems["music"] + stems["sfx"]
    mix = mix[: int(total * SR)]
    lufs = None
    try:
        import pyloudnorm as pyln

        meter = pyln.Meter(SR)
        lufs = float(meter.integrated_loudness(mix.astype(np.float64)))
        if np.isfinite(lufs):
            gain = 10 ** ((target_lufs - lufs) / 20)
            mix *= gain
            for k in stems:
                stems[k] *= gain
    except Exception:
        pass
    mix = _limit(mix, 10 ** (true_peak / 20))
    tp = float(20 * np.log10(max(1e-9, _true_peak(mix))))
    out_lufs = None
    try:
        import pyloudnorm as pyln

        out_lufs = round(float(pyln.Meter(SR).integrated_loudness(mix.astype(np.float64))), 2)
    except Exception:
        pass
    # speech-to-music ratio while someone talks
    sm = None
    d, m = stems["dialogue"][: len(mix)], stems["music"][: len(mix)]
    hop = SR // 10
    k = len(mix) // hop
    if k > 5:
        dr = np.sqrt((d[: k * hop].reshape(k, hop, 2) ** 2).mean(axis=(1, 2)))
        mr = np.sqrt((m[: k * hop].reshape(k, hop, 2) ** 2).mean(axis=(1, 2)))
        talk = dr > 10 ** (-40 / 20)
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
    """Look-ahead peak limiter (5 ms) with smooth release; keeps true peak under the ceiling."""
    from scipy.ndimage import maximum_filter1d

    c = ceiling * 0.97
    peak = np.max(np.abs(x), axis=1)
    if peak.max() <= c:
        return x
    look = int(0.005 * SR)
    env = maximum_filter1d(peak, size=2 * look + 1)
    gain = np.minimum(1.0, c / np.maximum(env, 1e-9))
    rel = np.exp(-1.0 / (0.08 * SR))
    g = gain.copy()
    for i in range(1, len(g)):   # release smoothing (attack is instant thanks to look-ahead)
        if g[i] > g[i - 1]:
            g[i] = g[i - 1] * rel + g[i] * (1 - rel)
    return (x * g[:, None]).astype(np.float32)


# ------------------------------------------------------------------ main
def render(tl: Timeline, pa: ProjectAnalysis, out: Path, *, quality: str = "preview", preview_height: int = 540, project_root=None,
           stems: bool = False, storyboard: bool = True, captions: bool = True, music: bool = True) -> RenderResult:
    proj = Project(project_root or pa.root)
    short = preview_height if quality == "preview" else min(tl.width, tl.height)
    scale = short / min(tl.width, tl.height)
    W, H = _even(tl.width * scale), _even(tl.height * scale)
    crf, preset = (30, "veryfast") if quality == "preview" else (19, "medium")
    look = lut_path(tl.look) if tl.look else None
    work = proj.sub(f"renders/work_{quality}")
    encoder = enc.choose(min(W, H))                  # the GPU when it is measurably faster here, else the CPU
    segs, made_by = [], []
    for it in sorted((i for i in tl.items if i.track == "V1" and i.kind in ("video", "image")), key=lambda i: i.rec_in):
        path, by = _segment(pa, proj, it, W, H, tl.fps, crf=crf if quality == "preview" else 16, preset=preset, look=look, cache=work,
                            encoder=encoder)
        segs.append((it, path))
        made_by.append(by)
    if not segs:
        raise ValueError("timeline has no picture")
    out.parent.mkdir(parents=True, exist_ok=True)
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
    final = _overlay_pass(pa, proj, tl, base, ass, vid, W, H, tl.fps, crf, preset, look, encoder=encoder)
    wav = out.with_suffix(".wav")
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
