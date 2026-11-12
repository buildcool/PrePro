"""Test photos both apps can make to the same pixel.

The iPhone app's photo analysis (ios/PreProCore Photos/) is checked against the desktop's on the same pixels, without
committing image files: these pictures are made from whole-number formulas and SplitMix64 noise only, nothing that
depends on a platform's maths library, so ios/PreProCore/Sources/PreProCore/Fixtures/PictureSynth.swift makes them
byte for byte. A picture is a scene: a sky over land (two gradients), a few rectangles and discs, fine noise (sharp,
like a photo), optionally a person's face, a box blur (out of focus), dimming (a dark shot), or seen a few pixels to
the side (the second frame of a burst).
"""

from __future__ import annotations

import numpy as np

MASK = (1 << 64) - 1
GOLDEN, MIX1, MIX2 = 0x9E3779B97F4A7C15, 0xBF58476D1CE4E5B9, 0x94D049BB133111EB
NOISE_SEED = 0x5EED_F00D

# (sky top, sky at the horizon, land at the horizon, land at the bottom)
PALETTES = {
    "beach": ((70, 140, 215), (175, 215, 240), (235, 210, 160), (200, 170, 120)),
    "cafe": ((120, 90, 70), (200, 170, 140), (150, 110, 80), (90, 60, 45)),
    "food": ((230, 225, 215), (245, 240, 230), (190, 120, 70), (140, 80, 50)),
    "market": ((90, 150, 210), (190, 210, 230), (180, 90, 60), (110, 70, 50)),
    "forest": ((60, 120, 90), (150, 190, 160), (60, 100, 50), (30, 60, 30)),
    "sunset": ((40, 40, 110), (250, 140, 70), (90, 60, 70), (30, 20, 30)),
    "city": ((40, 60, 100), (120, 140, 170), (90, 90, 95), (50, 50, 55)),
}
SKIN, EYE, MOUTH = (222, 180, 145), (40, 28, 20), (170, 80, 80)


def mix(z: np.ndarray) -> np.ndarray:
    z = (z ^ (z >> np.uint64(30))) * np.uint64(MIX1)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(MIX2)
    return z ^ (z >> np.uint64(31))


def stream(seed: int, k: np.ndarray) -> np.ndarray:
    """SplitMix64 seeded with `seed`: its k-th output (k = 1, 2, …) for each k."""
    with np.errstate(over="ignore"):
        return mix(np.uint64(seed & MASK) + k.astype(np.uint64) * np.uint64(GOLDEN))


def draws(seed: int, n: int) -> list[int]:
    return [int(v) for v in stream(seed, np.arange(1, n + 1, dtype=np.uint64))]


def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """A box blur of radius r along one axis, the edge pixel repeated, rounded to the nearest level (halves up)."""
    n = 2 * r + 1
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.int64)
    zero = np.zeros_like(np.take(c, [0], axis=axis))
    c = np.concatenate([zero, c], axis=axis)
    size = a.shape[axis]
    hi = np.take(c, np.arange(n, n + size), axis=axis)
    lo = np.take(c, np.arange(0, size), axis=axis)
    return (hi - lo + n // 2) // n


def picture(*, w: int, h: int, seed: int, palette: str = "beach", shapes: int = 7, noise: int = 8, dx: int = 0,
            dy: int = 0, blur: int = 0, dim: tuple[int, int] | None = None, faces: tuple = ()) -> np.ndarray:
    """An upright RGB picture (h, w, 3) uint8. `faces`: (x, y, width) of each face in thousandths of the picture."""
    top, sky, land, bottom = PALETTES[palette]
    X = np.arange(w, dtype=np.int64)[None, :] + dx            # scene coordinates: a burst's second frame is shifted
    Y = np.arange(h, dtype=np.int64)[:, None] + dy
    hz = h * (55 + seed % 10) // 100                          # the horizon
    img = np.zeros((h, w, 3), np.int64)
    ys = np.clip(Y, 0, hz)
    yl = np.clip(Y - hz, 0, h - hz)
    upper = hz > Y
    for c in range(3):
        s = (top[c] * (hz - ys) + sky[c] * ys) // hz
        g = (land[c] * (h - hz - yl) + bottom[c] * yl) // (h - hz)
        img[..., c] = np.where(upper, s, g) + (X * 24) // w   # and a little light from the right
    r = draws(seed, 6 * shapes)
    for i in range(shapes):
        kind, cx, cy, size, col = r[6 * i] % 2, r[6 * i + 1] % w, r[6 * i + 2] % h, w // 20 + r[6 * i + 3] % (w // 7), r[6 * i + 4] >> 40
        rgb = ((col >> 16) & 255, (col >> 8) & 255, col & 255)
        if kind == 0:
            inside = (np.abs(X - cx) <= size) & (np.abs(Y - cy) <= size * 2 // 3)
        else:
            inside = (X - cx) ** 2 + (Y - cy) ** 2 <= size * size
        for c in range(3):
            img[..., c] = np.where(inside, rgb[c], img[..., c])
    for fx, fy, fw in faces:
        cx, cy, a = w * fx // 1000, h * fy // 1000, w * fw // 2000
        b = a * 13 // 10
        head = (X - cx) ** 2 * (b * b) + (Y - cy) ** 2 * (a * a) <= (a * b) ** 2
        for c in range(3):
            img[..., c] = np.where(head, SKIN[c], img[..., c])
        er = max(2, a // 7)
        for ex in (cx - a * 2 // 5, cx + a * 2 // 5):
            eye = (X - ex) ** 2 + (Y - (cy - b // 6)) ** 2 <= er * er
            for c in range(3):
                img[..., c] = np.where(eye, EYE[c], img[..., c])
        mouth = (np.abs(X - cx) <= a * 2 // 5) & (np.abs(Y - (cy + b * 9 // 20)) <= max(1, b // 14))
        for c in range(3):
            img[..., c] = np.where(mouth, MOUTH[c], img[..., c])
    if noise:
        k = ((Y + 64) * (w + 128) + (X + 64)).astype(np.uint64) + np.uint64(1)    # the noise belongs to the scene too
        z = stream(NOISE_SEED ^ seed, k)
        for c, shift in enumerate((60, 52, 44)):                                   # whole numbers ≥ 0 before dividing
            img[..., c] += ((z >> np.uint64(shift)) & np.uint64(15)).astype(np.int64) * noise // 8 - noise
    img = np.clip(img, 0, 255)
    for _ in range(3 if blur else 0):
        img = _box(_box(img, blur, 1), blur, 0)
    if dim:
        img = (img * dim[0] + dim[1] // 2) // dim[1]
    return img.astype(np.uint8)


def stored(img: np.ndarray, orientation: int) -> np.ndarray:
    """The pixels as a phone stores an upright picture under an EXIF orientation (Pillow's exif_transpose undoes it)."""
    undo = {2: lambda a: a[:, ::-1], 3: lambda a: a[::-1, ::-1], 4: lambda a: a[::-1, :], 5: lambda a: a.transpose(1, 0, 2),
            6: lambda a: np.rot90(a, 1), 7: lambda a: np.rot90(a[::-1, :], 1), 8: lambda a: np.rot90(a, -1)}
    return np.ascontiguousarray(undo[orientation](img)) if orientation in undo else img


def fnv(img: np.ndarray) -> str:
    """FNV-1a (64-bit) of the pixel bytes, row by row: a picture's fingerprint in a golden file."""
    h = 0xCBF29CE484222325
    for b in np.ascontiguousarray(img).tobytes():
        h = ((h ^ b) * 0x100000001B3) & MASK
    return f"{h:016x}"
