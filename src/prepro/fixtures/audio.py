"""Procedural audio with exact ground truth: TTS speech, music with known beats/sections, SFX.

Everything here is generated locally (espeak-ng + numpy), so it is licence-free and deterministic.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000


# ---------------------------------------------------------------- basics
def write_wav(path: Path, y: np.ndarray, sr: int = SR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    y = np.asarray(y, dtype=np.float32)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.99:
        y = y * (0.99 / peak)
    sf.write(str(path), y, sr, subtype="PCM_16")
    return path


def resample(y: np.ndarray, sr_from: int, sr_to: int = SR) -> np.ndarray:
    if sr_from == sr_to:
        return y
    from scipy.signal import resample_poly

    g = np.gcd(sr_from, sr_to)
    return resample_poly(y, sr_to // g, sr_from // g).astype(np.float32)


def silence(sec: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(round(sec * sr)), dtype=np.float32)


def room_tone(n: int, level_db: float = -58.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n).astype(np.float32)
    # pinkish: smooth with a short moving average
    k = np.ones(8, dtype=np.float32) / 8
    noise = np.convolve(noise, k, mode="same")
    noise /= max(1e-9, float(np.std(noise)))
    return noise * (10 ** (level_db / 20))


def fade(y: np.ndarray, fin: float = 0.005, fout: float = 0.01, sr: int = SR) -> np.ndarray:
    y = y.copy()
    a, b = int(fin * sr), int(fout * sr)
    if a:
        y[:a] *= np.linspace(0, 1, a, dtype=np.float32)
    if b:
        y[-b:] *= np.linspace(1, 0, b, dtype=np.float32)
    return y


# ---------------------------------------------------------------- TTS
def have_tts() -> bool:
    return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None


def tts(text: str, *, lang: str = "en-us", speed: int = 165, pitch: int = 45, amplitude: int = 140, gap: int = 0) -> np.ndarray:
    """Synthesise ``text`` with espeak-ng → float32 mono at :data:`SR`."""
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise RuntimeError("espeak-ng is required for synthetic speech fixtures (apt install espeak-ng)")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "t.wav"
        subprocess.run(
            [exe, "-v", lang, "-s", str(speed), "-p", str(pitch), "-a", str(amplitude), "-g", str(gap), "-w", str(out), text],
            check=True, capture_output=True,
        )
        y, sr = sf.read(str(out), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    # trim espeak's leading/trailing silence so ground-truth times are tight
    thr = 10 ** (-45 / 20) * max(1e-6, float(np.max(np.abs(y))))
    idx = np.where(np.abs(y) > thr)[0]
    if idx.size:
        y = y[max(0, idx[0] - int(0.01 * sr)): idx[-1] + int(0.02 * sr)]
    return fade(resample(y, sr, SR) * 0.9)


@dataclass
class Line:
    text: str
    kind: str = "line"            # line|retake|false_start|filler|punchline|hook|cta|aside
    keep: bool = True             # ground truth: should this survive the edit?
    pause_after: float = 0.35     # silence after the line (seconds)
    lang: str = "en-us"
    speed: int = 165
    pitch: int = 45
    amplitude: int = 140
    group: str | None = None      # retake group label
    emphasis: list[str] = field(default_factory=list)   # words that should be emphasised
    romanized: str | None = None  # Hinglish romanisation for captions


@dataclass
class SpokenLine:
    t0: float
    t1: float
    text: str
    kind: str
    keep: bool
    group: str | None
    lang: str
    emphasis: list[str]
    romanized: str | None = None


def build_speech(lines: list[Line], *, lead_in: float = 0.6, tail: float = 0.8, noise_db: float = -60.0, seed: int = 0) -> tuple[np.ndarray, list[SpokenLine]]:
    parts = [silence(lead_in)]
    t = lead_in
    truth: list[SpokenLine] = []
    for ln in lines:
        y = tts(ln.text, lang=ln.lang, speed=ln.speed, pitch=ln.pitch, amplitude=ln.amplitude)
        dur = len(y) / SR
        truth.append(SpokenLine(t, t + dur, ln.text, ln.kind, ln.keep, ln.group, ln.lang, list(ln.emphasis), ln.romanized))
        parts.append(y)
        t += dur
        parts.append(silence(ln.pause_after))
        t += ln.pause_after
    parts.append(silence(tail))
    y = np.concatenate(parts)
    y = y + room_tone(len(y), noise_db, seed)
    return y.astype(np.float32), truth


# ---------------------------------------------------------------- music
_NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def _midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n: int, a: float, d: float, sr: int = SR) -> np.ndarray:
    t = np.arange(n) / sr
    e = np.minimum(1.0, t / max(a, 1e-4)) * np.exp(-t / max(d, 1e-4))
    return e.astype(np.float32)


def _kick(sr: int = SR) -> np.ndarray:
    n = int(0.35 * sr)
    t = np.arange(n) / sr
    f = 120 * np.exp(-t * 18) + 42
    ph = 2 * np.pi * np.cumsum(f) / sr
    return (np.sin(ph) * np.exp(-t * 9)).astype(np.float32)


def _snare(rng, sr: int = SR) -> np.ndarray:
    n = int(0.22 * sr)
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)
    noise = rng.standard_normal(n) * np.exp(-t * 18)
    return (0.5 * tone + 0.6 * noise).astype(np.float32)


def _hat(rng, sr: int = SR) -> np.ndarray:
    n = int(0.06 * sr)
    noise = rng.standard_normal(n)
    noise = np.diff(noise, prepend=0)  # crude high-pass
    return (noise * np.exp(-np.arange(n) / sr * 70) * 0.25).astype(np.float32)


def _tone(freq: float, dur: float, kind: str = "saw", sr: int = SR) -> np.ndarray:
    n = int(dur * sr)
    t = np.arange(n) / sr
    if kind == "sine":
        y = np.sin(2 * np.pi * freq * t)
    elif kind == "square":
        y = np.sign(np.sin(2 * np.pi * freq * t)) * 0.6
    else:  # band-limited-ish saw (few harmonics)
        y = sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, 7))
    return y.astype(np.float32)


def _add(buf: np.ndarray, y: np.ndarray, at: int, gain: float = 1.0) -> None:
    if at >= len(buf):
        return
    end = min(len(buf), at + len(y))
    buf[at:end] += y[: end - at] * gain


@dataclass
class MusicTruth:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    sections: list[tuple[str, float, float, float]]   # (label, t0, t1, energy)
    duration: float
    mood: str
    vocals: bool = False


def procedural_music(
    *, bpm: float = 100, sections: list[tuple[str, int, float]] | None = None, key: str = "A", minor: bool = True,
    seed: int = 0, swing: float = 0.0, mood: str = "neutral", vocal_hum: bool = False,
) -> tuple[np.ndarray, MusicTruth]:
    """Drums + bass + chords + lead, layered by section energy. sections = [(label, bars, energy 0..1)]."""
    sections = sections or [("intro", 4, 0.3), ("build", 4, 0.6), ("drop", 8, 1.0), ("outro", 4, 0.35)]
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    total_bars = sum(b for _, b, _ in sections)
    dur = total_bars * 4 * beat + 1.5
    buf = np.zeros(int(dur * SR), dtype=np.float32)
    kick, snare = _kick(), _snare(rng)
    root = 45 + _NOTE[key]  # A2-ish
    prog = [0, 8, 3, 10] if minor else [0, 7, 9, 5]   # i–VI–iii–VII  /  I–V–vi–IV
    third = 3 if minor else 4
    beats, downbeats, sec_truth = [], [], []
    bar_i = 0
    for label, bars, energy in sections:
        s_t0 = bar_i * 4 * beat
        for _b in range(bars):
            bar_t = bar_i * 4 * beat
            downbeats.append(bar_t)
            chord_root = root + prog[bar_i % 4]
            for q in range(4):
                bt = bar_t + q * beat + (swing * beat * 0.5 if q % 2 else 0)
                beats.append(bt)
                at = int(bt * SR)
                if energy >= 0.25 and (q in (0, 2) or energy > 0.85):
                    _add(buf, kick, at, 0.9 * min(1.0, energy + 0.2))
                if energy >= 0.45 and q in (1, 3):
                    _add(buf, snare, at, 0.45)
                if energy >= 0.35:
                    for h in range(2 if energy < 0.8 else 4):
                        _add(buf, _hat(rng), at + int(h * beat / (2 if energy < 0.8 else 4) * SR), 0.6)
                # bass on each beat
                bass = _tone(_midi_hz(chord_root - 12), beat * 0.9, "saw") * _env(int(beat * 0.9 * SR), 0.005, beat * 0.6)
                _add(buf, bass, at, 0.18 + 0.12 * energy)
            # chord pad per bar
            pad_len = 4 * beat
            for iv in (0, third, 7):
                pad = _tone(_midi_hz(chord_root + 12 + iv), pad_len, "sine") * _env(int(pad_len * SR), 0.15, pad_len * 0.9)
                _add(buf, pad, int(bar_t * SR), 0.06 + 0.04 * (1 - energy))
            # lead arpeggio in high energy
            if energy >= 0.8:
                for e8 in range(8):
                    note = chord_root + 24 + [0, third, 7, 12][e8 % 4]
                    ln = beat / 2
                    lead = _tone(_midi_hz(note), ln, "square") * _env(int(ln * SR), 0.003, ln * 0.4)
                    _add(buf, lead, int((bar_t + e8 * beat / 2) * SR), 0.05)
            if vocal_hum and energy >= 0.5:
                # crude "vocal" formant hum to emulate a track with vocals
                ln = 2 * beat
                f0 = _midi_hz(chord_root + 24 + third)
                t = np.arange(int(ln * SR)) / SR
                vib = np.sin(2 * np.pi * 5.5 * t) * 4
                voice = np.sin(2 * np.pi * (f0 + vib) * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 700 * t) ** 2)
                _add(buf, (voice * _env(len(t), 0.05, ln)).astype(np.float32), int(bar_t * SR), 0.08)
            bar_i += 1
        sec_truth.append((label, s_t0, bar_i * 4 * beat, energy))
    # fade the tail
    tail = int(1.5 * SR)
    buf[-tail:] *= np.linspace(1, 0, tail, dtype=np.float32)
    buf /= max(1e-6, float(np.max(np.abs(buf)))) / 0.8
    truth = MusicTruth(bpm=bpm, beats=[round(b, 4) for b in beats], downbeats=[round(b, 4) for b in downbeats],
                       sections=sec_truth, duration=len(buf) / SR, mood=mood, vocals=vocal_hum)
    return buf, truth


# ---------------------------------------------------------------- SFX
def sfx(kind: str, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sr = SR
    if kind == "whoosh":
        n = int(0.55 * sr)
        noise = rng.standard_normal(n).astype(np.float32)
        t = np.linspace(0, 1, n)
        env = np.sin(np.pi * t) ** 2
        # sweep a one-pole low-pass cutoff up then down
        out = np.zeros(n, dtype=np.float32)
        y = 0.0
        for i in range(n):
            a = 0.02 + 0.5 * env[i]
            y = y + a * (noise[i] - y)
            out[i] = y
        return fade(out * env.astype(np.float32) * 2.5)
    if kind == "pop":
        n = int(0.09 * sr)
        t = np.arange(n) / sr
        f = 900 * np.exp(-t * 40) + 300
        return fade((np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 45)).astype(np.float32))
    if kind == "riser":
        n = int(1.8 * sr)
        t = np.arange(n) / sr
        f = 200 * 2 ** (t / 1.8 * 3)
        tone = np.sin(2 * np.pi * np.cumsum(f) / sr)
        noise = rng.standard_normal(n) * (t / 1.8)
        return fade(((0.5 * tone + 0.3 * noise) * (t / 1.8) ** 1.5).astype(np.float32), fout=0.002)
    if kind in ("impact", "boom"):
        n = int(1.4 * sr)
        t = np.arange(n) / sr
        f = 70 * np.exp(-t * 2.5) + 38
        body = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 2.2)
        click = rng.standard_normal(n) * np.exp(-t * 60) * 0.4
        return fade((body + click).astype(np.float32))
    if kind == "ding":
        n = int(1.2 * sr)
        t = np.arange(n) / sr
        y = sum(np.sin(2 * np.pi * 1320 * r * t) * np.exp(-t * (3 + 2 * i)) / (i + 1) for i, r in enumerate((1, 2.76, 5.4)))
        return fade(y.astype(np.float32) * 0.6)
    if kind == "scratch":
        n = int(0.6 * sr)
        t = np.arange(n) / sr
        noise = rng.standard_normal(n)
        mod = np.sin(2 * np.pi * 6 * t) ** 2
        return fade((noise * mod * np.exp(-t * 3) * 0.7).astype(np.float32))
    if kind == "click":
        n = int(0.03 * sr)
        return fade((rng.standard_normal(n) * np.exp(-np.arange(n) / sr * 200)).astype(np.float32) * 0.6)
    if kind == "laugh":
        # bursty "ha-ha-ha" formants
        parts = []
        for k in range(6):
            n = int(0.16 * sr)
            t = np.arange(n) / sr
            f0 = 230 + 25 * np.sin(k)
            y = np.sin(2 * np.pi * f0 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 800 * t) ** 2) * np.sin(np.pi * t / t[-1])
            parts.append(y.astype(np.float32))
            parts.append(silence(0.07))
        return fade(np.concatenate(parts) * 0.6)
    if kind == "sizzle":
        n = int(4.0 * sr)
        crackle = (rng.random(n) > 0.997).astype(np.float32) * rng.standard_normal(n).astype(np.float32)
        hiss = rng.standard_normal(n).astype(np.float32) * 0.05
        return fade(np.diff(crackle + hiss, prepend=0) * 0.8, fin=0.3, fout=0.3)
    if kind == "chop":
        parts = []
        for _ in range(8):
            parts.append(sfx("click", int(rng.integers(0, 1000))) * 1.5)
            parts.append(silence(0.32 + float(rng.random()) * 0.1))
        return np.concatenate(parts)
    if kind == "waves":
        n = int(8 * sr)
        noise = rng.standard_normal(n).astype(np.float32)
        k = np.ones(64, dtype=np.float32) / 64
        noise = np.convolve(noise, k, mode="same")
        t = np.arange(n) / sr
        swell = 0.4 + 0.6 * np.sin(2 * np.pi * t / 4.0) ** 2
        return fade(noise * swell.astype(np.float32) * 3, fin=0.5, fout=0.5)
    if kind == "explosion":
        n = int(1.6 * sr)
        t = np.arange(n) / sr
        noise = rng.standard_normal(n) * np.exp(-t * 3)
        low = np.sin(2 * np.pi * 45 * t) * np.exp(-t * 2)
        return fade((noise * 0.7 + low).astype(np.float32))
    raise ValueError(f"unknown sfx kind {kind}")
