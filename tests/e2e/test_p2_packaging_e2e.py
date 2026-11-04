"""Packaging on a real cut: thumbnails at the right size from different kinds of frames, titles with the numbers."""

from __future__ import annotations

import pytest
from PIL import Image
from tests.conftest import needs_ffmpeg, needs_tts

from prepro.engine import analysis, build
from prepro.packaging import package

pytestmark = [needs_tts, needs_ffmpeg]


@pytest.fixture(scope="module")
def cut(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    return root, build(root, render=False).timeline, analysis(root)


def test_travel_packaging(cut, tmp_path):
    root, tl, pa = cut
    pk = package(tl, pa, tmp_path / "pk", project_root=root)
    assert pk.titles and any("₹5,000" in t for t in pk.titles) and all(len(t) <= 70 for t in pk.titles)
    assert any("→" in t for t in pk.titles)                                        # two places → a journey title
    assert len(pk.thumbs) == 3 and len({t.why for t in pk.thumbs}) >= 2              # a face AND scenery/action, not 3 faces
    for th in pk.thumbs:
        im = Image.open(root / th.path if not th.path.startswith("/") else th.path)
        assert im.size == ((1080, 1920) if tl.height > tl.width else (1280, 720))
    assert "#jaipur" in pk.hashtags and "#shorts" in pk.hashtags
    assert (tmp_path / "pk" / "packaging.md").exists() and pk.description.startswith(pk.titles[0])
