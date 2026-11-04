"""AI brain: the same plan objects as the Basic brain, with an AI editor's judgement on top.

Design for reliability:
  * the AI sees a compact **dossier** (IDs, facts, transcript; no footage file names, no GPS) plus the
    Basic brain's draft, and returns JSON for a strict schema;
  * every ID it returns is validated against the analysis; invalid parts are dropped, one repair round
    is attempted on schema errors, and any failure falls back to the Basic plan for that pass;
  * brief hard rules always survive (they are re-applied after the AI answers).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import knowledge as K
from ..config import Settings
from ..schema.analysis import ProjectAnalysis
from ..schema.brief import CreatorBrief, HardRule
from ..schema.media import AssetKind
from ..schema.plan import (
    BrollGap,
    CriticReport,
    Direction,
    DirectionSet,
    EffectCue,
    FixOp,
    HookOption,
    MusicBrief,
    MusicCue,
    PolishPlan,
    StoryItem,
    StoryPlan,
    StorySection,
)
from .basic import BasicBrain
from .providers import Provider, ProviderError

# ---------------------------------------------------------------- schemas (strict-mode friendly)
S, N = {"type": "string"}, {"type": "number"}
NS, NN = {"type": ["string", "null"]}, {"type": ["number", "null"]}


def arr(x: dict) -> dict:
    return {"type": "array", "items": x}


def obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def enum(vals) -> dict:
    return {"type": "string", "enum": list(vals)}


PLAYBOOKS = list(K.playbooks())
EFFECT_TYPES = ["zoom", "sfx", "meme", "text", "speed", "transition", "broll", "emphasis", "bleep", "split"]
SCHEMAS = {
    "director": obj({"directions": arr(obj({
        "playbook": enum(PLAYBOOKS), "name": S, "aspect": enum(["9:16", "16:9", "1:1", "4:5"]), "target_seconds": N, "why": S,
        "hooks": arr(obj({"refs": arr(S), "kind": enum(list(K.hooks())), "text_hook": NS, "why": S})),
        "outline": arr(S), "coverage_gaps": arr(S)}))}),
    "story": obj({"items": arr(obj({"ref": S, "role": S, "section": S, "t0": NN, "t1": NN, "note": S})),
                  "sections": arr(obj({"name": S, "music_mode": enum(["bed", "front", "light", "none"]), "card": NS})), "why": S}),
    "polish": obj({
        "music": arr(obj({"section": S, "mode": enum(["bed", "front", "light", "none"]), "track_id": NS, "mood": S, "search_terms": arr(S), "why": S})),
        "effects": arr(obj({"type": enum(EFFECT_TYPES), "at": S, "asset": NS, "value": NN, "text": NS, "style": NS, "why": S, "confidence": N})),
        "broll_gaps": arr(obj({"at": S, "want": S, "search_terms": arr(S)})), "vo_script": arr(S), "look": NS}),
    "critic": obj({"scores": obj({k: N for k in ("hook", "clarity", "story", "pacing", "payoff", "emotion", "restraint", "genre_fit")}),
                   "issues": arr(S), "fixes": arr(obj({"op": enum(["drop_effect", "drop_item", "swap_hook", "lower_density", "trim_item"]),
                                                        "target": S, "why": S})), "summary": S}),
    "vision": obj({"shots": arr(obj({"id": S, "desc": S, "tags": arr(S), "shot_type": enum(["wide", "medium", "close", "detail", "aerial", "screen", "other"]),
                                     "mood": S, "aesthetic": N}))}),
    "brief": obj({"rules": arr(obj({"kind": enum(list(HardRule.model_fields["kind"].annotation.__args__)), "target": S, "anchor": S, "value": NS})),
                  "playbook": {"type": ["string", "null"], "enum": PLAYBOOKS + [None]}, "aspect": NS, "target_length": NN, "pace": NN,
                  "captions": NS, "caption_lang": NS, "humour": NS, "look": NS, "goal": NS}),
    "revise": obj({"ops": arr(obj({"op": enum(["add_effect", "drop_effect", "drop_item", "trim_item", "set_speed", "swap_track", "add_text", "swap_hook"]),
                                   "at": S, "type": NS, "asset": NS, "value": NN, "text": NS, "why": S}))}),
}

SYSTEM = """You are PrePro's senior video editor. You plan edits for Instagram Reels, YouTube Shorts and YouTube videos
from a dossier of a creator's footage. You never see the footage files; you see IDs and facts.

