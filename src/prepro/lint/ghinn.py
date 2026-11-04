"""Ghinn guard: the explicit "would a viewer cringe?" rubric run on every cut.

Each check names one thing viewers hate in auto-edits — the "cuts fine, rhythm wrong / random good moments /
clipped words" family — measured on the compiled timeline. Results feed the scorecard (`no_cringe`) and the
EditLint findings, so every failed check is visible by name, and the safe ones carry a fix.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import knowledge as K
from ..schema.analysis import ProjectAnalysis
from ..schema.plan import Direction
from ..schema.timeline import Timeline

MOVING = ("pan_left", "pan_right", "tilt_up", "tilt_down", "whip_in", "whip_out")
SERIOUS = {"sad", "serious", "sponsor", "tension", "nostalgic"}


@dataclass
class Check:
    id: str
    ok: bool
    detail: str
    t: float | None = None
    weight: float = 1.0


def _shot_at(pa: ProjectAnalysis, asset_id: str, t: float):
    return next((s for s in pa.clips[asset_id].shots if s.t0 - 1e-3 <= t <= s.t1 + 1e-3), None)


def _activity(sh, a: float, b: float) -> float:
    if sh is None or sh.camera_move in MOVING:
        return 1.0
    if not sh.track and not sh.action_peaks:
        return 0.5
    pts = [t for t, _x, _y in sh.track if a - 0.25 <= t <= b + 0.25]
    cov = min(1.0, len(pts) / max(1.0, (b - a) * 2.0))
    if any(a - 0.3 <= p <= b + 0.3 for p in sh.action_peaks):
        cov = max(cov, 0.8)
    return cov


def checks(tl: Timeline, pa: ProjectAnalysis, d: Direction | None) -> list[Check]:
    out: list[Check] = []
    pb = K.playbook(d.playbook) if d else None
    v1 = sorted((i for i in tl.items if i.track == "V1" and i.kind == "video" and i.asset_id), key=lambda i: i.rec_in)
    minutes = max(tl.duration / 60, 0.5)

    # 1. empty frames: a B-roll moment where nothing happens (static camera, no tracked subject, no action)
    empty = []
    for it in v1:
        a = pa.asset(it.asset_id)
        if a.kind.value != "broll" or it.role == "meme":
            continue
        sh = _shot_at(pa, it.asset_id, (it.src_in + it.src_out) / 2)
        if sh is not None and sh.track and _activity(sh, it.src_in, it.src_out) < 0.3:
            empty.append(it)
    out.append(Check("empty_frames", not empty, f"{len(empty)} moment(s) where nothing happens on screen" if empty else "every moment has something in it",
                     empty[0].rec_in if empty else None, 1.5))

    # 2. the same moment twice (same source, overlapping windows)
    seen: list = []
    dup = None
    for it in v1:
        for o in seen:
            if o.asset_id == it.asset_id and min(o.src_out, it.src_out) - max(o.src_in, it.src_in) > 0.25 and it.role not in ("hook", "flashforward", "replay") \
                    and o.role not in ("flashforward", "hook"):
                dup = it
        seen.append(it)
    out.append(Check("repeated_moment", dup is None, "the same moment appears twice" if dup else "no moment repeats", dup.rec_in if dup else None, 1.5))

    # 3. effects without a reason (every applied decision must say why)
    unmotivated = [s for s in tl.suggestions if s.status == "applied" and s.type in ("zoom", "sfx", "meme", "transition", "speed", "text")
                   and len((s.reason or "").strip()) < 6]
    out.append(Check("unmotivated_effects", not unmotivated, f"{len(unmotivated)} effect(s) without a stated reason" if unmotivated else "every effect has a reason",
                     unmotivated[0].t if unmotivated else None, 1.0))

    # 4. effect density vs the genre's budget
    if pb is not None:
        over = []
        for kind, typ in (("zoom", "zoom"), ("sfx", "sfx"), ("meme", "meme"), ("transition", "transition")):
            n = sum(1 for s in tl.suggestions if s.status == "applied" and s.type == typ and not s.payload.get("reframe"))
            budget = pb.budget(kind) * minutes
            if n > max(2.0, budget * 1.6 + 0.5):
                over.append(f"{n} {kind}s (≈{budget:.0f} expected)")
        out.append(Check("effect_density", not over, ", ".join(over) if over else "effects within the genre's norm", None, 1.2))

    # 5. music that stops dead instead of fading or ending on its outro
    a2 = sorted((i for i in tl.items if i.track == "A2"), key=lambda i: i.rec_out)
    abrupt = bool(a2) and a2[-1].fade_out < 0.4 and a2[-1].rec_out < tl.duration - 0.3
    out.append(Check("music_ending", not abrupt, "the music stops dead" if abrupt else "music ends cleanly", a2[-1].rec_out if abrupt else None, 1.0))

    # 6. on-screen text too short to read (≈ 3 words per second + 0.6 s to find it)
    fast = [i for i in tl.items if i.kind == "text" and i.text and (i.duration or 0) < 0.6 + len(i.text.split()) / 3.0]
    out.append(Check("text_reading_time", not fast, f"“{fast[0].text}” is on screen too briefly to read" if fast else "text stays up long enough to read",
                     fast[0].rec_in if fast else None, 1.0))

    # 7. loudness jumps between talking clips (one clip much quieter than the next, uncorrected)
    a1 = sorted((i for i in tl.items if i.track == "A1" and i.role not in ("natural",) and i.asset_id), key=lambda i: i.rec_in)
    jump = None
    for x, y in zip(a1, a1[1:], strict=False):
        if x.asset_id == y.asset_id:
            continue
        lx = pa.clips[x.asset_id].audio.lufs if pa.clips[x.asset_id].audio else None
        ly = pa.clips[y.asset_id].audio.lufs if pa.clips[y.asset_id].audio else None
        if lx is not None and ly is not None and abs((lx + x.gain_db) - (ly + y.gain_db)) > 8:
            jump = y
            break
    out.append(Check("loudness_jump", jump is None, "a big loudness jump between two talking clips" if jump else "talking clips sit at a similar level",
                     jump.rec_in if jump else None, 0.8))

    # 8. jump cuts with identical framing (the "stitched" look)
    jc = None
    for x, y in zip(v1, v1[1:], strict=False):
        if x.asset_id == y.asset_id and y.src_in > x.src_out + 0.05 and y.transition_in == "cut" and pa.asset(x.asset_id).kind.value != "screen" \
                and "replay" not in (x.role, y.role):
            zx = x.transform.zoom if x.transform else 1.0
            zy = y.transform.zoom if y.transform else 1.0
            covered = any(o.track == "V2" and o.rec_in <= y.rec_in <= o.rec_out for o in tl.items)
            if abs(zx - zy) < 0.03 and not covered:
                jc = y
                break
    out.append(Check("jump_cut_framing", jc is None, "a jump cut with the same framing on both sides" if jc else "jump cuts are reframed or covered",
                     jc.rec_in if jc else None, 0.8))

    # 9. a meme in a serious / sad / sponsor moment
    memes = [i for i in tl.items if i.track == "V1" and i.role == "meme"]
    bad_meme = None
    for m in memes:
        before = [i for i in a1 if i.rec_out <= m.rec_in + 0.05]
        if before:
            seg = next((s for s in pa.clips[before[-1].asset_id].transcript.segments if before[-1].ref == s.id), None) if pa.clips[before[-1].asset_id].transcript else None
            if seg is not None and set(seg.tags) & SERIOUS:
                bad_meme = m
    out.append(Check("meme_tone", bad_meme is None, "a meme right after a serious moment" if bad_meme else "memes only after light moments",
                     bad_meme.rec_in if bad_meme else None, 1.2))
    return out


def score(cs: list[Check]) -> float:
    total = sum(c.weight for c in cs) or 1.0
    bad = sum(c.weight for c in cs if not c.ok)
    return round(max(0.0, 10.0 * (1 - bad / total)), 1)
