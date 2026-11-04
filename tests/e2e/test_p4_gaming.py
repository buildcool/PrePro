"""Gaming pack: impacts (explosions/shots) + the streamer's reactions become the highlights; the cut opens on the best
play, keeps a build-up into each play, replays the best in slow-mo and ends on the payoff — checked against the
planted ground truth of the gaming fixture."""

from __future__ import annotations

import numpy as np
import pytest
from tests.conftest import needs_ffmpeg, needs_tts, truth

from prepro.analyze.sound import impacts
from prepro.engine import build

pytestmark = [needs_tts, needs_ffmpeg]


def test_impact_detector_hears_booms_not_voices():
    from prepro.fixtures import audio as A

    sr = A.SR
    speech = np.zeros(sr * 6, dtype=np.float32)
    rng = np.random.default_rng(0)
    for t0 in (0.8, 2.6, 4.4):                                    # voice-like onsets: tonal, ~120 Hz + harmonics
        n = int(0.6 * sr)
        tt = np.arange(n) / sr
        tone = sum(np.sin(2 * np.pi * f * tt) / k for k, f in enumerate((120, 240, 360, 480), start=1)).astype(np.float32)
        speech[int(t0 * sr): int(t0 * sr) + n] += 0.3 * tone * np.minimum(1, tt / 0.03)
    speech += rng.normal(0, 1e-4, speech.size).astype(np.float32)
    assert impacts(speech, sr) == []                              # a voice starting is not an explosion
    boom = A.sfx("explosion")
    mix = speech.copy()
    at = int(3.5 * sr)
    mix[at: at + len(boom)] += boom[: len(mix) - at] * 0.5
    hits = impacts(mix, sr)
    assert len(hits) == 1 and abs(hits[0][0] - 3.5) < 0.1


@pytest.fixture(scope="module")
def game(shoot_factory):
    root = shoot_factory("gaming")
    return root, build(root, render=False)


def test_highlights_cover_the_planted_plays(game):
    root, res = game
    gt = truth(root)["expect"]["highlights"]                     # times of "DOUBLE KILL" and "VICTORY"
    tl = res.timeline
    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    covered = lambda t: any(i.src_in - 0.05 <= t <= i.src_out + 0.05 for i in v1 if i.role in ("highlight", "payoff"))  # noqa: E731
    assert all(covered(t) for t in gt), (gt, [(i.role, i.src_in, i.src_out) for i in v1])
    plays = gt + truth(root)["expect"].get("fails", [])          # a death is a play too (it gets a meme, see below)
    for i in v1:                                                 # each play keeps its build-up (≥ 2 s before the impact)
        if i.role == "highlight":
            assert any(i.src_in <= t - 2.0 for t in plays if i.src_in <= t <= i.src_out) or i.src_in <= 1.0


def test_cold_open_replay_and_payoff(game):
    root, res = game
    tl = res.timeline
    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    hook, last = v1[0], v1[-1]
    assert hook.role == "hook" and abs(hook.speed - 1) < 1e-6
    assert any(i.track == "A1" and i.rec_in < 0.1 for i in tl.items)          # the cold open has its sound
    replay = [i for i in v1 if i.role == "replay"]
    assert len(replay) == 1 and abs(replay[0].speed - 0.5) < 1e-6
    assert last.role == "payoff"
    assert any(i.kind == "text" and i.text == "REPLAY" for i in tl.items)
    assert any(i.kind == "text" and i.style == "callout" for i in tl.items)   # the play called out in the streamer's words
    assert tl.captions                                                        # reactions are captioned
    assert res.direction.hooks[0].kind == "peak_moment" and "best play" in res.direction.hooks[0].why
    assert res.critic.scores["no_cringe"] >= 9.5 and not [f for f in res.lint if f.severity == "error"]


def test_finds_the_webcam_in_the_stream(game):
    from prepro.engine import analysis

    root, _ = game
    pa = analysis(root)
    fc = pa.clips[next(a.id for a in pa.assets if a.path.startswith("gameplay/"))].facecam
    want = truth(root)["expect"]["facecam"]
    assert fc and max(abs(a - b) for a, b in zip(fc, want, strict=True)) < 0.02, (fc, want)


def test_vertical_short_stacks_webcam_over_the_game(game):
    from prepro import revise as R
    from prepro.engine import analysis

    root, _ = game
    res = build(root, render=False, direction="d2")                 # the Short offered next to the YouTube cut
    tl = res.timeline
    assert res.direction.aspect == "9:16" and tl.meta.get("layout_top")
    game_v1 = [i for i in tl.items if i.track == "V1" and i.kind == "video" and i.role != "meme"]
    cams = [i for i in tl.items if i.track == "V2" and i.role == "facecam"]
    assert game_v1 and all(i.place and i.place[1] > 0.2 for i in game_v1)            # the game below…
    assert len(cams) == len(game_v1) and all(c.place[1] == 0.0 for c in cams)        # …the webcam above, always
    big = [i for i in tl.items if i.role == "facecam_big"]
    assert len(big) == 1 and big[0].place[3] > tl.meta["layout_top"]                  # once, on the biggest win
    assert any(s.type == "facecam" and "DOUBLE KILL" in s.reason for s in tl.suggestions)
    # the death gets a meme right after it, and never opens the cut
    fail_t = truth(root)["expect"]["fails"][0]
    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    memes = [k for k, i in enumerate(v1) if i.role == "meme"]
    assert memes and v1[memes[0] - 1].src_in <= fail_t <= v1[memes[0] - 1].src_out
    assert not (v1[0].src_in <= fail_t <= v1[0].src_out)
    # rejecting the layout gives one plain 9:16 crop of the stream
    key = next(s.payload["key"] for s in tl.suggestions if s.type == "layout")
    tl2, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, key, "rejected"), pa=analysis(root))
    assert not [i for i in tl2.items if i.track == "V1" and i.place] and not [i for i in tl2.items if i.role == "facecam"]
    assert all(i.place[1] == 0.0 for i in tl2.items if i.role == "facecam_big")   # the big reaction: a top panel
