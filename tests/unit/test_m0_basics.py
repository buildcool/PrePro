from __future__ import annotations

import numpy as np
import pytest
from tests.conftest import needs_ffmpeg, needs_tts, truth

from prepro.fixtures import audio as A
from prepro.media.probe import parse_iso6709, probe
from prepro.project import Project, assign_ids, filename_tags


def test_iso6709():
    g = parse_iso6709("+26.9124+075.7873/")
    assert g and abs(g.lat - 26.9124) < 1e-6 and abs(g.lon - 75.7873) < 1e-6
    assert parse_iso6709("garbage") is None


def test_filename_tags():
    assert filename_tags("HOOK_MUST_IMG_1.mov") == (["hook", "must"], "IMG_1.mov")
    assert filename_tags("IMG_1.mov") == ([], "IMG_1.mov")


def test_procedural_music_truth():
    y, t = A.procedural_music(bpm=120, sections=[("intro", 2, 0.3), ("drop", 2, 1.0)], seed=1)
    assert abs(len(t.beats) - 16) <= 0
    assert t.downbeats[1] == pytest.approx(2.0, abs=1e-3)       # 4 beats @120bpm = 2 s
    assert t.sections[1][0] == "drop" and t.sections[1][1] == pytest.approx(4.0, abs=1e-3)
    assert np.isfinite(y).all() and np.max(np.abs(y)) <= 1.0


def test_sfx_kinds():
    for k in ("whoosh", "pop", "riser", "impact", "ding", "scratch", "click", "laugh", "waves", "explosion"):
        y = A.sfx(k)
        assert y.size > 100 and np.isfinite(y).all()


@needs_tts
@needs_ffmpeg
def test_demo_shoot_scan_and_probe(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    gt = truth(root)
    proj = Project(root)
    scan = proj.scan()
    rels = {f.rel for f in scan.files}
    assert "footage/day1/IMG_2041.mp4" in rels and "music/epic_build_128.wav" in rels
    assert any(p.name == "brief.md" for p in scan.brief_files)
    assert any(p.name == "notes.yaml" for p in scan.notes_files)
    assert all(not r.startswith(".prepro") for r in rels)
    ids = assign_ids(scan.files)
    assert ids["footage/day1/IMG_2041.mp4"].startswith("C") and ids["music/chill_lofi_90.wav"].startswith("A")
    # stable when re-assigned with the previous mapping
    from prepro.project import fast_hash

    prev = {fast_hash(f.path): ids[f.rel] for f in scan.files}
    assert assign_ids(scan.files, prev) == ids
    info = probe(root / "footage/day1/IMG_2046.mp4")
    assert info.has_video and round(info.fps or 0) == 60
    assert info.location and abs(info.location.lat - 15.5527) < 1e-3
    assert info.creation_time is not None
    a = probe(root / "footage/day1/IMG_2041.mp4")
    assert a.has_audio and a.duration > 5
    assert len(gt["clips"]["footage/day1/IMG_2041.mp4"]["lines"]) == 5
