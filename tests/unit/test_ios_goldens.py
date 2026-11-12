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
from prepro.schema.plan import Direction, PolishPlan, StoryPlan
from prepro.timeline import captions as C
from prepro.timeline.compiler import compile_timeline

GOLDEN = Path(__file__).resolve().parents[2] / "ios" / "PreProCore" / "Tests" / "PreProCoreTests" / "Golden"
METRICS = GOLDEN.parents[2] / "Sources" / "PreProCore" / "Resources" / "text_metrics.json"
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


@pytest.mark.parametrize("name", CASES)
def test_timeline_is_current(name):
    pa, brief, d = _inputs(name)
    pa.root = ""                                              # the goldens carry no shoot folder: nothing is read from disk
    story = StoryPlan.model_validate_json((GOLDEN / name / "story.json").read_text(encoding="utf-8"))
    polish = PolishPlan.model_validate_json((GOLDEN / name / "polish.json").read_text(encoding="utf-8"))
    tl = compile_timeline(pa, d, story, polish, brief)
    assert tl.model_dump(mode="json") == _read(name, "timeline.json"), f"{name} timeline: {STALE}"


def test_text_metrics_are_current():
    """The phone measures words with the advance table in text_metrics.json: it must be what the desktop measures."""
    from PIL import ImageFont

    from prepro.config import assets_dir

    m = json.loads(METRICS.read_text(encoding="utf-8"))
    assert m["safe"] == {k: list(v) for k, v in C.SAFE.items()}, STALE
    assert m["glue"] == sorted(C.GLUE), STALE
    assert m["libass_width"] == C.LIBASS_WIDTH, STALE
    assert m["styles"] == {k: {"font": v[0], "size": v[1], "primary": v[2], "outline": v[3], "bold": v[4], "upper": v[5]}
                           for k, v in C.STYLES.items()}, STALE
    assert set(m["fonts"]) == {s[0] for s in C.STYLES.values()}, STALE
    for name, f in m["fonts"].items():
        files = sorted((assets_dir() / "fonts").glob(name.replace(" ", "") + "*.ttf"))
        assert files and files[0].name == f["file"], f"{name}: {STALE}"
        font = ImageFont.truetype(str(files[0]), 100, layout_engine=ImageFont.Layout.BASIC)
        asc, desc = font.getmetrics()
        assert (asc + desc, font.getlength("\U0010fffd")) == (f["line_h"], f["notdef"]), f"{name}: {STALE}"
        for cp, w in f["advances"].items():
            assert font.getlength(chr(int(cp))) == w, f"{name} U+{int(cp):04X}: {STALE}"
        # what the phone computes — the plain sum of the advances — is what Pillow measures for a whole line
        for t in ("POV: you finally took the trip you kept postponing", "Goa → Jaipur · Oct 2026", "AV To Wa", "नमस्ते 😀"):
            assert font.getlength(t) == sum(f["advances"].get(str(ord(ch)), f["notdef"]) for ch in t), (name, t)


def test_text_blocks_are_current():
    for c in json.loads((GOLDEN / "text_blocks.json").read_text(encoding="utf-8")):
        lines, h = C.text_block(c["text"], c["style"], c["width"], c["height"], c["scale"])
        assert (lines, h) == (c["lines"], c["block"]), f"{c['text']}: {STALE}"


def _parity():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import export_parity

    return export_parity


PHOTOS = GOLDEN / "photos"


@pytest.mark.skipif(not (PHOTOS / "measures.json").exists(), reason="no photo goldens")
def test_photo_measures_are_current():
    """The desktop still measures the test photos as the phone's goldens say: Pillow's thumbnail to the bit, the burst
    hash, the flags, and the numbers (within the last rounded digit: numpy squares a float32 with the C library's powf)."""
    ep = _parity()
    want = {c["name"]: c for c in json.loads((PHOTOS / "measures.json").read_text(encoding="utf-8"))}
    assert [c[0] for c in ep.PHOTO_CASES] == list(want), STALE
    for case in ep.PHOTO_CASES:
        got, w = ep.photo_case(*case), want[case[0]]
        assert {k: got[k] for k in ("picture", "orientation", "faces", "stored", "probe", "thumb", "thumb_fnv")} == \
            {k: w[k] for k in ("picture", "orientation", "faces", "stored", "probe", "thumb", "thumb_fnv")}, f"{case[0]}: {STALE}"
        g, m = got["measures"], w["measures"]
        assert (g["phash"], g["flags"], g["quality"]) == (m["phash"], m["flags"], m["quality"]), f"{case[0]}: {STALE}"
        for k, tol in (("brightness", 0.0011), ("contrast", 0.0011), ("sharpness", 0.011), ("aesthetic", 0.0011)):
            assert abs(g[k] - m[k]) <= tol, f"{case[0]} {k}: {STALE}"


