"""Analysis results: what the engine learned about every asset (all computed locally)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .media import Asset


class Interval(BaseModel):
    t0: float
    t1: float

    @property
    def dur(self) -> float:
        return max(0.0, self.t1 - self.t0)


class Word(BaseModel):
    id: str                 # "<asset>.w<n>"
    t0: float
    t1: float
    text: str
    conf: float = 1.0
    filler: bool = False
    emphasis: float = 0.0   # prosody z-score-ish (0 = normal)


class Segment(BaseModel):
    """Sentence-ish unit of speech; the AI references these IDs, never timestamps."""

    id: str                 # "<asset>.s<n>"
    asset_id: str
    t0: float
    t1: float
    text: str
    word_ids: list[str] = Field(default_factory=list)
    retake_group: str | None = None   # segments that say "the same thing"
    retake_rank: int = 0              # 0 = preferred take in its group
    false_start: bool = False
    filler_ratio: float = 0.0
    energy: float = 0.0               # mean speech loudness (relative)
    emotion: str | None = None        # filled by AI (or heuristics)
    lang: str | None = None
    tags: list[str] = Field(default_factory=list)   # greeting|cta|question|numbers|hesitation|punchline…


class Transcript(BaseModel):
    asset_id: str
    backend: str                      # faster-whisper | pocketsphinx | sidecar | none
    language: str | None = None
    words: list[Word] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    note: str = ""                    # e.g. "sidecar transcript (not ASR)"

    def word_map(self) -> dict[str, Word]:
        return {w.id: w for w in self.words}


class FaceBox(BaseModel):
    t: float
    x: float                          # normalised 0..1 (centre)
    y: float
    w: float
    h: float
    conf: float = 1.0


class Window(BaseModel):
    t0: float
    t1: float
    score: float
    why: str = ""


class Shot(BaseModel):
    id: str                           # "<asset>.k<n>"
    asset_id: str
    t0: float
    t1: float
    keyframes: list[float] = Field(default_factory=list)
    sharpness: float = 0.0            # variance of Laplacian on proxy (higher = sharper)
    brightness: float = 0.0           # 0..1 mean luma
    contrast: float = 0.0
    saturation: float = 0.0
    shake: float = 0.0                # 0..1 handheld jitter estimate
    motion: float = 0.0               # mean optical-flow magnitude (px/frame on proxy)
    camera_move: str = "static"       # static|pan_left|pan_right|tilt_up|tilt_down|push_in|pull_out|handheld|whip
    whip_in: bool = False             # starts with a whip-pan blur burst
    whip_out: bool = False            # ends with a whip-pan blur burst
    faces: list[FaceBox] = Field(default_factory=list)
    face_ratio: float = 0.0           # fraction of sampled frames with a face
    dup_group: str | None = None
    dup_rank: int = 0                 # 0 = best of its duplicate group
    quality: float = 0.0              # 0..1 technical quality
    aesthetic: float | None = None    # 0..1 (vision tags) when available
    flags: list[str] = Field(default_factory=list)   # blurry|dark|overexposed|shaky|pocket
    tags: list[str] = Field(default_factory=list)    # semantic tags (vision AI / heuristics)
    desc: str | None = None
    shot_type: str | None = None      # wide|medium|close|detail|aerial|screen
    mood: str | None = None
    best: list[Window] = Field(default_factory=list)  # best 2–5 s windows inside the shot
    color: tuple[float, float, float] | None = None   # mean RGB 0..1 (colour continuity)
    phash: str | None = None
    action_peaks: list[float] = Field(default_factory=list)   # source times of motion peaks
    static_ratio: float = 0.0          # share of pixels that never change (HUD / screen capture hint)
    hud: float = 0.0                   # edge density inside the static region (text/HUD overlays)

    @property
    def dur(self) -> float:
        return self.t1 - self.t0


class AudioReport(BaseModel):
    lufs: float | None = None
    peak_db: float | None = None
    noise_floor_db: float | None = None
    snr_db: float | None = None
    clipping_ratio: float = 0.0
    hum_hz: float | None = None
    wind: float = 0.0
    echo: float = 0.0
    speech_ratio: float = 0.0
    issues: list[str] = Field(default_factory=list)   # human-readable


class Section(BaseModel):
    t0: float
    t1: float
    label: str                        # intro|build|drop|break|outro|verse|chorus
    energy: float = 0.0               # 0..1


class MusicInfo(BaseModel):
    bpm: float = 0.0
    beats: list[float] = Field(default_factory=list)
    downbeats: list[float] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    energy_curve: list[float] = Field(default_factory=list)   # 2 Hz, 0..1
    key: str | None = None
    mode: str | None = None           # major|minor
    vocals: bool | None = None        # None = unknown (user can tag)
    mood_tags: list[str] = Field(default_factory=list)
    brightness: float = 0.0


class ClipAnalysis(BaseModel):
    asset_id: str
    speech: list[Interval] = Field(default_factory=list)
    silences: list[Interval] = Field(default_factory=list)
    transcript: Transcript | None = None
    shots: list[Shot] = Field(default_factory=list)
    audio: AudioReport = Field(default_factory=AudioReport)
    music: MusicInfo | None = None
    place: str | None = None
    place_cluster: int | None = None
    day_index: int | None = None
    order_key: float = 0.0            # recording order (creation time or name order)
    errors: list[str] = Field(default_factory=list)


class GenreGuess(BaseModel):
    playbook: str
    score: float
    why: str = ""


class ProjectAnalysis(BaseModel):
    version: int = 1
    root: str
    assets: list[Asset] = Field(default_factory=list)
    clips: dict[str, ClipAnalysis] = Field(default_factory=dict)
    genres: list[GenreGuess] = Field(default_factory=list)
    speech_language: str | None = None
    stats: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def asset(self, asset_id: str) -> Asset:
        for a in self.assets:
            if a.id == asset_id:
                return a
        raise KeyError(asset_id)

    def by_kind(self, *kinds) -> list[Asset]:
        ks = {getattr(k, "value", k) for k in kinds}
        return [a for a in self.assets if a.kind.value in ks]

    def all_segments(self):
        for a in self.assets:
            ca = self.clips.get(a.id)
            if ca and ca.transcript:
                yield from ca.transcript.segments

    def all_shots(self):
        for a in self.assets:
            ca = self.clips.get(a.id)
            if ca:
                yield from ca.shots

    def segment(self, seg_id: str):
        for s in self.all_segments():
            if s.id == seg_id:
                return s
        raise KeyError(seg_id)

    def shot(self, shot_id: str):
        for s in self.all_shots():
            if s.id == shot_id:
                return s
        raise KeyError(shot_id)

    def words(self, asset_id: str):
        ca = self.clips.get(asset_id)
        return ca.transcript.words if ca and ca.transcript else []
