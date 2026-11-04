"""``prepro`` command-line interface."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__

app = typer.Typer(add_completion=False, no_args_is_help=True, help="PrePro — AI pre-edit engine: shoot folder → reasoned first cut.")
testmedia_app = typer.Typer(help="Download / list real test media (dev only).")
app.add_typer(testmedia_app, name="testmedia")
brains_app = typer.Typer(help="AI connectors: list, add, keys, routing, test, compare.")
app.add_typer(brains_app, name="brains")
console = Console()


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"prepro {__version__}")


@app.command()
def shorts(
    shoot: Path = typer.Argument(..., help="Shoot folder with long talking footage (podcast, vlog, interview)"),
    count: int = typer.Option(3, help="How many Shorts"),
    min_len: float = typer.Option(15.0, "--min", help="Shortest clip (s)"),
    max_len: float = typer.Option(60.0, "--max", help="Longest clip (s)"),
    render: bool = typer.Option(False, help="Also render a preview of each"),
) -> None:
    """Find the self-contained moments in long talks and cut each as a vertical Short (review them in `prepro ui`)."""
    from .repurpose import build_shorts

    with console.status("Finding Shorts…"):
        res = build_shorts(shoot, count=count, min_len=min_len, max_len=max_len, render=render)
    if not res:
        console.print("[yellow]No self-contained moments found — is there enough talking footage?")
        return
    for c, tid in res:
        console.rule(f"[bold]{c.id}[/] {c.dur:.0f}s · score {c.score:.2f} → timeline {tid}")
        console.print(f"  “{c.hook}”")
        for w in c.why:
            console.print(f"  · {w}")


@app.command()
def style(
    shoot: Path = typer.Argument(..., help="Shoot folder; reference videos go in <shoot>/style/ (or references/)"),
    refs: list[Path] = typer.Option(None, "--ref", help="Reference video(s) instead of the style/ folder"),
    off: bool = typer.Option(False, "--off", help="Keep the measurements but stop applying them"),
) -> None:
    """Style DNA: measure how reference videos are edited; the next `build` cuts in that style."""
    from .project import Project
    from .style import load, measure_shoot

    if off:
        dna = load(shoot)
        if dna:
            dna.enabled = False
            Project(shoot).save_model("style.json", dna)
        console.print("Style DNA off.")
        return
    with console.status("Measuring the references…"):
        dna = measure_shoot(shoot, list(refs) if refs else None)
    if dna is None:
        console.print("[yellow]No reference videos — put 1–5 videos you like into a style/ folder inside the shoot.")
        raise typer.Exit(1)
    for r in dna.refs:
        console.print(f"  {r.name}: {r.duration:.0f}s {r.aspect} · {r.cuts_per_min:.0f} cuts/min · talking {r.speech_ratio:.0%} · "
                      f"music {r.music_ratio:.0%} · text {r.text_ratio:.0%}")
    console.rule("style")
    for line in dna.summary:
        console.print(f"  · {line}")


@app.command()
def models(
    download: str = typer.Option(None, "--download", help="Download a speech model: tiny|base|small|medium|large-v3-turbo"),
    use: str = typer.Option(None, "--use", help="Use this speech model for analysis"),
) -> None:
    """Speech-recognition models: what's on this computer, download one, choose one."""
    from .config import Settings
    from .speech_models import SIZES_MB, status
    from .speech_models import download as dl

    s = Settings.load()
    if download:
        if download not in SIZES_MB:
            console.print(f"[red]unknown model {download!r}; choose from {', '.join(SIZES_MB)}")
            raise typer.Exit(2)
        last = [0.0]

        def prog(_stage, i, n, msg):
            if i - last[0] >= 25 or i >= n:
                console.print(f"  {msg}")
                last[0] = i

        dl(download, prog)
        s.asr.whisper_model = download
        s.save()
        console.print(f"[green]✓[/] {download} downloaded and selected")
    if use:
        s.asr.whisper_model = use
        s.save()
    for m in status(s.asr.whisper_model):
        mark = "[green]✓ on this computer[/]" if m["cached"] else f"[dim]{m['size_mb']} MB download[/]"
        console.print(f"  {'→' if m['current'] else ' '} {m['name']:15s} {mark}  {m['note']}")


