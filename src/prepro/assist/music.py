"""Soundtrack modes (bed / front / light / none) and music matching against the user's own library.

The engine never invents track names: it ranks tracks that exist in the shoot's music folder and, when
nothing fits, returns search terms for the libraries the creator already uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ..knowledge import Playbook
from ..schema.analysis import MusicInfo, ProjectAnalysis
from ..schema.media import Asset, AssetKind
from ..schema.plan import MusicBrief

VOCAL_NAME = re.compile(r"vocal|song|lyric|feat\.?|ft\.|sing|karaoke|acapella|chorus", re.I)
INSTRUMENTAL_NAME = re.compile(r"instrumental|inst\b|bgm|beat|lofi|lo-fi|ambient|no vocals?", re.I)


def soundtrack_mode(speech_coverage: float, playbook: Playbook, *, asmr: bool = False) -> str:
    """Pick the music's job for a section from how much of it is speech."""
    pref = playbook.music.get("mode", "mixed")
    if pref == "none":
        return "none"
    if asmr:
        return "light"
    if speech_coverage >= 0.5:
        return "bed"
    if speech_coverage <= 0.15:
        return "light" if pref == "light" else "front"
    return "bed" if pref in ("bed", "light") else "front"


def has_vocals(asset: Asset, info: MusicInfo | None) -> bool | None:
    if "instrumental" in asset.user_tags or INSTRUMENTAL_NAME.search(asset.name):
        return False
    if "vocals" in asset.user_tags or VOCAL_NAME.search(asset.name):
        return True
    return info.vocals if info else None


def brief_for(mode: str, playbook: Playbook, mood: str | None, *, need_secs: float, pace: float) -> MusicBrief:
    prefer = list(playbook.music.get("prefer", []))
    if mood:
        prefer = [mood] + [p for p in prefer if p != mood]
    if mode == "bed":
        lo, hi, energy = 70, 112, "low"
    elif mode == "light":
        lo, hi, energy = 60, 100, "low"
    else:
        lo = 90 + 50 * pace
        hi = lo + 45
        energy = "build" if playbook.key in ("travel_film", "hype_reel", "teaser") else "high"
        if playbook.music.get("bpm"):            # a genre with its own tempo (a day in my life: light, 80–125 BPM)
            lo, hi = (float(x) for x in playbook.music["bpm"])
            energy = "medium"
    terms = [f"{prefer[0] if prefer else 'chill'} {'instrumental ' if mode == 'bed' else ''}{'travel' if 'travel' in playbook.key or 'vlog' in playbook.key else ''}".strip()]
    if mode == "front":
        feel = {"build": "build drop", "high": "energetic"}.get(energy, "")
        terms.append(" ".join(x for x in (f"{int(lo)}-{int(hi)} bpm", feel, prefer[0] if prefer else "") if x))
    if mode == "bed":
        terms.append("no vocals background music")
    return MusicBrief(mood=prefer[0] if prefer else "neutral", energy=energy, bpm_min=float(lo), bpm_max=float(hi),
                      genre="", vocals_ok=(mode == "front"),
                      structure_needs=[f"at least {need_secs:.0f}s or loopable"] + (["a clear build → drop"] if energy == "build" else []),
                      search_terms=terms)


@dataclass
class TrackScore:
    asset_id: str
    score: float
    why: str


def rank_tracks(pa: ProjectAnalysis, brief: MusicBrief, mode: str, *, avoid: list[str] | None = None, exclude: set[str] | None = None) -> list[TrackScore]:
    out = []
    avoid = avoid or []
    for a in pa.assets:
        if a.kind != AssetKind.MUSIC or (exclude and a.id in exclude):
            continue
        m = pa.clips.get(a.id).music if pa.clips.get(a.id) else None
        if not m or not m.bpm:
            continue
        tags = set(m.mood_tags)
        why = []
        s = 0.0
        if brief.mood in tags:
            s += 0.35
            why.append(f"mood '{brief.mood}'")
        overlap = tags & set([brief.mood] + [t for t in ("chill", "calm", "happy", "upbeat", "epic", "hype", "warm", "aesthetic", "energetic") if t in tags])
        s += 0.05 * len(overlap)
        if tags & set(avoid):
            s -= 0.3
            why.append("mood clashes")
        bpm = m.bpm
        if brief.bpm_min <= bpm <= brief.bpm_max:
            s += 0.25
            why.append(f"{bpm:.0f} BPM fits")
        else:
            d = min(abs(bpm - brief.bpm_min), abs(bpm - brief.bpm_max))
            s += max(-0.2, 0.25 - d / 60)
        voc = has_vocals(a, m)
        if mode == "bed" and voc:
            s -= 0.45
            why.append("has vocals (bad under speech)")
        if brief.energy == "build" and any(sec.label in ("build", "drop") for sec in m.sections):
            s += 0.2
            why.append("has a build → drop")
        if brief.energy == "low" and np.mean(m.energy_curve or [0.5]) < 0.5:
            s += 0.15
            why.append("low energy")
        if brief.energy == "high" and np.mean(m.energy_curve or [0.5]) > 0.5:
            s += 0.15
            why.append("high energy")
        out.append(TrackScore(a.id, round(s, 3), ", ".join(why) or "available"))
    out.sort(key=lambda t: -t.score)
    return out


def drop_time(m: MusicInfo) -> float | None:
    for s in m.sections:
        if s.label == "drop":
            return s.t0
    return None


def best_offset(m: MusicInfo, track_dur: float, need: float, *, align_drop_at: float | None = None) -> tuple[float, str]:
    """Where to start the track so it fits the edit: align the drop to a moment, or backtime to end on the outro."""
    if align_drop_at is not None:
        d = drop_time(m)
        if d is not None and d - align_drop_at >= 0 and d - align_drop_at + need <= track_dur + 0.5:
            off = d - align_drop_at
            return off, f"drop lands at {align_drop_at:.1f}s"
    if track_dur > need + 2 and any(s.label == "outro" for s in m.sections):
        off = track_dur - need
        if m.downbeats:
            j = int(np.argmin(np.abs(np.array(m.downbeats) - off)))
            off = float(m.downbeats[j]) if m.downbeats[j] + need <= track_dur + 0.5 else off
        return max(0.0, off), "backtimed to end on the track's outro"
    first = m.downbeats[0] if m.downbeats and m.downbeats[0] < 4 else 0.0
    return first, "starts on the first downbeat"
