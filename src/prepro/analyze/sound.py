"""Audio health report (loudness, noise, SNR, clipping, hum, wind) and music analysis
(BPM, beats, downbeats, sections, energy curve, key/mode, mood)."""

from __future__ import annotations

import numpy as np

from ..schema.analysis import AudioReport, Interval, MusicInfo, Section

_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def audio_report(y: np.ndarray, sr: int, speech: list[Interval], *, music: bool = False) -> AudioReport:
    rep = AudioReport()
    if y.size < sr // 10:
        return rep
    try:
        import pyloudnorm as pyln

        if len(y) / sr >= 0.5:
            rep.lufs = round(float(pyln.Meter(sr).integrated_loudness(y.astype(np.float64))), 2)
    except Exception:
        pass
    rep.peak_db = round(_db(float(np.max(np.abs(y)))), 2)
    rep.clipping_ratio = round(float(np.mean(np.abs(y) > 0.985)), 5)
    hop = int(0.05 * sr)
    frames = y[: len(y) // hop * hop].reshape(-1, hop)
    rms = np.sqrt((frames**2).mean(axis=1)) + 1e-9
    t = np.arange(len(rms)) * 0.05
    in_speech = np.zeros(len(rms), bool)
    for iv in speech:
        in_speech |= (t >= iv.t0) & (t < iv.t1)
    total = len(y) / sr
    rep.speech_ratio = round(sum(iv.dur for iv in speech) / max(total, 1e-6), 3)
    quiet = rms[~in_speech] if (~in_speech).sum() > 10 else rms
    rep.noise_floor_db = round(_db(float(np.percentile(quiet, 20))), 2)
    if in_speech.sum() > 5:
        rep.snr_db = round(_db(float(np.median(rms[in_speech]))) - rep.noise_floor_db, 2)
    # hum: narrow peaks at 50/60 Hz (+harmonics) in non-speech
    mask = np.zeros(len(y), bool)
    mask[: len(in_speech) * hop] = np.repeat(in_speech, hop)
    seg = y[~mask] if (~in_speech).sum() > 20 else y
    if seg.size > sr and not music:
        spec = np.abs(np.fft.rfft(seg[: sr * 10] * np.hanning(min(len(seg), sr * 10))))
        freqs = np.fft.rfftfreq(min(len(seg), sr * 10), 1 / sr)
        for base in (50, 60):
            band = (freqs > base - 2) & (freqs < base + 2)
            neigh = (freqs > base - 15) & (freqs < base + 15) & ~band
            if band.any() and neigh.any() and spec[band].max() > 8 * np.median(spec[neigh]) and _db(spec[band].max() / len(seg)) > -80:
                rep.hum_hz = float(base)
        low = spec[(freqs > 20) & (freqs < 150)].sum()
        allp = spec[(freqs > 20)].sum() + 1e-9
        rep.wind = round(float(low / allp), 3)
    issues = []
    if rep.noise_floor_db is not None and rep.noise_floor_db > -42 and rep.speech_ratio > 0.2:
        issues.append(f"noisy background ({rep.noise_floor_db:.0f} dBFS floor)")
    if rep.snr_db is not None and rep.snr_db < 15 and rep.speech_ratio > 0.2:
        issues.append(f"voice not clear (SNR {rep.snr_db:.0f} dB)")
    if rep.clipping_ratio > 0.001:
        issues.append(f"clipping ({rep.clipping_ratio * 100:.2f}% samples)")
    if rep.hum_hz:
        issues.append(f"{rep.hum_hz:.0f} Hz hum")
    if rep.wind > 0.55 and rep.speech_ratio > 0.2:
        issues.append("possible wind/rumble")
    rep.issues = issues
    return rep


def music_info(y: np.ndarray, sr: int) -> MusicInfo:
    import librosa

    if y.size < sr * 2:
        return MusicInfo()
    y = y[: sr * 600]
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, units="frames", tightness=120)
    bpm = float(np.atleast_1d(tempo)[0])
    beats = np.asarray(beats, dtype=int)
    # librosa tends to double/halve: prefer 70–180 BPM (the beat list follows, so beats and BPM always agree)
    while bpm > 180:
        bpm /= 2
        beats = beats[::2]
    while 0 < bpm < 70:
        bpm *= 2
        beats = np.unique(np.r_[beats, (beats[:-1] + beats[1:]) // 2])
    times = librosa.frames_to_time(beats, sr=sr)
    # downbeat phase (which beat mod 4 starts the bar): chords change on the bar line and the kick is heaviest there.
    # Low end alone cannot tell beat 1 from beat 3 when the kick plays both, so the harmonic change entering each beat
    # decides, with low-frequency energy as the tie-break
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low = S[freqs < 150].sum(axis=0)
    bidx = beats[beats < S.shape[1]]
    change = np.zeros(len(bidx))
    if len(bidx) > 8:
        chroma = librosa.feature.chroma_stft(S=S**2, sr=sr, n_fft=2048, hop_length=512)
        ends = list(bidx[1:]) + [S.shape[1]]
        cs = np.stack([np.median(chroma[:, a:max(a + 1, b)], axis=1) for a, b in zip(bidx, ends, strict=True)], axis=1)
        cs = cs / (np.linalg.norm(cs, axis=0, keepdims=True) + 1e-9)
        change = np.r_[0.0, np.linalg.norm(np.diff(cs, axis=1), axis=0)]
    lows = [float(low[bidx[ph::4]].mean()) if len(bidx[ph::4]) else 0.0 for ph in range(4)]
    chords = [float(change[ph::4][1 if ph == 0 else 0:].mean()) if len(change[ph::4]) > 1 else 0.0 for ph in range(4)]
    score = 0.5 * np.array(lows) / (max(lows) + 1e-9) + np.array(chords) / (max(chords) + 1e-9)
    ph = int(np.argmax(score)) if any(lows) or any(chords) else 0
    downbeats = times[ph::4]
    # energy curve @2 Hz
    hop = sr // 2
    frames = y[: len(y) // hop * hop].reshape(-1, hop)
    rms = np.sqrt((frames**2).mean(axis=1))
    lo, hi = np.percentile(rms, 5), np.percentile(rms, 98)
    curve = np.clip((rms - lo) / (hi - lo + 1e-9), 0, 1)
    dur = len(y) / sr
    sections = _sections(y, sr, curve, downbeats, dur)
    chroma = librosa.feature.chroma_cqt(y=y[: sr * 120], sr=sr).mean(axis=1)
    best = (-2.0, "C", "major")
    for k in range(12):
        for prof, mode in ((_MAJOR, "major"), (_MINOR, "minor")):
            c = float(np.corrcoef(np.roll(prof, k), chroma)[0, 1])
            if c > best[0]:
                best = (c, _KEYS[k], mode)
    cent = float(librosa.feature.spectral_centroid(y=y[: sr * 60], sr=sr).mean())
    bright = min(1.0, cent / 4000.0)
    info = MusicInfo(bpm=round(bpm, 2), beats=[round(float(t), 3) for t in times], downbeats=[round(float(t), 3) for t in downbeats],
                     sections=sections, energy_curve=[round(float(v), 3) for v in curve], key=best[1], mode=best[2], brightness=round(bright, 3))
    info.mood_tags = mood_tags(info)
    return info


def _sections(y: np.ndarray, sr: int, curve: np.ndarray, downbeats: np.ndarray, dur: float) -> list[Section]:
    import librosa

    k = int(np.clip(round(dur / 8), 3, 8))
    try:
        hop = 2048
        mf = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop)
        ch = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop)
        rm = librosa.feature.rms(y=y, hop_length=hop) * 30
        feat = np.vstack([mf / (np.std(mf) + 1e-9), ch, rm])
        bounds = librosa.segment.agglomerative(feat, k)
        btimes = sorted(set([0.0] + [float(t) for t in librosa.frames_to_time(bounds, sr=sr, hop_length=hop)] + [dur]))
    except Exception:
        btimes = list(np.linspace(0, dur, k + 1))
    # snap inner bounds to nearest downbeat
    if len(downbeats):
        snapped = [0.0]
        for b in btimes[1:-1]:
            j = int(np.argmin(np.abs(downbeats - b)))
            snapped.append(float(downbeats[j]))
        snapped.append(dur)
        btimes = sorted(set(round(b, 3) for b in snapped))
    # drop tiny sections
    merged = [btimes[0]]
    for b in btimes[1:]:
        if b - merged[-1] < 4.0 and b != btimes[-1]:
            continue
        merged.append(b)
    if merged[-1] != btimes[-1]:
        merged[-1] = btimes[-1]
    secs = []
    for a, b in zip(merged[:-1], merged[1:], strict=False):
        e = float(curve[int(a * 2): max(int(a * 2) + 1, int(b * 2))].mean()) if len(curve) else 0.0
        secs.append(Section(t0=round(a, 3), t1=round(b, 3), label="verse", energy=round(e, 3)))
    if not secs:
        return []
    es = np.array([s.energy for s in secs])
    lo, hi = float(es.min()), float(es.max())
    rel = (es - lo) / (hi - lo + 1e-9)
    top = int(np.argmax(es))
    contrast = hi - lo
    for i, s in enumerate(secs):
        if i == top and contrast > 0.12:
            s.label = "drop" if contrast > 0.3 and es[top] > 0.5 else "chorus"
        elif i + 1 == top and contrast > 0.12 and rel[i] < 0.85:
            s.label = "build"
        elif i == 0 and rel[i] < 0.5:
            s.label = "intro"
        elif i == len(secs) - 1 and rel[i] < 0.5:
            s.label = "outro"
        elif rel[i] < 0.3:
            s.label = "break"
        else:
            s.label = "verse"
    return secs


def mood_tags(m: MusicInfo) -> list[str]:
    e = float(np.mean(m.energy_curve)) if m.energy_curve else 0.5
    tags = []
    if m.bpm < 95 and e < 0.55:
        tags += ["chill", "calm"]
    if m.bpm >= 125 and e > 0.5:
        tags += ["hype", "energetic"]
    if m.mode == "major" and 95 <= m.bpm < 135:
        tags += ["happy", "upbeat"]
    if m.mode == "minor" and m.bpm < 100:
        tags += ["moody"]
    has_drop = any(s.label == "drop" for s in m.sections)
    if has_drop and m.bpm >= 100 and max((s.energy for s in m.sections), default=0) >= 0.75:
        tags += ["epic", "build-drop"]
    elif has_drop:
        tags += ["build-drop"]
    if m.brightness < 0.25 and e < 0.5:
        tags += ["warm", "aesthetic"]
    return sorted(set(tags)) or ["neutral"]


def musicality(y: np.ndarray, sr: int) -> float:
    """0..1 'is this music?' score: beat regularity + harmonic stability (used to classify audio files)."""
    import librosa

    if y.size < sr * 3:
        return 0.0
    seg = y[: sr * 60]
    onset = librosa.onset.onset_strength(y=seg, sr=sr)
    if onset.size < 16:
        return 0.0
    ac = librosa.autocorrelate(onset - onset.mean())
    ac = ac / (ac[0] + 1e-9)
    lags = slice(int(sr / 512 * 60 / 180), int(sr / 512 * 60 / 60))
    rhythm = float(np.max(ac[lags])) if ac.size > lags.stop else 0.0
    flat = float(np.mean(librosa.feature.spectral_flatness(y=seg)))
    return float(np.clip(rhythm * 1.2 + (0.3 - flat) * 0.8, 0, 1))


def impacts(y: np.ndarray, sr: int, *, min_gap: float = 0.8, word_starts: list[float] | None = None) -> list[tuple[float, float]]:
    """Game/action impacts — explosions, gunshots, hits — as (time, strength in dB above the recent level).

    A sharp jump in level that is either sub-bass heavy (booms: a third or more of the energy under 60 Hz) or noise-like and very sharp
    (shots: high spectral flatness, ≥ 15 dB jump). Speech onsets are tonal with little bass; breathy consonants look
    noise-like for a moment, so a noise-like jump right at a transcribed word start is not an impact."""
    starts = np.array(sorted(word_starts or []), dtype=float)
    if y.ndim > 1:
        y = y.mean(axis=1)
    hop = max(1, sr // 50)                       # 20 ms
    n = len(y) // hop
    if n < 30:
        return []
    fr = y[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-9)
    win = 2 * hop
    hann = np.hanning(win)
    freqs = np.fft.rfftfreq(win, 1 / sr)
    out: list[tuple[float, float]] = []
    for i in range(25, n):
        jump = db[i] - float(np.median(db[i - 25: i]))
        if jump < 9 or db[i] < -32:
            continue
        seg = y[i * hop: i * hop + win]
        if len(seg) < win:
            break
        sp = np.abs(np.fft.rfft(seg * hann)) ** 2 + 1e-12
        low = float(sp[freqs < 60].sum() / sp.sum())      # sub-bass: booms live here, voices (≥ 85 Hz) don't
        flat = float(np.exp(np.mean(np.log(sp))) / np.mean(sp))
        t = i * hop / sr
        boom = low >= 0.3
        shot = flat >= 0.35 and jump >= 15
        if not boom and not shot:
            continue
        if not boom and starts.size and np.min(np.abs(starts - t)) < 0.2:
            continue                                  # a voice starting, not a gunshot
        if out and t - out[-1][0] < min_gap:
            if jump > out[-1][1]:
                out[-1] = (out[-1][0], round(float(jump), 1))
            continue
        out.append((round(t, 3), round(float(jump), 1)))
    return out