@app.command()
def ui(port: int = typer.Option(8765, help="Local port"), no_browser: bool = typer.Option(False, "--no-browser", help="Don't open a browser")) -> None:
    """Open the review app (runs on this computer only; footage is never uploaded)."""
    from .server import serve

    serve(port=port, open_browser=not no_browser)


def _import_state(module: str) -> tuple[str, str]:
    """(status, detail) for an optional module: installed, missing, or installed but broken (e.g. a DLL that won't
    load on Windows), so a broken install is never reported as simply "not installed"."""
    import importlib
    import importlib.util

    try:
        importlib.import_module(module)
        return "[green]installed", ""
    except Exception as e:
        try:
            missing = importlib.util.find_spec(module) is None
        except Exception:
            missing = False
        if missing:
            return "[yellow]not installed", "pip install prepro[asr]"
        return "[red]won't load", f"installed but importing it fails: {e}"


@app.command()
def doctor() -> None:
    """Check the local toolchain (ffmpeg, recognisers, models, AI connectors)."""
    from .config import Settings, ensure_model
    from .media.ffmpeg import FFmpegError, ffmpeg_bin, ffprobe_bin, filters

    t = Table(title="PrePro doctor", show_lines=False)
    t.add_column("Check")
    t.add_column("Status")
    t.add_column("Detail", overflow="fold")
    try:
        t.add_row("ffmpeg", "[green]ok", ffmpeg_bin())
        t.add_row("ffprobe", "[green]ok", ffprobe_bin())
        need = {"ass", "xfade", "sidechaincompress", "loudnorm", "ebur128", "lut3d", "afftdn"}
        missing = need - set(filters())
        t.add_row("ffmpeg filters", "[green]ok" if not missing else "[yellow]partial", ", ".join(sorted(missing)) or "all required filters present")
    except FFmpegError as e:
        t.add_row("ffmpeg", "[red]missing", str(e))
    from .speech_models import SIZES_MB, cached

    models = [n for n in SIZES_MB if cached(n)]
    for mod, ok_detail in (("faster_whisper", "speech models here: " + (", ".join(models) if models else
                                                                     "none yet (prepro models --download small)")),
                           ("pocketsphinx", "offline English fallback recogniser")):
        state, detail = _import_state(mod)
        t.add_row(mod.replace("_", "-"), state, ok_detail if state == "[green]installed" else detail)
    try:
        import opentimelineio as otio

        names = set(otio.adapters.available_adapter_names())
        need = {"fcp_xml", "kdenlive"}
        t.add_row("OTIO adapters", "[green]ok" if need <= names else "[yellow]partial",
                  ", ".join(sorted(names)) + ("" if need <= names else f" (missing {', '.join(sorted(need - names))}: pip install prepro[export])"))
    except Exception as e:  # pragma: no cover
        t.add_row("OTIO adapters", "[red]error", str(e)[:120])
    face = ensure_model("face_res10", download=False)
    t.add_row("face model", "[green]cached" if face else "[yellow]not cached", "downloads on first analysis" if not face else str(face[1]))
    for exe in ("claude", "codex", "ollama", "espeak-ng", "melt"):
        p = shutil.which(exe)
        t.add_row(exe, "[green]found" if p else "[dim]absent", p or "")
    s = Settings.load()
    t.add_row("privacy level", s.privacy, "local = nothing leaves this PC")
    t.add_row("routing", "", json.dumps(s.routing.model_dump()))
    console.print(t)


