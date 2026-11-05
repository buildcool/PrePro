"""The engine starts the way the desktop app starts it: output piped (not a console) in a legacy code page.

v0.8.0's installed app died on its first line, "PrePro 0.8.0 → http://…": Windows encodes a piped stdout in the ANSI
code page (cp1252), which has no "→", and the engine exited before the window opened. Tests never saw it because
pytest, CI shells and terminals are UTF-8. Here every command the desktop app or a user runs first must survive a
cp1252 pipe."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(PYTHONIOENCODING="cp1252", PYTHONUTF8="0", PREPRO_DESKTOP="1", PYTHONUNBUFFERED="1")
    return env


def _cli(*args: str) -> list[str]:
    return [sys.executable, "-c", "from prepro.cli import app; app()", *args]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_ui_starts_with_a_cp1252_pipe(tmp_path):
    env = _env()
    env.update(PREPRO_DATA_DIR=str(tmp_path / "data"), PREPRO_CONFIG_DIR=str(tmp_path / "config"))
    port = _free_port()
    p = subprocess.Popen(_cli("ui", "--no-browser", "--port", str(port)), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        up = False
        deadline = time.time() + 60
        while time.time() < deadline and p.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    up = True
                    break
            except OSError:
                time.sleep(0.3)
        if not up:
            out = p.stdout.read().decode("utf-8", "replace") if p.poll() is not None else ""
            pytest.fail(f"engine did not start (exit {p.poll()}):\n{out[-2000:]}")
    finally:
        p.kill()
        p.wait(timeout=20)


@pytest.mark.parametrize("args", [("version",), ("--help",)])
def test_first_commands_survive_a_cp1252_pipe(args):
    r = subprocess.run(_cli(*args), env=_env(), capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
