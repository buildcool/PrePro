"""Photo reels — a photo dump, and one photo + your words + a song: the photos an editor leaves out, the order they
were taken in, a cover that fills the frame, cuts on the song's beat from its chorus, photos that move smoothly, a
group photo never cut, a seamless loop, and your lines word for word, on the beat, readable and off the faces —
checked against the planted ground truth of the photo fixtures."""

from __future__ import annotations

import numpy as np
import pytest
from tests.conftest import needs_ffmpeg, truth

from prepro.engine import analysis, build

pytestmark = [needs_ffmpeg]


@pytest.fixture(scope="module")
def dump(shoot_factory):
    root = shoot_factory("photo_dump")
    return root, build(root, render=False)


@pytest.fixture(scope="module")
def single(shoot_factory):
    root = shoot_factory("photo_single")
    return root, build(root, render=True)


def _v1(tl):
    return sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)


def test_photos_read_upright_with_their_time_and_place(dump):
    from PIL import Image

    from prepro.analyze.pipeline import photo_copy
    from prepro.project import Project

    root, _ = dump
    pa = analysis(root)
    by = {a.path: a for a in pa.assets}
    for rel, size in truth(root)["expect"]["sideways"].items():           # stored sideways + an EXIF orientation tag
        assert list(by[rel].info.display_size) == size
        with Image.open(photo_copy(Project(root), by[rel])) as im:       # the working copy is upright
            assert list(im.size) == size
    a = by["photos/IMG_0001.jpg"]
    assert a.info.creation_time.utcoffset().total_seconds() == 5.5 * 3600  # the camera's local time, with its offset
    assert abs(a.info.location.lat - 15.5527) < 1e-3 and abs(a.info.location.lon - 73.7517) < 1e-3


def test_leaves_out_what_an_editor_would_and_keeps_the_order_taken(dump):
    root, res = dump
    gt = truth(root)["expect"]
    pa = analysis(root)
    used = {pa.asset(i.asset_id).path for i in res.timeline.items if i.track == "V1"}
    for rel, why in gt["left_out"].items():                                # burst duplicate, blurry, dark
        assert rel not in used, (rel, why)
    order = [pa.asset(i.asset_id).path for i in _v1(res.timeline) if i.role == "photo"]
    assert order == [p for p in gt["order"] if p in order]                 # by EXIF time, not by file name
    assert len(order) >= 5


def test_cover_fills_the_frame_and_the_reel_loops_seamlessly(dump):
    root, res = dump
    gt = truth(root)["expect"]
    pa = analysis(root)
    v1 = _v1(res.timeline)
    assert v1[0].role == "hook" and pa.asset(v1[0].asset_id).path in gt["covers"] and not v1[0].transform.fit
    assert v1[-1].role == "loop" and v1[-1].asset_id == v1[0].asset_id
    end, start = v1[-1].transform.keys[-1], v1[0].transform.keys[0]       # the last frame is the first frame
    assert (end.cx, end.cy, end.zoom) == pytest.approx((start.cx, start.cy, start.zoom))


def test_cuts_land_on_the_beat_from_the_chorus(dump):
    root, res = dump
    gt, song = truth(root)["expect"], truth(root)["music"]["music/golden_hour_100.wav"]
    tl = res.timeline
    music = next(i for i in tl.items if i.track == "A2")
    assert abs(music.src_in - gt["song_chorus"]) < 0.1                     # the song starts on its chorus downbeat
    for it in _v1(tl)[1:]:
        assert min(abs(music.src_in + it.rec_in - b) for b in song["beats"]) < 0.05, it.rec_in
    assert not tl.captions and not [i for i in tl.items if i.track == "A3"]   # photos, the song, words: nothing else


def test_photos_move_and_a_group_photo_is_never_cut(dump):
    root, res = dump
    pa = analysis(root)
    for it in _v1(res.timeline):                                           # never a frozen still
        assert it.transform and len({(k.cx, k.cy, k.zoom) for k in it.transform.keys}) > 1, it.asset_id
    group = [i for i in _v1(res.timeline) if pa.asset(i.asset_id).path == truth(root)["expect"]["group"]]
    assert group and all(i.transform.fit for i in group)                   # shown whole: nobody cut out at the sides
    assert res.critic.scores["genre_fit"] >= 9.5 and res.critic.scores["no_cringe"] >= 9.5
    assert not [f for f in res.lint if f.severity in ("error", "warn")], res.lint


def _on_beats(root, tl) -> bool:
    song = truth(root)["music"]["music/golden_hour_100.wav"]
    music = next(i for i in tl.items if i.track == "A2")
    return all(min(abs(music.src_in + it.rec_in - b) for b in song["beats"]) < 0.05 for it in _v1(tl)[1:])


