"""Per-clip visual analysis on a low-res frame stream: shots, quality, motion/camera move, whips, faces,
action peaks, best windows, keyframes + perceptual hash."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..media.proxy import grab_frame, iter_frames
from ..schema.analysis import FaceBox, Shot, Window

FPS = 4.0          # analysis sampling rate
WIDTH = 320        # analysis width (pixels)


@dataclass
class FrameStats:
    t: float
    sharp: float
    bright: float
    contrast: float
    sat: float
    rgb: tuple[float, float, float]
    hist: np.ndarray
    dx: float = 0.0          # global motion (fraction of width per second, + = content moves right)
    dy: float = 0.0
    div: float = 0.0         # radial flow (zoom in > 0)
    mag: float = 0.0         # mean flow magnitude (fraction of width per second)
    local: float = 0.0       # residual (subject) motion
    diff: float = 0.0        # mean abs frame difference (0..1)
    faces: list[FaceBox] = field(default_factory=list)


class FaceDetector:
    def __init__(self):
        from ..config import ensure_model

        paths = ensure_model("face_res10")
        self.net = cv2.dnn.readNetFromCaffe(str(paths[0]), str(paths[1])) if paths else None

    def __call__(self, rgb: np.ndarray, t: float, conf: float = 0.6) -> list[FaceBox]:
        if self.net is None:
            return []
        h, w = rgb.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(rgb[:, :, ::-1], (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0))
        self.net.setInput(blob)
        det = self.net.forward()
        out = []
        for i in range(det.shape[2]):
            c = float(det[0, 0, i, 2])
            if c < conf:
                continue
            x0, y0, x1, y1 = (det[0, 0, i, 3:7]).tolist()
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(1, x1), min(1, y1)
            if x1 - x0 < 0.03 or y1 - y0 < 0.03:
                continue
            out.append(FaceBox(t=round(t, 2), x=(x0 + x1) / 2, y=(y0 + y1) / 2, w=x1 - x0, h=y1 - y0, conf=round(c, 3)))
        return out


_FACE: FaceDetector | None = None


def face_detector() -> FaceDetector:
    global _FACE
    if _FACE is None:
        _FACE = FaceDetector()
    return _FACE


def _stats(t: float, rgb: np.ndarray) -> FrameStats:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    m = rgb.reshape(-1, 3).mean(axis=0) / 255.0
    return FrameStats(
        t=t, sharp=float(cv2.Laplacian(gray, cv2.CV_64F).var()), bright=float(gray.mean() / 255.0),
        contrast=float(gray.std() / 255.0), sat=float(hsv[:, :, 1].mean() / 255.0),
        rgb=(float(m[0]), float(m[1]), float(m[2])), hist=hist,
    )


def _flow(prev: np.ndarray, cur: np.ndarray, fs: FrameStats) -> None:
    a = cv2.resize(prev, (160, int(160 * prev.shape[0] / prev.shape[1])), interpolation=cv2.INTER_AREA)
    b = cv2.resize(cur, (160, a.shape[0]), interpolation=cv2.INTER_AREA)
    flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    fx, fy = flow[..., 0], flow[..., 1]
    w = a.shape[1]
    gdx, gdy = float(np.median(fx)), float(np.median(fy))
    hh, ww = a.shape
    ys, xs = np.mgrid[0:hh, 0:ww]
    rx, ry = xs - ww / 2, ys - hh / 2
    rn = np.sqrt(rx**2 + ry**2) + 1e-6
    div = float(np.mean((fx * rx + fy * ry) / rn))
    mag = np.sqrt(fx**2 + fy**2)
    resid = np.sqrt((fx - gdx) ** 2 + (fy - gdy) ** 2)
    k = FPS / w  # px/frame-step → fraction of width per second
    fs.dx, fs.dy, fs.div = gdx * k, gdy * k, div * k
    fs.mag, fs.local = float(mag.mean() * k), float(np.percentile(resid, 99.5) * k)
    ad = np.abs(b.astype(np.float32) - a.astype(np.float32)) / 255.0
    fs.diff = float(ad.mean())
    # small fast subjects (a jump, a splash) defeat optical flow: use the localized change too
    fs.local = max(fs.local, float(np.percentile(ad, 99.5)) * 2.0 if fs.diff < 0.06 else 0.0)


def _cuts(stats: list[FrameStats], thr: float = 0.55) -> list[int]:
    cuts = [0]
    for i in range(1, len(stats)):
        d = cv2.compareHist(stats[i - 1].hist.astype(np.float32), stats[i].hist.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
        jump = abs(stats[i].bright - stats[i - 1].bright)
        if (d > thr or (d > 0.4 and jump > 0.15)) and (i - cuts[-1]) / FPS >= 1.0 and stats[i].mag < 0.8:
            cuts.append(i)
    return cuts


def _camera_move(fr: list[FrameStats]) -> tuple[str, float]:
    if len(fr) < 3:
        return "static", 0.0
    dx = np.array([f.dx for f in fr[1:]])
    dy = np.array([f.dy for f in fr[1:]])
    dv = np.array([f.div for f in fr[1:]])
    # jitter: high-frequency part of the global motion
    jitter = float(np.sqrt(np.mean(np.diff(dx) ** 2 + np.diff(dy) ** 2))) if len(dx) > 2 else 0.0
    shake = min(1.0, jitter / 0.08)
    mdx, mdy, mdv = float(np.median(dx)), float(np.median(dy)), float(np.median(dv))
    sustained = lambda v, s: np.mean(np.sign(v) == np.sign(s)) > 0.7  # noqa: E731
    move = "static"
    if abs(mdx) > 0.03 and sustained(dx, mdx):
        move = "pan_right" if mdx < 0 else "pan_left"     # content moves left → camera pans right
    elif abs(mdy) > 0.03 and sustained(dy, mdy):
        move = "tilt_up" if mdy > 0 else "tilt_down"
    elif abs(mdv) > 0.012 and sustained(dv, mdv):
        move = "push_in" if mdv > 0 else "pull_out"
    if shake > 0.45 and move == "static":
        move = "handheld"
    return move, round(shake, 3)


def _whips(fr: list[FrameStats]) -> tuple[bool, bool]:
    if len(fr) < 6:
        return False, False
    mags = np.array([f.mag for f in fr])
    diffs = np.array([f.diff for f in fr])
    sharp = np.array([f.sharp for f in fr])
    med_m, med_s, med_d = float(np.median(mags)) + 1e-6, float(np.median(sharp)) + 1e-6, float(np.median(diffs)) + 1e-6
    k = max(2, int(0.6 * FPS))

    def burst(idx):
        return any(sharp[i] < 0.5 * med_s and (mags[i] > max(3 * med_m, 0.3) or diffs[i] > max(3 * med_d, 0.04)) for i in idx)

    return burst(range(0, k)), burst(range(len(fr) - k, len(fr)))


def _best_windows(fr: list[FrameStats], t0: float, t1: float, med_sharp: float) -> list[Window]:
    if t1 - t0 < 1.5:
        return [Window(t0=t0, t1=t1, score=0.5, why="short shot")]
    per = []
    for f in fr:
        q = min(1.0, f.sharp / (med_sharp + 1e-6)) * 0.4
        q += (1 - abs(f.bright - 0.5) * 2) * 0.2
        q += min(1.0, f.local / 0.25) * 0.25 if f.local < 0.8 else 0.1
        q += 0.15 if f.faces else 0.0
        q -= min(0.3, abs(f.mag) * 0.2) if f.mag > 0.8 else 0.0
        per.append((f.t, q))
    best: list[Window] = []
    for wl in (3.0, 4.0):
        if t1 - t0 < wl:
            continue
        for i in range(len(per)):
            a = per[i][0]
            b = a + wl
            if b > t1:
                break
            vals = [q for t, q in per if a <= t < b]
            if vals:
                best.append(Window(t0=round(a, 2), t1=round(b, 2), score=round(float(np.mean(vals)), 3), why=f"{wl:.0f}s steady/interesting"))
    best.sort(key=lambda w: -w.score)
    picked: list[Window] = []
    for w in best:
        if all(w.t1 <= p.t0 or w.t0 >= p.t1 for p in picked):
            picked.append(w)
        if len(picked) == 3:
            break
    return picked or [Window(t0=t0, t1=t1, score=0.5, why="whole shot")]


def _peaks(fr: list[FrameStats]) -> list[float]:
    """Moments of strongest subject motion (slow-mo / punch-in candidates)."""
    if len(fr) < 5:
        return []
    loc = np.array([f.local for f in fr])
    glob = float(np.median([f.mag for f in fr]))
    med = float(np.median(loc))
    out = []
    for i in range(1, len(loc) - 1):
        if loc[i] >= loc[i - 1] and loc[i] >= loc[i + 1] and loc[i] > max(1.4 * med, 0.15):
            out.append((loc[i], fr[i].t))
    if not out and med > 0.3 and glob < 0.1:
        # sustained subject action with a steady camera: take the strongest moment in the middle 80 %
        a, b = int(len(loc) * 0.1), max(int(len(loc) * 0.9), int(len(loc) * 0.1) + 1)
        j = a + int(np.argmax(loc[a:b]))
        out.append((loc[j], fr[j].t))
    out.sort(reverse=True)
    return [round(t, 2) for _, t in out[:2]]


def analyse_video(asset_id: str, src: Path, frames_dir: Path, *, duration: float, fps: float | None, faces: bool = True) -> tuple[list[Shot], dict]:
    stats: list[FrameStats] = []
    prev_gray = None
    det = face_detector() if faces else None
    acc_static = None
    for i, (t, rgb) in enumerate(iter_frames(src, fps=FPS, width=WIDTH)):
        fs = _stats(t, rgb)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        if prev_gray is not None:
            _flow(prev_gray, gray, fs)
            diff = (np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)) < 3)
            acc_static = diff if acc_static is None else (acc_static & diff)
        if det is not None and i % int(FPS) == 0:
            fs.faces = det(rgb, t)
        stats.append(fs)
        prev_gray = gray
    if not stats:
        return [], {"error": "no frames decoded"}
    static_ratio = float(acc_static.mean()) if acc_static is not None and len(stats) > 8 else 0.0
    hud = 0.0
    if acc_static is not None and prev_gray is not None and len(stats) > 8 and static_ratio > 0:
        edges = cv2.Canny(prev_gray, 60, 160) > 0
        hud = float((acc_static & edges).sum() / max(1, acc_static.sum()))
    sharp_all = np.array([s.sharp for s in stats])
    med_sharp = float(np.median(sharp_all))
    cuts = _cuts(stats) + [len(stats)]
    shots: list[Shot] = []
    for k in range(len(cuts) - 1):
        fr = stats[cuts[k]: cuts[k + 1]]
        t0 = 0.0 if k == 0 else fr[0].t
        t1 = duration if k == len(cuts) - 2 else stats[cuts[k + 1]].t
        if t1 - t0 < 0.3:
            continue
        sid = f"{asset_id}.k{len(shots)}"
        move, shake = _camera_move(fr)
        win, wout = _whips(fr)
        sharp = float(np.median([f.sharp for f in fr]))
        bright = float(np.mean([f.bright for f in fr]))
        contrast = float(np.mean([f.contrast for f in fr]))
        sat = float(np.mean([f.sat for f in fr]))
        mag = float(np.mean([f.mag for f in fr]))
        face_frames = [f for f in fr if f.faces]
        sampled = [f for i, f in enumerate(fr) if (cuts[k] + i) % int(FPS) == 0] or fr
        face_ratio = len([f for f in sampled if f.faces]) / max(1, len(sampled))
        rgb = tuple(float(np.mean([f.rgb[c] for f in fr])) for c in range(3))
        flags = []
        if bright < 0.17:
            flags.append("dark")
        if bright > 0.86 and contrast < 0.12:
            flags.append("overexposed")
        if shake > 0.55:
            flags.append("shaky")
        if (bright < 0.12 and mag > 0.6) or (contrast < 0.04 and mag > 0.5):
            flags.append("pocket")
        q = 1.0
        q -= 0.35 * ("dark" in flags) + 0.3 * ("overexposed" in flags) + 0.35 * min(1.0, shake) + 0.5 * ("pocket" in flags)
        shots.append(Shot(
            id=sid, asset_id=asset_id, t0=round(t0, 3), t1=round(t1, 3), sharpness=round(sharp, 2), brightness=round(bright, 3),
            contrast=round(contrast, 3), saturation=round(sat, 3), shake=shake, motion=round(mag, 4), camera_move=move,
            whip_in=win, whip_out=wout, faces=[b for f in face_frames for b in f.faces][:24], face_ratio=round(face_ratio, 3),
            flags=flags, quality=round(max(0.0, q), 3), color=rgb,
            best=_best_windows(fr, t0, t1, med_sharp), action_peaks=_peaks(fr),
            static_ratio=round(static_ratio, 3), hud=round(hud, 3),
        ))
    # blur is relative (sharpness depends on content): flag shots far below the clip/project norm later too
    for s in shots:
        if s.sharpness < 10:
            s.flags.append("blurry")
            s.quality = round(max(0.0, s.quality - 0.4), 3)
    # keyframes + phash
    for s in shots:
        kfs = []
        for j, frac in enumerate((0.15, 0.5, 0.85)):
            t = s.t0 + (s.t1 - s.t0) * frac
            dst = frames_dir / f"{s.id}_{j}.jpg"
            try:
                if not dst.exists():
                    grab_frame(src, t, dst, width=480)
                kfs.append(round(t, 3))
            except Exception:
                continue
        s.keyframes = kfs
        mid = frames_dir / f"{s.id}_1.jpg"
        if mid.exists():
            import imagehash

            s.phash = str(imagehash.phash(Image.open(mid)))
    return shots, {"static_ratio": static_ratio, "median_sharpness": med_sharp, "frames": len(stats)}


def relative_blur(shots: list[Shot]) -> None:
    """Project-level pass: a shot much softer than its siblings is 'blurry' even if the absolute value is ok."""
    vals = [s.sharpness for s in shots if s.sharpness > 0]
    if len(vals) < 3:
        return
    med = float(np.median(vals))
    for s in shots:
        if s.sharpness < 0.06 * med and "blurry" not in s.flags:
            s.flags.append("blurry")
            s.quality = round(max(0.0, s.quality - 0.4), 3)


def duplicate_groups(shots: list[Shot], *, max_dist: int = 10) -> None:
    import imagehash

    hs = [(s, imagehash.hex_to_hash(s.phash)) for s in shots if s.phash]
    gid = 0
    for i, (a, ha) in enumerate(hs):
        for b, hb in hs[i + 1:]:
            if a.asset_id == b.asset_id:
                continue
            if ha - hb <= max_dist:
                g = a.dup_group or b.dup_group or f"dup{gid}"
                if not (a.dup_group or b.dup_group):
                    gid += 1
                a.dup_group = b.dup_group = g
    groups: dict[str, list[Shot]] = {}
    for s in shots:
        if s.dup_group:
            groups.setdefault(s.dup_group, []).append(s)
    for members in groups.values():
        members.sort(key=lambda s: (-(s.quality + 0.1 * (s.camera_move != "static")), s.t0))
        for r, s in enumerate(members):
            s.dup_rank = r
