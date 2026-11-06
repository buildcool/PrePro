"""Your words on video (POV / text on video): a brief with your own lines and a handful of clips becomes a Reel where
your first line opens on the most striking clip, every line lands on the song's beat word for word, stays up long
enough to read (a long one runs over two clips), the last one holds, and an AI editor can't take it off the beat."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import needs_ffmpeg

from prepro.engine import analysis, brief_for, build

pytestmark = [needs_ffmpeg]

LINES = ["pov: you finally learned to cook", "and it's actually good", "sunday mornings hit different now",
         "save this for your next slow weekend"]
BRIEF = "Text:\n" + "\n".join(LINES) + "\n"


@pytest.fixture(scope="module")
def reel(shoot_factory):
    root = shoot_factory("aesthetic_cooking")
    return root, build(root, brief_text=BRIEF, render=False)


def _v1(tl):
    return sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)


def test_your_lines_choose_the_format(reel):
    _root, res = reel
    assert res.direction.playbook == "text_reel" and res.direction.aspect == "9:16"
    assert res.directions.directions[1].playbook != "text_reel"          # the footage's own genres follow
    hook = res.direction.hooks[0]
    assert hook.text_hook == LINES[0] and _v1(res.timeline)[0].ref == hook.refs[0]   # line 1 on the most striking clip


def test_every_line_word_for_word_on_the_beat_and_readable(reel):
    _root, res = reel
    tl = res.timeline
    words = sorted((i for i in tl.items if i.kind == "text"), key=lambda i: i.rec_in)
    assert [w.text for w in words] == LINES                               # your words, in your order, nothing else
    assert words[0].rec_in < 0.1                                          # the hook from the first frame
    for w in words:
        assert w.duration >= 0.6 + len(w.text.split()) / 3.0              # long enough to read
    for a, b in zip(words, words[1:], strict=False):
        assert a.rec_out <= b.rec_in + 0.02                               # one line at a time
    v1 = _v1(tl)
    starts = {round(v.rec_in, 2) for v in v1}
    assert all(round(w.rec_in, 2) in starts for w in words)               # each line arrives with a cut
    assert words[-1].duration > max(w.duration for w in words[:-1]) - 0.8  # the last one holds
    a2 = [i for i in tl.items if i.track == "A2"]
    assert len(a2) == 1 and a2[0].rec_out >= tl.duration - 0.05           # the song through to the end
    assert res.critic.scores["genre_fit"] >= 9.5                          # cut on the beat, readable, hook line first
    assert not [f for f in res.lint if f.rule in ("overstim", "microshot", "brief")]


def test_an_ai_editor_keeps_your_words_on_the_beat(reel):
    from prepro.brain.ai import AIBrain
    from prepro.brain.basic import BasicBrain
    from prepro.brain.providers import StubProvider
    from prepro.config import ConnectorConfig

    root, _ = reel
    pa = analysis(root)
    brief = brief_for(root, pa, extra_text=BRIEF)
    rules = BasicBrain(pa, brief)
    d = rules.directions().directions[0]
    base = rules.story(d)
    stub = StubProvider(name="stub", cfg=ConnectorConfig(kind="stub"), sent_dir=Path(root) / ".prepro" / "sent", privacy="text",
                        responses={"TASK: build the story": {"items": [{"ref": it.ref, "role": "montage", "section": "m", "t0": None,
                                                                         "t1": None, "note": ""} for it in reversed(base.items)],
                                                              "sections": [{"name": "m", "music_mode": "front", "card": None}], "why": "x"}})
    story = AIBrain(pa, brief, {"story": stub}).story(d)
    assert [(it.ref, it.beats) for it in story.items] == [(it.ref, it.beats) for it in base.items]
