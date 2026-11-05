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
from ..analyze.visual import photo_fills
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
    speed_done: set = field(default_factory=set)                                   # shots that already got their slow-mo
    on_screen: dict = field(default_factory=dict)                                  # two-shots: asset → seat framed now
    turns: dict = field(default_factory=dict)                                      # line → length of that speaker's turn
    layout_top: float | None = None                                                # stacked layout: the top panel's height
    n_photos: int = 0                                                              # photos placed so far (motion alternates)
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
                  whole: bool = False, lead: float = 0.0, hold: float = 0.0) -> tuple[list[tuple[float, float]], list[Word], int]:
    """Cut a line into word-snapped pieces (pauses/fillers out). `lead`/`hold` keep a beat before the first word and
    after the last one — comedy timing: the pause before a punchline and the beat after it are part of the joke."""
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
    for k, run in enumerate(runs):
        a, b = run[0].t0, run[-1].t1
        pre = max(breath, lead) if k == 0 else breath
        post = max(breath, hold) if k == len(runs) - 1 else breath
        prev_word = next((x for x in reversed(all_words) if x.t1 <= a - 0.01), None)
        next_word = next((x for x in all_words if x.t0 >= b + 0.01), None)
        lo_a = max((prev_word.t1 + (0.05 if pre > breath else 0.0)) if prev_word else 0.0, a - pre - 0.12)
        hi_b = min((next_word.t0 - (0.05 if post > breath else 0.0)) if next_word else b + 1.0, b + post + 0.15)
        a2 = snap(ctx, seg.asset_id, max(lo_a, a - pre), lo_a, a - 0.02)
        b2 = snap(ctx, seg.asset_id, min(hi_b, b + post), b + 0.04, hi_b)
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


def photo_motion(ctx: Ctx, shot, dur: float, idx: int) -> Transform | None:
    """A still that moves like a camera (Ken Burns), never a frozen frame: a wide photo in a narrow frame pans gently onto
    its subject; otherwise a slow push-in (or pull-out, alternating so it never feels mechanical) on the face or the
    centre. Holds under 0.7 s stay still — motion that fast reads as jitter. A group photo whose faces don't all fit a
    filled frame (or a panorama, of which a filled frame would show under a third) is shown whole on a blurred copy of
    itself instead: never cut a person out of a group photo."""
    ds = ctx.pa.asset(shot.asset_id).info.display_size or (ctx.W, ctx.H)
    src_ar, out_ar = ds[0] / ds[1], ctx.W / ctx.H
    face = max(shot.faces, key=lambda f: f.w * f.h) if shot.faces else None
    fx, fy = (face.x, face.y) if face else (0.5, 0.45)
    crop_w = out_ar / src_ar
    if not photo_fills(ds, shot.faces, out_ar):
        if dur < 0.7:
            return Transform(fit=True)
        z0, z1 = (1.0, 1.04) if idx % 2 == 0 else (1.04, 1.0)
        return Transform(fit=True, zoom=z0, keys=[TransformKey(t=0.0, zoom=z0), TransformKey(t=round(dur, 3), zoom=z1)])
    if dur < 0.7:                                       # framed like the others, just not moving
        return Transform(cx=round(min(max(fx, crop_w / 2), 1 - crop_w / 2), 4) if crop_w < 1 else 0.5, cy=0.5 if crop_w < 1 else round(fy, 4))
    if crop_w < 0.75:                                   # much wider than the frame: pan across, ending on the subject
        lo, hi = crop_w / 2, 1 - crop_w / 2
        end = min(max(fx, lo), hi)
        # a drift, not a sweep: about 6 % of the frame's width a second, like the push-ins
        span = min(0.06 * crop_w * dur, 0.08, (hi - lo) / 2) * (1 if idx % 2 else -1)
        start = min(max(end - span, lo), hi)
        if abs(end - start) < 0.01:
            start = min(max(end + span, lo), hi)
        return Transform(cx=round(start, 4), cy=0.5, zoom=1.0, keys=[TransformKey(t=0.0, cx=round(start, 4), cy=0.5, zoom=1.0),
                                                                     TransformKey(t=round(dur, 3), cx=round(end, 4), cy=0.5, zoom=1.0)])
    z0, z1 = (1.0, 1.07) if idx % 2 == 0 else (1.07, 1.0)
    cx, cy = round(min(max(fx, 0.35), 0.65), 4), round(min(max(fy, 0.35), 0.6), 4)
    return Transform(cx=cx, cy=cy, zoom=z0, keys=[TransformKey(t=0.0, cx=cx, cy=cy, zoom=z0), TransformKey(t=round(dur, 3), cx=cx, cy=cy, zoom=z1)])


