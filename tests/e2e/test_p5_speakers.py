"""Two people on one camera (a podcast two-shot): PrePro finds who says each line, cuts the conversation in the order it
was said, frames whoever is talking in a 9:16 crop (never the gap between them), cuts at the ends of lines, holds
through a quick "yeah", shows a short exclamation as a reaction shot, and keeps captions in one place."""

from __future__ import annotations

import pytest
from tests.conftest import needs_ffmpeg, needs_tts, truth

from prepro import revise as R
from prepro.engine import analysis, build

pytestmark = [needs_tts, needs_ffmpeg]


@pytest.fixture(scope="module")
def duo(shoot_factory):
    root = shoot_factory("podcast_duo")
    for p in (root / ".prepro" / "timelines").glob("*.json"):
        if p.name.endswith((".base.json", ".revision.json")):
            p.unlink()                                                   # a fresh build, no revisions from earlier runs
    return root, analysis(root)


def _talker(gt, t0, t1):
    mid = (t0 + t1) / 2
    return next((g["seat"] for g in gt if g["t0"] - 0.3 <= mid <= g["t1"] + 0.3), None)


def test_finds_both_people_and_who_says_each_line(duo):
    root, pa = duo
    gt = truth(root)["expect"]
    ca = pa.clips[pa.assets[0].id]
    sh = ca.shots[0]
    assert [round(s.x, 1) for s in sh.seats] == [0.3, 0.7]            # both seats — incl. the darker-skinned guest
    right = total = 0.0
    for seg in ca.transcript.segments:
        want = _talker(gt["speakers"], seg.t0, seg.t1)
        total += seg.t1 - seg.t0
        right += (seg.t1 - seg.t0) * (seg.speaker == want)
        assert seg.speaker in (want, None), (seg.text, seg.speaker, want)  # unsure is allowed, wrong is not
    assert right / total >= 0.9


def test_reply_that_echoes_the_other_person_is_not_a_retake(duo):
    _, pa = duo
    segs = {s.text: s for s in pa.clips[pa.assets[0].id].transcript.segments}
    setup = next(s for t, s in segs.items() if "almost did not upload." in t)
    reply = next(s for t, s in segs.items() if t.startswith("Wait"))
    assert setup.retake_rank == 0 and reply.retake_rank == 0 and setup.retake_group is None


def test_vertical_cut_frames_whoever_is_talking(duo):
    root, pa = duo
    gt = truth(root)["expect"]["speakers"]
    res = build(root, render=False, direction="podcast_clip")
    tl = res.timeline
    assert res.direction.aspect == "9:16"
    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    seats = [s.x for s in pa.clips[pa.assets[0].id].shots[0].seats]
    for i in v1:
        cx = i.transform.cx if i.transform else 0.5
        on = min(range(len(seats)), key=lambda k: abs(seats[k] - cx))
        assert abs(seats[on] - cx) < 0.06, ("frame sits between the people", i.rec_in, cx)
        talker = _talker(gt, i.src_in, i.src_out)
        seg = pa.segment(i.ref)
        quick = len(seg.text.split()) <= 2 and not seg.text.endswith("!")
        assert on == talker or quick, (i.rec_in, seg.text, on, talker)    # only a quick "yeah" may hold the other person
    # the conversation stays in the order it was said, and every reply keeps the line it answers
    srcs = [i.src_in for i in v1]
    assert srcs == sorted(srcs)
    texts = [pa.segment(i.ref).text for i in v1]
    if any(t.startswith("Wait") for t in texts):
        assert any("almost did not upload." in t for t in texts)
    reactions = [s for s in tl.suggestions if s.type == "framing" and "Reaction shot" in s.reason]
    assert reactions and all(s.reason for s in tl.suggestions if s.type == "framing")
    assert len({c.pos for c in tl.captions}) == 1                         # captions stay in one place
    assert res.critic.scores["no_cringe"] >= 9.5


def test_rejecting_a_cut_keeps_the_current_speaker(duo):
    root, pa = duo
    res = build(root, render=False, direction="podcast_clip")
    tl = res.timeline
    cut = next(s for s in tl.suggestions if s.type == "framing" and "lands at the end of the line" in s.reason)
    tl2, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, cut.payload["key"], "rejected"), pa=pa)
    ref = cut.payload["key"].split(":", 1)[1]
    before = next(i for i in sorted((i for i in tl2.items if i.track == "V1"), key=lambda i: i.rec_in) if i.ref == ref)
    prev = max((i for i in tl2.items if i.track == "V1" and i.rec_in < before.rec_in), key=lambda i: i.rec_in)
    assert abs(before.transform.cx - prev.transform.cx) < 0.01            # no cut there: the frame stays on who was on


def test_single_presenter_has_no_seats(shoot_factory):
    root = shoot_factory("talking_head")
    pa = analysis(root)
    assert not any(s.seats for a in pa.assets for s in pa.clips[a.id].shots)
