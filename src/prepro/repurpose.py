"""Long → Shorts: find the self-contained 20–60 s moments in long talking footage and cut each as a vertical Short.

What a clipper looks for (and what makes clips feel random when it's ignored):
- a first line that works on its own: a number, a question, a strong claim — never "and so, like I said…";
- a landing: the lesson, the punchline, the "that's it" — not a trailing "anyway, where was I";
- one idea, little dead weight inside (fillers, retakes, asides);
- 20–45 s sweet spot (up to 60 s), and no two Shorts telling the same part.
Each pick becomes a normal timeline (podcast_clip playbook, 9:16, bold captions, reframed on the face), so it can
be reviewed, revised and exported like any other cut.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from .brain.basic import BasicBrain, text_hook
from .project import Project
from .schema.analysis import ProjectAnalysis, Segment
from .schema.brief import CreatorBrief
from .schema.plan import Direction, DirectionSet, HookOption, Knobs, StoryItem, StoryPlan, StorySection

ORPHAN = re.compile(r"^\s*(and|so|but|also|then|anyway|because|which|plus|or|like i said|as i said|as i mentioned|like i mentioned|that's why|this is why|"
                    r"it|this|that|they|he|she|those|these|there)\b", re.I)
PAYOFF = re.compile(r"\b(so here is|here's the|the lesson|lesson|the point|the secret|that's it|that's the|that is the|remember|bottom line|"
                    r"try it|watch your|the answer|the trick|the truth|never again|and that's how|which is why|turns out)\b", re.I)
RAMBLE = re.compile(r"\b(anyway|where was i|you know|kind of|sort of|and stuff|whatever|let me check|moving on|i guess|it depends)\b", re.I)
DANGLING = re.compile(r"\b(and|but|or|so|because|like|um+|uh+)\W*$", re.I)


class ShortCandidate(BaseModel):
    id: str
    asset_id: str
    segments: list[str]
    t0: float
    t1: float
    score: float
    hook: str
    title: str
    why: list[str] = Field(default_factory=list)
    parts: dict[str, float] = Field(default_factory=dict)

    @property
    def dur(self) -> float:
        return self.t1 - self.t0


def _opener(bb: BasicBrain, s: Segment, rank: int) -> tuple[float, list[str]]:
    why = []
    sc = bb.speech_hook_score(s, rank)
    if "numbers" in s.tags:
        why.append("opens on a number")
    if "question" in s.tags:
        why.append("opens on a question")
    if re.search(r"\b(only|never|best|worst|most|secret|mistakes?|nobody|everyone|lost|million|thousand|why)\b", s.text, re.I):
        sc += 0.15
        why.append("opens on a strong claim")
    if ORPHAN.match(s.text):
        sc -= 0.6
        why.append("⚠ first line leans on earlier context")
    if bb.is_cut_candidate(s) or RAMBLE.search(s.text):
        sc -= 0.5
    return sc, why


def _closer(bb: BasicBrain, s: Segment) -> tuple[float, list[str]]:
    why, sc = [], 0.0
    text = s.text.strip()
    if PAYOFF.search(text):
        sc += 0.45
        why.append("lands on a lesson / payoff")
    if text.endswith("!") or "punchline" in s.tags:
        sc += 0.2
        why.append("ends on a punchline")
    if re.search(r"[.!?]$", text) and len(text.split()) >= 4:
        sc += 0.15
    if RAMBLE.search(text) or bb.is_cut_candidate(s):
        sc -= 0.6
        why.append("⚠ trails off")
    if DANGLING.search(text):
        sc -= 0.4
    if "cta" in s.tags:
        sc -= 0.1
    return sc, why


def _length_pref(d: float, lo: float, hi: float) -> float:
    if d < lo or d > hi:
        return -1.0
    sweet0, sweet1 = 20.0, 45.0
    if sweet0 <= d <= sweet1:
        return 1.0
    return 0.5 if d < sweet0 else max(0.0, 1.0 - (d - sweet1) / max(1.0, hi - sweet1))


def find_shorts(pa: ProjectAnalysis, *, count: int = 3, min_len: float = 15.0, max_len: float = 60.0,
                brief: CreatorBrief | None = None) -> list[ShortCandidate]:
    bb = BasicBrain(pa, brief)
    cands: list[ShortCandidate] = []
    for a in bb.talk_assets():
        segs = sorted(pa.clips[a.id].transcript.segments, key=lambda s: s.t0)
        clean = [s for s in segs if not (bb.is_cut_candidate(s) and s.retake_rank and s.retake_rank > 0)]
        for i, first in enumerate(clean):
            if "greeting" in first.tags:
                continue
            op, op_why = _opener(bb, first, i)
            if op < 0.05:
                continue
            for j in range(i, len(clean)):
                last = clean[j]
                dur = last.t1 - first.t0
                if dur > max_len:
                    break
                if dur < min_len:
                    continue
                window = clean[i: j + 1]
                weak = [s for s in window if bb.is_cut_candidate(s) or RAMBLE.search(s.text)]
                weak_ratio = sum(s.t1 - s.t0 for s in weak) / max(1e-6, dur)
                cl, cl_why = _closer(bb, last)
                lp = _length_pref(dur, min_len, max_len)
                inner = sum(bb.speech_hook_score(s, 3) for s in window[1:-1]) / max(1, len(window) - 2) if len(window) > 2 else 0.0
                score = 0.42 * op + 0.33 * cl + 0.15 * (1 - min(1.0, weak_ratio * 2)) + 0.1 * lp + 0.05 * inner
                why = op_why + cl_why
                if weak_ratio > 0.15:
                    why.append(f"⚠ {weak_ratio:.0%} rambling inside")
                cands.append(ShortCandidate(id="", asset_id=a.id, segments=[s.id for s in window], t0=first.t0, t1=last.t1,
                                            score=round(score, 3), hook=first.text.strip(), title=_title(first.text),
                                            why=why, parts={"open": round(op, 2), "close": round(cl, 2), "weak": round(weak_ratio, 2),
                                                            "length": round(lp, 2)}))
    # non-maximum suppression: no two Shorts tell the same part
    picked: list[ShortCandidate] = []
    for c in sorted(cands, key=lambda c: -c.score):
        if any(c.asset_id == p.asset_id and min(c.t1, p.t1) - max(c.t0, p.t0) > 0.2 * min(c.dur, p.dur) for p in picked):
            continue
        picked.append(c)
        if len(picked) >= count:
            break
    for k, c in enumerate(picked, start=1):
        c.id = f"s{k}"
    return picked


def _title(text: str) -> str:
    t = re.sub(r"\s+", " ", text.strip()).rstrip(".")
    return t if len(t) <= 70 else t[:67].rsplit(" ", 1)[0] + "…"


def _direction(c: ShortCandidate, pa: ProjectAnalysis) -> Direction:
    th = text_hook(c.hook)
    return Direction(id=c.id, playbook="podcast_clip", name=f"Short {c.id[1:]} · {_title(c.hook)[:48]}", aspect="9:16",
                     target_min=round(c.dur * 0.75, 1), target_max=round(c.dur * 1.1, 1), fit_score=round(min(1.0, max(0.0, c.score)), 3),
                     why="; ".join(w for w in c.why if not w.startswith("⚠")) or "self-contained moment",
                     hooks=[HookOption(id="h0", kind="from_clip", refs=[c.segments[0]], text_hook=th, why="the clip's own first line", score=1.0)],
                     outline=[f"{len(c.segments)} lines · {c.dur:.0f} s of {c.asset_id}"],
                     knobs=Knobs(captions="bold", effects="balanced", humour="off", target_length=round(c.dur * 1.05, 1), pace=0.6))


def _story(c: ShortCandidate) -> StoryPlan:
    n = len(c.segments)
    items = [StoryItem(ref=sid, role="hook" if k == 0 else ("payoff" if k == n - 1 and n > 2 else "body"), section="clip")
             for k, sid in enumerate(c.segments)]
    return StoryPlan(direction_id=c.id, hook_id="h0", items=items, sections=[StorySection(name="clip", music_mode="bed")],
                     why="one idea, its own first line as the hook, ends on its landing")


def shorts_path(root: str | Path) -> Path:
    return Project(root).cache / "shorts.json"


def find_direction(root: str | Path, did: str) -> Direction | None:
    """Direction by id from the director's cards or from the Shorts finder."""
    proj = Project(root)
    for name in ("directions.json", "shorts.json"):
        ds = proj.load_model(name, DirectionSet)
        if ds:
            d = next((x for x in ds.directions if x.id == did), None)
            if d:
                return d
    return None