def _beside_face(ctx: Ctx, fb, text: str, pos: str) -> tuple[str, float | None, float]:
    """Where words on a photo go, and at what size: the middle when it's free (or the top, for a title), else the
    larger free band above the head (leaving room for hair) or below the chin, inside the platform's safe area —
    never across a face. A tight close-up leaves little room: the words get a little smaller (down to 76 %) to fit."""
    from .captions import SAFE, text_block

    top_safe, bottom_safe, _ = SAFE["9:16" if ctx.H > ctx.W else "16:9"]
    lo_y, hi_y = top_safe + 0.02, 1 - bottom_safe - 0.01          # the text block must sit inside [lo_y, hi_y]

    def clamp(y: float, h: float) -> float:
        return round(min(max(y, lo_y + h / 2), hi_y - h / 2), 4)

    h = text_block(text, "photo", ctx.W, ctx.H)[1]
    want = 0.46 if pos == "center" else lo_y + h / 2
    if fb is None:
        return pos, clamp(want, h), 1.0
    face_top, face_bot = fb[1] - fb[3] / 2 - 0.3 * fb[3], fb[1] + fb[3] / 2 + 0.03       # hair above, a breath below the chin
    if want + h / 2 < face_top or want - h / 2 > face_bot:                                # the wanted place is already clear
        return pos, clamp(want, h), 1.0
    above, below = face_top - lo_y, hi_y - face_bot
    for scale in (1.0, 0.92, 0.84, 0.76):
        h = text_block(text, "photo", ctx.W, ctx.H, scale)[1]
        if above >= h and (above >= below or pos == "upper"):
            return "upper", round(max(lo_y + h / 2, min((lo_y + face_top) / 2, face_top - h / 2)), 4), scale
        if below >= h:
            return "lower", round(min(hi_y - h / 2, max((face_bot + hi_y) / 2, face_bot + h / 2)), 4), scale
    # even small it won't fit (an extreme close-up): the bigger band, against its outer edge
    h = text_block(text, "photo", ctx.W, ctx.H, 0.76)[1]
    return ("upper", clamp(lo_y + h / 2, h), 0.76) if above >= below else ("lower", clamp(hi_y - h / 2, h), 0.76)


def _seamless_loop(ctx: Ctx) -> None:
    """A Reel that ends on its cover should replay without a seam: the closing clip carries the cover's own move at
    the same speed and stops exactly on the cover's first frame, so the replay continues the motion. A push-in cannot
    be continued backwards (it would have to zoom out past the full photo), so the cover pulls out instead."""
    v1 = [i for i in ctx.items if i.track == "V1"]
    loop = next((i for i in v1 if i.role == "loop"), None)
    cover = next((i for i in v1 if loop is not None and i.role == "hook" and i.asset_id == loop.asset_id), None)
    if loop is None or cover is None or not cover.transform or len(cover.transform.keys) < 2:
        return
    k0, k1 = cover.transform.keys[0], cover.transform.keys[-1]
    if k1.zoom > k0.zoom + 1e-3:
        k0, k1 = k0.model_copy(update={"zoom": k1.zoom}), k1.model_copy(update={"zoom": k0.zoom})
        cover.transform = cover.transform.model_copy(update={"cx": k0.cx, "cy": k0.cy, "zoom": k0.zoom, "keys": [k0, k1]})
    f = loop.rec_dur / max(k1.t - k0.t, 1e-3)
    start = TransformKey(t=0.0, cx=round(k0.cx - (k1.cx - k0.cx) * f, 4), cy=round(k0.cy - (k1.cy - k0.cy) * f, 4),
                         zoom=round(max(1.0, k0.zoom - (k1.zoom - k0.zoom) * f), 4))
    end = TransformKey(t=round(loop.rec_dur, 3), cx=k0.cx, cy=k0.cy, zoom=k0.zoom)
    loop.transform = cover.transform.model_copy(update={"cx": start.cx, "cy": start.cy, "zoom": start.zoom, "keys": [start, end]})
    loop.note = "kenburns"


