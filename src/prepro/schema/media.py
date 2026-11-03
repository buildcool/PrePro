"""Media + asset models (what is in the shoot folder)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AssetKind(str, Enum):
    AROLL = "aroll"            # someone talking (to camera / voice-led)
    BROLL = "broll"            # visuals without meaningful speech
    SCREEN = "screen"          # screen capture / gameplay
    VOICEOVER = "voiceover"    # audio-only speech (VO, voice note brief excluded)
    MUSIC = "music"            # audio-only music track
    SFX = "sfx"                # short audio effect
    MEME_VIDEO = "meme_video"  # short reaction/meme clip
    MEME_IMAGE = "meme_image"  # still/GIF meme or sticker overlay
    IMAGE = "image"            # photo to use as a still in the edit
    LUT = "lut"                # .cube colour look
    UNKNOWN = "unknown"


VIDEO_KINDS = {AssetKind.AROLL, AssetKind.BROLL, AssetKind.SCREEN, AssetKind.MEME_VIDEO}
AUDIO_KINDS = {AssetKind.VOICEOVER, AssetKind.MUSIC, AssetKind.SFX}


class GeoPoint(BaseModel):
    lat: float
    lon: float
    alt: float | None = None


class MediaInfo(BaseModel):
    path: str
    size: int = 0
    format_name: str = ""
    duration: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    is_image: bool = False
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vfr: bool = False
    rotation: int = 0
    vcodec: str | None = None
    acodec: str | None = None
    pix_fmt: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bitrate: int | None = None
    creation_time: datetime | None = None
    location: GeoPoint | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    @property
    def display_size(self) -> tuple[int, int] | None:
        """Width/height after applying rotation metadata (what a player shows)."""
        if self.width is None or self.height is None:
            return None
        if abs(self.rotation) % 180 == 90:
            return self.height, self.width
        return self.width, self.height

    @property
    def is_vertical(self) -> bool:
        ds = self.display_size
        return bool(ds and ds[1] > ds[0])


class Asset(BaseModel):
    id: str                     # stable short id used everywhere (C01, B03, M01, S02, X01, I01…)
    path: str                   # relative to shoot root, forward slashes
    hash: str                   # fast content hash (size + head/tail blocks)
    kind: AssetKind
    kind_reason: str = ""
    info: MediaInfo
    tags: list[str] = Field(default_factory=list)       # filename tags: hook, must, skip …
    notes: list[str] = Field(default_factory=list)      # creator notes (notes.yaml / UI)
    user_tags: list[str] = Field(default_factory=list)  # e.g. "instrumental", "funny"

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]
