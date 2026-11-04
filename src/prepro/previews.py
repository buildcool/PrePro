"""Path previews: a few seconds of each direction's opening, so the creator can *see* the options before choosing.

Built with the rules engine (free, offline, a second or two per direction) and rendered small (360p). The full
build — with the AI brain if one is connected — happens only for the path the creator picks."""

from __future__ import annotations

from pathlib import Path

from .project import Project
from .schema.timeline import Timeline


def trim(tl: Timeline, seconds: float) -> Timeline:
    """The first `seconds` of a timeline: items cut at the end, captions/markers/music spans clipped."""
    out = tl.model_copy(deep=True)
    items = []
    for it in out.items:
        if it.rec_in >= seconds - 1e-3:
            continue
        over = it.rec_out - seconds
        if over > 1e-3:
            if it.kind in ("text", "image", "color"):
                it.duration = round(seconds - it.rec_in, 3)
            else:
                it.src_out = round(it.src_out - over * max(it.speed, 1e-6), 3)
            it.envelope = [e for e in it.envelope if e[0] <= seconds]
            it.fade_out = min(it.fade_out, 0.3)
        items.append(it)
    out.items = items
    out.captions = [c for c in out.captions if c.t0 < seconds - 0.2]
    for c in out.captions:
        c.t1 = min(c.t1, seconds)
    out.markers = [m for m in out.markers if m.t < seconds]
    out.music_spans = [s.model_copy(update={"t1": min(s.t1, seconds)}) for s in out.music_spans if s.t0 < seconds]
    return out


def make(root: str | Path, *, seconds: float = 6.0, height: int = 360, progress=None) -> dict[str, str]:
    """Render a short opening preview for every direction card. Returns {direction id: path relative to root}."""
    from .brain.basic import BasicBrain
    from .engine import analysis, brief_for
    from .export.render import render
    from .schema.plan import DirectionSet
    from .timeline.compiler import compile_timeline

    root = Path(root)
    proj = Project(root)
    pa = analysis(root)
    brief = brief_for(root, pa)
    bb = BasicBrain(pa, brief)
    ds = proj.load_model("directions.json", DirectionSet) or bb.directions()
    out: dict[str, str] = {}
    for k, d in enumerate(ds.directions):
        if progress:
            progress("previews", k, len(ds.directions), d.name)
        story = bb.story(d)
        tl = compile_timeline(pa, d, story, bb.polish(d, story), brief, project_root=root)
        short = trim(tl, min(seconds, tl.duration))
        dst = proj.sub("previews") / f"{d.id}.mp4"
        render(short, pa, dst, quality="preview", preview_height=height, project_root=root, storyboard=False)
        out[d.id] = str(dst.relative_to(root))
    return out
