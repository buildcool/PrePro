"""The iPhone app's goldens still say what the desktop decides.

PreProCore (ios/) is checked against files the desktop wrote (scripts/export_parity.py). This runs the desktop's rules
brain on each golden's own inputs (analysis, brief, direction) and expects the same music, beat grid, story and polish
as the files. When the desktop's brain changes on purpose, re-export them:

    python scripts/export_parity.py

and the iPhone's parity tests then show what the Swift port has to catch up on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prepro import knowledge as K
from prepro.assist.music import brief_for, rank_tracks
from prepro.brain.basic import BasicBrain
from prepro.schema.analysis import ProjectAnalysis
from prepro.schema.brief import CreatorBrief
from prepro.schema.plan import Direction

GOLDEN = Path(__file__).resolve().parents[2] / "ios" / "PreProCore" / "Tests" / "PreProCoreTests" / "Golden"
CASES = sorted(p.name for p in GOLDEN.iterdir() if (p / "analysis.json").exists()) if GOLDEN.is_dir() else []
STALE = "the desktop now decides differently: re-run `python scripts/export_parity.py` (then port the change to ios/)"


def _read(name: str, file: str):
    return json.loads((GOLDEN / name / file).read_text(encoding="utf-8"))


def _inputs(name: str):
    g = GOLDEN / name
    pa = ProjectAnalysis.model_validate_json((g / "analysis.json").read_text(encoding="utf-8"))
    brief = CreatorBrief.model_validate_json((g / "brief.json").read_text(encoding="utf-8"))
    d = Direction.model_validate_json((g / "direction.json").read_text(encoding="utf-8"))
    return pa, brief, d


def test_there_are_goldens():
    assert {"photo_reel", "photo_single", "day_in_life", "text_reel"} <= set(CASES)


@pytest.mark.parametrize("name", CASES)
def test_story_and_polish_are_current(name):
    pa, brief, d = _inputs(name)
    brain = BasicBrain(pa, brief)
    story = brain.story(d)
    assert story.model_dump(mode="json") == _read(name, "brain_story.json"), f"{name} story: {STALE}"
    polish = brain.polish(d, story)
    assert polish.model_dump(mode="json") == _read(name, "brain_polish.json"), f"{name} polish: {STALE}"


@pytest.mark.parametrize("name", CASES)
def test_music_and_beat_grid_are_current(name):
    pa, brief, d = _inputs(name)
    want = _read(name, "music.json")
    pb = K.playbook(d.playbook)
    need = want["grid"]["need"]
    for mode in ("front", "bed", "light"):
        mb = brief_for(mode, pb, brief.prefs.music_mood, need_secs=need, pace=d.knobs.pace)
        assert mb.model_dump(mode="json") == want[mode]["brief"], f"{name} {mode} music brief: {STALE}"
        ranked = [{"asset_id": t.asset_id, "score": t.score, "why": t.why} for t in rank_tracks(pa, mb, mode, avoid=pb.music.get("avoid", []))]
        assert ranked == want[mode]["ranked"], f"{name} {mode} ranking: {STALE}"
    grid = BasicBrain(pa, brief)._reel_grid(need, want["grid"]["playbook"])
    assert {"need": need, "playbook": want["grid"]["playbook"], **grid} == want["grid"], f"{name} beat grid: {STALE}"