def build_shorts(root: str | Path, *, count: int = 3, min_len: float = 15.0, max_len: float = 60.0, render: bool = False,
                 progress=None) -> list[tuple[ShortCandidate, str]]:
    """Find the best Shorts and compile each into a reviewable timeline. Returns (candidate, timeline id)."""
    from .engine import analysis, brief_for
    from .lint.editlint import apply_fixes, lint_timeline
    from .timeline.compiler import compile_timeline

    pa = analysis(root, progress=progress)
    brief = brief_for(root, pa)
    picks = find_shorts(pa, count=count, min_len=min_len, max_len=max_len, brief=brief)
    proj = Project(root)
    dirs = DirectionSet(directions=[_direction(c, pa) for c in picks], notes="Shorts found in long talking footage")
    proj.save_model("shorts.json", dirs)
    out = []
    bb = BasicBrain(pa, brief)
    for c, d in zip(picks, dirs.directions, strict=True):
        if progress:
            progress("shorts", len(out), len(picks), d.name)
        story = _story(c)
        polish = bb.polish(d, story)
        tl = compile_timeline(pa, d, story, polish, brief, project_root=root)
        findings = lint_timeline(tl, pa, d, brief)
        if any(f.fix for f in findings):
            polish, story = apply_fixes(findings, polish, story, pa, d)
            tl = compile_timeline(pa, d, story, polish, brief, project_root=root)
        tl.meta["short"] = c.model_dump()
        proj.save_model(f"timelines/{tl.id}.json", tl)
        proj.save_model(f"timelines/{tl.id}.story.json", story)
        proj.save_model(f"timelines/{tl.id}.polish.json", polish)
        base = proj.cache / "timelines" / f"{tl.id}.base.json"
        base.write_text(tl.model_dump_json(indent=1), encoding="utf-8")
        if render:
            from .export.render import render as do_render

            do_render(tl, pa, proj.sub("renders") / f"{tl.id}_preview.mp4", quality="preview", project_root=root)
        out.append((c, tl.id))
    return out


