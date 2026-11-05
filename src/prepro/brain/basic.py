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


CONTRACT = [(r"\bdid not\b", "didn't"), (r"\bdo not\b", "don't"), (r"\bdoes not\b", "doesn't"), (r"\bis not\b", "isn't"),
            (r"\bwas not\b", "wasn't"), (r"\bcan ?not\b", "can't"), (r"\bwill not\b", "won't"), (r"\bhave not\b", "haven't")]
NEGATION = {"not", "never", "no", "nobody", "nothing", "didn't", "don't", "doesn't", "isn't", "wasn't", "can't", "won't", "haven't"}
BAD_END = {"a", "an", "the", "to", "of", "in", "on", "at", "for", "with", "from", "by", "as", "than", "and", "or", "but", "so",
           "did", "do", "does", "was", "were", "is", "are", "be", "been", "has", "have", "had", "will", "would", "could", "should",
           "can", "my", "your", "our", "their", "his", "her", "its", "that", "which", "who", "i", "you", "we", "they", "he", "she",
           "it", "almost", "just", "only", "really", "very", "not", "never", "no", "every", "each", "some", "any", "all", "this",
           "these", "those", "more", "most", "how", "what", "why", "when", "where"}
BAD_START = {"and", "or", "but", "so", "to", "of", "with", "for", "from", "by", "as", "than", "that", "which", "who", "because",
             "did", "was", "were", "is", "are", "in", "on", "at"}
LEADING_ONLY = {"i", "we", "today", "now", "here", "there"}   # dropped as an opener, kept inside a phrase ("1 video I almost…")


def _phrase(words: list[str], max_words: int) -> list[str]:
    """The best few words of a clause for on-screen text: never cut mid-thought (ending on "did", "with", "almost"),
    never cut just before a "not" (which flips the meaning), keep the number, and prefer reaching the clause's end —
    up to two words over the limit when that is what it takes."""
    n = len(words)
    if n <= max_words:
        return words
    low = [re.sub(r"[^\w']", "", w.lower()) for w in words]
    digit = [bool(re.search(r"\d", w)) for w in words]
    best, best_key = None, None
    for i in range(n):
        if low[i] in BAD_START:
            continue
        for j in range(i + 1, n + 1):
            if j - i > max_words + (2 if j == n else 0):
                break
            if low[j - 1] in BAD_END or (j < n and low[j] in NEGATION):
                continue
            has = any(digit[i:j])
            # with a number: run to the clause's end ("…0 to 1M subscribers in 1 year"); without: keep its start,
            # where the subject is ("Yeh vada pav…", not "Pav sirf…")
            key = (has, (j == n) if has else (i == 0), -abs((j - i) - max_words), -i)
            if best_key is None or key > best_key:
                best, best_key = words[i:j], key
    return best or words[:max_words]


def reaction_text(text: str, max_words: int = 3) -> str:
    """A streamer's reaction as on-screen text: its first exclamation, whole ("DOUBLE KILL!"), never a dangling
    "DOUBLE KILL! LET'S"."""
    first = re.split(r"(?<=[!?.])\s", text.strip())[0]
    words = _phrase(first.split(), max_words) if len(first.split()) > max_words else first.split()
    return " ".join(words).upper().rstrip(",;: ")


def repeats_speech(text: str, spoken: str) -> bool:
    """On-screen text that only repeats words being said (and captioned) at the same time is clutter: "DOUBLE KILL!"
    over a caption "DOUBLE KILL!". A condensed form ("₹5000 for 3 days?!" for "five thousand rupees…") is not."""
    norm = lambda s: {w for w in re.findall(r"[\w₹$']+", s.lower())}          # noqa: E731
    shown = norm(text)
    return bool(shown) and shown <= norm(spoken)


