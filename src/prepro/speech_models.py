"""Speech-recognition models (faster-whisper): what's on this computer, and downloading one with real progress.

Without a downloaded model PrePro falls back to the small offline PocketSphinx recogniser (English only, rough
words). Whisper is far better — and multilingual — but its model is a one-time download from huggingface.co."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

# approximate download sizes (MB) — shown before downloading
SIZES_MB = {"tiny": 75, "base": 145, "small": 484, "medium": 1530, "large-v3-turbo": 1620}
NOTES = {
    "tiny": "fastest, rough — old laptops",
    "base": "fast, OK for clear speech",
    "small": "recommended on most computers",
    "medium": "better accents & Hindi, slower on CPU",
    "large-v3-turbo": "best quality — for an NVIDIA GPU",
}


def repo_for(name: str) -> str:
    try:
        from faster_whisper.utils import _MODELS

        return _MODELS.get(name, name if "/" in name else f"Systran/faster-whisper-{name}")
    except Exception:
        return name if "/" in name else f"Systran/faster-whisper-{name}"


def cached(name: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(repo_for(name), "model.bin"), str)
    except Exception:
        return False


def installed() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        return False


def status(current: str | None = None) -> list[dict]:
    return [{"name": n, "size_mb": mb, "note": NOTES.get(n, ""), "cached": cached(n), "current": n == current} for n, mb in SIZES_MB.items()]


def _repo_dir(repo: str) -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE) / f"models--{repo.replace('/', '--')}"


def _dir_mb(p: Path) -> float:
    if not p.exists():
        return 0.0
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            fp = Path(root) / f
            if not fp.is_symlink():
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    return total / 1e6


def download(name: str, progress=None) -> str:
    """Download a Whisper model into the Hugging Face cache, reporting MB as it arrives. Returns the model folder."""
    if not installed():
        raise RuntimeError("speech recognition isn't installed (pip install prepro[asr])")
    from faster_whisper.utils import download_model

    repo = repo_for(name)
    total = float(SIZES_MB.get(name, 500))
    folder = _repo_dir(repo)
    done = threading.Event()

    def watch():
        while not done.wait(0.5):
            if progress:
                mb = _dir_mb(folder)
                progress("model", min(mb, total * 0.99), total, f"Downloading the {name} speech model · {mb:.0f} / ~{total:.0f} MB")

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        path = download_model(name)
    finally:
        done.set()
        t.join(timeout=2)
    if progress:
        progress("model", total, total, f"{name} speech model ready")
    return str(path)


def wait_for(name: str, timeout: float = 5.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cached(name):
            return True
        time.sleep(0.2)
    return cached(name)
