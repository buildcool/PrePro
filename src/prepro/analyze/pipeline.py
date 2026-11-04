"""Orchestrates ingest + local analysis for a whole shoot, with per-asset caching."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..config import Settings
from ..media.probe import probe
from ..media.proxy import extract_audio
from ..project import Project, assign_ids, fast_hash
from ..schema.analysis import ClipAnalysis, ProjectAnalysis, Shot
from ..schema.media import Asset, AssetKind, MediaInfo
from . import context
from .asr import invert, load_wav16, transcribe, vad
from .sound import audio_report, music_info, musicality
from .speech import analyse_speech
from .visual import analyse_video, duplicate_groups, relative_blur

ANALYSIS_VERSION = 9
Progress = Callable[[str, int, int, str], None]


def _noop(stage: str, i: int, n: int, msg: str) -> None:  # pragma: no cover
    pass


def _image_shot(proj: Project, a: Asset) -> list[Shot]:
    import imagehash
    from PIL import Image

    src = proj.path(a.path)
    dst = proj.sub("frames") / f"{a.id}.k0_1.jpg"
    try:
        im = Image.open(src)
        im.seek(0)
        im = im.convert("RGB")
        im.thumbnail((480, 480))
        im.save(dst, quality=88)
        ph = str(imagehash.phash(im))
        arr = np.asarray(im, dtype=np.float32) / 255.0
        rgb = tuple(float(x) for x in arr.reshape(-1, 3).mean(axis=0))
        bright = float(arr.mean())
    except Exception:
        return []
    return [Shot(id=f"{a.id}.k0", asset_id=a.id, t0=0.0, t1=max(a.info.duration, 0.0), keyframes=[0.0], phash=ph,
                 color=rgb, brightness=round(bright, 3), quality=1.0, shot_type="still")]


def analyse_asset(proj: Project, a: Asset, *, sidecar: Path | None, settings: Settings, faces: bool = True) -> tuple[ClipAnalysis, float | None]:
    ca = ClipAnalysis(asset_id=a.id)
    src = proj.path(a.path)
    mus = None
    kind = a.kind
    try:
        if a.info.has_audio and kind not in (AssetKind.LUT, AssetKind.IMAGE, AssetKind.MEME_IMAGE):
            wav = proj.sub("audio") / f"{a.id}.wav"
            if not wav.exists():
                extract_audio(src, wav, sr=16000)
            y = load_wav16(wav)
            total = len(y) / 16000
            if kind != AssetKind.SFX:
                ca.speech = vad(y)
                ca.silences = invert(ca.speech, total, min_len=0.3)
            ca.audio = audio_report(y, 16000, ca.speech, music=kind == AssetKind.MUSIC)
            wants_asr = kind in (AssetKind.UNKNOWN, AssetKind.AROLL, AssetKind.SCREEN, AssetKind.VOICEOVER, AssetKind.MEME_VIDEO)
            if (wants_asr and ca.audio.speech_ratio > 0.1) or (sidecar and sidecar.exists()):
                tr = transcribe(a.id, wav, backend=settings.asr.backend, sidecar=sidecar, model=settings.asr.whisper_model,
                                device=settings.asr.device, compute_type=settings.asr.compute_type, language=settings.asr.language,
                                verbatim=settings.asr.verbatim, speech=ca.speech)
                ca.transcript = analyse_speech(tr, ca.speech, y)
            if kind in (AssetKind.MUSIC, AssetKind.VOICEOVER) or (not a.info.has_video and a.info.duration >= 12):
                import librosa

                ym, srm = librosa.load(str(src), sr=22050, mono=True, duration=600)
                mus = musicality(ym, srm)
                if kind == AssetKind.MUSIC or mus > 0.45:
                    ca.music = music_info(ym, srm)
        if a.info.has_video and not a.info.is_image and kind not in (AssetKind.LUT,):
            fdir = proj.sub("frames")
            ca.shots, meta = analyse_video(a.id, src, fdir, duration=a.info.duration, fps=a.info.fps, faces=faces and kind != AssetKind.MEME_VIDEO)
            if "error" in meta:
                ca.errors.append(meta["error"])
            if kind in (AssetKind.MEME_VIDEO, AssetKind.MEME_IMAGE):
                for sh in ca.shots:
                    sh.flags = []      # memes are designed that way (dark/blurry is intentional)
        elif a.info.is_image or kind in (AssetKind.IMAGE, AssetKind.MEME_IMAGE):
            ca.shots = _image_shot(proj, a)
    except Exception as e:  # never let one bad file kill the project
        ca.errors.append(f"{type(e).__name__}: {e}")
    return ca, mus


def _whisper_ready(settings) -> bool:
    from .asr import whisper_available

    return whisper_available(settings.asr.whisper_model)


def analyse_project(root: str | Path, *, settings: Settings | None = None, progress: Progress | None = None,
                    force: bool = False, faces: bool = True) -> ProjectAnalysis:
    settings = settings or Settings.load()
    progress = progress or _noop
    proj = Project(root)
    scan = proj.scan()
    prev = proj.load_json("ids.json", {}) or {}
    ids = assign_ids(scan.files, prev)
    pa = ProjectAnalysis(root=str(proj.root), version=ANALYSIS_VERSION)
    hints: dict[str, str | None] = {}
    n = len(scan.files)
    hash_to_id = {}
    for i, f in enumerate(scan.files):
        progress("probe", i, n, f.rel)
        h = fast_hash(f.path)
        hash_to_id[h] = ids[f.rel]
        cache = proj.cache / "analysis" / f"{ids[f.rel]}-{h}.probe.json"
        info = None
        if cache.exists() and not force:
            try:
                info = MediaInfo.model_validate_json(cache.read_text(encoding="utf-8"))
            except Exception:
                info = None
        if info is None:
            try:
                info = probe(f.path)
            except Exception as e:
                pa.warnings.append(f"cannot read {f.rel}: {e}")
                continue
            info.path = f.rel
            cache.write_text(info.model_dump_json(), encoding="utf-8")
        kind, why = context.initial_kind(f.media, f.hint, f.path.name, info)
        pa.assets.append(Asset(id=ids[f.rel], path=f.rel, hash=h, kind=kind, kind_reason=why, info=info, tags=f.tags))
        hints[ids[f.rel]] = f.hint
    proj.save_json("ids.json", hash_to_id)
    _apply_notes(proj, scan, pa)
    musical: dict[str, float | None] = {}
    t_start = time.time()
    for i, a in enumerate(pa.assets):
        progress("analyse", i, len(pa.assets), a.path)
        key = proj.cache / "analysis" / f"{a.id}-{a.hash}-v{ANALYSIS_VERSION}-{settings.asr.backend}.json"
        side = scan.sidecars.get(a.path.rsplit(".", 1)[0])
        ca = None
        if key.exists() and not force:
            try:
                data = key.read_text(encoding="utf-8")
                ca = ClipAnalysis.model_validate_json(data)
                if (ca.transcript and ca.transcript.backend == "pocketsphinx" and settings.asr.backend == "auto"
                        and _whisper_ready(settings)):
                    raise ValueError("a better speech model is now available")
                musical[a.id] = proj.load_json(f"analysis/{key.stem}.mus.json", {}).get("m") if (proj.cache / "analysis" / f"{key.stem}.mus.json").exists() else None
            except Exception:
                ca = None
        if ca is None:
            ca, mus = analyse_asset(proj, a, sidecar=side, settings=settings, faces=faces)
            musical[a.id] = mus
            key.write_text(ca.model_dump_json(), encoding="utf-8")
            proj.save_json(f"analysis/{key.stem}.mus.json", {"m": mus})
        pa.clips[a.id] = ca
    progress("context", 0, 1, "kinds, places, genres")
    for a in pa.assets:
        context.refine_kind(a, pa.clips[a.id], musical.get(a.id), hints.get(a.id))
    relative_blur([s for a in pa.assets if a.kind == AssetKind.BROLL for s in pa.clips[a.id].shots])
    duplicate_groups([s for a in pa.assets if a.kind == AssetKind.BROLL for s in pa.clips[a.id].shots])
    context.cluster_context(pa)
    pa.genres = context.guess_genres(pa)
    pa.stats["context_version"] = context.CONTEXT_VERSION
    langs = [c.transcript.language for c in pa.clips.values() if c.transcript and c.transcript.language]
    pa.speech_language = max(set(langs), key=langs.count) if langs else None
    pa.stats.update({
        "assets": len(pa.assets), "analysis_seconds": round(time.time() - t_start, 1),
        "footage_seconds": round(sum(a.info.duration for a in pa.assets if a.info.has_video and not a.info.is_image), 1),
    })
    for a in pa.assets:
        for e in pa.clips[a.id].errors:
            pa.warnings.append(f"{a.path}: {e}")
    proj.save_model("analysis.json", pa)
    progress("done", 1, 1, "analysis saved")
    return pa


def _apply_notes(proj: Project, scan, pa: ProjectAnalysis) -> None:
    import json

    import yaml

    by_path = {a.path: a for a in pa.assets}
    for nf in scan.notes_files:
        try:
            data = yaml.safe_load(nf.read_text(encoding="utf-8")) if nf.suffix in (".yaml", ".yml") else json.loads(nf.read_text(encoding="utf-8"))
        except Exception as e:
            pa.warnings.append(f"cannot read {nf.name}: {e}")
            continue
        if not isinstance(data, dict):
            continue
        for k, v in data.items():
            a = by_path.get(str(k).replace("\\", "/"))
            if a is None:
                # allow bare file names
                a = next((x for x in pa.assets if x.name == str(k)), None)
            if a is not None:
                a.notes += [str(x) for x in (v if isinstance(v, list) else [v])]


def load_analysis(root: str | Path) -> ProjectAnalysis | None:
    proj = Project(root)
    return proj.load_model("analysis.json", ProjectAnalysis)
