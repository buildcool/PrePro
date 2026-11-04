"""Editing knowledge base: playbooks, hooks, emotions, SFX vocabulary, meme catalogue, constitution."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

HERE = Path(__file__).parent


class Pacing(BaseModel):
    aroll_shot: tuple[float, float] = (2, 6)
    broll_shot: tuple[float, float] = (1.5, 4)
    tightness: float = 0.5
    breath: float = 0.12
    max_pause: float = 0.5
    dead_zone: float = 10


class Playbook(BaseModel):
    key: str = ""
    name: str
    aspect: str = "16:9"
    target: tuple[float, float] = (30, 90)
    keep_ratio: float = 0.6
    structure: list[str] = Field(default_factory=list)
    pacing: Pacing = Field(default_factory=Pacing)
    budgets: dict[str, float] = Field(default_factory=dict)
    captions: dict = Field(default_factory=dict)
    music: dict = Field(default_factory=dict)
    memes: str = "never"
    transitions: dict = Field(default_factory=dict)
    split_edits: dict = Field(default_factory=dict)   # J/L cut lengths in seconds, e.g. {j: 0.5, l: 0.4}; empty = none
    signature: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)

    def budget(self, kind: str) -> float:
        return float(self.budgets.get(kind, 0))


class Meme(BaseModel):
    id: str
    name: str
    type: str
    intent: list[str]
    tone: str = "clean"
    culture: str = "global"
    dur: float = 1.5
    notes: str = ""
    search: list[str] = Field(default_factory=list)
    freshness: int = 2026


@lru_cache(maxsize=1)
def playbooks() -> dict[str, Playbook]:
    data = yaml.safe_load((HERE / "playbooks.yaml").read_text(encoding="utf-8"))
    return {k: Playbook(key=k, **v) for k, v in data.items()}


def playbook(key: str) -> Playbook:
    pbs = playbooks()
    return pbs.get(key) or pbs["story_vlog"]


@lru_cache(maxsize=1)
def memes() -> list[Meme]:
    return [Meme(**m) for m in yaml.safe_load((HERE / "memes.yaml").read_text(encoding="utf-8"))]


@lru_cache(maxsize=1)
def hooks() -> dict:
    return yaml.safe_load((HERE / "hooks.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def emotions() -> dict:
    return yaml.safe_load((HERE / "emotions.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def sfx_vocab() -> dict:
    return yaml.safe_load((HERE / "sfx.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def craft() -> list[dict]:
    """Technique cards (knowledge/craft.yaml): trigger, recipe, guardrails, budget, source."""
    return yaml.safe_load((HERE / "craft.yaml").read_text(encoding="utf-8"))


def craft_brief(playbook: str | None = None) -> str:
    """Compact craft notes for the AI brain's prompt (only the cards for this genre)."""
    lines = []
    for c in craft():
        if playbook and "all" not in c["genres"] and playbook not in c["genres"]:
            continue
        lines.append(f"- {c['name']}: {c['recipe']} (not when: {c['guardrails']})")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def broll_concepts() -> list[dict]:
    return yaml.safe_load((HERE / "broll.yaml").read_text(encoding="utf-8"))


def broll_ask(text: str, place: str | None = None) -> tuple[str, list[str]]:
    """Turn a line with no matching footage into the shot request a human editor would write."""
    import re

    words = {w.lower() for w in re.findall(r"[\w₹]+", text)}
    hits = [c for c in broll_concepts() if words & {str(x).lower() for x in c["words"]}]
    concrete = [c for c in hits if not c.get("abstract")]
    if hits:
        c = (concrete or hits)[0]
        want = c["want"]
        extra = next((h.get("add") for h in hits if h is not c and h.get("add")), None)
        if extra:
            want = f"{want} — {extra}"
        terms = list(c["search"])
        if place and c.get("local"):
            terms = [f"{place} {terms[0]}"] + terms[1:]
        return want, terms[:3]
    if place:
        return f"an establishing shot of {place} that matches what you say here", [f"{place} wide shot", f"{place} street detail"]
    return "a cutaway that shows what you are talking about here", []


@lru_cache(maxsize=1)
def constitution() -> str:
    return (HERE / "constitution.md").read_text(encoding="utf-8")
