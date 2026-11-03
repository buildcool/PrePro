"""Shoot folder scanning, stable asset IDs, cache layout and JSON persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".3gp", ".mxf", ".ts", ".wmv"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".gif"}
LUT_EXT = {".cube"}
SIDECAR_EXT = {".srt", ".vtt", ".transcript.json"}
BRIEF_NAMES = {"brief", "prepro-brief", "_brief"}
NOTES_NAMES = {"notes.yaml", "notes.yml", "notes.json"}

TAG_RE = re.compile(r"^((?:HOOK|MUST|SKIP|BEST|FUNNY|SPONSOR)_)+", re.IGNORECASE)

# folder name → kind hint
FOLDER_HINTS = {
    "aroll": "aroll", "a-roll": "aroll", "talking": "aroll", "talk": "aroll",
    "broll": "broll", "b-roll": "broll", "cutaways": "broll",
    "footage": None, "clips": None, "video": None, "videos": None, "raw": None,
    "music": "music", "songs": "music", "bgm": "music", "tracks": "music",
    "sfx": "sfx", "sounds": "sfx", "soundeffects": "sfx", "sound-effects": "sfx",
    "memes": "meme", "meme": "meme", "gifs": "meme", "stickers": "meme", "reactions": "meme",
    "vo": "voiceover", "voiceover": "voiceover", "voice-over": "voiceover", "narration": "voiceover",
    "images": "image", "photos": "image", "pics": "image",
    "screen": "screen", "gameplay": "screen", "screenrec": "screen",
    "luts": "lut", "lut": "lut",
}

T = TypeVar("T", bound=BaseModel)


def fast_hash(path: Path, block: int = 1 << 20) -> str:
    """Hash size + first/last MiB: fast on multi-GB footage, stable across copies."""
    h = hashlib.sha1()
    size = path.stat().st_size
    h.update(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(block))
        if size > 2 * block:
            f.seek(-block, os.SEEK_END)
            h.update(f.read(block))
    return h.hexdigest()[:16]


def filename_tags(name: str) -> tuple[list[str], str]:
    """``HOOK_MUST_IMG_2041.mov`` → (["hook", "must"], "IMG_2041.mov")."""
    m = TAG_RE.match(name)
    if not m:
        return [], name
    tags = [t.lower() for t in m.group(0).strip("_").split("_") if t]
    return tags, name[m.end():]


@dataclass
class ScannedFile:
    path: Path            # absolute
    rel: str              # relative, forward slashes
    media: str            # video|audio|image|lut
    hint: str | None      # kind hint from folder name
    tags: list[str]


@dataclass
class ScanResult:
    files: list[ScannedFile]
    brief_files: list[Path]
    notes_files: list[Path]
    sidecars: dict[str, Path]     # media rel path (without ext) → transcript sidecar


class Project:
    """A shoot folder plus its ``.prepro`` cache."""

    def __init__(self, root: str | Path, cache_dir: str | Path | None = None):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"Shoot folder not found: {self.root}")
        self.cache = Path(cache_dir).resolve() if cache_dir else self.root / ".prepro"
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            probe = self.cache / ".write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError:
            from platformdirs import user_cache_dir

            self.cache = Path(user_cache_dir("prepro")) / "projects" / hashlib.sha1(str(self.root).encode()).hexdigest()[:12]
            self.cache.mkdir(parents=True, exist_ok=True)
        for sub in ("proxies", "audio", "frames", "analysis", "renders", "exports", "logs", "sent", "timelines", "qa"):
            (self.cache / sub).mkdir(exist_ok=True)

    # ---------- paths ----------
    def path(self, rel: str) -> Path:
        return (self.root / rel).resolve()

    def sub(self, name: str) -> Path:
        p = self.cache / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---------- scanning ----------
    def scan(self) -> ScanResult:
        files: list[ScannedFile] = []
        brief_files: list[Path] = []
        notes_files: list[Path] = []
        sidecars: dict[str, Path] = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__"))
            dpath = Path(dirpath)
            rel_dir = dpath.relative_to(self.root)
            hint = None
            for part in reversed(rel_dir.parts):
                key = part.lower().replace(" ", "").replace("_", "-")
                key2 = key.replace("-", "")
                if key in FOLDER_HINTS or key2 in FOLDER_HINTS:
                    hint = FOLDER_HINTS.get(key, FOLDER_HINTS.get(key2))
                    if hint:
                        break
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                p = dpath / fn
                low = fn.lower()
                stem = low.rsplit(".", 1)[0]
                ext = "." + low.rsplit(".", 1)[-1] if "." in low else ""
                rel = p.relative_to(self.root).as_posix()
                if stem in BRIEF_NAMES and ext in {".md", ".txt", ".yaml", ".yml", ".json"} | AUDIO_EXT:
                    brief_files.append(p)
                    continue
                if low in NOTES_NAMES:
                    notes_files.append(p)
                    continue
                if low.endswith(".transcript.json") or ext in {".srt", ".vtt"}:
                    base = rel[: -len(".transcript.json")] if low.endswith(".transcript.json") else rel.rsplit(".", 1)[0]
                    sidecars[base] = p
                    continue
                media = (
                    "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT
                    else "image" if ext in IMAGE_EXT else "lut" if ext in LUT_EXT else None
                )
                if media is None:
                    continue
                tags, _ = filename_tags(fn)
                files.append(ScannedFile(path=p, rel=rel, media=media, hint=hint, tags=tags))
        return ScanResult(files=files, brief_files=brief_files, notes_files=notes_files, sidecars=sidecars)

    # ---------- persistence ----------
    def save_model(self, name: str, model: BaseModel) -> Path:
        p = self.cache / name
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(model.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(p)
        return p

    def load_model(self, name: str, cls: type[T]) -> T | None:
        p = self.cache / name
        if not p.exists():
            return None
        try:
            return cls.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_json(self, name: str, data) -> Path:
        p = self.cache / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        return p

    def load_json(self, name: str, default=None):
        p = self.cache / name
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))


def assign_ids(files: list[ScannedFile], previous: dict[str, str] | None = None) -> dict[str, str]:
    """Stable IDs per media type: C (video), A (audio), I (image/GIF), L (LUT).

    ``previous`` maps content hash → id from an earlier scan so IDs never change when files are added.
    """
    prefix = {"video": "C", "audio": "A", "image": "I", "lut": "L"}
    previous = previous or {}
    taken = set(previous.values())
    counters = {p: 0 for p in prefix.values()}
    for v in taken:
        p, n = v[0], v[1:]
        if p in counters and n.isdigit():
            counters[p] = max(counters[p], int(n))
    out: dict[str, str] = {}
    for f in files:
        h = fast_hash(f.path)
        if h in previous and previous[h] not in out.values():
            out[f.rel] = previous[h]
            continue
        p = prefix[f.media]
        counters[p] += 1
        out[f.rel] = f"{p}{counters[p]:02d}"
    return out
