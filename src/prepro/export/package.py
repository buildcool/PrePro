"""Export bundles: NLE project files, the phone-app pack and the HTML editor brief."""

from __future__ import annotations

import base64
import html
import json
import shutil
from pathlib import Path

from ..project import Project
from ..schema.analysis import ProjectAnalysis
from ..schema.timeline import Timeline
from . import nle

FORMATS = ("fcp7", "otio", "kdenlive", "mlt", "srt", "overlay", "phone", "report")


def export_all(tl: Timeline, pa: ProjectAnalysis, out_dir: Path, *, formats=FORMATS, project_root=None, render_result=None,
               critic=None, lint=None, direction=None, brief=None) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    root = project_root or pa.root
    made: dict[str, Path] = {}
    base = _safe(tl.name)[:60] or tl.id
    if "srt" in formats and tl.captions:
        made["srt"] = nle.write_srt(tl, out_dir / f"{base}.srt")
        made["vtt"] = nle.write_vtt(tl, out_dir / f"{base}.vtt")
    overlay = None
    if "overlay" in formats:
        overlay = nle.write_caption_overlay(tl, out_dir / f"{base}_captions_overlay.mov")
        if overlay:
            made["overlay"] = overlay
    if "fcp7" in formats:
        made["fcp7"] = nle.write_fcp7(tl, pa, out_dir / f"{base}_Premiere_Resolve.xml", project_root=root, overlay=overlay)
    if "otio" in formats or "kdenlive" in formats:
        made["otio"] = nle.write_otio(tl, pa, out_dir / f"{base}.otio", project_root=root)
        if "kdenlive" in formats:
            k = nle.write_kdenlive(made["otio"], out_dir / f"{base}.kdenlive", width=tl.width, height=tl.height, fps=tl.fps)
            if k:
                made["kdenlive"] = k
    if "mlt" in formats:
        made["mlt"] = nle.write_mlt(tl, pa, out_dir / f"{base}_Shotcut.mlt", project_root=root)
    lut = nle.copy_luts(tl, out_dir)
    if lut:
        made["lut"] = lut
    if "phone" in formats:
        made.update(phone_pack(tl, pa, out_dir / "phone_pack", project_root=root))
    if "report" in formats:
        made["report"] = editor_brief(tl, pa, out_dir / f"{base}_editor_brief.html", render_result=render_result, critic=critic, lint=lint,
                                      direction=direction, brief=brief, files=made)
    return made


def _safe(s: str) -> str:
    import re

    return re.sub(r"[^\w\- ]+", "", s).strip().replace(" ", "_")


