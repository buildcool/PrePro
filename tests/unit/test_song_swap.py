"""Another song for a cut on the beat (a photo reel, a day in my life, your words on video): "change the song" in the
review rebuilds the cut on the new song as if your brief had named it — its own strongest start, every picture on its
beats, re-planned for its tempo — and the cut never outlasts its song: a short song shortens the cut instead of running
out and restarting from its top halfway through. Your other review choices stay; the old song is the way back.

Runs on the iPhone goldens (real analyses of the fixture shoots), so no media is needed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prepro import revise as R
from prepro.brain.basic import BasicBrain
from prepro.schema.analysis import ProjectAnalysis
from prepro.schema.brief import CreatorBrief, HardRule
from prepro.schema.plan import Direction, MusicCue, PolishPlan, StoryItem, StoryPlan
from prepro.timeline.compiler import compile_timeline

GOLDEN = Path(__file__).resolve().parents[2] / "ios" / "PreProCore" / "Tests" / "PreProCoreTests" / "Golden"


def _load(name: str):
    g = GOLDEN / name
    pa = ProjectAnalysis.model_validate_json((g / "analysis.json").read_text(encoding="utf-8"))
    pa.root = ""                                              # nothing is read from disk
    return (pa, CreatorBrief.model_validate_json((g / "brief.json").read_text(encoding="utf-8")),
            Direction.model_validate_json((g / "direction.json").read_text(encoding="utf-8")),
            StoryPlan.model_validate_json((g / "story.json").read_text(encoding="utf-8")),
            PolishPlan.model_validate_json((g / "polish.json").read_text(encoding="utf-8")))


def _photo_reel_with_two_songs():
    """The photo dump with a second song: the words reel's 144 BPM trap track (22 s) as A02."""
    pa, brief, d, s, p = _load("photo_reel")
    other = json.loads((GOLDEN / "text_reel" / "analysis.json").read_text(encoding="utf-8"))
    raw = json.loads(pa.model_dump_json())
    song = next(a for a in other["assets"] if a["id"] == "A01")
    raw["assets"].append({**song, "id": "A02"})
    raw["clips"]["A02"] = {**other["clips"]["A01"], "asset_id": "A02"}
    return ProjectAnalysis.model_validate(raw), brief, d, s, p


def _grid(pa, brief, d, track):
    b = brief.model_copy(deep=True)
    b.rules = [r for r in b.rules if r.kind != "use_music"] + [HardRule(kind="use_music", target=track, anchor="all", arg={"asset": track})]
    return BasicBrain(pa, b)._reel_grid(float(d.knobs.target_length or 30.0), d.playbook)


def _swap(track: str, sections: str) -> R.Op:
    return R.Op(op="swap_track", ref=sections, value=track)


def _on_its_beats(tl, pa) -> list[float]:
    """Cuts that miss the beat of the song under them (empty: every cut is on the beat)."""
    music = [i for i in tl.items if i.track == "A2"]
    beats = pa.clips[music[0].asset_id].music.beats
    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    return [i.rec_in for i in v1[1:] if music[0].src_in + i.rec_in < beats[-1] and min(abs(music[0].src_in + i.rec_in - b) for b in beats) > 0.03]


@pytest.mark.parametrize("name", ["day_in_life", "text_reel"])
def test_another_song_rebuilds_the_cut_on_its_own_beat(name):
    pa, brief, d, s, p = _load(name)
    old = p.music[0].track_id
    new = next(a.id for a in pa.assets if a.kind == "music" and a.id != old)
    s2, p2, d2 = R.apply_ops([_swap(new, ",".join(c.section for c in p.music))], s, p, d, pa, brief)
    grid = _grid(pa, brief, d, new)
    assert {c.track_id for c in p2.music} == {new} and {c.offset for c in p2.music} == {grid["offset"]}   # its own start
    assert all(c.why.startswith("your pick") and old in c.alternatives for c in p2.music)                 # the way back
    tl = compile_timeline(pa, d2, s2, p2, brief)
    music = [i for i in tl.items if i.track == "A2"]
    assert len(music) == 1, "the song never runs out and restarts from its top mid-cut"
    assert tl.duration <= grid["room"] + 0.05 and not _on_its_beats(tl, pa)
    if name == "text_reel":                                   # your lines, word for word, each up long enough to read
        texts = sorted((i for i in tl.items if i.kind == "text"), key=lambda i: i.rec_in)
        assert [t.text for t in texts] == [r.target for r in brief.rules if r.kind == "text_line"]
        assert all(t.duration >= 0.6 + len(t.text.split()) / 3.0 for t in texts)
    # and back again: the cut the build made, on its own song
    s3, p3, _ = R.apply_ops([_swap(new, p.music[0].section), _swap(old, p.music[0].section)], s, p, d, pa, brief)
    assert s3.items == s.items and [c.offset for c in p3.music] == [c.offset for c in p.music]