@app.command()
def demo(
    kind: str = typer.Argument("travel_vlog", help="travel_vlog|aesthetic_cooking|hype_reel|talking_head|comedy_skit|gaming|hindi_vlog|all"),
    out: Path = typer.Option(Path("demo-shoots"), help="Where to create the shoot folder(s)"),
    brief: bool = typer.Option(False, help="Also write a creator brief (brief.md) into the shoot"),
    sidecars: bool = typer.Option(False, help="Write .transcript.json sidecars (deterministic transcripts)"),
    real: bool = typer.Option(True, help="Mix in downloaded real media (faces) when available"),
) -> None:
    """Generate a synthetic demo shoot (with hidden ground truth) to try PrePro without your own footage."""
    from .fixtures import realmedia, shoots

    kinds = shoots.KINDS if kind == "all" else [kind]
    md = realmedia.cache_dir() if real else None
    for k in kinds:
        with console.status(f"Building demo shoot '{k}'…"):
            root = shoots.build(k, out, media_dir=md, with_brief=brief, sidecars=sidecars)
        console.print(f"[green]✓[/] {k} → {root}")


@app.command()
def analyze(
    shoot: Path = typer.Argument(..., help="Shoot folder"),
    force: bool = typer.Option(False, help="Ignore the analysis cache"),
    asr: str = typer.Option(None, help="auto|faster-whisper|pocketsphinx|sidecar|none"),
    no_faces: bool = typer.Option(False, help="Skip face detection"),
    verbose: bool = typer.Option(False, "-v", help="Show segments and shots"),
) -> None:
    """Analyse a shoot folder locally (nothing leaves this PC)."""
    from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

    from .analyze.pipeline import analyse_project
    from .config import Settings

    s = Settings.load()
    if asr:
        s.asr.backend = asr  # type: ignore[assignment]
    with Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=console) as prog:
        task = prog.add_task("analysing", total=1)

        def cb(stage, i, n, msg):
            prog.update(task, description=f"{stage}: {msg[:60]}", total=max(n, 1), completed=i)

        pa = analyse_project(shoot, settings=s, progress=cb, force=force, faces=not no_faces)
    print_analysis(pa, verbose=verbose)


def print_analysis(pa, verbose: bool = False) -> None:
    t = Table(title=f"{len(pa.assets)} assets · {pa.stats.get('footage_seconds', 0):.0f}s footage · {int(pa.stats.get('days', 0))} day(s) · {int(pa.stats.get('places', 0))} place(s)")
    for c in ("id", "kind", "file", "dur", "facts"):
        t.add_column(c, overflow="fold")
    for a in pa.assets:
        ca = pa.clips.get(a.id)
        facts = []
        if ca:
            if ca.transcript:
                segs = ca.transcript.segments
                bad = sum(1 for x in segs if x.retake_rank > 0 or x.false_start or "greeting" in x.tags or "hesitation" in x.tags)
                facts.append(f"{len(segs)} segs ({bad} to cut) [{ca.transcript.backend}]")
            if ca.music:
                facts.append(f"{ca.music.bpm:.0f} BPM {ca.music.key} {ca.music.mode} {'/'.join(ca.music.mood_tags[:3])} · {'-'.join(x.label for x in ca.music.sections)}")
            fl = sorted({f for s in ca.shots for f in s.flags})
            if ca.shots and a.info.has_video:
                mv = sorted({s.camera_move for s in ca.shots})
                facts.append(f"{','.join(mv)}" + (f" ⚠ {','.join(fl)}" if fl else "") + (" dup" if any(s.dup_group for s in ca.shots) else ""))
            if ca.audio.issues:
                facts.append("audio: " + "; ".join(ca.audio.issues))
            if ca.place:
                facts.append(f"📍{ca.place} d{ca.day_index}")
        t.add_row(a.id, a.kind.value, a.path, f"{a.info.duration:.1f}", " · ".join(facts))
    console.print(t)
    console.print("Genres: " + ", ".join(f"{g.playbook} {g.score:.2f} ({g.why})" for g in pa.genres))
    for w in pa.warnings:
        console.print(f"[yellow]⚠ {w}")
    if verbose:
        for a in pa.assets:
            ca = pa.clips.get(a.id)
            if ca and ca.transcript:
                console.print(f"[bold]{a.id}[/] {a.path}")
                for sg in ca.transcript.segments:
                    flags = ",".join(sg.tags + ([f"retake{sg.retake_rank}"] if sg.retake_rank else []) + (["g:" + sg.retake_group] if sg.retake_group else []))
                    console.print(f"  {sg.id:10s} {sg.t0:6.2f}-{sg.t1:6.2f} {sg.text[:80]!r} [dim]{flags}")


