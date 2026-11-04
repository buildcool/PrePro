"""User settings, app paths, secrets (OS keychain) and downloadable runtime models."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Literal

from platformdirs import user_cache_dir, user_config_dir, user_data_dir
from pydantic import BaseModel, Field

APP = "prepro"
PrivacyLevel = Literal["local", "text", "thumbs"]


def config_dir() -> Path:
    d = Path(os.environ.get("PREPRO_CONFIG_DIR") or user_config_dir(APP))
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_dir() -> Path:
    d = Path(os.environ.get("PREPRO_DATA_DIR") or user_data_dir(APP))
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = Path(os.environ.get("PREPRO_MODELS_DIR") or Path(user_cache_dir(APP)) / "models")
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir() -> Path:
    """Bundled fonts/SFX/LUTs: next to the package (dev) or inside the frozen app."""
    import sys

    cands = []
    if getattr(sys, "frozen", False):
        cands.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets")
    cands.append(Path(__file__).resolve().parents[2] / "assets")
    cands.append(Path(__file__).resolve().parent / "assets")
    for c in cands:
        if c.exists():
            return c
    return cands[-1]


class ASRSettings(BaseModel):
    backend: Literal["auto", "faster-whisper", "pocketsphinx", "sidecar", "none"] = "auto"
    whisper_model: str = "small"        # tiny|base|small|medium|large-v3-turbo
    device: Literal["auto", "cpu", "cuda"] = "auto"
    compute_type: str = "auto"
    language: str | None = None         # None = auto-detect
    verbatim: bool = True               # bias Whisper to keep "um/uh" so fillers can be cut


class RenderSettings(BaseModel):
    preview_height: int = 540
    final_height: int = 1080
    crf_preview: int = 30
    crf_final: int = 20
    preset_preview: str = "veryfast"
    preset_final: str = "medium"
    target_lufs: float = -14.0
    true_peak: float = -1.0
    encoder: Literal["auto", "cpu", "nvenc", "qsv", "amf"] = "auto"   # auto = the GPU if it encodes here, else the CPU


class BrainRouting(BaseModel):
    """Which connector handles which pass ("basic" = rules only, no AI)."""

    vision: str = "basic"
    director: str = "basic"
    story: str = "basic"
    polish: str = "basic"
    critic: str = "basic"
    brief: str = "basic"
    revise: str = "basic"


class ConnectorConfig(BaseModel):
    kind: str                            # claude_code|codex|anthropic|openai|gemini|xai|openrouter|ollama
    model: str | None = None
    base_url: str | None = None
    effort: str | None = None
    max_usd_per_project: float = 2.0
    extra: dict = Field(default_factory=dict)


class Settings(BaseModel):
    asr: ASRSettings = Field(default_factory=ASRSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    routing: BrainRouting = Field(default_factory=BrainRouting)
    connectors: dict[str, ConnectorConfig] = Field(default_factory=dict)
    privacy: PrivacyLevel = "thumbs"
    blur_faces_in_thumbs: bool = False
    monthly_cap_usd: float = 10.0
    meme_flavour: str = "global"
    language_ui: str = "en"

    @classmethod
    def load(cls) -> Settings:
        p = config_dir() / "settings.json"
        if p.exists():
            try:
                return cls.model_validate_json(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return cls()

    def save(self) -> Path:
        p = config_dir() / "settings.json"
        p.write_text(self.model_dump_json(indent=1), encoding="utf-8")
        return p


# ---------------------------------------------------------------- secrets
def set_secret(name: str, value: str) -> None:
    try:
        import keyring

        keyring.set_password(APP, name, value)
        return
    except Exception:
        pass
    p = config_dir() / ".secrets.json"
    data = json.loads(p.read_text()) if p.exists() else {}
    data[name] = value
    p.write_text(json.dumps(data))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def get_secret(name: str) -> str | None:
    env = os.environ.get(name.upper())
    if env:
        return env
    try:
        import keyring

        v = keyring.get_password(APP, name)
        if v:
            return v
    except Exception:
        pass
    p = config_dir() / ".secrets.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get(name)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- runtime models
MODELS = {
    "face_res10": [
        ("deploy.prototxt", "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/dnn/face_detector/deploy.prototxt",
         "dcd661dc48fc9de0a341db1f666a2164ea63a67265c7f779bc12d6b3f2fa67e9"),
        ("res10_300x300_ssd_iter_140000.caffemodel",
         "https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel",
         "2a56a11a57a4a295956b0660b4a3d76bbdca2206c4961cea8efe7d95c7cb2f2d"),
    ],
}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def ensure_model(name: str, *, download: bool = True) -> list[Path] | None:
    """Return local paths for a model's files, downloading (and verifying SHA-256) if needed."""
    files = MODELS[name]
    out = []
    for fname, url, sha in files:
        p = models_dir() / fname
        if not p.exists() or _sha256(p) != sha:
            if not download:
                return None
            tmp = p.with_suffix(p.suffix + ".part")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "prepro/0.1"})
                with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:
                    while chunk := r.read(1 << 16):
                        f.write(chunk)
            except Exception:
                tmp.unlink(missing_ok=True)
                return None
            if _sha256(tmp) != sha:
                tmp.unlink(missing_ok=True)
                return None
            tmp.replace(p)
        out.append(p)
    return out
