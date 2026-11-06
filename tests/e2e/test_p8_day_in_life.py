"""Day in my life — one Saturday off a phone, cut in the order it happened: found from the clips' own capture times,
every moment a few beats of a warm song (the hype track avoided), the first and the last moment held longer, the
morning and the night of the same room both kept (not "duplicates"), the retake, the shaky clip and the evening before
left out with their reasons, small time stamps where the day starts, moves on and ends, the sounds of the day kept
under the song; in the review, stamps go with one click and a moment brought back lands where it happened, on the
beat; and an AI editor can't reorder a beat-cut format off its grid — checked against the fixture's ground truth."""

from __future__ import annotations

import pytest
from tests.conftest import needs_ffmpeg, truth

from prepro import revise as R
from prepro.engine import analysis, brief_for, build

pytestmark = [needs_ffmpeg]


@pytest.fixture(scope="module")
def day(shoot_factory):
    root = shoot_factory("day_in_life")
    return root, build(root, render=True)


def _v1(tl):
    return sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)


def test_found_from_the_capture_times(day):
    root, res = day
    pa = analysis(root)
    assert pa.genres[0].playbook == "day_in_life" and "6:42 am to 11:05 pm" in pa.genres[0].why
    assert pa.stats["utc_offset_min"] == 330                                  # the phone's own +05:30
    assert res.direction.playbook == "day_in_life" and res.direction.aspect == "9:16"
    assert res.direction.hooks[0].kind == "first_moment"


def test_the_day_in_the_order_it_happened(day):
    root, res = day
    gt = truth(root)["expect"]
    pa = analysis(root)
    v1 = _v1(res.timeline)
    order = [pa.asset(i.asset_id).path for i in v1]
    assert order == gt["order"]                       # by the clock, not by file name (the lunch clip is VID_0099)
    assert v1[0].role == "hook" and order[-1] == gt["last_moment"]   # the room at 6:42 am and again at 11:05 pm
    left = {pa.asset(s.payload["asset"]).path: s.reason for s in res.timeline.suggestions if s.type == "cut" and s.payload.get("asset")}
    for rel in gt["left_out"]:
        assert rel in left and rel not in order, rel
    assert "duplicate" in left["footage/VID_0012.mp4"]
    assert "shaky" in left["footage/VID_0013.mp4"]
    assert "another day" in left["footage/VID_0000.mp4"]


def test_cut_on_the_beat_of_the_warm_song(day):
    root, res = day
    gt = truth(root)["expect"]
    pa = analysis(root)
    tl = res.timeline
    a2 = [i for i in tl.items if i.track == "A2"]
    assert len(a2) == 1 and pa.asset(a2[0].asset_id).path == gt["song"]       # one piece of the song: no loop seam
    assert a2[0].rec_out >= tl.duration - 0.05
    beats = [b - a2[0].src_in + a2[0].rec_in for b in pa.clips[a2[0].asset_id].music.beats]
    v1 = _v1(tl)
    for it in v1[1:]:
        assert min(abs(it.rec_in - b) for b in beats) <= 0.07, it.rec_in
    lens = [i.rec_dur for i in v1[1:-1]]
    assert max(lens) - min(lens) <= 0.15 and 1.0 <= min(lens) <= 2.2         # an even groove, about 1.5 s a moment
    assert v1[0].rec_dur > 1.8 * min(lens) and v1[-1].rec_dur > 1.8 * min(lens)   # the day's first and last moment linger
    assert res.critic.scores["genre_fit"] >= 9.5 and res.critic.scores["pacing"] >= 9.0


def test_time_stamps_where_the_day_starts_moves_on_and_ends(day):
    root, res = day
    tl = res.timeline
    v1 = _v1(tl)
    stamps = sorted((i for i in tl.items if i.kind == "text" and i.style == "stamp"), key=lambda i: i.rec_in)
    assert stamps[0].text == "6:42 am" and stamps[0].rec_in < 0.05
    assert stamps[-1].text == "11:05 pm" and abs(stamps[-1].rec_in - v1[-1].rec_in) < 0.05
    assert 3 <= len(stamps) < len(v1)                                          # not a ticking clock on every clip
    for a, b in zip(stamps, stamps[1:], strict=False):
        assert b.rec_in - a.rec_in >= 2.8                                      # never one right after another
    for s in stamps:
        assert s.duration >= 1.27                                              # long enough to read
        assert any(abs(s.rec_in - v.rec_in) < 0.05 and abs(s.rec_out - v.rec_out) < 0.1 for v in v1)   # up with its moment
    title = next(i for i in tl.items if i.kind == "text" and i.style == "photo")
    assert title.text == "a day in my life" and title.rec_in < 0.1
    one = [s for s in tl.suggestions if s.payload.get("key") == "stamps"]
    assert len(one) == 1 and set(one[0].item_ids) == {s.id for s in stamps}  # one decision covers them all
    ass = (res.render.video.with_suffix(".ass")).read_text(encoding="utf-8")
    assert "Style: stamp,Montserrat" in ass and "\\an8" in ass and "6:42 am" in ass