@pytest.mark.skipif(not (PHOTOS / "shoot.json").exists(), reason="no photo goldens")
def test_photo_shoot_is_current():
    """The test day of photos is still analysed and cut the way the phone's golden says: bursts, flags, days, places,
    the genre, then the direction, story, polish and timeline."""
    ep = _parity()
    got, want = ep.shoot_golden(), json.loads((PHOTOS / "shoot.json").read_text(encoding="utf-8"))
    assert got["photos"] == want["photos"], STALE
    ga, wa = got["analysis"], want["analysis"]
    assert [a["id"] for a in ga["assets"]] == [a["id"] for a in wa["assets"]], STALE
    for aid, c in wa["clips"].items():
        g = ga["clips"][aid]
        assert {k: g[k] for k in ("place", "place_cluster", "day_index", "order_key")} == \
            {k: c[k] for k in ("place", "place_cluster", "day_index", "order_key")}, f"{aid}: {STALE}"
        for s, t in zip(g["shots"], c["shots"], strict=True):
            assert {k: s[k] for k in ("phash", "flags", "dup_group", "dup_rank", "faces", "track")} == \
                {k: t[k] for k in ("phash", "flags", "dup_group", "dup_rank", "faces", "track")}, f"{aid}: {STALE}"
            assert abs(s["aesthetic"] - t["aesthetic"]) <= 0.0011 and abs(s["sharpness"] - t["sharpness"]) <= 0.011, f"{aid}: {STALE}"
    assert ga["stats"] == wa["stats"] and ga["genres"] == wa["genres"], STALE
    for k in ("brief", "direction", "story", "polish", "timeline"):
        assert got[k] == want[k], f"shoot {k}: {STALE}"


@pytest.mark.skipif(not (PHOTOS / "places.json").exists(), reason="no photo goldens")
def test_place_names_are_current():
    pytest.importorskip("reverse_geocoder")
    assert _parity().places_golden() == json.loads((PHOTOS / "places.json").read_text(encoding="utf-8")), STALE


SONGS = sorted(p.stem for p in (GOLDEN / "songs").glob("*.json")) if (GOLDEN / "songs").is_dir() else []


@pytest.mark.parametrize("name", SONGS)
def test_song_analysis_is_current(name):
    """The desktop still hears the test songs the way the goldens say (within float noise: numpy's sin/exp can differ by
    a few ULPs between CPUs): the same tempo bin and beat frames, the same music analysis."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from export_parity import song_golden

    got, want = song_golden(name), _read("songs", f"{name}.json")
    assert got["params"] == want["params"] and got["samples"] == want["samples"]
    assert max(abs(got["probe"][k] - v) for k, v in want["probe"].items()) < 1e-6, f"{name} synth: {STALE}"
    assert max(abs(a - b) for a, b in zip(got["onset"], want["onset"], strict=True)) < 1e-3, f"{name} onset: {STALE}"
    assert (got["tempo"], got["beat_frames"]) == (want["tempo"], want["beat_frames"]), f"{name} beats: {STALE}"
    g, w = got["music"], want["music"]
    assert (g["bpm"], g["key"], g["mode"], g["mood_tags"]) == (w["bpm"], w["key"], w["mode"], w["mood_tags"]), f"{name}: {STALE}"
    for k in ("beats", "downbeats"):
        assert len(g[k]) == len(w[k]) and max((abs(a - b) for a, b in zip(g[k], w[k], strict=True)), default=0) < 0.024, f"{name} {k}: {STALE}"
    assert [s["label"] for s in g["sections"]] == [s["label"] for s in w["sections"]], f"{name} sections: {STALE}"
    assert max(abs(a["t0"] - b["t0"]) for a, b in zip(g["sections"], w["sections"], strict=True)) < 0.05
    assert max(abs(a - b) for a, b in zip(g["energy_curve"], w["energy_curve"], strict=True)) < 0.01
    if "from_44k" in want:                                    # the same song made at 44.1 kHz, decoded like librosa.load
        f, h = got["from_44k"]["music"], want["from_44k"]["music"]
        assert (got["from_44k"]["samples"], f["bpm"], len(f["beats"])) == (want["from_44k"]["samples"], h["bpm"], len(h["beats"]))
        assert max(abs(a - b) for a, b in zip(f["beats"], h["beats"], strict=True)) < 0.024, f"{name} at 44.1 kHz: {STALE}"
        assert [s["label"] for s in f["sections"]] == [s["label"] for s in h["sections"]], f"{name} at 44.1 kHz: {STALE}"
