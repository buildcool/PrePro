"""Golden files for the iPhone app's parity tests: the desktop engine cuts the synthetic fixture shoots and writes what
it decided (timeline, story, polish) plus a few headline numbers, so PreProCore (Swift) can be checked against the
same decisions.

    python scripts/export_parity.py [--shoots DIR]

Writes ios/PreProCore/Tests/PreProCoreTests/Golden/<name>/{timeline,story,polish,expect}.json.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ios" / "PreProCore" / "Tests" / "PreProCoreTests" / "Golden"
CASES = {  # golden name → (fixture kind, extra brief text)
    "photo_reel": ("photo_dump", None),
    "day_in_life": ("day_in_life", None),
    "text_reel": ("aesthetic_cooking", "Text:\npov: you finally learned to cook\nand it's actually good\n"
                                       "sunday mornings hit different now\nsave this for your next slow weekend\n"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoots", default=os.environ.get("PREPRO_TEST_SHOOTS") or str(Path(tempfile.gettempdir()) / "prepro-parity"))
    args = ap.parse_args()
    from prepro.engine import build
    from prepro.fixtures import shoots

    base = Path(args.shoots) / "parity"
    for name, (kind, brief) in CASES.items():
        root = base / kind
        if not (root / ".built").exists():
            shoots.build(kind, base, sidecars=True, quick=True)
            (root / ".built").write_text("ok")
        res = build(root, brief_text=brief, render=False)
        tl = res.timeline
        out = OUT / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "timeline.json").write_text(tl.model_dump_json(indent=1), encoding="utf-8")
        (out / "story.json").write_text(res.story.model_dump_json(indent=1), encoding="utf-8")
        (out / "polish.json").write_text(res.polish.model_dump_json(indent=1), encoding="utf-8")
        texts = sorted((i for i in tl.items if i.kind == "text"), key=lambda i: i.rec_in)
        expect = {
            "playbook": tl.playbook, "duration": round(tl.duration, 3), "width": tl.width, "height": tl.height,
            "tracks": {t: len(tl.track(t)) for t in tl.tracks()},
            "v1_rec_in": [round(i.rec_in, 3) for i in tl.track("V1")],
            "texts": [i.text for i in texts],
            "suggestion_keys": sorted({s.payload.get("key", "") for s in tl.suggestions}),
        }
        (out / "expect.json").write_text(json.dumps(expect, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {tl.playbook}, {tl.duration:.2f} s, {len(tl.items)} items → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
