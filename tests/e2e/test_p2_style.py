"""Style DNA: reference videos are measured (not edited), the numbers match what the references really are, and the
next build is steered by them — unless the creator's own knobs/brief say otherwise."""

from __future__ import annotations

import shutil

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

from prepro.engine import analysis, build
from prepro.fixtures.shoots import style_references
from prepro.project import Project
from prepro.style import load, measure_shoot

pytestmark = [needs_tts, needs_ffmpeg]


@pytest.fixture(scope="module")
def refs(shoot_factory, tmp_path_factory):
    th = shoot_factory("talking_head")
    out = tmp_path_factory.mktemp("refs")
    return style_references(out, talking_clip=th / "A001.mp4"), th


@pytest.fixture()
def shoot(refs, tmp_path):
    _, th = refs
    root = tmp_path / "shoot"
    shutil.copytree(th, root, ignore=shutil.ignore_patterns(".prepro", "PrePro_exports"))
    return root


def test_references_are_measured_not_edited(refs, shoot):
    r, _ = refs
    (shoot / "style").mkdir()
    shutil.copy(r["fast"], shoot / "style" / r["fast"].name)
    assert [p.name for p in Project(shoot).scan().style_refs] == ["fast_montage.mp4"]
    pa = analysis(shoot)
    assert not any("style/" in a.path for a in pa.assets)
    dna = measure_shoot(shoot)
    assert dna.cuts_per_min > 60 and dna.shot_median < 1.0 and dna.speech_ratio < 0.1 and dna.music_ratio > 0.8
    assert dna.knobs["pace"] >= 0.85 and dna.knobs["captions"] == "off" and dna.knobs["effects"] == "bold"
    res = build(shoot, render=False)
    assert res.direction.knobs.pace == dna.knobs["pace"] and "styled like your references" in res.direction.why
    assert res.direction.knobs.shot_len == dna.knobs["shot_len"]
    dna.enabled = False
    Project(shoot).save_model("style.json", dna)
    res2 = build(shoot, render=False)
    assert "styled like" not in res2.direction.why


def test_talking_reference_with_captions(refs, shoot):
    r, _ = refs
    (shoot / "style").mkdir()
    shutil.copy(r["talky"], shoot / "style" / r["talky"].name)
    dna = measure_shoot(shoot)
    assert dna.speech_ratio > 0.5 and dna.text_ratio > 0.6 and dna.cuts_per_min < 5
    assert dna.knobs["captions"] == "bold" and dna.knobs["pace"] <= 0.4 and "tightness" in dna.knobs
    assert load(shoot).summary
    # the creator's explicit knob wins over the style
    res = build(shoot, render=False, knobs={"captions": "off"})
    assert res.direction.knobs.captions == "off"
