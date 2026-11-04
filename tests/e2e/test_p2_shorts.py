"""Phase 2 · long → Shorts: the finder must pick the planted self-contained moments, never the rambling, and each
pick must become a reviewable, revisable, exportable vertical cut."""

from __future__ import annotations

import pytest
from tests.conftest import needs_ffmpeg, needs_tts, truth

from prepro import revise as R
from prepro.engine import analysis
from prepro.repurpose import build_shorts, find_direction, find_shorts

pytestmark = [needs_tts, needs_ffmpeg]


@pytest.fixture(scope="module")
def podcast(shoot_factory):
    root = shoot_factory("podcast_long")
    return root, analysis(root)


def _iou(a0, a1, b0, b1):
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    return inter / (max(a1, b1) - min(a0, b0))


def test_finder_picks_the_planted_moments(podcast):
    root, pa = podcast
    gold = truth(root)["expect"]["shorts"]
    picks = find_shorts(pa, count=3)
    assert len(picks) == 3
    for g in gold:
        best = max(_iou(c.t0, c.t1, g["t0"], g["t1"]) for c in picks)
        assert best >= 0.85, (g, [(c.t0, c.t1) for c in picks])
    for c in picks:
        assert not c.hook.lower().startswith(("and", "so", "like i said", "anyway", "hey")), c.hook
        assert 15 <= c.dur <= 60 and c.why


def test_shorts_become_reviewable_vertical_cuts(podcast):
    root, pa = podcast
    res = build_shorts(root, count=2)
    assert len(res) == 2
    from prepro.project import Project
    from prepro.schema.timeline import Timeline

    for c, tid in res:
        tl = Project(root).load_model(f"timelines/{tid}.json", Timeline)
        assert (tl.width, tl.height) == (1080, 1920)
        assert tl.captions and abs(tl.duration - c.dur) < c.dur * 0.35          # fillers/pauses tightened, nothing added
        first = min((i for i in tl.items if i.track == "A1"), key=lambda i: i.rec_in)
        assert first.ref == c.segments[0]                                      # opens on its own first line
        assert find_direction(root, c.id) is not None
        # the revise layer works on Shorts too
        rev, cm = R.add_comment(root, tid, 1.0, "big text: watch this")
        tl2, findings, critic = R.recompile(root, tid, rev, pa=pa)
        assert cm.status == "applied" and any(i.kind == "text" and i.text == "watch this" for i in tl2.items)
        assert critic is not None and not [f for f in findings if f.severity == "error"]