def test_every_reel_decision_can_be_undone_and_stays_on_the_beat(dump, tmp_path):
    import shutil

    from prepro import revise as R

    src, _ = dump
    root = tmp_path / "reel"
    shutil.copytree(src, root)                            # a brief is added below: keep the shared fixture clean
    lines = ["golden hour hits different", "breakfast by the sea", "the best part of the day"]
    res = build(root, render=False, brief_text="Text:\n" + "\n".join(lines) + "\n")
    tl, pa = res.timeline, analysis(root)
    path = lambda i: pa.asset(i.asset_id).path                                  # noqa: E731
    keys = {s.payload.get("key") for s in tl.suggestions}
    left_out = {f"shot:{pa.clips[a.id].shots[0].id}": a.path for a in pa.assets if a.path in truth(root)["expect"]["left_out"]}
    assert set(left_out) <= keys                                                # each photo left out says why
    assert "photomotion" in keys and any(k and k.startswith("cover:") for k in keys) and any(k and k.startswith("loop:") for k in keys)
    texts = sorted((i for i in tl.items if i.kind == "text"), key=lambda i: i.rec_in)
    pics = [i for i in _v1(tl) if i.role != "loop"]
    assert [t.text for t in texts] == lines and [t.rec_in for t in texts] == pytest.approx([p.rec_in for p in pics[:3]])

    # drop the second photo: the lines move with the pictures, and every cut is still on the beat
    tl2, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, f"item:{pics[1].ref}", "rejected"), pa=pa)
    pics2 = [i for i in _v1(tl2) if i.role != "loop"]
    texts2 = sorted((i for i in tl2.items if i.kind == "text"), key=lambda i: i.rec_in)
    assert pics[1].ref not in {p.ref for p in pics2} and [t.text for t in texts2] == lines
    assert [t.rec_in for t in texts2] == pytest.approx([p.rec_in for p in pics2[:3]]) and _on_beats(root, tl2)
    assert all(t.duration >= 0.6 + len(t.text.split()) / 3.0 for t in texts2)

    # bring back the blurry photo: it returns in the order it was taken, on the beat
    blurry = next(k for k, p in left_out.items() if "0006" in p)
    tl3, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, blurry, "rejected"), pa=pa)
    order = [path(i) for i in _v1(tl3) if i.role == "photo"]
    assert "photos/IMG_0006.jpg" in order and order == sorted(order, key=lambda p: truth(root)["expect"]["order"].index(p)
                                                                if p in truth(root)["expect"]["order"] else 3.5) and _on_beats(root, tl3)

    # another cover: the loop ends on it, the old cover stays in the reel
    old_cover = _v1(tl3)[0]
    tl4, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, f"cover:{old_cover.ref}", "rejected"), pa=pa)
    v4 = _v1(tl4)
    assert v4[0].ref != old_cover.ref and v4[-1].ref == v4[0].ref and old_cover.ref in {i.ref for i in v4[1:-1]} and _on_beats(root, tl4)
    photos = [i for i in v4 if i.role == "photo"]
    lined = {p.rec_in for p in photos if any(abs(t.rec_in - p.rec_in) < 0.01 for t in tl4.items if t.kind == "text")}
    plain = [p.rec_dur for p in photos[:-1] if p.rec_in not in lined]
    assert plain and photos[-1].rec_dur > 1.6 * max(plain)                # the rhythm survives: the last photo still holds longest

    # photos still: every photo framed, none moving
    tl5, _, _ = R.recompile(root, tl.id, R.toggle(root, tl.id, "photomotion", "rejected"), pa=pa)
    assert all(i.transform is not None and not i.transform.keys for i in _v1(tl5))


