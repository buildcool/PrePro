"""Drive the built review UI in a real browser (Playwright + Chromium) through the whole flow.

Opt-in: needs node with the `playwright` package and a browser; marked slow. Screenshots land in the tmp dir."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

pytestmark = [pytest.mark.slow, needs_tts, needs_ffmpeg]
HERE = Path(__file__).parent


def _has_playwright() -> bool:
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True)
    return r.returncode == 0


@pytest.mark.skipif(not _has_playwright(), reason="node + playwright not available")
def test_review_ui_end_to_end(shoot_factory, tmp_path):
    src = shoot_factory("travel_vlog", brief=True)
    shoot = tmp_path / "shoot"
    shoot.mkdir()
    # copy without caches/brief so the UI does the whole job (analysis included)
    tar = tmp_path / "s.tar"
    with tarfile.open(tar, "w") as tf:
        for p in src.iterdir():
            if p.name not in (".prepro", "PrePro_exports", "brief.md", ".built"):
                tf.add(p, arcname=p.name)
    with tarfile.open(tar) as tf:
        tf.extractall(shoot, filter="data")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "PREPRO_DATA_DIR": str(tmp_path / "data"), "PREPRO_CONFIG_DIR": str(tmp_path / "config")}
    srv = subprocess.Popen([sys.executable, "-m", "prepro.cli", "ui", "--no-browser", "--port", str(port)], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import urllib.request

        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        (tmp_path / "shots").mkdir()
        flow = (HERE / "flow.js").read_text().replace("http://127.0.0.1:8765", f"http://127.0.0.1:{port}")
        (tmp_path / "flow.js").write_text(flow)
        r = subprocess.run(["node", str(tmp_path / "flow.js"), str(tmp_path), str(shoot)], capture_output=True, text=True, timeout=1800)
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
        assert "ERRORS: []" in r.stdout, r.stdout[-1500:]
        assert "mobile horizontal overflow px: 0" in r.stdout
        assert len(list((tmp_path / "shots").glob("*.png"))) >= 10
    finally:
        srv.terminate()
        srv.wait(timeout=20)
