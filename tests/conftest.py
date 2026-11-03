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
FIXTURE_VERSION = "3"


def have(exe: str) -> bool:
    return shutil.which(exe) is not None


needs_tts = pytest.mark.skipif(not have("espeak-ng") and not have("espeak"), reason="espeak-ng not installed")
needs_ffmpeg = pytest.mark.skipif(not have("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(scope="session")
def shoot_factory():
    def make(kind: str, *, brief: bool = False, sidecars: bool = True, quick: bool = True) -> Path:
        key = f"v{FIXTURE_VERSION}-{'sc' if sidecars else 'nosc'}-{'q' if quick else 'full'}"
        out = CACHE / key
        root = out / (kind + ("_brief" if brief else ""))
        marker = root / ".built"
        if not marker.exists():
            if root.exists():
                shutil.rmtree(root)
            md = realmedia.cache_dir() if realmedia.available() else None
            shoots.build(kind, out, media_dir=md, with_brief=brief, sidecars=sidecars, quick=quick)
            marker.write_text("ok")
        return root

    return make


def truth(root: Path) -> dict:
    return json.loads((root / ".groundtruth.json").read_text(encoding="utf-8"))
