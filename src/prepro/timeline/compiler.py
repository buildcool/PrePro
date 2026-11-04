"""Compile a StoryPlan + PolishPlan into a frame-exact :class:`Timeline`.

The brain decides *what* and *why* using IDs; the compiler decides *exactly where*: it tightens speech
(fillers/pauses out), snaps every cut to a low-energy point (never mid-word), alternates framing on jump
cuts, reframes for the output aspect, places B-roll/memes/text/SFX, lays music (drop alignment or
backtiming) with a ducking envelope, builds captions, and records a Suggestion for every decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import knowledge as K
from ..assist.music import best_offset
from ..project import Project
from ..schema.analysis import ProjectAnalysis, Segment, Shot, Word
from ..schema.brief import CreatorBrief
from ..schema.media import AssetKind
from ..schema.plan import Direction, EffectCue, PolishPlan, StoryItem, StoryPlan
from ..schema.timeline import (
    CaptionWord,
    Item,
    Marker,
    MusicSpan,
    Suggestion,
    Timeline,
    Transform,
    TransformKey,
)
from .captions import build_captions

SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
TRANS_DUR = {"whip": 0.3, "dissolve": 0.5, "zoom": 0.35, "fade_black": 0.45, "slide": 0.35}


@dataclass
class Ctx:
    pa: ProjectAnalysis
    proj: Project | None
    d: Direction
    story: StoryPlan
    polish: PolishPlan
    brief: CreatorBrief
    W: int
    H: int
    fps: float
    items: list[Item] = field(default_factory=list)
    sugg: list[Suggestion] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    spans: dict[str, list[tuple[float, float]]] = field(default_factory=dict)      # ref → timeline spans
    word_t: dict[str, float] = field(default_factory=dict)                         # word id → timeline time
    caption_words: list[CaptionWord] = field(default_factory=list)
    section_t: dict[str, list[float]] = field(default_factory=dict)
    speech_spans: list[tuple[float, float]] = field(default_factory=list)
    n_items: int = 0
    n_sugg: int = 0
    env_cache: dict[str, np.ndarray] = field(default_factory=dict)

    def iid(self, p: str) -> str:
        self.n_items += 1
        return f"{p}{self.n_items}"

    def suggest(self, type_: str, reason: str, *, source="rules", conf=0.8, t=None, items=None, payload=None, status=None, alts=None) -> Suggestion:
        self.n_sugg += 1
        st = status or ("applied" if conf >= 0.5 else "optional")
        s = Suggestion(id=f"sg{self.n_sugg}", type=type_, status=st, confidence=round(conf, 2), reason=reason, source=source,
                       t=None if t is None else round(t, 3), item_ids=items or [], payload=payload or {}, alternatives=alts or [])
        self.sugg.append(s)
        if t is not None:
            self.markers.append(Marker(t=round(t, 3), name=type_, note=reason[:140], color="green" if st == "applied" else "yellow", suggestion_id=s.id))
        return s


# ------------------------------------------------------------------ audio envelopes for snapping
def _envelope(ctx: Ctx, asset_id: str) -> np.ndarray | None:
    if asset_id in ctx.env_cache:
        return ctx.env_cache[asset_id]
    env = None
    if ctx.proj is not None:
        wav = ctx.proj.cache / "audio" / f"{asset_id}.wav"
        if wav.exists():
            import soundfile as sf

            y, sr = sf.read(str(wav), dtype="float32")
            if y.ndim > 1:
                y = y.mean(axis=1)
            hop = sr // 100
            fr = y[: len(y) // hop * hop].reshape(-1, hop)
            env = np.sqrt((fr**2).mean(axis=1)) + 1e-9
    ctx.env_cache[asset_id] = env
    return env


def snap(ctx: Ctx, asset_id: str, t: float, lo: float, hi: float) -> float:
    """Move a cut to the quietest 10 ms frame in [lo, hi] (never inside a kept word)."""
    env = _envelope(ctx, asset_id)
    if env is None or hi - lo < 0.02:
        return t
    a, b = max(0, int(lo * 100)), min(len(env), int(hi * 100))
    if b <= a:
        return t
    seg = env[a:b]
    # prefer the quietest point, tie-break toward the requested time
    idx = np.arange(a, b)
    cost = 20 * np.log10(seg) + np.abs(idx / 100 - t) * 6
    return float(idx[int(np.argmin(cost))] / 100)


# ------------------------------------------------------------------ speech pieces
def speech_pieces(ctx: Ctx, seg: Segment, *, tightness: float, breath: float, max_pause: float,
                  whole: bool = False) -> tuple[list[tuple[float, float]], list[Word], int]:
    words = {w.id: w for w in ctx.pa.words(seg.asset_id)}
    seq = [words[w] for w in seg.word_ids if w in words]
    all_words = sorted(ctx.pa.words(seg.asset_id), key=lambda w: w.t0)
    if whole:
        tightness, max_pause = 0.0, 1e9
    kept = list(seq) if whole else [w for w in seq if not w.filler and not w.text.startswith("[")]
    removed = len(seq) - len(kept)
    if not kept:
        return [], [], removed
    runs: list[list[Word]] = [[kept[0]]]
    for prev, w in zip(kept, kept[1:], strict=False):
        between = [x for x in seq if prev.t1 <= x.t0 < w.t0 and (x.filler or x.text.startswith("["))]
        if (w.t0 - prev.t1) > max_pause or (between and tightness >= 0.3):
            runs.append([w])
        else:
            runs[-1].append(w)
    pieces = []
    for run in runs:
        a, b = run[0].t0, run[-1].t1
        prev_word = next((x for x in reversed(all_words) if x.t1 <= a - 0.01), None)
        next_word = next((x for x in all_words if x.t0 >= b + 0.01), None)
        lo_a = max(prev_word.t1 if prev_word else 0.0, a - breath - 0.12)
        hi_b = min(next_word.t0 if next_word else b + 1.0, b + breath + 0.15)
        a2 = snap(ctx, seg.asset_id, max(lo_a, a - breath), lo_a, a - 0.02)
        b2 = snap(ctx, seg.asset_id, min(hi_b, b + breath), b + 0.04, hi_b)
        pieces.append((round(max(0.0, a2), 3), round(b2, 3)))
    merged: list[tuple[float, float]] = []
    for p in pieces:
        if merged and p[0] - merged[-1][1] < 0.08:
            merged[-1] = (merged[-1][0], p[1])
        else:
            merged.append(p)
    return merged, kept, removed


NUMWORD = re.compile(r"\d|₹|\$|%|\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|fifty|hundred|thousand|lakh|crore|"
                     r"only|never|best|worst|secret|mistake|unreal|insane)\b", re.I)


def tighten_hook(ctx: Ctx, seg: Segment, pieces, kept):
    """Enter late: when the payload of a long hook line comes after 1.5 s, start at the clause that carries it."""
    if not kept or (kept[-1].t1 - kept[0].t0) < 3.5:
        return pieces, kept, ""
    first = next((i for i, w in enumerate(kept) if NUMWORD.search(w.text)), None)
    if first is None or kept[first].t0 - kept[0].t0 < 1.5:
        return pieces, kept, ""
    start = first
    for j in range(first, 0, -1):   # walk back to the clause start (after punctuation / before a conjunction)
        prev = kept[j - 1].text
        if re.search(r"[,.;:!?]$", prev) or re.sub(r"[^\w]", "", kept[j].text.lower()) in ("and", "but", "so", "because"):
            start = j + (1 if re.sub(r"[^\w]", "", kept[j].text.lower()) in ("and", "but", "so") else 0)
            break
        start = j - 1
    if start == 0 or kept[-1].t1 - kept[start].t0 < 2.0:
        return pieces, kept, ""
    t_new = kept[start].t0
    lo, hi = (kept[start - 1].t1 if start else t_new - 0.2), t_new - 0.02
    a_new = snap(ctx, seg.asset_id, t_new - 0.08, lo, hi) if hi - lo > 0.03 else max(lo, t_new - 0.03)
    a_new = min(max(a_new, lo), t_new)
    out = [(max(a, a_new), b) for a, b in pieces if b > a_new + 0.1]
    return out, kept[start:], " ".join(w.text for w in kept[start:start + 5])


# ------------------------------------------------------------------ framing
def reframe_path(pts: list[tuple[float, float, float]], t0: float, t1: float, crop_w: float) -> list[tuple[float, float]]:
    """Camera-operator reframing: hold steady; re-centre smoothly only when the subject nears the crop edge.
    Returns [(item_time, cx)] keys."""
    pts = sorted(p for p in pts if t0 - 0.3 <= p[0] <= t1 + 0.3)
    if not pts:
        return []
    first = [p[1] for p in pts if p[0] <= t0 + 1.0] or [pts[0][1]]
    c = float(np.median(first))
    zone = crop_w * 0.22
    keys = [(0.0, c)]
    for t, x, _y in pts:
        if abs(x - c) > zone:
            tt = max(0.0, t - t0)
            target = x - np.sign(x - c) * zone * 0.4
            if tt - keys[-1][0] > 0.05:
                keys.append((tt, c))            # hold until the move starts
            c = float(target)
            keys.append((min(t1 - t0, tt + 0.7), c))  # ease to the new framing over 0.7 s
    keys.append((t1 - t0, c))
    out: list[tuple[float, float]] = []
    for k in keys:
        if out and k[0] - out[-1][0] < 0.04:
            out[-1] = (out[-1][0], k[1])
        else:
            out.append((round(k[0], 3), round(k[1], 4)))
    return out


def frame_for(ctx: Ctx, asset_id: str, src_t0: float, src_t1: float) -> Transform:
    """Crop centre for the output aspect: follow the main face / moving subject like a camera operator."""
    a = ctx.pa.asset(asset_id)
    ds = a.info.display_size or (ctx.W, ctx.H)
    src_ar, out_ar = ds[0] / ds[1], ctx.W / ctx.H
    tf = Transform()
    if abs(src_ar - out_ar) < 0.02:
        return tf
    pts = [p for s in ctx.pa.clips[asset_id].shots for p in s.track]
    if not pts:
        return tf
    win = [p for p in pts if src_t0 - 0.6 <= p[0] <= src_t1 + 0.6]
    if not win:
        return tf
    if out_ar > src_ar:          # vertical source → horizontal output: only vertical placement matters
        tf.cy = float(np.median([p[2] for p in win])) - 0.05
        return tf
    crop_w = out_ar / src_ar
    path = reframe_path(win, src_t0, src_t1, crop_w)
    tf.cx = path[0][1] if path else float(np.median([p[1] for p in win]))
    if len({round(k[1], 3) for k in path}) > 1:
        tf.keys = [TransformKey(t=t, cx=x, cy=0.5, zoom=1.0) for t, x in path]
    return tf


def _cue_index(polish: PolishPlan) -> dict[str, list[EffectCue]]:
    idx: dict[str, list[EffectCue]] = {}
    for c in polish.effects:
        idx.setdefault(c.at, []).append(c)
    return idx


# ------------------------------------------------------------------ main
def compile_timeline(pa: ProjectAnalysis, d: Direction, story: StoryPlan, polish: PolishPlan, brief: CreatorBrief | None = None,
                     *, project_root: str | Path | None = None, fps: float = 30.0) -> Timeline:
    W, H = SIZES.get(d.aspect, (1920, 1080))
    proj = Project(project_root or pa.root) if (project_root or pa.root) else None
    ctx = Ctx(pa=pa, proj=proj, d=d, story=story, polish=polish, brief=brief or CreatorBrief(), W=W, H=H, fps=fps)
    pb = K.playbook(d.playbook)
    cues = _cue_index(polish)
    no = {r.target for r in ctx.brief.rules if r.kind == "no_effect"}
    music_front = {c.section for c in polish.music if c.mode == "front"}
    applied_conf = 0.5

    # ---- removed material (what an editor would cut) as suggestions
    used_refs = {it.ref for it in story.items}
    from ..brain.basic import BasicBrain

    bb = BasicBrain(pa, ctx.brief)
    for a in bb.talk_assets():
        for s in pa.clips[a.id].transcript.segments:
            why = bb.is_cut_candidate(s)
            if why and s.id not in used_refs:
                ctx.suggest("cut", f"Cut “{_clip(s.text, 64)}” — {why}", conf=0.85, payload={"asset": a.id, "t0": s.t0, "t1": s.t1, "segment": s.id,
                                                                                    "key": f"seg:{s.id}"})
    for a in pa.assets:
        if a.kind != AssetKind.BROLL:
            continue
        for sh in pa.clips[a.id].shots:
            bad = set(sh.flags) & {"dark", "blurry", "shaky", "pocket"}
            if bad and sh.id not in used_refs:
                ctx.suggest("cut", f"Left out {a.name} — {', '.join(sorted(bad))}", conf=0.8, payload={"asset": a.id, "shot": sh.id, "key": f"shot:{sh.id}"})
            elif sh.dup_group and sh.dup_rank > 0 and sh.id not in used_refs:
                ctx.suggest("cut", f"Left out {a.name} — near-duplicate of a better take", conf=0.75, payload={"asset": a.id, "shot": sh.id,
                                                                                                                  "key": f"shot:{sh.id}"})

    # ---- main assembly (V1/A1)
    t = 0.0
    last_asset, last_src_out, zoom_toggle = None, None, False
    zoom_ok = "zoom" not in no and pb.budget("zoom") > 0
    tight, breath, max_pause = pb.pacing.tightness, pb.pacing.breath, pb.pacing.max_pause
    if d.knobs.tightness is not None:              # Style DNA: cut speech like the references do
        tight = d.knobs.tightness
        max_pause = max(0.25, max_pause * (1.3 - d.knobs.tightness))
    broll_len = d.knobs.shot_len or float(np.mean(pb.pacing.broll_shot))
    word_zoom = {c.at: c for c in polish.effects if c.type == "zoom" and ".w" in c.at and c.confidence >= applied_conf}
    for k, it in enumerate(story.items):
        sec = it.section
        ctx.section_t.setdefault(sec, [t, t])
        trans = next((c for c in cues.get(f"before:{it.ref}", []) if c.type == "transition" and c.confidence >= applied_conf), None)
        seg = _try(pa.segment, it.ref)
        shot = _try(pa.shot, it.ref)
        if seg is not None:
            pieces, kept, removed = speech_pieces(ctx, seg, tightness=tight, breath=breath, max_pause=max_pause, whole=it.whole)
            if it.role == "hook" and pieces and not it.whole:
                pieces, kept, trimmed = tighten_hook(ctx, seg, pieces, kept)
                if trimmed:
                    ctx.suggest("hook", f"Hook enters late: starts at “{trimmed}” so the promise lands in the first seconds", conf=0.8, t=0.0,
                                payload={"key": f"whole:{seg.id}"})
            if removed:
                ctx.suggest("filler", f"Removed {removed} filler word(s)/pause(s) inside “{seg.text[:40]}”", conf=0.9, t=t,
                            payload={"key": f"whole:{seg.id}"})
            asset = pa.asset(seg.asset_id)
            # split pieces at punch-in words
            split: list[tuple[float, float, float]] = []   # (a, b, zoom)
            for a, b in pieces:
                zoom_at = [word_zoom[w.id] for w in kept if w.id in word_zoom and a < w.t0 < b]
                if zoom_at and zoom_ok:
                    w0 = min(zoom_at, key=lambda c: c.at)
                    wt = next(w.t0 for w in kept if w.id == w0.at) - 0.03
                    if wt - a > 0.6 and b - wt > 0.4:
                        split.append((a, wt, 1.0))
                        split.append((wt, b, w0.value or 1.16))
                        ctx.suggest("zoom", w0.why or "punch-in", conf=w0.confidence, t=t + (wt - a), payload={"key": f"fx:zoom:{w0.at}"})
                        continue
                split.append((a, b, 1.0))
            jump_cue = next((c for c in cues.get(seg.id, []) if c.type == "zoom" and c.intent == "jumpcut"), None)
            for j, (a, b, z) in enumerate(split):
                base_tf = frame_for(ctx, asset.id, a, b)
                if asset.info.has_video:
                    is_jump = last_asset == asset.id and last_src_out is not None and a > last_src_out + 0.05
                    if is_jump and z == 1.0 and jump_cue and zoom_ok:
                        zoom_toggle = not zoom_toggle
                        z = (jump_cue.value or 1.12) if zoom_toggle else 1.0
                        if zoom_toggle:
                            ctx.suggest("zoom", "Alternate framing to hide a jump cut", conf=0.8, t=t, payload={"key": f"fx:zoom:{jump_cue.at}"})
                    base_tf.zoom = z
                    v = Item(id=ctx.iid("v"), track="V1", kind="video", asset_id=asset.id, src_in=a, src_out=b, rec_in=t,
                             transform=base_tf if not base_tf.is_identity else None, role=it.role, section=sec, ref=it.ref)
                    if trans and j == 0 and ctx.items:
                        dur = TRANS_DUR.get(trans.style or "dissolve", 0.4)
                        v.transition_in, v.transition_dur = trans.style or "dissolve", dur
                        v.rec_in = t = max(0.0, t - dur)
                        ctx.suggest("transition", trans.why, conf=trans.confidence, t=t, items=[v.id], payload={"key": f"fx:transition:{trans.at}"})
                    ctx.items.append(v)
                    link = v.id
                else:
                    link = None
                au = Item(id=ctx.iid("a"), track="A1", kind="audio", asset_id=asset.id, src_in=a, src_out=b, rec_in=t, link=link,
                          fade_in=0.01, fade_out=0.015, role=it.role, section=sec, ref=it.ref)
                ctx.items.append(au)
                for w in kept:
                    if a - 0.01 <= w.t0 and w.t1 <= b + 0.05:
                        tt = t + (w.t0 - a)
                        ctx.word_t[w.id] = tt
                        ctx.caption_words.append(CaptionWord(text=w.text, t0=round(tt, 3), t1=round(t + (min(w.t1, b) - a), 3)))
                ctx.speech_spans.append((t, t + (b - a)))
                ctx.spans.setdefault(it.ref, []).append((t, t + (b - a)))
                t += b - a
                last_asset, last_src_out = asset.id, b
            if it.role == "hook":
                ctx.suggest("hook", f"Hook first: “{_clip(seg.text, 80)}”" + (f" ({it.note})" if it.note else ""), conf=0.9, t=0.0,
                            payload={"key": "hook", "ref": it.ref})
        elif shot is not None:
            asset = pa.asset(shot.asset_id)
            a = it.t0 if it.t0 is not None else shot.t0
            b = it.t1 if it.t1 is not None else min(shot.t1, a + broll_len)
            speed_cue = next((c for c in cues.get(shot.id, []) if c.type == "speed"), None)
            speed = 1.0
            if speed_cue and speed_cue.confidence >= applied_conf:
                speed = float(speed_cue.value or 1.0)
                if speed < 1:   # slow-mo: centre the source window on the action, keep the rec length
                    rec_len = b - a
                    src_len = rec_len * speed
                    centre = shot.action_peaks[0] if shot.action_peaks else (a + b) / 2
                    a = max(shot.t0, min(centre - src_len / 2, shot.t1 - src_len))
                    b = a + src_len
                ctx.suggest("speed", speed_cue.why, conf=speed_cue.confidence, t=t, payload={"speed": speed, "key": f"fx:speed:{speed_cue.at}"})
            elif speed_cue:
                ctx.suggest("speed", speed_cue.why, conf=speed_cue.confidence, t=t, payload={"speed": speed_cue.value, "key": f"fx:speed:{speed_cue.at}",
                                                                                         "acceptable": True}, status="optional")
            tf = frame_for(ctx, asset.id, a, b)
            if tf.keys and abs(speed - 1) > 1e-3:
                for kf in tf.keys:
                    kf.t = kf.t / speed
            if asset.info.is_image or asset.kind in (AssetKind.IMAGE, AssetKind.MEME_IMAGE):
                v = Item(id=ctx.iid("v"), track="V1", kind="image", asset_id=asset.id, rec_in=t, duration=b - a, role=it.role, section=sec,
                         ref=it.ref)
            else:
                v = Item(id=ctx.iid("v"), track="V1", kind="video", asset_id=asset.id, src_in=a, src_out=b, rec_in=t, speed=speed,
                         transform=tf if not tf.is_identity else None, role=it.role, section=sec, ref=it.ref)
                if d.playbook == "aesthetic" and shot.camera_move == "static" and zoom_ok:
                    v.transform = v.transform or Transform()
                    v.transform.keys = [TransformKey(t=0, cx=v.transform.cx, cy=v.transform.cy, zoom=1.0),
                                        TransformKey(t=v.rec_dur, cx=v.transform.cx, cy=v.transform.cy, zoom=1.06)]
            if trans and ctx.items:
                dur = TRANS_DUR.get(trans.style or "dissolve", 0.4)
                v.transition_in, v.transition_dur = trans.style or "dissolve", dur
                v.rec_in = t = max(0.0, t - dur)
                ctx.suggest("transition", trans.why, conf=trans.confidence, t=t, items=[v.id], payload={"key": f"fx:transition:{trans.at}"})
            ctx.items.append(v)
            if asset.info.has_audio and speed == 1.0:
                gain = {"aesthetic": 0.0}.get(d.playbook, -14.0 if sec in music_front else -9.0)
                ctx.items.append(Item(id=ctx.iid("a"), track="A1", kind="audio", asset_id=asset.id, src_in=a, src_out=b, rec_in=t,
                                      link=v.id, gain_db=gain, fade_in=0.08, fade_out=0.08, role="natural", section=sec, ref=it.ref))
            ctx.spans.setdefault(it.ref, []).append((t, t + v.rec_dur))
            t += v.rec_dur
            last_asset, last_src_out = asset.id, b
            if it.role in ("hook", "establishing"):
                ctx.suggest(it.role if it.role == "hook" else "broll", it.note or it.role, conf=0.85, t=v.rec_in, items=[v.id],
                            payload={"key": "hook" if it.role == "hook" else f"item:{it.ref}", "ref": it.ref})
        else:
            continue
        ctx.section_t[sec][1] = t
        # meme cutaway right after its anchor segment
        for c in cues.get(it.ref, []):
            if c.type != "meme":
                continue
            if not c.asset or c.asset.startswith("meme:") or c.confidence < applied_conf or "meme" in no:
                m = K.memes()
                cat = next((x for x in m if c.asset and x.id == c.asset.split(":", 1)[1]), None) if c.asset and c.asset.startswith("meme:") else None
                ctx.suggest("meme", (c.why or "meme moment") + (f" — try “{cat.name}” (search: {cat.search[0]})" if cat else ""), conf=min(c.confidence, 0.45),
                            t=t, status="optional", payload={"catalogue": c.asset, "search": cat.search if cat else [], "key": f"fx:meme:{c.at}",
                                                             "acceptable": bool(c.asset and not c.asset.startswith("meme:") and "meme" not in no)})
                continue
            ma = pa.asset(c.asset)
            mdur = min(1.6, ma.info.duration) if ma.info.has_video and not ma.info.is_image and ma.info.duration > 0.3 else 1.2
            if ma.kind == AssetKind.MEME_IMAGE or ma.info.is_image:
                mv = Item(id=ctx.iid("v"), track="V1", kind="image", asset_id=ma.id, rec_in=t, duration=mdur, role="meme", section=sec,
                          ref=f"fx:meme:{c.at}")
            else:
                mv = Item(id=ctx.iid("v"), track="V1", kind="video", asset_id=ma.id, src_in=0.0, src_out=mdur, rec_in=t, role="meme", section=sec,
                          ref=f"fx:meme:{c.at}")
            ctx.items.append(mv)
            if ma.info.has_audio and not ma.info.is_image:
                ctx.items.append(Item(id=ctx.iid("a"), track="A4", kind="audio", asset_id=ma.id, src_in=0.0, src_out=mdur, rec_in=t, link=mv.id,
                                      gain_db=-4.0, fade_out=0.05, role="meme"))
            elif "sfx" not in no:
                ctx.items.append(_sfx_item(ctx, "boom", t, gain=-9.0))
            ctx.suggest("meme", c.why, conf=c.confidence, t=t, items=[mv.id], source="brief" if c.intent == "brief" else "rules",
                        payload={"key": f"fx:meme:{c.at}"})
            t += mdur
            ctx.section_t[sec][1] = t
    total = t

    # ---- B-roll overlays (V2) over talking beats
    for c in polish.effects:
        if c.type != "broll" or c.at not in ctx.spans:
            continue
        sh = _try(pa.shot, c.asset or "")
        if sh is None:
            continue
        spans = ctx.spans[c.at]
        s0, s1 = spans[0][0], spans[-1][1]
        if s1 - s0 < 2.0:
            continue
        dur = min(c.dur or 2.5, s1 - s0 - 0.8)
        start = s0 + min(1.0, (s1 - s0 - dur) / 2)
        if story.items and story.items[0].ref == c.at:
            if s1 - s0 < 5.0:
                continue      # a short hook keeps the face on screen
            start = max(start, s0 + 3.0)   # never cover the first 3 s of the hook
            dur = min(dur, s1 - start - 0.3)
            if dur < 1.2:
                continue
        a, b = (sh.best[0].t0, sh.best[0].t0 + dur) if sh.best and sh.best[0].t1 - sh.best[0].t0 >= dur else (sh.t0, min(sh.t1, sh.t0 + dur))
        tf = frame_for(ctx, sh.asset_id, a, b)
        ov = Item(id=ctx.iid("v"), track="V2", kind="video", asset_id=sh.asset_id, src_in=a, src_out=b, rec_in=start,
                  transform=tf if not tf.is_identity else None, role="broll", fade_in=0.0, fade_out=0.0)
        if c.confidence >= applied_conf:
            ov.ref = f"fx:broll:{c.at}"
            ctx.items.append(ov)
            ctx.suggest("broll", c.why, conf=c.confidence, t=start, items=[ov.id], payload={"shot": sh.id, "key": f"fx:broll:{c.at}"})
        else:
            ctx.suggest("broll", c.why, conf=c.confidence, t=start, status="optional", payload={"shot": sh.id, "key": f"fx:broll:{c.at}",
                                                                                                "acceptable": True})

    # ---- text (T1)
    for c in polish.effects:
        if c.type != "text" or not c.text:
            continue
        dur = c.dur or 2.4
        if c.at == "start":
            t0 = 0.05
        elif c.at == "end":
            t0 = max(0.0, total - dur - 0.1)
        elif c.at.startswith("section:"):
            t0 = ctx.section_t.get(c.at.split(":", 1)[1], [None])[0]
            if t0 is None:
                continue
            t0 += 0.25
        elif c.at in ctx.spans:
            t0 = ctx.spans[c.at][0][0]
        elif c.at in ctx.word_t:
            t0 = ctx.word_t[c.at]
        else:
            continue
        dur = min(dur, max(0.8, total - t0))
        key = f"fx:text:{c.at}|{c.text[:24]}"
        txt = Item(id=ctx.iid("t"), track="T1", kind="text", text=c.text, style=c.style or "title", rec_in=round(t0, 3), duration=round(dur, 3), role="text",
                   ref=key)
        if c.confidence < applied_conf:
            ctx.suggest("text", f"{c.why}: “{c.text}”", conf=c.confidence, t=t0, status="optional", payload={"key": key, "acceptable": True})
        else:
            ctx.items.append(txt)
            ctx.suggest("text", f"{c.why}: “{c.text}”", conf=c.confidence, t=t0, items=[txt.id],
                        source="user" if c.intent == "user" else ("brief" if c.confidence >= 1.0 else "rules"), payload={"key": key})
            if "sfx" not in no and c.style in ("hook", "card") and pb.budget("sfx") > 0 and d.playbook not in ("aesthetic",):
                ctx.items.append(_sfx_item(ctx, "pop", t0, gain=-12.0))

    # ---- SFX (A3)
    if "sfx" not in no:
        for c in polish.effects:
            if c.type != "sfx" or not c.asset:
                continue
            at = c.at
            if at.startswith("before:section:"):
                sec = at.split(":", 2)[2]
                if sec not in ctx.section_t:
                    continue
                kind_len = 1.8
                t0 = max(0.0, ctx.section_t[sec][0] - kind_len)
            elif at.startswith("section:"):
                sec = at.split(":", 1)[1]
                if sec not in ctx.section_t:
                    continue
                t0 = ctx.section_t[sec][0]
            elif at.startswith("before:"):
                ref = at.split(":", 1)[1]
                if ref not in ctx.spans:
                    continue
                t0 = max(0.0, ctx.spans[ref][0][0] - 0.25)
            elif at in ctx.word_t:
                t0 = ctx.word_t[at]
            else:
                continue
            if c.confidence >= applied_conf:
                item = _sfx_item(ctx, c.asset, t0, gain=-8.0)
                item.ref = f"fx:sfx:{c.at}"
                ctx.items.append(item)
                ctx.suggest("sfx", c.why, conf=c.confidence, t=t0, items=[item.id], payload={"key": f"fx:sfx:{c.at}"},
                            source="user" if c.intent == "user" else "rules")
            else:
                ctx.suggest("sfx", c.why, conf=c.confidence, t=t0, status="optional", payload={"key": f"fx:sfx:{c.at}", "acceptable": True})

    # ---- bleeps
    for c in polish.effects:
        if c.type == "bleep" and c.at in ctx.word_t:
            t0 = ctx.word_t[c.at]
            ctx.items.append(_sfx_item(ctx, "bleep", t0, gain=-10.0))
            ctx.suggest("bleep", c.why, conf=1.0, t=t0, payload={"word": c.at, "key": f"fx:bleep:{c.at}"})

    # ---- music (A2) per section with ducking
    _lay_music(ctx, total)

    # ---- captions
    style = d.knobs.captions
    if any(r.kind == "captions" and r.value == "off" for r in ctx.brief.rules):
        style = "off"
    emph = {c.at for c in polish.effects if c.type == "emphasis" and c.confidence >= applied_conf}
    emph_t = {round(ctx.word_t[w], 3) for w in emph if w in ctx.word_t}
    for cw in ctx.caption_words:
        if round(cw.t0, 3) in emph_t:
            cw.emph = True
    if d.playbook == "aesthetic" and style != "off":
        style = "aesthetic"
    caps = build_captions(sorted(ctx.caption_words, key=lambda w: w.t0), style=style if style != "aesthetic" else "clean",
                          words_range=tuple(pb.captions.get("words", [3, 6])), vertical=H > W, face_boxes_at=_face_lookup(ctx))
    if style == "aesthetic":
        for c in caps:
            c.style = "aesthetic"
            for w in c.words:
                w.text = w.text.lower()
    texts = [i for i in ctx.items if i.kind == "text"]
    hook_txt = [t for t in texts if t.style == "hook"]
    for c in caps:
        if any(t.rec_in - 0.1 <= c.t0 <= t.rec_out for t in hook_txt):
            c.pos = "lower"           # the text hook owns the top of the frame
    def _words(s: str) -> set:
        return {w for w in re.findall(r"[a-z0-9]+", s.lower().replace("two", "2")) if len(w) > 1}
    for t in [t for t in texts if t.style in ("cta", "title")]:
        tw = _words(t.text or "")
        overlapping = [c for c in caps if c.t1 > t.rec_in and c.t0 < t.rec_out]
        said = _words(" ".join(c.text for c in overlapping))
        if tw and len(tw & said) >= max(1, int(len(tw) * 0.6)):
            caps = [c for c in caps if c not in overlapping]   # don't show the same words twice
    if caps:
        ctx.suggest("caption", f"{len(caps)} caption chunks ({style}); {sum(1 for c in caps for w in c.words if w.emph)} emphasised words", conf=0.9,
                    payload={"key": "captions"})

    tl = Timeline(id=f"{d.id}-{d.playbook}", name=d.name, direction_id=d.id, playbook=d.playbook, fps=fps, width=W, height=H,
                  items=sorted(ctx.items, key=lambda i: (i.rec_in, i.track)), captions=caps, markers=ctx.markers, suggestions=ctx.sugg,
                  look=polish.look,
                  meta={"target": d.knobs.target_length, "hook": d.hooks[0].model_dump() if d.hooks else None, "story_why": story.why,
                        "vo_script": polish.vo_script, "broll_gaps": [g.model_dump() for g in polish.broll_gaps],
                        "music": [c.model_dump() for c in polish.music],
                        "word_t": {k: round(v, 3) for k, v in ctx.word_t.items()}})
    tl.music_spans = getattr(ctx, "_music_spans", [])
    return tl


def _clip(text: str, n: int) -> str:
    """Shorten at a word boundary with an ellipsis (no "for thre" stubs in the UI)."""
    text = text.strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:—-")
    return cut + "…"


def _try(fn, key):
    try:
        return fn(key)
    except KeyError:
        return None


def _face_lookup(ctx: Ctx):
    v1 = [i for i in ctx.items if i.track == "V1" and i.kind == "video"]

    def at(t: float):
        for it in v1:
            if it.rec_in <= t < it.rec_out:
                st = it.src_in + (t - it.rec_in) * it.speed
                faces = [f for s in ctx.pa.clips[it.asset_id].shots for f in s.faces if abs(f.t - st) <= 1.0]
                if faces:
                    f = max(faces, key=lambda f: f.w * f.h)
                    return (f.x, f.y, f.w, f.h)
        return None

    return at


def _sfx_item(ctx: Ctx, asset: str, t0: float, gain: float = -8.0) -> Item:
    if asset.startswith("sfx:"):
        name = asset.split(":", 1)[1]
    elif asset in ("pop", "bleep", "whoosh", "riser", "impact", "ding", "boom"):
        name = asset
    else:
        a = ctx.pa.asset(asset)
        return Item(id=ctx.iid("s"), track="A3", kind="audio", asset_id=a.id, src_in=0.0, src_out=a.info.duration, rec_in=round(t0, 3),
                    gain_db=gain, fade_out=0.05, role="sfx")
    dur = {"pop": 0.12, "bleep": 0.4, "whoosh": 0.55, "riser": 1.8, "impact": 1.4, "ding": 1.2, "boom": 1.4}.get(name, 0.6)
    return Item(id=ctx.iid("s"), track="A3", kind="audio", asset_id=None, src_in=0.0, src_out=dur, rec_in=round(t0, 3), gain_db=gain,
                role="sfx", note=f"builtin:{name}")


def _lay_music(ctx: Ctx, total: float) -> None:
    pb = K.playbook(ctx.d.playbook)
    bed_db, front_db = float(pb.music.get("bed_db", -20)), float(pb.music.get("front_db", -8))
    spans: list[MusicSpan] = []
    for cue in ctx.polish.music:
        if cue.section not in ctx.section_t:
            continue
        t0, t1 = ctx.section_t[cue.section]
        if t1 - t0 < 0.3:
            continue
        spans.append(MusicSpan(t0=t0, t1=t1, mode=cue.mode if cue.track_id else "none", section=cue.section))
    # group consecutive spans that share a track
    groups: list[tuple[str, list]] = []
    for cue in ctx.polish.music:
        if cue.section not in ctx.section_t or not cue.track_id or cue.mode == "none":
            continue
        t0, t1 = ctx.section_t[cue.section]
        if groups and groups[-1][0] == cue.track_id and abs(groups[-1][1][-1][1] - t0) < 0.6:
            groups[-1][1].append((t0, t1, cue))
        else:
            groups.append((cue.track_id, [(t0, t1, cue)]))
    ctx._music_spans = spans  # type: ignore[attr-defined]
    for track, parts in groups:
        g0, g1 = parts[0][0], parts[-1][1]
        need = g1 - g0
        a = ctx.pa.asset(track)
        m = ctx.pa.clips[track].music
        drop_sec = ctx.section_t.get("drop") or ctx.section_t.get("climax")
        align = (drop_sec[0] - g0) if drop_sec and g0 <= drop_sec[0] < g1 else None
        off, why = best_offset(m, a.info.duration, need, align_drop_at=align) if m else (0.0, "start of track")
        # envelope: sampled every 50 ms — section level, ducked (or muted) under speech with smooth ramps
        mute_speech = any(r.kind == "no_music_under_speech" for r in ctx.brief.rules)

        def levels(cue):
            free = front_db if cue.mode == "front" else (bed_db + 6 if cue.mode == "bed" else bed_db + 2)
            sp = -80.0 if mute_speech else (bed_db if cue.mode in ("bed", "light") else bed_db + 2)
            g = max(-12.0, min(6.0, cue.gain_db))
            return min(-1.0, free + g), (sp if sp <= -80 else min(-12.0, sp + g))

        merged: list[list[float]] = []
        for s0, s1 in sorted(ctx.speech_spans):
            if s1 <= g0 or s0 >= g1:
                continue
            if merged and s0 - merged[-1][1] < 1.0:
                merged[-1][1] = max(merged[-1][1], s1)
            else:
                merged.append([s0, s1])

        def level_at(tt: float) -> float:
            cue = next((c for p0, p1, c in parts if p0 - 1e-6 <= tt <= p1 + 1e-6), parts[-1][2])
            free, sp = levels(cue)
            lvl = free
            for s0, s1 in merged:
                if s0 <= tt <= s1:
                    return sp
                if s0 - 0.25 <= tt < s0:
                    lvl = min(lvl, sp + (free - sp) * (s0 - tt) / 0.25)
                elif s1 < tt <= s1 + 0.4:
                    lvl = min(lvl, sp + (free - sp) * (tt - s1) / 0.4)
            return lvl

        grid = np.arange(g0, g1 + 0.05, 0.05)
        vals = [level_at(float(x)) for x in grid]
        clean: list[tuple[float, float]] = []
        for k2, (tt, db) in enumerate(zip(grid, vals, strict=False)):
            prev_v = vals[k2 - 1] if k2 else None
            next_v = vals[k2 + 1] if k2 + 1 < len(vals) else None
            if k2 == 0 or next_v is None or abs(db - prev_v) > 1e-3 or abs(db - next_v) > 1e-3:
                clean.append((round(float(tt), 3), round(float(db), 2)))
        pos, cur_off = g0, off
        guard = 0
        while pos < g1 - 0.05 and guard < 50:
            guard += 1
            avail = a.info.duration - cur_off
            if avail < 1.0:          # end of track: loop from the top
                cur_off = 0.0
                avail = a.info.duration
            if avail < 1.0:
                break
            seg_len = min(g1 - pos, avail)
            item = Item(id=ctx.iid("m"), track="A2", kind="audio", asset_id=a.id, src_in=round(cur_off, 3), src_out=round(cur_off + seg_len, 3),
                        rec_in=round(pos, 3), gain_db=0.0, envelope=[e for e in clean if pos - 0.01 <= e[0] <= pos + seg_len + 0.01],
                        fade_in=0.05 if pos == g0 else 1.0, fade_out=1.5 if pos + seg_len >= g1 - 0.05 else 1.0, role="music",
                        section=parts[0][2].section)
            ctx.items.append(item)
            pos += seg_len
            cur_off = 0.0
        modes = "/".join(sorted({p[2].mode for p in parts}))
        ctx.suggest("music", f"{a.name} as {modes} ({parts[0][2].why}); {why}", conf=0.8, t=g0,
                    alts=parts[0][2].alternatives, payload={"track": a.id, "offset": off, "key": "music:" + ",".join(p[2].section for p in parts),
                                                            "sections": [p[2].section for p in parts]})
    for cue in ctx.polish.music:
        if cue.mode == "none" or cue.track_id:
            continue
        if cue.section in ctx.section_t:
            ctx.suggest("music", f"No suitable track for “{cue.section}” in your music folder — search: {', '.join(cue.brief.search_terms[:2])}",
                        conf=0.4, t=ctx.section_t[cue.section][0], status="optional",
                        payload={"search": cue.brief.search_terms, "key": f"music:{cue.section}", "acceptable": False})


def story_items_text(pa: ProjectAnalysis, items: list[StoryItem]) -> str:
    out = []
    for it in items:
        seg = _try(pa.segment, it.ref)
        out.append(f"[{it.role}] " + (f"“{seg.text}”" if seg else f"<{it.ref}>"))
    return "\n".join(out)


def shot_label(sh: Shot) -> str:
    return re.sub(r"_+", " ", f"{sh.camera_move} {'/'.join(sh.tags[:2])}").strip()
