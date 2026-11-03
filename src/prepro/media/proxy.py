"""Proxies, audio extraction, frame grabs and streaming frame decode (all via ffmpeg)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from .ffmpeg import FFmpegError, ffmpeg_bin, run_ffmpeg


def extract_audio(src: Path, dst: Path, *, sr: int = 16000, mono: bool = True, start: float | None = None, dur: float | None = None) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = []
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(src)]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-vn", "-ac", "1" if mono else "2", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)]
    run_ffmpeg(args, timeout=1800)
    return dst


def make_proxy(src: Path, dst: Path, *, height: int = 540, fps: float = 30.0, crf: int = 28) -> Path:
    """Constant-frame-rate H.264 proxy (fixes phone VFR) used for fast preview rendering."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale=-2:{height}:flags=bilinear,fps={fps},format=yuv420p"
    run_ffmpeg(["-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-g", str(int(fps)),
                "-c:a", "aac", "-b:a", "96k", "-ar", "48000", str(dst)], timeout=3600)
    return dst


def grab_frame(src: Path, t: float, dst: Path, *, width: int = 480) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(dst)], timeout=120)
    if not dst.exists():
        raise FFmpegError(f"no frame at {t:.2f}s in {src}")
    return dst


def iter_frames(src: Path, *, fps: float = 4.0, width: int = 320, start: float = 0.0, dur: float | None = None,
                gray: bool = False) -> Iterator[tuple[float, np.ndarray]]:
    """Decode frames at ``fps`` scaled to ``width`` → (time, HxWx3 uint8 RGB or HxW gray)."""
    from .probe import probe

    info = probe(src)
    if not info.has_video:
        return
    ds = info.display_size or (info.width or 16, info.height or 9)
    h = int(round(width * ds[1] / ds[0] / 2) * 2) or 2
    pix = "gray" if gray else "rgb24"
    ch = 1 if gray else 3
    args = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(src)]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-vf", f"fps={fps},scale={width}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", pix, "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = width * h * ch
    i = 0
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            arr = np.frombuffer(buf, np.uint8).reshape((h, width) if gray else (h, width, 3))
            yield start + i / fps, arr
            i += 1
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()


def contact_sheet(images: list[Path], dst: Path, *, cols: int = 4, width: int = 384, labels: list[str] | None = None) -> Path:
    """Tile thumbnails into one image (used for vision tagging and storyboards)."""
    from PIL import Image, ImageDraw

    from ..fixtures.visual import font

    thumbs = []
    for p in images:
        im = Image.open(p).convert("RGB")
        im.thumbnail((width, width))
        thumbs.append(im)
    if not thumbs:
        raise ValueError("no images")
    cw = width
    chh = max(t.height for t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows * (chh + 4)), (16, 16, 16))
    d = ImageDraw.Draw(sheet)
    f = font(18)
    for i, t in enumerate(thumbs):
        x, y = (i % cols) * cw, (i // cols) * (chh + 4)
        sheet.paste(t, (x + (cw - t.width) // 2, y))
        if labels:
            d.rectangle([x, y, x + 8 + d.textlength(labels[i], font=f), y + 24], fill=(0, 0, 0))
            d.text((x + 4, y + 2), labels[i], font=f, fill=(255, 255, 255))
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst, quality=88)
    return dst
