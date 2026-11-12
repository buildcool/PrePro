"""Golden files for the iPhone app's parity tests: the desktop engine cuts the synthetic fixture shoots and writes what
it decided (timeline, story, polish) plus a few headline numbers, so PreProCore (Swift) can be checked against the
same decisions.

    python scripts/export_parity.py [--shoots DIR]

Writes ios/PreProCore/Tests/PreProCoreTests/Golden/<name>/: the inputs (analysis, brief, direction), what the rules
brain decided before the editor's checks (brain_story, brain_polish), the finished plans (story, polish, timeline) and a
few headline numbers (expect). Always the rules engine, whatever AI editor this PC uses, so the files never change with
the machine they were made on.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ios" / "PreProCore" / "Tests" / "PreProCoreTests" / "Golden"
METRICS = ROOT / "ios" / "PreProCore" / "Sources" / "PreProCore" / "Resources" / "text_metrics.json"
CASES = {  # golden name → (fixture kind, extra brief text)
    "photo_reel": ("photo_dump", None),
    "photo_single": ("photo_single", None),
    "day_in_life": ("day_in_life", None),
    "text_reel": ("aesthetic_cooking", "Text:\npov: you finally learned to cook\nand it's actually good\n"
                                       "sunday mornings hit different now\nsave this for your next slow weekend\n"),
}
# the desktop's line breaks and block heights the phone must reproduce: (text, style, width, height, scale)
TEXT_CASES = [
    *[("POV: you finally took the trip you kept postponing", "photo", 1080, 1920, s) for s in (1.0, 0.92, 0.84, 0.76)],
    ("3 days, 1 backpack, zero plans", "photo", 1080, 1920, 1.0),
    ("and it was everything", "photo", 1080, 1920, 1.0),
    ("Calangute · Oct 2026", "photo", 1080, 1920, 1.0),
    ("Goa → Jaipur → Udaipur · Dec 2026", "photo", 1080, 1920, 1.0),
    ("pov: you finally learned to cook and it's actually good", "photo", 1080, 1920, 1.0),
    ("save this for your next slow weekend", "photo", 1080, 1920, 0.84),
    ("“the best things happen when you stop planning them” — me, probably", "photo", 1080, 1920, 1.0),
    ("6:42 am", "stamp", 1080, 1920, 1.0),
    ("the one thing nobody tells you about travelling alone in the mountains", "hook", 1080, 1920, 1.0),
    ("SUBSCRIBE FOR THE NEXT ONE", "cta", 1080, 1920, 1.0),
    ("a quiet morning with coffee, rain on the window and absolutely nowhere to be", "aesthetic", 1080, 1920, 1.0),
    ("a very long line with lots of little words to see how the balancing works in a wide frame", "clean", 1920, 1080, 1.0),
    ("नमस्ते दुनिया, यह मेरा पहला वीडियो है और मैं बहुत खुश हूँ", "devanagari", 1080, 1920, 1.0),
    ("emoji at the end 😀🎉 still counts", "photo", 1080, 1920, 1.0),
]


# test songs for the iPhone's music analysis: the fixture synth's style with portable noise (scripts/portable_song.py),
# made at the analysis rate — chosen to cross the analysis's paths (major/minor, a bright drop, the doubling of a slow
# tempo, a song that is all drop)
SONGS = {
    "happy_100": dict(bpm=100, minor=False, seed=16, sections=[("intro", 2, 0.3), ("verse", 4, 0.6), ("chorus", 8, 0.9), ("outro", 2, 0.35)]),
    "warm_92": dict(bpm=92, minor=False, key="D", seed=3, sections=[("intro", 2, 0.25), ("verse", 4, 0.5), ("chorus", 6, 0.8), ("outro", 2, 0.3)]),
    "trap_140": dict(bpm=140, seed=10, sections=[("drop", 8, 1.0), ("outro", 2, 0.3)]),
    "ballad_64": dict(bpm=64, key="E", seed=4, sections=[("intro", 2, 0.3), ("verse", 4, 0.5), ("chorus", 4, 0.7), ("outro", 2, 0.3)]),
}
# songs also made at 44.1 kHz, as a creator's file would be: the desktop decodes them like librosa.load (soxr to
# 22.05 kHz) and the phone with AVAudioConverter; both must hear the same song (the analysis changes with the rate the
# song was made at, so this is checked against its own golden, not the 22.05 kHz one)
FROM_44K = {"happy_100"}


def song_golden(name: str) -> dict:
    """What the desktop hears in a test song: librosa's onset envelope, tempo and beat frames (the phone's tracker must
    land on the same frames), the desktop's whole music analysis, and probes of the samples (the phone's synth must
    make the same song)."""
    import librosa
    import numpy as np
    from portable_song import song

    from prepro.analyze.sound import music_info

    params = SONGS[name]
    y, truth = song(**params, sr=22050)
    onset = librosa.onset.onset_strength(y=y, sr=22050)
    tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=22050, units="frames", tightness=120)
    probe = sorted({int(i) for i in np.linspace(0, len(y) - 1, 97)})
    return {
        "params": {**params, "sections": [list(s) for s in params["sections"]], "sr": 22050},
        "truth": {"beats": [round(b, 4) for b in truth["beats"]], "downbeats": [round(b, 4) for b in truth["downbeats"]],
                  "sections": [list(s) for s in truth["sections"]]},
        "samples": len(y), "probe": {str(i): float(y[i]) for i in probe}, "energy": float(np.sum(y.astype(np.float64) ** 2)),
        "onset": [float(v) for v in onset], "tempo": float(np.atleast_1d(tempo)[0]), "beat_frames": [int(f) for f in frames],
        "music": music_info(y, 22050).model_dump(mode="json"),
        **({"from_44k": _from_44k(params)} if name in FROM_44K else {}),
    }


def _from_44k(params: dict) -> dict:
    import librosa
    from portable_song import song

    from prepro.analyze.sound import music_info

    y44, _ = song(**params, sr=44100)
    y = librosa.resample(y44, orig_sr=44100, target_sr=22050)          # what librosa.load(sr=22050) hands the analysis
    return {"samples_44k": len(y44), "samples": len(y), "music": music_info(y, 22050).model_dump(mode="json")}


def write_song_goldens() -> None:
    out = OUT / "songs"
    out.mkdir(parents=True, exist_ok=True)
    for name in SONGS:
        g = song_golden(name)
        (out / f"{name}.json").write_text(json.dumps(g), encoding="utf-8")
        print(f"song {name}: {g['music']['bpm']} BPM, {len(g['beat_frames'])} beats, sections "
              f"{[s['label'] for s in g['music']['sections']]}, {g['music']['key']} {g['music']['mode']}")


# test photos for the iPhone's photo analysis (scripts/portable_picture.py): sizes that cross Pillow's paths (a 2× and
# 3× box reduction, odd sizes with a leftover row and column, bicubic alone, no resize at all), every way a phone
# stores a photo, out of focus, dark, a burst's second frame, faces: (name, picture, EXIF orientation, face boxes)
PHOTO_CASES = [
    ("wide", dict(w=2000, h=1500, seed=81, palette="beach"), 1, []),
    ("tall_face", dict(w=1500, h=2000, seed=82, palette="cafe", faces=[[460, 400, 300]]), 6, [[0.46, 0.40, 0.30, 0.39]]),
    ("pano", dict(w=2400, h=1350, seed=88, palette="sunset"), 1, []),
    ("odd", dict(w=1999, h=1333, seed=85, palette="food"), 8, []),
    ("big", dict(w=2880, h=2160, seed=90, palette="city"), 3, []),
    ("small", dict(w=640, h=480, seed=87, palette="forest"), 2, []),
    ("tiny", dict(w=400, h=300, seed=86, palette="market"), 1, []),
    ("flipped", dict(w=1203, h=901, seed=83, palette="beach"), 4, []),
    ("transposed", dict(w=1080, h=1350, seed=84, palette="cafe"), 5, []),
    ("transverse", dict(w=1350, h=1080, seed=91, palette="forest"), 7, []),
    ("blurry", dict(w=1500, h=2000, seed=86, palette="market", blur=8), 1, []),
    ("dark", dict(w=2000, h=1500, seed=90, palette="city", noise=24, dim=[3, 10]), 1, []),
    ("burst", dict(w=1500, h=2000, seed=82, palette="cafe", faces=[[460, 400, 300]], dx=14, dy=10, blur=1), 6, [[0.47, 0.41, 0.30, 0.39]]),
    ("group", dict(w=2000, h=1500, seed=92, palette="cafe", faces=[[200, 420, 140], [500, 420, 140], [800, 420, 140]]), 1,
     [[0.2, 0.42, 0.14, 0.24], [0.5, 0.42, 0.14, 0.24], [0.8, 0.42, 0.14, 0.24]]),
]
# a day in Goa like the photo_dump fixture, made of test photos: the burst copy, the out-of-focus and the dark photo an
# editor leaves out, two stored on their side, lunch with friends named last but taken mid-day. The faces are given:
# the phone finds faces with Vision, the desktop with its own detector, so both get the same boxes here and everything
# after the detector is compared on its own. (name, picture, orientation, local time, face boxes)
SHOOT_GPS = (15.5527, 73.7517)
SHOOT = [
    ("photos/IMG_0001.jpg", dict(w=2000, h=1500, seed=81, palette="beach"), 1, "08:02:10", []),
    ("photos/IMG_0002.jpg", dict(w=1500, h=2000, seed=82, palette="beach", faces=[[460, 400, 300]]), 6, "08:05:31", [[0.46, 0.40, 0.30, 0.39]]),
    ("photos/IMG_0003.jpg", dict(w=1500, h=2000, seed=82, palette="beach", faces=[[460, 400, 300]], dx=14, dy=10, blur=1), 6, "08:05:32",
     [[0.47, 0.41, 0.30, 0.39]]),
    ("photos/IMG_0004.jpg", dict(w=1500, h=2000, seed=84, palette="cafe"), 1, "09:31:00", []),
    ("photos/IMG_0005.jpg", dict(w=2000, h=1500, seed=85, palette="food"), 1, "10:12:45", []),
    ("photos/IMG_0006.jpg", dict(w=1500, h=2000, seed=86, palette="market", blur=8), 1, "11:03:20", []),
    ("photos/IMG_0007.jpg", dict(w=1500, h=2000, seed=87, palette="forest"), 8, "13:22:05", []),
    ("photos/IMG_0008.jpg", dict(w=2400, h=1350, seed=88, palette="sunset"), 1, "17:46:40", []),
    ("photos/IMG_0009.jpg", dict(w=1500, h=2000, seed=89, palette="sunset", faces=[[550, 400, 300]]), 1, "18:10:12", [[0.55, 0.40, 0.30, 0.39]]),
    ("photos/IMG_0010.jpg", dict(w=2000, h=1500, seed=90, palette="city", noise=24, dim=[3, 10]), 1, "21:34:50", []),
    ("photos/IMG_0011.jpg", dict(w=2000, h=1500, seed=92, palette="cafe", faces=[[200, 420, 140], [500, 420, 140], [800, 420, 140]]), 1,
     "12:31:15", [[0.2, 0.42, 0.14, 0.24], [0.5, 0.42, 0.14, 0.24], [0.8, 0.42, 0.14, 0.24]]),
]
# where the phone must name places as the desktop does: the fixture's beach, cities, the sea, the poles, the date line
PLACES = [(15.5527, 73.7517), (15.552700000000002, 73.7517), (26.9124, 75.7873), (24.5854, 73.7125), (28.6139, 77.209),
          (19.076, 72.8777), (12.9716, 77.5946), (48.8566, 2.3522), (40.7128, -74.006), (-33.8688, 151.2093),
          (35.6762, 139.6503), (51.5074, -0.1278), (-22.9068, -43.1729), (64.1466, -21.9426), (0.0, 0.0), (89.9, 179.9),
          (-89.9, -179.9), (-17.7134, 178.065), (52.52, 13.405), (1.3521, 103.8198), (30.0444, 31.2357), (-1.2921, 36.8219)]


def picture_spec(spec: dict) -> dict:
    """A picture's full recipe, every default spelled out (the phone reads it as is)."""
    return {"w": spec["w"], "h": spec["h"], "seed": spec["seed"], "palette": spec.get("palette", "beach"), "shapes": spec.get("shapes", 7),
            "noise": spec.get("noise", 8), "dx": spec.get("dx", 0), "dy": spec.get("dy", 0), "blur": spec.get("blur", 0),
            "dim": spec.get("dim"), "faces": spec.get("faces", [])}


