"""Measure speech recognition on real speech with a known transcript: word error rate per backend.

    python scripts/check_asr.py                 # every backend that is available
    python scripts/check_asr.py --model base    # a different Whisper model

Uses the JFK clip from the real test media (`prepro testmedia fetch`), whose words are known exactly. Everything
runs locally; nothing is uploaded. Report the numbers as measured — never round a failure into a pass.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import time
from pathlib import Path

REFERENCE = {
    "speech/jfk.flac": "and so my fellow americans ask not what your country can do for you ask what you can do for your country",
}


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z' ]+", " ", text.lower()).split()


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(1, len(ref))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small")
    args = ap.parse_args()
    from prepro.analyze import asr
    from prepro.fixtures import realmedia
    from prepro.media.proxy import extract_audio
    from prepro.speech_models import cached

    root = realmedia.cache_dir()
    backends = ["pocketsphinx"] + (["faster-whisper"] if cached(args.model) else [])
    if not cached(args.model):
        print(f"(Whisper {args.model} isn't downloaded — `prepro models --download {args.model}` to include it)")
    worst = 0.0
    with tempfile.TemporaryDirectory() as td:
        for rel, ref in REFERENCE.items():
            src = root / rel
            if not src.exists():
                print(f"missing {src} — run `prepro testmedia fetch`")
                return 2
            wav = Path(td) / "a.wav"
            extract_audio(src, wav, sr=16000)
            for b in backends:
                t0 = time.time()
                tr = asr.transcribe("T", wav, backend=b, model=args.model)
                hyp = " ".join(w.text for w in tr.words)
                e = wer(words(ref), words(hyp))
                worst = max(worst, e) if b == "faster-whisper" else worst
                print(f"{rel} · {tr.backend:14s} WER {e:6.1%} · {time.time() - t0:5.1f} s · {tr.note}")
                print(f"    heard: {hyp}")
    return 0 if worst <= 0.1 else 1


if __name__ == "__main__":
    sys.exit(main())
