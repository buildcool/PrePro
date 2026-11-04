"""High-level API used by the CLI, the server and the desktop app."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .analyze.context import CONTEXT_VERSION
from .analyze.pipeline import ANALYSIS_VERSION, analyse_project, load_analysis
from .brain.basic import BasicBrain
from .brief.parse import load_brief, parse_text
from .brief.resolve import resolve
from .config import Settings
from .project import Project
from .schema.analysis import ProjectAnalysis
from .schema.brief import CreatorBrief
from .schema.plan import CriticReport, Direction, DirectionSet, PolishPlan, StoryPlan
from .schema.timeline import Timeline
from .timeline.compiler import compile_timeline


def make_brain(pa: ProjectAnalysis, brief: CreatorBrief, settings: Settings, root: str | Path, *, overrides: dict | None = None):
    """BasicBrain when every pass is routed to 'basic', otherwise an AIBrain with one provider per pass."""
    from .brain.providers import make_provider

    routing = settings.routing.model_dump()
    routing.update(overrides or {})
    if all(v in ("basic", None, "") for v in routing.values()):
        return BasicBrain(pa, brief)
    from .brain.ai import AIBrain

    sent = Project(root).sub("sent")
    providers = {}
    for pass_name, conn in routing.items():
        if conn in ("basic", None, ""):
            providers[pass_name] = None
            continue
        cfg = settings.connectors.get(conn)
        if cfg is None:
            from .brain.providers import detect_connectors

            cfg = detect_connectors().get(conn)
        providers[pass_name] = make_provider(conn, cfg, sent_dir=sent, privacy=settings.privacy) if cfg else None
    return AIBrain(pa, brief, providers, settings=settings)


@dataclass
class BuildResult:
    directions: DirectionSet
    direction: Direction
    story: StoryPlan
    polish: PolishPlan
    timeline: Timeline
    lint: list = field(default_factory=list)
    critic: CriticReport | None = None
    render: object | None = None
    brief: CreatorBrief | None = None
    timeline_path: Path | None = None
    ai_calls: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(c["usage"].get("usd", 0.0) for c in self.ai_calls if not c["usage"].get("plan_usage")), 4)


def analysis(root: str | Path, *, settings: Settings | None = None, force: bool = False, progress=None) -> ProjectAnalysis:
    pa = None if force else load_analysis(root)
    proj = Project(root)
    if pa is not None and pa.version != ANALYSIS_VERSION:
        pa = None
    if pa is not None:
        # re-analyse if files changed
        scan = proj.scan()
        if {f.rel for f in scan.files} != {a.path for a in pa.assets}:
            pa = None
    if pa is not None and any(c.transcript and c.transcript.backend == "pocketsphinx" for c in pa.clips.values()):
        s = settings or Settings.load()
        from .analyze.asr import whisper_available

        if s.asr.backend == "auto" and whisper_available(s.asr.whisper_model):
            pa = None                     # Whisper was downloaded since: redo the rough transcripts (other clips stay cached)
    if pa is not None and pa.stats.get("context_version", 1) < CONTEXT_VERSION:
        from .analyze import context as ctx

        ctx.cluster_context(pa)
        pa.genres = ctx.guess_genres(pa)
        pa.stats["context_version"] = CONTEXT_VERSION
        proj.save_model("analysis.json", pa)
    return pa or analyse_project(root, settings=settings, progress=progress, force=force)


def brief_for(root: str | Path, pa: ProjectAnalysis, *, extra_text: str | None = None, settings: Settings | None = None) -> CreatorBrief:
    proj = Project(root)
    scan = proj.scan()

    def voice(path: Path) -> str:
        from .analyze.asr import transcribe
        from .media.proxy import extract_audio

        wav = proj.sub("audio") / "brief_voice.wav"
        extract_audio(path, wav, sr=16000)
        s = settings or Settings.load()
        tr = transcribe("brief", wav, backend=s.asr.backend, model=s.asr.whisper_model)
        return " ".join(w.text for w in tr.words)

    b = load_brief(scan.brief_files, transcribe_voice=voice)
    if extra_text:
        parse_text(extra_text, b)
        b.sources.append("ui")
    # filename tags (HOOK_ / MUST_ / SKIP_) are brief rules too
    from .schema.brief import HardRule

    for a in pa.assets:
        if "skip" in a.tags:
            b.rules.append(HardRule(kind="must_exclude", target=a.id, source=f"filename tag on {a.name}"))
        if "must" in a.tags:
            b.rules.append(HardRule(kind="must_include", target=a.id, source=f"filename tag on {a.name}"))
        if "hook" in a.tags:
            segs = pa.clips[a.id].transcript.segments if pa.clips[a.id].transcript else []
            shots = pa.clips[a.id].shots
            tgt = segs[0].id if segs else (shots[0].id if shots else "")
            if tgt:
                b.rules.append(HardRule(kind="hook", target=tgt, anchor=a.name, source=f"filename tag on {a.name}"))
    for r in b.rules:   # SKIP/MUST on whole assets apply to their shots
        if r.kind in ("must_exclude", "must_include") and r.target in {a.id for a in pa.assets}:
            pass
    resolve(b, pa)
    return b


def directions(root: str | Path, *, settings: Settings | None = None, brief_text: str | None = None, routing: dict | None = None,
               progress=None) -> tuple[DirectionSet, CreatorBrief, list]:
    """Only the Director pass (cheap): direction cards + hooks + coverage gaps, so quality can be judged before a build."""
    settings = settings or Settings.load()
    pa = analysis(root, settings=settings, progress=progress)
    brief = brief_for(root, pa, extra_text=brief_text, settings=settings)
    brain = make_brain(pa, brief, settings, root, overrides=routing)
    if hasattr(brain, "parse_brief") and brief.raw_text and brain.providers.get("brief"):
        brief = brain.parse_brief(brief.raw_text)
        resolve(brief, pa)
        brain.brief, brain.rules = brief, brief.rules
    ds = brain.directions()
    proj = Project(root)
    proj.save_model("directions.json", ds)
    proj.save_model("brief.json", brief)
    return ds, brief, getattr(brain, "calls", [])


def choose(ds: DirectionSet, which: str | None) -> Direction:
    if not which or which == "auto":
        return ds.directions[0]
    for d in ds.directions:
        if which in (d.id, d.playbook):
            return d
    raise KeyError(f"no direction {which!r}; have {[d.id + ':' + d.playbook for d in ds.directions]}")


def build(root: str | Path, *, direction: str | None = "auto", settings: Settings | None = None, brief_text: str | None = None,
          render: bool = True, quality: str = "preview", lint: bool = True, progress=None, extra_playbook: str | None = None,
          routing: dict | None = None, knobs: dict | None = None) -> BuildResult:
    settings = settings or Settings.load()
    pa = analysis(root, settings=settings, progress=progress)
    brief = brief_for(root, pa, extra_text=brief_text, settings=settings)
    if extra_playbook:
        brief.prefs.playbook = extra_playbook
    brain = make_brain(pa, brief, settings, root, overrides=routing)
    if hasattr(brain, "vision_tags") and brain.vision_tags(root):
        Project(root).save_model("analysis.json", pa)
    if hasattr(brain, "parse_brief") and brief.raw_text and brain.providers.get("brief"):
        brief = brain.parse_brief(brief.raw_text)
        resolve(brief, pa)
        brain.brief = brief
        brain.rules = brief.rules
    ds = brain.directions()
    d = choose(ds, direction)
    from .style import load as load_style

    dna = load_style(root)
    if dna is not None and dna.enabled and dna.knobs:
        sk = dict(dna.knobs)
        if brief.prefs.target_length:                       # the brief's length wins
            sk.pop("target_length", None)
        if any(r.kind == "captions" for r in brief.rules):  # so do caption rules
            sk.pop("captions", None)
        d.knobs = d.knobs.model_copy(update={k: v for k, v in sk.items() if k in type(d.knobs).model_fields})
        if sk.get("target_length"):
            L = float(sk["target_length"])
            d.target_min, d.target_max = round(L * 0.85, 1), round(L * 1.15, 1)
        d.why = (d.why + " · " if d.why else "") + "styled like your references"
    if knobs:
        d.knobs = d.knobs.model_copy(update={k: v for k, v in knobs.items() if k in type(d.knobs).model_fields and v is not None})
        if knobs.get("target_length"):
            L = float(knobs["target_length"])
            d.target_min, d.target_max = round(L * 0.85, 1), round(L * 1.15, 1)
    story = brain.story(d)
    polish = brain.polish(d, story)
    tl = compile_timeline(pa, d, story, polish, brief, project_root=root)
    res = BuildResult(directions=ds, direction=d, story=story, polish=polish, timeline=tl, brief=brief)
    if lint:
        from .lint.editlint import apply_fixes, lint_timeline

        findings = lint_timeline(tl, pa, d, brief)
        if any(f.fix for f in findings):
            polish2, story2 = apply_fixes(findings, polish, story, pa, d)
            tl = compile_timeline(pa, d, story2, polish2, brief, project_root=root)
            res.story, res.polish, res.timeline = story2, polish2, tl
            findings = lint_timeline(tl, pa, d, brief)
        res.lint = findings
        from .lint.critic import rules_critic

        res.critic = rules_critic(tl, pa, d, findings)
        if hasattr(brain, "critic") and brain.providers.get("critic"):
            from .brain.ai import paper_edit
            from .lint.editlint import Finding

            ai = brain.critic(paper_edit(tl, pa), res.critic, res.polish.effects)
            if ai.source == "ai":
                safe = [Finding(rule="critic", severity="info", msg=f.why, fix=f) for f in ai.fixes if f.op in ("drop_effect", "drop_item", "lower_density")
                        and f.target not in {r.target for r in brief.rules}]
                if safe:
                    polish3, story3 = apply_fixes(safe, res.polish, res.story, pa, d)
                    tl = compile_timeline(pa, d, story3, polish3, brief, project_root=root)
                    res.story, res.polish, res.timeline = story3, polish3, tl
                    res.lint = lint_timeline(tl, pa, d, brief)
                ai.scores = {**res.critic.scores, **ai.scores}
                res.critic = ai
    if hasattr(brain, "calls"):
        res.ai_calls, res.warnings = brain.calls, brain.warnings
    proj = Project(root)
    res.timeline_path = proj.save_model(f"timelines/{tl.id}.json", res.timeline)
    proj.save_model("directions.json", ds)
    proj.save_model("brief.json", brief)
    proj.save_model(f"timelines/{tl.id}.story.json", res.story)
    proj.save_model(f"timelines/{tl.id}.polish.json", res.polish)
    if render:
        from .export.render import render as do_render

        out = proj.sub("renders") / f"{tl.id}_{quality}.mp4"
        res.render = do_render(res.timeline, pa, out, quality=quality, project_root=root)
        if lint:
            from .lint.editlint import lint_render

            res.lint += lint_render(res.render, d)
    return res