def test_the_sounds_of_the_day_stay_under_the_song(day):
    _root, res = day
    tl = res.timeline
    natural = [i for i in tl.items if i.track == "A1" and i.role == "natural"]
    assert natural and all(i.gain_db == -5.0 for i in natural)
    r = res.render
    assert abs(r.lufs + 14) <= 1.0 and r.true_peak_db <= -0.8
    assert r.speech_to_music_db is None                                        # nobody talks: no voice-over-music target
    assert not [f for f in res.lint if f.rule in ("ducking", "loudness", "overstim", "microshot", "quality")]


@pytest.fixture()
def fresh(day):
    root, res = day
    tid = res.timeline.id
    for suffix in (".base.json", ".revision.json"):
        p = root / ".prepro" / "timelines" / f"{tid}{suffix}"
        if p.exists():
            p.unlink()
    build(root, render=False)
    return root, tid, analysis(root)


def test_review_turns_stamps_off_and_brings_a_moment_back_where_it_happened(fresh):
    root, tid, pa = fresh
    rev = R.toggle(root, tid, "stamps", "rejected")
    tl, _, _ = R.recompile(root, tid, rev, pa=pa)
    assert not [i for i in tl.items if i.kind == "text" and i.style == "stamp"]
    assert any(i.kind == "text" and i.text == "a day in my life" for i in tl.items)       # the title stays
    ids = {a.path: a.id for a in pa.assets}
    shaky = next(s for s in tl.suggestions if s.type == "cut" and s.payload.get("asset") == ids["footage/VID_0013.mp4"])
    rev = R.toggle(root, tid, shaky.payload["key"], "rejected")                  # "keep it after all"
    tl, _, _ = R.recompile(root, tid, rev, pa=pa)
    order = [pa.asset(i.asset_id).path for i in _v1(tl)]
    k = order.index("footage/VID_0013.mp4")                                     # 7:30 pm: after the sunset, before 9:40 pm
    assert order[k - 1] == "footage/VID_0011.mp4" and order[k + 1] == "footage/VID_0014.mp4"
    a2 = next(i for i in tl.items if i.track == "A2")
    beats = [b - a2.src_in + a2.rec_in for b in pa.clips[a2.asset_id].music.beats]
    for it in _v1(tl)[1:]:
        assert min(abs(it.rec_in - b) for b in beats) <= 0.07, it.rec_in     # every cut still on the beat


def test_an_ai_editor_keeps_beat_cut_formats_on_their_grid(day, shoot_factory):
    from pathlib import Path

    from prepro.brain.ai import AIBrain
    from prepro.brain.basic import BasicBrain
    from prepro.brain.providers import StubProvider
    from prepro.config import ConnectorConfig

    for root in (day[0], shoot_factory("photo_dump")):
        pa = analysis(root)
        brief = brief_for(root, pa)
        rules = BasicBrain(pa, brief)
        d = rules.directions().directions[0]
        assert d.playbook in ("day_in_life", "photo_reel")
        base_story = rules.story(d)
        base_polish = rules.polish(d, base_story)
        shots = [it.ref for it in base_story.items]
        reorder = {"TASK: build the story": {"items": [{"ref": r, "role": "montage", "section": "m", "t0": None, "t1": None, "note": ""}
                                                        for r in reversed(shots)],
                                              "sections": [{"name": "m", "music_mode": "front", "card": None}], "why": "causality"},
                   "TASK: polish": {"music": [{"section": "m", "mode": "bed", "track_id": None, "mood": "epic", "search_terms": [], "why": ""}],
                                    "effects": [], "broll_gaps": [], "vo_script": [], "look": "warm"}}
        stub = StubProvider(name="stub", cfg=ConnectorConfig(kind="stub"), sent_dir=Path(root) / ".prepro" / "sent", privacy="text",
                            responses=reorder)
        ai = AIBrain(pa, brief, {"story": stub, "polish": stub})
        story = ai.story(d)
        assert [(it.ref, it.beats) for it in story.items] == [(it.ref, it.beats) for it in base_story.items]
        polish = ai.polish(d, story)
        assert [(m.track_id, m.offset) for m in polish.music] == [(m.track_id, m.offset) for m in base_polish.music]