MIN_SPEAKER_HOLD = 1.2      # never cut to someone for less than this: a quick "yeah" stays on the current speaker
REACTION_HOLD = 0.8         # …except an exclamation: a short reaction shot is the spice of a podcast edit


def _turn_lengths(pa: ProjectAnalysis, story: StoryPlan) -> dict[str, float]:
    """For each line in the cut: how long its speaker keeps talking from there on (consecutive lines by the same
    person). "Right." followed by a long answer starts a long turn, so the cut to that person happens on "Right."."""
    segs = []
    for it in story.items:
        try:
            segs.append(pa.segment(it.ref))
        except KeyError:
            segs.append(None)
    out: dict[str, float] = {}
    run = 0.0
    for k in range(len(segs) - 1, -1, -1):
        s = segs[k]
        if s is None or s.speaker is None:
            run = 0.0
            continue
        nxt = segs[k + 1] if k + 1 < len(segs) else None
        same = nxt is not None and nxt.speaker == s.speaker and nxt.asset_id == s.asset_id
        run = (s.t1 - s.t0) + (run if same else 0.0)
        out[s.id] = run
    return out


def speaker_frame(ctx: Ctx, seg, a: float, b: float, *, note: str = "", t: float = 0.0) -> Transform | None:
    """Two-shot cropped to a narrower frame (a 9:16 Short from a 16:9 podcast): frame the person talking, like a
    podcast clipper — cut at the end of a line, hold the current speaker through short interjections and unclear
    lines, and never centre on the empty gap between people. None when this doesn't apply (one person, or everyone
    fits in the frame anyway)."""
    asset = ctx.pa.asset(seg.asset_id)
    ds = asset.info.display_size or (ctx.W, ctx.H)
    src_ar, out_ar = ds[0] / ds[1], ctx.W / ctx.H
    if out_ar >= src_ar - 0.02:
        return None
    mid = (a + b) / 2
    sh = next((s for s in ctx.pa.clips[asset.id].shots if s.t0 <= mid <= s.t1 and len(s.seats) >= 2), None)
    if sh is None:
        return None
    crop_w = out_ar / src_ar
    xs = [s.x for s in sh.seats]
    if max(xs) - min(xs) + max(s.w for s in sh.seats) <= crop_w * 0.9:
        return None                                       # everyone fits: no need to choose
    held = ctx.on_screen.get(asset.id)
    seat = seg.speaker
    why = ""
    turn = ctx.turns.get(seg.id, b - a)
    # an exclamation ("Eleven times!") is a reaction worth seeing even when short; a plain "yeah" is not
    hold_min = REACTION_HOLD if seg.text.strip().endswith("!") else MIN_SPEAKER_HOLD
    if "nospeaker" in note or seat is None or (held is not None and seat != held and turn < hold_min):
        seat = held if held is not None else seat         # stay on who is on screen (rejected cut, unclear or a quick "yeah")
    if seat is None:
        seat = 0
    if seat != held:
        side = "left" if seat == 0 else "right" if seat == len(sh.seats) - 1 else f"seat {seat + 1}"
        if held is None:
            why = f"Opens on the person talking ({side}); the frame follows the conversation"
        elif turn < MIN_SPEAKER_HOLD:
            why = f"Reaction shot ({side}): “{_clip(seg.text, 30)}” is worth seeing"
        else:
            why = f"Framed on the person talking ({side}) — the cut to them lands at the end of the line"
        ctx.suggest("framing", why, conf=0.8, t=t, payload={"key": f"speaker:{seg.id}", "seat": seat})
    ctx.on_screen[asset.id] = seat
    cx = min(max(sh.seats[seat].x, crop_w / 2), 1 - crop_w / 2)
    return Transform(cx=round(cx, 4), cy=0.5)


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
    ctx.turns = _turn_lengths(pa, story)
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
            punch = (it.role == "punchline" or any(c.type == "meme" for c in cues.get(seg.id, []))) and "nobeat" not in (it.note or "")
            pieces, kept, removed = speech_pieces(ctx, seg, tightness=tight, breath=breath, max_pause=max_pause, whole=it.whole,
                                                  lead=0.45 if punch else 0.0, hold=0.4 if punch else 0.0)
            if pieces and last_asset == seg.asset_id and last_src_out is not None and last_src_out - 0.3 < pieces[0][0] < last_src_out:
                # the previous line's hold and this line's lead would both claim the same pause: play it once
                pieces[0] = (round(last_src_out, 3), pieces[0][1])
            if punch and pieces and k > 0:
                ctx.suggest("timing", f"Comedy timing: a beat before “{_clip(seg.text, 40)}” and a hold after it — the pause is part of the joke",
                            conf=0.8, t=t, payload={"key": f"beat:{seg.id}", "comedy": True})
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
                sp = speaker_frame(ctx, seg, a, b, note=it.note, t=t) if asset.info.has_video else None
                base_tf = sp if sp is not None else frame_for(ctx, asset.id, a, b)
                if asset.info.has_video:
                    is_jump = last_asset == asset.id and last_src_out is not None and a > last_src_out + 0.05
                    reframe = False
                    prev_v = next((x for x in reversed(ctx.items) if x.track == "V1"), None)
                    if sp is not None and prev_v is not None and prev_v.transform and abs(prev_v.transform.cx - sp.cx) > 0.05:
                        is_jump = False               # a cut to the other person is a real cut, not a jump cut to hide
                    if is_jump and z == 1.0 and jump_cue and zoom_ok:
                        prev_zoom = prev_v.transform.zoom if prev_v is not None and prev_v.transform else 1.0
                        zoom_toggle = prev_zoom < 1.01      # alternate against the framing actually on screen
                        z = (jump_cue.value or 1.12) if zoom_toggle else 1.0
                        reframe = zoom_toggle
                        if zoom_toggle:
                            ctx.suggest("zoom", "Alternate framing to hide a jump cut", conf=0.8, t=t,
                                        payload={"key": f"fx:zoom:{jump_cue.at}", "reframe": True})
                    base_tf.zoom = z
                    v = Item(id=ctx.iid("v"), track="V1", kind="video", asset_id=asset.id, src_in=a, src_out=b, rec_in=t,
                             transform=base_tf if not base_tf.is_identity else None, role=it.role, section=sec, ref=it.ref,
                             note="reframe" if reframe else "")
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
            if it.role == "flashforward":
                speed_cue = None             # the payoff later gets the slow-mo, not its preview
            if speed_cue and shot.id in ctx.speed_done:
                speed_cue = None             # one slow-mo per shot: later uses of the same shot play at normal speed
            if (speed_cue and (speed_cue.value or 1.0) < 1 and it.t0 is not None and shot.action_peaks
                    and not any(a - 0.3 <= p <= b + 0.3 for p in shot.action_peaks) and speed_cue.confidence < 1.0):
                speed_cue = None             # slow-mo belongs on the moment with the action, not on an empty stretch
            speed = 1.0
            if it.role == "replay" and "speed" not in no:
                speed_cue = EffectCue(type="speed", at=shot.id, value=0.5, why="slow-mo replay of the best play", confidence=0.8)
            if speed_cue and speed_cue.confidence >= applied_conf:
                if it.role != "replay":
                    ctx.speed_done.add(shot.id)
                speed = float(speed_cue.value or 1.0)
                if speed < 1:   # slow-mo: centre the source window on the action inside this moment, keep the rec length
                    rec_len = b - a
                    src_len = rec_len * speed
                    inside = [p for p in shot.action_peaks if a - 0.3 <= p <= b + 0.3]
                    centre = inside[0] if inside else (shot.action_peaks[0] if shot.action_peaks and it.t0 is None else (a + b) / 2)
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
                if asset.kind == AssetKind.IMAGE:          # photos move like a camera, never freeze ("no zooms": framed, still)
                    v.transform = photo_motion(ctx, shot, 0.0 if "zoom" in no else b - a, ctx.n_photos)
                    v.note = "kenburns" if v.transform and v.transform.keys else v.note
                    ctx.n_photos += 1
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
            talky = asset.kind in (AssetKind.SCREEN, AssetKind.AROLL) and bool(ctx.pa.words(asset.id))
            if asset.info.has_audio and speed == 1.0:
                if talky:
                    # a gameplay / talking window: its sound IS the content (commentary + game) — full level, captioned
                    ctx.items.append(Item(id=ctx.iid("a"), track="A1", kind="audio", asset_id=asset.id, src_in=a, src_out=b, rec_in=t,
                                          link=v.id, gain_db=0.0, fade_in=0.03, fade_out=0.05, role=it.role, section=sec, ref=it.ref))
                    for w in ctx.pa.words(asset.id):
                        if a - 0.01 <= w.t0 and w.t1 <= b + 0.05 and not w.filler and not w.text.startswith("["):
                            tt = t + (w.t0 - a)
                            ctx.word_t[w.id] = tt
                            ctx.caption_words.append(CaptionWord(text=w.text, t0=round(tt, 3), t1=round(t + (min(w.t1, b) - a), 3)))
                    for sp in (ctx.pa.clips[asset.id].speech or []):
                        lo, hi = max(a, sp.t0), min(b, sp.t1)
                        if hi > lo:
                            ctx.speech_spans.append((t + lo - a, t + hi - a))
                else:
                    gain = {"aesthetic": 0.0}.get(d.playbook, -14.0 if sec in music_front else -9.0)
                    ctx.items.append(Item(id=ctx.iid("a"), track="A1", kind="audio", asset_id=asset.id, src_in=a, src_out=b, rec_in=t,
                                          link=v.id, gain_db=gain, fade_in=0.08, fade_out=0.08, role="natural", section=sec, ref=it.ref))
            ctx.spans.setdefault(it.ref, []).append((t, t + v.rec_dur))
            t += v.rec_dur
            last_asset, last_src_out = asset.id, b
            if it.role == "flashforward":
                ctx.suggest("open_loop", it.note or "flash-forward of the payoff", conf=0.75, t=v.rec_in, items=[v.id],
                            payload={"key": f"open_loop:{it.ref}", "ref": it.ref})
            if it.role == "loop":
                ctx.suggest("loop", it.note or "loop ending", conf=0.75, t=v.rec_in, items=[v.id], payload={"key": f"loop:{it.ref}", "ref": it.ref})
            if it.role in ("hook", "establishing"):
                ctx.suggest(it.role if it.role == "hook" else "broll", it.note or it.role, conf=0.85, t=v.rec_in, items=[v.id],
                            payload={"key": "hook" if it.role == "hook" else f"item:{it.ref}", "ref": it.ref})
        else:
            continue
        ctx.section_t[sec][1] = t
        # meme cutaway right after its anchor segment (or after one play window of a long gameplay shot: "<shot>@<t0>")
        windowed = cues.get(f"{it.ref}@{it.t0:.1f}", []) if it.t0 is not None else []
        for c in [*cues.get(it.ref, []), *windowed]:
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
    _apply_split_edits(ctx, polish, no)
    _facecam_layout(ctx)
    _facecam_moments(ctx, polish, applied_conf)

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

    _seamless_loop(ctx)
    # ---- text (T1)
    face_at = _face_lookup(ctx)
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
        elif c.at.startswith("t:"):                       # an exact time (photo reels: lines land on the beat grid)
            t0 = float(c.at[2:])
        else:
            continue
        dur = min(dur, max(0.8, total - t0))
        key = f"fx:text:{c.at}|{c.text[:24]}"
        pos, text_y, text_scale = c.position, None, None
        if pos in ("center", "upper") and c.style == "photo":
            # the face wherever it goes while the words are up (a push-in grows it): clear of both ends of the move
            ends = [b for b in (face_at(t0 + 0.05), face_at(t0 + dur - 0.05)) if b]
            fb = None
            if ends:
                top, bot = min(b[1] - b[3] / 2 for b in ends), max(b[1] + b[3] / 2 for b in ends)
                fb = (ends[0][0], (top + bot) / 2, max(b[2] for b in ends), bot - top)
            pos, text_y, text_scale = _beside_face(ctx, fb, c.text, pos)
            text_scale = text_scale if text_scale < 0.999 else None
        elif pos == "center":                             # never across a face: above or below it instead
            fb = face_at(t0 + 0.2)
            if fb and fb[1] - fb[3] / 2 < 0.54 and fb[1] + fb[3] / 2 > 0.38:
                pos = "upper" if fb[1] > 0.46 else "lower"
        txt = Item(id=ctx.iid("t"), track="T1", kind="text", text=c.text, style=c.style or "title", rec_in=round(t0, 3), duration=round(dur, 3), role="text",
                   ref=key, position=pos, text_y=text_y, text_scale=text_scale)
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
    # a callout shows the streamer's words big while they say them: the captions step aside for it (the same words
    # twice, drawn at the same height, overlapped into "DCDOUBLE KILL!LL!")
    callouts = [(i.rec_in, i.rec_in + (i.duration or 0)) for i in ctx.items if i.kind == "text" and i.style == "callout"]
    ctx.caption_words = [w for w in ctx.caption_words if not any(a - 0.05 <= w.t0 < b for a, b in callouts)]
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
                        "word_t": {k: round(v, 3) for k, v in ctx.word_t.items()},
                        **({"layout_top": ctx.layout_top} if ctx.layout_top else {})})
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


