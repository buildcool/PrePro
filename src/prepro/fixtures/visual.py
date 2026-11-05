"""Procedural images and video clips with known properties (camera moves, shake, blur, darkness…)."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..media.ffmpeg import ffmpeg_bin, run_ffmpeg

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def font(size: int) -> ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _noise1d(n: int, rng, octaves: int = 5) -> np.ndarray:
    out = np.zeros(n)
    for o in range(octaves):
        pts = 4 * 2**o + 1
        ctrl = rng.random(pts)
        xs = np.linspace(0, pts - 1, n)
        out += np.interp(xs, np.arange(pts), ctrl) / 2**o
    return (out - out.min()) / max(1e-9, out.max() - out.min())


def _grad(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    t = np.linspace(0, 1, h)[:, None, None]
    arr = (np.array(top)[None, None, :] * (1 - t) + np.array(bottom)[None, None, :] * t)
    arr = np.repeat(arr, w, axis=1).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def scenery(kind: str, w: int = 3200, h: int = 1800, seed: int = 0) -> Image.Image:
    """Stylised but recognisable scenes: beach, mountain, city, food, forest, sunset, market, room, cafe."""
    rng = np.random.default_rng(seed)
    if kind == "beach":
        img = _grad(w, h, (110, 170, 235), (235, 245, 255))
        d = ImageDraw.Draw(img)
        d.ellipse([w * 0.72, h * 0.12, w * 0.8, h * 0.26], fill=(255, 236, 160))
        sea_y = int(h * 0.55)
        d.rectangle([0, sea_y, w, int(h * 0.75)], fill=(30, 120, 180))
        for _i in range(60):
            y = sea_y + int(rng.random() * h * 0.2)
            x = int(rng.random() * w)
            d.line([x, y, x + int(rng.random() * 160 + 40), y], fill=(200, 230, 250), width=4)
        d.rectangle([0, int(h * 0.75), w, h], fill=(236, 212, 160))
        for px in (0.12, 0.3, 0.88):
            x0 = int(w * px)
            d.line([x0, int(h * 0.78), x0 + 40, int(h * 0.42)], fill=(80, 55, 30), width=22)
            for a in range(6):
                ang = a * math.pi / 3
                d.line([x0 + 40, int(h * 0.42), x0 + 40 + int(180 * math.cos(ang)), int(h * 0.42 + 90 * math.sin(ang) - 40)], fill=(30, 110, 50), width=18)
    elif kind in ("mountain", "forest"):
        img = _grad(w, h, (120, 160, 210), (220, 230, 240))
        d = ImageDraw.Draw(img)
        cols = [(110, 125, 150), (70, 95, 110), (40, 70, 60)] if kind == "mountain" else [(60, 110, 70), (35, 85, 50), (20, 60, 35)]
        for layer, col in enumerate(cols):
            ridge = _noise1d(w, rng) * h * (0.35 - layer * 0.07) + h * (0.25 + layer * 0.17)
            pts = [(x, int(ridge[x])) for x in range(0, w, 8)] + [(w, h), (0, h)]
            d.polygon(pts, fill=col)
            if kind == "mountain" and layer == 0:
                for x in range(0, w, 8):
                    if ridge[x] < h * 0.33:
                        d.line([x, int(ridge[x]), x, int(ridge[x]) + 30], fill=(245, 245, 250), width=8)
        if kind == "forest":
            for _ in range(140):
                x = int(rng.random() * w)
                base = int(h * (0.7 + rng.random() * 0.3))
                s = int(60 + rng.random() * 120)
                d.polygon([(x, base - 3 * s), (x - s, base), (x + s, base)], fill=(20, int(70 + rng.random() * 60), 30))
    elif kind in ("city", "sunset"):
        top, bot = ((40, 40, 90), (240, 140, 80)) if kind == "sunset" else ((20, 30, 70), (90, 90, 140))
        img = _grad(w, h, top, bot)
        d = ImageDraw.Draw(img)
        if kind == "sunset":
            d.ellipse([w * 0.45, h * 0.5, w * 0.55, h * 0.68], fill=(255, 200, 90))
        x = 0
        while x < w:
            bw = int(80 + rng.random() * 220)
            bh = int(h * (0.25 + rng.random() * 0.45))
            col = tuple(int(c) for c in rng.integers(15, 55, 3))
            d.rectangle([x, h - bh, x + bw, h], fill=col)
            if kind == "city":
                for wy in range(h - bh + 20, h - 20, 46):
                    for wx in range(x + 12, x + bw - 20, 34):
                        if rng.random() > 0.45:
                            d.rectangle([wx, wy, wx + 16, wy + 22], fill=(255, 215, 120))
            x += bw + int(rng.random() * 20)
    elif kind in ("food", "cafe"):
        img = Image.new("RGB", (w, h), (150, 105, 70) if kind == "food" else (215, 200, 180))
        d = ImageDraw.Draw(img)
        for i in range(0, w, 90):
            d.line([i, 0, i, h], fill=(135, 95, 62) if kind == "food" else (205, 190, 170), width=6)
        cx, cy, r = w * 0.5, h * 0.5, h * 0.36
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(245, 245, 240), outline=(220, 220, 215), width=12)
        palette = [(220, 60, 40), (250, 190, 40), (70, 160, 60), (240, 120, 30), (120, 60, 30), (250, 240, 200)]
        for _ in range(55 if kind == "food" else 8):
            a, rr = rng.random() * 2 * math.pi, rng.random() * r * 0.75
            x0, y0 = cx + rr * math.cos(a), cy + rr * math.sin(a)
            s = 25 + rng.random() * 60
            d.ellipse([x0 - s, y0 - s, x0 + s, y0 + s], fill=palette[int(rng.integers(0, len(palette)))])
        if kind == "cafe":
            d.ellipse([cx - r * 0.45, cy - r * 0.45, cx + r * 0.45, cy + r * 0.45], fill=(110, 70, 40))
            d.ellipse([cx - r * 0.2, cy - r * 0.15, cx + r * 0.2, cy + r * 0.15], fill=(235, 215, 190))
    elif kind == "market":
        img = _grad(w, h, (240, 225, 200), (180, 150, 120))
        d = ImageDraw.Draw(img)
        x = 0
        while x < w:
            sw = int(260 + rng.random() * 200)
            col = tuple(int(c) for c in rng.integers(80, 250, 3))
            d.rectangle([x, int(h * 0.3), x + sw, int(h * 0.42)], fill=col)
            for k in range(0, sw, 40):
                d.polygon([(x + k, int(h * 0.42)), (x + k + 40, int(h * 0.42)), (x + k + 20, int(h * 0.47))], fill=col)
            for _ in range(30):
                fx, fy = x + rng.random() * sw, h * (0.6 + rng.random() * 0.3)
                s = 14 + rng.random() * 22
                d.ellipse([fx - s, fy - s, fx + s, fy + s], fill=tuple(int(c) for c in rng.integers(60, 255, 3)))
            x += sw + 30
    elif kind == "room":
        img = Image.new("RGB", (w, h), (232, 222, 210))
        d = ImageDraw.Draw(img)
        d.rectangle([w * 0.1, h * 0.12, w * 0.42, h * 0.55], fill=(170, 210, 240), outline=(250, 250, 250), width=24)
        d.rectangle([0, h * 0.72, w, h], fill=(180, 140, 100))
        d.rectangle([w * 0.55, h * 0.5, w * 0.92, h * 0.58], fill=(120, 85, 60))
        d.ellipse([w * 0.6, h * 0.3, w * 0.7, h * 0.5], fill=(60, 140, 70))
        d.rectangle([w * 0.63, h * 0.45, w * 0.67, h * 0.52], fill=(170, 100, 60))
    else:
        raise ValueError(kind)
    return img.filter(ImageFilter.GaussianBlur(1.2))


def photo(img: Image.Image, out: Path, *, taken: str | None = None, gps: tuple[float, float] | None = None, orientation: int = 1,
          offset: str | None = "+05:30", quality: int = 90) -> Path:
    """Save a JPEG the way a phone does: EXIF capture time (local time + its UTC offset), GPS and an orientation tag.
    With orientation 6/8/3 the pixels are stored sideways (as phones do) and the tag says how to turn them upright."""
    from PIL.TiffImagePlugin import IFDRational

    out.parent.mkdir(parents=True, exist_ok=True)
    stored = {6: Image.Transpose.ROTATE_90, 8: Image.Transpose.ROTATE_270, 3: Image.Transpose.ROTATE_180}.get(orientation)
    pixels = img.transpose(stored) if stored is not None else img
    ex = Image.Exif()
    ex[0x0112] = orientation
    if taken:                                             # "2026:10:10 08:02:00"
        ex[0x0132] = taken
        sub = {36867: taken, 36868: taken}
        if offset:
            sub[36881] = offset
        ex[0x8769] = sub
    if gps:
        def dms(v: float) -> tuple:
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            s = ((v - d) * 60 - m) * 60
            return (IFDRational(d, 1), IFDRational(m, 1), IFDRational(round(s * 100), 100))

        lat, lon = gps
        ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lon >= 0 else "W", 4: dms(lon)}
    pixels.convert("RGB").save(out, "JPEG", quality=quality, exif=ex)
    return out


def photo_face(img: Image.Image, cx: float, cy: float, fw: float, *, skin=(222, 180, 145), hair=(45, 32, 24), top=(60, 70, 110)) -> None:
    """A person drawn for a *photo*, with the cues a face detector learned from real photos (shaded skin, brows, eye
    whites and irises, a nose shadow, lips, ears, a neck, hair framing the forehead): found at ~0.97–1.0 confidence
    even at 14 % of a photo's width, where the flat presenter face is missed."""
    fh = fw * 1.3
    d = ImageDraw.Draw(img)
    d.rectangle([cx - fw * 0.22, cy + fh * 0.35, cx + fw * 0.22, cy + fh * 0.75], fill=tuple(int(c * 0.82) for c in skin))     # neck
    d.rounded_rectangle([cx - fw * 0.95, cy + fh * 0.66, cx + fw * 0.95, cy + fh * 2.6], radius=int(fw * 0.42), fill=top)       # shoulders
    d.ellipse([cx - fw * 0.62, cy - fh * 0.62, cx + fw * 0.62, cy + fh * 0.25], fill=hair)                                    # hair behind
    for sx in (-1, 1):                                                                                                       # ears
        d.ellipse([cx + sx * fw * 0.5 - fw * 0.09, cy - fh * 0.06, cx + sx * fw * 0.5 + fw * 0.09, cy + fh * 0.14],
                  fill=tuple(int(c * 0.9) for c in skin))
    x0, y0, x1, y1 = int(cx - fw / 2), int(cy - fh / 2), int(cx + fw / 2), int(cy + fh / 2)                                   # shaded head
    yy, xx = np.mgrid[y0:y1, x0:x1]
    r = np.sqrt(((xx - cx) / (fw / 2)) ** 2 + ((yy - cy) / (fh / 2)) ** 2)
    arr = np.asarray(img).copy()
    sub = arr[y0:y1, x0:x1]
    patch = (np.array(skin)[None, None, :] * np.clip(1.08 - 0.32 * r ** 2, 0.6, 1.1)[:, :, None]).clip(0, 255).astype(np.uint8)
    sub[r <= 1.0] = patch[r <= 1.0]
    img.paste(Image.fromarray(arr))
    d = ImageDraw.Draw(img)
    d.chord([cx - fw * 0.52, cy - fh * 0.56, cx + fw * 0.52, cy - fh * 0.05], 180, 360, fill=hair)                           # hairline
    s = fw / 300
    for sx in (-1, 1):
        ex, ey = cx + sx * fw * 0.2, cy - fh * 0.02
        d.line([ex - 40 * s, ey - 34 * s, ex, ey - 44 * s, ex + 40 * s, ey - 36 * s], fill=(40, 28, 20), width=max(2, int(12 * s)))
        d.ellipse([ex - 34 * s, ey - 15 * s, ex + 34 * s, ey + 15 * s], fill=(245, 242, 238))
        d.ellipse([ex - 15 * s, ey - 15 * s, ex + 15 * s, ey + 15 * s], fill=(85, 55, 35))
        d.ellipse([ex - 7 * s, ey - 7 * s, ex + 7 * s, ey + 7 * s], fill=(15, 10, 8))
        d.arc([ex - 36 * s, ey - 18 * s, ex + 36 * s, ey + 14 * s], 190, 350, fill=(60, 40, 30), width=max(1, int(5 * s)))
    d.line([cx + 6 * s, cy, cx + 14 * s, cy + fh * 0.17], fill=tuple(int(c * 0.72) for c in skin), width=max(2, int(9 * s)))
    for sx in (-1, 1):
        d.ellipse([cx + sx * 20 * s - 9 * s, cy + fh * 0.19 - 6 * s, cx + sx * 20 * s + 9 * s, cy + fh * 0.19 + 6 * s],
                  fill=tuple(int(c * 0.55) for c in skin))
    my = cy + fh * 0.31
    d.ellipse([cx - 52 * s, my - 14 * s, cx + 52 * s, my + 16 * s], fill=(170, 80, 80))
    d.line([cx - 50 * s, my, cx + 50 * s, my], fill=(110, 45, 50), width=max(1, int(5 * s)))