def text_hook(seg_text: str, max_words: int = 6) -> str:
    """'So today we are in Goa and I spent only five thousand rupees for three full days.' → '₹5000 for 3 days?!'
    'Honestly, it started with one video I almost did not upload.' → '1 video I almost didn't upload?!'"""
    t = words_to_digits(seg_text)
    t = re.sub(r"[\"“”]", "", t)
    for pat, rep in CONTRACT:
        t = re.sub(pat, rep, t, flags=re.I)
    clauses = re.split(r"[,.;!?]|\band\b|\bbut\b", t)
    clauses = [c.strip() for c in clauses if c.strip()]
    def content(c: str) -> int:        # "the lesson is" (1) sets up "show the payoff first" (3): the payload wins
        return sum(1 for w in c.split() if re.sub(r"[^\w']", "", w.lower()) not in STOP | BAD_END)

    best = max(clauses, key=lambda c: (bool(re.search(r"\d", c)), len(c.split()) <= 9, min(content(c), 4),
                                       -abs(len(c.split()) - 6))) if clauses else t
    words = []
    toks = best.split()
    for k, w in enumerate(toks):
        lw = re.sub(r"[^\w']", "", w.lower())
        if (lw in STOP and lw not in LEADING_ONLY) or (lw in LEADING_ONLY | {"only", "full", "spent", "me", "my", "for", "it"} and not words):
            continue
        if lw in CURRENCY and words and re.match(r"^\d+$", words[-1]):
            words[-1] = CURRENCY[lw] + words[-1]
            continue
        if lw in ("full", "only") and k + 1 < len(toks):
            continue
        words.append(w.strip(",.;"))
    words = _phrase(words, max_words)
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
        if playbook == "gaming":
            plays = [(e, a) for a in self.pa.assets if a.kind in (AssetKind.SCREEN, AssetKind.AROLL) for e in self._game_events(a.id)]
            if plays:
                e, a = max(plays, key=lambda p: p[0]["score"])
                sh = next((x for x in self.pa.clips[a.id].shots if x.t0 <= e["t"] <= x.t1), None)
                r = self._seg(e["reaction"]) if e["reaction"] else None
                if sh is not None:
                    opts.append(HookOption(id=f"h{len(opts)}", kind="peak_moment", refs=[sh.id],
                                           text_hook=reaction_text(r.text) if r else None,
                                           why=f"open on the best play ({e['kind'].replace('+', ' + ')} at {e['t']:.1f} s)" +
                                               (f" — “{r.text.strip()[:40]}”" if r else ""),
                                           score=round(min(1.0, 0.55 + 0.3 * min(1.0, e["score"] / 1.5)), 3)))
        if playbook == "photo_reel":
            shots = self.photos()
            if shots:
                cover = max(shots, key=self._cover_score)
                opts.append(HookOption(id=f"h{len(opts)}", kind="visual_spectacle", refs=[cover.id], text_hook=self.photo_title(),
                                       why=f"open on your most striking photo ({cover.asset_id}): colour, contrast"
                                           + (" and a face" if cover.faces else "") + " stop the scroll",
                                       score=round(0.6 + 0.4 * (cover.aesthetic or 0), 3)))
        talk_ok = playbook not in ("travel_film", "hype_reel", "aesthetic", "photo_reel")
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
        # a stream makes a YouTube highlight *and* a vertical Short: offer both (the Short stacks the webcam on top)
        g = next((d for d in out if d.playbook == "gaming" and d.aspect == "16:9" and not d.from_brief), None)
        if g is not None and len(out) < max_n and not prefs.aspect:
            s = g.model_copy(deep=True)
            tgt = min(g.knobs.target_length or 30.0, 45.0)
            s.id, s.aspect, s.name = f"d{len(out) + 1}", "9:16", self.direction_name("gaming", "9:16", tgt)
            s.knobs.target_length, s.target_min, s.target_max = tgt, round(max(5.0, tgt * 0.85), 1), round(tgt * 1.15, 1)
            s.knobs.captions = "bold" if s.knobs.captions == "clean" else s.knobs.captions
            cam = any(self.pa.clips[a.id].facecam for a in self.pa.assets if a.id in self.pa.clips)
            s.why = "the same plays as a vertical Short" + (" — your webcam stacked on top, the game below" if cam else "")
            s.fit_score = round(g.fit_score * 0.95, 3)
            s.outline, s.coverage_gaps = self.outline(s), self.coverage_gaps(s)
            out.append(s)
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
            wins = []
            for a in self.pa.assets:
                if a.kind in (AssetKind.SCREEN, AssetKind.AROLL):
                    for e in self._game_events(a.id):
                        r = self._seg(e["reaction"]) if e["reaction"] else None
                        wins.append((max(0.0, e["t"] - 3.0), (r.t1 + 0.5) if r else e["t"] + 1.6))
            wins.sort()
            merged: list[list[float]] = []
            for w0, w1 in wins:
                if merged and w0 <= merged[-1][1] + 0.5:
                    merged[-1][1] = max(merged[-1][1], w1)
                else:
                    merged.append([w0, w1])
            # every play + a cold open + a replay; talk-only footage falls back to the speech estimate
            est = sum(b - a for a, b in merged) + 3.4 if merged else speech_ok * 0.9 + 6
        elif pbk == "travel_film":
            est = broll_ok * 0.55 * (0.5 + 0.5 * getattr(self, "_variety", 1.0))    # few angles → shorter film
        elif pbk == "hype_reel":
            est = 15.0 if broll_ok >= 12 else max(8.0, broll_ok * 0.8)
        elif pbk == "teaser":
            est = 20.0
        elif pbk == "photo_reel":                # ≈ 1.2 s a photo + a held cover; one photo: two to four phrases
            n = len(self.photos())
            est = 10.0 + 3.5 * max(0, len(self.text_lines()) - 2) if n <= 1 else 2.4 + 1.2 * n
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
        conversation = self._story_dialogue(d)            # two people talking: keep the exchange intact
        if conversation is not None:
            return conversation
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

    RESPONSE = re.compile(r"^\s*(wait|really|right|exactly|yeah|yes|yep|no|nope|true|totally|wow|oh|ha+|okay|ok|hmm+|what)\b", re.I)
    ECHO_STOP = frozenset(["a", "an", "the", "and", "or", "but", "so", "to", "of", "in", "on", "at", "for", "with", "is", "it", "this", "that", "i", "you", "we", "they", "he", "she", "me", "my", "your", "our", "was", "were", "be", "been", "am", "are", "do", "did", "not", "no", "yes", "just", "very", "really", "what", "wait"])

    def _opening_speech(self, it: StoryItem) -> str:
        """What is said during the first item of the cut: its line, or the lines inside a shot window (a gameplay
        cold open plays the streamer's reaction)."""
        seg = self._seg(it.ref)
        if seg is not None:
            return seg.text
        shot = self._shot(it.ref)
        if shot is None or not self.pa.clips[shot.asset_id].transcript:
            return ""
        a, b = (it.t0 if it.t0 is not None else shot.t0), (it.t1 if it.t1 is not None else shot.t1)
        return " ".join(s.text for s in self.pa.clips[shot.asset_id].transcript.segments if s.t1 > a and s.t0 < b)

    def responds(self, s: Segment, prev: Segment | None) -> bool:
        """`s` answers or echoes the line before it, said by someone else ("Wait, you almost did not upload it?",
        "Eleven times!", "Right."): without that line it makes no sense, so it can't open a clip or survive alone."""
        if prev is None or s.speaker is None or prev.speaker is None or s.speaker == prev.speaker:
            return False
        content = {w for w in re.findall(r"[a-z0-9']+", s.text.lower()) if w not in self.ECHO_STOP}
        before = {w for w in re.findall(r"[a-z0-9']+", prev.text.lower()) if w not in self.ECHO_STOP}
        echo = len(content & before)
        short = len(s.text.split()) <= 6
        return (short and (echo >= 1 or bool(self.RESPONSE.match(s.text)))) or (s.text.strip().endswith("?") and echo >= 1)

    def dialogue_lines(self) -> list[Segment] | None:
        """The usable lines of a conversation (a two-shot whose lines have speakers), in order; None for monologues."""
        for a in self.talk_assets():
            segs = sorted(self.pa.clips[a.id].transcript.segments, key=lambda s: s.t0)
            if len({s.speaker for s in segs if s.speaker is not None}) >= 2:
                return [s for s in segs if not self.is_cut_candidate(s) or ("micro" in s.tags and s.speaker is not None)]
        return None

    def _story_dialogue(self, d: Direction) -> StoryPlan | None:
        """A conversation is cut like a podcast clipper cuts it: one stretch of the exchange, in the order it was said,
        opening on a line that stands on its own (a number, a claim, a question — never an answer or an echo) and
        ending on a landing, not on a question left hanging. Moving lines around would break the back-and-forth."""
        lines = self.dialogue_lines()
        if not lines or len(lines) < 3:
            return None
        from ..repurpose import _closer, _opener  # the Shorts finder's opener/closer judgement

        lo = d.target_min or (d.knobs.target_length or 30) * 0.8
        hi = d.target_max or (d.knobs.target_length or 30) * 1.2
        best, best_sc = None, -9.0
        for i, first in enumerate(lines):
            prev = lines[i - 1] if i else None
            if self.responds(first, prev) or "greeting" in first.tags:
                continue
            op, _ = _opener(self, first, i)
            for j in range(i + 1, len(lines)):
                dur = lines[j].t1 - first.t0
                if dur > hi * 1.1:
                    break
                if dur < lo * 0.85:
                    continue
                last = lines[j]
                cl, _ = _closer(self, last)
                if last.text.strip().endswith("?"):
                    cl -= 0.6                                 # a question left hanging
                if j + 1 < len(lines) and self.responds(lines[j + 1], last) and lines[j + 1].text.strip().endswith("!"):
                    cl -= 0.2                                 # the reaction that lands it is just outside
                fit = 1.0 - min(1.0, abs(dur - (lo + hi) / 2) / max(1.0, hi - lo))
                sc = 0.45 * op + 0.35 * cl + 0.2 * fit
                if sc > best_sc:
                    best, best_sc = (i, j), sc
        if best is None:
            return None
        i, j = best
        window = lines[i: j + 1]
        items = [StoryItem(ref=s.id, role="hook" if k == 0 else "body", section="cold_open" if k == 0 else "conversation",
                           whole=s.speaker is not None and len(s.text.split()) <= 3)
                 for k, s in enumerate(window)]
        if len(items) > 2:
            items[-1].role = "payoff"
        return StoryPlan(direction_id=d.id, hook_id=d.hooks[0].id if d.hooks else None, items=items,
                         sections=[StorySection(name="cold_open"), StorySection(name="conversation")],
                         why="one stretch of the conversation in the order it was said: opens on a line that stands on its "
                             "own, every answer stays with its question, ends on a landing")

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

    REACTION = re.compile(r"\b(let'?s go|no way|oh my god|omg|what|victory|won|win|kill|clutch|headshot|insane|yes|noo+|bro)\b", re.I)
    FAIL = re.compile(r"\b(noo+|i died|i'?m dead|dead|how did|lag+|bruh|ugh|why|nahh*)\b", re.I)
    WIN = re.compile(r"\b(kill|kills|won|win|victory|let'?s go|clutch|headshot|yes+)\b", re.I)

    def _game_events(self, asset_id: str) -> list[dict]:
        """Highlights in gameplay: an impact (explosion/shot) followed by the streamer's reaction is the classic
        moment; a big reaction alone or an impact alone count less. Returns dicts sorted by time."""
        cache = getattr(self, "_events_cache", None)
        if cache is None:
            cache = self._events_cache = {}
        if asset_id in cache:
            return cache[asset_id]
        from ..analyze.sound import impacts
        from ..project import Project

        ca = self.pa.clips[asset_id]
        segs = sorted(ca.transcript.segments, key=lambda s: s.t0) if ca.transcript else []
        hits: list[tuple[float, float]] = []
        try:
            import soundfile as sf

            wav = Project(self.pa.root).cache / "audio" / f"{asset_id}.wav"
            if wav.exists():
                y, sr = sf.read(str(wav), dtype="float32")
                hits = impacts(y, sr, word_starts=[w.t0 for w in self.pa.words(asset_id)])
        except Exception:
            hits = []

        def reaction(s) -> float:
            return 0.5 * s.text.strip().endswith("!") + 0.4 * bool(self.REACTION.search(s.text)) + 0.2 * min(1.0, max(0.0, s.energy) / 1.5)

        def fail(s) -> bool:              # a death / a miss: "Noooo! How did he even hit that?" (not "No way, double kill!")
            return bool(s is not None and self.FAIL.search(s.text) and not self.WIN.search(s.text))

        events, used = [], set()
        for t, strength in hits:
            r = next((s for s in segs if t - 0.3 <= s.t0 <= t + 2.5 and reaction(s) >= 0.4), None)
            score = 0.5 + min(0.3, strength / 150) + (reaction(r) if r else 0.0)
            events.append({"t": t, "score": round(score, 3), "reaction": r.id if r else None, "kind": "impact+reaction" if r else "impact",
                           "fail": fail(r)})
            if r:
                used.add(r.id)
        for s in segs:
            if s.id not in used and reaction(s) >= 0.8:
                events.append({"t": max(0.0, s.t0 - 0.3), "score": round(0.3 + reaction(s) * 0.5, 3), "reaction": s.id, "kind": "reaction",
                               "fail": fail(s)})
        cache[asset_id] = sorted(events, key=lambda e: e["t"])
        return cache[asset_id]

    def _story_gaming(self, d: Direction) -> StoryPlan:
        """Gaming highlight cut: cold open on the best moment → highlights in order, each with a 3 s build-up and
        the reaction → a slow-mo replay of the best play → the payoff. Dead gameplay in between is cut."""
        clips = [a for a in self.pa.assets if a.kind in (AssetKind.SCREEN, AssetKind.AROLL) and self.pa.clips[a.id].shots]
        moments = []
        for a in clips:
            ca = self.pa.clips[a.id]
            for e in self._game_events(a.id):
                sh = next((x for x in ca.shots if x.t0 <= e["t"] <= x.t1), None)
                if sh is None:
                    continue
                r = self._seg(e["reaction"]) if e["reaction"] else None
                t0 = max(sh.t0, e["t"] - 3.0)
                t1 = min(sh.t1, (r.t1 + 0.5) if r else e["t"] + 1.6)
                if t1 - t0 >= 1.5:
                    moments.append({**e, "shot": sh, "t0": t0, "t1": t1, "asset": a.id})
        if not moments:
            # no detectable plays: fall back to the talking-led cut (best reaction first, lines in order)
            segs = self.usable_segments()
            hype = [s for s in segs if s.text.strip().endswith("!") or s.energy > 1.5]
            items = []
            if hype:
                best = max(hype, key=lambda s: s.energy)
                items.append(StoryItem(ref=best.id, role="hook", section="cold_open", note="best reaction as the cold open"))
            items += [StoryItem(ref=s.id, role="highlight" if s in hype else "body", section="match") for s in segs if not items or s.id != items[0].ref]
            return StoryPlan(direction_id=d.id, items=items, sections=[StorySection(name="cold_open"), StorySection(name="match")],
                             why="best reaction first, dead gameplay cut, highlights in order")
        # merge overlapping windows on the same clip
        moments.sort(key=lambda m: (m["asset"], m["t0"]))
        merged: list[dict] = []
        for m in moments:
            if merged and merged[-1]["asset"] == m["asset"] and m["t0"] <= merged[-1]["t1"] + 0.5:
                last = merged[-1]
                if bool(last.get("fail")) != bool(m.get("fail")):
                    # a death and a win are separate beats (the fail meme goes between them): split where the first
                    # one ends, so no frame plays twice
                    m = {**m, "t0": max(m["t0"], last["t1"])}
                    if m["t1"] - m["t0"] >= 1.0:
                        merged.append(m)
                    continue
                last["t1"] = max(last["t1"], m["t1"])
                if m["score"] > last["score"]:
                    last.update({k: m[k] for k in ("t", "score", "reaction", "kind", "fail")})
                continue
            merged.append(dict(m))
        target = d.knobs.target_length or 45
        best = max(merged, key=lambda m: (not m.get("fail"), m["score"]))     # a death is no cold open — the best win is
        final = max(merged, key=lambda m: m["t"])          # the last play is the payoff — never cut it
        chosen, total = [final], 2.4 + (final["t1"] - final["t0"])
        for m in sorted(merged, key=lambda m: -m["score"]):
            if m is final:
                continue
            if total + (m["t1"] - m["t0"]) > target * 1.2 and chosen:
                continue
            chosen.append(m)
            total += m["t1"] - m["t0"]
        chosen.sort(key=lambda m: (m["asset"], m["t0"]))
        items: list[StoryItem] = []
        sh = best["shot"]
        h0 = max(sh.t0, best["t"] - 0.4)
        items.append(StoryItem(ref=sh.id, role="hook", t0=round(h0, 3), t1=round(min(best["t1"], h0 + 2.4), 3), section="cold_open",
                               note="cold open on the best play"))
        for k, m in enumerate(chosen):
            role = "payoff" if k == len(chosen) - 1 and len(chosen) > 1 else "highlight"
            items.append(StoryItem(ref=m["shot"].id, role=role, t0=round(m["t0"], 3), t1=round(m["t1"], 3), section="match",
                                   note=f"{m['kind'].replace('+', ' + ')} at {m['t']:.1f}s" + (" · fail" if m.get("fail") else "")))
            if m is best and "speed" not in self.no:
                r0 = max(m["shot"].t0, best["t"] - 0.3)
                items.append(StoryItem(ref=m["shot"].id, role="replay", t0=round(r0, 3), t1=round(min(m["shot"].t1, r0 + 1.0), 3), section="replay",
                                       note="slow-mo replay of the best play"))
        return StoryPlan(direction_id=d.id, items=items,
                         sections=[StorySection(name="cold_open"), StorySection(name="match"), StorySection(name="replay", music_mode="none")],
                         why="cold open on the best play, highlights in order with a 3 s build-up into each, a slow-mo replay of the best, "
                             "dead gameplay cut")

    # ------------------------------------------------------------ photo reels
    def photos(self) -> list[Shot]:
        """Usable photos in the order they were taken: one per burst (the sharpest, most striking), dark or blurry ones
        out unless the brief asks for them."""
        imgs = [a for a in self.pa.assets if a.kind == AssetKind.IMAGE and self.pa.clips.get(a.id) and self.pa.clips[a.id].shots]
        imgs.sort(key=lambda a: (a.info.creation_time.timestamp() if a.info.creation_time else float("inf"), a.path))
        out = []
        for a in imgs:
            sh = self.pa.clips[a.id].shots[0]
            if a.id in self.excluded or sh.id in self.excluded:
                continue
            forced = a.id in self.included or sh.id in self.included
            if not forced and ((sh.dup_group and sh.dup_rank > 0) or set(sh.flags) & {"dark", "blurry"}):
                continue
            out.append(sh)
        return out

    def text_lines(self) -> list[str]:
        """The creator's own on-screen lines, in order (a "Text:" block, POV lines, quoted lines)."""
        return [r.target for r in sorted((r for r in self.rules if r.kind == "text_line"), key=lambda r: float(r.value or 0))]

    def photo_title(self) -> str | None:
        """Words for the cover: the creator's first line, else where and when from the photos' GPS/EXIF ("Goa · Oct 2026",
        "Goa → Jaipur"), else nothing (a generic "photo dump" adds nothing)."""
        lines = self.text_lines()
        if lines:
            return lines[0]
        start = next((r.target for r in self.rules if r.kind == "add_text" and r.anchor == "start"), None)
        if start:
            return start
        shots = self.photos()
        places = list(dict.fromkeys(p for p in (self.pa.clips[s.asset_id].place for s in shots)
                                    if p and not re.match(r"^Place \d+$", p)))
        when = next((self.pa.asset(s.asset_id).info.creation_time for s in shots if self.pa.asset(s.asset_id).info.creation_time), None)
        where = " → ".join(places[:3]) if len(places) > 1 else (places[0] if places else "")
        if where and when:
            return f"{where} · {when.strftime('%b %Y')}"
        return where or None

    def _reel_grid(self, need: float) -> dict:
        """The song and the beat grid a photo reel is cut on: a downbeat at the start of the song's strongest part (its
        drop/chorus) that leaves enough music after it."""
        tid, m = self._music_plan(Direction(id="x", playbook="photo_reel", name="x", aspect="9:16"), need)
        if m is None or len(m.beats) < 8:
            return {"track": tid, "offset": 0.0, "beat": 0.5, "beats": [k * 0.5 for k in range(400)], "label": None, "bpm": 120.0}
        dur = self.pa.asset(tid).info.duration
        downs = m.downbeats or m.beats[::4]
        best = None
        for sec in sorted(m.sections, key=lambda s: -s.energy):
            cand = next((b for b in downs if b >= sec.t0 - 0.05), None)
            if cand is not None and cand + min(need, 8.0) <= dur:
                best = (cand, sec.label)
                break
        start, label = best if best else (downs[0], None)
        beats = [round(b - start, 3) for b in m.beats if b >= start - 1e-3]
        period = float(np.median(np.diff(beats[:64]))) if len(beats) > 4 else 60.0 / max(60.0, m.bpm)
        return {"track": tid, "offset": round(start, 3), "beat": period, "beats": beats, "label": label, "bpm": m.bpm}

    def _cover_score(self, s: Shot) -> tuple[float, float]:
        """What makes the first frame of a Reel: a striking photo with a person in it that fills the 9:16 frame edge
        to edge (a portrait-orientation photo does), never one that has to be shown framed on a blurred fill."""
        from ..analyze.visual import photo_fills

        ds = self.pa.asset(s.asset_id).info.display_size
        fills = photo_fills(ds, s.faces, 9 / 16)
        tall = bool(ds and ds[1] > ds[0])
        return ((s.aesthetic or 0) + 0.15 * bool(s.faces) + 0.08 * tall - (0.6 if not fills else 0.0), s.sharpness)

    @staticmethod
    def _beat_at(grid: dict, j: int) -> float:
        """Time of beat j of the reel's grid (beats counted from the start of the cut); past the analysed beats the
        grid carries on at the song's tempo."""
        beats = grid["beats"]
        if j < len(beats):
            return beats[j]
        return (beats[-1] if beats else 0.0) + (j - len(beats) + 1) * grid["beat"]

    def _story_photo_reel(self, d: Direction) -> StoryPlan:
        shots = self.photos()
        if not shots:
            return self._story_story_vlog(d)
        lines = self.text_lines()
        grid = self._reel_grid(need=float(d.knobs.target_length or 15.0))
        p = grid["beat"]
        k = min((1, 2, 4), key=lambda n: abs(n * p - 1.2))   # ≈ 1.2 s a photo, in whole beats (100 BPM → 2 beats)
        j = 0                                                 # beats used so far: every cut lands on a detected beat

        def take(n: int) -> float:
            nonlocal j
            a, b = self._beat_at(grid, j), self._beat_at(grid, j + n)
            j += n
            return round(b - a, 3)

        def beats_for(text: str | None, base: int, unit: int) -> int:
            n = base
            if text:                                     # long enough to read: ≈ 3 words a second + time to find it
                while n * p < 0.75 + len(text.split()) / 3.0:
                    n += unit
            return n

        items: list[StoryItem] = []
        if len(shots) == 1:
            # one photo, your words, the song: your first line is on the first frame (it is the hook), every next line
            # arrives on the beat, half a bar at a time, and stays up long enough to read; the last one holds to the end
            unit = 2 if p >= 0.45 else 4
            slots = []
            for t in lines:
                n = beats_for(t, unit, unit)
                slots.append((j, j + n))
                j += n
            tail = 2 * unit if lines else 16                 # no words: four bars of the photo and the song
            j += tail
            total = round(self._beat_at(grid, j) - self._beat_at(grid, 0), 3)
            items.append(StoryItem(ref=shots[0].id, role="hook", t0=0.0, t1=total, section="reel",
                                   note="one photo held while your lines land on the music's beat"))
            self._reel = {**grid, "lines": lines, "slots": slots, "end": j}
            return StoryPlan(direction_id=d.id, items=items, sections=[StorySection(name="reel", music_mode="front")],
                             why="one photo, your words and the song: your first line from the first frame, each next line on the beat")
        cover = max(shots, key=self._cover_score)
        rest = [s for s in shots if s.id != cover.id]
        target = float(d.target_max or (d.knobs.target_length or 30) * 1.15)
        # too many photos for the length: the least striking middle ones go (the order stays the order they were taken)
        while rest and (2 * k + len(rest) * k + (k if len(shots) >= 4 else 0)) * p > target and len(rest) > 2:
            rest.remove(min(rest[1:-1] or rest, key=lambda s: s.aesthetic or 0))
        texts = [lines[i] if i < len(lines) else None for i in range(1 + len(rest))]
        items.append(StoryItem(ref=cover.id, role="hook", t0=0.0, t1=take(beats_for(texts[0], 2 * k, k)), section="reel",
                               note="cover: your most striking photo first"))
        for i, s in enumerate(rest, start=1):
            n = beats_for(texts[i], 2 * k if i == len(rest) else k, k)
            items.append(StoryItem(ref=s.id, role="photo", t0=0.0, t1=take(n), section="reel",
                                   note="the last photo holds a little longer" if i == len(rest) else ""))
        if len(shots) >= 4 and "loop" not in self.no:
            items.append(StoryItem(ref=cover.id, role="loop", t0=0.0, t1=take(k), section="reel",
                                   note="loop ending: back to the cover so the Reel replays seamlessly"))
        self._reel = {**grid, "k": k, "lines": lines}
        return StoryPlan(direction_id=d.id, items=items, sections=[StorySection(name="reel", music_mode="front")],
                         why=(f"cut on the beat of the song ({grid['bpm']:.0f} BPM, from {'its ' + grid['label'] if grid['label'] else 'a downbeat'}):"
                              f" every photo lasts {k} beat(s)"))

    def _polish_photo_reel(self, d: Direction, story: StoryPlan, pp: PolishPlan) -> None:
        """Music fixed on the reel's beat grid; your lines (or where/when) on the photos, readable and off the faces."""
        reel = getattr(self, "_reel", None) or {**self._reel_grid(15.0), "k": 2, "lines": self.text_lines()}
        if reel["track"] and "music" not in self.no:
            label = f", the {reel['label']}" if reel.get("label") else ""
            pp.music = [MusicCue(section="reel", mode="front", track_id=reel["track"], offset=reel["offset"],
                                 why=f"{reel['bpm']:.0f} BPM — the photos change on its beats; it starts at {reel['offset']:.1f}s{label}")]
        if "text" in self.no:
            return
        lines = reel["lines"]
        t, starts = 0.0, []
        for it in story.items:
            starts.append((t, it))
            t += (it.t1 or 0) - (it.t0 or 0)
        if len(story.items) == 1 and lines and reel.get("slots"):
            # one photo: each line replaces the last on the beat; the last one stays until the end
            for i, (line, (a, b)) in enumerate(zip(lines, reel["slots"], strict=False)):
                t0 = self._beat_at(reel, a) - self._beat_at(reel, 0)
                t1 = self._beat_at(reel, reel["end"] if i == len(lines) - 1 else b) - self._beat_at(reel, 0)
                pp.effects.append(EffectCue(type="text", at=f"t:{t0:.3f}", text=line, style="photo", dur=round(t1 - t0 - 0.05, 3),
                                            position="center", confidence=1.0, intent="brief",
                                            why=f"your line {i + 1}" + (", from the first frame: it is the hook" if i == 0 else ", on the beat")))
            return
        title = self.photo_title()
        if lines:
            for i, (t0, it) in enumerate(starts):
                if i < len(lines) and it.role != "loop":
                    pp.effects.append(EffectCue(type="text", at=f"t:{t0:.3f}", text=lines[i], style="photo", position="center",
                                                dur=round((it.t1 or 0) - 0.05, 3), confidence=1.0, intent="brief",
                                                why=f"your line {i + 1} on photo {i + 1}"))
        elif title:
            dur = (story.items[0].t1 or 2.0) - 0.05
            pp.effects.append(EffectCue(type="text", at="t:0.000", text=title, style="photo", position="upper", dur=round(dur, 3),
                                        confidence=0.8, why="where and when, from your photos — on the cover only"))

    # ------------------------------------------------------------ polish
    def polish(self, d: Direction, story: StoryPlan) -> PolishPlan:
        pb = K.playbook(d.playbook)
        k = d.knobs
        pp = PolishPlan(direction_id=d.id, look=None if "look" in self.no else k.look)
        if d.playbook == "photo_reel":            # the photos, the song's beat and your words — nothing else
            self._polish_photo_reel(d, story, pp)
            return pp
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
        if d.playbook == "gaming" and meme_ok:
            # gaming: a fail meme right after the death — the setback before the comeback, and the classic gaming beat
            for it in story.items:
                if placed >= meme_budget or "fail" not in (it.note or "").split() or it.t0 is None:
                    continue
                asset = self._pick_meme(["fail"])
                if asset is None:
                    continue
                said = next((self._seg(e["reaction"]) for e in self._game_events(self._shot(it.ref).asset_id)
                             if e.get("fail") and e["reaction"] and it.t0 <= e["t"] <= (it.t1 or e["t"])), None)
                pp.effects.append(EffectCue(type="meme", at=f"{it.ref}@{it.t0:.1f}", asset=asset, intent="fail",
                                            why="fail meme right after the death" + (f": “{said.text.strip()[:40]}”" if said else ""),
                                            confidence=0.7 if not asset.startswith("meme:") else 0.45))
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
        # gaming: a callout on the best plays in the streamer's own words, a REPLAY label on the slow-mo
        if d.playbook == "gaming" and "text" not in self.no:
            if any(sec.name == "replay" for sec in story.sections) and any(it.role == "replay" for it in story.items):
                pp.effects.append(EffectCue(type="text", at="section:replay", text="REPLAY", style="card", dur=1.4, confidence=0.75,
                                            why="a replay tag in the corner, like a broadcast, so the slow-mo reads as a replay, not a glitch"))
            last_t = -1e9
            for it in story.items:
                if it.role not in ("highlight", "payoff") or "reaction" not in (it.note or "") or "fail" in (it.note or "").split():
                    continue                     # a death gets its meme, not a hype callout
                inside = [e for a in self.pa.assets if a.kind in (AssetKind.SCREEN, AssetKind.AROLL) for e in self._game_events(a.id)
                          if e["reaction"] and it.t0 is not None and it.t0 <= e["t"] <= (it.t1 or e["t"])]
                ev = max(inside, key=lambda e: e["score"]) if inside else None
                r = self._seg(ev["reaction"]) if ev else None
                if r is None or ev["t"] - last_t < 20:
                    continue
                words = [w for w in self.pa.words(r.asset_id) if w.id in r.word_ids and not w.filler]
                if not words:
                    continue
                call = reaction_text(r.text)
                pp.effects.append(EffectCue(type="text", at=words[0].id, text=call, style="callout", dur=max(1.6, 0.9 + len(call.split()) / 2.5),
                                            confidence=0.7, why=f"callout on the play, in your words: “{call}”"))
                last_t = ev["t"]
        # gaming with a webcam: the streamer's face, big, on the single biggest reaction (once — a habit would be noise)
        if d.playbook == "gaming" and "zoom" not in self.no:
            best = None
            for it in story.items:
                sh = self._shot(it.ref)
                if it.role not in ("highlight", "payoff") or it.t0 is None or sh is None:
                    continue
                for e in self._game_events(sh.asset_id):
                    rank = (not e.get("fail"), e["score"])        # the biggest win; a death gets its meme instead
                    if e["reaction"] and it.t0 <= e["t"] <= (it.t1 or e["t"]) and (best is None or rank > (not best.get("fail"), best["score"])):
                        best = e
            r = self._seg(best["reaction"]) if best else None
            if r is not None and self.pa.clips[r.asset_id].facecam:
                words = [w for w in self.pa.words(r.asset_id) if w.id in r.word_ids and not w.filler]
                if words:
                    pp.effects.append(EffectCue(type="facecam", at=words[0].id, dur=round(min(2.2, max(1.4, r.t1 - r.t0 + 0.4)), 2),
                                                confidence=0.75, why=f"your face, big, on the biggest reaction: “{reaction_text(r.text)}”"))
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
        opener = self._seg(story.items[0].ref) if story.items else None
        if opener is not None and d.hooks and opener.id not in d.hooks[0].refs and d.playbook != "comedy":
            hook_text = text_hook(opener.text) or hook_text      # the words on screen tease the line that actually opens it
        if d.playbook == "comedy":
            # comedy: tease the premise — putting the punchline on screen first kills the joke
            premise = next((self._seg(it.ref) for it in story.items if self._seg(it.ref)), None)
            punch_words = {w for it in story.items if it.role == "punchline" and self._seg(it.ref)
                           for w in re.findall(r"[a-z]{4,}", self._seg(it.ref).text.lower())}
            hook_text = text_hook(premise.text) if premise else None
            if hook_text and set(re.findall(r"[a-z]{4,}", hook_text.lower())) & punch_words - set(re.findall(r"[a-z]{4,}", premise.text.lower())):
                hook_text = None
        if hook_text and story.items and repeats_speech(hook_text, self._opening_speech(story.items[0])):
            hook_text = None              # the captions already say exactly this at the same moment: no echo on screen
        if d.aspect == "9:16" and hook_text:
            read = round(max(2.6, 0.8 + len(hook_text.split()) / 3.0), 1)      # long enough to read (≈ 3 words/s)
            pp.effects.append(EffectCue(type="text", at="start", text=hook_text, style="hook", dur=read, why="on-screen text hook (works on mute)", confidence=0.7))
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