def rebuild_short(root: str | Path, sid: str, knobs: dict | None = None) -> str:
    """Re-polish one Short with new knobs (same lines), keeping it reviewable. Returns the timeline id."""
    from .engine import analysis, brief_for
    from .timeline.compiler import compile_timeline

    proj = Project(root)
    ds = proj.load_model("shorts.json", DirectionSet)
    d = next(x for x in ds.directions if x.id == sid)
    if knobs:
        d.knobs = d.knobs.model_copy(update={k: v for k, v in knobs.items() if k in type(d.knobs).model_fields and v is not None})
        proj.save_model("shorts.json", ds)
    tid = f"{sid}-{d.playbook}"
    story = proj.load_model(f"timelines/{tid}.story.json", StoryPlan)
    pa = analysis(root)
    brief = brief_for(root, pa)
    polish = BasicBrain(pa, brief).polish(d, story)
    tl = compile_timeline(pa, d, story, polish, brief, project_root=root)
    old = proj.load_model(f"timelines/{tid}.base.json", __import__("prepro.schema.timeline", fromlist=["Timeline"]).Timeline)
    if old and old.meta.get("short"):
        tl.meta["short"] = old.meta["short"]
    proj.save_model(f"timelines/{tid}.json", tl)
    proj.save_model(f"timelines/{tid}.polish.json", polish)
    (proj.cache / "timelines" / f"{tid}.base.json").write_text(tl.model_dump_json(indent=1), encoding="utf-8")
    return tid
