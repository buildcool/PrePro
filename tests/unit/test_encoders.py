"""Video encoding uses a GPU when it really encodes on this PC *and* is measurably faster than the CPU; the CPU
otherwise — and a GPU that fails mid-render never fails the render."""

from __future__ import annotations

import os

import pytest

from prepro.media import encoders as E
from prepro.media.ffmpeg import FFmpegError


@pytest.fixture
def fake_pc(monkeypatch):
    """A PC where only Quick Sync works (NVENC compiled into ffmpeg, but no NVIDIA chip)."""
    monkeypatch.setattr(E, "_FAILED", {})
    monkeypatch.setattr(E, "works", lambda name: name in ("cpu", "qsv"))
    monkeypatch.delenv("PREPRO_ENCODER", raising=False)
    monkeypatch.setattr(E, "preference", lambda: os.environ.get("PREPRO_ENCODER", "auto"))
    times = {"cpu": 2.0, "qsv": 1.0}
    monkeypatch.setattr(E, "benchmark", lambda short, refresh=False: dict(times))
    return times


def test_auto_picks_a_gpu_only_when_it_is_clearly_faster(fake_pc, monkeypatch):
    assert E.choose(1080) == E.Encoder("qsv") and E.choose(1080).gpu
    fake_pc.update({"qsv": 1.9})                                    # barely faster: x264 makes smaller files → CPU
    assert E.choose(1080) == E.CPU
    fake_pc.pop("qsv")                                              # no GPU at all (CI, old laptops)
    assert E.choose(1080) == E.CPU
    assert "measured on this PC" in E.why(1080)


def test_a_setting_overrides_the_measurement(fake_pc, monkeypatch):
    monkeypatch.setenv("PREPRO_ENCODER", "cpu")
    assert E.choose() == E.CPU
    monkeypatch.setenv("PREPRO_ENCODER", "qsv")
    assert E.choose() == E.Encoder("qsv")
    monkeypatch.setenv("PREPRO_ENCODER", "nvenc")                   # asked for a GPU that doesn't work here → CPU
    assert E.choose() == E.CPU


def test_a_gpu_failure_mid_render_finishes_on_the_cpu(fake_pc, monkeypatch):
    calls = []

    def run(args, timeout=None):
        calls.append(args[args.index("-c:v") + 1])
        if args[args.index("-c:v") + 1] != "libx264":
            raise FFmpegError("ffmpeg failed (1): [h264_qsv @ 0x1] Error initializing an internal MFX session")

    monkeypatch.setattr(E, "run_ffmpeg", run)
    qsv = E.choose(1080)
    used = E.encode(lambda e: ["-i", "in.mp4", *e.args(28, "veryfast"), "out.mp4"], prefer=qsv)
    assert used == E.CPU and calls == ["h264_qsv", "libx264"]
    assert "MFX session" in E.failed_reason("qsv")
    assert E.choose(1080) == E.CPU                                  # the broken GPU is left alone for the rest of the run
    calls.clear()
    E.encode(lambda e: ["-i", "in.mp4", *e.args(28, "veryfast"), "out.mp4"], prefer=qsv)
    assert calls == ["libx264"]


def test_every_encoder_writes_4_2_0_h264_at_matched_quality():
    for name in ("nvenc", "qsv", "amf", "cpu"):
        a = E.Encoder(name).args(19, "medium")
        assert a[a.index("-c:v") + 1].startswith(("h264_", "libx264"))
        assert a[a.index("-pix_fmt") + 1] in ("yuv420p", "nv12")    # 4:2:0 8-bit: plays on phones, Instagram accepts it
    nv = E.Encoder("nvenc").args(19, "medium")
    assert nv[nv.index("-cq") + 1] == "25"                         # NVENC's scale needs +6 for x264-like quality
