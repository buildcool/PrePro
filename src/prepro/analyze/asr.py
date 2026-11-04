"""Speech: VAD (Silero, bundled) + recognisers → word-level transcript.

Backends, in ``auto`` order:
  1. ``sidecar``      — ``<clip>.transcript.json`` / ``.srt`` / ``.vtt`` next to the clip (subtitles you already have)
  2. ``faster-whisper`` — best quality, multilingual; models download on first use (huggingface.co)
  3. ``pocketsphinx`` — offline English fallback (bundled model), good timings, rough words
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..schema.analysis import Interval, Transcript, Word

SR = 16000
VERBATIM_PROMPT = "Umm, so, uh, I mean, like, you know... Okay. Hmm, let me think. Uh, yeah."


@dataclass
class RawWord:
    text: str
    t0: float
    t1: float
    conf: float = 1.0


def load_wav16(path: Path) -> np.ndarray:
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        from ..fixtures.audio import resample

        y = resample(y, sr, SR)
    return y


# ---------------------------------------------------------------- VAD
def vad(y: np.ndarray, *, min_silence_ms: int = 250, pad_ms: int = 40, threshold: float = 0.5) -> list[Interval]:
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        ts = get_speech_timestamps(y, VadOptions(threshold=threshold, min_silence_duration_ms=min_silence_ms,
                                                 speech_pad_ms=pad_ms, min_speech_duration_ms=120))
        return [Interval(t0=s["start"] / SR, t1=s["end"] / SR) for s in ts]
    except Exception:
        return energy_vad(y)


def energy_vad(y: np.ndarray, *, hop: float = 0.02, thr_db: float | None = None) -> list[Interval]:
    n = int(hop * SR)
    if len(y) < n:
        return []
    frames = y[: len(y) // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    if thr_db is None:
        floor = np.percentile(db, 10)
        thr_db = max(floor + 15, -50)
    on = db > thr_db
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if (i - start) * hop >= 0.12:
                out.append(Interval(t0=start * hop, t1=i * hop))
            start = None
    if start is not None:
        out.append(Interval(t0=start * hop, t1=len(on) * hop))
    # merge gaps < 250 ms
    merged: list[Interval] = []
    for iv in out:
        if merged and iv.t0 - merged[-1].t1 < 0.25:
            merged[-1].t1 = iv.t1
        else:
            merged.append(iv)
    return merged


def invert(intervals: list[Interval], total: float, min_len: float = 0.0) -> list[Interval]:
    out, t = [], 0.0
    for iv in sorted(intervals, key=lambda i: i.t0):
        if iv.t0 - t >= min_len and iv.t0 > t:
            out.append(Interval(t0=t, t1=iv.t0))
        t = max(t, iv.t1)
    if total - t >= min_len and total > t:
        out.append(Interval(t0=t, t1=total))
    return out


# ---------------------------------------------------------------- sidecars
_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_TS_SHORT = re.compile(r"(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+)[,.](\d+)")


def _spread(text: str, t0: float, t1: float) -> list[RawWord]:
    ws = text.split()
    if not ws:
        return []
    total = sum(len(w) + 1 for w in ws)
    out, t = [], t0
    for w in ws:
        d = (t1 - t0) * (len(w) + 1) / total
        out.append(RawWord(w, t, t + d * 0.92, 0.9))
        t += d
    return out


def read_sidecar(path: Path) -> tuple[list[RawWord], str | None]:
    if path.name.endswith(".transcript.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        words: list[RawWord] = []
        for seg in data.get("segments", []):
            if seg.get("words"):
                words += [RawWord(w["text"], float(w["t0"]), float(w["t1"]), float(w.get("conf", 1.0))) for w in seg["words"]]
            else:
                words += _spread(seg.get("text", ""), float(seg["t0"]), float(seg["t1"]))
        return words, data.get("language")
    text = path.read_text(encoding="utf-8", errors="replace")
    words = []
    for block in re.split(r"\n\s*\n", text):
        m = _TS.search(block)
        if m:
            g = [int(x) for x in m.groups()]
            t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 10 ** len(m.group(4))
            t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 10 ** len(m.group(8))
        else:
            m = _TS_SHORT.search(block)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            t0 = g[0] * 60 + g[1] + g[2] / 10 ** len(m.group(3))
            t1 = g[3] * 60 + g[4] + g[5] / 10 ** len(m.group(6))
        lines = [ln for ln in block.splitlines() if "-->" not in ln and not ln.strip().isdigit() and ln.strip() and ln.strip() != "WEBVTT"]
        txt = re.sub(r"<[^>]+>", "", " ".join(lines)).strip()
        words += _spread(txt, t0, t1)
    return words, None


# ---------------------------------------------------------------- recognisers
_WHISPER_CACHE: dict = {}


def whisper_available(model: str = "small") -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    from ..speech_models import cached

    return cached(model)


def transcribe_whisper(y: np.ndarray, *, model: str = "small", device: str = "auto", compute_type: str = "auto",
                       language: str | None = None, verbatim: bool = True) -> tuple[list[RawWord], str | None]:
    from faster_whisper import WhisperModel

    key = (model, device, compute_type)
    if key not in _WHISPER_CACHE:
        dev = device
        if dev == "auto":
            try:
                import ctranslate2

                dev = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                dev = "cpu"
        ct = compute_type if compute_type != "auto" else ("float16" if dev == "cuda" else "int8")
        _WHISPER_CACHE[key] = WhisperModel(model, device=dev, compute_type=ct)
    m = _WHISPER_CACHE[key]
    segments, info = m.transcribe(
        y, language=language, word_timestamps=True, vad_filter=True,
        initial_prompt=VERBATIM_PROMPT if verbatim and (language in (None, "en")) else None,
        condition_on_previous_text=False,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append(RawWord(w.word.strip(), float(w.start), float(w.end), float(w.probability)))
    return words, getattr(info, "language", language)


def transcribe_pocketsphinx(y: np.ndarray, speech: list[Interval]) -> list[RawWord]:
    from pocketsphinx import Decoder

    try:
        dec = Decoder(samprate=SR, loglevel="FATAL")
    except Exception:
        dec = Decoder(samprate=SR)
    words: list[RawWord] = []
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    # decode per VAD chunk (padded) — faster and keeps timings anchored
    chunks = merge_close(speech, gap=0.6, pad=0.15, total=len(y) / SR)
    for iv in chunks:
        a, b = int(iv.t0 * SR), int(iv.t1 * SR)
        dec.start_utt()
        dec.process_raw(pcm[a:b].tobytes(), full_utt=True)
        dec.end_utt()
        for s in dec.seg():
            w = s.word
            if w.startswith("<") or w.startswith("[") or w.startswith("++"):
                continue
            w = re.sub(r"\(\d+\)$", "", w)
            words.append(RawWord(w, iv.t0 + s.start_frame / 100.0, iv.t0 + (s.end_frame + 1) / 100.0, float(np.exp(min(0, s.prob / 10000.0)))))
    return words


def merge_close(ivs: list[Interval], *, gap: float, pad: float, total: float) -> list[Interval]:
    out: list[Interval] = []
    for iv in sorted(ivs, key=lambda i: i.t0):
        a, b = max(0.0, iv.t0 - pad), min(total, iv.t1 + pad)
        if out and a - out[-1].t1 < gap:
            out[-1].t1 = max(out[-1].t1, b)
        else:
            out.append(Interval(t0=a, t1=b))
    return out


def transcribe(asset_id: str, wav16: Path, *, backend: str = "auto", sidecar: Path | None = None, model: str = "small",
               device: str = "auto", compute_type: str = "auto", language: str | None = None, verbatim: bool = True,
               speech: list[Interval] | None = None) -> Transcript:
    """Return a word-level :class:`Transcript` (segments are built later by :mod:`analyze.speech`)."""
    y = load_wav16(wav16)
    speech = speech if speech is not None else vad(y)
    note = ""
    lang = language
    words: list[RawWord] = []
    used = "none"
    order = [backend] if backend != "auto" else ["sidecar", "faster-whisper", "pocketsphinx"]
    for b in order:
        try:
            if b == "sidecar" and sidecar and sidecar.exists():
                words, lang2 = read_sidecar(sidecar)
                lang = lang or lang2
                used, note = "sidecar", "imported subtitles/transcript (not speech recognition)"
                break
            if b == "faster-whisper" and (backend == "faster-whisper" or whisper_available(model)):
                words, lang = transcribe_whisper(y, model=model, device=device, compute_type=compute_type, language=language, verbatim=verbatim)
                used = "faster-whisper"
                break
            if b == "pocketsphinx" and (lang in (None, "en") or backend == "pocketsphinx"):
                if not speech:
                    used = "pocketsphinx"
                    break
                words = transcribe_pocketsphinx(y, speech)
                lang = lang or "en"
                used, note = "pocketsphinx", "offline fallback recogniser: timings good, words approximate"
                break
        except Exception as e:  # keep going down the list
            note = f"{b} failed: {e}"
            continue
    out = [Word(id=f"{asset_id}.w{i}", t0=round(w.t0, 3), t1=round(max(w.t1, w.t0 + 0.04), 3), text=w.text, conf=round(w.conf, 3))
           for i, w in enumerate(sorted(words, key=lambda w: w.t0)) if w.text]
    return Transcript(asset_id=asset_id, backend=used, language=lang, words=out, note=note)
