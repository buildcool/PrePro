"""Freeze the engine into dist/prepro-engine/ (PyInstaller, one folder) for the desktop app.

    python scripts/build_engine.py            # then: dist/prepro-engine/prepro-engine doctor

ffmpeg/ffprobe are not frozen: the desktop build copies them into resources/engine/bin when available
(Windows CI), otherwise the system ones are used (Linux packages depend on ffmpeg).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEP = ";" if os.name == "nt" else ":"

COLLECT_DATA = ["prepro", "librosa", "faster_whisper", "pocketsphinx", "reverse_geocoder", "opentimelineio",
                "otio_fcp_adapter", "otio_kdenlive_adapter", "otio_fcpx_xml_adapter"]
COLLECT_SUBMODULES = ["prepro", "uvicorn", "keyring", "opentimelineio", "otio_fcp_adapter", "otio_kdenlive_adapter", "otio_fcpx_xml_adapter",
                      "librosa", "anthropic", "openai", "google.genai"]
COPY_METADATA = ["prepro", "opentimelineio", "otio-fcp-adapter", "otio-fcpx-xml-adapter", "otio-kdenlive-adapter", "librosa", "numba",
                 "faster-whisper", "keyring", "pooch", "fastapi", "uvicorn", "pydantic", "anthropic", "openai", "google-genai"]
EXCLUDE = ["tkinter", "matplotlib", "IPython", "pytest", "torch", "tensorflow", "scenedetect", "pandas"]


def main() -> int:
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--name", "prepro-engine",
            # stand-ins shadow heavy packages we never call (see scripts/frozen_stubs/*/__init__.py)
            "--paths", str(ROOT / "scripts" / "frozen_stubs"),
            "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"), "--specpath", str(ROOT / "build"),
            "--add-data", f"{ROOT / 'assets'}{SEP}assets"]
    # OTIO loads plugin adapters from .py files by path (plugin_manifest.json "filepath"), so ship them as source
    import importlib.util

    for pkg in ("otio_fcp_adapter", "otio_kdenlive_adapter", "otio_fcpx_xml_adapter"):
        spec = importlib.util.find_spec(pkg)
        if spec and spec.submodule_search_locations:
            args += ["--add-data", f"{list(spec.submodule_search_locations)[0]}{SEP}{pkg}"]
    if sys.platform.startswith("linux"):
        args.append("--strip")           # debug symbols are most of llvmlite/ctranslate2/av on Linux
    for m in COLLECT_DATA:
        args += ["--collect-data", m]
    for m in COLLECT_SUBMODULES:
        args += ["--collect-submodules", m]
    for m in COPY_METADATA:
        try:
            from importlib.metadata import distribution

            distribution(m)
            args += ["--copy-metadata", m]
        except Exception:
            print(f"(skip metadata for {m}: not installed)")
    for m in EXCLUDE:
        args += ["--exclude-module", m]
    args.append(str(ROOT / "scripts" / "engine_entry.py"))
    print(" ".join(args))
    return subprocess.call(args, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
