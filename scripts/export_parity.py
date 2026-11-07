"""Golden files for the iPhone app's parity tests: the desktop engine cuts the synthetic fixture shoots and writes what
it decided (timeline, story, polish) plus a few headline numbers, so PreProCore (Swift) can be checked against the
same decisions.

    python scripts/export_parity.py [--shoots DIR]

Writes ios/PreProCore/Tests/PreProCoreTests/Golden/<name>/: the inputs (analysis, brief, direction), what the rules
brain decided before the editor's checks (brain_story, brain_polish), the finished plans (story, polish, timeline) and a
few headline numbers (expect). Always the rules engine, whatever AI editor this PC uses, so the files never change with
the machine they were made on.
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
    "photo_single": ("photo_single", None),
    "day_in_life": ("day_in_life", None),
    "text_reel": ("aesthetic_cooking", "Text:\npov: you finally learned to cook\nand it's actually good\n"
                                       "sunday mornings hit different now\nsave this for your next slow weekend\n"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoots", default=os.environ.get("PREPRO_TEST_SHOOTS") or str(Path(tempfile.gettempdir()) / "prepro-parity"))
    args = ap.parse_args()
    from prepro import knowledge as K
    from prepro.assist.music import brief_for, rank_tracks
    from prepro.brain.basic import BasicBrain
    from prepro.config import Settings
    from prepro.engine import analysis, build
    from prepro.fixtures import shoots

    settings = Settings.load()
    settings.ai_editor = "basic"                     # the rules engine: the same goldens on every machine

    base = Path(args.shoots) / "parity"
    for name, (kind, brief) in CASES.items():
        root = base / kind
        if not (root / ".built").exists():
            shoots.build(kind, base, sidecars=True, quick=True)
            (root / ".built").write_text("ok")
        res = build(root, brief_text=brief, render=False, settings=settings,
                    routing={k: "basic" for k in settings.routing.model_dump()})
        tl = res.timeline
        out = OUT / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "timeline.json").write_text(tl.model_dump_json(indent=1), encoding="utf-8")
        (out / "story.json").write_text(res.story.model_dump_json(indent=1), encoding="utf-8")
        (out / "polish.json").write_text(res.polish.model_dump_json(indent=1), encoding="utf-8")
        # the inputs the decisions were made from, so the phone can be run on exactly the same: the analysis (no local
        # paths in it), the brief and the direction
        pa = analysis(root)
        pa.root = "."
        for a in pa.assets:
            a.info.path = a.path
        (out / "analysis.json").write_text(pa.model_dump_json(), encoding="utf-8")
        (out / "brief.json").write_text(res.brief.model_dump_json(indent=1), encoding="utf-8")
        (out / "direction.json").write_text(res.direction.model_dump_json(indent=1), encoding="utf-8")
        # the brain's own decisions, before the editor's checks fix anything: the first thing the phone must match
        brain = BasicBrain(analysis(root), res.brief)
        story = brain.story(res.direction)
        (out / "brain_story.json").write_text(story.model_dump_json(indent=1), encoding="utf-8")
        (out / "brain_polish.json").write_text(brain.polish(res.direction, story).model_dump_json(indent=1), encoding="utf-8")
        # the pieces those decisions stand on: the music brief and ranking for each soundtrack job, and the beat grid
        pb = K.playbook(res.direction.playbook)
        need = float(res.direction.knobs.target_length or 15.0)
        music = {}
        for mode in ("front", "bed", "light"):
            mb = brief_for(mode, pb, res.brief.prefs.music_mood, need_secs=need, pace=res.direction.knobs.pace)
            ranked = rank_tracks(pa, mb, mode, avoid=pb.music.get("avoid", []))
            music[mode] = {"brief": mb.model_dump(), "ranked": [{"asset_id": t.asset_id, "score": t.score, "why": t.why} for t in ranked]}
        grid = brain._reel_grid(need, res.direction.playbook)
        music["grid"] = {"need": need, "playbook": res.direction.playbook, **grid}
        (out / "music.json").write_text(json.dumps(music, indent=1, ensure_ascii=False), encoding="utf-8")
        texts = sorted((i for i in tl.items if i.kind == "text"), key=lambda i: i.rec_in)
        expect = {
            "playbook": tl.playbook, "duration": round(tl.duration, 3), "width": tl.width, "height": tl.height,
            "tracks": {t: len(tl.track(t)) for t in tl.tracks()},
            "v1_rec_in": [round(i.rec_in, 3) for i in tl.track("V1")],
            "texts": [i.text for i in texts],
            "suggestion_keys": sorted({s.payload.get("key", "") for s in tl.suggestions}),
        }
        (out / "expect.json").write_text(json.dumps(expect, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {tl.playbook}, {tl.duration:.2f} s, {len(tl.items)} items -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