@app.command()
def directions(shoot: Path = typer.Argument(..., help="Shoot folder"), brief: str = typer.Option(None, help="Extra brief text")) -> None:
    """Propose 2–4 creative directions (with hooks and coverage gaps) for a shoot."""
    from .brain.basic import BasicBrain
    from .engine import analysis, brief_for

    pa = analysis(shoot)
    b = brief_for(shoot, pa, extra_text=brief)
    ds = BasicBrain(pa, b).directions()
    for d in ds.directions:
        console.rule(f"[bold]{d.id}[/] {d.name}  [dim](fit {d.fit_score:.2f}{' · from your brief' if d.from_brief else ''})")
        console.print(f"[dim]why:[/] {d.why}")
        for h in d.hooks:
            console.print(f"  hook {h.id} [{h.kind}] {h.score:.2f}  {h.why}" + (f"  → text: “{h.text_hook}”" if h.text_hook else ""))
        for o in d.outline:
            console.print(f"  • {o}")
        for g in d.coverage_gaps:
            console.print(f"  [yellow]gap:[/] {g}")
    if b.rules or b.questions:
        console.rule("brief")
        for r in b.rules:
            console.print(f"  {'✓' if r.resolved else '?'} {r.kind} {r.target or ''} {('@' + r.anchor) if r.anchor else ''} [dim]{r.source.strip()[:70]}")
        for q in b.questions:
            console.print(f"  [yellow]question:[/] {q.text}")
    console.print(f"[dim]{ds.notes}")


@app.command()
def build(
    shoot: Path = typer.Argument(..., help="Shoot folder"),
    direction: str = typer.Option("auto", help="Direction id (d1…) or playbook key"),
    brief: str = typer.Option(None, help="Extra brief text"),
    quality: str = typer.Option("preview", help="preview|final"),
    no_render: bool = typer.Option(False, help="Plan + timeline only"),
) -> None:
    """Build the chosen direction into a first cut (timeline + preview render + storyboard)."""
    from .engine import build as do_build

    with console.status("Building first cut…"):
        res = do_build(shoot, direction=direction, brief_text=brief, render=not no_render, quality=quality, extra_playbook=direction if direction not in ("auto",) and not direction.startswith("d") else None)
    tl = res.timeline
    console.rule(f"[bold]{res.direction.name}[/]")
    console.print(f"duration {tl.duration:.1f}s · {len([i for i in tl.items if i.track == 'V1'])} shots · {len(tl.captions)} captions · "
                  f"{len(tl.suggestions)} suggestions · timeline {res.timeline_path}")
    applied = [s for s in tl.suggestions if s.status == "applied"]
    optional = [s for s in tl.suggestions if s.status == "optional"]
    for s in applied[:40]:
        console.print(f"  [green]✓[/] {('%6.1fs' % s.t) if s.t is not None else '      '} {s.type:10s} {s.reason}")
    for s in optional[:15]:
        console.print(f"  [yellow]?[/] {('%6.1fs' % s.t) if s.t is not None else '      '} {s.type:10s} {s.reason}")
    if res.lint:
        console.rule("EditLint")
        for f in res.lint:
            col = {"error": "red", "warn": "yellow"}.get(f.severity, "dim")
            console.print(f"  [{col}]{f.severity:5s}[/] {f.rule:10s} {f.msg}" + (f" @ {f.t:.1f}s" if f.t is not None else ""))
    if res.critic:
        console.print("Critic: " + ", ".join(f"{k} {v}" for k, v in res.critic.scores.items()) + f"  → {res.critic.summary}")
    if res.render:
        r = res.render
        console.print(f"[bold green]render[/] {r.video}  ({r.duration:.1f}s, {r.lufs} LUFS, TP {r.true_peak_db} dBTP, voice/music {r.speech_to_music_db} dB)")
        if r.storyboard:
            console.print(f"storyboard {r.storyboard}")


