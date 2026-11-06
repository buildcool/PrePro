"""Shared fixtures: synthetic shoots are built once per machine and cached between test runs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from prepro.fixtures import realmedia, shoots

CACHE = Path(os.environ.get("PREPRO_TEST_SHOOTS") or Path(tempfile.gettempdir()) / "prepro-test-shoots")
FIXTURE_VERSION = "6"     # 4: TTS via a UTF-8 file (Hindi was noise on Windows); 5: gaming facecam top-right, bundled font;
                          # 6: a drawn streamer in the gaming facecam, and a planted death (fail) in the match


def have(exe: str) -> bool:
    return shutil.which(exe) is not None


needs_tts = pytest.mark.skipif(not have("espeak-ng") and not have("espeak"), reason="espeak-ng not installed")
needs_ffmpeg = pytest.mark.skipif(not have("ffmpeg"), reason="ffmpeg not installed")


def pytest_runtest_logreport(report):
    """On GitHub Actions, every failure is also an annotation: annotations can be read through the public API without
    signing in (the logs can't), so a red CI run says what broke."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    import sys

    text = str(report.longrepr)
    tail = text[-1800:]
    esc = lambda s: s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")   # noqa: E731
    title = esc(f"{report.nodeid} ({report.when})").replace(":", "%3A").replace(",", "%2C")
    sys.__stdout__.write(f"\n::error title={title}::{esc(tail)}\n")
    sys.__stdout__.flush()


@pytest.fixture(scope="session")
def shoot_factory():
    def make(kind: str, *, brief: bool = False, sidecars: bool = True, quick: bool = True) -> Path:
        # shoots built with downloaded real media (faces…) differ from fully drawn ones, so they are cached apart:
        # fetching test media later must not leave the drawn shoots in place under the same key
        md = realmedia.cache_dir() if realmedia.available() else None
        key = f"v{FIXTURE_VERSION}-{'sc' if sidecars else 'nosc'}-{'q' if quick else 'full'}-{'rm' if md else 'syn'}"
        out = CACHE / key
        root = out / (kind + ("_brief" if brief else ""))
        marker = root / ".built"
        if not marker.exists():
            if root.exists():
                shutil.rmtree(root)
            shoots.build(kind, out, media_dir=md, with_brief=brief, sidecars=sidecars, quick=quick)
            marker.write_text("ok")
        return root

    return make


def truth(root: Path) -> dict:
    return json.loads((root / ".groundtruth.json").read_text(encoding="utf-8"))