STACK_TOP = (0.24, 0.40)       # the webcam panel's share of a vertical frame (sized to the webcam's own shape)


def _facecam_layout(ctx: Ctx) -> None:
    """Vertical cut of a screen recording with a webcam (a gaming stream): stacked like gaming Shorts — the webcam on
    top at its own shape, the game below. A plain 9:16 crop of a 16:9 stream would cut the streamer out (or, following
    the face, cut the game out)."""
    if ctx.H <= ctx.W or ctx.d.knobs.layout == "crop":
        return
    v1 = [i for i in ctx.items if i.track == "V1" and i.kind == "video" and i.role != "meme" and i.asset_id]
    for asset_id in dict.fromkeys(i.asset_id for i in v1):
        fc = ctx.pa.clips[asset_id].facecam
        if not fc:
            continue
        ds = ctx.pa.asset(asset_id).info.display_size or (1920, 1080)
        fx0, fy0, fx1, fy1 = fc
        cam_ar = (fx1 - fx0) * ds[0] / max(1e-6, (fy1 - fy0) * ds[1])
        top = round(min(STACK_TOP[1], max(STACK_TOP[0], ctx.W / cam_ar / ctx.H)), 3)     # the webcam at its own shape
        cam_tf = _cam_transform(fc, ds, ctx.W, top * ctx.H)
        ctx.layout_top = top
        for it in (i for i in v1 if i.asset_id == asset_id):
            z = it.transform.zoom if it.transform else 1.0
            it.transform = Transform(cx=0.5, cy=0.5, zoom=z) if abs(z - 1) > 1e-3 else None    # the game, centred
            it.place = (0.0, top, 1.0, round(1.0 - top, 3))
            ctx.items.append(Item(id=ctx.iid("v"), track="V2", kind="video", asset_id=asset_id, src_in=it.src_in, src_out=it.src_out,
                                  rec_in=it.rec_in, speed=it.speed, transform=cam_tf, place=(0.0, 0.0, 1.0, top), role="facecam",
                                  ref=it.ref, transition_in=it.transition_in, transition_dur=it.transition_dur))
        ctx.suggest("layout", "Stacked for a vertical Short: your webcam on top, the game below — a plain 9:16 crop of the stream "
                    "would cut one of you out", conf=0.85, t=0.0, payload={"key": f"layout:{asset_id}"})


