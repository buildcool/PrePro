"""The Basic brain: a rules-only editor (no AI, nothing leaves the PC).

It encodes the playbooks: hook selection, per-genre story structures, soundtrack modes, restraint
budgets, motivated effects. AI connectors produce the same plan objects with better judgement; the
compiler and the quality gate treat both identically.
"""

from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

from .. import knowledge as K
from ..assist.music import brief_for, rank_tracks, soundtrack_mode
from ..schema.analysis import ProjectAnalysis, Segment, Shot
from ..schema.brief import CreatorBrief
from ..schema.media import AssetKind
from ..schema.plan import (
    BrollGap,
    Direction,
    DirectionSet,
    EffectCue,
    HookOption,
    Knobs,
    MusicCue,
    PolishPlan,
    StoryItem,
    StoryPlan,
    StorySection,
)

NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100}
CURRENCY = {"rupees": "₹", "rupee": "₹", "rs": "₹", "dollars": "$", "dollar": "$", "euros": "€"}
STOP = set(["so", "okay", "ok", "well", "um", "uh", "like", "basically", "actually", "today", "we", "are", "i", "am", "it", "is", "the", "a", "an", "and", "but", "just", "really", "very", "honestly", "now", "this", "that", "these", "those", "here", "there"])
MEME_KEYWORDS = {
    "shock": ["shock", "what", "wait", "surprise", "pikachu", "omg", "boom"],
    "fail": ["fail", "bruh", "facepalm", "damage", "oops", "sad"],
    "irony": ["irony", "fine", "wait"],
    "roast": ["damage", "roast", "burn"],
    "hype": ["hype", "airhorn", "lets", "go", "win"],
}
LOOK_BY_PLAYBOOK = {"story_vlog": "warm", "travel_film": "teal_orange", "hype_reel": "punchy", "aesthetic": "pastel", "teaser": "teal_orange",
                    "talking_head": "natural", "podcast_clip": "natural", "gaming": "punchy", "comedy": "natural"}


def words_to_digits(text: str) -> str:
    text = re.sub(r"\b(a|one)\s+(million|billion)\b", lambda m: "1" + ("M" if m.group(2).lower() == "million" else "B"), text, flags=re.I)
    toks = text.split()
    out = []
    i = 0
    while i < len(toks):
        w = re.sub(r"[^\w]", "", toks[i].lower())
        if w in NUMS and i + 1 < len(toks) and re.sub(r"[^\w]", "", toks[i + 1].lower()) in ("million", "billion"):
            out.append(f"{NUMS[w]}{'M' if 'million' in toks[i + 1].lower() else 'B'}")
            i += 2
            continue
        if w in NUMS:
            val = NUMS[w]
            j = i + 1
            while j < len(toks):
                nxt = re.sub(r"[^\w]", "", toks[j].lower())
                if nxt == "thousand":
                    val *= 1000
                elif nxt == "hundred":
                    val *= 100
                elif nxt in ("lakh", "lakhs"):
                    val *= 100000
                else:
                    break
                j += 1
            out.append(str(val) + ("" if not re.search(r"[!?.,]$", toks[j - 1]) else toks[j - 1][-1]))
            i = j
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)


def text_hook(seg_text: str, max_words: int = 6) -> str:
    """'So today we are in Goa and I spent only five thousand rupees for three full days.' → '₹5000 for 3 days?!'"""
    t = words_to_digits(seg_text)
    t = re.sub(r"[\"“”]", "", t)
    clauses = re.split(r"[,.;!?]|\band\b|\bbut\b", t)
    clauses = [c.strip() for c in clauses if c.strip()]
    best = max(clauses, key=lambda c: (bool(re.search(r"\d", c)), len(c.split()) <= 9, -abs(len(c.split()) - 6))) if clauses else t
    words = []
    toks = best.split()
    for k, w in enumerate(toks):
        lw = re.sub(r"[^\w]", "", w.lower())
        if lw in STOP or lw in ("only", "full", "spent", "i", "me", "my", "for") and not words:
            continue
        if lw in CURRENCY and words and re.match(r"^\d+$", words[-1]):
            words[-1] = CURRENCY[lw] + words[-1]
            continue
        if lw in ("full", "only") and k + 1 < len(toks):
            continue
        words.append(w.strip(",.;"))
    words = words[:max_words]
    if not words:
        return ""
    s = " ".join(words)
    s = s[0].upper() + s[1:]
    if re.search(r"\d", s) and not s.endswith(("?", "!")):
        s += "?!"
    return s


