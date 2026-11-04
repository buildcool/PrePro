"""Resolve brief anchors ("the line where I say five thousand rupees", "the jump", "the dark night clip",
"epic_build_128") to segment / shot / asset IDs. Unresolvable anchors become open questions."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..schema.analysis import ProjectAnalysis
from ..schema.brief import CreatorBrief, OpenQuestion
from ..schema.media import AssetKind

WORDNUM = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
           "nine": "9", "ten": "10", "twenty": "20", "thirty": "30", "fifty": "50", "hundred": "100", "thousand": "1000"}
# visual words → analysis evidence
VISUAL_HINTS = {
    "dark": lambda s: "dark" in s.flags or s.brightness < 0.2,
    "night": lambda s: s.brightness < 0.25,
    "blurry": lambda s: "blurry" in s.flags,
    "shaky": lambda s: "shaky" in s.flags,
    "jump": lambda s: bool(s.action_peaks) and s.camera_move in ("static", "handheld"),
    "action": lambda s: bool(s.action_peaks),
    "pan": lambda s: s.camera_move.startswith("pan"),
    "transition": lambda s: s.whip_in or s.whip_out,
    "whip": lambda s: s.whip_in or s.whip_out,
    "drive": lambda s: s.camera_move.startswith("push") or s.motion > 0.2,
}
STOP = {"the", "a", "an", "my", "of", "clip", "shot", "part", "scene", "video", "where", "when", "i", "say", "said", "line", "bit", "moment", "wala", "waala"}


def _norm(t: str) -> str:
    t = t.lower()
    for k, v in WORDNUM.items():
        t = re.sub(rf"\b{k}\b", v, t)
    return re.sub(r"[^\wऀ-ॿ ]", " ", t)


def find_segment(pa: ProjectAnalysis, phrase: str, *, min_score: int = 62) -> tuple[str | None, float]:
    best, score = None, 0.0
    q = _norm(phrase)
    for seg in pa.all_segments():
        if seg.retake_rank > 0 or seg.false_start:
            continue
        sc = max(fuzz.partial_ratio(q, _norm(seg.text)), fuzz.token_set_ratio(q, _norm(seg.text)) * 0.95)
        if sc > score:
            best, score = seg.id, sc
    return (best, score) if score >= min_score else (None, score)


def find_shot(pa: ProjectAnalysis, phrase: str) -> tuple[str | None, float]:
    words = [w for w in re.findall(r"[a-z]+", phrase.lower()) if w not in STOP]
    talky = any(w in ("talk", "talking", "say", "speak", "face", "me") for w in words)
    kinds = (AssetKind.BROLL, AssetKind.SCREEN, AssetKind.IMAGE) + ((AssetKind.AROLL,) if talky else ())
    best, score = None, 0.0
    for a in pa.assets:
        if a.kind not in kinds:
            continue
        for s in pa.clips[a.id].shots:
            sc = 0.0
            if any(w in ("jump", "action", "slow", "splash", "flip") for w in words) and s.action_peaks:
                sc += 0.6 * ((a.info.fps or 30) >= 48)
            for w in words:
                if w in VISUAL_HINTS and VISUAL_HINTS[w](s):
                    sc += 1.0
                if w in " ".join(s.tags).lower() or (s.desc and w in s.desc.lower()):
                    sc += 1.2
                if w in a.name.lower() or any(w in n.lower() for n in a.notes):
                    sc += 1.5
            sc /= max(1, len(words))
            if sc > score:
                best, score = s.id, sc
    return (best, score) if score >= 0.5 else (None, score)


def find_asset(pa: ProjectAnalysis, name: str, kinds: set) -> str | None:
    best, score = None, 0
    q = name.lower().replace(" ", "_")
    for a in pa.assets:
        if a.kind not in kinds:
            continue
        sc = fuzz.partial_ratio(q, a.name.lower().rsplit(".", 1)[0])
        if sc > score:
            best, score = a.id, sc
    return best if score >= 70 else None


def resolve(brief: CreatorBrief, pa: ProjectAnalysis) -> CreatorBrief:
    """Fill rule targets/anchors with IDs; add open questions for anything ambiguous."""
    qn = 0
    for i, r in enumerate(brief.rules):
        if r.kind == "hook" and r.anchor:
            sid, sc = find_segment(pa, r.anchor)
            if sid:
                r.target, r.resolved = sid, True
            else:
                shot, _ = find_shot(pa, r.anchor)
                r.target, r.resolved = (shot or ""), bool(shot)
        elif r.kind in ("must_include", "must_exclude") and r.anchor:
            sid, sc = find_segment(pa, r.anchor, min_score=75)
            shot, ssc = find_shot(pa, r.anchor)
            if shot and (ssc >= 0.8 or not sid):
                r.target, r.resolved = shot, True
            elif sid:
                r.target, r.resolved = sid, True
            else:
                r.resolved = False
        elif r.kind == "speed" and r.anchor:
            shot, _ = find_shot(pa, r.anchor)
            r.target, r.resolved = (shot or ""), bool(shot)
        elif r.kind in ("add_meme", "add_sfx") and r.anchor:
            sid, _ = find_segment(pa, r.anchor, min_score=70)
            r.arg["segment"] = sid or ""
            r.resolved = bool(sid)
            if r.target:
                kinds = {AssetKind.MEME_IMAGE, AssetKind.MEME_VIDEO, AssetKind.SFX}
                aid = find_asset(pa, r.target, kinds)
                if aid:
                    r.arg["asset"] = aid
        elif r.kind == "use_music" and r.target:
            aid = find_asset(pa, r.target, {AssetKind.MUSIC})
            if aid:
                r.arg["asset"] = aid
                r.resolved = True
            else:
                r.resolved = False
        if not r.resolved:
            qn += 1
            opts = []
            if r.kind in ("must_include", "must_exclude", "speed", "hook"):
                opts = [s.id for s in list(pa.all_shots())[:12]]
            brief.questions.append(OpenQuestion(id=f"q{qn}", text=f"Which part did you mean by “{r.anchor or r.target}”? ({r.source.strip()[:80]})",
                                                options=opts, rule_index=i))
    return brief