def portrait(kind: str, *, size=(1500, 2000), seed: int = 0, face_video: Path | None = None, at: float = 0.5,
             face_frac: float = 0.3) -> Image.Image:
    """A photo of someone in a place: a frame of the real face video when there is one (a real person), else the
    scenery with a drawn person standing in it (face centre at x = `at`)."""
    w, h = size
    if face_video and Path(face_video).exists():
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "f.png"
            run_ffmpeg(["-ss", f"{1.0 + seed % 5}", "-i", str(face_video), "-frames:v", "1", str(png)], timeout=120)
            fr = Image.open(png).convert("RGB")
            fw, fh = fr.size
            cw = min(fw, int(fh * w / h))
            left = int(min(max(fw * at - cw / 2, 0), fw - cw))
            return fr.crop((left, 0, left + cw, fh)).resize((w, h), Image.Resampling.LANCZOS)
    img = scenery(kind, w=w, h=h, seed=seed)
    photo_face(img, w * at, h * 0.4, w * face_frac)
    return img.filter(ImageFilter.GaussianBlur(0.8))


def group_photo(kind: str, *, n: int = 3, size=(2000, 1500), seed: int = 0) -> Image.Image:
    """Friends in a row across a landscape photo: faces spread over most of the width (a filled 9:16 crop would cut
    the people at the sides out)."""
    w, h = size
    img = scenery(kind, w=w, h=h, seed=seed)
    looks = [((222, 180, 145), (45, 32, 24), (60, 70, 110)), ((165, 118, 85), (25, 18, 14), (150, 45, 55)),
             ((238, 205, 175), (120, 80, 40), (45, 110, 75))]
    for k in range(n):
        skin, hair, top = looks[k % len(looks)]
        photo_face(img, w * (0.2 + 0.6 * k / max(1, n - 1)), h * 0.42, w * 0.14, skin=skin, hair=hair, top=top)
    return img.filter(ImageFilter.GaussianBlur(0.8))


