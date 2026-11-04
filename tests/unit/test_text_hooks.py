"""On-screen hook text: short, built around the number, and never garbled — no phrase cut mid-thought, no dropped
"not" (which flips the meaning), no dangling "did" / "with" / "every" at the end."""

from __future__ import annotations

import re

import pytest

from prepro.brain.basic import BAD_END, text_hook

CASES = {
    "So today we are in Goa, and I spent only five thousand rupees for three full days.": "₹5000 for 3 days?!",
    "Honestly, it started with one video I almost did not upload.": "1 video I almost didn't upload?!",
    "Today I have a creator who went from zero to a million subscribers in one year.": "Zero to 1M subscribers in 1 year?!",
    "I thought the hook was boring, so I recut the first three seconds eleven times.": "Recut first 3 seconds 11 times?!",
    "Yeh vada pav sirf pandrah rupaye ka hai.": "Yeh vada pav sirf pandrah rupaye",
}


@pytest.mark.parametrize("line,want", list(CASES.items()))
def test_hook_text_reads_like_an_editor_wrote_it(line, want):
    assert text_hook(line) == want


@pytest.mark.parametrize("line", [*CASES, "And the second lesson is to cut every pause that does not carry a feeling.",
                                  "Let me show you exactly how I did it.", "So the lesson is, show the payoff first.",
                                  "Why do some videos get a million views with just a phone camera?"])
def test_hook_text_never_dangles_or_flips_meaning(line):
    t = text_hook(line)
    words = re.sub(r"[?!.,]+$", "", t).split()
    assert words and words[-1].lower() not in BAD_END, t
    if re.search(r"\bnot\b|n't\b", line) and any(w in t.lower() for w in ("upload", "carry")):
        assert "n't" in t or "not" in t, t                       # a negated verb never loses its "not"
    assert len(words) <= 8
