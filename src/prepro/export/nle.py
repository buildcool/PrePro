"""Editable timelines for NLEs.

* FCP7 XML (xmeml v5)  → Premiere Pro and DaVinci Resolve (Resolve recommends FCP7 XML v5 for interchange)
* OpenTimelineIO       → Kdenlive (native OTIO import), Resolve 18+, and anything with an OTIO adapter
* MLT XML              → Shotcut / melt

Everything an NLE can't represent (captions styling, meme ideas, music search terms, coverage gaps…)
travels as **markers with the reason** plus SRT and a transparent caption-overlay clip.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

from ..project import Project
from ..schema.analysis import ProjectAnalysis
from ..schema.media import AssetKind
from ..schema.timeline import Item, Timeline


def _f(t: float, fps: float) -> int:
    return int(round(t * fps))


def _sub(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def _rate(parent, fps: float):
    r = _sub(parent, "rate")
    _sub(r, "timebase", int(round(fps)))
    _sub(r, "ntsc", "TRUE" if abs(fps - round(fps)) > 0.01 else "FALSE")


def builtin_sfx_files(tl: Timeline, out_dir: Path) -> dict[str, Path]:
    """Materialise built-in SFX (whoosh/pop/riser/impact/boom/bleep) as WAVs next to the export."""
    import soundfile as sf

    from .render import SR, _builtin

    files = {}
    for it in tl.items:
        if it.note.startswith("builtin:"):
            name = it.note.split(":", 1)[1]
            if name in files:
                continue
            p = out_dir / "sfx" / f"prepro_{name}.wav"
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                sf.write(str(p), _builtin(name, it.src_out - it.src_in), SR)
            files[name] = p
    return files


def _media_path(pa: ProjectAnalysis, proj: Project, it: Item, sfx: dict[str, Path]) -> Path | None:
    if it.note.startswith("builtin:"):
        return sfx.get(it.note.split(":", 1)[1])
    if not it.asset_id:
        return None
    return proj.path(pa.asset(it.asset_id).path)


def _trim_transitions(items: list[Item]) -> list[tuple[Item, float, float, float, float, str | None, float]]:
    """NLE tracks can't overlap: split each transition overlap at its midpoint.
    Returns (item, rec_in, rec_out, src_in, src_out, transition_in, transition_len)."""
    out = []
    seq = sorted(items, key=lambda i: i.rec_in)
    for k, it in enumerate(seq):
        rin, rout, sin, sout = it.rec_in, it.rec_out, it.src_in, it.src_out
        tin, tlen = None, 0.0
        if it.transition_in != "cut" and it.transition_dur > 0 and k > 0:
            half = it.transition_dur / 2
            rin += half
            sin += half * it.speed
            tin, tlen = it.transition_in, it.transition_dur
        if k + 1 < len(seq):
            nxt = seq[k + 1]
            if nxt.transition_in != "cut" and nxt.transition_dur > 0:
                half = nxt.transition_dur / 2
                rout -= half
                sout -= half * it.speed
        out.append((it, rin, rout, sin, sout, tin, tlen))
    return out


# ------------------------------------------------------------------ FCP7 XML
def write_fcp7(tl: Timeline, pa: ProjectAnalysis, path: Path, *, project_root=None, overlay: Path | None = None) -> Path:
    proj = Project(project_root or pa.root)
    fps = tl.fps
    sfx = builtin_sfx_files(tl, path.parent)
    root = ET.Element("xmeml", version="5")
    project = _sub(root, "project")
    _sub(project, "name", f"PrePro — {tl.name}")
    children = _sub(project, "children")
    # ---- bins: organised like an assistant editor would
    bins: dict[str, list] = {}
    used = {i.asset_id for i in tl.items if i.asset_id}
    for a in pa.assets:
        ca = pa.clips.get(a.id)
        if a.kind == AssetKind.AROLL:
            name = "A-roll (talking)"
        elif a.kind in (AssetKind.BROLL, AssetKind.SCREEN):
            label = " · ".join(x for x in (f"Day {ca.day_index}" if ca and ca.day_index else "", (ca.place or "") if ca else "") if x)
            name = f"B-roll{(' · ' + label) if label else ''}"
        elif a.kind == AssetKind.MUSIC:
            name = "Music"
        elif a.kind == AssetKind.SFX:
            name = "SFX"
        elif a.kind in (AssetKind.MEME_IMAGE, AssetKind.MEME_VIDEO):
            name = "Memes"
        else:
            name = "Other"
        if a.kind in (AssetKind.BROLL, AssetKind.AROLL) and a.id not in used and ca and any(set(s.flags) & {"dark", "blurry", "shaky", "pocket"} or s.dup_rank for s in ca.shots):
            name = "Rejects (bad or duplicate)"
        bins.setdefault(name, []).append(a)
    file_ids: dict[str, str] = {}

    def file_el(parent, a, p: Path):
        fid = file_ids.get(str(p))
        if fid:
            return _sub(parent, "file", id=fid)
        fid = f"file-{len(file_ids) + 1}"
        file_ids[str(p)] = fid
        fe = _sub(parent, "file", id=fid)
        _sub(fe, "name", p.name)
        _sub(fe, "pathurl", p.resolve().as_uri())
        _rate(fe, a.info.fps if a and a.info.fps else fps)
        _sub(fe, "duration", _f(a.info.duration if a else 1.0, a.info.fps if a and a.info.fps else fps))
        media = _sub(fe, "media")
        if a is None or a.info.has_video or a.info.is_image:
            v = _sub(media, "video")
            sc = _sub(v, "samplecharacteristics")
            if a and a.info.display_size:
                _sub(sc, "width", a.info.display_size[0])
                _sub(sc, "height", a.info.display_size[1])
        if a is None or a.info.has_audio:
            au = _sub(media, "audio")
            _sub(au, "channelcount", a.info.channels if a and a.info.channels else 2)
        return fe

    for bname, assets in sorted(bins.items()):
        b = _sub(children, "bin")
        _sub(b, "name", bname)
        bc = _sub(b, "children")
        for a in assets:
            c = _sub(bc, "clip", id=f"masterclip-{a.id}")
            _sub(c, "name", a.name)
            _sub(c, "duration", _f(a.info.duration, a.info.fps or fps))
            _rate(c, a.info.fps or fps)
            if a.notes:
                _sub(c, "comments").append(ET.Element("mastercomment1"))
                c.find("comments/mastercomment1").text = "; ".join(a.notes)[:200]
    # ---- sequence
    seq = _sub(children, "sequence", id="sequence-1")
    _sub(seq, "name", tl.name)
    _sub(seq, "duration", _f(tl.duration, fps))
    _rate(seq, fps)
    tc = _sub(seq, "timecode")
    _rate(tc, fps)
    _sub(tc, "string", "00:00:00:00")
    _sub(tc, "frame", 0)
    _sub(tc, "displayformat", "NDF")
    media = _sub(seq, "media")
    video = _sub(media, "video")
    fmt = _sub(video, "format")
    sc = _sub(fmt, "samplecharacteristics")
    _rate(sc, fps)
    _sub(sc, "width", tl.width)
    _sub(sc, "height", tl.height)
    _sub(sc, "pixelaspectratio", "square")
    n_clip = 0
    for track in ("V1", "V2", "V3"):
        items = [i for i in tl.items if i.track == track and i.kind in ("video", "image")]
        if not items:
            continue
        tr = _sub(video, "track")
        for it, rin, rout, sin, sout, tin, tlen in _trim_transitions(items):
            if tin:
                ti = _sub(tr, "transitionitem")
                _sub(ti, "start", _f(rin - tlen / 2, fps))
                _sub(ti, "end", _f(rin + tlen / 2, fps))
                _sub(ti, "alignment", "center")
                _rate(ti, fps)
                ef = _sub(ti, "effect")
                _sub(ef, "name", "Cross Dissolve")
                _sub(ef, "effectid", "Cross Dissolve")
                _sub(ef, "effectcategory", "Dissolve")
                _sub(ef, "effecttype", "transition")
                _sub(ef, "mediatype", "video")
            n_clip += 1
            a = pa.asset(it.asset_id)
            ci = _sub(tr, "clipitem", id=f"clipitem-{n_clip}")
            _sub(ci, "name", a.name)
            _sub(ci, "enabled", "TRUE")
            _sub(ci, "duration", _f(a.info.duration if not a.info.is_image else rout - rin, fps))
            _rate(ci, fps)
            _sub(ci, "start", _f(rin, fps))
            _sub(ci, "end", _f(rout, fps))
            _sub(ci, "in", _f(sin if it.kind == "video" else 0.0, fps))
            _sub(ci, "out", _f(sout if it.kind == "video" else rout - rin, fps))
            file_el(ci, a, proj.path(a.path))
            _motion(ci, it, a, tl)
            if abs(it.speed - 1) > 1e-3:
                _speed(ci, it.speed)
            if it.role:
                _sub(ci, "comments").append(ET.Element("mastercomment1"))
                ci.find("comments/mastercomment1").text = f"PrePro: {it.role}" + (f" · {it.note}" if it.note else "")
    if overlay is not None and overlay.exists():
        tr = _sub(video, "track")
        n_clip += 1
        ci = _sub(tr, "clipitem", id=f"clipitem-{n_clip}")
        _sub(ci, "name", "PrePro captions overlay")
        _sub(ci, "enabled", "TRUE")
        _sub(ci, "duration", _f(tl.duration, fps))
        _rate(ci, fps)
        for tag, v in (("start", 0), ("end", _f(tl.duration, fps)), ("in", 0), ("out", _f(tl.duration, fps))):
            _sub(ci, tag, v)
        file_el(ci, None, overlay)
    audio = _sub(media, "audio")
    for track in ("A1", "A2", "A3", "A4"):
        items = [i for i in tl.items if i.track == track and i.kind == "audio"]
        if not items:
            continue
        # audio items may overlap on our track (e.g. two SFX); spread them over sub-tracks
        lanes: list[list[Item]] = []
        for it in sorted(items, key=lambda i: i.rec_in):
            for lane in lanes:
                if lane[-1].rec_out <= it.rec_in + 1e-3:
                    lane.append(it)
                    break
            else:
                lanes.append([it])
        for lane in lanes:
            tr = _sub(audio, "track")
            for it, rin, rout, sin, sout, _tin, _tl in _trim_transitions(lane):
                p = _media_path(pa, proj, it, sfx)
                if p is None:
                    continue
                a = pa.asset(it.asset_id) if it.asset_id else None
                n_clip += 1
                ci = _sub(tr, "clipitem", id=f"clipitem-{n_clip}")
                _sub(ci, "name", p.name)
                _sub(ci, "enabled", "TRUE")
                _sub(ci, "duration", _f(a.info.duration if a else (it.src_out - it.src_in), fps))
                _rate(ci, fps)
                _sub(ci, "start", _f(rin, fps))
                _sub(ci, "end", _f(rout, fps))
                _sub(ci, "in", _f(sin, fps))
                _sub(ci, "out", _f(sout, fps))
                file_el(ci, a, p)
                st = _sub(ci, "sourcetrack")
                _sub(st, "mediatype", "audio")
                _sub(st, "trackindex", 1)
                _levels(ci, it, fps, rin)
                if abs(it.speed - 1) > 1e-3:
                    _speed(ci, it.speed)
    # ---- markers: every suggestion with its reason
    for m in sorted(tl.markers, key=lambda m: m.t):
        mk = _sub(seq, "marker")
        _sub(mk, "name", m.name)
        _sub(mk, "comment", m.note)
        _sub(mk, "in", _f(m.t, fps))
        _sub(mk, "out", -1)
    for c in tl.captions[:0]:
        pass
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    with path.open("wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        tree.write(fh, encoding="utf-8")
    return path


def _param(effect, pid, name, value, vmin=None, vmax=None):
    p = _sub(effect, "parameter")
    _sub(p, "parameterid", pid)
    _sub(p, "name", name)
    if vmin is not None:
        _sub(p, "valuemin", vmin)
        _sub(p, "valuemax", vmax)
    if isinstance(value, dict):
        v = _sub(p, "value")
        for k, x in value.items():
            _sub(v, k, f"{x:.5f}")
    else:
        _sub(p, "value", value)
    return p


def _motion(ci, it: Item, a, tl: Timeline) -> None:
    """Basic Motion: scale (%) + centre (fraction of the frame, 0 = centred) for punch-ins and reframing."""
    ds = a.info.display_size or (tl.width, tl.height)
    fill = max(tl.width / ds[0], tl.height / ds[1])          # scale so the source fills the sequence frame
    tf = it.transform
    z = tf.zoom if tf else 1.0
    cx = tf.cx if tf else 0.5
    cy = tf.cy if tf else 0.5
    scale = 100.0 * fill * z
    if abs(scale - 100) < 0.5 and abs(cx - 0.5) < 1e-3 and abs(cy - 0.5) < 1e-3:
        return
    scaled_w, scaled_h = ds[0] * fill * z, ds[1] * fill * z
    horiz = (0.5 - cx) * scaled_w / tl.width
    vert = (0.5 - cy) * scaled_h / tl.height
    flt = _sub(ci, "filter")
    ef = _sub(flt, "effect")
    _sub(ef, "name", "Basic Motion")
    _sub(ef, "effectid", "basic")
    _sub(ef, "effectcategory", "motion")
    _sub(ef, "effecttype", "motion")
    _sub(ef, "mediatype", "video")
    _param(ef, "scale", "Scale", f"{scale:.2f}", 0, 1000)
    _param(ef, "center", "Center", {"horiz": horiz, "vert": vert})


def _speed(ci, speed: float) -> None:
    flt = _sub(ci, "filter")
    ef = _sub(flt, "effect")
    _sub(ef, "name", "Time Remap")
    _sub(ef, "effectid", "timeremap")
    _sub(ef, "effectcategory", "motion")
    _sub(ef, "effecttype", "motion")
    _sub(ef, "mediatype", "video")
    _param(ef, "variablespeed", "variablespeed", 0, 0, 1)
    _param(ef, "speed", "speed", f"{speed * 100:.2f}", -100000, 100000)
    _param(ef, "reverse", "reverse", "FALSE")


def _levels(ci, it: Item, fps: float, rin: float) -> None:
    gain = 10 ** (it.gain_db / 20)
    if not it.envelope and abs(it.gain_db) < 0.05:
        return
    flt = _sub(ci, "filter")
    ef = _sub(flt, "effect")
    _sub(ef, "name", "Audio Levels")
    _sub(ef, "effectid", "audiolevels")
    _sub(ef, "effectcategory", "audiolevels")
    _sub(ef, "effecttype", "audiolevels")
    _sub(ef, "mediatype", "audio")
    p = _param(ef, "level", "Level", f"{gain:.5f}", 0.00001, 31.6228)
    for t, db in it.envelope:
        kf = _sub(p, "keyframe")
        _sub(kf, "when", _f(t - rin, fps) + _f(it.src_in, fps))
        _sub(kf, "value", f"{gain * 10 ** (db / 20):.5f}")


# ------------------------------------------------------------------ OTIO
def write_otio(tl: Timeline, pa: ProjectAnalysis, path: Path, *, project_root=None) -> Path:
    import opentimelineio as otio

    proj = Project(project_root or pa.root)
    fps = tl.fps
    sfx = builtin_sfx_files(tl, path.parent)
    RT = otio.opentime.RationalTime
    TR = otio.opentime.TimeRange
    timeline = otio.schema.Timeline(name=tl.name)
    timeline.metadata["prepro"] = {"direction": tl.direction_id, "playbook": tl.playbook, "width": tl.width, "height": tl.height}
    for track_name in ("V1", "V2", "V3", "A1", "A2", "A3", "A4"):
        kind = otio.schema.TrackKind.Video if track_name.startswith("V") else otio.schema.TrackKind.Audio
        items = [i for i in tl.items if i.track == track_name and i.kind in (("video", "image") if track_name.startswith("V") else ("audio",))]
        if not items:
            continue
        lanes: list[list[Item]] = []
        for it in sorted(items, key=lambda i: i.rec_in):
            for lane in lanes:
                last = lane[-1]
                if last.rec_out <= it.rec_in + 1e-3 or (it.transition_in != "cut" and track_name == "V1"):
                    lane.append(it)
                    break
            else:
                lanes.append([it])
        for li, lane in enumerate(lanes):
            track = otio.schema.Track(name=f"{track_name}{'.' + str(li) if li else ''}", kind=kind)
            cursor = 0
            for it, rin, rout, sin, sout, tin, tlen in _trim_transitions(lane):
                start_f, end_f = _f(rin, fps), _f(rout, fps)
                if start_f > cursor:
                    track.append(otio.schema.Gap(source_range=TR(RT(0, fps), RT(start_f - cursor, fps))))
                if tin and len(track):
                    half = _f(tlen / 2, fps)
                    track.append(otio.schema.Transition(transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                                                        in_offset=RT(half, fps), out_offset=RT(half, fps)))
                p = _media_path(pa, proj, it, sfx)
                if p is None:
                    continue
                src_len = max(1, end_f - start_f) if it.kind == "image" else max(1, _f(sout - sin, fps))
                clip = otio.schema.Clip(name=p.name, media_reference=otio.schema.ExternalReference(target_url=p.resolve().as_uri()),
                                        source_range=TR(RT(_f(sin, fps) if it.kind != "image" else 0, fps), RT(src_len, fps)))
                clip.metadata["prepro"] = {"role": it.role, "suggestions": it.suggestion_ids, "gain_db": it.gain_db,
                                           "transform": it.transform.model_dump() if it.transform else None, "note": it.note}
                if abs(it.speed - 1) > 1e-3:
                    clip.effects.append(otio.schema.LinearTimeWarp(time_scalar=it.speed))
                track.append(clip)
                cursor = start_f + (max(1, end_f - start_f))
            timeline.tracks.append(track)
    for m in tl.markers:
        timeline.tracks.markers.append(otio.schema.Marker(name=m.name, marked_range=TR(RT(_f(m.t, fps), fps), RT(0, fps)),
                                                          metadata={"note": m.note, "suggestion": m.suggestion_id}))
    path.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(timeline, str(path))
    return path


def write_kdenlive(otio_path: Path, path: Path) -> Path | None:
    try:
        import opentimelineio as otio

        tl = otio.adapters.read_from_file(str(otio_path))
        otio.adapters.write_to_file(tl, str(path), adapter_name="kdenlive")
        return path
    except Exception:
        return None


# ------------------------------------------------------------------ MLT (Shotcut / melt)
def write_mlt(tl: Timeline, pa: ProjectAnalysis, path: Path, *, project_root=None) -> Path:
    proj = Project(project_root or pa.root)
    fps = tl.fps
    sfx = builtin_sfx_files(tl, path.parent)
    num, den = (int(round(fps * 1000)), 1000) if abs(fps - round(fps)) > 0.01 else (int(round(fps)), 1)
    mlt = ET.Element("mlt", LC_NUMERIC="C", version="7.0.0", title=tl.name, producer="main_bin")
    ET.SubElement(mlt, "profile", description=f"PrePro {tl.width}x{tl.height}", width=str(tl.width), height=str(tl.height),
                  progressive="1", sample_aspect_num="1", sample_aspect_den="1", display_aspect_num=str(tl.width),
                  display_aspect_den=str(tl.height), frame_rate_num=str(num), frame_rate_den=str(den), colorspace="709")
    producers: dict[str, str] = {}

    def producer_for(p: Path, is_image: bool, speed: float = 1.0) -> str:
        key = f"{p}|{speed:.4f}"
        if key in producers:
            return producers[key]
        pid = f"producer{len(producers)}"
        pr = ET.SubElement(mlt, "producer", id=pid)
        if abs(speed - 1) > 1e-3:
            _sub(pr, "property", f"{speed:.4f}:{p.resolve()}", name="resource")
            _sub(pr, "property", "timewarp", name="mlt_service")
        else:
            _sub(pr, "property", str(p.resolve()), name="resource")
        if is_image:
            _sub(pr, "property", "pixbuf", name="mlt_service")
            _sub(pr, "property", "1", name="aspect_ratio")
        producers[key] = pid
        return pid

    playlists = []
    for track in ("V1", "V2", "V3", "A1", "A2", "A3", "A4"):
        items = [i for i in tl.items if i.track == track and i.kind in (("video", "image") if track.startswith("V") else ("audio",))]
        if not items:
            continue
        lanes: list[list[Item]] = []
        for it in sorted(items, key=lambda i: i.rec_in):
            for lane in lanes:
                if lane[-1].rec_out <= it.rec_in + 1e-3 or (it.transition_in != "cut" and track == "V1"):
                    lane.append(it)
                    break
            else:
                lanes.append([it])
        for li, lane in enumerate(lanes):
            plid = f"playlist_{track}_{li}"
            pl = ET.Element("playlist", id=plid)
            cursor = 0
            for it, rin, rout, sin, sout, _tin, _tl in _trim_transitions(lane):
                p = _media_path(pa, proj, it, sfx)
                if p is None:
                    continue
                s_f, e_f = _f(rin, fps), _f(rout, fps)
                if s_f > cursor:
                    _sub(pl, "blank", length=str(s_f - cursor))
                pid = producer_for(p, it.kind == "image", it.speed if it.kind != "image" else 1.0)
                if it.kind == "image":
                    _sub(pl, "entry", producer=pid, **{"in": "0", "out": str(max(0, e_f - s_f - 1))})
                else:
                    src_in = _f(sin / max(it.speed, 1e-6), fps)      # timewarp producers count warped frames
                    src_out = src_in + max(1, e_f - s_f) - 1
                    _sub(pl, "entry", producer=pid, **{"in": str(src_in), "out": str(src_out)})
                cursor = e_f
            playlists.append((plid, pl, track))
    for _, pl, _ in playlists:
        mlt.append(pl)
    tractor = ET.SubElement(mlt, "tractor", id="tractor0", **{"in": "0", "out": str(max(0, _f(tl.duration, fps) - 1))})
    _sub(tractor, "property", "PrePro", name="shotcut:projectNote")
    mt = ET.SubElement(tractor, "multitrack")
    for plid, _, track in playlists:
        attrs = {"producer": plid}
        if track.startswith("A"):
            attrs["hide"] = "video"
        ET.SubElement(mt, "track", attrs)
    for i, (_, _, track) in enumerate(playlists[1:], start=1):
        tr = ET.SubElement(tractor, "transition")
        _sub(tr, "property", "0", name="a_track")
        _sub(tr, "property", str(i), name="b_track")
        _sub(tr, "property", "mix", name="mlt_service")
        _sub(tr, "property", "1", name="always_active")
        _sub(tr, "property", "1", name="sum")
        if track.startswith("V"):
            vt = ET.SubElement(tractor, "transition")
            _sub(vt, "property", "0", name="a_track")
            _sub(vt, "property", str(i), name="b_track")
            _sub(vt, "property", "qtblend", name="mlt_service")
    ET.indent(mlt)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(mlt).write(path, encoding="utf-8", xml_declaration=True)
    return path


# ------------------------------------------------------------------ captions
def _ts(t: float, sep: str = ",") -> str:
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int(round((s - int(s)) * 1000)):03d}"


def write_srt(tl: Timeline, path: Path) -> Path:
    lines = []
    for k, c in enumerate(tl.captions, start=1):
        lines += [str(k), f"{_ts(c.t0)} --> {_ts(c.t1)}", c.text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_vtt(tl: Timeline, path: Path) -> Path:
    lines = ["WEBVTT", ""]
    for c in tl.captions:
        lines += [f"{_ts(c.t0, '.')} --> {_ts(c.t1, '.')}", c.text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_caption_overlay(tl: Timeline, path: Path, *, codec: str = "prores") -> Path | None:
    """Captions + text cards on a transparent background (ProRes 4444) — drop on the top track of any NLE."""
    from ..config import assets_dir
    from ..media.ffmpeg import run_ffmpeg
    from ..timeline.captions import write_ass
    from .render import ff_escape

    if not tl.captions and not any(i.kind == "text" for i in tl.items):
        return None
    ass = write_ass(tl, path.with_suffix(".ass"))
    vf = f"ass=filename='{ff_escape(ass)}':fontsdir='{ff_escape(assets_dir() / 'fonts')}':alpha=1"
    args = ["-f", "lavfi", "-i", f"color=c=black@0.0:s={tl.width}x{tl.height}:r={tl.fps}:d={tl.duration:.3f},format=yuva444p10le", "-vf", vf]
    if codec == "prores":
        args += ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "8"]
    else:
        args += ["-c:v", "qtrle", "-pix_fmt", "argb"]
    run_ffmpeg(args + ["-t", f"{tl.duration:.3f}", str(path)], timeout=3600)
    return path


def copy_luts(tl: Timeline, out: Path) -> Path | None:
    from ..assist.looks import lut_path

    lp = lut_path(tl.look) if tl.look else None
    if lp:
        dst = out / lp.name
        shutil.copy(lp, dst)
        return dst
    return None


def loudness(path: Path) -> float | None:
    import pyloudnorm as pyln
    import soundfile as sf

    y, sr = sf.read(str(path), dtype="float64")
    if y.ndim == 1:
        y = np.stack([y, y], -1)
    return float(pyln.Meter(sr).integrated_loudness(y))