def _moves(move: str, dur: float, out_w: int, out_h: int) -> str:
    D = max(0.1, dur)
    # scale the 16:9 scenery so it covers the output frame with room to move (works for 9:16 too)
    base = f"scale={int(out_w * 1.6)}:-2" if out_w >= out_h else f"scale=-2:{int(out_h * 1.25)}"
    if move == "pan_right":
        return f"{base},crop={out_w}:{out_h}:x='(iw-ow)*t/{D}':y='(ih-oh)/2'"
    if move == "pan_left":
        return f"{base},crop={out_w}:{out_h}:x='(iw-ow)*(1-t/{D})':y='(ih-oh)/2'"
    if move == "tilt_up":
        return f"{base},crop={out_w}:{out_h}:x='(iw-ow)/2':y='(ih-oh)*(1-t/{D})'"
    if move == "shaky":
        return f"{base},crop={out_w}:{out_h}:x='(iw-ow)/2+28*sin(t*17)+19*sin(t*41)':y='(ih-oh)/2+24*sin(t*23)+15*cos(t*37)'"
    if move == "static":
        return f"{base},crop={out_w}:{out_h}:x='(iw-ow)/2':y='(ih-oh)/2'"
    if move == "whip_out":
        a = max(0.1, D - 0.4)
        return (f"{base},crop={out_w}:{out_h}:x='if(lt(t,{a}),(iw-ow)*0.3*t/{a},(iw-ow)*(0.3+0.7*(t-{a})/0.4))':y='(ih-oh)/2',"
                f"boxblur=luma_radius=22:luma_power=2:enable='gte(t,{a})'")
    if move == "push_in":
        pre = f"scale={out_w * 2}:-2" if out_w >= out_h else f"scale=-2:{out_h * 2},crop=ih*{out_w}/{out_h}:ih"
        return f"{pre},zoompan=z='min(1+0.25*on/({D}*30),1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={out_w}x{out_h}:fps=30"
    raise ValueError(move)


