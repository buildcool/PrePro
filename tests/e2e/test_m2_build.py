"""M2: shoot → plan → timeline (→ render). Checked against ground truth, the brief and EditLint."""

from __future__ import annotations

import json
import subprocess

import pytest
from tests.conftest import needs_ffmpeg, needs_tts, truth

from prepro.engine import build
from prepro.schema.media import AssetKind

pytestmark = [needs_tts, needs_ffmpeg]


def _a1_overlaps(tl, asset_id, t0, t1):
    return sum(max(0.0, min(i.src_out, t1) - max(i.src_in, t0)) for i in tl.items if i.track == "A1" and i.asset_id == asset_id)


@pytest.fixture(scope="module")
def travel_brief(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    return root, build(root, render=False)


def test_brief_is_fully_met(travel_brief):
    _, res = travel_brief
    errors = [f for f in res.lint if f.severity == "error"]
    assert not errors, [f.msg for f in errors]
    from prepro.lint.editlint import compliance

    items = compliance(res.timeline, __import__("prepro.engine", fromlist=["analysis"]).analysis(res.brief and travel_brief[0]), res.direction, res.brief)
    assert items and all(ci.ok for ci in items), [(ci.rule.kind, ci.detail) for ci in items if not ci.ok]


def test_editor_decisions_match_ground_truth(travel_brief):
    root, res = travel_brief
    gt = truth(root)
    tl = res.timeline
    from prepro.engine import analysis

    pa = analysis(root)
    by_path = {a.path: a for a in pa.assets}
    # every line a pro editor would cut is out; every keeper line from the used clips is in
    for rel, clip in gt["clips"].items():
        if clip["kind"] != "aroll":
            continue
        aid = by_path[rel].id
        for line in clip["lines"]:
            ov = _a1_overlaps(tl, aid, line["t0"], line["t1"])
            if not line["keep"]:
                assert ov < 0.2, (rel, line["kind"], line["text"], ov)
    # hook first
    first = sorted((i for i in tl.items if i.track == "A1"), key=lambda i: i.rec_in)[0]
    hook_line = next(ln for ln in gt["clips"]["footage/day1/IMG_2041.mp4"]["lines"] if ln["kind"] == "hook")
    # the hook comes from the hook line and keeps its payload (it may enter late, at the clause with the numbers)
    assert first.asset_id == by_path["footage/day1/IMG_2041.mp4"].id
    assert hook_line["t0"] - 0.4 <= first.src_in <= hook_line["t1"] - 2.0
    # bad shots never used
    used = {i.asset_id for i in tl.items if i.track in ("V1", "V2")}
    for rel in gt["expect"]["bad_shots"]:
        assert by_path[rel].id not in used, rel
    # slow-mo on the 60 fps jump, meme after "Twenty!", CTA text, requested song only
    jump = by_path["footage/day1/IMG_2046.mp4"].id
    assert any(i.asset_id == jump and abs(i.speed - 0.5) < 0.01 for i in tl.items if i.track == "V1")
    assert any(i.role == "meme" for i in tl.items)
    assert any(i.kind == "text" and "part 2" in (i.text or "").lower() for i in tl.items)
    music = {i.asset_id for i in tl.items if i.track == "A2"}
    assert music == {by_path["music/epic_build_128.wav"].id}
    assert tl.duration <= 30 * 1.15


@pytest.mark.parametrize("kind", ["travel_vlog", "aesthetic_cooking", "hype_reel", "talking_head", "gaming", "comedy_skit", "hindi_vlog"])
def test_auto_mode_every_genre(shoot_factory, kind):
    root = shoot_factory(kind)
    res = build(root, render=False)
    tl = res.timeline
    assert [i for i in tl.items if i.track == "V1"], "no picture"
    errors = [f for f in res.lint if f.severity == "error"]
    assert not errors, [f.msg for f in errors]
    tgt = res.direction.knobs.target_length or tl.duration
    assert tgt * 0.45 <= tl.duration <= tgt * 1.45, (tl.duration, tgt)
    # captions whenever there is kept speech (unless the playbook turns them off)
    speech = [i for i in tl.items if i.track == "A1" and i.role not in ("natural",)]
    if speech and res.direction.knobs.captions != "off":
        assert tl.captions
    # every applied effect has a reason
    assert all(s.reason for s in tl.suggestions)
    # nothing technically bad on screen
    pa = __import__("prepro.engine", fromlist=["analysis"]).analysis(root)
    for i in tl.items:
        if i.track in ("V1", "V2") and i.asset_id and pa.asset(i.asset_id).kind == AssetKind.BROLL:
            sh = next((s for s in pa.clips[i.asset_id].shots if s.t0 <= i.src_in < s.t1), None)
            assert not (sh and set(sh.flags) & {"dark", "blurry", "shaky", "pocket"}), (i.asset_id, sh.flags)


def test_directions_have_hooks_and_gaps(shoot_factory):
    from prepro.brain.basic import BasicBrain
    from prepro.engine import analysis, brief_for

    root = shoot_factory("travel_vlog")
    pa = analysis(root)
    ds = BasicBrain(pa, brief_for(root, pa)).directions()
    assert 2 <= len(ds.directions) <= 4
    d1 = ds.directions[0]
    assert d1.playbook == "story_vlog" and d1.hooks and "rupees" in d1.hooks[0].why.lower()
    assert d1.hooks[0].text_hook and "5000" in d1.hooks[0].text_hook
    assert any("CTA" in g or "call-to-action" in g for g in d1.coverage_gaps) is False  # the shoot has a CTA
    assert {d.playbook for d in ds.directions} >= {"story_vlog", "travel_film"}


@pytest.mark.slow
def test_preview_render_meets_delivery_specs(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    res = build(root, render=True)
    r = res.render
    assert r.video.exists()
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json",
                                      str(r.video)], capture_output=True, text=True).stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (540, 960)
    assert abs(float(info["format"]["duration"]) - res.timeline.duration) < 0.4
    assert r.lufs is not None and abs(r.lufs + 14) <= 1.0
    assert r.true_peak_db is not None and r.true_peak_db <= -0.7
    assert r.storyboard and r.storyboard.exists()