{constitution}

Rules for your answers:
- Reference material ONLY by the IDs in the dossier (segments like C01.s2, words like C01.w14, shots like C02.k0,
  assets like A02 / I01). Never invent IDs, file names, song titles or timestamps.
- Every effect must state its motivation in "why" (the word, action, emotion beat or music hit that justifies it).
- Respect the creator's brief rules exactly; when a rule conflicts with taste, the rule wins.
- Split edits: effect type "split" at "before:<ref>" with style "J" (next sound leads its picture) or "L" (the voice
  runs under the next picture) and value = seconds (0.3–0.8).
- Output JSON only, matching the schema.

CRAFT (what top editors do — follow the recipe, respect the "not when"):
{craft}"""


class AIBrain(BasicBrain):
    """Routes each pass to a connector (or the rules engine) and validates everything that comes back."""

    name = "ai"

    def __init__(self, pa: ProjectAnalysis, brief: CreatorBrief | None, providers: dict[str, Provider | None], *, settings: Settings | None = None):
        super().__init__(pa, brief)
        self.providers = providers            # pass name → provider (None = rules)
        self.settings = settings or Settings()
        self.warnings: list[str] = []
        self.calls: list[dict] = []

    # ------------------------------------------------------------ plumbing
    def _call(self, pass_name: str, instruction: str, *, images: list[Path] | None = None, effort: str = "high", dossier: bool = True) -> dict | None:
        prov = self.providers.get(pass_name)
        if prov is None:
            return None
        system = SYSTEM.format(constitution=K.constitution(), craft=K.craft_brief())
        user = (self.dossier() + "\n\n" if dossier else "") + instruction
        schema = SCHEMAS[pass_name if pass_name in SCHEMAS else "director"]
        for attempt in range(2):
            try:
                rep = prov.complete_json(system, user, schema, images=images, effort=effort, pass_name=pass_name)
                self.calls.append({"pass": pass_name, "connector": prov.name, "usage": rep.usage.__dict__})
                if not isinstance(rep.data, dict):
                    raise ValueError("not a JSON object")
                return rep.data
            except (ProviderError, ValueError, json.JSONDecodeError) as e:
                if attempt == 0 and not isinstance(e, ProviderError):
                    user += f"\n\nYour previous answer was invalid ({e}). Return valid JSON for the schema only."
                    continue
                self.warnings.append(f"{pass_name}: {prov.name} failed ({str(e)[:160]}) — used the rules engine instead")
                return None
        return None

    def _ref_ok(self, ref: str) -> bool:
        return self._seg(ref) is not None or self._shot(ref) is not None

    def dossier(self) -> str:
        pa = self.pa
        lines = [f"SHOOT: {len(pa.assets)} assets · {int(pa.stats.get('days', 0))} day(s) · places: "
                 + ", ".join(sorted({c.place for c in pa.clips.values() if c.place})) + f" · speech language: {pa.speech_language or 'n/a'}"]
        lines.append("GENRE GUESSES: " + ", ".join(f"{g.playbook} {g.score:.2f}" for g in pa.genres))
        lines.append("\nTALKING (segment · time in clip · flags · text):")
        for a in self.talk_assets():
            ca = pa.clips[a.id]
            lines.append(f"[{a.id} {a.kind.value} {a.info.duration:.0f}s day{ca.day_index or '-'} {ca.place or ''}]")
            for s in ca.transcript.segments:
                why = self.is_cut_candidate(s)
                flags = ",".join(s.tags) + (f" CUT:{why.split('(')[0].strip()}" if why else "")
                lines.append(f"  {s.id} {s.t0:.1f}-{s.t1:.1f}s {('[' + flags + ']') if flags else ''} “{s.text}”")
        lines.append("\nSHOTS (id · len · move · quality · flags · place · description):")
        for a in pa.assets:
            if a.kind not in (AssetKind.BROLL, AssetKind.AROLL, AssetKind.SCREEN, AssetKind.IMAGE):
                continue
            ca = pa.clips[a.id]
            for s in ca.shots:
                desc = s.desc or ("talking head" if a.kind == AssetKind.AROLL else "")
                lines.append(f"  {s.id} {s.dur:.1f}s {s.camera_move} q{s.quality:.1f} fps{a.info.fps or 30:.0f} "
                             f"{('⚠' + ','.join(s.flags)) if s.flags else ''} {'dup' if s.dup_group and s.dup_rank else ''} "
                             f"{'action@' + ','.join(f'{x:.1f}' for x in s.action_peaks) if s.action_peaks else ''} "
                             f"{(ca.place or '')} {desc} {('tags:' + ','.join(s.tags)) if s.tags else ''}".rstrip())
        lines.append("\nMUSIC (id · label · bpm · mood · sections · vocals):")
        for a in pa.by_kind(AssetKind.MUSIC):
            m = pa.clips[a.id].music
            if m:
                from ..assist.music import has_vocals

                secs = " ".join(f"{s.label}{s.t0:.0f}-{s.t1:.0f}" for s in m.sections)
                lines.append(f"  {a.id} “{_label(a.name)}” {m.bpm:.0f}bpm {','.join(m.mood_tags)} · {secs} · vocals={has_vocals(a, m)}")
        memes = pa.by_kind(AssetKind.MEME_IMAGE, AssetKind.MEME_VIDEO)
        if memes:
            lines.append("\nMEMES (your library): " + "; ".join(f"{a.id} “{_label(a.name)}”" for a in memes))
        sfx = pa.by_kind(AssetKind.SFX)
        if sfx:
            lines.append("SFX (your library): " + "; ".join(f"{a.id} “{_label(a.name)}”" for a in sfx))
        lines.append("BUILT-IN SFX: sfx:whoosh, sfx:pop, sfx:riser, sfx:impact, sfx:ding, sfx:boom")
        cat = [m for m in K.memes() if m.culture in (self.brief.prefs.meme_flavour or "global", "global")][:24]
        lines.append("MEME CATALOGUE (suggest by id only; not in library): " + "; ".join(f"meme:{m.id} ({'/'.join(m.intent)})" for m in cat))
        if self.brief.rules or self.brief.raw_text:
            lines.append("\nCREATOR BRIEF (hard rules — must be met):")
            for r in self.brief.rules:
                lines.append(f"  - {r.kind} {r.target or ''} {('@' + r.anchor) if r.anchor else ''} {r.value if r.value is not None else ''} ← “{r.source.strip()[:100]}”")
            p = self.brief.prefs.model_dump(exclude_defaults=True)
            if p:
                lines.append(f"  preferences: {json.dumps(p, ensure_ascii=False)}")
        return "\n".join(lines)

    # ------------------------------------------------------------ passes
    def vision_tags(self, project_root: str | Path) -> int:
        """Tag shots from small contact sheets (only at privacy level 'thumbs')."""
        prov = self.providers.get("vision")
        if prov is None or prov.privacy != "thumbs":
            return 0
        from ..media.proxy import contact_sheet
        from ..project import Project

        proj = Project(project_root)
        shots = [s for s in self.pa.all_shots() if not s.tags and self.pa.asset(s.asset_id).kind in (AssetKind.BROLL, AssetKind.SCREEN, AssetKind.IMAGE)]
        done = 0
        for i in range(0, len(shots), 12):
            batch = shots[i: i + 12]
            frames, labels = [], []
            for s in batch:
                f = proj.cache / "frames" / f"{s.id}_1.jpg"
                if f.exists():
                    frames.append(f)
                    labels.append(s.id)
            if not frames:
                continue
            sheet = contact_sheet(frames, proj.sub("sent") / f"sheet_{i // 12}.jpg", cols=4, width=320, labels=labels)
            if self.settings.blur_faces_in_thumbs:
                _blur_faces(sheet)
            data = self._call("vision", "Describe each labelled thumbnail (id in the corner): what it shows (≤10 words), 3–6 tags, shot type, "
                              "mood, and aesthetic appeal 0–1. Only the ids shown.", images=[sheet], effort="low", dossier=False)
            for row in (data or {}).get("shots", []):
                sh = self._shot(str(row.get("id", "")))
                if sh is None:
                    continue
                sh.desc = str(row.get("desc", ""))[:120] or sh.desc
                sh.tags = [str(t)[:24] for t in row.get("tags", [])][:8]
                sh.shot_type = row.get("shot_type") or sh.shot_type
                sh.mood = str(row.get("mood", ""))[:24] or sh.mood
                try:
                    sh.aesthetic = max(0.0, min(1.0, float(row.get("aesthetic"))))
                except (TypeError, ValueError):
                    pass
                done += 1
        return done

    def directions(self, max_n: int = 4) -> DirectionSet:
        base = super().directions(max_n)
        data = self._call("director", "TASK: propose 2–4 creative directions this footage can become (different playbooks/formats). "
                          "For each: 3 hook options (refs = segment or shot ids; text_hook ≤ 7 words for vertical formats), an outline, "
                          "and coverage gaps (shots or lines the creator should record next time). Draft from the rules engine:\n"
                          + json.dumps([{"playbook": d.playbook, "aspect": d.aspect, "target_seconds": d.knobs.target_length,
                                         "hooks": [h.refs for h in d.hooks]} for d in base.directions]))
        if not data:
            return base
        out = []
        by_pb = {d.playbook: d for d in base.directions}
        for i, row in enumerate(data.get("directions", [])[:max_n]):
            pb = row.get("playbook")
            if pb not in K.playbooks():
                continue
            ref = by_pb.get(pb) or super().directions(max_n).directions[0]
            d = ref.model_copy(deep=True)
            d.id = f"d{len(out) + 1}"
            d.playbook = pb
            d.name = str(row.get("name") or d.name)[:80]
            d.aspect = row.get("aspect") if row.get("aspect") in ("9:16", "16:9", "1:1", "4:5") else d.aspect
            if self.brief.prefs.aspect and i == 0:
                d.aspect = self.brief.prefs.aspect
            try:
                t = float(row.get("target_seconds") or 0)
                if t > 3 and not self.brief.prefs.target_length:
                    d.knobs.target_length = t
                    d.target_min, d.target_max = round(t * 0.85, 1), round(t * 1.15, 1)
            except (TypeError, ValueError):
                pass
            hooks = []
            for h in row.get("hooks", [])[:3]:
                refs = [r for r in h.get("refs", []) if self._ref_ok(r)]
                if refs:
                    hooks.append(HookOption(id=f"h{len(hooks)}", kind=h.get("kind", "curiosity_gap"), refs=refs,
                                            text_hook=(h.get("text_hook") or None), why=str(h.get("why", ""))[:200], score=0.8 - 0.1 * len(hooks)))
            forced = next((r for r in self.rules if r.kind == "hook" and r.target), None)
            if forced:
                hooks = [x for x in ref.hooks if x.kind == "from_brief"] + [x for x in hooks if forced.target not in x.refs]
            d.hooks = hooks[:3] or ref.hooks
            d.why = str(row.get("why", d.why))[:300]
            d.outline = [str(x)[:160] for x in row.get("outline", [])][:8] or d.outline
            d.coverage_gaps = list(dict.fromkeys(ref.coverage_gaps + [str(x)[:200] for x in row.get("coverage_gaps", [])]))[:8]
            d.from_brief = pb == self.brief.prefs.playbook
            out.append(d)
        if not out:
            return base
        return DirectionSet(directions=out, notes=base.notes + " · directions by AI editor")

    def story(self, d: Direction) -> StoryPlan:
        base = super().story(d)
        pb = K.playbook(d.playbook)
        data = self._call("story", f"TASK: build the story for direction “{d.name}” (playbook {d.playbook}: structure {' → '.join(pb.structure)}; "
                          f"target {d.knobs.target_length:.0f}s; hook first: {d.hooks[0].refs if d.hooks else 'your choice'}). "
                          "Order segments and shots for a story with causality (but/therefore), not shooting order. Skip CUT-flagged segments. "
                          "For shots give t0/t1 inside the shot. Sections carry music modes. Rules-engine draft to improve:\n"
                          + "\n".join(f"{it.role}:{it.ref}{f' {it.t0:.1f}-{it.t1:.1f}' if it.t0 is not None else ''} [{it.section}]" for it in base.items))
        if not data:
            return base
        items = []
        excluded = {r.target for r in self.rules if r.kind == "must_exclude"}
        for row in data.get("items", []):
            ref = str(row.get("ref", ""))
            if not self._ref_ok(ref) or ref in excluded:
                continue
            seg, sh = self._seg(ref), self._shot(ref)
            if seg is not None and self.is_cut_candidate(seg) and ref not in self.included:
                continue
            it = StoryItem(ref=ref, role=str(row.get("role") or "body")[:20], section=str(row.get("section") or "main")[:30], note=str(row.get("note", ""))[:160])
            if sh is not None:
                try:
                    t0, t1 = float(row.get("t0")), float(row.get("t1"))
                    if sh.t0 - 0.05 <= t0 < t1 <= sh.t1 + 0.05 and t1 - t0 >= 0.4:
                        it.t0, it.t1 = round(max(sh.t0, t0), 3), round(min(sh.t1, t1), 3)
                except (TypeError, ValueError):
                    pass
                if it.t0 is None:
                    it.t0, it.t1 = self._window(sh, float(sum(pb.pacing.broll_shot)) / 2)
            items.append(it)
        if len(items) < 2:
            self.warnings.append("story: AI answer unusable — used the rules draft")
            return base
        # brief guarantees: forced hook first, must-includes present
        forced = next((r.target for r in self.rules if r.kind == "hook" and r.target), None)
        if forced:
            items = [i for i in items if i.ref != forced]
            items.insert(0, StoryItem(ref=forced, role="hook", section=items[0].section if items else "cold_open"))
        have = {i.ref for i in items}
        for base_it in base.items:
            if base_it.ref in self.included and base_it.ref not in have:
                items.append(base_it)
        sections = []
        for row in data.get("sections", []):
            name = str(row.get("name", ""))[:30]
            if name and name in {i.section for i in items}:
                sections.append(StorySection(name=name, music_mode=row.get("music_mode") if row.get("music_mode") in ("bed", "front", "light", "none") else "bed",
                                             card=row.get("card") or None))
        for sec in {i.section for i in items} - {s.name for s in sections}:
            sections.append(StorySection(name=sec))
        order = []
        for i in items:
            if i.section not in order:
                order.append(i.section)
        sections.sort(key=lambda s: order.index(s.name) if s.name in order else 99)
        return StoryPlan(direction_id=d.id, hook_id=d.hooks[0].id if d.hooks else None, items=self._fit(items, d.knobs.target_length or 60, d),
                         sections=sections, why=str(data.get("why", ""))[:300] or base.why)

    def polish(self, d: Direction, story: StoryPlan) -> PolishPlan:
        base = super().polish(d, story)
        pb = K.playbook(d.playbook)
        data = self._call("polish", f"TASK: polish direction “{d.name}” ({d.playbook}). Budgets per minute: {json.dumps(pb.budgets)}. "
                          f"Music: pick track ids ONLY from MUSIC (bed under speech = instrumental), or null + search_terms. Effects anchor 'at' = a word/segment/shot id, "
                          "'start', 'end', 'section:<name>' or 'before:<ref>'. Memes: library ids or meme:<catalogue id> AFTER a punchline, never over it. "
                          "Story:\n" + "\n".join(f"[{it.section}] {it.role} {it.ref}" + (f" “{self._seg(it.ref).text[:70]}”" if self._seg(it.ref) else "") for it in story.items)
                          + "\nRules-engine draft to improve:\n" + json.dumps({"music": [{"section": m.section, "mode": m.mode, "track": m.track_id} for m in base.music],
                                                                              "effects": [{"type": e.type, "at": e.at, "asset": e.asset, "why": e.why} for e in base.effects]}),
                          effort="medium")
        if not data:
            return base
        pp = PolishPlan(direction_id=d.id, look=data.get("look") or base.look, vo_script=[str(x)[:200] for x in data.get("vo_script", [])][:6] or base.vo_script)
        music_ids = {a.id for a in self.pa.by_kind(AssetKind.MUSIC)}
        sec_names = {s.name for s in story.sections}
        for row in data.get("music", []):
            if row.get("section") not in sec_names:
                continue
            tid = row.get("track_id") if row.get("track_id") in music_ids else None
            pp.music.append(MusicCue(section=row["section"], mode=row.get("mode") or "bed", track_id=tid,
                                     brief=MusicBrief(mood=str(row.get("mood", "neutral"))[:20], search_terms=[str(x)[:60] for x in row.get("search_terms", [])][:3]),
                                     why=str(row.get("why", ""))[:160]))
        for m in base.music:   # sections the AI forgot keep the rules choice
            if m.section not in {x.section for x in pp.music}:
                pp.music.append(m)
        # brief music rules win
        if any(r.kind in ("use_music", "no_music_under_speech") or (r.kind == "no_effect" and r.target == "music") for r in self.rules):
            pp.music = base.music
        assets = {a.id for a in self.pa.assets}
        for row in data.get("effects", []):
            t = row.get("type")
            at = str(row.get("at", ""))
            if t not in EFFECT_TYPES or not self._anchor_ok(at):
                continue
            if t in self.no or (t == "sfx" and "sfx" in self.no):
                continue
            asset = row.get("asset")
            if asset and not (asset in assets or asset.startswith(("meme:", "sfx:")) or self._ref_ok(asset)):
                asset = None
            if t in ("meme", "broll", "sfx") and not asset:
                continue
            conf = max(0.0, min(0.95, float(row.get("confidence") or 0.7)))
            pp.effects.append(EffectCue(type=t, at=at, asset=asset, value=row.get("value"), text=(row.get("text") or None),
                                        style=row.get("style") or None, why=str(row.get("why", ""))[:200] or "AI editor", confidence=conf))
        pp.effects += [e for e in base.effects if e.confidence >= 1.0]       # brief-forced effects always survive
        for row in data.get("broll_gaps", []):
            if self._seg(str(row.get("at", ""))):
                pp.broll_gaps.append(BrollGap(at=row["at"], want=str(row.get("want", ""))[:120], search_terms=[str(x)[:40] for x in row.get("search_terms", [])][:4]))
        pp.notes = ["polish by AI editor"]
        return pp

    def _anchor_ok(self, at: str) -> bool:
        if at in ("start", "end") or at.startswith("section:"):
            return True
        if at.startswith("before:"):
            return self._ref_ok(at.split(":", 1)[1]) or at.startswith("before:section:")
        if ".w" in at:
            return any(w.id == at for a in self.talk_assets() for w in self.pa.words(a.id))
        return self._ref_ok(at)

    def critic(self, paper_edit: str, rules_report: CriticReport, effects: list | None = None) -> CriticReport:
        fx = "\n".join(f"  {e.type}:{e.at}  ({e.why[:60]})" for e in (effects or []) if e.confidence < 1.0)
        data = self._call("critic", "TASK: you are reviewing a junior editor's cut. Score 0–10 (hook, clarity, story, pacing, payoff, emotion, "
                          "restraint, genre_fit). Name concrete issues (what would make a viewer cringe or scroll) and fixes from the allowed ops. "
                          "Fix targets: drop_item → a shot/segment id; lower_density → zoom|sfx|meme|text|transition; drop_effect → one of the "
                          "effect ids below (type:anchor). Brief-required effects are not listed and cannot be dropped.\nEFFECTS:\n" + fx +
                          "\nRules-engine findings: " + "; ".join(rules_report.issues[:10]) + "\nPAPER EDIT:\n" + paper_edit, effort="high")
        if not data:
            return rules_report
        rep = CriticReport(scores={k: round(max(0.0, min(10.0, float(v))), 1) for k, v in (data.get("scores") or {}).items() if isinstance(v, (int, float))},
                           issues=[str(x)[:200] for x in data.get("issues", [])][:12], summary=str(data.get("summary", ""))[:300], source="ai")
        for f in data.get("fixes", [])[:8]:
            try:
                rep.fixes.append(FixOp(op=f["op"], target=str(f.get("target", ""))[:40], why=str(f.get("why", ""))[:160]))
            except Exception:
                continue
        return rep

    def revise(self, text: str, t: float, tl, pa: ProjectAnalysis) -> tuple[list, str]:
        """A timeline note the rules couldn't parse → validated revision ops (see prepro.revise)."""
        from ..revise import Op

        if self.providers.get("revise") is None:
            return [], ""
        pe = [ln for ln in paper_edit(tl, pa).splitlines() if abs(float(ln[:6]) - t) <= 15]
        wt = tl.meta.get("word_t") or {}
        wtext = {w.id: w.text for a in {i.asset_id for i in tl.items if i.track == "A1" and i.asset_id} for w in pa.words(a)}
        words = [f"{wid}@{tt:.1f}s “{wtext.get(wid, '')}”" for wid, tt in sorted(wt.items(), key=lambda kv: kv[1]) if abs(tt - t) <= 4]
        keys = {s.payload["key"]: s for s in tl.suggestions if s.payload.get("key") and s.status == "applied"}
        fx = [f"{k} ({s.type}: {s.reason[:50]})" for k, s in keys.items() if s.t is not None and abs(s.t - t) <= 8]
        on_tl = {i.ref for i in tl.items if i.ref}
        data = self._call("revise", f"TASK: the creator left a note on the timeline at {t:.1f}s: “{text}”. Turn it into edit ops. "
                          "drop_effect: at = an EFFECT key below. drop_item: at = a segment/shot id on the timeline. trim_item: at = shot id, "
                          "value = length factor 0.3–2. set_speed: at = shot id, value 0.25–4. add_effect: type zoom|sfx|emphasis (at = word id) "
                          "or meme|broll (at = segment id), asset = library id or sfx:name. add_text: at = word id, text, type = style "
                          "(big|small|callout|card). swap_track: at = section names, asset = music id. Return no ops if the note can't be "
                          "done with these.\nWORDS NEAR THE NOTE: " + "; ".join(words) + "\nEFFECTS NEAR THE NOTE:\n" + "\n".join(fx) +
                          "\nPAPER EDIT AROUND THE NOTE:\n" + "\n".join(pe), effort="medium")
        if not data:
            return [], ""
        ops: list[Op] = []
        segs_on = {i.ref for i in tl.items if i.track == "A1" and i.ref}
        for o in data.get("ops", [])[:6]:
            kind, at, why = o.get("op"), str(o.get("at") or ""), str(o.get("why") or text)[:120]
            asset = o.get("asset")
            if kind == "drop_effect" and at in keys:
                ops.append(Op(op="reject", key=at, why=why))
            elif kind == "drop_item" and at in on_tl and not at.startswith("fx:"):
                ops.append(Op(op="drop", ref=at, why=why))
            elif kind == "trim_item" and self._shot(at) and isinstance(o.get("value"), (int, float)):
                ops.append(Op(op="trim", ref=at, value=max(0.3, min(2.0, float(o["value"]))), why=why))
            elif kind == "set_speed" and self._shot(at) and isinstance(o.get("value"), (int, float)):
                ops.append(Op(op="add", cue=EffectCue(type="speed", at=at, value=max(0.25, min(4.0, float(o["value"]))), why=why), why=why))
            elif kind == "add_effect" and o.get("type") in ("zoom", "sfx", "emphasis") and at in wt:
                if o["type"] == "sfx" and not (isinstance(asset, str) and (asset.startswith("sfx:") or any(a.id == asset for a in pa.assets))):
                    asset = "sfx:pop"
                ops.append(Op(op="add", cue=EffectCue(type=o["type"], at=at, asset=asset if o["type"] == "sfx" else None,
                                                      value=1.16 if o["type"] == "zoom" else None, style="big" if o["type"] == "emphasis" else None,
                                                      why=why), why=why))
            elif kind == "add_effect" and o.get("type") in ("meme", "broll") and at in segs_on and isinstance(asset, str):
                ok = any(a.id == asset for a in pa.assets) if o["type"] == "meme" else self._shot(asset) is not None
                if ok:
                    ops.append(Op(op="add", cue=EffectCue(type=o["type"], at=at, asset=asset, dur=2.5 if o["type"] == "broll" else None, why=why), why=why))
            elif kind == "add_text" and (at in wt or at in segs_on) and o.get("text"):
                style = o.get("type") if o.get("type") in ("big", "small", "callout", "card") else "callout"
                ops.append(Op(op="add", cue=EffectCue(type="text", at=at, text=str(o["text"])[:60], style=style, dur=2.2, why=why), why=why))
            elif kind == "swap_track" and isinstance(asset, str) and any(a.id == asset and a.kind == AssetKind.MUSIC for a in pa.assets):
                ops.append(Op(op="swap_track", ref=at, value=asset, why=why))
        return ops, ("AI: " + "; ".join(o.why for o in ops)) if ops else ""

    def parse_brief(self, text: str) -> CreatorBrief:
        data = self._call("brief", "TASK: turn this creator brief into hard rules and preferences. Anchors are the creator's own words "
                          "(we resolve them). Brief:\n" + text, effort="low", dossier=False)
        b = self.brief.model_copy(deep=True)
        if not data:
            return b
        for r in data.get("rules", []):
            try:
                b.rules.append(HardRule(kind=r["kind"], target=str(r.get("target", "")), anchor=str(r.get("anchor", "")), value=r.get("value"), source=f"AI: {text[:80]}"))
            except Exception:
                continue
        for k in ("playbook", "aspect", "captions", "caption_lang", "humour", "look", "goal"):
            if data.get(k) and getattr(b.prefs, k) in (None, ""):
                setattr(b.prefs, k, data[k])
        for k in ("target_length", "pace"):
            if data.get(k) is not None and getattr(b.prefs, k) is None:
                setattr(b.prefs, k, float(data[k]))
        b.parsed_by = "ai"
        return b