@app.command()
def export(
    shoot: Path = typer.Argument(..., help="Shoot folder (after `prepro build`)"),
    timeline: str = typer.Option(None, help="Timeline id (default: most recent)"),
    formats: str = typer.Option("fcp7,otio,kdenlive,mlt,srt,overlay,report", help="Comma list (or 'all'): " + ",".join(("fcp7", "otio", "kdenlive", "mlt", "srt", "overlay", "phone", "report"))),
    out: Path = typer.Option(None, help="Output folder (default: <shoot>/PrePro_exports/<timeline>)"),
) -> None:
    """Export the cut for Premiere/Resolve (FCP7 XML), Kdenlive (OTIO/.kdenlive), Shotcut (MLT), phone apps, SRT + editor brief."""
    from .engine import analysis
    from .export.package import FORMATS, export_all
    from .lint.critic import rules_critic
    from .lint.editlint import lint_timeline
    from .project import EXPORTS_DIR, Project
    from .schema.brief import CreatorBrief
    from .schema.timeline import Timeline

    proj = Project(shoot)
    tdir = proj.cache / "timelines"
    cands = sorted((p for p in tdir.glob("*.json") if p.name.count(".") == 1), key=lambda p: p.stat().st_mtime)
    if timeline:
        cands = [p for p in cands if p.stem == timeline]
    if not cands:
        console.print("[red]no timeline — run `prepro build` first")
        raise typer.Exit(1)
    tl = Timeline.model_validate_json(cands[-1].read_text(encoding="utf-8"))
    pa = analysis(shoot)
    from .repurpose import find_direction

    d = find_direction(shoot, tl.direction_id)
    brief = proj.load_model("brief.json", CreatorBrief)
    findings = lint_timeline(tl, pa, d, brief) if d else []
    critic = rules_critic(tl, pa, d, findings) if d else None
    out = out or (proj.root / EXPORTS_DIR / tl.id)
    with console.status("Exporting…"):
        fmts = list(FORMATS) if formats.strip() == "all" else [f.strip() for f in formats.split(",")]
        bad = [f for f in fmts if f not in FORMATS]
        if bad:
            console.print(f"[red]unknown format(s): {', '.join(bad)} — choose from {', '.join(FORMATS)} or 'all'")
            raise typer.Exit(2)
        made = export_all(tl, pa, out, formats=fmts, project_root=shoot, critic=critic,
                          lint=findings, direction=d, brief=brief)
    for k, v in made.items():
        console.print(f"  [green]✓[/] {k:16s} {v}")
    from .export.nle import EXPORT_WARNINGS

    for w in EXPORT_WARNINGS:
        console.print(f"  [yellow]![/] {w}")


@brains_app.command("list")
def brains_list() -> None:
    """Show connectors (configured + detected), availability, routing and training badges."""
    from .brain.providers import detect_connectors, make_provider
    from .config import Settings

    s = Settings.load()
    conns = {**detect_connectors(), **s.connectors}
    t = Table(title=f"Brains · privacy level: {s.privacy}")
    for c in ("name", "kind", "model", "ready", "training / data use"):
        t.add_column(c, overflow="fold")
    t.add_row("basic", "rules", "-", "[green]yes", "Nothing is sent — rules only, on this PC.")
    for name, cfg in conns.items():
        p = make_provider(name, cfg, privacy=s.privacy)
        ok, why = p.available()
        t.add_row(name, cfg.kind, cfg.model or "default", ("[green]yes" if ok else "[yellow]no") + f" [dim]{why}", p.training_badge())
    console.print(t)
    console.print("Routing: " + ", ".join(f"{k}→{v}" for k, v in s.routing.model_dump().items()))


