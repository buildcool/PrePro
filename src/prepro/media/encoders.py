"""Video encoding on the GPU when that is actually faster on this PC, on the CPU (x264) otherwise.

A GPU encoder (NVIDIA NVENC, Intel Quick Sync, AMD AMF) is only a candidate after a real test encode succeeds here:
being compiled into ffmpeg says nothing about the chip or the driver. Faster isn't a given either: on a 24-core
CPU, x264 beat NVENC on our renders, while Quick Sync was twice as fast as x264 on 1080p finals. So "auto" times a
short render-like encode once per PC and size (preview / final) with every candidate, keeps the result in the data
folder, and picks a GPU only when it is clearly faster (≥ 15 %), because x264 makes the smallest files. A GPU that
still fails during a render (driver hiccup, all encode sessions busy) has that piece redone on the CPU and is left
alone for the rest of the run, so a render never fails because the GPU did.

Settings.render.encoder or ``PREPRO_ENCODER``: ``auto`` (default) | ``cpu`` | ``nvenc`` | ``qsv`` | ``amf``.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from functools import cache

from .ffmpeg import FFmpegError, ffmpeg_bin, run_ffmpeg

GPU_ORDER = ("nvenc", "qsv", "amf")
CODEC = {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf", "cpu": "libx264"}
LABEL = {"nvenc": "NVIDIA GPU (NVENC)", "qsv": "Intel GPU (Quick Sync)", "amf": "AMD GPU (AMF)", "cpu": "CPU (x264)"}
# quality offsets that match x264's -crf, measured by SSIM on a 1080×1920 cut (QA log, v0.8): Quick Sync's
# global_quality tracks CRF; NVENC's constant-quality scale needs ~6 more for the same picture. AMF is untested.
Q_OFFSET = {"nvenc": 6, "qsv": 1, "amf": 2}
MIN_GAIN = 0.15                       # a GPU must be this much faster than x264 to be used
BENCH_VERSION = 2                     # 2: grainy test footage (v1's clean pattern favoured x264 unfairly)
_LOCK = threading.Lock()
_FAILED: dict[str, str] = {}          # GPU encoders that failed mid-render in this process → why


@dataclass(frozen=True)
class Encoder:
    name: str                          # nvenc | qsv | amf | cpu

    @property
    def gpu(self) -> bool:
        return self.name != "cpu"

    @property
    def label(self) -> str:
        return LABEL[self.name]

    def args(self, crf: int, preset: str) -> list[str]:
        """ffmpeg output options for H.264 4:2:0 at about x264's ``-crf`` quality. ``preset`` is x264's name
        (veryfast … slow); GPU encoders get their own fast/quality equivalent."""
        fast = preset in ("ultrafast", "superfast", "veryfast", "faster", "fast")
        q = str(crf + Q_OFFSET.get(self.name, 0))
        if self.name == "nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p2" if fast else "p5", "-rc", "vbr", "-cq", q, "-b:v", "0",
                    "-spatial-aq", "1", "-profile:v", "high", "-pix_fmt", "yuv420p"]
        if self.name == "qsv":
            return ["-c:v", "h264_qsv", "-preset", "veryfast" if fast else "slower", "-global_quality", q, "-look_ahead", "0",
                    "-profile:v", "high", "-pix_fmt", "nv12"]
        if self.name == "amf":
            return ["-c:v", "h264_amf", "-quality", "speed" if fast else "quality", "-rc", "cqp", "-qp_i", q, "-qp_p", q, "-qp_b", q,
                    "-profile:v", "high", "-pix_fmt", "yuv420p"]
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]


CPU = Encoder("cpu")


@cache
def works(name: str) -> bool:
    """A real test encode on this PC (cached per process). The CPU always works."""
    if name == "cpu":
        return True
    try:
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
               "-frames:v", "30", *Encoder(name).args(28, "veryfast"), "-f", "null", "-"]
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def preference() -> str:
    pref = os.environ.get("PREPRO_ENCODER")
    if not pref:
        try:
            from ..config import Settings

            pref = Settings.load().render.encoder
        except Exception:
            pref = "auto"
    return (pref or "auto").lower()


def available() -> list[str]:
    """GPU encoders that work on this PC (for `prepro doctor` and the UI)."""
    return [n for n in GPU_ORDER if works(n)]


def _bucket(short: int) -> str:
    return "final" if short > 720 else "preview"


def _bench_one(name: str, short: int) -> float | None:
    """Seconds for 4 s of a vertical frame with sensor-like grain through a scale/crop/sharpen chain + the encoder,
    process start included — close to how a render piece is made. The grain matters: a clean test pattern is so easy
    to compress that x264 looks fastest, while on real footage it was 4–12× slower than the GPU encoders at 1080p."""
    w = short - short % 2
    h = int(short * 16 / 9) // 2 * 2
    crf, preset = (30, "veryfast") if _bucket(short) == "preview" else (19, "medium")
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30",
           "-t", "4", "-vf", f"scale={w + 64}:-2:flags=bicubic,crop={w}:{h},noise=alls=12:allf=t,unsharp=5:5:0.6",
           *Encoder(name).args(crf, preset), "-f", "null", "-"]
    t0 = time.perf_counter()
    try:
        ok = subprocess.run(cmd, capture_output=True, timeout=120).returncode == 0
    except Exception:
        ok = False
    return round(time.perf_counter() - t0, 3) if ok else None


def _bench_file():
    from ..config import data_dir

    return data_dir() / "encoders.json"


def benchmark(short: int, *, refresh: bool = False) -> dict[str, float]:
    """Seconds per candidate for this size bucket, measured once per PC (and ffmpeg) and remembered."""
    key = f"v{BENCH_VERSION}|{ffmpeg_bin()}|{_bucket(short)}"
    path = _bench_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    if not refresh and key in data:
        return data[key]
    size = 1080 if _bucket(short) == "final" else 540
    res = {n: t for n in ("cpu", *available()) if (t := _bench_one(n, size)) is not None}
    data[key] = res
    try:
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass
    return res


def choose(short: int = 1080) -> Encoder:
    """The encoder for a render whose short side is ``short`` pixels."""
    pref = preference()
    with _LOCK:
        failed = set(_FAILED)
    if pref == "cpu":
        return CPU
    if pref in CODEC:                                   # a specific GPU was asked for: use it if it works here
        return Encoder(pref) if pref not in failed and works(pref) else CPU
    times = {n: t for n, t in benchmark(short).items() if n not in failed}
    cpu = times.get("cpu")
    gpus = sorted((t, n) for n, t in times.items() if n != "cpu")
    if gpus and (cpu is None or gpus[0][0] <= cpu * (1 - MIN_GAIN)):
        return Encoder(gpus[0][1])
    return CPU


def why(short: int = 1080) -> str:
    """The choice in words, with the measured times."""
    pick = choose(short)
    pref = preference()
    if pref != "auto":
        return f"{pick.label} (setting: {pref})"
    times = benchmark(short)
    shown = ", ".join(f"{LABEL[n]} {t:.1f} s" for n, t in sorted(times.items(), key=lambda kv: kv[1]))
    return f"{pick.label} — measured on this PC: {shown}" if shown else pick.label


def failed_reason(name: str) -> str | None:
    with _LOCK:
        return _FAILED.get(name)


def encode(build, *, prefer: Encoder | None = None, timeout: float | None = None) -> Encoder:
    """Run ``run_ffmpeg(build(encoder))`` with ``prefer`` (or the general choice); if a GPU encoder fails, redo it on
    the CPU and stop using that GPU for this run. Returns the encoder that produced the file."""
    enc = prefer or choose()
    with _LOCK:
        if enc.gpu and enc.name in _FAILED:
            enc = CPU
    try:
        run_ffmpeg(build(enc), timeout=timeout)
        return enc
    except FFmpegError as e:
        if not enc.gpu:
            raise
        with _LOCK:
            _FAILED.setdefault(enc.name, str(e).splitlines()[0][:200])
        run_ffmpeg(build(CPU), timeout=timeout)
        return CPU