def _label(name: str) -> str:
    stem = name.rsplit(".", 1)[0]
    return re.sub(r"[_\-]+", " ", stem)[:40]


def _blur_faces(img_path: Path) -> None:
    import cv2

    from ..analyze.visual import face_detector

    im = cv2.imread(str(img_path))
    if im is None:
        return
    rgb = im[:, :, ::-1]
    h, w = im.shape[:2]
    for f in face_detector()(rgb, 0.0, conf=0.5):
        x0, y0 = int((f.x - f.w / 2) * w), int((f.y - f.h / 2) * h)
        x1, y1 = int((f.x + f.w / 2) * w), int((f.y + f.h / 2) * h)
        roi = im[max(0, y0):y1, max(0, x0):x1]
        if roi.size:
            im[max(0, y0):y1, max(0, x0):x1] = cv2.GaussianBlur(roi, (0, 0), 12)
    cv2.imwrite(str(img_path), im)


def paper_edit(tl, pa: ProjectAnalysis) -> str:
    """Text version of the cut for the critic: time · track · what · effects."""
    out = []
    for it in sorted(tl.items, key=lambda i: (i.rec_in, i.track)):
        what = ""
        if it.track == "A1" and it.role not in ("natural",):
            ws = [w.text for w in pa.words(it.asset_id) if it.src_in - 0.01 <= w.t0 and w.t1 <= it.src_out + 0.05 and not w.filler]
            what = "“" + " ".join(ws)[:110] + "”"
        elif it.kind == "text":
            what = f"[TEXT {it.style}] “{it.text}”"
        elif it.track == "A2":
            what = f"[MUSIC {pa.asset(it.asset_id).id}]"
        elif it.track == "A3":
            what = f"[SFX {it.note or it.asset_id}]"
        elif it.track in ("V1", "V2"):
            sh = next((s for s in pa.clips[it.asset_id].shots if s.t0 <= it.src_in < s.t1 + 0.01), None) if it.asset_id else None
            fx = []
            if it.transform and it.transform.zoom > 1.01:
                fx.append(f"zoom {it.transform.zoom:.2f}")
            if abs(it.speed - 1) > 1e-3:
                fx.append(f"{it.speed:g}x")
            if it.transition_in != "cut":
                fx.append(it.transition_in)
            what = f"[{'B-ROLL OVER' if it.track == 'V2' else 'PICTURE'} {it.role or ''} {sh.id if sh else it.asset_id} {sh.desc or sh.camera_move if sh else ''}] {' '.join(fx)}"
        else:
            continue
        out.append(f"{it.rec_in:6.1f}-{it.rec_out:6.1f} {it.track} {what}")
    return "\n".join(out)
