"""The fixture song synth (prepro.fixtures.audio.procedural_music) with a random generator both apps can run.

numpy's default_rng can't be reproduced in Swift, so this copy draws the drums' noise from SplitMix64 + Box–Muller —
a few lines PreProCore implements identically (Fixtures/SongSynth.swift) — and synthesizes at any sample rate (the
analysis rate, 22.05 kHz, so no resampler stands between the two apps). Same drums, bass, chords and lead, laid on
an exactly known beat grid; the desktop's analysis of these songs is the iPhone's golden.
"""

from __future__ import annotations

import math

import numpy as np

MASK = (1 << 64) - 1
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


class PortableRng:
    """SplitMix64 → uniforms in (0, 1] → Box–Muller standard normals (one per pair of uniforms)."""

    def __init__(self, seed: int):
        self.state = seed & MASK

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def uniform(self) -> float:
        return ((self.next_u64() >> 11) + 1) * (1.0 / 9007199254740992.0)

    def normals(self, n: int) -> np.ndarray:
        out = np.empty(n)
        for i in range(n):
            u1, u2 = self.uniform(), self.uniform()
            out[i] = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return out


def _midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n, a, d, sr):
    t = np.arange(n) / sr
    return (np.minimum(1.0, t / max(a, 1e-4)) * np.exp(-t / max(d, 1e-4))).astype(np.float32)


def _kick(sr):
    n = int(0.35 * sr)
    t = np.arange(n) / sr
    f = 120 * np.exp(-t * 18) + 42
    ph = 2 * np.pi * np.cumsum(f) / sr
    return (np.sin(ph) * np.exp(-t * 9)).astype(np.float32)


def _snare(rng, sr):
    n = int(0.22 * sr)
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)
    noise = rng.normals(n) * np.exp(-t * 18)
    return (0.5 * tone + 0.6 * noise).astype(np.float32)


def _hat(rng, sr):
    n = int(0.06 * sr)
    noise = rng.normals(n)
    noise = np.diff(noise, prepend=0)
    return (noise * np.exp(-np.arange(n) / sr * 70) * 0.25).astype(np.float32)


def _tone(freq, dur, kind, sr):
    n = int(dur * sr)
    t = np.arange(n) / sr
    if kind == "sine":
        y = np.sin(2 * np.pi * freq * t)
    elif kind == "square":
        y = np.sign(np.sin(2 * np.pi * freq * t)) * 0.6
    else:
        y = sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, 7))
    return y.astype(np.float32)


def _add(buf, y, at, gain=1.0):
    if at >= len(buf):
        return
    end = min(len(buf), at + len(y))
    buf[at:end] += y[: end - at] * np.float32(gain)


def song(*, bpm=100.0, sections=None, key="A", minor=True, seed=0, swing=0.0, vocal_hum=False, sr=22050):
    """(samples, truth): the fixture synth's song at `sr`, with its exact beats, bar lines and sections."""
    sections = sections or [("intro", 4, 0.3), ("build", 4, 0.6), ("drop", 8, 1.0), ("outro", 4, 0.35)]
    rng = PortableRng(seed)
    beat = 60.0 / bpm
    total_bars = sum(b for _, b, _ in sections)
    dur = total_bars * 4 * beat + 1.5
    buf = np.zeros(int(dur * sr), dtype=np.float32)
    kick, snare = _kick(sr), _snare(rng, sr)
    root = 36 + NOTE[key]          # A2 = 45 for "A" (the fixture synth adds 45: its "A" songs are in F#)
    prog = [0, 8, 3, 10] if minor else [0, 7, 9, 5]
    third = 3 if minor else 4
    beats, downbeats, secs = [], [], []
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
                at = int(bt * sr)
                if energy >= 0.25 and (q in (0, 2) or energy > 0.85):
                    _add(buf, kick, at, 0.9 * min(1.0, energy + 0.2))
                if energy >= 0.45 and q in (1, 3):
                    _add(buf, snare, at, 0.45)
                if energy >= 0.35:
                    for h in range(2 if energy < 0.8 else 4):
                        _add(buf, _hat(rng, sr), at + int(h * beat / (2 if energy < 0.8 else 4) * sr), 0.6)
                bass = _tone(_midi_hz(chord_root - 12), beat * 0.9, "saw", sr) * _env(int(beat * 0.9 * sr), 0.005, beat * 0.6, sr)
                _add(buf, bass, at, 0.18 + 0.12 * energy)
            pad_len = 4 * beat
            for iv in (0, third, 7):
                pad = _tone(_midi_hz(chord_root + 12 + iv), pad_len, "sine", sr) * _env(int(pad_len * sr), 0.15, pad_len * 0.9, sr)
                _add(buf, pad, int(bar_t * sr), 0.06 + 0.04 * (1 - energy))
            if energy >= 0.8:
                for e8 in range(8):
                    note = chord_root + 24 + [0, third, 7, 12][e8 % 4]
                    ln = beat / 2
                    lead = _tone(_midi_hz(note), ln, "square", sr) * _env(int(ln * sr), 0.003, ln * 0.4, sr)
                    _add(buf, lead, int((bar_t + e8 * beat / 2) * sr), 0.05)
            if vocal_hum and energy >= 0.5:
                ln = 2 * beat
                f0 = _midi_hz(chord_root + 24 + third)
                t = np.arange(int(ln * sr)) / sr
                vib = np.sin(2 * np.pi * 5.5 * t) * 4
                voice = np.sin(2 * np.pi * (f0 + vib) * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 700 * t) ** 2)
                _add(buf, (voice * _env(len(t), 0.05, ln, sr)).astype(np.float32), int(bar_t * sr), 0.08)
            bar_i += 1
        secs.append((label, s_t0, bar_i * 4 * beat, energy))
    tail = int(1.5 * sr)
    buf[-tail:] *= np.linspace(1, 0, tail, dtype=np.float32)
    buf /= np.float32(max(1e-6, float(np.max(np.abs(buf)))) / 0.8)
    return buf, {"bpm": bpm, "beats": beats, "downbeats": downbeats, "sections": secs, "duration": len(buf) / sr}
