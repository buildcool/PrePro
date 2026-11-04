"""Packaging rules: titles keep the promise (and the numbers), thumbnail text is punchy, chapters follow YouTube's rules."""

from __future__ import annotations

from prepro.packaging import FUNCTION_WORDS, chapters, thumb_text
from prepro.schema.timeline import Item, Timeline


def test_thumb_text_centres_on_the_number_and_never_dangles():
    assert thumb_text("Why do some videos get a million views from a phone camera?").startswith("1M views")
    assert thumb_text("So today we are in Goa, and I spent only five thousand rupees for three full days.") == "₹5000 for 3 days"
    assert thumb_text("I lost ten thousand dollars on my first channel.").startswith("$10,000")
    for h in ("Three editing mistakes that are killing your views.", "The worst mistake beginners make is talking too slowly."):
        t = thumb_text(h)
        assert t and t.split()[-1].lower() not in FUNCTION_WORDS and len(t.split()) <= 6


def _tl(sections, cards):
    items, t = [], 0.0
    for name, dur in sections:
        items.append(Item(id=f"v{len(items)}", track="V1", kind="video", asset_id="C01", src_in=0, src_out=dur, rec_in=t, section=name))
        t += dur
    for t0, txt in cards:
        items.append(Item(id=f"t{len(items)}", track="T1", kind="text", text=txt, style="card", rec_in=t0, duration=2))
    return Timeline(id="x", name="x", direction_id="d1", playbook="story_vlog", fps=30, width=1920, height=1080, items=items)


class _PA:
    def words(self, _):
        return []


def test_chapters_follow_youtube_rules():
    tl = _tl([("cold_open", 5), ("part1", 35), ("part2", 40), ("outro", 12)], [(5, "Day 1 · Goa"), (40, "Day 2 · Jaipur")])
    ch, note = chapters(tl, _PA())
    assert ch[0] == (0.0, "Day 1 · Goa")                     # starts at 0:00; the 5 s intro folds into it
    assert [n for _, n in ch] == ["Day 1 · Goa", "Day 2 · Jaipur", "Outro"] and not note
    assert all(b[0] - a[0] >= 10 for a, b in zip(ch, ch[1:], strict=False))
    short = _tl([("cold_open", 5), ("part1", 20)], [])
    ch, note = chapters(short, _PA())
    assert ch == [] and "minute" in note


def test_caption_detector_sees_outlined_text_over_a_dark_shirt():
    """CI regression: captions drawn over a presenter's dark shirt merged into one tall block and were missed."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from prepro.config import assets_dir
    from prepro.style import _text_band

    W, H = 240, 136
    base = Image.new("RGB", (W, H), (60, 90, 150))
    d = ImageDraw.Draw(base)
    d.ellipse([95, 30, 145, 85], fill=(230, 190, 150))            # a face
    d.rectangle([80, 85, 160, H], fill=(30, 30, 35))               # a dark shirt right under the caption
    clean = np.asarray(base.copy())
    font = ImageFont.truetype(str(assets_dir() / "fonts" / "Anton-Regular.ttf"), 13)
    d.text((W // 2, int(H * 0.72)), "MISTAKES", font=font, fill=(255, 255, 255), anchor="mt", stroke_width=2, stroke_fill=(0, 0, 0))
    assert _text_band(np.asarray(base)) is True
    assert _text_band(clean) is False