def phone_pack(tl: Timeline, pa: ProjectAnalysis, out: Path, *, project_root=None) -> dict[str, Path]:
    """For InShot / VN / KineMaster / Instagram Edits — apps that can't import timelines."""
    from .render import render

    out.mkdir(parents=True, exist_ok=True)
    made: dict[str, Path] = {}
    cap = render(tl, pa, out / "1_captioned.mp4", quality="final", project_root=project_root, stems=True, storyboard=False)
    made["phone_captioned"] = cap.video
    clean = render(tl, pa, out / "2_clean_no_text.mp4", quality="final", project_root=project_root, captions=False, storyboard=False)
    made["phone_clean"] = clean.video
    if any(i.track == "A2" for i in tl.items):
        nm = render(tl, pa, out / "3_no_music_for_trending_audio.mp4", quality="final", project_root=project_root, captions=False,
                    music=False, storyboard=False)
        made["phone_no_music"] = nm.video
    stems = out / "1_captioned_stems"
    if stems.exists():
        made["stems"] = stems
    for p in out.glob("*.wav"):
        p.unlink()
    for pat in ("*.ass", "*.base.txt", "*.base.mp4"):
        for p in out.glob(pat):
            p.unlink()
    if tl.captions:
        made["phone_srt"] = nle.write_srt(tl, out / "captions.srt")
    made["cue_sheet"] = _cue_sheet(tl, pa, out / "cue_sheet.txt")
    made["beat_plan"] = _beat_plan(tl, pa, out / "beat_plan.txt")
    return made


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def _cue_sheet(tl: Timeline, pa: ProjectAnalysis, path: Path) -> Path:
    lines = [f"PrePro cue sheet — {tl.name}", f"Duration {_mmss(tl.duration)} · {tl.width}x{tl.height} · {tl.fps:g} fps", ""]
    lines.append("FILES")
    lines += ["  1_captioned.mp4 — ready to post (captions + text burned in)",
              "  2_clean_no_text.mp4 — add your own text/captions in the app",
              "  3_no_music_for_trending_audio.mp4 — add trending audio in Instagram / your app (see beat_plan.txt)",
              "  1_captioned_stems/ — dialogue.wav, music.wav, sfx.wav if you want to rebalance", ""]
    texts = [i for i in tl.items if i.kind == "text"]
    if texts:
        lines.append("TEXT TO ADD (if you use the clean version)")
        lines += [f"  {_mmss(t.rec_in)}–{_mmss(t.rec_out)}  [{t.style}] {t.text}" for t in texts]
        lines.append("")
    opt = [s for s in tl.suggestions if s.status == "optional"]
    if opt:
        lines.append("IDEAS THAT NEED YOUR CALL (not applied)")
        for s in opt:
            lines.append(f"  {_mmss(s.t) if s.t is not None else '   -   '}  {s.type}: {s.reason}")
            if s.payload.get("search"):
                lines.append(f"            search: {', '.join(s.payload['search'][:3])}")
        lines.append("")
    gaps = tl.meta.get("broll_gaps") or []
    if gaps:
        lines.append("B-ROLL YOU COULD ADD")
        lines += [f"  {g['want']}" + (f"\n            search: {', '.join(g['search_terms'])}" if g.get("search_terms") else "") for g in gaps]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _beat_plan(tl: Timeline, pa: ProjectAnalysis, path: Path) -> Path:
    cuts = sorted({round(i.rec_in, 2) for i in tl.items if i.track == "V1"})
    music = [i for i in tl.items if i.track == "A2"]
    bpm = None
    if music:
        m = pa.clips[music[0].asset_id].music
        bpm = m.bpm if m else None
    lines = [f"Beat plan — {tl.name}", ""]
    if bpm:
        lines.append(f"The cut is timed for ~{bpm:.0f} BPM. When you pick a trending sound in the app, choose one around {bpm - 8:.0f}–{bpm + 8:.0f} BPM "
                     "and line its first strong beat up with the first cut below.")
    else:
        lines.append("No music was used — any trending sound works; keep it low under the talking.")
    lines += ["", "Cut points (mm:ss.hh):"] + [f"  {_mmss(t)}" for t in cuts]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def editor_brief(tl: Timeline, pa: ProjectAnalysis, path: Path, *, render_result=None, critic=None, lint=None, direction=None, brief=None,
                 files: dict | None = None) -> Path:
    """Self-contained HTML hand-off for a human editor: story, every decision with its reason, what is missing."""
    from ..brain.ai import paper_edit

    e = html.escape
    sb = ""
    sbp = getattr(render_result, "storyboard", None) if render_result else None
    if sbp is None:
        cand = sorted((Project(pa.root).cache / "qa").glob(f"{tl.id}_*storyboard.jpg"))
        sbp = cand[-1] if cand else None
    if sbp and Path(sbp).exists():
        sb = f'<img alt="storyboard" style="max-width:100%;border-radius:8px" src="data:image/jpeg;base64,{base64.b64encode(Path(sbp).read_bytes()).decode()}">'
    def when(s):
        return (s.t is None, s.t if s.t is not None else 0.0)

    applied = sorted((s for s in tl.suggestions if s.status == "applied"), key=when)
    optional = sorted((s for s in tl.suggestions if s.status == "optional"), key=when)

    def rows(sugs):
        if not sugs:
            return '<tr><td colspan=5 class=mute>nothing here</td></tr>'
        return "".join(f"<tr><td>{_mmss(s.t) if s.t is not None else ''}</td><td>{e(s.type)}</td><td>{e(s.reason)}</td>"
                       f"<td>{s.confidence:.2f}</td><td>{e(s.source)}</td></tr>" for s in sugs)

    scores = ""
    if critic is not None:
        scores = "".join(f"<span class=chip>{e(k)} {v:g}</span>" for k, v in critic.scores.items()) + f"<p>{e(critic.summary)}</p>"
        if critic.issues:
            scores += "<ul>" + "".join(f"<li>{e(i)}</li>" for i in critic.issues[:10]) + "</ul>"
    lint_html = "".join(f"<li><b>{e(f.severity)}</b> {e(f.rule)} — {e(f.msg)}</li>" for f in (lint or []))
    music = "".join(f"<li>{e(m['section'])}: <b>{e(m['mode'])}</b> {e(m.get('track_id') or 'no track')} — {e(m.get('why', ''))}"
                    + (f" · search: {e(', '.join(m['brief']['search_terms'][:2]))}" if not m.get('track_id') and m.get('brief') and m['mode'] != "none" else "") + "</li>"
                    for m in tl.meta.get("music", []))
    gaps = "".join(f"<li>{e(g)}</li>" for g in (direction.coverage_gaps if direction else []))
    bgaps = "".join(f"<li>{e(g['want'])}" + (f" <i>— search: {e(', '.join(g['search_terms']))}</i>" if g.get("search_terms") else "") + "</li>"
                    for g in tl.meta.get("broll_gaps", []))
    vo = "".join(f"<li>{e(x)}</li>" for x in tl.meta.get("vo_script", []))
    brief_html = ""
    if brief is not None and (brief.rules or brief.raw_text):
        from ..lint.editlint import compliance

        items = compliance(tl, pa, direction, brief) if direction else []
        brief_html = "<ul>" + "".join(f"<li>{'✅' if c.ok else '❌'} {e(c.rule.source.strip() or c.rule.kind)} {e(c.detail)}</li>" for c in items) + "</ul>"
    filelist = "".join(f"<li>{e(k)}: <code>{e(str(v.name))}</code></li>" for k, v in (files or {}).items())
    metrics = ""
    if render_result is not None:
        metrics = (f"<span class=chip>{render_result.duration:.1f}s</span><span class=chip>{render_result.lufs} LUFS</span>"
                   f"<span class=chip>TP {render_result.true_peak_db} dBTP</span><span class=chip>voice/music {render_result.speech_to_music_db} dB</span>")
    pe = e(paper_edit(tl, pa))
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Editor brief — {e(tl.name)}</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--mute:#666;--card:#f5f5f2;--line:#ddd;--acc:#c2410c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--mute:#999;--card:#1c1c1c;--line:#333;--acc:#fb923c}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:16px}}
h1{{font-size:24px;margin:.2em 0}} h2{{font-size:18px;margin-top:1.6em;border-bottom:1px solid var(--line);padding-bottom:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td,th{{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}}
.chip{{display:inline-block;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:2px 10px;margin:2px;font-size:13px}}
pre{{background:var(--card);padding:10px;border-radius:8px;overflow:auto;font-size:12px}} .mute{{color:var(--mute)}}
</style></head><body>
<h1>{e(tl.name)}</h1>
<p class=mute>{e(tl.playbook)} · {tl.width}×{tl.height} · {tl.fps:g} fps · {_mmss(tl.duration)} · look: {e(tl.look or 'natural')}</p>
<p>{metrics}</p>
<p>{e(tl.meta.get('story_why') or '')}</p>
{sb}
<h2>Quality scorecard</h2>{scores or '<p class=mute>not scored</p>'}
<h2>Creator brief checklist</h2>{brief_html or '<p class=mute>no brief — Auto mode</p>'}
<h2>Every decision (applied)</h2><table><tr><th>time</th><th>type</th><th>reason</th><th>conf</th><th>by</th></tr>{rows(applied)}</table>
<h2>Ideas that need your call (not applied)</h2><table><tr><th>time</th><th>type</th><th>reason</th><th>conf</th><th>by</th></tr>{rows(optional)}</table>
<h2>Music</h2><ul>{music}</ul>
<h2>Missing material</h2><ul>{(gaps + bgaps) or '<li class=mute>nothing — the footage covers the story</li>'}</ul>{('<h3>Suggested voice-over</h3><ul>' + vo + '</ul>') if vo else ''}
<h2>EditLint</h2><ul>{lint_html or '<li>clean</li>'}</ul>
<h2>Paper edit</h2><pre>{pe}</pre>
<h2>Files</h2><ul>{filelist}</ul>
<p class=mute>Made with PrePro. Footage never left this computer.</p>
</body></html>"""
    path.write_text(doc, encoding="utf-8")
    return path


def zip_export(out_dir: Path) -> Path:
    return Path(shutil.make_archive(str(out_dir), "zip", out_dir))


def manifest(made: dict[str, Path], path: Path) -> Path:
    path.write_text(json.dumps({k: str(v) for k, v in made.items()}, indent=1), encoding="utf-8")
    return path
