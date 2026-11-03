"""Real-world test media fetched from openly reachable sources (never committed to git).

Every entry records its source and licence. Use ``prepro testmedia fetch`` to download into the cache
(``~/.cache/prepro/testmedia`` or ``$PREPRO_TESTMEDIA``). Tests marked ``realmedia`` skip when absent.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir

RAW = "https://raw.githubusercontent.com"
INTEL = f"{RAW}/intel-iot-devkit/sample-videos/master"
LIBROSA = f"{RAW}/librosa/data/main/audio"


@dataclass(frozen=True)
class MediaItem:
    name: str
    url: str
    category: str          # face|people|street|driving|food|indoor|animation|music|speech|podcast|nature
    licence: str
    note: str = ""


MANIFEST: list[MediaItem] = [
    MediaItem("head-pose-face-detection-female-and-male.mp4", f"{INTEL}/head-pose-face-detection-female-and-male.mp4", "face", "CC-BY-4.0 (Intel sample-videos)", "talking-head stand-in"),
    MediaItem("head-pose-face-detection-female.mp4", f"{INTEL}/head-pose-face-detection-female.mp4", "face", "CC-BY-4.0 (Intel sample-videos)"),
    MediaItem("face-demographics-walking.mp4", f"{INTEL}/face-demographics-walking.mp4", "people", "CC-BY-4.0 (Intel sample-videos)"),
    MediaItem("people-detection.mp4", f"{INTEL}/people-detection.mp4", "people", "CC-BY-4.0 (Intel sample-videos)"),
    MediaItem("person-bicycle-car-detection.mp4", f"{INTEL}/person-bicycle-car-detection.mp4", "street", "CC-BY-4.0 (Intel sample-videos)"),
    MediaItem("car-detection.mp4", f"{INTEL}/car-detection.mp4", "driving", "CC-BY-4.0 (Intel sample-videos)", "speed-up candidate"),
    MediaItem("fruit-and-vegetable-detection.mp4", f"{INTEL}/fruit-and-vegetable-detection.mp4", "food", "CC-BY-4.0 (Intel sample-videos)", "lifestyle/cooking"),
    MediaItem("store-aisle-detection.mp4", f"{INTEL}/store-aisle-detection.mp4", "indoor", "CC-BY-4.0 (Intel sample-videos)"),
    MediaItem("classroom.mp4", f"{INTEL}/classroom.mp4", "indoor", "CC-BY-4.0 (Intel sample-videos)"),
    MediaItem("vtest.avi", f"{RAW}/opencv/opencv/4.x/samples/data/vtest.avi", "street", "Apache-2.0 (OpenCV samples)"),
    MediaItem("bear-1280x720.mp4", f"{RAW}/chromium/chromium/main/media/test/data/bear-1280x720.mp4", "nature", "BSD-3 (Chromium test data)"),
    MediaItem("big_buck_bunny.mp4", f"{RAW}/mediaelement/mediaelement-files/master/big_buck_bunny.mp4", "animation", "CC-BY-3.0 (Blender Foundation)"),
    MediaItem("echo-hereweare.mp4", f"{RAW}/mediaelement/mediaelement-files/master/echo-hereweare.mp4", "speech", "test-only (mediaelement-files)"),
    MediaItem("podcast-chasing-corporate.mp3", f"{RAW}/mediaelement/mediaelement-files/master/AirReview-Landmarks-02-ChasingCorporate.mp3", "podcast", "test-only (mediaelement-files)"),
    MediaItem("jfk.flac", f"{RAW}/openai/whisper/main/tests/jfk.flac", "speech", "Public domain (JFK inaugural address)"),
    MediaItem("libri1.ogg", f"{LIBROSA}/5703-47212-0000.hq.ogg", "speech", "CC-BY-4.0 (LibriSpeech)"),
    MediaItem("libri2.ogg", f"{LIBROSA}/3436-172162-0000.hq.ogg", "speech", "CC-BY-4.0 (LibriSpeech)"),
    MediaItem("libri3.ogg", f"{LIBROSA}/198-209-0000.hq.ogg", "speech", "CC-BY-4.0 (LibriSpeech)"),
    MediaItem("vibe_ace.ogg", f"{LIBROSA}/Kevin_MacLeod_-_Vibe_Ace.hq.ogg", "music", "CC-BY-3.0 (Kevin MacLeod)", "funky/jazzy"),
    MediaItem("choice_drum_bass.ogg", f"{LIBROSA}/admiralbob77_-_Choice_-_Drum-bass.hq.ogg", "music", "CC-BY (Admiral Bob)", "hype/drum & bass"),
    MediaItem("pistachio_ragtime.ogg", f"{LIBROSA}/442789__lena-orsa__happy-music-pistachio-ice-cream-ragtime.hq.ogg", "music", "CC-BY (Lena Orsa)", "happy"),
    MediaItem("lets_go_fishin.ogg", f"{LIBROSA}/Karissa_Hobbs_-_Lets_Go_Fishin.hq.ogg", "music", "CC-BY (Karissa Hobbs)", "blues/folk"),
    MediaItem("sweet_waltz.ogg", f"{LIBROSA}/147793__setuniman__sweet-waltz-0i-22mi.hq.ogg", "music", "CC-BY (Setuniman)", "calm"),
    MediaItem("brahms_hungarian5.ogg", f"{LIBROSA}/Hungarian_Dance_number_5_-_Allegro_in_F_sharp_minor_(string_orchestra).hq.ogg", "music", "Public domain recording (Musopen)", "dramatic"),
    MediaItem("robin_bird.ogg", f"{LIBROSA}/456440__inspectorj__bird-whistling-robin-single-13.hq.ogg", "nature", "CC-BY-3.0 (InspectorJ)"),
]


def cache_dir() -> Path:
    d = Path(os.environ.get("PREPRO_TESTMEDIA") or Path(user_cache_dir("prepro")) / "testmedia")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, dest: Path, timeout: float = 120) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "prepro-testmedia/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    head = tmp.read_bytes()[:64]
    if head.startswith(b"version https://git-lfs") or head.lstrip().startswith(b"<"):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{url} returned a pointer/HTML page, not media")
    tmp.replace(dest)


def fetch(categories: set[str] | None = None, *, verbose: bool = True) -> dict[str, Path]:
    out: dict[str, Path] = {}
    root = cache_dir()
    for it in MANIFEST:
        if categories and it.category not in categories:
            continue
        dest = root / it.category / it.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 1000:
            out[it.name] = dest
            continue
        try:
            _download(it.url, dest)
            out[it.name] = dest
            if verbose:
                print(f"  ✓ {it.category:9s} {it.name}  ({dest.stat().st_size // 1024} KB)  [{it.licence}]")
        except Exception as e:  # network policy / missing file
            if verbose:
                print(f"  ✗ {it.name}: {e}")
    (root / "SOURCES.md").write_text(
        "# Test media sources (test use only; not redistributed)\n\n"
        + "\n".join(f"- `{i.category}/{i.name}` — {i.licence} — {i.url}" for i in MANIFEST),
        encoding="utf-8",
    )
    return out


def available() -> dict[str, Path]:
    root = cache_dir()
    found = {}
    for it in MANIFEST:
        p = root / it.category / it.name
        if p.exists() and p.stat().st_size > 1000:
            found[it.name] = p
    return found


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
