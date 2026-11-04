"""Style DNA: measure how reference videos are edited and steer the cut toward that style.

Drop 1–5 videos you like into a `style/` (or `references/`) folder inside the shoot. They are measured locally,
never cut into your edit and never uploaded. What is measured, and what it steers:

| measured                         | steers                                   |
|----------------------------------|------------------------------------------|
| cuts per minute, shot lengths    | pace knob, B-roll shot length            |
| talking share, pause lengths     | how tight speech is cut                  |
| on-screen text share             | captions off / clean / bold              |
| music under / instead of voice   | soundtrack mode hint                     |
| length                           | target length                            |

Knobs you set yourself always win over the style.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from .project import Project


class StyleRef(BaseModel):
    name: str
    duration: float
    aspect: str
    cuts_per_min: float
    shot_median: float
    speech_ratio: float
    pause_median: float | None
    music_ratio: float
    text_ratio: float
    lufs: float | None = None


class StyleDNA(BaseModel):
    refs: list[StyleRef] = Field(default_factory=list)
    duration: float = 0.0
    aspect: str = "9:16"
    cuts_per_min: float = 0.0
    shot_median: float = 0.0
    speech_ratio: float = 0.0
    pause_median: float | None = None
    music_ratio: float = 0.0
    text_ratio: float = 0.0
    knobs: dict = Field(default_factory=dict)       # what the style sets (pace, captions, effects, target_length, tightness, shot_len)
    summary: list[str] = Field(default_factory=list)
    enabled: bool = True


def _hist(fr: np.ndarray) -> np.ndarray:
    import cv2

    hsv = cv2.cvtColor(fr, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten().astype(np.float32)


def _text_band(fr: np.ndarray) -> bool:
    """Burned-in captions/titles: a text-shaped block (wide, 2.5–16 % of the height, densely stroked) in the upper or
    lower caption band, with bright letters next to dark outlines."""
    import cv2

    g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
    H, W = g.shape
    grad = cv2.morphologyEx(g, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    joined = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, W // 25), 3)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(joined)
    for x, y, w, h, area in stats[1:]:
        if not (0.025 * H <= h <= 0.16 * H) or w < 2.0 * h or w < 0.12 * W:
            continue
        if not (y > 0.55 * H or y + h < 0.45 * H):        # captions/titles live in the top or bottom band
            continue
        if area / float(w * h) < 0.45:
            continue
        roi = g[y: y + h, x: x + w]
        if (roi > 200).mean() > 0.06 and (roi < 60).mean() > 0.06:
            return True
    return False


def measure(path: Path, work: Path) -> StyleRef:
    from .analyze.asr import energy_vad
    from .media.probe import probe
    from .media.proxy import extract_audio, iter_frames

    info = probe(path)
    dur = info.duration or 0.0
    ds = info.display_size or (info.width or 16, info.height or 9)
    aspect = "9:16" if ds[1] > ds[0] * 1.2 else ("1:1" if abs(ds[0] - ds[1]) < 0.1 * ds[0] else "16:9")
    # picture: cuts from colour-histogram jumps at 8 fps (references can cut fast), text from stroke bands at 2 fps
    import cv2

    fps = 8.0
    prev, cuts, texts, tn = None, [0.0], 0, 0
    for n, (t, fr) in enumerate(iter_frames(path, fps=fps, width=240)):
        h = _hist(fr)
        if prev is not None:
            d = cv2.compareHist(prev, h, cv2.HISTCMP_BHATTACHARYYA)
            if d > 0.45 and t - cuts[-1] >= 0.2:
                cuts.append(t)
        prev = h
        if n % 4 == 0:
            tn += 1
            texts += _text_band(fr)
    shots = np.diff(cuts + [dur]) if dur else np.array([])
    shots = shots[shots > 0.05]
    # sound: speech vs music from the energy VAD and the level of the gaps
    speech_ratio, pause_med, music_ratio, lufs = 0.0, None, 0.0, None
    if info.has_audio:
        wav = extract_audio(path, work / f"{path.stem}.style.wav", sr=16000)
        import soundfile as sf

        y, sr = sf.read(str(wav), dtype="float32")
        wav.unlink(missing_ok=True)
        if y.ndim > 1:
            y = y.mean(axis=1)
        speech = energy_vad(y)
        sp_t = sum(iv.t1 - iv.t0 for iv in speech)
        speech_ratio = sp_t / max(1e-6, len(y) / sr)
        gaps = [b.t0 - a.t1 for a, b in zip(speech, speech[1:], strict=False) if 0.05 < b.t0 - a.t1 < 2.0]
        pause_med = float(np.median(gaps)) if gaps else None
        # music: sustained energy where nobody talks (and a steady floor under speech)
        hop = sr // 20
        frames = y[: len(y) // hop * hop].reshape(-1, hop)
        rms_db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
        is_sp = np.zeros(len(rms_db), bool)
        for iv in speech:
            is_sp[int(iv.t0 * 20): int(iv.t1 * 20) + 1] = True
        non = rms_db[~is_sp]
        music_ratio = float((non > -38).mean()) if non.size else 0.0
        if speech_ratio > 0.5 and non.size < 0.1 * len(rms_db):
            music_ratio = float(np.percentile(rms_db[is_sp], 10) > -35)   # a bed never lets the floor drop
        try:
            import pyloudnorm as pyln

            lufs = round(float(pyln.Meter(sr).integrated_loudness(y.astype(np.float64))), 1)
        except Exception:
            lufs = None
    return StyleRef(name=path.name, duration=round(dur, 2), aspect=aspect,
                    cuts_per_min=round((len(cuts) - 1) / max(dur / 60, 1e-6), 1), shot_median=round(float(np.median(shots)) if shots.size else dur, 2),
                    speech_ratio=round(speech_ratio, 3), pause_median=round(pause_med, 3) if pause_med is not None else None,
                    music_ratio=round(music_ratio, 3), text_ratio=round(texts / max(tn, 1), 3), lufs=lufs)


def to_knobs(dna: StyleDNA) -> tuple[dict, list[str]]:
    k: dict = {}
    s: list[str] = []
    cpm = dna.cuts_per_min
    k["pace"] = 0.9 if cpm >= 30 else 0.75 if cpm >= 18 else 0.55 if cpm >= 9 else 0.35
    s.append(f"{cpm:.0f} cuts/min (shots ~{dna.shot_median:.1f} s) → pace {k['pace']:.2f}")
    k["shot_len"] = round(float(np.clip(dna.shot_median, 0.6, 6.0)), 2)
    if dna.speech_ratio > 0.25 and dna.pause_median is not None:
        k["tightness"] = 0.85 if dna.pause_median < 0.22 else 0.65 if dna.pause_median < 0.4 else 0.45
        s.append(f"talking {dna.speech_ratio:.0%}, pauses ~{dna.pause_median:.2f} s → {'tight' if k['tightness'] > 0.7 else 'natural'} speech cuts")
    k["captions"] = "bold" if dna.text_ratio >= 0.45 else "clean" if dna.text_ratio >= 0.15 else "off"
    s.append(f"text on screen {dna.text_ratio:.0%} of the time → captions {k['captions']}")
    k["effects"] = "bold" if cpm >= 30 else "balanced" if cpm >= 9 else "clean"
    if dna.music_ratio > 0.5:
        s.append("music " + ("under the voice" if dna.speech_ratio > 0.3 else "leads the edit"))
    if dna.duration:
        k["target_length"] = round(dna.duration)
        s.append(f"~{dna.duration:.0f} s long")
    return k, s


def measure_shoot(root: str | Path, refs: list[Path] | None = None) -> StyleDNA | None:
    proj = Project(root)
    refs = refs if refs is not None else proj.scan().style_refs
    if not refs:
        return None
    work = proj.sub("style")
    rs = [measure(p, work) for p in refs]
    w = np.array([max(1.0, r.duration) for r in rs])

    def avg(attr):
        vals = [(getattr(r, attr), wi) for r, wi in zip(rs, w, strict=True) if getattr(r, attr) is not None]
        return float(np.average([v for v, _ in vals], weights=[x for _, x in vals])) if vals else None

    aspects = [r.aspect for r in rs]
    dna = StyleDNA(refs=rs, duration=round(float(np.median([r.duration for r in rs])), 1), aspect=max(set(aspects), key=aspects.count),
                   cuts_per_min=round(avg("cuts_per_min"), 1), shot_median=round(float(np.median([r.shot_median for r in rs])), 2),
                   speech_ratio=round(avg("speech_ratio"), 3), pause_median=None if avg("pause_median") is None else round(avg("pause_median"), 3),
                   music_ratio=round(avg("music_ratio"), 3), text_ratio=round(avg("text_ratio"), 3))
    dna.knobs, dna.summary = to_knobs(dna)
    proj.save_model("style.json", dna)
    return dna


def load(root: str | Path) -> StyleDNA | None:
    return Project(root).load_model("style.json", StyleDNA)
