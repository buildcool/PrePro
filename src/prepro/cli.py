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