def still_clip(img: Image.Image, out: Path, *, dur: float, move: str = "static", size=(1280, 720), fps: int = 30,
               blur: float = 0.0, dark: bool = False, overexposed: bool = False, audio: Path | None = None,
               creation_time: str | None = None, location: str | None = None, vertical: bool = False) -> Path:
    """Render a moving-camera clip from a still image (+ optional audio and metadata)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = (size[1], size[0]) if vertical else size
    src = out.with_suffix(".src.png")
    img.save(src)
    vf = _moves(move, dur, w, h)
    if blur:
        vf += f",gblur=sigma={blur}"
    if dark:
        vf += ",eq=brightness=-0.32:saturation=0.7:gamma=0.75"
    if overexposed:
        vf += ",eq=brightness=0.35:contrast=0.7"
    vf += ",noise=alls=4:allf=t,format=yuv420p"
    args = ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(src)]
    if audio:
        args += ["-i", str(audio)]
    args += ["-vf", vf, "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "24"]
    if audio:
        args += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        args += ["-an"]
    if creation_time:
        args += ["-metadata", f"creation_time={creation_time}"]
    if location:
        args += ["-metadata", f"location={location}"]
    args += ["-t", f"{dur:.3f}", str(out)]
    run_ffmpeg(args, timeout=600)
    src.unlink(missing_ok=True)
    return out


def action_clip(img: Image.Image, out: Path, *, dur: float = 4.0, fps: int = 60, size=(1280, 720),
                creation_time: str | None = None, location: str | None = None) -> tuple[Path, float]:
    """High-fps clip with a 'jump' motion peak (true slow-mo candidate). Returns (path, peak_time)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    src = out.with_suffix(".src.png")
    img.save(src)
    w, h = size
    peak = dur * 0.5
    # object arcs up and lands; fastest around take-off/landing, apex at `peak`
    ov = (f"[0:v]scale={w}:{h},format=rgba[bg];color=c=0xE04040:s=120x120:d={dur}[ball];"
          f"[bg][ball]overlay=x='(W-w)*t/{dur}':y='H-h-40-max(0,(1-pow((t-{peak})/{peak*0.8},2)))*{h*0.55}':shortest=1,format=yuv420p")
    args = ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(src), "-filter_complex", ov,
            "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-an"]
    if creation_time:
        args += ["-metadata", f"creation_time={creation_time}"]
    if location:
        args += ["-metadata", f"location={location}"]
    run_ffmpeg(args + ["-t", f"{dur:.3f}", str(out)], timeout=600)
    src.unlink(missing_ok=True)
    return out, peak


