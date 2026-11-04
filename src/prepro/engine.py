"""High-level API used by the CLI, the server and the desktop app."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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


def choose(ds: DirectionSet, which: str | None) -> Direction:
    if not which or which == "auto":
        return ds.directions[0]
    for d in ds.directions:
        if which in (d.id, d.playbook):
            return d
    raise KeyError(f"no direction {which!r}; have {[d.id + ':' + d.playbook for d in ds.directions]}")


def build(root: str | Path, *, direction: str | None = "auto", settings: Settings | None = None, brief_text: str | None = None,
          render: bool = True, quality: str = "preview", lint: bool = True, progress=None, extra_playbook: str | None = None) -> BuildResult:
    settings = settings or Settings.load()
    pa = analysis(root, settings=settings, progress=progress)
    brief = brief_for(root, pa, extra_text=brief_text, settings=settings)
    brain = BasicBrain(pa, brief)
    ds = brain.directions()
    if extra_playbook and extra_playbook not in [d.playbook for d in ds.directions]:
        brief.prefs.playbook = extra_playbook
        ds = BasicBrain(pa, brief).directions()
    d = choose(ds, direction)
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