BIG_TOP = 0.52                 # stacked layout: the webcam panel's share of the frame while it is enlarged


def _cam_transform(fc: list[float], ds: tuple[int, int], panel_w: float, panel_h: float) -> Transform:
    """Crop of the webcam picture for a panel of panel_w × panel_h output pixels: centred on the webcam, zoomed just
    inside its border."""
    fx0, fy0, fx1, fy1 = fc
    src_ar, panel_ar = ds[0] / ds[1], panel_w / panel_h
    base_w, base_h = min(1.0, panel_ar / src_ar), min(1.0, src_ar / panel_ar)
    zoom = max(base_w / (fx1 - fx0), base_h / (fy1 - fy0)) * 1.03
    return Transform(cx=round((fx0 + fx1) / 2, 4), cy=round((fy0 + fy1) / 2, 4), zoom=round(zoom, 3))


def _facecam_moments(ctx: Ctx, polish: PolishPlan, applied_conf: float) -> None:
    """`facecam` cues: the streamer's webcam enlarged for a moment over the game (stacked Shorts: the webcam panel
    grows to half the frame; 16:9: the picture-in-picture doubles in its corner)."""
    for c in polish.effects:
        if c.type != "facecam" or c.at not in ctx.word_t:
            continue
        t = ctx.word_t[c.at] - 0.25
        host = next((i for i in ctx.items if i.track == "V1" and i.kind == "video" and i.asset_id and i.rec_in <= t < i.rec_out), None)
        fc = ctx.pa.clips[host.asset_id].facecam if host is not None else None
        if not fc:
            continue
        t0, t1 = max(host.rec_in, t), min(host.rec_out, t + (c.dur or 1.6))
        if t1 - t0 < 0.8:
            continue
        ds = ctx.pa.asset(host.asset_id).info.display_size or (1920, 1080)
        if ctx.layout_top or ctx.H > ctx.W:                  # vertical: the webcam over the top half (a plain 9:16 crop
            place = (0.0, 0.0, 1.0, BIG_TOP)                 # doesn't show the webcam's corner at all)
        else:                                                # 16:9: the picture-in-picture, twice as big, same corner
            fx0, fy0, fx1, fy1 = fc
            w, h = min(0.5, 2 * (fx1 - fx0)), min(0.5, 2 * (fy1 - fy0))
            x = fx0 if fx0 < 0.5 else min(1.0, fx1) - w
            y = fy0 if fy0 < 0.5 else min(1.0, fy1) - h
            place = (round(max(0.0, x), 4), round(max(0.0, y), 4), round(w, 4), round(h, 4))
        tf = _cam_transform(fc, ds, place[2] * ctx.W, place[3] * ctx.H)
        s_in = host.src_in + (t0 - host.rec_in) * host.speed
        on = c.confidence >= applied_conf
        if on:
            ctx.items.append(Item(id=ctx.iid("v"), track="V2", kind="video", asset_id=host.asset_id, src_in=round(s_in, 3),
                                  src_out=round(s_in + (t1 - t0) * host.speed, 3), rec_in=round(t0, 3), speed=host.speed, transform=tf,
                                  place=place, role="facecam_big", ref=f"fx:facecam:{c.at}"))
        ctx.suggest("facecam", c.why or "facecam enlarged on a big reaction", conf=c.confidence, t=t0,
                    payload={"key": f"fx:facecam:{c.at}"}, status=None if on else "optional")


