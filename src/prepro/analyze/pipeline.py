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
from .asr import can_improve, failed_note, invert, load_wav16, transcribe, vad
from .sound import audio_report, music_info, musicality
from .speakers import assign_speakers
from .speech import analyse_speech
from .visual import analyse_video, duplicate_groups, relative_blur

ANALYSIS_VERSION = 13         # 10: seats + mouth movement, a speaker per line; 11: the facecam of screen recordings;
                               # 12: photos — upright copy, EXIF time/place, sharpness, faces, striking score;
                               # 13: two seats only when two people are on screen together
Progress = Callable[[str, int, int, str], None]


def _noop(stage: str, i: int, n: int, msg: str) -> None:  # pragma: no cover
    pass


PHOTO_MAX = 2560          # upright working copy of each photo, long side (enough for a 1080×1920 reel with a push-in)


def photo_copy(proj: Project, a: Asset) -> Path:
    """Where the upright, resized working copy of a photo lives (the renderer uses it when it exists)."""
    return proj.sub("photos") / f"{a.id}.jpg"


def photo_measures(im, boxes: list, *, photo: bool = True) -> dict:
    """What a still is judged by, from its upright RGB thumbnail (≤ 480 px) and the faces found on it: perceptual hash,
    colour, brightness, contrast, sharpness, the dark/blurry flags, quality and the striking score. The iPhone app
    computes the same numbers from the same pixels (ios/PreProCore Photos/PhotoMeasures.swift, checked against
    goldens from this function)."""
    import cv2
    import imagehash

    ph = str(imagehash.phash(im))
    arr = np.asarray(im, dtype=np.float32) / 255.0
    rgb = tuple(float(x) for x in arr.reshape(-1, 3).mean(axis=0))
    bright = float(arr.mean())
    gray = cv2.cvtColor((arr * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    sharp = float(lap.var())
    contrast = float(gray.std() / 255.0)
    rg, yb = arr[:, :, 0] - arr[:, :, 1], 0.5 * (arr[:, :, 0] + arr[:, :, 1]) - arr[:, :, 2]
    colourful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    if photo:
        # a photo is as sharp as its sharpest part (the face, if there is one): a portrait-mode background is soft
        # on purpose, so the whole-frame measure would throw out exactly the photos people like most
        h, w = gray.shape
        tiles = sorted(float(lap[i * h // 4:(i + 1) * h // 4, j * w // 4:(j + 1) * w // 4].var()) for i in range(4) for j in range(4))
        on_face = [float(lap[max(0, int((b.y - b.h / 2) * h)):int((b.y + b.h / 2) * h), max(0, int((b.x - b.w / 2) * w)):int((b.x + b.w / 2) * w)].var())
                   for b in boxes if b.w * w >= 8 and b.h * h >= 8]
        sharp = max([sharp, tiles[-2], *on_face])
    flags = []
    if bright < 0.17:
        flags.append("dark")
    if sharp < (20 if photo else 25):
        flags.append("blurry")
    q = max(0.0, 1.0 - 0.4 * ("dark" in flags) - 0.4 * ("blurry" in flags))
    # what makes a photo stop the scroll: colour, contrast, sharpness and a face
    striking = round(min(1.0, colourful * 2.2) * 0.35 + min(1.0, contrast * 4) * 0.25 + min(1.0, sharp / 400) * 0.2
                     + 0.2 * bool(boxes), 3)
    return {"phash": ph, "color": rgb, "brightness": round(bright, 3), "contrast": round(contrast, 3),
            "sharpness": round(sharp, 2), "quality": round(q, 3), "flags": flags, "aesthetic": striking}


def _image_shot(proj: Project, a: Asset, *, faces: bool = True) -> list[Shot]:
    from PIL import Image, ImageOps

    src = proj.path(a.path)
    dst = proj.sub("frames") / f"{a.id}.k0_1.jpg"
    try:
        im = Image.open(src)
        im.seek(0)
        im = ImageOps.exif_transpose(im) if a.kind == AssetKind.IMAGE else im      # upright, whatever EXIF says
        im = im.convert("RGB")
        if a.kind == AssetKind.IMAGE:
            big = im.copy()
            big.thumbnail((PHOTO_MAX, PHOTO_MAX))
            big.save(photo_copy(proj, a), quality=92)
        im.thumbnail((480, 480))
        im.save(dst, quality=88)
        boxes = []
        if faces and a.kind == AssetKind.IMAGE:
            from .visual import face_detector

            boxes = face_detector()(np.asarray(im), 0.0)
        m = photo_measures(im, boxes, photo=a.kind == AssetKind.IMAGE)
    except Exception:
        return []
    return [Shot(id=f"{a.id}.k0", asset_id=a.id, t0=0.0, t1=max(a.info.duration, 0.0), keyframes=[0.0], phash=m["phash"],
                 color=m["color"], brightness=m["brightness"], contrast=m["contrast"], sharpness=m["sharpness"], quality=m["quality"],
                 flags=m["flags"], faces=boxes[:6], face_ratio=1.0 if boxes else 0.0, aesthetic=m["aesthetic"], shot_type="still",
                 track=[(0.0, round(b.x, 3), round(b.y, 3)) for b in sorted(boxes, key=lambda b: -b.w * b.h)[:1]])]


def analyse_asset(proj: Project, a: Asset, *, sidecar: Path | None, settings: Settings, faces: bool = True,
                  note=None) -> tuple[ClipAnalysis, float | None]:
    """One file, all the way. ``note(fraction, words)`` says where it is inside the file, so a long song or interview
    moves the progress bar instead of freezing it."""
    ca = ClipAnalysis(asset_id=a.id)
    src = proj.path(a.path)
    mus = None
    kind = a.kind
    name = Path(a.path).name

    def say(f: float, words: str) -> None:
        if note:
            note(f, words)

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
                say(0.15, f"Writing down what's said in {name}")
                tr = transcribe(a.id, wav, backend=settings.asr.backend, sidecar=sidecar, model=settings.asr.whisper_model,
                                device=settings.asr.device, compute_type=settings.asr.compute_type, language=settings.asr.language,
                                verbatim=settings.asr.verbatim, speech=ca.speech)
                ca.transcript = analyse_speech(tr, ca.speech, y)
            if kind in (AssetKind.MUSIC, AssetKind.VOICEOVER) or (not a.info.has_video and a.info.duration >= 12):
                import librosa

                say(0.1, f"Listening to {name}")
                ym, srm = librosa.load(str(src), sr=22050, mono=True, duration=600)
                mus = musicality(ym, srm)
                if kind == AssetKind.MUSIC or mus > 0.45:
                    ca.music = music_info(ym, srm, note=lambda f, w: say(0.2 + 0.75 * f, f"{w} in {name}"))
        if a.info.has_video and not a.info.is_image and kind not in (AssetKind.LUT,):
            say(0.55 if ca.transcript else 0.2, f"Looking at the shots in {name}")
            fdir = proj.sub("frames")
            ca.shots, meta = analyse_video(a.id, src, fdir, duration=a.info.duration, fps=a.info.fps, faces=faces and kind != AssetKind.MEME_VIDEO)
            if "error" in meta:
                ca.errors.append(meta["error"])
            if ca.transcript and any(s.seats for s in ca.shots):
                assign_speakers(ca)          # two-shots: who says each line (for framing on the speaker)
            static = max((s.static_ratio for s in ca.shots), default=0.0)
            hud = max((s.hud for s in ca.shots), default=0.0)
            if faces and (kind == AssetKind.SCREEN or (0.01 < static < 0.6 and hud > 0.06)):     # a screen recording
                from .visual import find_facecam

                ca.facecam = find_facecam(src, a.info.duration)    # the streamer's webcam, for gaming layouts
            if kind in (AssetKind.MEME_VIDEO, AssetKind.MEME_IMAGE):
                for sh in ca.shots:
                    sh.flags = []      # memes are designed that way (dark/blurry is intentional)
        elif a.info.is_image or kind in (AssetKind.IMAGE, AssetKind.MEME_IMAGE):
            ca.shots = _image_shot(proj, a, faces=faces)
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
    proj.sub("analysis")                 # recreated if someone cleaned it out — the caches below are written into it
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
                if can_improve(ca.transcript) and settings.asr.backend == "auto" and _whisper_ready(settings):
                    raise ValueError("a better speech model is now available")
                musical[a.id] = proj.load_json(f"analysis/{key.stem}.mus.json", {}).get("m") if (proj.cache / "analysis" / f"{key.stem}.mus.json").exists() else None
            except Exception:
                ca = None
        if ca is None:
            ca, mus = analyse_asset(proj, a, sidecar=side, settings=settings, faces=faces,
                                    note=lambda f, w, i=i: progress("analyse", i + f, len(pa.assets), w))
            musical[a.id] = mus
            key.write_text(ca.model_dump_json(), encoding="utf-8")
            proj.save_json(f"analysis/{key.stem}.mus.json", {"m": mus})
        pa.clips[a.id] = ca
    progress("context", 0, 1, "kinds, places, genres")
    for a in pa.assets:
        context.refine_kind(a, pa.clips[a.id], musical.get(a.id), hints.get(a.id))
    relative_blur([s for a in pa.assets if a.kind == AssetKind.BROLL for s in pa.clips[a.id].shots])
    duplicate_groups([s for a in pa.assets if a.kind == AssetKind.BROLL for s in pa.clips[a.id].shots])
    duplicate_groups([s for a in pa.assets if a.kind == AssetKind.IMAGE for s in pa.clips[a.id].shots], max_dist=12, prefix="burst")
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
        why = failed_note(pa.clips[a.id].transcript)
        if why:                     # talking footage with no words would be cut blind — say so, and how to fix it
            pa.warnings.append(f"{a.path}: the speech couldn't be recognised ({why}). Download a speech model "
                               "(Settings → Speech recognition, or `prepro models --download small`).")
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
