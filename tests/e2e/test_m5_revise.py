"""M5 revise layer: accept/reject any suggestion, timeline comments → edits, undo — all without re-running a brain."""

from __future__ import annotations

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

from prepro import revise as R
from prepro.engine import analysis, build

pytestmark = [needs_tts, needs_ffmpeg]


@pytest.fixture(scope="module")
def shoot(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    res = build(root, render=False)
    return root, res.timeline.id, analysis(root)


@pytest.fixture()
def fresh(shoot):
    root, tid, pa = shoot
    for suffix in (".base.json", ".revision.json"):
        p = root / ".prepro" / "timelines" / f"{tid}{suffix}"
        if p.exists():
            p.unlink()
    build(root, render=False)
    return root, tid, pa


def _v1(tl):
    return [i for i in sorted(tl.items, key=lambda i: i.rec_in) if i.track == "V1"]


def test_every_decision_has_a_key(fresh):
    root, tid, _ = fresh
    tl = R.base_timeline(root, tid)
    for s in tl.suggestions:
        assert s.payload.get("key"), (s.type, s.reason)


def test_reject_then_undo_a_meme(fresh):
    root, tid, pa = fresh
    rev = R.toggle(root, tid, "fx:meme:C08.s1", "rejected")
    tl, _, _ = R.recompile(root, tid, rev, pa=pa)
    assert not any(i.role == "meme" for i in tl.items)
    gone = [s for s in tl.suggestions if s.payload.get("key") == "fx:meme:C08.s1"]
    assert gone and gone[0].status == "rejected"            # still listed, so it can be turned back on
    rev = R.toggle(root, tid, "fx:meme:C08.s1", "applied")
    tl, _, _ = R.recompile(root, tid, rev, pa=pa)
    assert any(i.role == "meme" for i in tl.items) and not rev.ops


def test_keep_a_line_the_engine_cut(fresh):
    root, tid, pa = fresh
    base = R.base_timeline(root, tid)
    cut = next(s for s in base.suggestions if s.payload.get("key", "").startswith("seg:"))
    rev = R.toggle(root, tid, cut.payload["key"], "rejected")
    tl, _, _ = R.recompile(root, tid, rev, pa=pa)
    ref = cut.payload["key"][4:]
    assert any(i.track == "A1" and i.ref == ref for i in tl.items)
    # it comes back next to its neighbours from the same clip (in spoken order), never before the hook
    refs = [i.ref for i in sorted(tl.items, key=lambda i: i.rec_in) if i.track == "A1" and i.role != "natural"]
    assert refs[0] != ref
    same = [r for r in refs[1:] if r.split(".")[0] == ref.split(".")[0]]
    assert same == sorted(same, key=lambda r: int(r.split(".s")[1]))


@pytest.mark.parametrize("t,text,check", [
    (8.0, "big text: ₹5000 only", lambda tl, pa: any(i.kind == "text" and i.style == "big" and "5000" in i.text for i in tl.items)),
    # the creator's own whoosh from sfx/ wins over the built-in one
    (20.0, "whoosh here", lambda tl, pa: any(i.track == "A3" and ("whoosh" in (i.note or "") or (i.asset_id and "whoosh" in pa.asset(i.asset_id).name))
                                              and abs(i.rec_in - 20.0) < 1.5 for i in tl.items)),
    (12.0, "music quieter", lambda tl, pa: True),
    (21.0, "no meme", lambda tl, pa: not any(i.role == "meme" for i in tl.items)),
    (4.5, "remove this shot", lambda tl, pa: "C07.k0" not in {i.ref for i in tl.items}),
])
def test_comments_become_edits(fresh, t, text, check):
    root, tid, pa = fresh
    rev, c = R.add_comment(root, tid, t, text)
    assert c.status == "applied", c.reply
    tl, _, _ = R.recompile(root, tid, rev, pa=pa)
    assert check(tl, pa), (text, c.reply)
    # deleting the comment undoes it
    rev = R.remove_comment(root, tid, c.id)
    tl2, _, _ = R.recompile(root, tid, rev, pa=pa)
    assert abs(tl2.duration - R.base_timeline(root, tid).duration) < 0.05


def test_faster_shortens_broll_but_never_speech(fresh):
    root, tid, pa = fresh
    tl0 = R.base_timeline(root, tid)
    shot = next(i for i in _v1(tl0) if i.ref and ".k" in i.ref and i.role == "montage")
    rev, c = R.add_comment(root, tid, shot.rec_in + 0.3, "faster here")
    assert c.status == "applied"
    tl, _, _ = R.recompile(root, tid, rev, pa=pa)
    new = next(i for i in _v1(tl) if i.ref == shot.ref)
    assert new.rec_dur < shot.rec_dur * 0.75
    talk = next(i for i in tl0.items if i.track == "A1" and i.role == "body")
    _, c2 = R.add_comment(root, tid, talk.rec_in + 0.5, "faster")
    assert c2.status == "not_understood" and "speech" in c2.reply


def test_brief_overrides_are_flagged_and_hooks_cycle(fresh):
    root, tid, pa = fresh
    first = _v1(R.base_timeline(root, tid))[0].ref
    seen = []
    for _ in range(3):
        rev, c = R.add_comment(root, tid, 1.0, "another hook")
        assert "brief" in c.reply                               # the brief chose the hook: say so
        tl, _, _ = R.recompile(root, tid, rev, pa=pa)
        seen.append(_v1(tl)[0].ref)
    assert len(set(seen)) == 3 and seen[-1] == first           # walks every option and comes back
    rev, c = R.add_comment(root, tid, 12.0, "change song")
    assert c.status == "applied" and "brief" in c.reply


def test_unclear_notes_are_reported_not_guessed(fresh):
    root, tid, _ = fresh
    rev, c = R.add_comment(root, tid, 10.0, "add some confetti magic")
    assert c.status == "not_understood" and not [o for o in rev.ops if o.comment_id == c.id]