def _face_boxes(faces: list) -> list:
    from prepro.schema.analysis import FaceBox

    return [FaceBox(t=0.0, x=x, y=y, w=w, h=h, conf=0.99) for x, y, w, h in faces]


def photo_case(name: str, spec: dict, orientation: int, faces: list) -> dict:
    """What the desktop measures on a test photo: its thumbnail's fingerprint and photo_measures."""
    import numpy as np
    from PIL import Image
    from portable_picture import fnv, picture, stored

    from prepro.analyze.pipeline import photo_measures

    up = picture(**spec)
    st = stored(up, orientation)
    im = Image.fromarray(up)                           # what exif_transpose gives back from the stored pixels
    im.thumbnail((480, 480))
    thumb = np.asarray(im)
    probe = [[x, y] for x in (0, up.shape[1] // 3, up.shape[1] - 1) for y in (0, up.shape[0] // 2, up.shape[0] - 1)]
    return {"name": name, "picture": picture_spec(spec), "orientation": orientation, "faces": faces, "stored": [st.shape[1], st.shape[0]],
            "probe": [[x, y, *(int(v) for v in up[y, x])] for x, y in probe], "thumb": [thumb.shape[1], thumb.shape[0]],
            "thumb_fnv": fnv(thumb), "measures": photo_measures(im, _face_boxes(faces))}


def shoot_golden() -> dict:
    """The fixture-like shoot as the desktop analyses and cuts it: every photo measured, bursts, days, places, the genre,
    then the rules brain's direction, story, polish and timeline (the song: the photo_reel golden's)."""
    from datetime import datetime

    from PIL import Image
    from portable_picture import picture, stored

    from prepro.analyze import context
    from prepro.analyze.pipeline import ANALYSIS_VERSION, photo_measures
    from prepro.analyze.visual import duplicate_groups
    from prepro.brain.basic import BasicBrain
    from prepro.schema.analysis import ClipAnalysis, ProjectAnalysis, Shot
    from prepro.schema.brief import CreatorBrief
    from prepro.schema.media import Asset, AssetKind, GeoPoint, MediaInfo
    from prepro.timeline.compiler import compile_timeline

    base = json.loads((OUT / "photo_reel" / "analysis.json").read_text(encoding="utf-8"))
    song = next(a for a in base["assets"] if a["kind"] == "music")
    pa = ProjectAnalysis(version=ANALYSIS_VERSION, root="", assets=[Asset.model_validate(song)],
                         clips={song["id"]: ClipAnalysis.model_validate(base["clips"][song["id"]])})
    photos = []
    for k, (name, spec, orientation, taken, faces) in enumerate(SHOOT):
        aid = f"I{k + 1:02d}"
        up = picture(**spec)
        h, w = stored(up, orientation).shape[:2]
        im = Image.fromarray(up)
        im.thumbnail((480, 480))
        boxes = _face_boxes(faces)
        m = photo_measures(im, boxes)
        when = f"2026-10-10T{taken}+05:30"
        info = MediaInfo(path=name, size=0, format_name="image2", duration=0.04, has_video=True, has_audio=False, is_image=True, width=w,
                         height=h, fps=25.0, rotation={3: 180, 6: 90, 8: 270}.get(orientation, 0), creation_time=datetime.fromisoformat(when),
                         location=GeoPoint(lat=SHOOT_GPS[0], lon=SHOOT_GPS[1]))
        pa.assets.append(Asset(id=aid, path=name, hash="", kind=AssetKind.IMAGE, kind_reason="photo", info=info))
        shot = Shot(id=f"{aid}.k0", asset_id=aid, t0=0.0, t1=0.04, keyframes=[0.0], phash=m["phash"], color=m["color"],
                    brightness=m["brightness"], contrast=m["contrast"], sharpness=m["sharpness"], quality=m["quality"], flags=m["flags"],
                    faces=boxes[:6], face_ratio=1.0 if boxes else 0.0, aesthetic=m["aesthetic"], shot_type="still",
                    track=[(0.0, round(b.x, 3), round(b.y, 3)) for b in sorted(boxes, key=lambda b: -b.w * b.h)[:1]])
        pa.clips[aid] = ClipAnalysis(asset_id=aid, shots=[shot])
        photos.append({"name": name, "picture": picture_spec(spec), "orientation": orientation, "creation_time": when,
                       "location": {"lat": SHOOT_GPS[0], "lon": SHOOT_GPS[1]}, "faces": faces})
    duplicate_groups([s for a in pa.assets if a.kind == AssetKind.IMAGE for s in pa.clips[a.id].shots], max_dist=12, prefix="burst")
    context.cluster_context(pa)
    pa.genres = context.guess_genres(pa)
    pa.stats["context_version"] = context.CONTEXT_VERSION
    pa.stats.update({"assets": len(pa.assets), "analysis_seconds": 0.0, "footage_seconds": 0.0})
    brief = CreatorBrief()
    brain = BasicBrain(pa, brief)
    d = next(x for x in brain.directions().directions if x.playbook == "photo_reel")
    story = brain.story(d)
    polish = brain.polish(d, story)
    tl = compile_timeline(pa, d, story, polish, brief)
    return {"photos": photos, "analysis": pa.model_dump(mode="json"), "brief": brief.model_dump(mode="json"), "direction": d.model_dump(mode="json"),
            "story": story.model_dump(mode="json"), "polish": polish.model_dump(mode="json"), "timeline": tl.model_dump(mode="json")}


FACE_VIDEO = ("head-pose-face-detection-female.mp4",
              "https://raw.githubusercontent.com/intel-iot-devkit/sample-videos/master/head-pose-face-detection-female.mp4")
FACE_TIMES = (5.0, 40.0, 90.0)


def faces_golden() -> dict | None:
    """Where the desktop's face detector finds a real face (Intel's sample video, CC BY 4.0) on frames of it, measured
    like a photo (the 480 px thumbnail): the phone's Vision boxes must land on the same face, the same way up."""
    import subprocess

    import numpy as np
    from PIL import Image

    from prepro.analyze.visual import face_detector
    from prepro.fixtures.realmedia import cache_dir

    video = cache_dir() / "face" / FACE_VIDEO[0]
    if not video.exists():
        return None
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for t in FACE_TIMES:
            png = Path(td) / f"{t}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(video), "-frames:v", "1", "-y", str(png)], check=True)
            im = Image.open(png).convert("RGB")
            im.thumbnail((480, 480))
            boxes = face_detector()(np.asarray(im), 0.0)
            frames.append({"t": t, "size": list(im.size), "boxes": [b.model_dump(mode="json") for b in boxes]})
    return {"video": FACE_VIDEO[0], "url": FACE_VIDEO[1], "frames": frames}


def places_golden() -> list:
    from prepro.analyze.context import place_name
    from prepro.schema.media import GeoPoint

    return [{"lat": lat, "lon": lon, "name": place_name(GeoPoint(lat=lat, lon=lon))} for lat, lon in PLACES]


def write_photo_goldens() -> None:
    out = OUT / "photos"
    out.mkdir(parents=True, exist_ok=True)
    cases = [photo_case(*c) for c in PHOTO_CASES]
    (out / "measures.json").write_text(json.dumps(cases, indent=1), encoding="utf-8")
    for c in cases:
        m = c["measures"]
        print(f"photo {c['name']}: {c['thumb'][0]}x{c['thumb'][1]} sharp {m['sharpness']} striking {m['aesthetic']} {m['flags']}")
    shoot = shoot_golden()
    (out / "shoot.json").write_text(json.dumps(shoot, indent=1, ensure_ascii=False), encoding="utf-8")
    left = [s["ref"] for s in shoot["story"]["items"]]
    print(f"photo shoot: {len(shoot['photos'])} photos -> reel of {left}, {len(shoot['timeline']['items'])} timeline items")
    (out / "places.json").write_text(json.dumps(places_golden(), indent=1, ensure_ascii=False), encoding="utf-8")
    faces = faces_golden()
    if faces:
        (out / "faces.json").write_text(json.dumps(faces, indent=1), encoding="utf-8")
        print(f"faces: {[(f['t'], len(f['boxes'])) for f in faces['frames']]}")
    else:
        print("faces: the face video isn't downloaded (prepro testmedia fetch): faces.json left as it is")


def write_text_metrics() -> None:
    """The bundled fonts' advance widths as the desktop measures them (Pillow, basic layout, the font's default
    instance, size 100: a plain sum of per-character advances, checked in tests/unit/test_ios_goldens.py), plus the
    caption styles, safe areas, glue words and libass factors — so the phone breaks your lines where the desktop does
    and finds the same room beside a face. Characters a font lacks measure as its .notdef glyph, as on the desktop."""
    from PIL import ImageFont

    from prepro.config import assets_dir
    from prepro.timeline import captions as C

    ranges = [(0x20, 0x250), (0x2000, 0x2070), (0x20A0, 0x20D0), (0x2190, 0x2200), (0x900, 0x980)]
    fonts = {}
    for name in sorted({s[0] for s in C.STYLES.values()}):
        files = sorted((assets_dir() / "fonts").glob(name.replace(" ", "") + "*.ttf"))
        if not files:
            continue
        f = ImageFont.truetype(str(files[0]), 100, layout_engine=ImageFont.Layout.BASIC)
        asc, desc = f.getmetrics()
        notdef = f.getlength("\U0010fffd")                   # a private-use code point no font here has
        adv = {str(cp): f.getlength(chr(cp)) for lo, hi in ranges for cp in range(lo, hi)}
        fonts[name] = {"file": files[0].name, "line_h": asc + desc, "notdef": notdef,
                       "advances": {k: v for k, v in adv.items() if v != notdef}}
    data = {"safe": C.SAFE, "glue": sorted(C.GLUE), "libass_width": C.LIBASS_WIDTH, "fonts": fonts,
            "styles": {k: {"font": v[0], "size": v[1], "primary": v[2], "outline": v[3], "bold": v[4], "upper": v[5]} for k, v in C.STYLES.items()}}
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    blocks = []
    for text, style, w, h, scale in TEXT_CASES:
        lines, height = C.text_block(text, style, w, h, scale)
        blocks.append({"text": text, "style": style, "width": w, "height": h, "scale": scale, "lines": lines, "block": height})
    (OUT / "text_blocks.json").write_text(json.dumps(blocks, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"text metrics: {len(fonts)} fonts -> {METRICS.name}; {len(blocks)} text blocks")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoots", default=os.environ.get("PREPRO_TEST_SHOOTS") or str(Path(tempfile.gettempdir()) / "prepro-parity"))
    ap.add_argument("--photos", action="store_true", help="only the photo goldens (photos/: measures, shoot, places, faces)")
    args = ap.parse_args()
    if args.photos:
        write_photo_goldens()
        return 0
    from prepro import knowledge as K
    from prepro.assist.music import brief_for, rank_tracks
    from prepro.brain.basic import BasicBrain
    from prepro.config import Settings
    from prepro.engine import analysis, build
    from prepro.fixtures import shoots

    settings = Settings.load()
    settings.ai_editor = "basic"                     # the rules engine: the same goldens on every machine

    write_text_metrics()
    write_song_goldens()
    base = Path(args.shoots) / "parity"
    for name, (kind, brief) in CASES.items():
        root = base / kind
        if not (root / ".built").exists():
            shoots.build(kind, base, sidecars=True, quick=True)
            (root / ".built").write_text("ok")
        res = build(root, brief_text=brief, render=False, settings=settings,
                    routing={k: "basic" for k in settings.routing.model_dump()})
        tl = res.timeline
        out = OUT / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "timeline.json").write_text(tl.model_dump_json(indent=1), encoding="utf-8")
        (out / "story.json").write_text(res.story.model_dump_json(indent=1), encoding="utf-8")
        (out / "polish.json").write_text(res.polish.model_dump_json(indent=1), encoding="utf-8")
        # the inputs the decisions were made from, so the phone can be run on exactly the same: the analysis (no local
        # paths in it), the brief and the direction
        pa = analysis(root)
        pa.root = "."
        for a in pa.assets:
            a.info.path = a.path
        (out / "analysis.json").write_text(pa.model_dump_json(), encoding="utf-8")
        (out / "brief.json").write_text(res.brief.model_dump_json(indent=1), encoding="utf-8")
        (out / "direction.json").write_text(res.direction.model_dump_json(indent=1), encoding="utf-8")
        # the brain's own decisions, before the editor's checks fix anything: the first thing the phone must match
        brain = BasicBrain(analysis(root), res.brief)
        story = brain.story(res.direction)
        (out / "brain_story.json").write_text(story.model_dump_json(indent=1), encoding="utf-8")
        (out / "brain_polish.json").write_text(brain.polish(res.direction, story).model_dump_json(indent=1), encoding="utf-8")
        # the pieces those decisions stand on: the music brief and ranking for each soundtrack job, and the beat grid
        pb = K.playbook(res.direction.playbook)
        need = float(res.direction.knobs.target_length or 15.0)
        music = {}
        for mode in ("front", "bed", "light"):
            mb = brief_for(mode, pb, res.brief.prefs.music_mood, need_secs=need, pace=res.direction.knobs.pace)
            ranked = rank_tracks(pa, mb, mode, avoid=pb.music.get("avoid", []))
            music[mode] = {"brief": mb.model_dump(), "ranked": [{"asset_id": t.asset_id, "score": t.score, "why": t.why} for t in ranked]}
        grid = brain._reel_grid(need, res.direction.playbook)
        music["grid"] = {"need": need, "playbook": res.direction.playbook, **grid}
        (out / "music.json").write_text(json.dumps(music, indent=1, ensure_ascii=False), encoding="utf-8")
        texts = sorted((i for i in tl.items if i.kind == "text"), key=lambda i: i.rec_in)
        expect = {
            "playbook": tl.playbook, "duration": round(tl.duration, 3), "width": tl.width, "height": tl.height,
            "tracks": {t: len(tl.track(t)) for t in tl.tracks()},
            "v1_rec_in": [round(i.rec_in, 3) for i in tl.track("V1")],
            "texts": [i.text for i in texts],
            "suggestion_keys": sorted({s.payload.get("key", "") for s in tl.suggestions}),
        }
        (out / "expect.json").write_text(json.dumps(expect, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {tl.playbook}, {tl.duration:.2f} s, {len(tl.items)} items -> {out}")
    write_photo_goldens()                             # after photo_reel: its song goes into the test shoot
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