@brains_app.command("add")
def brains_add(name: str, kind: str = typer.Option(..., help="claude_code|codex|anthropic|openai|xai|openrouter|gemini|ollama"),
               model: str = typer.Option(None), tier: str = typer.Option(None, help="gemini: free|paid"),
               max_usd: float = typer.Option(2.0, help="per-project cap")) -> None:
    from .config import ConnectorConfig, Settings

    s = Settings.load()
    s.connectors[name] = ConnectorConfig(kind=kind, model=model, max_usd_per_project=max_usd, extra={"tier": tier} if tier else {})
    s.save()
    console.print(f"added {name} ({kind})")


@brains_app.command("key")
def brains_key(provider: str = typer.Argument(..., help="anthropic|openai|xai|openrouter|gemini"), value: str = typer.Option(..., prompt=True, hide_input=True)) -> None:
    """Store an API key in the OS keychain."""
    from .config import set_secret

    set_secret(f"{provider}_api_key", value)
    console.print(f"stored {provider} key in the keychain")


@brains_app.command("route")
def brains_route(pass_name: str = typer.Argument(..., help="vision|director|story|polish|critic|brief|revise|all"), connector: str = typer.Argument(...)) -> None:
    from .config import Settings

    s = Settings.load()
    keys = list(s.routing.model_dump()) if pass_name == "all" else [pass_name]
    for k in keys:
        setattr(s.routing, k, connector)
    s.save()
    console.print("Routing: " + ", ".join(f"{k}→{v}" for k, v in s.routing.model_dump().items()))


@brains_app.command("privacy")
def brains_privacy(level: str = typer.Argument(..., help="local|text|thumbs")) -> None:
    from .config import Settings

    s = Settings.load()
    s.privacy = level  # type: ignore[assignment]
    s.save()
    console.print(f"privacy level → {level}")


@brains_app.command("compare")
def brains_compare(shoot: Path, connectors: list[str] = typer.Option(None, "--connector", "-c")) -> None:
    """Build the same shoot with each brain and compare scorecards (the 'which brain is best?' report)."""
    from .brain.providers import detect_connectors
    from .config import Settings
    from .engine import build as do_build

    s = Settings.load()
    names = connectors or ["basic"] + list({**detect_connectors(), **s.connectors})
    t = Table(title="Which brain is best?")
    for c in ("brain", "direction", "dur", "hook", "clarity", "pacing", "restraint", "genre_fit", "lint errors", "cost"):
        t.add_column(c)
    for n in names:
        try:
            res = do_build(shoot, render=False, routing={k: n for k in s.routing.model_dump()} if n != "basic" else {k: "basic" for k in s.routing.model_dump()})
        except Exception as e:  # keep comparing
            t.add_row(n, f"[red]failed: {str(e)[:60]}", *[""] * 8)
            continue
        sc = res.critic.scores if res.critic else {}
        t.add_row(n, res.direction.playbook, f"{res.timeline.duration:.0f}s", *[str(sc.get(k, "-")) for k in ("hook", "clarity", "pacing", "restraint", "genre_fit")],
                  str(sum(1 for f in res.lint if f.severity == "error")), f"${res.cost_usd:.3f}" + (" + plan" if any(c["usage"].get("plan_usage") for c in res.ai_calls) else ""))
    console.print(t)


@testmedia_app.command("fetch")
def testmedia_fetch(category: list[str] = typer.Option(None, help="Only these categories")) -> None:
    from .fixtures import realmedia

    got = realmedia.fetch(set(category) if category else None)
    console.print(f"{len(got)}/{len(realmedia.MANIFEST)} files in {realmedia.cache_dir()}")


@testmedia_app.command("list")
def testmedia_list() -> None:
    from .fixtures import realmedia

    have = realmedia.available()
    for it in realmedia.MANIFEST:
        mark = "[green]✓" if it.name in have else "[dim]·"
        console.print(f"{mark} {it.category:9s} {it.name:48s} {it.licence}")


def main() -> None:  # pragma: no cover
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
