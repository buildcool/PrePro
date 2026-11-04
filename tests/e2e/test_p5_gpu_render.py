"""The same cut rendered on the CPU and on every GPU encoder that works on this PC: each meets the delivery specs and
the GPU picture matches the CPU one (SSIM). On a PC without a usable GPU only the CPU render runs."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

from prepro.engine import analysis, build
from prepro.export.render import render
from prepro.media import encoders as E
from prepro.media.ffmpeg import ffmpeg_bin
from prepro.project import Project

pytestmark = [pytest.mark.slow, needs_tts, needs_ffmpeg]


@pytest.fixture(scope="module")
def cut(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    return root, build(root, render=False), analysis(root)


def _probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,pix_fmt:format=duration",
                          "-of", "json", str(p)], capture_output=True, text=True).stdout
    return json.loads(out)


def _ssim(a, b) -> float:
    err = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi", "[0:v][1:v]ssim", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    return float(re.search(r"All:([0-9.]+)", err).group(1))


def test_gpu_and_cpu_renders_match(cut, tmp_path, monkeypatch):
    root, res, pa = cut
    work = Project(root).cache / "renders" / "work_preview"
    results = {}
    for name in ["cpu", *E.available()]:
        shutil.rmtree(work, ignore_errors=True)                       # no reuse: each encoder renders every piece
        monkeypatch.setenv("PREPRO_ENCODER", name)
        t0 = time.time()
        r = render(res.timeline, pa, tmp_path / f"{name}.mp4", storyboard=False, project_root=root)
        results[name] = (r, time.time() - t0)
        assert r.encoder == name and E.LABEL[name] in r.encoder_note
        info = _probe(r.video)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p" and (v["width"], v["height"]) == (540, 960), (name, v)
        assert abs(float(info["format"]["duration"]) - res.timeline.duration) < 0.4
        assert r.lufs is not None and abs(r.lufs + 14) <= 1.0
    for name, (r, secs) in results.items():
        line = f"{E.LABEL[name]}: {secs:.1f} s"
        if name != "cpu":
            s = _ssim(results["cpu"][0].video, r.video)
            line += f", SSIM vs CPU {s:.3f}"
            assert s >= 0.93, line                                    # the same picture, not a different edit
        print(line)
