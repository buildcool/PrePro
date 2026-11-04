"""Revisions: accept/reject suggestions and timeline comments → plan edits → instant recompile.

The build's story/polish plans stay untouched. A revision is a list of operations replayed on top of them, so
every choice can be undone, and the same choices are re-applied after a rebuild (keys are stable analysis ids).
No AI is needed for the common notes an editor gets ("remove that zoom", "big text: ₹500 only", "meme here",
"faster here", "cut this", "change the song"); an AI connector can interpret the rest.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import knowledge as K
from .project import Project
from .schema.analysis import ProjectAnalysis
from .schema.media import AssetKind
from .schema.plan import Direction, EffectCue, PolishPlan, StoryItem, StoryPlan
from .schema.timeline import Suggestion, Timeline

OpKind = Literal["reject", "accept", "add", "drop", "trim", "speed", "whole", "swap_track", "music_gain", "captions", "hook"]


class Op(BaseModel):
    op: OpKind
    key: str | None = None            # suggestion key: fx:zoom:C01.w14 · seg:C01.s3 · shot:C04.k1 · item:C02.k0 · music:a,b · captions …
    ref: str | None = None            # story ref for drop/trim/speed/whole, sections for music ops ("a,b")
    cue: EffectCue | None = None      # for add
    value: float | str | None = None
    why: str = ""
    comment_id: str | None = None     # set when the op came from a timeline comment


class Comment(BaseModel):
    id: str
    t: float
    text: str
    status: Literal["applied", "partly", "not_understood"] = "applied"
    reply: str = ""                   # what the engine did, in words
    source: str = "rules"             # rules | ai


class Revision(BaseModel):
    timeline_id: str
    ops: list[Op] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)


# ------------------------------------------------------------------ applying ops to plans
def _find(story: StoryPlan, ref: str) -> int | None:
    return next((k for k, it in enumerate(story.items) if it.ref == ref), None)


def _fx_match(c: EffectCue, key: str) -> bool:
    body = key[3:]                                   # "zoom:C01.w14" or "text:end|Follow for part 2"
    typ, _, rest = body.partition(":")
    at, _, text = rest.partition("|")
    if c.type != typ:
        return False
    if c.at != at and not (typ in ("broll",) and c.asset == at):
        return False
    return not text or (c.text or "")[:24] == text


def _seg_or_shot(pa: ProjectAnalysis, ref: str):
    try:
        return pa.segment(ref), None
    except KeyError:
        pass
    try:
        return None, pa.shot(ref)
    except KeyError:
        return None, None


def _insert_ref(story: StoryPlan, pa: ProjectAnalysis, ref: str, role: str) -> None:
    """Put a line/shot back where it belongs: next to its neighbours from the same clip, else the same day/place."""
    if _find(story, ref) is not None:
        return
    seg, shot = _seg_or_shot(pa, ref)
    obj = seg or shot
    if obj is None:
        return
    aid, t0 = obj.asset_id, obj.t0
    same = []
    for k, it in enumerate(story.items):
        s2, h2 = _seg_or_shot(pa, it.ref)
        o2 = s2 or h2
        if o2 is not None and o2.asset_id == aid:
            same.append((k, o2.t0))
    pos = None
    if same:
        before = [k for k, tt in same if tt < t0]
        pos = (max(before) + 1) if before else min(k for k, _ in same)
    else:
        ca = pa.clips[aid]
        cl = (ca.day_index, ca.place_cluster)
        hits = []
        for k, it in enumerate(story.items):
            s2, h2 = _seg_or_shot(pa, it.ref)
            o2 = s2 or h2
            if o2 is not None and (pa.clips[o2.asset_id].day_index, pa.clips[o2.asset_id].place_cluster) == cl:
                hits.append(k)
        pos = (max(hits) + 1) if hits else max(1, len(story.items) - 1)
    if story.items and pos >= len(story.items) and story.items[-1].role in ("cta", "outro"):
        pos = len(story.items) - 1
    pos = max(1, min(pos, len(story.items))) if story.items else 0
    section = story.items[pos - 1].section if pos and story.items else "main"
    # the creator asked for this exact line back — keep it as spoken (even a lone "uh" can be a beat they want)
    story.items.insert(pos, StoryItem(ref=ref, role=role, section=section, note="kept by you", whole=seg is not None))


def apply_ops(ops: list[Op], story: StoryPlan, polish: PolishPlan, d: Direction, pa: ProjectAnalysis) -> tuple[StoryPlan, PolishPlan, Direction]:
    s, p, dd = story.model_copy(deep=True), polish.model_copy(deep=True), d.model_copy(deep=True)
    last_hook = max((k for k, o in enumerate(ops) if o.op == "hook"), default=None)   # the latest hook choice wins
    for k_op, o in enumerate(ops):
        if o.op == "hook" and k_op != last_hook:
            continue
        key = o.key or ""
        if o.op == "reject":
            if key.startswith("fx:"):
                p.effects = [c for c in p.effects if not _fx_match(c, key)]
            elif key.startswith("item:"):
                ref = key[5:]
                s.items = [it for it in s.items if it.ref != ref]
                p.effects = [c for c in p.effects if c.at not in (ref, f"before:{ref}")]
            elif key.startswith("seg:"):
                _insert_ref(s, pa, key[4:], "body")
            elif key.startswith("shot:"):
                _insert_ref(s, pa, key[5:], "broll")
            elif key.startswith("beat:"):
                k = _find(s, key[5:])
                if k is not None:
                    s.items[k].note = (s.items[k].note + " nobeat").strip()
            elif key.startswith("speaker:"):            # don't cut to the speaker here: keep who is on screen
                k = _find(s, key[8:])
                if k is not None:
                    s.items[k].note = (s.items[k].note + " nospeaker").strip()
            elif key.startswith("loop:"):
                ref = key.split(":", 1)[1]
                s.items = [it for it in s.items if not (it.ref == ref and it.role == "loop")]
            elif key.startswith("open_loop:"):
                ref = key.split(":", 1)[1]
                s.items = [it for it in s.items if not (it.ref == ref and it.role == "flashforward")]
                p.effects = [c for c in p.effects if not (c.type == "text" and c.intent == "open_loop" and c.at == ref)]
            elif key.startswith("whole:"):
                k = _find(s, key[6:])
                if k is not None:
                    s.items[k].whole = True
            elif key == "captions":
                dd.knobs.captions = "off"
            elif key.startswith("music:"):
                secs = set(key[6:].split(","))
                for c in p.music:
                    if c.section in secs:
                        c.mode, c.track_id = "none", None
        elif o.op == "accept":
            if key.startswith("fx:"):
                for c in p.effects:
                    if _fx_match(c, key):
                        c.confidence = max(c.confidence, 0.9)
        elif o.op == "add" and o.cue is not None:
            cue = o.cue.model_copy()
            cue.confidence, cue.intent = 1.0, "user"
            if cue.type == "speed":
                p.effects = [c for c in p.effects if not (c.type == "speed" and c.at == cue.at)]
            p.effects.append(cue)
        elif o.op == "drop" and o.ref:
            s.items = [it for it in s.items if it.ref != o.ref]
            p.effects = [c for c in p.effects if c.at not in (o.ref, f"before:{o.ref}")]
        elif o.op == "trim" and o.ref:
            k = _find(s, o.ref)
            _, shot = _seg_or_shot(pa, o.ref)
            if k is not None and shot is not None and isinstance(o.value, (int, float)):
                it = s.items[k]
                a = it.t0 if it.t0 is not None else shot.t0
                b = it.t1 if it.t1 is not None else min(shot.t1, a + 3.0)
                centre = shot.action_peaks[0] if shot.action_peaks and a <= shot.action_peaks[0] <= b else (a + b) / 2
                new = max(0.8, min(shot.t1 - shot.t0, (b - a) * float(o.value)))
                a2 = max(shot.t0, min(centre - new / 2, shot.t1 - new))
                it.t0, it.t1 = round(a2, 3), round(a2 + new, 3)
        elif o.op == "whole" and o.ref:
            k = _find(s, o.ref)
            if k is not None:
                s.items[k].whole = True
        elif o.op == "swap_track" and o.ref and isinstance(o.value, str):
            for c in p.music:
                if c.section in set(o.ref.split(",")):
                    if c.track_id and c.track_id not in c.alternatives:
                        c.alternatives.insert(0, c.track_id)
                    c.track_id = o.value
                    c.alternatives = [x for x in c.alternatives if x != o.value]
                    if c.mode == "none":
                        c.mode = "bed"
                    c.why = "your pick"
        elif o.op == "music_gain" and o.ref and isinstance(o.value, (int, float)):
            for c in p.music:
                if c.section in set(o.ref.split(",")):
                    c.gain_db = max(-12.0, min(6.0, c.gain_db + float(o.value)))
        elif o.op == "captions" and isinstance(o.value, str):
            dd.knobs.captions = o.value  # type: ignore[assignment]
        elif o.op == "hook" and isinstance(o.value, str):
            idx = next((k for k, x in enumerate(dd.hooks) if x.id == o.value), None)
            h = dd.hooks[idx] if idx is not None else None
            if h and h.refs and s.items:
                new, old_ref = h.refs[0], s.items[0].ref
                s.items = [it for k, it in enumerate(s.items) if k == 0 or it.ref != new]
                sec = s.items[0].section
                s.items[0] = StoryItem(ref=new, role="hook", section=sec, note=f"hook you picked: {h.kind}")
                old_seg, _ = _seg_or_shot(pa, old_ref)
                if old_seg is not None and old_ref != new and _find(s, old_ref) is None:
                    # the old hook line usually carries the video's promise: keep it, right after the new hook
                    s.items.insert(1, StoryItem(ref=old_ref, role="setup", section=sec, note="the old hook line keeps the promise"))
                dd.hooks = dd.hooks[idx:] + dd.hooks[:idx]      # rotate so "another hook" walks through every option
                if h.text_hook:
                    for c in p.effects:
                        if c.type == "text" and c.style == "hook":
                            c.text = h.text_hook
    return s, p, dd


# ------------------------------------------------------------------ comments → ops (rules)
NEG = r"\b(no|not|remove|delete|drop|cut|kill|lose|get rid of|without|don'?t|hata|hatao|hata do|nikal|nikalo|mat|band)\b"
TYPES = [
    ("zoom", r"\b(zoom|zooms|punch[\s-]?in)\b"),
    ("meme", r"\bmemes?\b"),
    ("sfx", r"\b(sfx|sound effects?|whoosh|swoosh|pop|ding|boom|riser|impact)\b"),
    ("captions", r"\b(captions?|subtitles?|subs)\b"),
    ("text", r"\b(text|title|card)\b"),
    ("transition", r"\b(transitions?|dissolve|whip)\b"),
    ("speed", r"\b(slow[\s-]?mo|slow motion|speed ramp)\b"),
    ("music", r"\b(music|song|track|gaana|bgm)\b"),
    ("broll", r"\b(b[\s-]?roll|overlay|cutaway)\b"),
    ("bleep", r"\b(bleep|beep)\b"),
]
SFX_NAMES = ("whoosh", "pop", "ding", "boom", "riser", "impact")


def _at(tl: Timeline, t: float, tracks=("A1",), roles_skip=("natural",)):
    for it in sorted(tl.items, key=lambda i: i.rec_in):
        if it.track in tracks and it.rec_in - 1e-3 <= t < it.rec_out and it.role not in roles_skip and it.ref:
            return it
    return None


def _word_near(tl: Timeline, t: float, within: float = 1.2) -> str | None:
    wt = tl.meta.get("word_t") or {}
    best = min(wt.items(), key=lambda kv: abs(kv[1] - t), default=None)
    return best[0] if best and abs(best[1] - t) <= within else None


def _near(tl: Timeline, typ: str, t: float, window: float = 3.0, status=("applied",)) -> Suggestion | None:
    c = [s for s in tl.suggestions if s.type == typ and s.payload.get("key") and s.status in status and s.t is not None and abs(s.t - t) <= window]
    return min(c, key=lambda s: abs((s.t or 0) - t)) if c else None


def _music_at(tl: Timeline, t: float) -> Suggestion | None:
    ms = [s for s in tl.suggestions if s.type == "music" and s.status == "applied" and s.payload.get("sections") and s.t is not None and s.t <= t + 0.5]
    return max(ms, key=lambda s: s.t or 0) if ms else None


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def interpret(text: str, t: float, tl: Timeline, pa: ProjectAnalysis, d: Direction, story: StoryPlan,
              rules: list | None = None) -> tuple[list[Op], str]:
    """One timeline comment → edit ops + a one-line reply. Empty ops = not understood."""
    rules = rules or []
    low = text.strip().lower()
    head = low.split(":", 1)[0]                    # "big text: no regrets" — only the instruction part counts
    neg = re.search(NEG, head) is not None
    typ = next((k for k, rx in TYPES if re.search(rx, head)), None)
    speech = _at(tl, t, ("A1",))
    pic = _at(tl, t, ("V1",), roles_skip=())
    seg_ref = speech.ref if speech else None
    shot_ref = pic.ref if pic and pic.ref and ".k" in pic.ref else None

    # big / small / plain text with the words after a colon (or quotes)
    m = re.match(r"^(?:add\s+)?(big|bold|large|huge|bada|badi|small|subtle|chhota|chhoti)?\s*(?:text|title|likho|likh do|caption)\s*[:\-–]\s*(.+)$", text.strip(), re.I)
    if m and not neg:
        size = (m.group(1) or "").lower()
        style = "big" if size in ("big", "bold", "large", "huge", "bada", "badi") else ("small" if size else "callout")
        words = m.group(2).strip().strip("\"“”'")
        anchor = _word_near(tl, t) or seg_ref or (pic.ref if pic else None)
        if not anchor:
            return [], "There is nothing to pin text to at this point."
        cue = EffectCue(type="text", at=anchor, text=words[:60], style=style, dur=2.2, why="your note")
        return [Op(op="add", cue=cue, why=text)], f"Added {style} text “{words[:40]}” at {_mmss(t)}."

    if neg and typ:
        if typ == "captions":
            return [Op(op="captions", value="off", why=text)], "Captions are off."
        if typ == "music":
            ms = _music_at(tl, t)
            if ms:
                secs = ",".join(ms.payload["sections"])
                return [Op(op="reject", key=f"music:{secs}", why=text)], f"Removed the music from {secs.replace(',', ', ')}."
            return [], "There is no music at this point."
        s = _near(tl, typ, t)
        if s:
            return [Op(op="reject", key=s.payload["key"], why=text)], f"Removed the {typ} at {_mmss(s.t or t)}."
        return [], f"No {typ} near {_mmss(t)} to remove."

    if re.search(r"\b(cut|remove|delete|drop|skip|hatao|nikalo|kaat|kaato|kato)\b", low) and not typ:
        ref = seg_ref or (pic.ref if pic else None)
        if ref and not ref.startswith("fx:"):
            seg, _ = _seg_or_shot(pa, ref)
            what = f"“{seg.text[:50]}”" if seg else "this shot"
            if story.items and story.items[0].ref == ref:
                return [], "That is the hook — pick another hook instead of cutting it (say “another hook”)."
            must = any(r.kind == "must_include" and r.target == ref for r in rules)
            return [Op(op="drop", ref=ref, why=text)], f"Cut {what}." + (" Note: your brief said to keep it." if must else "")
        if ref and ref.startswith("fx:"):
            return [Op(op="reject", key=ref, why=text)], "Removed it."
        return [], "Nothing to cut at this point."

    if re.search(r"\b(another|different|better|change|other|swap)\b.*\bhook\b|\bhook\b.*\b(another|different|better|change)\b", low):
        cur = story.items[0].ref if story.items else None
        alt = next((h for h in d.hooks if h.refs and h.refs[0] != cur), None)
        if alt:
            note = " Note: your brief chose the hook — delete this comment to go back." if any(r.kind == "hook" for r in rules) else ""
            return [Op(op="hook", value=alt.id, why=text)], (f"Switched the hook to {alt.kind.replace('_', ' ')}"
                                                             + (f" (“{alt.text_hook}”)" if alt.text_hook else "") + "." + note)
        return [], "There is no other hook option in this footage."

    if typ == "music":
        ms = _music_at(tl, t)
        secs = ",".join(ms.payload["sections"]) if ms else None
        if re.search(r"\b(change|swap|another|different|other|badlo|dusra|next)\b", low):
            if not ms:
                return [], "There is no music at this point."
            alts = [a for a in ms.alternatives if a != ms.payload.get("track")]
            if not alts:
                alts = [a.id for a in pa.assets if a.kind == AssetKind.MUSIC and a.id != ms.payload.get("track")]
            if not alts:
                return [], "Your music folder has no other track — add one and say “change song” again."
            name = pa.asset(alts[0]).name
            note = " Note: your brief picked the song here — delete this comment to go back." if any(r.kind == "use_music" for r in rules) else ""
            return [Op(op="swap_track", ref=secs, value=alts[0], why=text)], f"Swapped the song to {name}.{note}"
        up = re.search(r"\b(louder|up|more|increase|badhao|tez)\b", low)
        down = re.search(r"\b(quieter|lower|down|softer|less|decrease|kam|dheere)\b", low)
        if ms and (up or down):
            v = 3.0 if up else -3.0
            return [Op(op="music_gain", ref=secs, value=v, why=text)], f"Music {'+' if v > 0 else ''}{v:g} dB here."

    if re.search(r"\b(faster|too slow|speed (it )?up|tighter|tighten|drags?|dragging|boring|jaldi|tez)\b", low):
        if shot_ref and not (speech and speech.role != "natural"):
            return [Op(op="trim", ref=shot_ref, value=0.6, why=text)], "Shortened this shot by 40 %."
        return [], "This is talking — I won't speed up speech. Say “cut this” to drop the line, or comment on a B-roll shot."

    if re.search(r"\b(slower|too fast|breathe|let it breathe|hold|longer|ruk|ruko)\b", low) and shot_ref:
        return [Op(op="trim", ref=shot_ref, value=1.5, why=text)], "Held this shot 50 % longer."

    if typ == "speed" and shot_ref:
        cue = EffectCue(type="speed", at=shot_ref, value=0.5, why="your note: slow-mo")
        return [Op(op="add", cue=cue, why=text)], "Slow-mo on this shot."

    if typ == "zoom":
        w = _word_near(tl, t)
        if w:
            return [Op(op="add", cue=EffectCue(type="zoom", at=w, value=1.16, why="your note: punch-in"), why=text)], f"Punch-in at {_mmss(t)}."
        return [], "Punch-ins work on talking shots — there is no speech here."

    if typ == "sfx":
        name = next((n for n in SFX_NAMES if n in low), "pop")
        lib = next((a.id for a in pa.assets if a.kind == AssetKind.SFX and name in a.name.lower()), None)
        anchor = _word_near(tl, t)
        if not anchor:
            return [], "SFX are pinned to words for now — put the note on a spoken word."
        cue = EffectCue(type="sfx", at=anchor, asset=lib or f"sfx:{name}", why=f"your note: {name}")
        return [Op(op="add", cue=cue, why=text)], f"Added a {name} at {_mmss(t)}."

    if typ == "meme":
        if not seg_ref:
            return [], "Memes go right after a line — put the note on a spoken line."
        memes = [a for a in pa.assets if a.kind in (AssetKind.MEME_IMAGE, AssetKind.MEME_VIDEO)]
        used = {i.asset_id for i in tl.items if i.role == "meme"}
        pick = next((a for a in memes if any(w in a.name.lower() for w in re.findall(r"[a-z]{3,}", low)) and a.id not in used), None)
        pick = pick or next((a for a in memes if a.id not in used), None) or (memes[0] if memes else None)
        if pick:
            cue = EffectCue(type="meme", at=seg_ref, asset=pick.id, why="your note: meme here")
            return [Op(op="add", cue=cue, why=text)], f"Added the meme {pick.name} after this line."
        cat = next(iter(K.memes()), None)
        hint = f" Try “{cat.name}” (search: {cat.search[0]})." if cat else ""
        return [], "Your folder has no memes yet — add one to a memes/ folder." + hint

    if re.search(r"\b(keep (the )?(pause|um|uh)s?|natural|don'?t cut (the )?pauses?)\b", low) and seg_ref:
        return [Op(op="whole", ref=seg_ref, why=text)], "Kept this line exactly as spoken."

    return [], ("I couldn't turn this into an edit. Try: “remove zoom”, “big text: …”, “meme here”, “whoosh”, “faster”, "
                "“cut this”, “change song”, “music quieter”, “another hook”.")


# ------------------------------------------------------------------ recompile
def _paths(proj: Project, tl_id: str) -> dict[str, Path]:
    tdir = proj.sub("timelines")
    return {k: tdir / f"{tl_id}{suffix}" for k, suffix in
            (("tl", ".json"), ("base", ".base.json"), ("story", ".story.json"), ("polish", ".polish.json"), ("rev", ".revision.json"))}


def load_revision(root: str | Path, tl_id: str) -> Revision:
    p = _paths(Project(root), tl_id)["rev"]
    return Revision.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else Revision(timeline_id=tl_id)


def base_timeline(root: str | Path, tl_id: str) -> Timeline:
    ps = _paths(Project(root), tl_id)
    p = ps["base"] if ps["base"].exists() else ps["tl"]
    return Timeline.model_validate_json(p.read_text(encoding="utf-8"))


def recompile(root: str | Path, tl_id: str, rev: Revision | None = None, *, pa: ProjectAnalysis | None = None):
    """Replay the revision on the build's plans → (timeline, lint findings, rules critic). Saves timeline + revision."""
    from .engine import analysis
    from .lint.critic import rules_critic
    from .lint.editlint import lint_timeline
    from .schema.brief import CreatorBrief
    from .timeline.compiler import compile_timeline

    proj = Project(root)
    ps = _paths(proj, tl_id)
    if not ps["base"].exists():
        ps["base"].write_text(ps["tl"].read_text(encoding="utf-8"), encoding="utf-8")
    base = Timeline.model_validate_json(ps["base"].read_text(encoding="utf-8"))
    rev = rev or load_revision(root, tl_id)
    pa = pa or analysis(root)
    story = StoryPlan.model_validate_json(ps["story"].read_text(encoding="utf-8"))
    polish = PolishPlan.model_validate_json(ps["polish"].read_text(encoding="utf-8"))
    from .repurpose import find_direction

    d = find_direction(root, base.direction_id)
    if d is None:
        raise KeyError(f"direction {base.direction_id} not found for {tl_id}")
    brief = proj.load_model("brief.json", CreatorBrief) or CreatorBrief()
    s2, p2, d2 = apply_ops(rev.ops, story, polish, d, pa)
    tl = compile_timeline(pa, d2, s2, p2, brief, project_root=root)
    # show what the creator turned off, so it can be turned back on
    rejected = {o.key for o in rev.ops if o.op == "reject" and o.key}
    accepted = {o.key for o in rev.ops if o.op == "accept" and o.key}
    live = {s.payload.get("key") for s in tl.suggestions if s.payload.get("key")}
    n = len(tl.suggestions)
    for s in base.suggestions:
        k = s.payload.get("key")
        if k in rejected and (k not in live or k.startswith(("seg:", "shot:", "whole:"))):
            n += 1
            tl.suggestions.append(s.model_copy(update={"id": f"sg{n}", "status": "rejected", "source": "user"}))
    for s in tl.suggestions:
        if s.payload.get("key") in accepted and s.status == "applied":
            s.source = "user"
        if s.payload.get("key", "").startswith(("seg:", "shot:")) and s.payload["key"] in rejected and s.status != "rejected":
            s.status = "rejected"
    tl.meta["revision"] = {"ops": len(rev.ops), "comments": len(rev.comments)}
    findings = lint_timeline(tl, pa, d2, brief)
    critic = rules_critic(tl, pa, d2, findings)
    ps["tl"].write_text(tl.model_dump_json(indent=1), encoding="utf-8")
    ps["rev"].write_text(rev.model_dump_json(indent=1), encoding="utf-8")
    return tl, findings, critic


