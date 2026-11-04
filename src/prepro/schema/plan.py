"""Editorial plans produced by a brain (rules-only Basic brain or an AI connector).

Plans reference IDs only (segments ``C01.s4``, words ``C01.w37``, shots ``B02.k1``, assets ``M01``,
catalogue memes ``meme:vine-boom``). The compiler resolves IDs to frame-exact times — the brain
never invents timestamps.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Effects = Literal["clean", "balanced", "bold"]
Captions = Literal["off", "clean", "bold"]
Humour = Literal["off", "light", "heavy"]
Freedom = Literal["strict", "balanced", "surprise"]
Aspect = Literal["9:16", "16:9", "1:1", "4:5"]


class Knobs(BaseModel):
    pace: float = 0.5                 # 0 calm … 1 fast
    effects: Effects = "balanced"
    captions: Captions = "clean"
    humour: Humour = "light"
    music_track: str | None = None    # asset id, or None = engine picks
    target_length: float | None = None  # seconds; None = playbook default
    freedom: Freedom = "balanced"
    look: str | None = None           # LUT preset name or asset id
    meme_flavour: str = "global"      # global | indian | genz | mix
    meme_tone: Literal["clean", "edgy"] = "clean"
    tightness: float | None = None    # speech-cut tightness override (Style DNA); None = playbook
    shot_len: float | None = None     # typical B-roll shot length override (Style DNA); None = playbook
    layout: Literal["auto", "stack", "crop"] = "auto"   # vertical cuts of a screen recording with a webcam: stacked or cropped


class HookOption(BaseModel):
    id: str
    kind: str                         # hook taxonomy key (peak_moment, result_first, curiosity_gap…)
    refs: list[str] = Field(default_factory=list)   # segment/shot ids that form the hook
    text_hook: str | None = None      # 3–7 word on-screen hook
    why: str = ""
    score: float = 0.0


class Direction(BaseModel):
    id: str                           # "d1"
    playbook: str                     # playbook key (story_vlog, travel_film, hype_reel, aesthetic, teaser…)
    name: str
    aspect: Aspect = "16:9"
    target_min: float = 30
    target_max: float = 60
    fit_score: float = 0.0
    why: str = ""
    hooks: list[HookOption] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    knobs: Knobs = Field(default_factory=Knobs)
    coverage_gaps: list[str] = Field(default_factory=list)
    from_brief: bool = False


class DirectionSet(BaseModel):
    directions: list[Direction]
    notes: str = ""


class StoryItem(BaseModel):
    ref: str                          # segment id (speech) or shot id (visual)
    role: str = "body"                # hook|setup|escalation|payoff|breather|cta|montage|body|reflection|outro
    t0: float | None = None           # optional sub-range inside a shot (seconds, source time)
    t1: float | None = None
    section: str = "main"
    note: str = ""
    whole: bool = False               # keep the line exactly as spoken (no filler/pause removal, no hook trim)


class StorySection(BaseModel):
    name: str
    music_mode: Literal["bed", "front", "light", "none"] = "bed"
    mood: str | None = None
    card: str | None = None           # title card text at section start (e.g. "Day 2 · Udaipur")


class StoryPlan(BaseModel):
    direction_id: str
    hook_id: str | None = None
    items: list[StoryItem]
    sections: list[StorySection] = Field(default_factory=list)
    chapters: list[str] = Field(default_factory=list)
    why: str = ""


class MusicBrief(BaseModel):
    mood: str = "neutral"
    energy: Literal["low", "medium", "high", "build"] = "medium"
    bpm_min: float = 80
    bpm_max: float = 120
    genre: str = ""
    vocals_ok: bool = False
    structure_needs: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)


class MusicCue(BaseModel):
    section: str
    mode: Literal["bed", "front", "light", "none"] = "bed"
    track_id: str | None = None       # asset id from the user's library (never invented)
    alternatives: list[str] = Field(default_factory=list)
    brief: MusicBrief = Field(default_factory=MusicBrief)
    why: str = ""
    gain_db: float = 0.0              # creator's "music louder/quieter" on top of the playbook level


class EffectCue(BaseModel):
    """Generic anchored effect: zoom, sfx, meme, text, speed, transition, broll…"""

    type: str                         # zoom|sfx|meme|text|speed|transition|broll|emphasis|look|bleep
    at: str                           # anchor id: word, segment, shot or item boundary ("cut:3")
    asset: str | None = None          # asset id or catalogue id ("meme:vine-boom", "sfx:whoosh")
    value: float | None = None        # zoom scale, speed factor, …
    text: str | None = None
    style: str | None = None
    dur: float | None = None
    intent: str | None = None
    why: str = ""
    confidence: float = 0.7


class BrollGap(BaseModel):
    at: str                           # segment id
    want: str                         # what shot would help
    search_terms: list[str] = Field(default_factory=list)


class PolishPlan(BaseModel):
    direction_id: str
    music: list[MusicCue] = Field(default_factory=list)
    effects: list[EffectCue] = Field(default_factory=list)
    broll_gaps: list[BrollGap] = Field(default_factory=list)
    vo_script: list[str] = Field(default_factory=list)
    look: str | None = None
    notes: list[str] = Field(default_factory=list)


class FixOp(BaseModel):
    op: Literal[
        "drop_effect", "move_effect", "swap_hook", "trim_item", "drop_item", "add_effect",
        "shift_music", "lower_density", "reorder", "set_speed", "swap_track", "add_text",
    ]
    target: str = ""                  # suggestion id / item id / hook id
    arg: dict = Field(default_factory=dict)
    why: str = ""


class CriticReport(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)   # 0..10
    issues: list[str] = Field(default_factory=list)
    fixes: list[FixOp] = Field(default_factory=list)
    summary: str = ""
    source: str = "rules"
