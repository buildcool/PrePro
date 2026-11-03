"""M1: local analysis scored against the synthetic shoots' ground truth."""

from __future__ import annotations

import pytest
from tests.conftest import needs_ffmpeg, needs_tts, truth

from prepro.analyze.pipeline import analyse_project
from prepro.config import Settings
from prepro.schema.media import AssetKind

pytestmark = [needs_tts, needs_ffmpeg]


def _settings(backend="auto"):
    s = Settings()
    s.asr.backend = backend
    return s


def _by_path(pa):
    return {a.path: a for a in pa.assets}


def _seg_for(ca, t0, t1):
    best, ov = None, 0.0
    for s in ca.transcript.segments:
        o = min(t1, s.t1) - max(t0, s.t0)
        if o > ov:
            best, ov = s, o
    return best


@pytest.fixture(scope="module")
def travel(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    return root, analyse_project(root, settings=_settings())


def test_kinds(travel):
    root, pa = travel
    gt = truth(root)
    bp = _by_path(pa)
    for rel, c in gt["clips"].items():
        want = {"aroll": AssetKind.AROLL, "broll": AssetKind.BROLL, "screen": AssetKind.SCREEN}[c["kind"]]
        assert bp[rel].kind == want, (rel, bp[rel].kind, bp[rel].kind_reason)
    assert all(bp[m].kind == AssetKind.MUSIC for m in gt["music"])
    assert bp["sfx/whoosh.wav"].kind == AssetKind.SFX
    assert bp["memes/bruh_facepalm.gif"].kind == AssetKind.MEME_IMAGE
    assert bp["memes/emotional_damage_fail.mp4"].kind == AssetKind.MEME_VIDEO


def test_speech_cut_candidates_match_truth(travel):
    root, pa = travel
    gt = truth(root)
    bp = _by_path(pa)
    checked = 0
    for rel, c in gt["clips"].items():
        if c["kind"] != "aroll":
            continue
        ca = pa.clips[bp[rel].id]
        assert ca.transcript and ca.transcript.segments, rel
        for line in c["lines"]:
            seg = _seg_for(ca, line["t0"], line["t1"])
            assert seg is not None, (rel, line["text"])
            flagged = (seg.retake_rank > 0 or seg.false_start or "greeting" in seg.tags or "hesitation" in seg.tags)
            if line["keep"]:
                assert not flagged, (rel, line["text"], seg.tags, seg.retake_rank)
            else:
                assert flagged, (rel, line["kind"], line["text"], seg.tags)
            checked += 1
    assert checked >= 10


def test_shot_flags_dups_whips_peaks(travel):
    root, pa = travel
    gt = truth(root)
    bp = _by_path(pa)
    for rel, flag in gt["expect"]["bad_shots"].items():
        flags = {f for s in pa.clips[bp[rel].id].shots for f in s.flags}
        assert flag in flags, (rel, flags)
    for rel, c in gt["clips"].items():
        if c["kind"] == "aroll":
            assert not {f for s in pa.clips[bp[rel].id].shots for f in s.flags}, rel
    a, b = gt["expect"]["dup_pairs"][0]
    ga = {s.dup_group for s in pa.clips[bp[a].id].shots}
    gb = {s.dup_group for s in pa.clips[bp[b].id].shots}
    assert ga & gb - {None}
    assert any(s.whip_out for s in pa.clips[bp["footage/day1/IMG_2047.mp4"].id].shots)
    assert any(s.action_peaks for s in pa.clips[bp["footage/day1/IMG_2046.mp4"].id].shots)


def test_places_days_genres(travel):
    _, pa = travel
    assert pa.stats["places"] == 2 and pa.stats["days"] == 2
    places = {c.place for c in pa.clips.values() if c.place}
    assert "Jaipur" in places
    assert pa.genres[0].playbook == "story_vlog"
    assert {"travel_film", "teaser"} <= {g.playbook for g in pa.genres}


def test_music_bpm_and_drop(travel):
    root, pa = travel
    gt = truth(root)
    bp = _by_path(pa)
    for rel, m in gt["music"].items():
        info = pa.clips[bp[rel].id].music
        assert info and abs(info.bpm - m["bpm"]) / m["bpm"] < 0.03, (rel, info and info.bpm)
    epic = pa.clips[bp["music/epic_build_128.wav"].id].music
    drop = next(s for s in epic.sections if s.label == "drop")
    t_drop = next(s for s in gt["music"]["music/epic_build_128.wav"]["sections"] if s[0] == "drop")
    assert abs(drop.t0 - t_drop[1]) < 2.5 and abs(drop.t1 - t_drop[2]) < 3.5


def test_pocketsphinx_finds_false_start(shoot_factory):
    root = shoot_factory("travel_vlog", sidecars=False)
    pa = analyse_project(root, settings=_settings("auto"))
    gt = truth(root)
    bp = _by_path(pa)
    ca = pa.clips[bp["footage/day1/IMG_2041.mp4"].id]
    assert ca.transcript.backend in ("pocketsphinx", "faster-whisper")
    fs = next(ln for ln in gt["clips"]["footage/day1/IMG_2041.mp4"]["lines"] if ln["kind"] == "false_start")
    seg = _seg_for(ca, fs["t0"], fs["t1"])
    assert seg.false_start or seg.retake_rank > 0, [(s.text, s.tags, s.retake_rank) for s in ca.transcript.segments]
    filler = next(ln for ln in gt["clips"]["footage/day1/IMG_2041.mp4"]["lines"] if ln["kind"] == "filler")
    seg = _seg_for(ca, filler["t0"], filler["t1"])
    assert "micro" in seg.tags or "hesitation" in seg.tags


@pytest.mark.parametrize("kind,top", [("gaming", "gaming"), ("aesthetic_cooking", "aesthetic"), ("talking_head", "talking_head"),
                                      ("hype_reel", "hype_reel")])
def test_genre_detection(shoot_factory, kind, top):
    root = shoot_factory(kind)
    pa = analyse_project(root, settings=_settings())
    assert pa.genres[0].playbook == top, [(g.playbook, g.score, g.why) for g in pa.genres]


def test_hindi_sidecar_and_fillers(shoot_factory):
    root = shoot_factory("hindi_vlog")
    pa = analyse_project(root, settings=_settings())
    a = next(x for x in pa.assets if x.path.endswith("VID_hi_01.mp4"))
    tr = pa.clips[a.id].transcript
    assert tr.backend == "sidecar" and tr.language == "hi"
    assert any(w.filler for w in tr.words if w.text.startswith("अम्म"))
    assert pa.speech_language == "hi"
