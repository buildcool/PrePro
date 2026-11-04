"""M4: exports. Every hand-off file is read back by an independent tool (OTIO adapters, melt, ffprobe/ebur128)
and checked against the timeline it came from — an export that imports "fine" but drifts by a few frames is a bug."""

from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

from prepro.engine import analysis, build
from prepro.export.package import export_all
from prepro.media.ffmpeg import ffmpeg_bin, ffprobe_json

pytestmark = [needs_tts, needs_ffmpeg]

FAST = ["fcp7", "otio", "kdenlive", "mlt", "srt", "overlay", "report"]


@pytest.fixture(scope="module")
def cut(shoot_factory, tmp_path_factory):
    root = shoot_factory("travel_vlog", brief=True)
    res = build(root, render=False)
    pa = analysis(root)
    out = tmp_path_factory.mktemp("exports")
    made = export_all(res.timeline, pa, out, formats=FAST, project_root=root, critic=res.critic, lint=res.lint,
                      direction=res.direction, brief=res.brief)
    return root, res, pa, out, made


def _frames(t: float, fps: float) -> int:
    return int(round(t * fps))


def _v1(tl):
    return sorted((i for i in tl.items if i.track == "V1" and i.kind in ("video", "image")), key=lambda i: i.rec_in)


def test_every_requested_file_exists(cut):
    _, res, _, out, made = cut
    for k in ("fcp7", "otio", "mlt", "report", "overlay"):
        assert k in made and made[k].exists() and made[k].stat().st_size > 200, k
    if res.timeline.captions:
        assert made["srt"].exists() and made["vtt"].exists()


# ---------------------------------------------------------------- Premiere / Resolve (FCP7 XML)
def test_fcp7_xml_structure(cut):
    _, res, _, _, made = cut
    tl = res.timeline
    root = ET.parse(made["fcp7"]).getroot()
    assert root.tag == "xmeml" and root.get("version") == "5"
    seq = root.find(".//sequence")
    assert seq is not None
    assert int(seq.findtext("rate/timebase")) == round(tl.fps)
    assert abs(int(seq.findtext("duration")) - _frames(tl.duration, tl.fps)) <= 1
    fmt = seq.find("media/video/format/samplecharacteristics")
    assert (int(fmt.findtext("width")), int(fmt.findtext("height"))) == (tl.width, tl.height)
    # organised bins come with the project
    bins = {b.findtext("name") for b in root.iter("bin")}
    assert any(b.startswith("A-roll") for b in bins) and any(b.startswith("B-roll · Day") for b in bins) and "Music" in bins, bins
    # every referenced media file exists on disk (relinking is the #1 import pain)
    urls = {e.text for e in root.iter("pathurl")}
    assert urls
    for u in urls:
        p = Path(unquote(urlparse(u).path))
        assert p.exists(), u
    # suggestion markers carry the reason so the editor sees *why* in the NLE
    comments = [m.findtext("comment") or "" for m in seq.iter("marker")]
    assert comments and all(c.strip() for c in comments)


def test_fcp7_reads_back_identically_through_otio(cut):
    otio = pytest.importorskip("opentimelineio")
    if "fcp_xml" not in otio.adapters.available_adapter_names():
        pytest.skip("otio-fcp-adapter not installed (pip install prepro[export])")
    _, res, _, _, made = cut
    tl = res.timeline
    t = otio.adapters.read_from_file(str(made["fcp7"]), adapter_name="fcp_xml")
    if isinstance(t, otio.schema.SerializableCollection):
        t = next(iter(t))
    v1 = t.video_tracks()[0]
    clips = [c for c in v1 if isinstance(c, otio.schema.Clip)]
    assert len(clips) == len(_v1(tl))
    assert abs(t.duration().to_seconds() - tl.duration) <= 2 / tl.fps
    # cut points survive: each V1 clip starts where the timeline item starts (transitions may shift by the overlap)
    starts = [v1.range_of_child(c).start_time.to_seconds() for c in clips]
    for s, it in zip(starts, _v1(tl), strict=False):
        assert abs(s - it.rec_in) <= max(1.5 / tl.fps, (it.transition_dur or 0) / 2 + 1 / tl.fps), (s, it.rec_in)
    n_markers = len(list(t.tracks.markers)) + sum(len(c.markers) for c in t.find_clips())
    assert n_markers >= len(tl.markers)
    assert t.audio_tracks(), "dialogue/music/SFX tracks missing"


# ---------------------------------------------------------------- Kdenlive (OTIO) + Shotcut (MLT)
def test_otio_roundtrip(cut):
    otio = pytest.importorskip("opentimelineio")
    _, res, _, _, made = cut
    tl = res.timeline
    t = otio.adapters.read_from_file(str(made["otio"]))
    assert abs(t.duration().to_seconds() - tl.duration) <= 2 / tl.fps
    v1 = t.video_tracks()[0]
    assert len([c for c in v1 if isinstance(c, otio.schema.Clip)]) == len(_v1(tl))
    for c in t.find_clips():
        if isinstance(c.media_reference, otio.schema.ExternalReference):
            assert Path(unquote(urlparse(c.media_reference.target_url).path)).exists()
    if "kdenlive" in made:
        k = ET.parse(made["kdenlive"]).getroot()
        assert k.tag == "mlt" and k.findall("producer") or k.findall("chain")


def _playlist_frames(pl) -> int:
    n = 0
    for e in pl:
        if e.tag == "blank":
            n += int(e.get("length"))
        elif e.tag == "entry":
            n += int(e.get("out")) - int(e.get("in")) + 1
    return n


