"""Locate and run ffmpeg / ffprobe.

Lookup order: ``PREPRO_FFMPEG`` / ``PREPRO_FFPROBE`` env vars → binaries bundled next to the
frozen app (``<app>/bin``) → ``PATH``. Every call goes through :func:`run_ffmpeg` so errors carry the
tail of ffmpeg's stderr, which is what you need to debug a filtergraph.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import cache, lru_cache
from pathlib import Path


class FFmpegError(RuntimeError):
    """ffmpeg/ffprobe failed or is missing."""


def _bundled(name: str) -> str | None:
    exe = name + (".exe" if os.name == "nt" else "")
    roots = []
    if getattr(sys, "frozen", False):  # PyInstaller
        roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
        roots.append(Path(sys.executable).parent)
    roots.append(Path(__file__).resolve().parents[3] / "bin")
    for root in roots:
        cand = root / "bin" / exe if (root / "bin" / exe).exists() else root / exe
        if cand.exists():
            return str(cand)
    return None


@cache
def find_binary(name: str) -> str:
    env = os.environ.get(f"PREPRO_{name.upper()}")
    for cand in (env, _bundled(name), shutil.which(name)):
        if cand and Path(cand).exists():
            return cand
    raise FFmpegError(
        f"{name} not found. Install ffmpeg (https://ffmpeg.org/download.html) or set PREPRO_{name.upper()}."
    )


def ffmpeg_bin() -> str:
    return find_binary("ffmpeg")


def ffprobe_bin() -> str:
    return find_binary("ffprobe")


def run_ffmpeg(args: list[str], *, timeout: float | None = None, capture_stdout: bool = False) -> subprocess.CompletedProcess:
    """Run ffmpeg with sane defaults; raise :class:`FFmpegError` with stderr tail on failure."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise FFmpegError(f"ffmpeg timed out after {timeout}s: {' '.join(cmd[:12])}…") from e
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-2000:]
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}): {tail}\ncmd: {' '.join(cmd)}")
    return proc


def run_ffmpeg_stderr(args: list[str], *, timeout: float | None = None) -> str:
    """Run ffmpeg for analysis filters that print to stderr (ebur128, silencedetect…); return stderr."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout, check=False)
    err = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}): {err[-2000:]}")
    return err


def ffprobe_json(path: str | Path, *, timeout: float = 60) -> dict:
    cmd = [
        ffprobe_bin(), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path}: {proc.stderr.decode('utf-8', 'replace')[-800:]}")
    return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")


def has_encoder(name: str) -> bool:
    return name in _encoders()


@lru_cache(maxsize=1)
def _encoders() -> frozenset[str]:
    try:
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-encoders"], capture_output=True, timeout=30).stdout
    except Exception:  # pragma: no cover - environment specific
        return frozenset()
    names = set()
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6:
            names.add(parts[1])
    return frozenset(names)


@lru_cache(maxsize=1)
def filters() -> frozenset[str]:
    try:
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, timeout=30).stdout
    except Exception:  # pragma: no cover
        return frozenset()
    names = set()
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) in (2, 3):
            names.add(parts[1])
    return frozenset(names)
