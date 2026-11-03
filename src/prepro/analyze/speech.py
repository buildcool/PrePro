"""Turn words into editorial units: segments, fillers, retakes/false starts, emphasis, tags.

These are the things an assistant editor marks on a first pass: "dead intro", "um", "she says that line
three times — use the last one", "this word is the punch".
"""

from __future__ import annotations

import re

import numpy as np
from rapidfuzz import fuzz

from ..schema.analysis import Interval, Segment, Transcript, Word

HARD_FILLERS = {
    "um", "umm", "ummm", "uh", "uhh", "uhm", "er", "erm", "ah", "ahh", "hmm", "hm", "mm", "mmm", "eh",
    "अम्म", "उम्म", "अ", "आ", "हम्म",
}
SOFT_FILLERS = {"like", "basically", "actually", "literally", "so", "okay", "right", "matlab", "toh", "yaani", "मतलब", "तो", "यानी"}
FILLER_PHRASES = ["you know", "i mean", "kind of", "sort of", "you see"]
GREETING_RE = re.compile(
    r"^(hey|hi|hello|what'?s up|namaste|namaskar|नमस्ते|नमस्कार)\b.*\b(guys|everyone|everybody|friends|doston|दोस्तों|channel|back)\b"
    r"|welcome back|welcome to my channel|it'?s me again|subscribe to my channel",
    re.I,
)
CTA_RE = re.compile(r"\b(follow|subscribe|like and share|comment below|link in (the )?bio|part (two|2)|hit the bell|फॉलो|सब्सक्राइब)\b", re.I)
NUM_RE = re.compile(r"(\d|₹|\$|%|\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|hundred|thousand|lakh|crore|million|"
                    r"zero|first|second|third|half)\b|पंद्रह|सौ|हज़ार|हजार|लाख|रुपये|rupees?)", re.I)
END_PUNCT = re.compile(r"[.!?।]$")


def _norm(w: str) -> str:
    return re.sub(r"[^\wऀ-ॿ']", "", w.lower())


def mark_fillers(words: list[Word]) -> None:
    n = len(words)
    for i, w in enumerate(words):
        t = _norm(w.text)
        if t in HARD_FILLERS:
            w.filler = True
            continue
        if t in SOFT_FILLERS:
            prev_gap = w.t0 - words[i - 1].t1 if i else 1.0
            next_gap = words[i + 1].t0 - w.t1 if i + 1 < n else 1.0
            # isolated by pauses, or repeated ("like, like") → filler; inside a sentence → keep
            rep = i + 1 < n and _norm(words[i + 1].text) == t
            if (prev_gap > 0.25 and next_gap > 0.2) or rep:
                w.filler = True
    text = " ".join(_norm(w.text) for w in words)
    for ph in FILLER_PHRASES:
        for m in re.finditer(r"\b" + re.escape(ph) + r"\b", text):
            # map char offset back to word index
            idx = text[: m.start()].count(" ")
            k = len(ph.split())
            span = words[idx: idx + k]
            if span and (idx == 0 or span[0].t0 - words[idx - 1].t1 > 0.2):
                for w in span:
                    w.filler = True


def unaccounted_speech(words: list[Word], speech: list[Interval], *, min_len: float = 0.15) -> list[Interval]:
    """VAD says someone is talking but the recogniser produced no word: usually 'um/uh' or a breathy restart."""
    covered = sorted((w.t0 - 0.06, w.t1 + 0.06) for w in words)
    out = []
    for iv in speech:
        t = iv.t0
        for a, b in covered:
            if b <= t or a >= iv.t1:
                continue
            if a - t >= min_len:
                out.append(Interval(t0=t, t1=a))
            t = max(t, b)
        if iv.t1 - t >= min_len:
            out.append(Interval(t0=t, t1=iv.t1))
    return out


def build_segments(tr: Transcript, *, max_gap: float = 0.45, max_dur: float = 12.0, max_words: int = 26) -> list[Segment]:
    segs: list[Segment] = []
    cur: list[Word] = []

    def flush():
        if not cur:
            return
        sid = f"{tr.asset_id}.s{len(segs)}"
        text = " ".join(w.text for w in cur)
        fill = sum(w.filler for w in cur) / len(cur)
        segs.append(Segment(id=sid, asset_id=tr.asset_id, t0=cur[0].t0, t1=cur[-1].t1, text=text,
                            word_ids=[w.id for w in cur], filler_ratio=round(fill, 3), lang=tr.language))
        cur.clear()

    for w in tr.words:
        if cur:
            gap = w.t0 - cur[-1].t1
            if gap >= max_gap or (w.t1 - cur[0].t0) > max_dur or len(cur) >= max_words or END_PUNCT.search(cur[-1].text) and gap > 0.12:
                flush()
        cur.append(w)
    flush()
    return segs


def _content(text: str) -> str:
    return " ".join(t for t in (_norm(x) for x in text.split()) if t and t not in HARD_FILLERS)