def _apply_split_edits(ctx: Ctx, polish: PolishPlan, no: set) -> None:
    """Turn `split` cues into J/L cuts by moving only the picture cut. Audio items keep their word-snapped timing,
    so no word is ever clipped: a J-cut delays the next picture (its sound already started), an L-cut brings the
    next picture in early (the current voice carries on under it). Source frames must exist inside the same shot."""
    if "split" in no:
        return
    v1 = sorted((i for i in ctx.items if i.track == "V1"), key=lambda i: i.rec_in)
    for c in polish.effects:
        if c.type != "split" or c.confidence < 0.5 or not c.at.startswith("before:"):
            continue
        ref = c.at.split(":", 1)[1]
        k = next((j for j, i in enumerate(v1) if i.ref == ref), None)
        if not k:
            continue
        pv, nx = v1[k - 1], v1[k]
        if (pv.kind != "video" or nx.kind != "video" or abs(pv.rec_out - nx.rec_in) > 0.02 or nx.transition_in != "cut"
                or nx.rec_in < 3.0 or "meme" in (pv.role, nx.role) or abs(pv.speed - 1) > 1e-3 or abs(nx.speed - 1) > 1e-3):
            continue
        d = float(c.value or 0.4)
        if c.style == "J":
            sh = _shot_containing(ctx, pv.asset_id, pv.src_out - 0.01)
            room = (sh.t1 if sh else pv.src_out) - pv.src_out
            if room < d or nx.rec_dur - d < 1.0:
                continue
            pv.src_out = round(pv.src_out + d, 3)
            nx.src_in, nx.rec_in = round(nx.src_in + d, 3), round(nx.rec_in + d, 3)
            _shift_keys(nx, -d)
        else:
            sh = _shot_containing(ctx, nx.asset_id, nx.src_in + 0.01)
            room = nx.src_in - (sh.t0 if sh else nx.src_in)
            if room < d or pv.rec_dur - d < 1.0:
                continue
            pv.src_out = round(pv.src_out - d, 3)
            nx.src_in, nx.rec_in = round(nx.src_in - d, 3), round(nx.rec_in - d, 3)
            _shift_keys(nx, d)
        ctx.suggest("split", c.why, conf=c.confidence, t=nx.rec_in, items=[pv.id, nx.id],
                    payload={"key": f"fx:split:{c.at}", "style": c.style, "lead": d})


