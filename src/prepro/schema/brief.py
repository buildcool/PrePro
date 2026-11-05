"""Creator brief: optional pre-inputs. Hard rules are enforced; preferences steer; Auto fills the rest."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HardRule(BaseModel):
    """A must/never instruction the compiler enforces and the compliance lint checks."""

    kind: Literal[
        "must_include",      # target = asset id / segment id / shot id / phrase
        "must_exclude",
        "hook",              # use target as the hook
        "use_music",         # target = music asset id; scope = section name or "all"
        "no_music_under_speech",
        "add_text",          # text at anchor (phrase / segment / "start" / "end")
        "text_line",         # one of the creator's on-screen lines, in order (value = index): photo reels, POV text
        "add_meme",          # target = meme asset/catalogue id; anchor = phrase / segment
        "add_sfx",
        "speed",             # target = shot/asset; value = factor
        "no_effect",         # target = zoom|sfx|meme|transition|captions|music
        "max_length",        # value = seconds
        "min_length",
        "captions",          # value: off|clean|bold ; lang in arg
        "no_profanity",
        "deliverable",       # target = playbook / format
    ]
    target: str = ""
    anchor: str = ""          # phrase or id where it applies
    value: float | str | None = None
    arg: dict = Field(default_factory=dict)
    source: str = ""          # original instruction text
    resolved: bool = True     # False when the anchor could not be resolved → open question


class Preferences(BaseModel):
    playbook: str | None = None
    aspect: str | None = None
    target_length: float | None = None
    goal: str | None = None
    audience: str | None = None
    mood: str | None = None
    pace: float | None = None
    effects: str | None = None
    captions: str | None = None
    caption_lang: str | None = None
    humour: str | None = None
    meme_flavour: str | None = None
    look: str | None = None
    music_mood: str | None = None
    references: list[str] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    freedom: Literal["strict", "balanced", "surprise"] = "balanced"
    deliverables: list[str] = Field(default_factory=list)


class OpenQuestion(BaseModel):
    id: str
    text: str
    options: list[str] = Field(default_factory=list)   # ids (shots/segments) to pick from
    rule_index: int | None = None


class CreatorBrief(BaseModel):
    raw_text: str = ""
    sources: list[str] = Field(default_factory=list)   # brief.md, brief.yaml, voice note, ui, tags
    rules: list[HardRule] = Field(default_factory=list)
    prefs: Preferences = Field(default_factory=Preferences)
    questions: list[OpenQuestion] = Field(default_factory=list)
    parsed_by: str = "none"                             # none|rules|ai

    @property
    def is_empty(self) -> bool:
        return not self.raw_text.strip() and not self.rules and self.prefs == Preferences()


class ComplianceItem(BaseModel):
    rule: HardRule
    ok: bool
    detail: str = ""