def mark_retakes(segs: list[Segment], *, window: int = 3, max_gap_s: float = 8.0) -> None:
    """Group segments that say the same thing (retakes) and flag false starts. Last fluent take wins."""
    group_n = 0
    for i, s in enumerate(segs):
        a = _content(s.text)
        if not a:
            continue
        for j in range(i + 1, min(len(segs), i + 1 + window)):
            o = segs[j]
            if o.t0 - s.t1 > max_gap_s:
                break
            b = _content(o.text)
            if not b:
                continue
            aw, bw = a.split(), b.split()
            prefix = 0
            for x, y in zip(aw, bw, strict=False):
                if x != y:
                    break
                prefix += 1
            sim = fuzz.token_set_ratio(a, b) if min(len(aw), len(bw)) >= 3 else 0
            partial = fuzz.partial_ratio(a, b) if len(aw) >= 3 else 0
            is_false_start = (len(aw) <= 7 and len(aw) < len(bw) and (prefix >= 2 or (prefix >= 1 and partial >= 85)))
            is_retake = sim >= 72 or (prefix >= 3 and len(bw) >= len(aw) * 0.8)
            if is_false_start or is_retake:
                g = s.retake_group or o.retake_group or f"{s.asset_id}.g{group_n}"
                if not (s.retake_group or o.retake_group):
                    group_n += 1
                s.retake_group = o.retake_group = g
                if is_false_start:
                    s.false_start = True
                break
    # rank: last take of each group (and not a false start) is preferred
    groups: dict[str, list[Segment]] = {}
    for s in segs:
        if s.retake_group:
            groups.setdefault(s.retake_group, []).append(s)
    for members in groups.values():
        members.sort(key=lambda s: s.t0)
        best = next((s for s in reversed(members) if not s.false_start), members[-1])
        rank = 1
        for s in members:
            if s is best:
                s.retake_rank = 0
            else:
                s.retake_rank = rank
                rank += 1


def tag_segments(segs: list[Segment], words: dict[str, Word]) -> None:
    for k, s in enumerate(segs):
        t = s.text.strip()
        tags = set(s.tags)
        if GREETING_RE.search(t) and k <= 2:
            tags.add("greeting")
        if CTA_RE.search(t):
            tags.add("cta")
        if t.endswith("?") or re.match(r"^(why|how|what|who|when|where|did you|have you|can you|do you)\b", t, re.I):
            tags.add("question")
        if NUM_RE.search(t):
            tags.add("numbers")
        ws = [words[w] for w in s.word_ids if w in words]
        if ws and len(ws) <= 2 and (s.t1 - s.t0) < 0.6:
            tags.add("micro")
        if ws and all(w.filler for w in ws):
            tags.add("hesitation")
        if s.false_start:
            tags.add("false_start")
        s.tags = sorted(tags)


def prosody(words: list[Word], y: np.ndarray, sr: int = 16000) -> None:
    """Per-word emphasis score from loudness + pitch relative to the speaker's baseline (z-scores)."""
    if not words or y.size == 0:
        return
    rms, pitch = [], []
    try:
        import librosa

        f0 = librosa.yin(y, fmin=70, fmax=400, sr=sr, frame_length=1024, hop_length=256)
        f0_t = np.arange(len(f0)) * 256 / sr
    except Exception:
        f0, f0_t = None, None
    for w in words:
        a, b = int(w.t0 * sr), max(int(w.t0 * sr) + 1, int(w.t1 * sr))
        seg = y[a:b]
        rms.append(20 * np.log10(np.sqrt(np.mean(seg**2)) + 1e-9) if seg.size else -90)
        if f0 is not None:
            m = (f0_t >= w.t0) & (f0_t <= w.t1)
            v = f0[m]
            v = v[(v > 70) & (v < 400)]
            pitch.append(float(np.median(v)) if v.size else np.nan)
    r = np.array(rms)
    zr = (r - np.nanmedian(r)) / (np.nanstd(r) + 1e-6)
    if pitch:
        p = np.array(pitch)
        zp = (p - np.nanmedian(p)) / (np.nanstd(p) + 1e-6)
        zp = np.nan_to_num(zp)
    else:
        zp = np.zeros_like(zr)
    for w, a, b in zip(words, zr, zp, strict=False):
        w.emphasis = round(float(max(a, 0) * 0.6 + max(b, 0) * 0.4), 3)


def segment_energy(segs: list[Segment], y: np.ndarray, sr: int = 16000) -> None:
    vals = []
    for s in segs:
        seg = y[int(s.t0 * sr): int(s.t1 * sr)]
        vals.append(20 * np.log10(np.sqrt(np.mean(seg**2)) + 1e-9) if seg.size else -90)
    if not vals:
        return
    med = float(np.median(vals))
    for s, v in zip(segs, vals, strict=False):
        s.energy = round(float(v - med), 2)


def analyse_speech(tr: Transcript, speech: list[Interval], y: np.ndarray) -> Transcript:
    """Fill fillers, hesitation pseudo-words, segments, retakes, tags and emphasis into the transcript."""
    words = sorted(tr.words, key=lambda w: w.t0)
    mark_fillers(words)
    # insert hesitation pseudo-words for VAD speech with no recognised word
    for k, iv in enumerate(unaccounted_speech(words, speech)):
        if iv.dur <= 1.2:
            words.append(Word(id=f"{tr.asset_id}.h{k}", t0=round(iv.t0, 3), t1=round(iv.t1, 3), text="[hesitation]", conf=0.3, filler=True))
    words.sort(key=lambda w: w.t0)
    tr.words = words
    prosody([w for w in words if not w.text.startswith("[")], y)
    segs = build_segments(tr)
    wm = tr.word_map()
    mark_retakes(segs)
    tag_segments(segs, wm)
    segment_energy(segs, y)
    tr.segments = segs
    return tr