def presenter_clip(audio_wav: Path, out: Path, *, size=(1280, 720), fps: int = 30, bg=(60, 90, 140), seed: int = 0,
                   face_video: Path | None = None, creation_time: str | None = None, location: str | None = None,
                   vertical: bool = False) -> Path:
    """A-roll: a real face video looped under the speech (if given) or a drawn presenter whose mouth follows the audio."""
    import soundfile as sf

    out.parent.mkdir(parents=True, exist_ok=True)
    y, sr = sf.read(str(audio_wav), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    dur = len(y) / sr
    w, h = (size[1], size[0]) if vertical else size
    meta = []
    if creation_time:
        meta += ["-metadata", f"creation_time={creation_time}"]
    if location:
        meta += ["-metadata", f"location={location}"]
    if face_video and face_video.exists():
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=yuv420p"
        run_ffmpeg(["-stream_loop", "-1", "-i", str(face_video), "-i", str(audio_wav), "-map", "0:v", "-map", "1:a",
                    "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "128k",
                    "-t", f"{dur:.3f}", *meta, str(out)], timeout=900)
        return out
    # drawn presenter
    hop = sr // fps
    env = np.array([float(np.sqrt(np.mean(y[i * hop:(i + 1) * hop] ** 2) + 1e-12)) for i in range(int(dur * fps))])
    env = env / max(1e-6, float(np.percentile(env, 95)))
    proc = subprocess.Popen(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
         "-r", str(fps), "-i", "-", "-i", str(audio_wav), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", *meta, str(out)],
        stdin=subprocess.PIPE,
    )
    base = _room(w, h, bg, seed)
    fw = int(min(w, h) * 0.42)
    cx, cy = w // 2, int(h * 0.48)
    for i in range(len(env)):
        fr = base.copy()
        _draw_person(ImageDraw.Draw(fr), cx, cy, fw, h, mouth=min(1.0, env[i]), bob=int(6 * math.sin(i / fps * 2.1)),
                     blink=(i % 97) < 3)
        proc.stdin.write(fr.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("presenter render failed")
    return out


def _room(w: int, h: int, bg, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = Image.new("RGB", (w, h), bg)
    bd = ImageDraw.Draw(base)
    for _ in range(12):
        x, yy = rng.random() * w, rng.random() * h * 0.6
        bd.rectangle([x, yy, x + 120, yy + 80], fill=tuple(int(c * 0.8) for c in bg))
    return base


def _draw_person(d: ImageDraw.ImageDraw, cx: float, cy: float, fw: float, h: int, *, mouth: float, bob: int, blink: bool,
                 skin=(225, 185, 150), hair=(50, 35, 25), shirt=(40, 40, 50)) -> None:
    """A drawn presenter: head, hair, eyes (with blinks) and a mouth that opens with `mouth` (0..1)."""
    s = fw / 302.0                                   # features were drawn for a 302 px face
    d.rectangle([cx - fw * 0.7, cy + fw * 0.45, cx + fw * 0.7, h], fill=shirt)                                  # shoulders
    d.ellipse([cx - fw / 2, cy - fw / 2 + bob, cx + fw / 2, cy + fw * 0.6 + bob], fill=skin)                   # head
    d.ellipse([cx - fw / 2, cy - fw / 2 - 20 * s + bob, cx + fw / 2, cy - fw * 0.05 + bob], fill=hair)         # hair
    for ex in (-0.18, 0.18):
        ey = cy + fw * 0.08 + bob
        if blink:
            d.line([cx + ex * fw - 18 * s, ey, cx + ex * fw + 18 * s, ey], fill=(30, 30, 30), width=max(2, int(5 * s)))
        else:
            d.ellipse([cx + ex * fw - 16 * s, ey - 12 * s, cx + ex * fw + 16 * s, ey + 12 * s], fill=(255, 255, 255))
            d.ellipse([cx + ex * fw - 7 * s, ey - 7 * s, cx + ex * fw + 7 * s, ey + 7 * s], fill=(40, 30, 20))
    mh = (6 + 46 * mouth) * s
    d.ellipse([cx - fw * 0.13, cy + fw * 0.33 - mh / 2 + bob, cx + fw * 0.13, cy + fw * 0.33 + mh / 2 + bob], fill=(120, 40, 50))


def duo_clip(audio_wav: Path, out: Path, envelopes: tuple[np.ndarray, np.ndarray], *, size=(1280, 720), fps: int = 30,
             seats=(0.3, 0.7), creation_time: str | None = None, seed: int = 0) -> Path:
    """A podcast two-shot: two drawn people side by side, each mouth moving only with that person's own voice
    (``envelopes`` at `fps`). Both bob and blink on their own rhythm, as people do while listening."""
    import soundfile as sf

    out.parent.mkdir(parents=True, exist_ok=True)
    y, sr = sf.read(str(audio_wav), dtype="float32")
    n = int(len(y) / sr * fps)
    w, h = size
    meta = ["-metadata", f"creation_time={creation_time}"] if creation_time else []
    proc = subprocess.Popen(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
         "-r", str(fps), "-i", "-", "-i", str(audio_wav), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", *meta, str(out)],
        stdin=subprocess.PIPE,
    )
    base = _room(w, h, (70, 80, 100), seed)
    fw = int(h * 0.30)
    looks = [dict(skin=(225, 185, 150), hair=(50, 35, 25), shirt=(40, 40, 50)),
             dict(skin=(190, 140, 105), hair=(25, 20, 18), shirt=(120, 50, 50))]
    for i in range(n):
        fr = base.copy()
        d = ImageDraw.Draw(fr)
        for k, sx in enumerate(seats):
            env = envelopes[k]
            m = min(1.0, float(env[i])) if i < len(env) else 0.0
            _draw_person(d, sx * w, h * 0.50, fw, h, mouth=m, bob=int(4 * math.sin(i / fps * (1.7 + 0.6 * k) + k)),
                         blink=((i + 41 * k) % (89 + 12 * k)) < 3, **looks[k % 2])
        proc.stdin.write(fr.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("duo render failed")
    return out


def screen_clip(out: Path, *, dur: float, audio: Path | None = None, facecam: Path | None = None, size=(1280, 720),
                fps: int = 30, events: list[tuple[float, str]] | None = None) -> Path:
    """Gameplay-like screen capture: moving synthetic world + HUD + optional facecam PiP + event banners."""
    from ..config import assets_dir

    w, h = size
    events = events or []
    font = (assets_dir() / "fonts" / "Anton-Regular.ttf").as_posix().replace(":", "\\:")     # bundled: same look on every OS
    hud = (f"drawtext=fontfile='{font}':text='HP 100  AMMO 30':x=30:y=h-60:"
           "fontsize=34:fontcolor=white:box=1:boxcolor=black@0.4")
    banners = ",".join(
        f"drawtext=fontfile='{font}':text='{txt}':x=(w-tw)/2:y=h*0.18:"
        f"fontsize=72:fontcolor=yellow:borderw=4:enable='between(t,{t0},{t0 + 1.6})'" for t0, txt in events
    )
    chain = f"[0:v]scale={w}:{h},{hud}" + ("," + banners if banners else "") + "[g]"
    inputs = ["-f", "lavfi", "-t", f"{dur}", "-i", f"mandelbrot=s={w}x{h}:rate={fps}"]
    if facecam and facecam.exists():
        inputs += ["-stream_loop", "-1", "-i", str(facecam)]
        chain += ";[1:v]scale=320:-2,format=yuv420p[fc];[g][fc]overlay=W-w-24:24,format=yuv420p[v]"
    else:
        chain += ";[g]drawbox=x=iw-344:y=24:w=320:h=180:color=0x3060A0:t=fill,format=yuv420p[v]"   # top-right (w = the box's width)
    args = inputs[:]
    a_idx = 1 + (1 if facecam and facecam.exists() else 0)
    if audio:
        args += ["-i", str(audio)]
    args += ["-filter_complex", chain, "-map", "[v]"]
    if audio:
        args += ["-map", f"{a_idx}:a", "-c:a", "aac", "-b:a", "128k"]
    args += ["-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-t", f"{dur}", str(out)]
    run_ffmpeg(args, timeout=900)
    return out


def meme_image(text: str, out: Path, *, size=(800, 800), bg=(250, 220, 60), emoji: str = "o_O") -> Path:
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    f = font(int(size[0] * 0.14))
    tw = d.textlength(text, font=f)
    d.text(((size[0] - tw) / 2, size[1] * 0.68), text, font=f, fill=(20, 20, 20), stroke_width=6, stroke_fill=(255, 255, 255))
    fe = font(int(size[0] * 0.3))
    ew = d.textlength(emoji, font=fe)
    d.text(((size[0] - ew) / 2, size[1] * 0.15), emoji, font=fe, fill=(30, 30, 30))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def meme_gif(text: str, out: Path, *, frames: int = 12, size=(480, 480)) -> Path:
    imgs = []
    for i in range(frames):
        s = 1 + 0.25 * math.sin(i / frames * 2 * math.pi)
        img = Image.new("RGB", size, (30, 30, 30))
        d = ImageDraw.Draw(img)
        f = font(int(size[0] * 0.12 * s))
        tw = d.textlength(text, font=f)
        d.text(((size[0] - tw) / 2, size[1] * 0.42), text, font=f, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
        imgs.append(img)
    out.parent.mkdir(parents=True, exist_ok=True)
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=80, loop=0)
    return out


def meme_video(text: str, out: Path, *, audio: Path | None = None, dur: float = 1.6, size=(720, 720)) -> Path:
    img = Image.new("RGB", (size[0] * 2, size[1] * 2), (15, 15, 15))
    d = ImageDraw.Draw(img)
    f = font(int(size[0] * 0.22))
    tw = d.textlength(text, font=f)
    d.text(((img.width - tw) / 2, img.height * 0.4), text, font=f, fill=(255, 60, 60), stroke_width=8, stroke_fill=(255, 255, 255))
    src = out.with_suffix(".src.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(src)
    vf = f"zoompan=z='min(1+0.6*on/({dur}*30),1.6)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={size[0]}x{size[1]}:fps=30,format=yuv420p"
    args = ["-loop", "1", "-framerate", "30", "-t", f"{dur}", "-i", str(src)]
    if audio:
        args += ["-i", str(audio)]
    args += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24"]
    args += ["-c:a", "aac", "-shortest"] if audio else ["-an"]
    run_ffmpeg(args + ["-t", f"{dur}", str(out)], timeout=300)
    src.unlink(missing_ok=True)
    return out