class BasicBrain:
    name = "basic"

    def __init__(self, pa: ProjectAnalysis, brief: CreatorBrief | None = None):
        self.pa = pa
        self.brief = brief or CreatorBrief()
        self.assets = {a.id: a for a in pa.assets}
        self.rules = self.brief.rules
        self.excluded = {r.target for r in self.rules if r.kind == "must_exclude" and r.target}
        self.included = {r.target for r in self.rules if r.kind == "must_include" and r.target}
        self.no = {r.target for r in self.rules if r.kind == "no_effect"}

    # ------------------------------------------------------------ material
    def talk_assets(self):
        return sorted((a for a in self.pa.assets if a.kind in (AssetKind.AROLL, AssetKind.SCREEN, AssetKind.VOICEOVER) and self.pa.clips[a.id].transcript),
                      key=lambda a: self.pa.clips[a.id].order_key)

    def is_cut_candidate(self, s: Segment) -> str | None:
        if s.id in self.included:
            return None
        if s.id in self.excluded or s.asset_id in self.excluded:
            return "excluded by your brief"
        if s.retake_rank > 0:
            return "earlier take of a line you repeated (kept the last, cleanest take)"
        if s.false_start:
            return "false start"
        if "greeting" in s.tags:
            return "greeting before the hook (viewers leave during slow intros)"
        if "hesitation" in s.tags:
            return "hesitation / filler"
        if "micro" in s.tags and "numbers" not in s.tags and not s.text.strip().endswith("!"):
            return "stray fragment"
        if s.filler_ratio > 0.6:
            return "mostly filler words"
        return None

    def usable_segments(self) -> list[Segment]:
        out = []
        for a in self.talk_assets():
            for s in self.pa.clips[a.id].transcript.segments:
                if not self.is_cut_candidate(s):
                    out.append(s)
        return out

    def good_shots(self, kinds=(AssetKind.BROLL,)) -> list[Shot]:
        out = []
        for a in sorted(self.pa.assets, key=lambda a: self.pa.clips[a.id].order_key):
            if a.kind not in kinds:
                continue
            for s in self.pa.clips[a.id].shots:
                if s.id in self.excluded or a.id in self.excluded:
                    continue
                bad = set(s.flags) & {"dark", "blurry", "shaky", "pocket"}
                if bad and s.id not in self.included and a.id not in self.included:
                    continue
                if s.dup_group and s.dup_rank > 0 and s.id not in self.included:
                    continue
                out.append(s)
        return out

    def cluster_of(self, asset_id: str) -> tuple:
        ca = self.pa.clips[asset_id]
        return (ca.day_index or 0, ca.place_cluster if ca.place_cluster is not None else -1)

    def clusters(self) -> list[tuple]:
        seen = []
        for a in sorted(self.pa.assets, key=lambda a: self.pa.clips[a.id].order_key):
            if a.kind in (AssetKind.AROLL, AssetKind.BROLL, AssetKind.SCREEN):
                c = self.cluster_of(a.id)
                if c not in seen:
                    seen.append(c)
        return seen

    def cluster_label(self, c: tuple) -> str:
        day, pc = c
        place = next((self.pa.clips[a.id].place for a in self.pa.assets if self.cluster_of(a.id) == c and self.pa.clips[a.id].place), None)
        bits = []
        if day and self.pa.stats.get("days", 0) > 1:
            bits.append(f"Day {day}")
        if place:
            bits.append(place)
        return " · ".join(bits)

    # ------------------------------------------------------------ hooks
    def speech_hook_score(self, s: Segment, rank_in_clip: int) -> float:
        wm = {w.id: w for w in self.pa.words(s.asset_id)}
        emph = max((wm[w].emphasis for w in s.word_ids if w in wm), default=0.0)
        dur = s.t1 - s.t0
        sc = 0.32 * ("numbers" in s.tags) + 0.22 * ("question" in s.tags) + 0.12 * min(1.0, emph / 2.0)
        sc += 0.08 * min(1.0, max(0.0, s.energy + 3) / 6) + 0.1 * (rank_in_clip <= 2) + 0.1 * (2.0 <= dur <= 12.0)
        sc -= 0.4 * ("cta" in s.tags) + 0.5 * ("greeting" in s.tags)
        if re.search(r"\b(only|never|best|worst|most|secret|mistakes?|nobody|everyone|unreal|insane|crazy)\b", s.text, re.I):
            sc += 0.12
        return round(sc, 3)

    def shot_hook_why(self, s: Shot, kind: str) -> str:
        """Why a shot could open the video, in words (asset ids only — never file names, this can reach an AI prompt)."""
        a = self.pa.asset(s.asset_id)
        ca = self.pa.clips[s.asset_id]
        what = s.desc or (" / ".join(s.tags[:2]) if s.tags else None)
        move = {"pan_right": "a pan", "pan_left": "a pan", "tilt_up": "a tilt up", "tilt_down": "a tilt down", "push_in": "a push-in",
                "static": "a steady frame", "shaky": "a handheld shot", "whip_out": "a whip pan"}.get(s.camera_move, "a shot")
        where = f" at {ca.place}" if ca.place else ""
        fps = a.info.fps or 30
        if kind == "peak_moment" and s.action_peaks:
            t = s.action_peaks[0]
            extra = f", {fps:.0f} fps so it can go real slow-mo" if fps >= 48 else ""
            return f"open on the action{where}: {what or move} ({a.id} at {t:.1f} s{extra}) — movement in frame 1 stops the scroll"
        return f"open on the most striking frame{where}: {what or move} ({a.id}) — a strong image before any words"

    def hook_options(self, playbook: str) -> list[HookOption]:
        pb = K.playbook(playbook)
        opts: list[HookOption] = []
        forced = next((r for r in self.rules if r.kind == "hook" and r.target), None)
        if forced:
            seg = self._seg(forced.target)
            opts.append(HookOption(id="h0", kind="from_brief", refs=[forced.target], text_hook=text_hook(seg.text) if seg else None,
                                   why=f"you asked: “{forced.anchor}”", score=1.0))
        talk_ok = playbook not in ("travel_film", "hype_reel", "aesthetic")
        if talk_ok:
            per_clip = defaultdict(int)
            cands = []
            for s in self.usable_segments():
                per_clip[s.asset_id] += 1
                cands.append((self.speech_hook_score(s, per_clip[s.asset_id]), s))
            cands.sort(key=lambda x: -x[0])
            for sc, s in cands[:3]:
                if forced and s.id == forced.target:
                    continue
                kind = "bold_claim" if "numbers" in s.tags else "question" if "question" in s.tags else "curiosity_gap"
                opts.append(HookOption(id=f"h{len(opts)}", kind=kind, refs=[s.id], text_hook=text_hook(s.text),
                                       why=f"{kind.replace('_', ' ')}: “{s.text[:70]}”", score=sc))
        shots = self.good_shots((AssetKind.BROLL, AssetKind.SCREEN))
        vis = sorted(shots, key=lambda s: -(s.quality * 0.5 + min(1.0, s.motion / 0.12) * 0.25 + 0.25 * bool(s.action_peaks)
                                            * (1.0 if (self.assets[s.asset_id].info.fps or 30) >= 48 else 0.6)))
        for s in vis[:2]:
            kind = "peak_moment" if s.action_peaks else "visual_spectacle"
            opts.append(HookOption(id=f"h{len(opts)}", kind=kind, refs=[s.id], why=self.shot_hook_why(s, kind),
                                   score=round(0.3 + 0.25 * s.quality + 0.15 * bool(s.action_peaks) + (0.2 if not talk_ok else 0), 3)))
        allowed = set(pb.hooks) | {"from_brief"}
        opts.sort(key=lambda o: (-(o.score + (0.1 if o.kind in allowed else 0))))
        return opts[:3]

    def _seg(self, sid: str) -> Segment | None:
        try:
            return self.pa.segment(sid)
        except KeyError:
            return None

    def _shot(self, sid: str) -> Shot | None:
        try:
            return self.pa.shot(sid)
        except KeyError:
            return None

    # ------------------------------------------------------------ directions
    def directions(self, max_n: int = 4) -> DirectionSet:
        prefs = self.brief.prefs
        keys: list[tuple[str, float, str, bool]] = []
        if prefs.playbook:
            keys.append((prefs.playbook, 1.0, "what your brief asked for", True))
        for g in self.pa.genres:
            if g.score >= 0.35 and g.playbook not in [k[0] for k in keys]:
                keys.append((g.playbook, g.score, g.why, False))
        if not keys:
            keys = [("story_vlog", 0.4, "default", False)]
        speech_ok = sum(s.t1 - s.t0 for s in self.usable_segments())
        # a long shot holds several usable moments — only where something happens, and at most three per angle:
        # cutting back to the same three angles over and over is what makes a montage feel stitched together
        good = self.good_shots()
        broll_ok = sum(min(s.dur, 5.0 + 3.5 * min(2, max(0, self._active_moments(s) - 1))) for s in good)
        self._variety = min(1.0, len(good) / 6.0)
        vertical = sum(1 for a in self.pa.assets if a.info.is_vertical and a.kind in (AssetKind.AROLL, AssetKind.BROLL))
        horizontal = sum(1 for a in self.pa.assets if a.info.has_video and not a.info.is_vertical and a.kind in (AssetKind.AROLL, AssetKind.BROLL))
        out = []
        for i, (pbk, score, why, from_brief) in enumerate(keys[:max_n]):
            pb = K.playbook(pbk)
            aspect = (prefs.aspect if from_brief or (prefs.aspect and i == 0) else None) or pb.aspect
            if not from_brief and pbk in ("story_vlog", "gaming") and vertical > horizontal:
                aspect = "9:16"
            target = self.target_length(pbk, speech_ok, broll_ok)
            if (from_brief or i == 0) and prefs.target_length:
                target = prefs.target_length
            for r in self.rules:
                if r.kind == "max_length" and isinstance(r.value, (int, float)):
                    target = min(target, float(r.value))
            cap_default = pb.captions.get("default", "clean")
            if aspect == "9:16" and pbk in ("story_vlog", "talking_head", "podcast_clip", "comedy", "gaming") and cap_default == "clean":
                cap_default = "bold"      # reels/shorts are watched on mute: word-pop captions
            knobs = Knobs(pace=prefs.pace if prefs.pace is not None else {"hype_reel": 0.9, "teaser": 0.8, "aesthetic": 0.25, "travel_film": 0.6}.get(pbk, 0.5),
                          effects=prefs.effects or "balanced", captions=prefs.captions or cap_default,
                          humour=prefs.humour or ("light" if pb.memes in ("light", "allowed", "comedic_only") else "off"),
                          target_length=target, freedom=prefs.freedom, look=prefs.look or LOOK_BY_PLAYBOOK.get(pbk),
                          meme_flavour=prefs.meme_flavour or "global")
            if "captions" in {r.kind for r in self.rules if r.value == "off"}:
                knobs.captions = "off"
            hooks = self.hook_options(pbk)
            d = Direction(id=f"d{i + 1}", playbook=pbk, name=self.direction_name(pbk, aspect, target), aspect=aspect,
                          target_min=round(max(5.0, target * 0.85), 1), target_max=round(target * 1.15, 1), fit_score=round(score, 3),
                          why=why, hooks=hooks, knobs=knobs, from_brief=from_brief)
            d.outline = self.outline(d)
            d.coverage_gaps = self.coverage_gaps(d)
            out.append(d)
        notes = f"{len(self.usable_segments())} usable talking segments ({speech_ok:.0f}s), {len(self.good_shots())} usable B-roll shots"
        return DirectionSet(directions=out, notes=notes)

    def target_length(self, pbk: str, speech_ok: float, broll_ok: float) -> float:
        pb = K.playbook(pbk)
        lo, hi = pb.target
        if pbk == "comedy":
            est = speech_ok * 1.25 + 3.0        # dialogue + the beats around punchlines + a meme cutaway or two
        elif pbk in ("story_vlog", "talking_head", "podcast_clip"):
            est = speech_ok * 0.98 + (min(broll_ok, speech_ok * 0.5) * 0.35 if pbk == "story_vlog" else 0)
        elif pbk == "gaming":
            est = speech_ok * 0.9 + 6
        elif pbk == "travel_film":
            est = broll_ok * 0.55 * (0.5 + 0.5 * getattr(self, "_variety", 1.0))    # few angles → shorter film
        elif pbk == "hype_reel":
            est = 15.0 if broll_ok >= 12 else max(8.0, broll_ok * 0.8)
        elif pbk == "teaser":
            est = 20.0
        else:  # aesthetic
            est = min(45.0, broll_ok * 0.6 + speech_ok)
        if pbk == "talking_head" and est > 90:
            est = 75.0
        return round(float(np.clip(est, min(lo, est), hi)), 1)

    def direction_name(self, pbk: str, aspect: str, target: float) -> str:
        pb = K.playbook(pbk)
        fmt = "Reel/Short" if aspect == "9:16" else "YouTube"
        t = f"{target / 60:.0f} min" if target >= 120 else f"{target:.0f} s"
        return f"{pb.name} · {fmt} · ~{t}"

    def outline(self, d: Direction) -> list[str]:
        pb = K.playbook(d.playbook)
        lines = []
        if d.hooks:
            h = d.hooks[0]
            ref = h.refs[0] if h.refs else ""
            seg = self._seg(ref)
            lines.append(f"Hook ({h.kind.replace('_', ' ')}): " + (f"“{seg.text[:60]}”" if seg else f"shot {ref}"))
        for c in self.clusters()[:6]:
            lab = self.cluster_label(c) or "Main"
            nseg = sum(1 for s in self.usable_segments() if self.cluster_of(s.asset_id) == c)
            nshot = sum(1 for s in self.good_shots() if self.cluster_of(s.asset_id) == c)
            lines.append(f"{lab}: {nseg} talking beats, {nshot} shots")
        lines.append("Structure: " + " → ".join(pb.structure))
        return lines

    def coverage_gaps(self, d: Direction) -> list[str]:
        gaps = []
        shots = self.good_shots()
        for c in self.clusters():
            cs = [s for s in shots if self.cluster_of(s.asset_id) == c]
            est = [s for s in cs if s.face_ratio < 0.2 and (s.camera_move.startswith("pan") or s.camera_move in ("static", "tilt_up")) and s.quality >= 0.6]
            if d.playbook in ("story_vlog", "travel_film") and not est:
                gaps.append(f"No establishing shot for {self.cluster_label(c) or 'this place'} — a steady 3-second wide helps viewers orient.")
        segs = self.usable_segments()
        if d.playbook in ("story_vlog", "talking_head", "podcast_clip") and not any("cta" in s.tags for s in segs):
            gaps.append("No call-to-action line — record a 5-second 'follow for part 2' outro.")
        if d.hooks and d.hooks[0].score < 0.35 and d.playbook in ("story_vlog", "talking_head", "podcast_clip", "comedy"):
            gaps.append("No strong hook line — record one sentence that teases the best moment or the payoff.")
        if d.playbook in ("hype_reel", "travel_film", "teaser", "aesthetic") and 0 < len(shots) < 6:
            gaps.append(f"Only {len(shots)} distinct B-roll shot{'s' if len(shots) > 1 else ''} — film more angles and details "
                        "(a wide, a medium and a close-up per place) so the montage doesn't keep cutting back to the same view.")
        if d.playbook in ("hype_reel", "travel_film", "teaser") and not any((self.assets[s.asset_id].info.fps or 30) >= 48 for s in shots):
            gaps.append("No high-frame-rate clips — shoot 60/120 fps for real slow-motion.")
        for a in self.talk_assets():
            iss = self.pa.clips[a.id].audio.issues
            if iss:
                gaps.append(f"{a.name}: {iss[0]} — a clip-on mic or a quieter spot will help next time.")
        if d.playbook in ("story_vlog", "talking_head") and segs:
            covered = len(self.good_shots())
            if covered < max(2, len(segs) // 3):
                gaps.append(f"Only {covered} usable B-roll shots for {len(segs)} talking beats — film close-ups of what you talk about.")
        return gaps[:8]

    # ------------------------------------------------------------ story
    def story(self, d: Direction) -> StoryPlan:
        fn = getattr(self, f"_story_{d.playbook}", None) or self._story_story_vlog
        sp = fn(d)
        if d.playbook in ("story_vlog", "teaser", "gaming") and "open_loop" not in self.no:
            self._open_loop(d, sp)
        return sp

    def _open_loop(self, d: Direction, sp: StoryPlan) -> None:
        """Flash-forward: right after the hook, 1–1.5 s of the payoff that comes in the last third — an open loop the
        cut then pays off. One per video; only when the payoff is a real action moment that stays in the cut."""
        if len(sp.items) < 4 or any(it.role == "flashforward" for it in sp.items):
            return
        est, times = 0.0, []
        for it in sp.items:
            seg, shot = self._seg(it.ref), self._shot(it.ref)
            dur = (it.t1 - it.t0) if it.t0 is not None and it.t1 is not None else ((seg.t1 - seg.t0) if seg else (min(3.0, shot.dur) if shot else 2.0))
            times.append(est)
            est += dur
        if est < 25:
            return
        hook_refs = {sp.items[0].ref}
        late = [(t, it) for t, it in zip(times, sp.items, strict=True) if t >= est * 0.6 and it.ref not in hook_refs and self._shot(it.ref)]
        best = None
        for _t, it in late:
            sh = self._shot(it.ref)
            a = it.t0 if it.t0 is not None else sh.t0
            b = it.t1 if it.t1 is not None else sh.t1
            peaks = [p for p in sh.action_peaks if a <= p <= b]
            if peaks and sh.quality >= 0.6 and not set(sh.flags) & {"dark", "blurry", "shaky", "pocket"}:
                score = sh.quality + 0.3 * len(peaks) + 0.2 * ((self.assets[sh.asset_id].info.fps or 30) >= 48)
                if best is None or score > best[0]:
                    best = (score, sh, peaks[0])
        if best is None:
            return
        _s, sh, peak = best
        t0 = max(sh.t0, peak - 0.6)
        ff = StoryItem(ref=sh.id, role="flashforward", t0=round(t0, 3), t1=round(min(sh.t1, t0 + 1.3), 3), section=sp.items[0].section,
                       note="flash-forward of the payoff: an open loop the video pays off later")
        sp.items.insert(1, ff)

    def _rehooks(self, d: Direction, story: StoryPlan, pp: PolishPlan) -> None:
        """Re-hooks: a fresh reason to keep watching at the start of a later part — its own question / number / "but"
        line put on screen. Shorts: one every 20–30 s after the first 30 s; long-form: every 2–3 minutes."""
        if d.playbook not in ("story_vlog", "talking_head", "podcast_clip", "gaming", "comedy") or "text" in self.no:
            return
        vertical = d.aspect == "9:16"
        first, every = (30.0, 25.0) if vertical else (150.0, 150.0)
        t, last = 0.0, -1e9
        taken = {c.at for c in pp.effects if c.type == "text"}
        for it in story.items:
            seg = self._seg(it.ref)
            shot = self._shot(it.ref)
            dur = (it.t1 - it.t0) if it.t0 is not None and it.t1 is not None else ((seg.t1 - seg.t0) if seg else (min(3.0, shot.dur) if shot else 2.0))
            if seg is not None and t >= first and t - last >= every and it.role not in ("hook", "cta", "outro") and seg.id not in taken:
                strong = ("question" in seg.tags or "numbers" in seg.tags
                          or re.match(r"^\s*(but|so here|now|the best part|the worst|wait|here's|and then)\b", seg.text, re.I))
                words = ""
                if strong:
                    from ..packaging import thumb_text

                    words = thumb_text(seg.text, max_words=5)
                    if len(words.split()) < 2:
                        words = ""
                if words:
                    hold = round(max(2.0, 0.9 + len(words.split()) / 2.5), 1)
                    pp.effects.append(EffectCue(type="text", at=seg.id, text=words, style="callout", dur=hold, confidence=0.7, intent="rehook",
                                                why=f"re-hook at {t:.0f}s: put “{words}” on screen — a fresh reason to keep watching"))
                    if "sfx" not in self.no and K.playbook(d.playbook).budget("sfx") > 0:
                        pp.effects.append(EffectCue(type="sfx", at=f"before:{seg.id}", asset=self._pick_sfx("riser"), confidence=0.6,
                                                    why="soft riser into the re-hook"))
                    last = t
            t += dur

    def _hook_item(self, d: Direction, used: set) -> list[StoryItem]:
        if not d.hooks:
            return []
        h = d.hooks[0]
        ref = h.refs[0]
        if self._seg(ref):
            used.add(ref)
            return [StoryItem(ref=ref, role="hook", section="cold_open", note=h.why)]
        sh = self._shot(ref)
        if sh:
            used.add(ref)
            t0, t1 = self._window(sh, 1.6 if d.playbook in ("hype_reel", "teaser") else 2.4, around=sh.action_peaks[0] if sh.action_peaks else None)
            return [StoryItem(ref=ref, role="hook", t0=t0, t1=t1, section="cold_open", note=h.why)]
        return []

    MOVING = ("pan_left", "pan_right", "tilt_up", "tilt_down", "whip_in", "whip_out")

    def _activity(self, s: Shot, a: float, b: float) -> float:
        """How much is happening in a moment: a tracked subject on screen or an action peak (0..1).
        A moving camera carries the shot by itself; without tracker data the answer is "unknown" (0.5)."""
        if s.camera_move in self.MOVING:
            return 1.0
        if not s.track and not s.action_peaks:
            return 0.5
        pts = [t for t, _x, _y in s.track if a - 0.25 <= t <= b + 0.25]
        cov = min(1.0, len(pts) / max(1.0, (b - a) * 2.0))      # tracks are sampled at ~2 Hz
        if any(a - 0.3 <= p <= b + 0.3 for p in s.action_peaks):
            cov = max(cov, 0.8)
        return cov

    def _candidates(self, s: Shot, dur: float):
        """Moments of a shot, best first: its best windows, then every half-second position."""
        seen = []
        for w in sorted(s.best, key=lambda w: -w.score):
            mid = (w.t0 + w.t1) / 2
            a = min(max(s.t0, mid - dur / 2), s.t1 - dur)
            seen.append(round(max(s.t0, a), 3))
        a = s.t0
        while a + dur <= s.t1 + 1e-6:
            seen.append(round(a, 3))
            a += max(0.5, dur / 2)
        out = []
        for a in seen:
            if a not in out:
                out.append(a)
        return out

    def _active_moments(self, s: Shot, dur: float = 3.5) -> int:
        """How many distinct, non-overlapping moments of `dur` seconds in this shot have something happening."""
        n, last = 0, -1e9
        for a in sorted(self._candidates(s, min(dur, s.dur))):
            if a >= last + dur and self._activity(s, a, a + min(dur, s.dur)) >= 0.5:
                n += 1
                last = a
        return max(1, n) if s.dur <= dur else n

    def _align(self, s: Shot, a: float, dur: float) -> float:
        """Start the moment as the subject enters, not on the empty frame before it (static shots with tracks)."""
        if s.camera_move in self.MOVING or not s.track:
            return a
        pts = sorted(t for t, _x, _y in s.track if a <= t <= a + dur)
        if pts and pts[0] - a > 0.4:
            a = min(pts[0] - 0.2, s.t1 - dur)
        return max(s.t0, a)

    def _fresh_window(self, s: Shot, dur: float, taken: list[tuple[float, float]]) -> tuple[float, float] | None:
        """A moment of shot `s` that doesn't overlap the moments already used (≥ 0.5 s apart) and has something
        happening in it — an editor never cuts to an empty frame just to fill time."""
        dur = min(dur, s.dur)

        def free(a: float, b: float) -> bool:
            return all(b <= x - 0.5 or a >= y + 0.5 for x, y in taken)

        best, best_act = None, 0.0
        for a in self._candidates(s, dur):
            if not free(a, a + dur):
                continue
            act = self._activity(s, a, a + dur)
            if act > best_act + 1e-6:
                best, best_act = a, act
            if act >= 0.8:
                break
        if best is None or best_act < 0.4:
            return None
        if best_act < 0.8:
            moved = self._align(s, best, dur)
            if free(moved, moved + dur):
                best = moved
        return round(best, 3), round(best + dur, 3)

    def _window(self, s: Shot, dur: float, around: float | None = None) -> tuple[float, float]:
        dur = min(dur, s.dur)
        if around is not None:
            t0 = min(max(s.t0, around - dur / 2), s.t1 - dur)
        else:
            # the best-scoring moment that actually has something happening in it
            cands = self._candidates(s, dur)
            t0 = next((a for a in cands if self._activity(s, a, a + dur) >= 0.5), None)
            if t0 is None:
                t0 = max(cands, key=lambda a: self._activity(s, a, a + dur)) if cands else s.t0 + (s.dur - dur) / 2
            if self._activity(s, t0, t0 + dur) < 0.8:
                t0 = self._align(s, t0, dur)
        t0 = max(s.t0, t0)
        return round(t0, 3), round(t0 + dur, 3)

    def _story_story_vlog(self, d: Direction) -> StoryPlan:
        used: set = set()
        items = self._hook_item(d, used)
        sections = [StorySection(name="cold_open")]
        segs = self.usable_segments()
        shots = self.good_shots()
        budget = d.knobs.target_length or 120
        pb = K.playbook(d.playbook)
        cta = [s for s in segs if "cta" in s.tags]
        clusters = self.clusters()
        for ci, c in enumerate(clusters):
            name = f"part{ci + 1}"
            sections.append(StorySection(name=name, card=self.cluster_label(c) or None))
            cs = [s for s in shots if self.cluster_of(s.asset_id) == c and s.id not in used]
            est = sorted([s for s in cs if s.face_ratio < 0.2], key=lambda s: -(s.quality + 0.2 * s.camera_move.startswith("pan")))
            if est:
                e = est[0]
                t0, t1 = self._window(e, (d.knobs.shot_len or float(np.mean(pb.pacing.broll_shot))) + 0.8)
                items.append(StoryItem(ref=e.id, role="establishing", t0=t0, t1=t1, section=name, note="establishing shot of a new place"))
                used.add(e.id)
            for s in [s for s in segs if self.cluster_of(s.asset_id) == c and s.id not in used and s not in cta]:
                items.append(StoryItem(ref=s.id, role="body", section=name))
                used.add(s.id)
            mont = [s for s in cs if s.id not in used][:3]
            if mont:
                mname = f"{name}_montage"
                sections.append(StorySection(name=mname, music_mode="front"))
                for s in mont:
                    t0, t1 = self._window(s, (d.knobs.shot_len or float(pb.pacing.broll_shot[1]) - 0.6))
                    items.append(StoryItem(ref=s.id, role="montage", t0=t0, t1=t1, section=mname))
                    used.add(s.id)
        # payoff + cta at the end
        if cta:
            sections.append(StorySection(name="outro"))
            for s in cta:
                if s.id not in used:
                    items.append(StoryItem(ref=s.id, role="cta", section="outro"))
                    used.add(s.id)
        # mark the last talking beat before the outro as payoff
        for it in reversed(items):
            if self._seg(it.ref) and it.role == "body":
                it.role = "payoff"
                break
        first_body = next((it for it in items if it.role == "body"), None)
        if first_body:
            first_body.role = "setup"
        return StoryPlan(direction_id=d.id, hook_id=d.hooks[0].id if d.hooks else None, items=self._fit(items, budget, d), sections=sections,
                         why="cold open on the hook, then one part per day/place (establishing → talking → mini-montage), payoff and CTA last")

    def _fit(self, items: list[StoryItem], budget: float, d: Direction) -> list[StoryItem]:
        """Drop the weakest montage/body items until the estimated length fits the target (never pad)."""
        def est(it):
            if it.t0 is not None and it.t1 is not None:
                return it.t1 - it.t0
            s = self._seg(it.ref)
            return (s.t1 - s.t0) * 0.92 if s else 2.0
        total = sum(est(i) for i in items)
        tol = 1.06 if self.brief.prefs.target_length else 1.15
        if total <= budget * tol:
            return items
        protected = {r.target for r in self.rules if r.target} | {r.arg.get("segment") for r in self.rules if r.arg.get("segment")}
        order = [i for i in items if i.role == "montage" and i.ref not in protected] + [i for i in items if i.role == "body" and i.ref not in protected]
        drop = set()
        for it in reversed(order):
            if total <= budget * tol:
                break
            drop.add(id(it))
            total -= est(it)
        return [i for i in items if id(i) not in drop]

    def _music_plan(self, d: Direction, need: float):
        """Pick the soundtrack for music-led directions up front (structure follows the track)."""
        forced = next((r.arg.get("asset") for r in self.rules if r.kind == "use_music" and r.arg.get("asset")), None)
        pb = K.playbook(d.playbook)
        mb = brief_for("front", pb, None, need_secs=need, pace=d.knobs.pace)
        ranked = rank_tracks(self.pa, mb, "front", avoid=pb.music.get("avoid", []))
        tid = forced or d.knobs.music_track or (ranked[0].asset_id if ranked else None)
        return tid, (self.pa.clips[tid].music if tid else None)

    def _montage(self, d: Direction, sections_spec: list[tuple[str, float, float]], pool: list[Shot], *, hook: list[StoryItem]) -> StoryPlan:
        """Fill music sections (name, seconds, shot length) with shots; strongest motion goes to the drop."""
        items = list(hook)
        used = {i.ref for i in items}
        used_w: dict[str, list[tuple[float, float]]] = {}    # moments already taken from each shot
        for i in items:
            if i.t0 is not None and i.t1 is not None:
                used_w.setdefault(i.ref, []).append((i.t0, i.t1))
        calm = sorted(pool, key=lambda s: (s.motion, -s.quality))
        kinetic = sorted(pool, key=lambda s: -(s.motion + 0.5 * bool(s.action_peaks) + 0.3 * (s.whip_in or s.whip_out)))
        sections = [StorySection(name="cold_open", music_mode="front")] if items else []
        for name, secs, shot_len in sections_spec:
            sections.append(StorySection(name=name, music_mode="front"))
            src = kinetic if name in ("drop", "climax", "escalation", "build") else calm
            t = 0.0
            rounds = 0
            while t < secs - 0.3 and rounds < 6:
                progressed = False
                for s in src:
                    if t >= secs - 0.3:
                        break
                    if s.id in used and rounds == 0:
                        continue
                    dur = min(shot_len, secs - t)
                    if dur < 0.4:
                        break
                    around = s.action_peaks[0] if (s.action_peaks and name in ("drop", "climax")) else None
                    t0, t1 = self._window(s, dur, around=around)
                    taken = used_w.get(s.id, [])
                    if any(min(t1, b) - max(t0, a) > 0.1 for a, b in taken):
                        # long shots hold several moments: take a fresh one (best windows first, then any free stretch)
                        fresh = self._fresh_window(s, dur, taken)
                        if fresh is None:
                            continue
                        t0, t1 = fresh
                    items.append(StoryItem(ref=s.id, role="montage" if name != "outro" else "outro", t0=t0, t1=t1, section=name))
                    used.add(s.id)
                    used_w.setdefault(s.id, []).append((t0, t1))
                    t += t1 - t0
                    progressed = True
                rounds += 1
                if not progressed and rounds > 1:    # round 0 skips used shots; only give up once reuse found nothing
                    break
        # motion continuity: within each section, order moments so movement keeps its direction and colours flow
        if d.playbook in ("travel_film", "hype_reel", "teaser"):
            items = self._flow_order(items)
        # loop ending (vertical Shorts/Reels): finish on a fresh moment of the opening image so the replay is seamless
        if d.aspect == "9:16" and len(items) >= 4 and "loop" not in self.no:
            first = items[0]
            sh = self._shot(first.ref)
            if sh is not None and items[-1].ref != first.ref:
                fresh = self._fresh_window(sh, min(1.2, sh.dur), used_w.get(first.ref, []) + [(first.t0 or sh.t0, first.t1 or sh.t1)])
                if fresh:
                    items.append(StoryItem(ref=sh.id, role="loop", t0=fresh[0], t1=fresh[1], section=items[-1].section,
                                           note="loop ending: back to the opening image so the Short replays seamlessly"))
        return StoryPlan(direction_id=d.id, hook_id=d.hooks[0].id if d.hooks else None, items=items, sections=sections)

    def _direction_of(self, it: StoryItem) -> int:
        """+1 / -1 for the way movement goes in this moment (camera pan or the tracked subject), 0 if none."""
        sh = self._shot(it.ref)
        if sh is None:
            return 0
        if sh.camera_move in ("pan_right", "pan_left"):
            return 1 if sh.camera_move == "pan_right" else -1
        a = it.t0 if it.t0 is not None else sh.t0
        b = it.t1 if it.t1 is not None else sh.t1
        pts = [(t, x) for t, x, _y in sh.track if a <= t <= b]
        if len(pts) >= 2 and pts[-1][0] > pts[0][0]:
            v = (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])
            if abs(v) > 0.05:
                return 1 if v > 0 else -1
        return 0

    def _flow_cost(self, a: StoryItem, b: StoryItem) -> float:
        da, db = self._direction_of(a), self._direction_of(b)
        cost = 1.0 if da * db < 0 else (-0.2 if da * db > 0 else 0.0)        # reversal hurts, a match cut helps
        sa, sb = self._shot(a.ref), self._shot(b.ref)
        if sa is not None and sb is not None and sa.color and sb.color:
            cost += 0.6 * float(np.linalg.norm(np.array(sa.color) - np.array(sb.color)))
        if a.ref == b.ref:
            cost += 1.5            # two moments of the same angle back to back read as a jump cut
        return cost

    def flow_score(self, items: list[StoryItem]) -> float:
        """Total flow cost of consecutive montage moments (lower = smoother); used by tests and the critic."""
        return round(sum(self._flow_cost(a, b) for a, b in zip(items, items[1:], strict=False)), 3)

    def _flow_order(self, items: list[StoryItem]) -> list[StoryItem]:
        out: list[StoryItem] = []
        k = 0
        while k < len(items):
            j = k
            while j < len(items) and items[j].section == items[k].section:
                j += 1
            block = items[k:j]
            if len(block) > 2 and all(it.role == "montage" for it in block):
                ordered = [block[0]]
                rest = block[1:]
                while rest:
                    nxt = min(rest, key=lambda r: self._flow_cost(ordered[-1], r))
                    ordered.append(nxt)
                    rest.remove(nxt)
                block = ordered
            out += block
            k = j
        return out

    def _story_travel_film(self, d: Direction) -> StoryPlan:
        target = d.knobs.target_length or 40
        tid, m = self._music_plan(d, target)
        beat = 60.0 / (m.bpm if m and m.bpm else 110)
        spec = [("intro", target * 0.2, beat * 4), ("build", target * 0.2, beat * 2), ("drop", target * 0.4, beat * 2), ("outro", target * 0.2, beat * 4)]
        sp = self._montage(d, spec, self.good_shots(), hook=[])
        sp.why = "music-led film: calm establishing shots on the intro, faster cuts in the build, the most kinetic shots on the drop, a wide to close"
        return sp

    def _story_hype_reel(self, d: Direction) -> StoryPlan:
        target = d.knobs.target_length or 15
        tid, m = self._music_plan(d, target)
        beat = 60.0 / (m.bpm if m and m.bpm else 128)
        used: set = set()
        hook = self._hook_item(d, used)
        spec = [("build", target * 0.3, beat * 2), ("drop", target * 0.6, beat), ("outro", target * 0.1, beat * 2)]
        sp = self._montage(d, spec, [s for s in self.good_shots() if s.id not in used], hook=hook)
        sp.why = "frame-1 spectacle, beat-synced escalation (2 beats → 1 beat per shot), loop back to the opening image"
        return sp

    def _story_teaser(self, d: Direction) -> StoryPlan:
        target = d.knobs.target_length or 20
        tid, m = self._music_plan(d, target)
        beat = 60.0 / (m.bpm if m and m.bpm else 120)
        spec = [("setup", target * 0.3, beat * 4), ("escalation", target * 0.35, beat * 2), ("climax", target * 0.2, beat)]
        sp = self._montage(d, spec, self.good_shots(), hook=[])
        # the button: a line after a beat of silence
        funny = [s for s in self.usable_segments() if s.text.strip().endswith("!") or "numbers" in s.tags]
        if funny:
            sp.sections.append(StorySection(name="button", music_mode="none"))
            sp.items.append(StoryItem(ref=funny[0].id, role="button", section="button", note="the button after a silence"))
        sp.why = "setup → escalation → climax on the beat, then silence and a button line; title card at the end"
        return sp

    def _story_aesthetic(self, d: Direction) -> StoryPlan:
        target = d.knobs.target_length or 30
        pool = self.good_shots()
        pb = K.playbook("aesthetic")
        hold = d.knobs.shot_len or float(np.mean(pb.pacing.broll_shot))
        if not pool:
            return self._story_story_vlog(d)
        opener = max(pool, key=lambda s: s.quality + 0.3 * bool(s.action_peaks) + 0.2 * (s.camera_move == "push_in"))
        items = [StoryItem(ref=opener.id, role="hook", t0=self._window(opener, hold)[0], t1=self._window(opener, hold)[1], section="open",
                           note="most satisfying shot first")]
        rest = [s for s in pool if s.id != opener.id]
        t = hold
        for s in rest:
            if t >= target - 0.5:
                break
            dur = min(hold + (1.0 if s.action_peaks else 0.0), target - t)
            a, b = self._window(s, dur, around=s.action_peaks[0] if s.action_peaks else None)
            items.append(StoryItem(ref=s.id, role="body", t0=a, t1=b, section="progression"))
            t += b - a
        if len(items) > 2:
            items[-1].role = "reveal"
        segs = self.usable_segments()
        if segs and d.knobs.target_length and d.knobs.target_length > 25:
            items.insert(1, StoryItem(ref=segs[0].id, role="setup", section="progression", note="one line of context"))
        return StoryPlan(direction_id=d.id, items=items, sections=[StorySection(name="open", music_mode="light"),
                                                                  StorySection(name="progression", music_mode="light")],
                         why="satisfying shot first, unhurried holds, natural sound up, final reveal last")

    def _story_talking_head(self, d: Direction) -> StoryPlan:
        used: set = set()
        items = self._hook_item(d, used)
        segs = [s for s in self.usable_segments() if s.id not in used]
        cta = [s for s in segs if "cta" in s.tags]
        for s in segs:
            if s in cta:
                continue
            items.append(StoryItem(ref=s.id, role="body", section="points"))
        for s in cta:
            items.append(StoryItem(ref=s.id, role="cta", section="outro"))
        if len(items) > 2:
            for it in reversed(items):
                if it.role == "body":
                    it.role = "payoff"
                    break
        return StoryPlan(direction_id=d.id, hook_id=d.hooks[0].id if d.hooks else None,
                         items=self._fit(items, d.knobs.target_length or 60, d),
                         sections=[StorySection(name="cold_open"), StorySection(name="points"), StorySection(name="outro")],
                         why="hook first, every point tight (fillers, retakes and pauses out), CTA last")

    _story_podcast_clip = _story_talking_head

    def _story_comedy(self, d: Direction) -> StoryPlan:
        items = [StoryItem(ref=s.id, role="beat", section="skit") for s in self.usable_segments()]
        for i, it in enumerate(items):
            s = self._seg(it.ref)
            if s is None or i == 0:
                continue
            prev = self._seg(items[i - 1].ref)
            exclaim = s.text.strip().endswith("!")
            comeback = prev is not None and prev.text.strip().endswith(("!", "?"))          # the retort to a claim/question
            button = prev is not None and len(s.text.split()) <= 4 < len(prev.text.split())  # a short tag line after a setup
            if exclaim or comeback or button:
                it.role = "punchline"
        shots = self.good_shots()
        if shots and items:
            pl = next((k for k, it in enumerate(items) if it.role == "punchline"), None)
            if pl is not None:
                a, b = self._window(shots[0], 1.6)
                items.insert(pl + 1, StoryItem(ref=shots[0].id, role="reaction", t0=a, t1=b, section="skit", note="reaction after the punchline"))
        return StoryPlan(direction_id=d.id, items=items, sections=[StorySection(name="skit", music_mode="light")],
                         why="dialogue in order, pauses tightened except the beat before each punchline, reaction cutaway after it")

    def _story_gaming(self, d: Direction) -> StoryPlan:
        segs = self.usable_segments()
        hype = [s for s in segs if s.text.strip().endswith("!") or s.energy > 1.5]
        items = []
        if hype:
            best = max(hype, key=lambda s: s.energy + 2 * ("numbers" in s.tags))
            items.append(StoryItem(ref=best.id, role="hook", section="cold_open", note="best reaction as the cold open"))
        for s in segs:
            if items and s.id == items[0].ref:
                continue
            items.append(StoryItem(ref=s.id, role="highlight" if s in hype else "body", section="match"))
        return StoryPlan(direction_id=d.id, items=items, sections=[StorySection(name="cold_open"), StorySection(name="match")],
                         why="best reaction first, dead gameplay cut, highlights in order")

    # ------------------------------------------------------------ polish
    def polish(self, d: Direction, story: StoryPlan) -> PolishPlan:
        pb = K.playbook(d.playbook)
        k = d.knobs
        pp = PolishPlan(direction_id=d.id, look=None if "look" in self.no else k.look)
        target = k.target_length or 60
        # ---- music per section
        sec_speech: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for it in story.items:
            seg = self._seg(it.ref)
            dur = (it.t1 - it.t0) if it.t0 is not None and it.t1 is not None else ((seg.t1 - seg.t0) if seg else 2.0)
            sec_speech[it.section][1] += dur
            if seg:
                sec_speech[it.section][0] += dur
        asmr = d.playbook == "aesthetic" and any(self.pa.clips[a.id].audio.speech_ratio < 0.2 and a.info.has_audio and a.kind == AssetKind.BROLL
                                                  for a in self.pa.assets)
        no_music = "music" in self.no
        forced = next((r.arg.get("asset") for r in self.rules if r.kind == "use_music" and r.arg.get("asset")), None)
        forced_scope = next((r.anchor for r in self.rules if r.kind == "use_music" and r.arg.get("asset")), "all")
        no_under_speech = any(r.kind == "no_music_under_speech" for r in self.rules)
        chosen: dict[str, str] = {}
        for sec in story.sections:
            spoken, total = sec_speech.get(sec.name, [0.0, 0.0])
            cov = spoken / total if total else 0.0
            mode = sec.music_mode if sec.music_mode in ("front", "none") and cov < 0.3 else soundtrack_mode(cov, pb, asmr=asmr)
            if no_music or (no_under_speech and cov >= 0.5):
                mode = "none"
            mb = brief_for(mode, pb, self.brief.prefs.music_mood, need_secs=max(total, 8), pace=k.pace)
            track = None
            alts: list[str] = []
            if mode != "none":
                if forced and (forced_scope in ("all", "") or forced_scope in sec.name or (forced_scope == "montage" and mode == "front")):
                    track = forced
                else:
                    ranked = rank_tracks(self.pa, mb, mode, avoid=pb.music.get("avoid", []))
                    key = "front" if mode == "front" else "bed"
                    if key in chosen:
                        track = chosen[key]
                    elif ranked:
                        track = ranked[0].asset_id
                        alts = [r.asset_id for r in ranked[1:3]]
                    if track:
                        chosen[key] = track
            pp.music.append(MusicCue(section=sec.name, mode=mode, track_id=track, alternatives=alts, brief=mb,
                                     why=f"{cov:.0%} speech → {mode}" + (" (your brief)" if track == forced and forced else "")))
        # ---- effects: emphasis, zooms, broll, memes, sfx, speed, transitions, text
        segs_in_story = [self._seg(it.ref) for it in story.items if self._seg(it.ref)]
        minutes = max(0.5, target / 60)
        zoom_budget = 0 if ("zoom" in self.no or k.effects == "clean" and d.playbook not in ("talking_head",)) else int(round(pb.budget("zoom") * minutes * (1.4 if k.effects == "bold" else 1.0)))
        emph_words = []
        for s in segs_in_story:
            for wid in s.word_ids:
                w = next((x for x in self.pa.words(s.asset_id) if x.id == wid), None)
                if not w or w.filler or w.text.startswith("["):
                    continue
                num = bool(re.search(r"\d|₹|\$", words_to_digits(w.text))) or re.sub(r"[^\w]", "", w.text.lower()) in NUMS
                score = w.emphasis + (1.5 if num else 0)
                if score > 1.0:
                    emph_words.append((score, w, s))
        emph_words.sort(key=lambda x: -x[0])
        used_seg_emph = set()
        for score, w, s in emph_words:
            if s.id in used_seg_emph:
                continue
            used_seg_emph.add(s.id)
            pp.effects.append(EffectCue(type="emphasis", at=w.id, style="big", why=f"emphasised word “{w.text}”", confidence=min(0.95, 0.5 + score / 6)))
        for score, w, s in emph_words[: max(0, zoom_budget // 2)]:
            pp.effects.append(EffectCue(type="zoom", at=w.id, value=1.16, why=f"punch-in on “{w.text}”", confidence=min(0.9, 0.45 + score / 6)))
        if zoom_budget and d.playbook in ("story_vlog", "talking_head", "podcast_clip", "comedy", "gaming"):
            for s in segs_in_story:
                pp.effects.append(EffectCue(type="zoom", at=s.id, value=1.12, why="alternate framing to hide jump cuts", confidence=0.8, intent="jumpcut"))
        # B-roll overlays on talking beats (story vlog / talking head)
        if d.playbook in ("story_vlog", "talking_head", "podcast_clip", "gaming"):
            used_shots = {it.ref for it in story.items}
            pool = [s for s in self.good_shots() if s.id not in used_shots]
            for s in segs_in_story:
                if s.t1 - s.t0 < (3.0 if d.playbook in ("talking_head", "podcast_clip") else 4.5):
                    continue
                cand = [p for p in pool if self.cluster_of(p.asset_id) == self.cluster_of(s.asset_id)]   # same place only
                if cand:
                    shot = cand[0]
                    pool.remove(shot)
                    pp.effects.append(EffectCue(type="broll", at=s.id, asset=shot.id, dur=round(min(3.2, (s.t1 - s.t0) * 0.45), 2),
                                                why="cover the talking beat with what is being talked about", confidence=0.7))
                elif d.playbook in ("story_vlog", "talking_head"):
                    want, terms = K.broll_ask(s.text, self.pa.clips[s.asset_id].place)
                    line = s.text.strip()
                    line = line if len(line) <= 48 else line[:46].rsplit(" ", 1)[0] + "…"
                    pp.broll_gaps.append(BrollGap(at=s.id, want=f"{want} (for “{line}”)", search_terms=terms))
        # memes
        meme_ok = pb.memes in ("allowed", "light", "comedic_only") and k.humour != "off" and "meme" not in self.no
        if pb.memes == "comedic_only" and k.humour == "light" and d.playbook == "story_vlog":
            meme_ok = meme_ok and any(s.text.strip().endswith("!") and "micro" in s.tags for s in segs_in_story)
        meme_budget = max(1, int(round(pb.budget("meme") * minutes * (2 if k.humour == "heavy" else 1)))) if meme_ok else 0
        forced_memes = [r for r in self.rules if r.kind == "add_meme"]
        placed = 0
        for r in forced_memes:
            at = r.arg.get("segment")
            if at:
                asset = r.arg.get("asset") or self._pick_meme(["shock", "irony"])
                pp.effects.append(EffectCue(type="meme", at=at, asset=asset, intent="brief", why=f"you asked: {r.source.strip()}", confidence=1.0))
                placed += 1
        if d.playbook == "comedy" and meme_ok:
            # comedy: the meme goes after a real punchline — the one a library meme literally matches first, else the button
            punches = [it for it in story.items if it.role == "punchline" and self._seg(it.ref)]
            ranked = sorted(punches, key=lambda it: (self._meme_by_words(self._seg(it.ref).text) is None, -story.items.index(it)))
            for it in ranked:
                if placed >= meme_budget:
                    break
                s = self._seg(it.ref)
                if any(e.type == "meme" and e.at == s.id for e in pp.effects):
                    continue
                asset = self._meme_by_words(s.text) or self._pick_meme(["shock", "irony", "fail"])
                why = (f"punchline “{s.text.strip()[:40]}” → the matching meme from your folder after it" if self._meme_by_words(s.text)
                       else f"punchline “{s.text.strip()[:40]}” → a reaction meme after it")
                pp.effects.append(EffectCue(type="meme", at=s.id, asset=asset, intent="punchline", why=why,
                                            confidence=0.75 if asset and not asset.startswith("meme:") else 0.45))
                placed += 1
        for s in segs_in_story:
            if placed >= meme_budget or d.playbook == "comedy":
                break
            punch = (s.text.strip().endswith("!") and ("micro" in s.tags or "numbers" in s.tags))
            if punch and not any(e.type == "meme" and e.at == s.id for e in pp.effects):
                intent = "shock" if "numbers" in s.tags else "irony"
                asset = self._pick_meme([intent, "fail"])
                pp.effects.append(EffectCue(type="meme", at=s.id, asset=asset, intent=intent, why=f"punchline “{s.text.strip()[:40]}” → {intent} meme after it",
                                            confidence=0.65 if asset and not asset.startswith("meme:") else 0.45))
                placed += 1
        # SFX (motivated only)
        if "sfx" not in self.no:
            if any(c.mode == "front" for c in pp.music) and d.playbook in ("travel_film", "hype_reel", "teaser"):
                pp.effects.append(EffectCue(type="sfx", at="section:drop" if any(s.name == "drop" for s in story.sections) else "section:climax",
                                            asset=self._pick_sfx("impact"), why="impact on the drop", confidence=0.7))
                pp.effects.append(EffectCue(type="sfx", at="before:section:drop" if any(s.name == "drop" for s in story.sections) else "before:section:climax",
                                            asset=self._pick_sfx("riser"), why="riser into the drop", confidence=0.6))
        # speed: real slow-mo on high-fps action, brief speed rules
        for r in self.rules:
            if r.kind == "speed" and r.target:
                pp.effects.append(EffectCue(type="speed", at=r.target, value=float(r.value or 0.5), why=f"you asked: {r.source.strip()}", confidence=1.0))
        if pb.budget("slowmo") > 0:
            for it in story.items:
                sh = self._shot(it.ref)
                if not sh or not sh.action_peaks or any(e.type == "speed" and e.at == sh.id for e in pp.effects):
                    continue
                fps = self.assets[sh.asset_id].info.fps or 30
                if fps >= 48:
                    pp.effects.append(EffectCue(type="speed", at=sh.id, value=round(30 / fps * (1 if fps < 100 else 2), 3),
                                                why=f"real slow-motion: {fps:.0f} fps source on an action moment", confidence=0.8))
                elif d.playbook in ("hype_reel", "travel_film"):
                    pp.effects.append(EffectCue(type="speed", at=sh.id, value=0.6, why="slow-mo candidate (needs optical flow in your editor)", confidence=0.35))
        # transitions
        if "transition" not in self.no:
            for i, it in enumerate(story.items[1:], start=1):
                prev = self._shot(story.items[i - 1].ref)
                cur = self._shot(it.ref)
                sec_change = it.section != story.items[i - 1].section
                talk = self._seg(it.ref) is not None or self._seg(story.items[i - 1].ref) is not None
                if not talk and ((prev and prev.whip_out) or (cur and cur.whip_in)):
                    pp.effects.append(EffectCue(type="transition", at=f"before:{it.ref}", style="whip", why="whip pan in the footage → seamless transition", confidence=0.75))
                    if "sfx" not in self.no:
                        pp.effects.append(EffectCue(type="sfx", at=f"before:{it.ref}", asset=self._pick_sfx("whoosh"), why="whoosh on the whip", confidence=0.6))
                elif d.playbook == "aesthetic" and prev and cur:
                    pp.effects.append(EffectCue(type="transition", at=f"before:{it.ref}", style="dissolve", why="soft dissolve between calm shots", confidence=0.6))
                elif sec_change and d.playbook == "teaser" and it.section == "button":
                    pp.effects.append(EffectCue(type="transition", at=f"before:{it.ref}", style="fade_black", why="beat of black before the button", confidence=0.7))
        # split edits (J/L cuts): sound leads or trails the picture where the scene or the speaker changes
        self._split_edits(d, story, pp, pb)
        # open loop: "later…" on the flash-forward; re-hooks at later parts
        for it in story.items:
            if it.role == "flashforward" and "text" not in self.no:
                pp.effects.append(EffectCue(type="text", at=it.ref, text="later…", style="small", dur=1.2, confidence=0.75, intent="open_loop",
                                            why="open loop: a glimpse of the payoff that comes later in this video"))
        self._rehooks(d, story, pp)
        # text
        for sec in story.sections:
            if sec.card and d.playbook in ("story_vlog", "travel_film") and len([s for s in story.sections if s.card]) > 1:
                pp.effects.append(EffectCue(type="text", at=f"section:{sec.name}", text=sec.card, style="card", dur=2.4, why="location/day card at a new place", confidence=0.75))
        hook_text = d.hooks[0].text_hook if d.hooks else None
        if d.playbook == "comedy":
            # comedy: tease the premise — putting the punchline on screen first kills the joke
            premise = next((self._seg(it.ref) for it in story.items if self._seg(it.ref)), None)
            punch_words = {w for it in story.items if it.role == "punchline" and self._seg(it.ref)
                           for w in re.findall(r"[a-z]{4,}", self._seg(it.ref).text.lower())}
            hook_text = text_hook(premise.text) if premise else None
            if hook_text and set(re.findall(r"[a-z]{4,}", hook_text.lower())) & punch_words - set(re.findall(r"[a-z]{4,}", premise.text.lower())):
                hook_text = None
        if d.aspect == "9:16" and hook_text:
            pp.effects.append(EffectCue(type="text", at="start", text=hook_text, style="hook", dur=2.6, why="on-screen text hook (works on mute)", confidence=0.7))
        for r in self.rules:
            if r.kind == "add_text" and r.target:
                pp.effects.append(EffectCue(type="text", at=r.anchor or "end", text=r.target, style="cta" if (r.anchor or "end") == "end" else "title",
                                            dur=2.6, why=f"you asked: {r.source.strip()}", confidence=1.0))
        if d.playbook == "teaser":
            pp.effects.append(EffectCue(type="text", at="end", text="FULL VIDEO OUT NOW", style="title", dur=2.0, why="teaser end card", confidence=0.7))
        # profanity
        if any(r.kind == "no_profanity" for r in self.rules):
            bad = re.compile(r"\b(fuck|shit|damn|bitch|bc|mc|chutiya|saala)\w*", re.I)
            for s in segs_in_story:
                for w in self.pa.words(s.asset_id):
                    if w.id in s.word_ids and bad.search(w.text):
                        pp.effects.append(EffectCue(type="bleep", at=w.id, why="no swearing (your brief)", confidence=1.0))
        if not any(self._seg(it.ref) for it in story.items) and d.playbook in ("story_vlog", "travel_film"):
            places = [self.cluster_label(c) for c in self.clusters() if self.cluster_label(c)]
            pp.vo_script = ([f"{places[0]}. I had no plan — just a camera."] if places else []) + ["Here's what happened."]
        return pp

    def _split_edits(self, d: Direction, story: StoryPlan, pp: PolishPlan, pb) -> None:
        """J-cut: the next sound starts under the current picture; L-cut: the current voice runs under the next picture.
        Only at talking ↔ B-roll changes and place changes, never inside music-led montages, never where a
        transition (whip/dissolve) already joins the shots, at most one every ~6 s of story."""
        se = pb.split_edits or {}
        if not se or "split" in self.no:
            return
        joined = {c.at for c in pp.effects if c.type == "transition"}
        front = {c.section for c in pp.music if c.mode == "front"}
        last_t, t = -1e9, 0.0
        for prev, nxt in zip(story.items, story.items[1:], strict=False):
            pseg, nseg = self._seg(prev.ref), self._seg(nxt.ref)
            pshot, nshot = self._shot(prev.ref), self._shot(nxt.ref)
            dur = (prev.t1 - prev.t0) if prev.t0 is not None and prev.t1 is not None else ((pseg.t1 - pseg.t0) if pseg else 2.5)
            t += dur
            at = f"before:{nxt.ref}"
            if at in joined or nxt.section in front or prev.section in front or t < 3.0 or t - last_t < 6.0 or prev.ref == nxt.ref:
                continue
            cue = None
            if pshot and nseg and se.get("j"):
                cue = EffectCue(type="split", at=at, style="J", value=float(se["j"]), confidence=0.75,
                                why="J-cut: your voice starts under the last shot, so the move back to talking feels continuous")
            elif pseg and nshot and se.get("l") and nshot.asset_id != pseg.asset_id:
                cue = EffectCue(type="split", at=at, style="L", value=float(se["l"]), confidence=0.75,
                                why="L-cut: you keep talking as the next shot appears — no hard stop between words and pictures")
            elif pshot and nshot and prev.section != nxt.section and se.get("j") and self.assets[nshot.asset_id].info.has_audio:
                cue = EffectCue(type="split", at=at, style="J", value=float(se["j"]), confidence=0.7,
                                why="J-cut: the next place's sound arrives just before its picture")
            if cue:
                pp.effects.append(cue)
                last_t = t

    def _meme_by_words(self, text: str) -> str | None:
        """A library meme whose file name says what the line says ("Emotional damage." ↔ emotional_damage_fail.mp4)."""
        words = {w for w in re.findall(r"[a-z]{4,}", text.lower())}
        best, score = None, 0
        for a in self.pa.assets:
            if a.kind not in (AssetKind.MEME_IMAGE, AssetKind.MEME_VIDEO):
                continue
            name = set(re.findall(r"[a-z]{4,}", a.name.lower()))
            hit = len(words & name)
            if hit > score:
                best, score = a.id, hit
        return best

    def _pick_meme(self, intents: list[str]) -> str | None:
        memes = [a for a in self.pa.assets if a.kind in (AssetKind.MEME_IMAGE, AssetKind.MEME_VIDEO)]
        for intent in intents:
            for a in memes:
                if any(k in a.name.lower() for k in MEME_KEYWORDS.get(intent, [intent])):
                    return a.id
        if memes:
            return memes[0].id
        flav = self.brief.prefs.meme_flavour or "global"
        for m in K.memes():
            if set(m.intent) & set(intents) and (m.culture == flav or flav == "mix" or (flav == "global" and m.culture == "global")):
                return f"meme:{m.id}"
        return None

    def _pick_sfx(self, kind: str) -> str:
        for a in self.pa.assets:
            if a.kind == AssetKind.SFX and kind in a.name.lower():
                return a.id
        return f"sfx:{kind}"
