"""Desktop app smoke test: Electron starts the frozen engine, the page is local, sandboxed, and has the bridge.

Opt-in (slow): needs dist/prepro-engine (python scripts/build_engine.py), desktop/node_modules, xvfb-run and
node with playwright."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow]
ROOT = Path(__file__).resolve().parents[2]
ELECTRON = ROOT / "desktop" / "node_modules" / "electron" / "dist" / "electron"
ENGINE = ROOT / "dist" / "prepro-engine" / "prepro-engine"


def _ready() -> bool:
    if not (ELECTRON.exists() and ENGINE.exists() and shutil.which("xvfb-run") and shutil.which("node")):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _ready(), reason="frozen engine / electron / xvfb / playwright not available")
def test_desktop_app_starts_engine_and_stays_sandboxed(tmp_path):
    shoot = tmp_path / "shoot"
    (shoot / "footage").mkdir(parents=True)
    r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24", "node", str(Path(__file__).parent / "electron_smoke.js"),
                        str(ELECTRON), str(ROOT / "desktop"), str(tmp_path), str(shoot)], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res == {"bridge": True, "nodeInPage": False, "local": True}
    # the engine is gone after the window closes
    left = subprocess.run(["pgrep", "-f", str(ENGINE)], capture_output=True, text=True).stdout.strip()
    assert not left, left
