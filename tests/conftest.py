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
FIXTURE_VERSION = "5"     # 4: TTS via a UTF-8 file (Hindi was noise on Windows); 5: gaming facecam top-right, bundled font


def have(exe: str) -> bool:
    return shutil.which(exe) is not None


needs_tts = pytest.mark.skipif(not have("espeak-ng") and not have("espeak"), reason="espeak-ng not installed")
needs_ffmpeg = pytest.mark.skipif(not have("ffmpeg"), reason="ffmpeg not installed")


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
