"""Per-clip visual analysis on a low-res frame stream: shots, quality, motion/camera move, whips, faces,
action peaks, best windows, keyframes + perceptual hash."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..media.proxy import grab_frame, iter_frames
from ..schema.analysis import FaceBox, Seat, Shot, Window

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
    cx: float | None = None  # centroid of local change (moving subject), normalised
    cy: float | None = None
    faces: list[FaceBox] = field(default_factory=list)
    faces_lo: list[FaceBox] = field(default_factory=list)   # incl. lower-confidence boxes: only used to find seats
    grid: np.ndarray | None = None   # change since the previous frame on a coarse grid (who is moving their mouth)


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


def photo_fills(display_size: tuple[int, int] | None, faces: list, out_ar: float) -> bool:
    """Whether a photo can fill a frame of aspect ``out_ar`` without cutting anyone out: not a group photo whose faces
    spread wider than the crop window, and not a panorama of which a filled frame would show under a third."""
    if not display_size or not display_size[1]:
        return True
    crop_w = out_ar / (display_size[0] / display_size[1])
    span = (max(f.x + f.w / 2 for f in faces) - min(f.x - f.w / 2 for f in faces)) if len(faces) >= 2 else 0.0
    return not (span > 0.92 * min(1.0, crop_w) or crop_w < 0.3)


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
    if fs.diff < 0.06:   # steady camera: locate the moving subject
        thr = max(0.08, float(np.percentile(ad, 99)) * 0.5)
        ys, xs = np.nonzero(ad > thr)
        if xs.size > 6:
            fs.cx, fs.cy = float(xs.mean() / ad.shape[1]), float(ys.mean() / ad.shape[0])
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


def _track(fr: list[FrameStats]) -> list[tuple[float, float, float]]:
    """Subject position over time (~2 Hz): biggest face, else the centroid of local motion."""
    out = []
    step = max(1, int(FPS / 2))
    for f in fr[::step]:
        if f.faces:
            b = max(f.faces, key=lambda x: x.w * x.h)
            out.append((round(f.t, 2), round(b.x, 3), round(b.y, 3)))
        elif f.cx is not None and f.local > 0.12:
            out.append((round(f.t, 2), round(f.cx, 3), round(f.cy or 0.5, 3)))
    return out


GRID_W = 96        # change-grid columns (≈3 px per cell at the analysis width: a two-shot mouth spans a few cells)
SEAT_CONF = 0.35   # face confidence for finding seats. Lower than elsewhere on purpose: the detector finds some faces
                   # (in our two-shot fixture, the darker-skinned guest) less often, and nobody may be left out of the edit
SEAT_SEEN = 0.25   # a seat must be seen in this share of the face-sampled frames, at a consistent position


def _seats(sampled: list[FrameStats]) -> list[Seat]:
    """People sitting still in a shot: face positions clustered left to right. Two or more stable clusters make a
    multi-person shot; anything else has no seats."""
    boxes = sorted((b for f in sampled for b in f.faces_lo), key=lambda b: b.x)
    if len(sampled) < 3 or len(boxes) < 4:
        return []
    groups: list[list[FaceBox]] = [[boxes[0]]]
    for b in boxes[1:]:
        if b.x - groups[-1][-1].x > max(0.06, 0.5 * float(np.median([g.w for g in groups[-1]]))):
            groups.append([b])
        else:
            groups[-1].append(b)
    seats, spans = [], []
    for g in groups:
        lo, hi = g[0].x - 1e-6, g[-1].x + 1e-6
        seen = sum(1 for f in sampled if any(lo <= b.x <= hi for b in f.faces_lo)) / len(sampled)
        steady = float(np.std([b.x for b in g])) < 0.04 and float(np.std([b.y for b in g])) < 0.05
        if seen >= SEAT_SEEN and steady:
            seats.append(Seat(x=round(float(np.median([b.x for b in g])), 4), y=round(float(np.median([b.y for b in g])), 4),
                              w=round(float(np.median([b.w for b in g])), 4), h=round(float(np.median([b.h for b in g])), 4),
                              presence=round(seen, 3)))
            spans.append((lo, hi))
    if len(seats) < 2:
        return []
    # two people are on screen *at the same time*; one person moving between two spots (a vlogger leaning, walking,
    # turning) is never in both at once — reading them as two speakers split their retakes into a "conversation"
    together = sum(1 for f in sampled if sum(1 for lo, hi in spans if any(lo <= b.x <= hi for b in f.faces_lo)) >= 2)
    return seats if together >= max(2, 0.15 * len(sampled)) else []


def _mouth_series(fr: list[FrameStats], seats: list[Seat]) -> list[list[float]]:
    """Per seat: change in the mouth area minus change around the eyes (so nodding, bobbing and leaning don't count),
    one value per analysis frame."""
    out = []
    for s in seats:
        vals = []
        for f in fr:
            g = f.grid
            if g is None:
                vals.append(0.0)
                continue
            gh, gw = g.shape

            def box(y0, y1, s=s, gw=gw, gh=gh, g=g):
                xa, xb = int((s.x - 0.24 * s.w) * gw), int(np.ceil((s.x + 0.24 * s.w) * gw))
                ya, yb = int((s.y + y0 * s.h) * gh), int(np.ceil((s.y + y1 * s.h) * gh))
                cell = g[max(0, ya): max(ya + 1, min(gh, yb)), max(0, xa): max(xa + 1, min(gw, xb))]
                return float(cell.mean()) if cell.size else 0.0

            vals.append(round(max(0.0, box(0.10, 0.45) - box(-0.38, -0.02)), 2))
        out.append(vals)
    return out


def find_facecam(src: Path, duration: float, *, samples: int = 12, width: int = 960) -> list[float] | None:
    """The picture-in-picture webcam of a screen recording, as [x0, y0, x1, y1] (normalised), or None.

    A steady face in a corner (looked for at 960 px: at the 320 px analysis width a streamer's face in a PiP is too
    small to detect), then the rectangle around it whose border stays in the same place in every frame while the
    game and the person move (where the webcam picture meets the game). Without a clear border, a head-and-shoulders
    box around the face."""
    det = face_detector()
    if det.net is None or duration <= 0:
        return None
    seen: list[FaceBox] = []
    freq = None
    n = 0
    for t, rgb in iter_frames(src, fps=samples / max(duration, 0.1), width=width):
        n += 1
        fh_, fw_ = rgb.shape[:2]
        for qx, qy in ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5)):   # each corner on its own: twice the face size
            crop = rgb[int(qy * fh_): int((qy + 0.5) * fh_), int(qx * fw_): int((qx + 0.5) * fw_)]
            for b in det(np.ascontiguousarray(crop), t, conf=0.5):
                x, y, w, h = qx + b.x * 0.5, qy + b.y * 0.5, b.w * 0.5, b.h * 0.5
                if (x < 0.38 or x > 0.62) and (y < 0.42 or y > 0.58) and w < 0.25:
                    seen.append(FaceBox(t=b.t, x=x, y=y, w=w, h=h, conf=b.conf))
        # edges in any colour channel: a webcam border can differ from the game in colour only (blue-grey next to green
        # of the same brightness is nearly invisible in greyscale)
        e = cv2.dilate(np.maximum.reduce([cv2.Canny(np.ascontiguousarray(rgb[:, :, c]), 50, 150) for c in range(3)]),
                       np.ones((3, 3), np.uint8)) > 0
        freq = e.astype(np.float32) if freq is None else freq + e
    if not seen or freq is None or n < 3:
        return None
    # the steady corner face: the biggest group of detections at about the same place, seen in half the samples
    groups: list[list[FaceBox]] = []
    for b in seen:
        g = next((g for g in groups if abs(g[0].x - b.x) < 0.05 and abs(g[0].y - b.y) < 0.08), None)
        (g.append(b) if g is not None else groups.append([b]))
    g = max(groups, key=len)
    if len({round(b.t, 1) for b in g}) < max(3, n * 0.5):
        return None
    fx, fy = float(np.median([b.x for b in g])), float(np.median([b.y for b in g]))
    fw, fh = float(np.median([b.w for b in g])), float(np.median([b.h for b in g]))
    on = (freq / n) >= 0.6                             # an edge in (nearly) every sampled frame
    H, W = on.shape

    def longest(v: np.ndarray) -> int:
        best = cur = 0
        for x in v:
            cur = cur + 1 if x else 0
            best = max(best, cur)
        return best

    def line(lo: float, hi: float, span: tuple[float, float], vertical: bool) -> tuple[float, float]:
        """The straight line in [lo, hi] (columns if vertical, else rows) with the longest unbroken persistent run
        across `span`: a PiP border runs the webcam's whole height/width, edges inside the picture don't."""
        size, other = (W, H) if vertical else (H, W)
        a, b = int(max(0.0, lo) * size), int(min(1.0, hi) * size)
        s0, s1 = int(max(0.0, span[0]) * other), int(min(1.0, span[1]) * other)
        best, at = 0, (lo + hi) / 2
        for k in range(a, b):
            v = on[s0:s1, k] if vertical else on[k, s0:s1]
            r = longest(v)
            if r > best or (r == best and r and abs(k / size - (fx if vertical else fy)) > abs(at - (fx if vertical else fy))):
                best, at = r, (k + 0.5) / size        # ties: the one farther from the face (the outer frame)
        return best / other, at

    right, top = fx > 0.5, fy < 0.5
    # provisional head-and-shoulders box, then snap each side to a border line that persists
    x0, x1 = fx - 1.3 * fw, fx + 1.3 * fw
    y0, y1 = fy - 1.1 * fh, fy + 1.4 * fh
    tall = (fy - 4 * fh, fy + 4 * fh)
    for _ in range(2):
        rows = (min(y0, tall[0]), max(y1, tall[1]))
        r_in, c_in = line(fx - 4.0 * fw, fx - 0.7 * fw, rows, True) if right else line(fx + 0.7 * fw, fx + 4.0 * fw, rows, True)
        r_out, c_out = line(fx + 0.7 * fw, 1.0, rows, True) if right else line(0.0, fx - 0.7 * fw, rows, True)
        need = 1.5 * fh
        if r_in >= need:
            x0, x1 = (c_in, x1) if right else (x0, c_in)
        x0, x1 = ((x0, c_out) if r_out >= need else (x0, 1.0)) if right else ((c_out, x1) if r_out >= need else (0.0, x1))
        cols = (x0 - 0.02, x1 + 0.02)
        r_in, w_in = line(fy + 0.7 * fh, fy + 4.0 * fh, cols, False) if top else line(fy - 4.0 * fh, fy - 0.7 * fh, cols, False)
        r_out, w_out = line(0.0, fy - 0.7 * fh, cols, False) if top else line(fy + 0.7 * fh, 1.0, cols, False)
        need = 0.6 * (x1 - x0)
        if r_in >= need:
            y0, y1 = (y0, w_in) if top else (w_in, y1)
        y0, y1 = ((w_out, y1) if r_out >= need else (0.0, y1)) if top else ((y0, w_out) if r_out >= need else (y0, 1.0))
    box = [max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)]
    if box[2] - box[0] < 1.2 * fw or box[3] - box[1] < 1.2 * fh or (box[2] - box[0]) * (box[3] - box[1]) > 0.25:
        return None                                    # not a PiP: a face in the corner of a normal shot
    return [round(v, 4) for v in box]


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
            if det is not None:
                gh = max(4, int(round(GRID_W * gray.shape[0] / gray.shape[1])))
                fs.grid = cv2.resize(cv2.absdiff(gray, prev_gray), (GRID_W, gh), interpolation=cv2.INTER_AREA)
        if det is not None and i % int(FPS) == 0:
            fs.faces_lo = det(rgb, t, conf=SEAT_CONF)
            fs.faces = [b for b in fs.faces_lo if b.conf >= 0.6]
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
        seats = _seats(sampled) if det is not None else []
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
            static_ratio=round(static_ratio, 3), hud=round(hud, 3), track=_track(fr),
            seats=seats if move == "static" else [], mouth=_mouth_series(fr, seats) if seats and move == "static" else [],
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


def duplicate_groups(shots: list[Shot], *, max_dist: int = 10, prefix: str = "dup") -> None:
    """Near-identical shots (or a burst of photos) share a group; rank 0 is the one to use (sharpest, best)."""
    import imagehash

    hs = [(s, imagehash.hex_to_hash(s.phash)) for s in shots if s.phash]
    gid = 0
    for i, (a, ha) in enumerate(hs):
        for b, hb in hs[i + 1:]:
            if a.asset_id == b.asset_id:
                continue
            if ha - hb <= max_dist:
                g = a.dup_group or b.dup_group or f"{prefix}{gid}"
                if not (a.dup_group or b.dup_group):
                    gid += 1
                a.dup_group = b.dup_group = g
    groups: dict[str, list[Shot]] = {}
    for s in shots:
        if s.dup_group:
            groups.setdefault(s.dup_group, []).append(s)
    photo = prefix == "burst"            # a burst of photos: keep the sharpest, most striking frame
    for members in groups.values():
        members.sort(key=lambda s: (-(s.quality + 0.1 * (s.camera_move != "static")
                                      + (0.3 * (s.aesthetic or 0) + min(0.3, 0.0005 * s.sharpness) if photo else 0.0)), s.t0))
        for r, s in enumerate(members):
            s.dup_rank = r