def test_mlt_tracks_match_timeline(cut):
    _, res, _, _, made = cut
    tl = res.timeline
    r = ET.parse(made["mlt"]).getroot()
    total = _frames(tl.duration, tl.fps)
    pls = {p.get("id"): _playlist_frames(p) for p in r.findall("playlist")}
    assert pls
    assert all(n <= total + 1 for n in pls.values()), pls
    v1 = [n for k, n in pls.items() if k.startswith("playlist_V1")]
    assert v1 and abs(max(v1) - total) <= 1, (v1, total)          # slow-mo entries must not shorten the picture track
    if any(abs(i.speed - 1) > 1e-3 for i in tl.items if i.track == "V1"):
        services = [p.findtext("property[@name='mlt_service']") for p in r.findall("producer")]
        assert "timewarp" in services


@pytest.mark.skipif(shutil.which("melt") is None, reason="melt (MLT) not installed")
def test_mlt_renders_headless_with_melt(cut, tmp_path):
    _, res, _, _, made = cut
    tl = res.timeline
    prof = tmp_path / "profile"
    prof.write_text(f"description=test\nframe_rate_num={round(tl.fps)}\nframe_rate_den=1\nwidth={tl.width}\nheight={tl.height}\n"
                    f"progressive=1\nsample_aspect_num=1\nsample_aspect_den=1\ndisplay_aspect_num={tl.width}\n"
                    f"display_aspect_den={tl.height}\ncolorspace=709\n")
    out = tmp_path / "melt.mp4"
    w = 270 if tl.height > tl.width else 480
    h = 480 if tl.height > tl.width else 270
    subprocess.run(["melt", "-profile", str(prof), str(made["mlt"]), "-consumer", f"avformat:{out}", "vcodec=libx264", "acodec=aac",
                    "preset=ultrafast", f"s={w}x{h}", "-silent"], check=True, timeout=1200, capture_output=True)
    info = ffprobe_json(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(v.get("duration") or info["format"]["duration"]) - tl.duration) <= 3 / tl.fps


# ---------------------------------------------------------------- captions
def test_srt_and_vtt_are_valid(cut):
    _, res, _, _, made = cut
    tl = res.timeline
    if not tl.captions:
        pytest.skip("no captions in this cut")
    blocks = [b for b in made["srt"].read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
    assert len(blocks) == len(tl.captions)
    prev = -1.0
    rx = re.compile(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)")
    for b in blocks:
        lines = b.split("\n")
        m = rx.fullmatch(lines[1])
        assert m, lines[1]
        g = [int(x) for x in m.groups()]
        t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        assert prev - 1e-3 <= t0 < t1 <= tl.duration + 0.05
        assert 1 <= len(lines[2:]) <= 2 and all(x.strip() for x in lines[2:])
        prev = t0
    assert made["vtt"].read_text(encoding="utf-8").startswith("WEBVTT")


def test_caption_overlay_is_transparent_and_full_length(cut):
    _, res, _, _, made = cut
    tl = res.timeline
    info = ffprobe_json(made["overlay"])
    v = info["streams"][0]
    assert v["codec_name"] == "prores" and v["pix_fmt"].startswith("yuva"), v["pix_fmt"]
    assert (v["width"], v["height"]) == (tl.width, tl.height)
    assert abs(float(info["format"]["duration"]) - tl.duration) <= 2 / tl.fps


# ---------------------------------------------------------------- hand-off report
def test_editor_brief_is_a_complete_handoff(cut):
    _, res, _, _, made = cut
    tl = res.timeline
    doc = made["report"].read_text(encoding="utf-8")
    for section in ("Quality scorecard", "Creator brief checklist", "Every decision", "Paper edit"):
        assert section in doc, section
    assert "❌" not in doc, "a brief instruction was not met"
    applied = [s for s in tl.suggestions if s.status == "applied"]
    assert doc.count("<tr>") >= len(applied)
    assert "<script" not in doc.lower()          # static, safe to email


# ---------------------------------------------------------------- phone pack (InShot / VN / Edits)
def _ebur128(path: Path) -> float:
    p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1])


@pytest.mark.slow
def test_phone_pack_meets_delivery_specs(cut, tmp_path):
    root, res, pa, _, _ = cut
    tl = res.timeline
    made = export_all(tl, pa, tmp_path, formats=["phone"], project_root=root)
    for key in ("phone_captioned", "phone_clean", "cue_sheet", "beat_plan"):
        assert made[key].exists(), key
    for key in ("phone_captioned", "phone_clean"):
        info = ffprobe_json(made[key])
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert (v["width"], v["height"]) == (tl.width, tl.height)
        assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p", (v["codec_name"], v["pix_fmt"])
        assert v["r_frame_rate"] == v["avg_frame_rate"], "must be constant frame rate for phone editors"
        assert a["codec_name"] == "aac" and int(a["sample_rate"]) == 48000
        assert abs(float(info["format"]["duration"]) - tl.duration) <= 0.1
        assert abs(_ebur128(made[key]) + 14) <= 1.0
    if "phone_no_music" in made:
        assert made["phone_no_music"].exists()
    stems = made.get("stems")
    assert stems and {p.stem for p in stems.glob("*.wav")} >= {"dialogue", "music"}
    cue = made["cue_sheet"].read_text(encoding="utf-8")
    assert "1_captioned.mp4" in cue and "TEXT TO ADD" in cue