def test_change_the_song_rebuilds_the_reel_on_its_beat(dump, tmp_path):
    """"change the song" in the review: the reel is rebuilt on the other song — every cut on its beats, from its own
    strong part, the photos still in the order taken, one pass of the song (no restart mid-reel) — and the old song is
    the way back."""
    import shutil

    from prepro import revise as R
    from prepro.fixtures import audio as A

    src, _ = dump
    root = tmp_path / "two_songs"
    shutil.copytree(src, root)
    y, epic = A.procedural_music(bpm=128, minor=False, mood="epic", seed=21,
                                 sections=[("intro", 2, 0.3), ("build", 2, 0.6), ("drop", 6, 1.0), ("outro", 2, 0.35)])
    A.write_wav(root / "music" / "epic_drive_128.wav", y)
    beats = {"music/epic_drive_128.wav": epic.beats, "music/golden_hour_100.wav": truth(root)["music"]["music/golden_hour_100.wav"]["beats"]}
    tl = build(root, render=False).timeline
    pa = analysis(root)
    song = lambda t: next(i for i in t.items if i.track == "A2")                          # noqa: E731
    first = pa.asset(song(tl).asset_id).path
    rev, c = R.add_comment(root, tl.id, 1.0, "change the song")
    assert c.status == "applied" and "Swapped the song" in c.reply
    tl2, _, _ = R.recompile(root, tl.id, rev, pa=pa)
    m2 = song(tl2)
    other = pa.asset(m2.asset_id).path
    assert other != first and len([i for i in tl2.items if i.track == "A2"]) == 1
    assert all(min(abs(m2.src_in + i.rec_in - b) for b in beats[other]) < 0.05 for i in _v1(tl2)[1:])     # on the new beat
    order = [pa.asset(i.asset_id).path for i in _v1(tl2) if i.role == "photo"]
    assert order == sorted(order, key=lambda p: truth(root)["expect"]["order"].index(p))
    why = next(s for s in tl2.suggestions if s.type == "music")
    assert "your pick" in why.reason and why.alternatives
    # and back: the reel the build made
    rev, _ = R.add_comment(root, tl.id, 1.0, "change the song")
    tl3, _, _ = R.recompile(root, tl.id, rev, pa=pa)
    assert pa.asset(song(tl3).asset_id).path == first
    assert [(i.ref, round(i.rec_dur, 3)) for i in _v1(tl3)] == [(i.ref, round(i.rec_dur, 3)) for i in _v1(tl)]


def test_photo_motion_renders_smoothly(dump):
    import cv2

    from prepro.analyze.pipeline import photo_copy
    from prepro.export.render import photo_frames
    from prepro.project import Project

    root, res = dump
    pa = analysis(root)
    pan = next(i for i in _v1(res.timeline) if i.transform.keys and abs(i.transform.keys[0].cx - i.transform.keys[-1].cx) > 0.01)
    frames = list(photo_frames(photo_copy(Project(root), pa.asset(pan.asset_id)), pan, 540, 960, 30.0, 30))
    g = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frames]
    shifts = [cv2.phaseCorrelate(g[k], g[k + 1])[0][0] for k in range(len(g) - 1)]
    assert abs(np.mean(shifts)) > 0.3 and np.std(shifts) < 0.1             # a steady glide, no whole-pixel stepping


def test_one_photo_your_lines_on_the_beat_readable_and_off_the_face(single):
    from prepro.lint.editlint import compliance
    from prepro.timeline.captions import text_block

    root, res = single
    gt, song = truth(root)["expect"], truth(root)["music"]["music/warm_acoustic_92.wav"]
    tl = res.timeline
    texts = sorted((i for i in tl.items if i.kind == "text"), key=lambda i: i.rec_in)
    assert [t.text for t in texts] == gt["lines"]                          # word for word, in order
    assert texts[0].rec_in < 0.05                                          # the first line is the hook: frame one
    music = next(i for i in tl.items if i.track == "A2")
    for t in texts[1:]:
        assert min(abs(music.src_in + t.rec_in - b) for b in song["beats"]) < 0.05
    for t in texts:
        assert t.duration >= 0.6 + len(t.text.split()) / 3.0               # long enough to read
    pa = analysis(root)
    photo = _v1(tl)[0]
    face = max(pa.clips[photo.asset_id].shots[0].faces, key=lambda f: f.w * f.h)
    ds = pa.asset(photo.asset_id).info.display_size
    src_ar, out_ar = ds[0] / ds[1], tl.width / tl.height
    for t in texts:                                                        # each line clears the face while it is up,
        h = text_block(t.text, t.style, tl.width, tl.height, t.text_scale or 1.0)[1]   # wherever the push-in has taken it
        assert (t.text_scale or 1.0) >= 0.76                               # never shrunk past readable
        for at in (t.rec_in, t.rec_out):
            _cx, cy, z = photo.transform.at(at - photo.rec_in)
            cw, ch = ((out_ar / src_ar) / z, 1 / z) if src_ar > out_ar else (1 / z, (src_ar / out_ar) / z)
            top = min(max(cy - ch / 2, 0.0), 1 - ch)
            f0, f1 = (face.y - face.h / 2 - top) / ch, (face.y + face.h / 2 - top) / ch
            assert t.text_y is not None and (t.text_y + h / 2 <= f0 or t.text_y - h / 2 >= f1), (t.text, at, t.text_y, h, f0, f1)
    assert all(c.ok for c in compliance(tl, pa, res.direction, res.brief)), compliance(tl, pa, res.direction, res.brief)
    assert res.render and abs(res.render.lufs + 14) <= 1.0 and res.render.true_peak_db <= -0.8
