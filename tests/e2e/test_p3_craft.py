"""Editor's Craft v2: split edits, open loops that pay off, re-hooks, jump-cut reframing, dead-zone fixes and the
cringe guard — each checked against what an editor would accept."""

from __future__ import annotations

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

from prepro import revise as R
from prepro.engine import analysis, build

pytestmark = [needs_tts, needs_ffmpeg]


def _v1(tl):
    return sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)


def _speech(tl):
    return sorted((i for i in tl.items if i.track == "A1" and i.role != "natural"), key=lambda i: i.rec_in)


@pytest.fixture(scope="module")
def travel(shoot_factory):
    root = shoot_factory("travel_vlog")
    for suffix in (".base.json", ".revision.json"):
        p = root / ".prepro" / "timelines" / f"d1-story_vlog{suffix}"
        if p.exists():
            p.unlink()
    return root, build(root, render=False)


def test_split_edits_move_the_picture_not_the_words(travel):
    root, res = travel
    tl = res.timeline
    splits = [s for s in tl.suggestions if s.type == "split"]
    assert splits, "a story vlog with talking ↔ B-roll changes should get J/L cuts"
    bounds = sorted({round(i.rec_in, 3) for i in _speech(tl)} | {round(i.rec_out, 3) for i in _speech(tl)})
    for s in splits:
        nx = next(i for i in _v1(tl) if i.id == s.item_ids[1])
        off = min(abs(nx.rec_in - b) for b in bounds)
        assert 0.2 <= off <= 0.85, (s.payload, off)                         # sound leads/trails by a real split
    assert not [f for f in res.lint if f.rule == "midword"]                  # and never clips a word
    # the creator can reject a split: the cut goes back to a straight cut there
    key = splits[0].payload["key"]
    tl2, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, key, "rejected"), pa=analysis(root))
    assert not [s for s in tl2.suggestions if s.payload.get("key") == key and s.status == "applied"]


def test_open_loop_is_paid_off_and_removable(travel):
    root, res = travel
    tl = res.timeline
    ff = [i for i in _v1(tl) if i.role == "flashforward"]
    assert len(ff) <= 1
    if not ff:
        pytest.skip("no action payoff late enough for a flash-forward in this cut")
    f = ff[0]
    assert f.rec_in < 6.0 and any(i.ref == f.ref and i.rec_in > f.rec_out for i in _v1(tl))   # early glimpse, real payoff later
    assert any(i.kind == "text" and i.text == "later…" for i in tl.items)
    assert not [x for x in res.lint if x.rule == "open_loop_unpaid"]
    tl2, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, f"open_loop:{f.ref}", "rejected"), pa=analysis(root))
    assert not [i for i in _v1(tl2) if i.role == "flashforward"]
    assert any(i.ref == f.ref for i in _v1(tl2))                             # rejecting the preview keeps the payoff


def test_long_talk_gets_readable_rehooks(shoot_factory):
    root = shoot_factory("podcast_long")
    res = build(root, render=False, direction="talking_head")
    texts = [i for i in res.timeline.items if i.kind == "text" and any(s.payload.get("key", "").endswith(f"|{i.text[:24]}")
                                                                       and "re-hook" in s.reason for s in res.timeline.suggestions)]
    if res.timeline.duration > 45:
        assert texts, "a long talk needs at least one re-hook"
    for t in texts:
        assert t.rec_in >= 25 and (t.duration or 0) >= 0.6 + len(t.text.split()) / 3.0      # never in the hook, always readable
    assert res.critic.scores["no_cringe"] >= 9.0


def test_talking_head_jump_cuts_alternate_framing(shoot_factory):
    root = shoot_factory("talking_head")
    res = build(root, render=False)
    v1 = [i for i in _v1(res.timeline) if i.kind == "video"]
    same = [(a, b) for a, b in zip(v1, v1[1:], strict=False) if a.asset_id == b.asset_id and b.src_in > a.src_out + 0.05
            and abs((a.transform.zoom if a.transform else 1) - (b.transform.zoom if b.transform else 1)) < 0.03
            and not any(o.track == "V2" and o.rec_in <= b.rec_in <= o.rec_out for o in res.timeline.items)]
    assert not same, [(a.ref, b.ref) for a, b in same]
    assert not [f for f in res.lint if f.rule == "overstim"]                 # reframes are framing, not effects