def toggle(root: str | Path, tl_id: str, key: str, status: Literal["applied", "rejected"]) -> Revision:
    """Accept/reject one suggestion by its key; toggling back removes the op (undo)."""
    rev = load_revision(root, tl_id)
    base = base_timeline(root, tl_id)
    orig = next((s for s in base.suggestions if s.payload.get("key") == key), None)
    rev.ops = [o for o in rev.ops if not (o.key == key and o.op in ("reject", "accept"))]
    was_applied = orig is None or orig.status == "applied"
    if status == "rejected" and was_applied:
        rev.ops.append(Op(op="reject", key=key))
    elif status == "applied" and not was_applied:
        if orig is not None and orig.payload.get("acceptable") is False:
            raise ValueError("this idea needs a file you don't have yet — see its search terms")
        rev.ops.append(Op(op="accept", key=key))
    return rev


def add_comment(root: str | Path, tl_id: str, t: float, text: str, *, brain=None) -> tuple[Revision, Comment]:
    """Interpret a timeline comment (rules first, then the AI 'revise' pass if one is connected)."""
    from .engine import analysis

    proj = Project(root)
    ps = _paths(proj, tl_id)
    rev = load_revision(root, tl_id)
    tl = Timeline.model_validate_json(ps["tl"].read_text(encoding="utf-8"))
    pa = analysis(root)
    from .repurpose import find_direction

    d = find_direction(root, tl.direction_id)
    if d is None:
        raise KeyError(f"direction {tl.direction_id} not found")
    story = StoryPlan.model_validate_json(ps["story"].read_text(encoding="utf-8"))
    story, _, d = apply_ops(rev.ops, story, PolishPlan.model_validate_json(ps["polish"].read_text(encoding="utf-8")), d, pa)
    from .schema.brief import CreatorBrief

    brief = proj.load_model("brief.json", CreatorBrief) or CreatorBrief()
    cid = f"c{max([int(c.id[1:]) for c in rev.comments if c.id[1:].isdigit()] + [0]) + 1}"
    ops, reply = interpret(text, t, tl, pa, d, story, brief.rules)
    source = "rules"
    if not ops and brain is not None and hasattr(brain, "revise"):
        ai_ops, ai_reply = brain.revise(text, t, tl, pa)
        if ai_ops:
            ops, reply, source = ai_ops, ai_reply, "ai"
    for o in ops:
        o.comment_id = cid
    rev.ops += ops
    c = Comment(id=cid, t=round(t, 2), text=text, status="applied" if ops else "not_understood", reply=reply, source=source)
    rev.comments.append(c)
    return rev, c


def remove_comment(root: str | Path, tl_id: str, comment_id: str) -> Revision:
    rev = load_revision(root, tl_id)
    rev.ops = [o for o in rev.ops if o.comment_id != comment_id]
    rev.comments = [c for c in rev.comments if c.id != comment_id]
    return rev
