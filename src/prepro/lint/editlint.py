"""EditLint — the anti-irritation quality gate. Deterministic checks over a compiled Timeline (and the
rendered mix), each with a severity, a timeline position and (when safe) a plan-level fix."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel

from .. import knowledge as K
from ..schema.analysis import ProjectAnalysis
from ..schema.brief import ComplianceItem, CreatorBrief
from ..schema.media import AssetKind
from ..schema.plan import Direction, FixOp, PolishPlan, StoryPlan
from ..schema.timeline import Timeline


class Finding(BaseModel):
    rule: str
    severity: str            # error|warn|info
    msg: str
    t: float | None = None
    fix: FixOp | None = None


def _speech_items(tl: Timeline):
    return [i for i in tl.items if i.track == "A1" and i.role not in ("natural",)]


def lint_timeline(tl: Timeline, pa: ProjectAnalysis, d: Direction, brief: CreatorBrief | None = None) -> list[Finding]:
    pb = K.playbook(d.playbook)
    out: list[Finding] = []
    v1 = sorted((i for i in tl.items if i.track == "V1"), key=lambda i: i.rec_in)
    dur = max(tl.duration, 1e-6)
    minutes = max(0.5, dur / 60)
    # mid-word cuts
    for it in _speech_items(tl):
        for w in pa.words(it.asset_id):
            if w.text.startswith("[") or w.filler:
                continue
            if w.t0 + 0.03 < it.src_in < w.t1 - 0.03 or w.t0 + 0.03 < it.src_out < w.t1 - 0.03:
                out.append(Finding(rule="midword", severity="error", msg=f"cut inside the word “{w.text}”", t=it.rec_in))
                break
    # micro shots / monotone rhythm
    fast = d.playbook in ("hype_reel", "teaser")
    for it in v1:
        if it.rec_dur < (0.3 if fast else 0.45) and it.role not in ("meme",):
            out.append(Finding(rule="microshot", severity="warn", msg=f"{it.rec_dur:.2f}s shot is too short to read", t=it.rec_in))
    run = 1
    for a, b in zip(v1, v1[1:], strict=False):
        if a.role == b.role == "montage" and abs(a.rec_dur - b.rec_dur) <= 0.08 * max(a.rec_dur, b.rec_dur) and not fast:
            run += 1
            if run == 5:
                out.append(Finding(rule="monotone", severity="info", msg="5+ montage shots with identical length — vary the rhythm", t=b.rec_in))
        else:
            run = 1
    # shot grammar: two B-roll shots of the same size from the same clip back to back read as one shot, stuttering
    def size(it):
        if not it.asset_id or it.asset_id not in pa.clips:
            return None
        sh = next((x for x in pa.clips[it.asset_id].shots if x.t0 - 1e-3 <= (it.src_in + it.src_out) / 2 <= x.t1 + 1e-3), None)
        if sh is None:
            return None
        faces = [f for f in sh.faces if it.src_in - 0.5 <= f.t <= it.src_out + 0.5]
        if faces:
            h = max(f.h for f in faces)
            return "close" if h >= 0.33 else ("medium" if h >= 0.15 else "wide")
        return sh.shot_type
    broll_v1 = [i for i in v1 if i.kind == "video" and i.asset_id and pa.asset(i.asset_id).kind == AssetKind.BROLL and i.role != "meme"]
    for a, b in zip(broll_v1, broll_v1[1:], strict=False):
        if abs(a.rec_out - b.rec_in) < 0.05 and a.asset_id == b.asset_id and size(a) and size(a) == size(b) and b.role not in ("loop",):
            out.append(Finding(rule="samesize", severity="info", msg=f"two {size(a)} shots of the same scene back to back — vary the framing",
                               t=b.rec_in))
    # open loops must be paid off later in the same cut
    for ff in (i for i in v1 if i.role == "flashforward"):
        if not any(i.ref == ff.ref and i.rec_in > ff.rec_out and i.role != "flashforward" for i in v1):
            out.append(Finding(rule="open_loop_unpaid", severity="error", msg="a flash-forward promises a moment the cut never shows", t=ff.rec_in,
                               fix=FixOp(op="drop_effect", target=f"open_loop:{ff.ref}", why="never promise what the video doesn't pay off")))
    # dead zones (no visual change)
    events = sorted({0.0, dur} | {i.rec_in for i in tl.items if i.track in ("V1", "V2", "V3", "T1")} |
                    {i.rec_out for i in tl.items if i.track in ("V2", "V3", "T1")})
    for a, b in zip(events, events[1:], strict=False):
        # slow push-ins and pans count as change
        moving = any(i.transform and (any(k.zoom > 1.01 for k in i.transform.keys) or len({(k.cx, k.cy) for k in i.transform.keys}) > 1)
                     and i.rec_in <= a < i.rec_out for i in v1)
        for i in v1:                       # the picture itself changes: gameplay, pans, action — not dead air
            if i.asset_id and i.rec_in <= (a + b) / 2 < i.rec_out and i.asset_id in pa.clips:
                sh = next((x for x in pa.clips[i.asset_id].shots if x.t0 - 1e-3 <= i.src_in <= x.t1), None)
                if sh is not None and (sh.motion > 0.15 or pa.asset(i.asset_id).kind == AssetKind.SCREEN or sh.camera_move not in ("static", "")):
                    moving = True
        if b - a > pb.pacing.dead_zone and not moving:
            mid = (a + b) / 2
            on = next((i for i in v1 if i.rec_in <= mid < i.rec_out and i.ref), None)
            fix = FixOp(op="add_effect", target=on.ref, arg={"kind": "deadzone", "t0": round(a, 2), "t1": round(b, 2)},
                        why="break a dull stretch") if on is not None and d.playbook != "aesthetic" else None
            out.append(Finding(rule="deadzone", severity="warn", msg=f"{b - a:.1f}s with no visual change (limit {pb.pacing.dead_zone:.0f}s) — add a B-roll cutaway or punch-in",
                               t=a, fix=fix))
    # effect density vs budget
    counts = defaultdict(int)
    for i in v1:
        if i.transform and i.transform.zoom > 1.01 and i.note not in ("reframe", "kenburns"):   # reframes and a photo's own slow move are not effects
            counts["zoom"] += 1
        if i.transition_in != "cut":
            counts["transition"] += 1
        if i.role == "meme":
            counts["meme"] += 1
    counts["sfx"] = sum(1 for i in tl.items if i.track == "A3" and not i.note.endswith("bleep"))
    counts["text"] = sum(1 for i in tl.items if i.track == "T1")
    mult = 1.4 if d.knobs.effects == "bold" else 0.7 if d.knobs.effects == "clean" else 1.0
    for kind, n in counts.items():
        budget = pb.budget(kind) * minutes * mult
        if kind == "meme" and n and budget < 1:
            budget = 1
        if n > np.ceil(budget) + (1 if kind in ("text", "sfx") else 0):
            out.append(Finding(rule="overstim", severity="warn", msg=f"{n} {kind} effects in {dur:.0f}s (budget ≈ {budget:.1f}) — feels over-edited",
                               fix=FixOp(op="lower_density", target=kind, arg={"keep": int(np.ceil(budget))}, why="restraint budget")))
    # repeats
    last: dict[str, float] = {}
    for i in sorted((x for x in tl.items if x.track in ("A3",)), key=lambda x: x.rec_in):
        key = i.asset_id or i.note
        if key in last and i.rec_in - last[key] < 12:
            out.append(Finding(rule="repeat", severity="warn", msg=f"same sound effect twice within {i.rec_in - last[key]:.1f}s", t=i.rec_in,
                               fix=FixOp(op="drop_effect", target=f"sfx@{i.rec_in:.2f}", why="no back-to-back repeats")))
        last[key] = i.rec_in
    memes = [i for i in v1 if i.role == "meme"]
    seen = set()
    for m in memes:
        if m.asset_id in seen:
            out.append(Finding(rule="repeat", severity="warn", msg="same meme used twice", t=m.rec_in))
        seen.add(m.asset_id)
    # jump cuts without a framing change
    for a, b in zip(v1, v1[1:], strict=False):
        if a.asset_id == b.asset_id and a.kind == b.kind == "video" and b.src_in > a.src_out + 0.05 and b.transition_in == "cut":
            za = a.transform.zoom if a.transform else 1.0
            zb = b.transform.zoom if b.transform else 1.0
            covered = any(o.track == "V2" and o.rec_in <= b.rec_in <= o.rec_out for o in tl.items)
            if abs(za - zb) < 0.03 and not covered:
                out.append(Finding(rule="jumpcut", severity="info", msg="jump cut with identical framing — punch in or cover with B-roll", t=b.rec_in))
    # captions
    max_cps = float(pb.captions.get("max_cps", 18))
    vertical = tl.height > tl.width
    for c in tl.captions:
        chars = sum(len(w.text) + 1 for w in c.words)
        if chars > (28 if vertical else 46):
            out.append(Finding(rule="caption", severity="warn", msg=f"caption too long ({chars} chars)", t=c.t0))
        if c.t1 - c.t0 > 0 and chars / (c.t1 - c.t0) > max_cps * 1.6:
            out.append(Finding(rule="caption", severity="info", msg="caption flashes by faster than people can read", t=c.t0))
        if sum(1 for w in c.words if w.emph) > 1:
            out.append(Finding(rule="caption", severity="info", msg="more than one highlighted word in a caption", t=c.t0))
    # bad shots kept
    must = {r.target for r in (brief.rules if brief else []) if r.kind == "must_include"}
    for i in tl.items:
        if i.track in ("V1", "V2") and i.kind == "video" and i.asset_id:
            a = pa.asset(i.asset_id)
            if a.kind != AssetKind.BROLL:
                continue
            for s in pa.clips[a.id].shots:
                if s.t0 <= i.src_in < s.t1 and set(s.flags) & {"dark", "blurry", "shaky", "pocket"} and s.id not in must and a.id not in must:
                    out.append(Finding(rule="quality", severity="error", msg=f"{a.name} is {', '.join(s.flags)}", t=i.rec_in,
                                       fix=FixOp(op="drop_item", target=s.id, why="technically bad shot")))
    # colour jumps
    for a, b in zip(v1, v1[1:], strict=False):
        if a.asset_id == b.asset_id or a.section != b.section or a.kind != "video" or b.kind != "video":
            continue
        ca, cb = _shot_color(pa, a), _shot_color(pa, b)
        if ca is not None and cb is not None and float(np.linalg.norm(np.array(ca) - np.array(cb))) > 0.35:
            out.append(Finding(rule="colorjump", severity="info", msg="big colour/exposure jump between neighbouring shots — consider matching", t=b.rec_in))
    # slow start
    sp = sorted(_speech_items(tl), key=lambda i: i.rec_in)
    if v1 and sp and v1[0].role in ("hook", "setup", "body") and sp[0].rec_in > (0.6 if vertical else 1.2):
        out.append(Finding(rule="slowstart", severity="warn", msg=f"first word only at {sp[0].rec_in:.1f}s", t=0.0))
    # duration
    tgt = d.knobs.target_length
    if tgt and (dur < tgt * 0.6 or dur > tgt * 1.35):
        out.append(Finding(rule="duration", severity="info", msg=f"{dur:.0f}s vs target {tgt:.0f}s" + (" — not enough strong material (never padded)" if dur < tgt else "")))
    # brief compliance
    for ci in compliance(tl, pa, d, brief):
        if not ci.ok:
            out.append(Finding(rule="brief", severity="error", msg=f"brief not met: {ci.rule.source.strip() or ci.rule.kind} — {ci.detail}"))
    return out


def _shot_color(pa, it):
    for s in pa.clips[it.asset_id].shots:
        if s.t0 <= it.src_in < s.t1 + 0.01:
            return s.color
    return None


def compliance(tl: Timeline, pa: ProjectAnalysis, d: Direction, brief: CreatorBrief | None) -> list[ComplianceItem]:
    if not brief:
        return []
    out = []
    v = [i for i in tl.items if i.track.startswith("V")]
    refs_assets = {i.asset_id for i in tl.items if i.asset_id}

    def shot_used(sid: str) -> bool:
        try:
            s = pa.shot(sid)
        except KeyError:
            return False
        return any(i.asset_id == s.asset_id and i.src_in < s.t1 and i.src_out > s.t0 for i in v)

    def seg_used(sid: str) -> bool:
        try:
            s = pa.segment(sid)
        except KeyError:
            return False
        return any(i.asset_id == s.asset_id and i.track == "A1" and i.src_in < s.t1 - 0.1 and i.src_out > s.t0 + 0.1 for i in tl.items)

    speech = [(i.rec_in, i.rec_out) for i in _speech_items(tl)]
    for r in brief.rules:
        ok, detail = True, ""
        if not r.resolved and r.kind in ("hook", "must_include", "must_exclude", "speed", "add_meme", "use_music"):
            out.append(ComplianceItem(rule=r, ok=False, detail="could not find what you meant — answer the open question"))
            continue
        if r.kind == "hook":
            first = sorted((i for i in tl.items if i.track in ("V1", "A1")), key=lambda i: i.rec_in)[:2]
            try:
                seg = pa.segment(r.target)
                ok = any(i.asset_id == seg.asset_id and seg.t0 - 0.6 <= i.src_in < seg.t1 for i in first)
            except KeyError:
                ok = shot_used(r.target) and bool(first)
            detail = "" if ok else "the hook is not at the start"
        elif r.kind == "must_exclude":
            ok = not (shot_used(r.target) or seg_used(r.target) or r.target in refs_assets)
            detail = "" if ok else "excluded material is still in the cut"
        elif r.kind == "must_include":
            ok = shot_used(r.target) or seg_used(r.target) or r.target in refs_assets
            detail = "" if ok else "required material is missing"
        elif r.kind == "use_music":
            ok = any(i.track == "A2" and i.asset_id == r.arg.get("asset") for i in tl.items)
            detail = "" if ok else "requested track not used"
        elif r.kind == "no_music_under_speech":
            bad = 0.0
            for m in (i for i in tl.items if i.track == "A2"):
                for s0, s1 in speech:
                    a0, a1 = max(m.rec_in, s0), min(m.rec_out, s1)
                    if a1 - a0 <= 0.1:
                        continue
                    ts = np.linspace(a0, a1, 8)
                    if m.envelope:
                        lv = np.interp(ts, [e[0] for e in m.envelope], [e[1] for e in m.envelope]) + m.gain_db
                    else:
                        lv = np.full(len(ts), m.gain_db)
                    bad += float((lv > -50).mean()) * (a1 - a0)
            ok = bad < 0.6
            detail = "" if ok else f"music plays under {bad:.1f}s of talking"
        elif r.kind == "add_text":
            ok = any(i.kind == "text" and r.target.lower()[:12] in (i.text or "").lower() for i in tl.items)
        elif r.kind == "text_line":                       # your own words, on screen word for word
            want = " ".join(r.target.split()).lower()
            ok = any(i.kind == "text" and " ".join((i.text or "").split()).lower() == want for i in tl.items)
            detail = "" if ok else "this line of yours is not on screen as written"
        elif r.kind == "add_meme":
            ok = any(i.role == "meme" for i in v) or any(s.type == "meme" for s in tl.suggestions)
        elif r.kind == "add_sfx":
            ok = any(i.track == "A3" for i in tl.items)
        elif r.kind == "no_effect":
            t = r.target
            if t == "zoom":
                ok = not any(i.transform and (i.transform.zoom > 1.01 or any(k.zoom > 1.01 for k in i.transform.keys)) for i in v)
            elif t == "sfx":
                ok = not any(i.track == "A3" and not i.note.endswith("bleep") for i in tl.items)
            elif t == "meme":
                ok = not any(i.role == "meme" for i in v)
            elif t == "transition":
                ok = not any(i.transition_in != "cut" for i in v)
            elif t == "music":
                ok = not any(i.track == "A2" for i in tl.items)
            detail = "" if ok else f"{t} still present"
        elif r.kind == "speed":
            try:
                s = pa.shot(r.target)
                its = [i for i in v if i.asset_id == s.asset_id]
                ok = any(abs(i.speed - float(r.value or 1)) < 0.05 for i in its) if its else True
                detail = "" if ok else f"speed {r.value}x not applied" if its else ""
            except KeyError:
                ok = False
        elif r.kind in ("max_length", "min_length") and isinstance(r.value, (int, float)):
            ok = tl.duration <= r.value + 0.5 if r.kind == "max_length" else tl.duration >= r.value - 0.5
            detail = f"duration {tl.duration:.1f}s"
        elif r.kind == "captions" and r.value == "off":
            ok = not tl.captions
        out.append(ComplianceItem(rule=r, ok=ok, detail=detail))
    return out


def lint_render(res, d: Direction) -> list[Finding]:
    out = []
    if res.lufs is not None and abs(res.lufs - (-14.0)) > 1.0:
        out.append(Finding(rule="loudness", severity="warn", msg=f"integrated loudness {res.lufs:.1f} LUFS (target −14)"))
    if res.true_peak_db is not None and res.true_peak_db > -0.8:
        out.append(Finding(rule="loudness", severity="warn", msg=f"true peak {res.true_peak_db:.1f} dBTP (limit −1)"))
    if res.speech_to_music_db is not None and res.speech_to_music_db < 12:
        out.append(Finding(rule="ducking", severity="warn", msg=f"music only {res.speech_to_music_db:.0f} dB under the voice (want ≥ 12)"))
    return out


def apply_fixes(findings: list[Finding], polish: PolishPlan, story: StoryPlan, pa: ProjectAnalysis, d: Direction) -> tuple[PolishPlan, StoryPlan]:
    p = polish.model_copy(deep=True)
    s = story.model_copy(deep=True)
    for f in findings:
        if not f.fix:
            continue
        op = f.fix
        if op.op == "lower_density":
            keep = int(op.arg.get("keep", 0))
            kind = op.target
            typ = {"zoom": "zoom", "sfx": "sfx", "meme": "meme", "transition": "transition", "text": "text"}.get(kind)
            if not typ:
                continue
            cues = [c for c in p.effects if c.type == typ]
            # never drop brief-forced cues (confidence 1.0); drop lowest confidence first
            cues.sort(key=lambda c: c.confidence)
            drop = len(cues) - keep
            removed = 0
            for c in cues:
                if removed >= drop:
                    break
                if c.confidence >= 1.0:
                    continue
                p.effects.remove(c)
                removed += 1
        elif op.op == "drop_item":
            s.items = [it for it in s.items if it.ref != op.target]
            p.effects = [c for c in p.effects if c.asset != op.target]
        elif op.op == "drop_effect" and ":" in op.target and not op.target.startswith("sfx@"):
            typ, at = op.target.split(":", 1)
            p.effects = [c for c in p.effects if not (c.confidence < 1.0 and c.type == typ and (c.at == at or c.asset == at))]
        elif op.op == "add_effect" and op.arg.get("kind") == "deadzone":
            _fix_deadzone(op.target, p, s, pa)
        elif op.op == "drop_effect" and op.target.startswith("open_loop:"):
            ref = op.target.split(":", 1)[1]
            s.items = [it for it in s.items if not (it.ref == ref and it.role == "flashforward")]
            p.effects = [c for c in p.effects if not (c.type == "text" and c.intent == "open_loop" and c.at == ref)]
        elif op.op == "drop_effect" and op.target.startswith("sfx@"):
            # drop the later of two identical sfx: lower its confidence below the apply threshold
            t = float(op.target.split("@", 1)[1])
            _ = t
            sfx = [c for c in p.effects if c.type == "sfx" and c.confidence < 1.0]
            if len(sfx) > 1:
                p.effects.remove(sfx[-1])
    return p, s


def _fix_deadzone(ref: str, p: PolishPlan, s: StoryPlan, pa: ProjectAnalysis) -> None:
    """Cheapest honest fix for a dull stretch: a same-place B-roll cutaway over talking, else a punch-in on its
    strongest word; wordless B-roll gets a gentle speed-up. Never on purpose-slow moments (handled by the caller)."""
    from ..schema.media import AssetKind
    from ..schema.plan import EffectCue

    seg = next((x for x in pa.all_segments() if x.id == ref), None)
    if seg is not None:
        used = {it.ref for it in s.items} | {c.asset for c in p.effects if c.type == "broll" and c.asset}
        ca = pa.clips[seg.asset_id]
        same = [sh for a in pa.assets if a.kind == AssetKind.BROLL and (pa.clips[a.id].day_index, pa.clips[a.id].place_cluster) ==
                (ca.day_index, ca.place_cluster) for sh in pa.clips[a.id].shots
                if sh.id not in used and not set(sh.flags) & {"dark", "blurry", "shaky", "pocket"} and sh.dur >= 1.5]
        if same and not any(c.type == "broll" and c.at == seg.id for c in p.effects):
            sh = max(same, key=lambda x: x.quality)
            p.effects.append(EffectCue(type="broll", at=seg.id, asset=sh.id, dur=round(min(3.0, sh.dur), 2), confidence=0.7,
                                       why="break a dull stretch: show what you're talking about"))
            return
        words = [w for w in pa.words(seg.asset_id) if w.id in seg.word_ids and not w.filler and w.t0 >= seg.t0 + 1.0]
        if words and not any(c.type == "zoom" and c.at in seg.word_ids for c in p.effects):
            w = max(words, key=lambda w: (w.emphasis, len(w.text)))
            p.effects.append(EffectCue(type="zoom", at=w.id, value=1.14, confidence=0.7, why=f"break a dull stretch: punch in on “{w.text}”"))
        return
    shot = next((x for x in pa.all_shots() if x.id == ref), None)
    wordless = shot is not None and pa.asset(shot.asset_id).kind == AssetKind.BROLL and not any(
        shot.t0 <= w.t0 <= shot.t1 for w in pa.words(shot.asset_id))
    if wordless and not any(c.type == "speed" and c.at == ref for c in p.effects):
        p.effects.append(EffectCue(type="speed", at=ref, value=1.5, confidence=0.65, why="break a dull stretch: speed up a long wordless shot"))