def test_cringe_guard_catches_empty_and_repeated_moments(travel):
    from prepro.lint.ghinn import checks, score

    root, res = travel
    tl = res.timeline.model_copy(deep=True)
    pa = analysis(root)
    ok = {c.id: c.ok for c in checks(tl, pa, res.direction)}
    assert ok["repeated_moment"] and ok["unmotivated_effects"]
    v = next(i for i in _v1(tl) if i.kind == "video" and i.role == "montage")
    dup = v.model_copy(update={"id": "vdup", "rec_in": tl.duration, "role": "montage"})
    tl.items.append(dup)                                                   # the same moment twice = stitched
    bad = {c.id: c for c in checks(tl, pa, res.direction)}
    assert not bad["repeated_moment"].ok and score(list(bad.values())) < 10


def test_comedy_keeps_the_beat_and_finds_the_real_punchlines(shoot_factory):
    root = shoot_factory("comedy_skit")
    pa = analysis(root)
    assert pa.genres[0].playbook == "comedy"                                # skit + memes + SFX kit → comedy path first
    res = build(root, render=False)
    roles = {it.ref: it.role for it in res.story.items}
    texts = {s.id: s.text for a in pa.assets if pa.clips[a.id].transcript for s in pa.clips[a.id].transcript.segments}
    punch = [texts[r] for r, role in roles.items() if role == "punchline"]
    assert any(t.endswith("!") for t in punch) and any(len(t.split()) <= 4 for t in punch)   # the claim and the button line
    assert not any("homework." in t and "first" in t for t in punch)       # a plain setup line is not a punchline
    beats = [s for s in res.timeline.suggestions if s.type == "timing"]
    assert beats
    for s in beats:                                                       # a real pause sits before the punchline's first word
        ref = s.payload["key"].split(":", 1)[1]
        a1 = next(i for i in res.timeline.items if i.track == "A1" and i.ref == ref)
        first = next(w for w in pa.words(a1.asset_id) if w.id in pa.segment(ref).word_ids and not w.filler)
        assert first.t0 - a1.src_in >= 0.2, (ref, first.t0 - a1.src_in)
    v1 = sorted((i for i in res.timeline.items if i.track == "V1" and i.kind == "video"), key=lambda i: i.rec_in)
    for a, b in zip(v1, v1[1:], strict=False):                            # the pause is never played twice
        if a.asset_id == b.asset_id:
            assert b.src_in >= a.src_out - 0.02
    assert res.critic.scores["no_cringe"] >= 9.5


def test_vertical_montage_loops_and_flows(shoot_factory):
    from prepro.brain.basic import BasicBrain

    root = shoot_factory("hype_reel")
    res = build(root, render=False)
    v1 = [i for i in _v1(res.timeline) if i.kind == "video"]
    assert res.direction.aspect == "9:16"
    assert v1[-1].role == "loop" and v1[-1].asset_id == v1[0].asset_id                 # ends on the opening image
    assert min(abs(v1[-1].src_in - v1[0].src_in), abs(v1[-1].src_out - v1[0].src_out)) > 0.2 or v1[-1].src_in >= v1[0].src_out
    bb = BasicBrain(analysis(root), None)
    mont = [it for it in res.story.items if it.role == "montage"]
    naive = sorted(mont, key=lambda it: (it.section, it.ref))
    assert bb.flow_score(mont) <= bb.flow_score(naive) + 1e-6                          # ordered for motion/colour flow


def test_path_previews_show_every_direction(shoot_factory):
    import json
    import subprocess

    from prepro.previews import make

    root = shoot_factory("travel_vlog")
    out = make(root, seconds=4)
    from prepro.project import Project
    from prepro.schema.plan import DirectionSet

    ds = Project(root).load_model("directions.json", DirectionSet)
    assert set(out) == {d.id for d in ds.directions}
    for did, rel in out.items():
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height:format=duration", "-of", "json",
                                          str(root / rel)], capture_output=True, text=True).stdout)
        d = next(x for x in ds.directions if x.id == did)
        w, h = info["streams"][0]["width"], info["streams"][0]["height"]
        assert (h > w) == (d.aspect == "9:16") and min(w, h) == 360 and abs(float(info["format"]["duration"]) - 4) < 0.25