def _shot_containing(ctx: Ctx, asset_id: str | None, t: float):
    if not asset_id or asset_id not in ctx.pa.clips:
        return None
    return next((s for s in ctx.pa.clips[asset_id].shots if s.t0 - 1e-3 <= t <= s.t1 + 1e-3), None)


def _shift_keys(it: Item, dt: float) -> None:
    """Keep reframing keys aligned with the picture when an item's start moves by -dt (keys are item-relative)."""
    if it.transform and it.transform.keys:
        keys = [k.model_copy(update={"t": round(k.t + dt, 3)}) for k in it.transform.keys]
        it.transform.keys = [k for k in keys if k.t >= -1e-3] or keys[-1:]


def _face_lookup(ctx: Ctx):
    """t → the face on screen at timeline time t, as (x, y, w, h) in *output* coordinates (after the crop and any
    punch-in), or None. In a two-shot that is the person in the frame, not simply the biggest face in the source."""
    v1 = [i for i in ctx.items if i.track == "V1" and (i.kind == "video" or (i.kind == "image" and i.transform is not None))]

    def at(t: float):
        for it in v1:
            if not (it.rec_in <= t < it.rec_out):
                continue
            st = 0.0 if it.kind == "image" else it.src_in + (t - it.rec_in) * it.speed
            sh = next((s for s in ctx.pa.clips[it.asset_id].shots if s.t0 - 1e-3 <= st <= s.t1 + 1e-3), None)
            if sh is None:
                return None
            if sh.seats:
                boxes = [(s.x, s.y, s.w, s.h) for s in sh.seats]
            else:
                near = [f for f in sh.faces if abs(f.t - st) <= 1.0]
                if near:
                    boxes = [(f.x, f.y, f.w, f.h) for f in near]
                elif sh.faces and sh.track:            # between face samples: the tracked position, the usual face size
                    p = min(sh.track, key=lambda p: abs(p[0] - st))
                    boxes = [(p[1], p[2], float(np.median([f.w for f in sh.faces])), float(np.median([f.h for f in sh.faces])))]
                else:
                    return None
            ds = ctx.pa.asset(it.asset_id).info.display_size or (ctx.W, ctx.H)
            src_ar, out_ar = ds[0] / ds[1], ctx.W / ctx.H
            if it.transform is not None and it.transform.fit:       # the whole photo, a little above the middle
                s = min(ctx.W / ds[0], ctx.H / ds[1])
                fw, fh = ds[0] * s / ctx.W, ds[1] * s / ctx.H
                left, top = (1 - fw) / 2, (1 - fh) * 0.45
                shown = [(left + x * fw, top + y * fh, w * fw, h * fh) for x, y, w, h in boxes]
                return min(shown, key=lambda b: abs(b[1] - 0.46)) if shown else None
            if it.kind == "image" and it.transform is not None:     # a photo's own move: where it is at time t
                cx, cy, z = it.transform.at(t - it.rec_in)
                z = max(1.0, z)
            else:
                z = max(1.0, it.transform.zoom if it.transform else 1.0)
                cx, cy = (it.transform.cx, it.transform.cy) if it.transform else (0.5, 0.5)
            cw, ch = ((out_ar / src_ar) / z, 1.0 / z) if src_ar > out_ar else (1.0 / z, (src_ar / out_ar) / z)
            left, top = min(max(cx - cw / 2, 0.0), 1 - cw), min(max(cy - ch / 2, 0.0), 1 - ch)
            shown = [((x - left) / cw, (y - top) / ch, w / cw, h / ch) for x, y, w, h in boxes if left <= x <= left + cw]
            return min(shown, key=lambda b: abs(b[0] - 0.5)) if shown else None
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
        fixed = next((p[2].offset for p in parts if p[2].offset is not None), None)
        if fixed is not None:                     # the cut was built on this track's beats: start exactly there
            off, why = fixed, f"starts at {fixed:.1f}s, where the cut's beat grid begins"
        else:
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
