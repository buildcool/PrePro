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
    args = ap.parse_args()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
