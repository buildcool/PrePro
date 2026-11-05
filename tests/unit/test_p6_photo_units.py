"""The pieces under photo reels: phone EXIF (time zone, GPS, orientation), the creator's "Text:" block, line breaks that
never strand a "the", bar lines found from chord changes, and a limiter that keeps the true peak under −1 dBTP."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest


def test_phone_exif_time_zone_gps_and_orientation(tmp_path):
    from PIL import Image

    from prepro.fixtures import visual as V
    from prepro.media.probe import photo_exif, probe

    img = Image.new("RGB", (400, 300), (200, 120, 60))
    p = V.photo(img, tmp_path / "IMG_1.jpg", taken="2026:10:10 08:02:10", gps=(15.5527, 73.7517), orientation=6)
    rot, when, gps = photo_exif(p)
    assert rot == 90 and when.utcoffset() == timedelta(hours=5, minutes=30) and when.hour == 8
    assert gps.lat == pytest.approx(15.5527, abs=1e-4) and gps.lon == pytest.approx(73.7517, abs=1e-4)
    info = probe(p)
    with Image.open(p) as raw:
        assert raw.size == (300, 400)                           # the pixels are stored sideways…
    assert info.display_size == (400, 300)                      # …and shown upright
    q = V.photo(img, tmp_path / "IMG_2.jpg", taken="2026:10:10 08:02:10", offset=None)
    assert photo_exif(q)[1].tzinfo is not None                   # no offset tag: this PC's time zone, never naive


def test_text_block_in_a_brief_becomes_your_lines():
    from prepro.brief.parse import parse_text

    b = parse_text("Text:\nPOV: you finally took the trip\n3 days, 1 backpack\n\nUse the warm song.\n\"and it was everything\"\n")
    lines = [r.target for r in sorted((r for r in b.rules if r.kind == "text_line"), key=lambda r: r.value)]
    assert lines == ["POV: you finally took the trip", "3 days, 1 backpack", "and it was everything"]
    assert not any(r.kind == "text_line" and "warm" in r.target for r in b.rules)


def test_line_breaks_are_balanced_and_never_end_on_a_glue_word():
    from prepro.timeline.captions import balance_lines, text_block

    lines = balance_lines("POV: you finally took the trip you kept postponing", 30)
    assert len(lines) == 2 and lines[0].split()[-1].lower() not in ("the", "a", "to", "you") and abs(len(lines[0]) - len(lines[1])) < 12
    assert balance_lines("short line", 30) == ["short line"]
    glue = ("the", "a", "an", "to", "of", "and")
    many, h = text_block("POV: you finally took the trip you kept postponing", "photo", 1080, 1920)   # measured with the font
    assert 2 <= len(many) <= 3 and not any(x.split()[-1].lower() in glue for x in many[:-1]) and 0.05 < h < 0.2
    small, h2 = text_block("POV: you finally took the trip you kept postponing", "photo", 1080, 1920, 0.84)
    assert len(small) == 2 and small[0].split()[-1].lower() not in glue and h2 < h   # smaller: two lines fit


def test_downbeats_follow_the_chords_not_just_the_kick():
    from prepro.analyze.sound import music_info
    from prepro.fixtures import audio as A

    # kick on beats 1 and 3: the low end alone can't tell bar lines from the middle of the bar
    y, t = A.procedural_music(bpm=100, minor=False, seed=16, sections=[("verse", 6, 0.6), ("chorus", 6, 0.75)])
    info = music_info(y, A.SR)
    beat = 60 / t.bpm
    for d in info.downbeats[1:-1]:
        assert min(abs(d - x) for x in t.downbeats) < 0.25 * beat, (d, t.downbeats[:6])


def test_limiter_holds_the_true_peak():
    from prepro.export.render import SR, _limit, _true_peak

    rng = np.random.default_rng(0)
    n = SR * 3
    tt = np.arange(n) / SR
    x = (np.sign(np.sin(2 * np.pi * 997 * tt)) * 0.9 + 0.3 * rng.standard_normal(n)).astype(np.float32)   # harsh, dense
    y = _limit(np.stack([x, x], -1) * 2.0, 10 ** (-1 / 20))
    assert 20 * np.log10(_true_peak(y)) <= -0.95                 # between the samples too, not only at them
