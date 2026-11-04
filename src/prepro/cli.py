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
console = Console()


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"prepro {__version__}")


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
    try:
        import faster_whisper  # noqa: F401

        t.add_row("faster-whisper", "[green]installed", "models download on first use (huggingface.co)")
    except ImportError:
        t.add_row("faster-whisper", "[yellow]not installed", "pip install prepro[asr]")
    try:
        import pocketsphinx  # noqa: F401

        t.add_row("pocketsphinx", "[green]installed", "offline English fallback recogniser")
    except ImportError:
        t.add_row("pocketsphinx", "[yellow]not installed", "")
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
