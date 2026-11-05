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