def test_a_short_song_shortens_the_day_instead_of_restarting():
    pa, brief, d, s, p = _load("day_in_life")
    short = next(a.id for a in pa.assets if a.kind == "music" and a.info.duration < 25)      # the 22 s trap track
    s2, p2, d2 = R.apply_ops([_swap(short, ",".join(c.section for c in p.music))], s, p, d, pa, brief)
    tl = compile_timeline(pa, d2, s2, p2, brief)
    assert len([i for i in tl.items if i.track == "A2"]) == 1 and tl.duration < 22.0
    stamps = [i.text for i in sorted(tl.items, key=lambda i: i.rec_in) if i.kind == "text" and i.style == "stamp"]
    assert stamps[0] == "6:42 am" and stamps[-1].endswith("pm")                                    # still the whole day
    assert "more moment" in s2.why                                                                 # the rest wait in the review


def test_photo_reel_keeps_your_choices_on_the_new_song():
    pa, brief, d, s, p = _photo_reel_with_two_songs()
    s2, p2, d2 = R.apply_ops([R.Op(op="reject", key="item:I05.k0"), _swap("A02", "reel")], s, p, d, pa, brief)
    assert p2.music[0].track_id == "A02" and p2.music[0].offset == _grid(pa, brief, d, "A02")["offset"]
    tl = compile_timeline(pa, d2, s2, p2, brief)
    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    assert "I05.k0" not in {i.ref for i in v1}, "the photo you dropped stays out"
    assert v1[-1].role == "loop" and v1[-1].ref == v1[0].ref and not _on_its_beats(tl, pa)
    title = next(i for i in tl.items if i.kind == "text")
    assert title.duration >= 0.6 + len(title.text.split()) / 3.0, "the cover's where-and-when can be read on a fast song"
    assert len([i for i in tl.items if i.track == "A2"]) == 1


def test_turning_the_music_off_and_a_new_song_in_that_order():
    pa, brief, d, s, p = _photo_reel_with_two_songs()
    off = R.Op(op="reject", key="music:reel")
    _, p_on, _ = R.apply_ops([off, _swap("A02", "reel")], s, p, d, pa, brief)
    assert [(c.track_id, c.mode) for c in p_on.music] == [("A02", "front")], "a new song after 'no music' brings music back"
    _, p_off, _ = R.apply_ops([_swap("A02", "reel"), off], s, p, d, pa, brief)
    assert all(c.track_id is None and c.mode == "none" for c in p_off.music), "'no music' after a swap still wins"


def test_a_short_song_shortens_a_photo_reel_built_on_it():
    pa, brief, d, s, p = _photo_reel_with_two_songs()
    b = brief.model_copy(deep=True)
    b.rules.append(HardRule(kind="use_music", target="trap", anchor="all", arg={"asset": "A02"}))
    d2 = d.model_copy(deep=True)
    d2.knobs.target_length, d2.target_max = 30.0, 34.5        # a long reel asked for, on a 22 s song
    brain = BasicBrain(pa, b)
    story = brain.story(d2)
    tl = compile_timeline(pa, d2, story, brain.polish(d2, story), b)
    room = brain._reel_grid(30.0)["room"]
    assert tl.duration <= room + 0.05 and len([i for i in tl.items if i.track == "A2"]) == 1


def test_another_song_walks_through_the_ones_you_have_not_heard():
    pa, brief, _, _, _ = _load("day_in_life")
    d = Direction(id="v", playbook="story_vlog", name="vlog")
    story = StoryPlan(direction_id="v", items=[StoryItem(ref="C02.k0", section="main")])
    polish = PolishPlan(direction_id="v", music=[MusicCue(section="main", mode="bed", track_id="A01", alternatives=["A02", "A03"])])
    _, p2, _ = R.apply_ops([_swap("A02", "main")], story, polish, d, pa, brief)
    assert p2.music[0].track_id == "A02" and p2.music[0].alternatives == ["A03", "A01"]   # the next unheard first, then back
