"""Build complete synthetic *shoot folders* (one per genre) with a hidden ``.groundtruth.json``.

``prepro demo <kind> <dir>`` uses these, and so do the tests. Real downloaded media (faces, people,
music, speech) is mixed in when available under the test-media cache; otherwise everything is
procedural. Ground truth records what an expert editor would do: which lines to keep, which shots are
bad, where the action peak and the punchline are, the music's beats and sections.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import audio as A
from . import visual as V

KINDS = ["travel_vlog", "aesthetic_cooking", "hype_reel", "talking_head", "comedy_skit", "gaming", "hindi_vlog", "podcast_long"]

GOA = "+15.5527+073.7517/"
JAIPUR = "+26.9124+075.7873/"
MUMBAI = "+19.0760+072.8777/"


def _real(media_dir: Path | None, name: str) -> Path | None:
    if not media_dir:
        return None
    for p in media_dir.rglob(name):
        return p
    return None


def _write_speech(lines, out_wav: Path, seed: int = 0, noise_db: float = -60.0):
    y, truth = A.build_speech(lines, seed=seed, noise_db=noise_db)
    A.write_wav(out_wav, y)
    return truth


def _approx_words(line: A.SpokenLine, text: str | None = None) -> list[dict]:
    words = (text or line.text).split()
    if not words:
        return []
    total = sum(len(w) + 1 for w in words)
    t, out = line.t0, []
    span = line.t1 - line.t0
    for w in words:
        d = span * (len(w) + 1) / total
        out.append({"text": w, "t0": round(t, 3), "t1": round(t + d * 0.92, 3)})
        t += d
    return out


def write_sidecar(media: Path, truth: list[A.SpokenLine], lang: str, romanize: bool = False) -> Path:
    """``<clip>.transcript.json`` — what a creator gets from their phone/YouTube subtitles."""
    segs = []
    for ln in truth:
        txt = ln.romanized if (romanize and ln.romanized) else ln.text
        segs.append({"t0": round(ln.t0, 3), "t1": round(ln.t1, 3), "text": txt, "words": _approx_words(ln, txt)})
    p = media.with_name(media.stem + ".transcript.json")
    p.write_text(json.dumps({"language": lang, "source": "sidecar", "segments": segs}, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _music(root: Path, truth: dict, name: str, **kw):
    y, t = A.procedural_music(**kw)
    rel = f"music/{name}.wav"
    A.write_wav(root / rel, y)
    truth["music"][rel] = asdict(t)


def _sfx_pack(root: Path, kinds=("whoosh", "pop", "riser", "impact", "ding")):
    for i, k in enumerate(kinds):
        A.write_wav(root / f"sfx/{k}.wav", A.sfx(k, seed=i))


def _memes(root: Path):
    V.meme_image("WAIT WHAT", root / "memes/wait_what_shock.png", emoji="O_O")
    V.meme_gif("BRUH", root / "memes/bruh_facepalm.gif")
    boom = root / "memes/.boom.wav"
    A.write_wav(boom, A.sfx("boom"))
    V.meme_video("EMOTIONAL DAMAGE", root / "memes/emotional_damage_fail.mp4", audio=boom)
    boom.unlink(missing_ok=True)


def build(kind: str, out_dir: str | Path, *, media_dir: str | Path | None = None, with_brief: bool = False,
          sidecars: bool = False, quick: bool = False) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown demo kind {kind!r}; choose from {KINDS}")
    root = Path(out_dir) / (kind + ("_brief" if with_brief else ""))
    root.mkdir(parents=True, exist_ok=True)
    md = Path(media_dir) if media_dir else None
    truth: dict = {"shoot": kind, "clips": {}, "music": {}, "expect": {}}
    face = _real(md, "head-pose-face-detection-female.mp4") or _real(md, "head-pose-face-detection-female-and-male.mp4")
    fn = globals()[f"_build_{kind}"]
    fn(root, truth, face=face, md=md, quick=quick, sidecars=sidecars, with_brief=with_brief)
    (root / ".groundtruth.json").write_text(json.dumps(truth, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    return root


def _aroll(root: Path, truth: dict, rel: str, lines, *, face, seed, ct, loc, sidecars, lang="en", vertical=False, place=None, day=None, noise_db=-60.0):
    wav = root / (rel + ".wav")
    spoken = _write_speech(lines, wav, seed=seed, noise_db=noise_db)
    out = root / rel
    V.presenter_clip(wav, out, face_video=face, seed=seed, creation_time=ct, location=loc, vertical=vertical)
    wav.unlink(missing_ok=True)
    if sidecars:
        write_sidecar(out, spoken, lang)
    truth["clips"][rel] = {"kind": "aroll", "lines": [asdict(s) for s in spoken], "place": place, "day": day}
    return spoken


def _broll(root: Path, truth: dict, rel: str, scene: str, *, seed: int, dur: float, move: str = "static", flags=(), ct=None,
           loc=None, place=None, day=None, dup_of=None, vertical=False, audio=None, **kw):
    img = V.scenery(scene, seed=seed)
    V.still_clip(img, root / rel, dur=dur, move=move, creation_time=ct, location=loc, vertical=vertical, audio=audio, **kw)
    truth["clips"][rel] = {"kind": "broll", "scene": scene, "move": move, "flags": list(flags), "place": place, "day": day,
                           "dup_of": dup_of, "fps": 30}


# ------------------------------------------------------------------ genres
def _build_travel_vlog(root, truth, *, face, md, quick, sidecars, with_brief):
    d1, d2 = "2026-10-10T08:{:02d}:00Z", "2026-10-11T17:{:02d}:00Z"
    intro = [
        A.Line("Hey guys, welcome back to my channel.", kind="greeting", keep=False, pause_after=0.5),
        A.Line("So today we are, umm", kind="false_start", keep=False, pause_after=1.4, group="g1"),
        A.Line("So today we are in Goa, and I spent only five thousand rupees for three full days.", kind="hook", group="g1",
               emphasis=["five thousand", "three"], pause_after=0.9),
        A.Line("Uh", kind="filler", keep=False, pause_after=0.6),
        A.Line("Let me show you exactly how I did it.", pause_after=1.8),
    ]
    _aroll(root, truth, "footage/day1/IMG_2041.mp4", intro, face=face, seed=1, ct=d1.format(5), loc=GOA, sidecars=sidecars, place="Goa", day=1)
    _broll(root, truth, "footage/day1/IMG_2042.mp4", "beach", seed=11, dur=6, move="pan_right", ct=d1.format(9), loc=GOA, place="Goa", day=1)
    _broll(root, truth, "footage/day1/IMG_2043.mp4", "beach", seed=11, dur=5, move="static", ct=d1.format(10), loc=GOA, place="Goa", day=1,
           dup_of="footage/day1/IMG_2042.mp4")
    _broll(root, truth, "footage/day1/IMG_2044.mp4", "beach", seed=12, dur=5, move="shaky", flags=["shaky"], ct=d1.format(12), loc=GOA, place="Goa", day=1)
    _broll(root, truth, "footage/day1/IMG_2045.mp4", "sunset", seed=13, dur=4, move="static", flags=["blurry"], blur=9, ct=d1.format(40), loc=GOA, place="Goa", day=1)
    out, peak = V.action_clip(V.scenery("beach", seed=14), root / "footage/day1/IMG_2046.mp4", creation_time=d1.format(20), location=GOA)
    truth["clips"]["footage/day1/IMG_2046.mp4"] = {"kind": "broll", "scene": "beach", "move": "action", "fps": 60,
                                                    "action_peak": peak, "flags": [], "place": "Goa", "day": 1}
    _broll(root, truth, "footage/day1/IMG_2047.mp4", "sunset", seed=15, dur=4, move="whip_out", ct=d1.format(45), loc=GOA, place="Goa", day=1)
    if not quick:
        _broll(root, truth, "footage/day1/IMG_2048.mp4", "forest", seed=16, dur=5, move="tilt_up", ct=d1.format(50), loc=GOA, place="Goa", day=1)
    talk2 = [
        A.Line("Now we are in Jaipur, and the street food here is honestly unreal.", emphasis=["unreal"], pause_after=0.5),
        A.Line("This kachori cost me twenty rupees.", emphasis=["twenty rupees"], pause_after=0.4),
        A.Line("Twenty!", kind="punchline", emphasis=["Twenty"], pause_after=1.2),
        A.Line("Okay so the best part, the best part is the lassi.", kind="retake", group="g2", keep=False, pause_after=0.8),
        A.Line("Okay so the best part is the lassi, it is thick and sweet.", group="g2", pause_after=1.5),
    ]
    _aroll(root, truth, "footage/day2/IMG_3101.mp4", talk2, face=face, seed=2, ct=d2.format(3), loc=JAIPUR, sidecars=sidecars, place="Jaipur", day=2)
    _broll(root, truth, "footage/day2/IMG_3102.mp4", "market", seed=21, dur=6, move="pan_left", ct=d2.format(5), loc=JAIPUR, place="Jaipur", day=2)
    _broll(root, truth, "footage/day2/IMG_3103.mp4", "food", seed=22, dur=5, move="push_in", ct=d2.format(8), loc=JAIPUR, place="Jaipur", day=2)
    _broll(root, truth, "footage/day2/IMG_3104.mp4", "city", seed=23, dur=5, move="static", flags=["dark"], dark=True, ct=d2.format(55), loc=JAIPUR, place="Jaipur", day=2)
    _broll(root, truth, "footage/day2/IMG_3105.mp4", "city", seed=24, dur=6, move="pan_right", ct=d2.format(30), loc=JAIPUR, place="Jaipur", day=2)
    outro = [
        A.Line("So that was three days, five thousand rupees, zero regrets.", kind="payoff", emphasis=["zero regrets"], pause_after=0.6),
        A.Line("Follow for part two, where I try the most expensive hotel in Jaipur.", kind="cta", pause_after=1.0),
    ]
    _aroll(root, truth, "footage/day2/IMG_3110.mp4", outro, face=face, seed=3, ct=d2.format(58), loc=JAIPUR, sidecars=sidecars, place="Jaipur", day=2)
    _music(root, truth, "chill_lofi_90", bpm=90, mood="chill", seed=5,
           sections=[("intro", 2, 0.3), ("verse", 8, 0.5), ("break", 2, 0.3), ("verse", 8, 0.55), ("outro", 2, 0.3)])
    _music(root, truth, "upbeat_travel_118", bpm=118, minor=False, mood="happy", seed=6,
           sections=[("intro", 2, 0.4), ("build", 4, 0.6), ("drop", 8, 0.9), ("outro", 2, 0.4)])
    _music(root, truth, "epic_build_128", bpm=128, mood="epic", seed=7,
           sections=[("intro", 4, 0.3), ("build", 4, 0.65), ("drop", 8, 1.0), ("outro", 4, 0.35)])
    _music(root, truth, "pop_song_vocals_100", bpm=100, minor=False, mood="happy", seed=8, vocal_hum=True,
           sections=[("intro", 2, 0.4), ("verse", 8, 0.6), ("chorus", 8, 0.85), ("outro", 2, 0.4)])
    _sfx_pack(root)
    _memes(root)
    truth["expect"] = {
        "playbooks": ["story_vlog", "travel_film", "hype_reel", "teaser"],
        "hook_contains": "five thousand rupees",
        "must_cut_kinds": ["greeting", "false_start", "filler", "retake"],
        "bad_shots": {"footage/day1/IMG_2044.mp4": "shaky", "footage/day1/IMG_2045.mp4": "blurry", "footage/day2/IMG_3104.mp4": "dark"},
        "dup_pairs": [["footage/day1/IMG_2042.mp4", "footage/day1/IMG_2043.mp4"]],
        "places": ["Goa", "Jaipur"],
        "vocal_track": "music/pop_song_vocals_100.wav",
    }
    if with_brief:
        (root / "brief.md").write_text(
            "Make a 30 second Instagram reel about my Goa + Jaipur budget trip.\n"
            "Hook: use the line where I say five thousand rupees.\n"
            "Use the epic_build_128 song for the montage. No music while I talk.\n"
            "Add text at the end: Follow for part 2\n"
            "Add a meme after I say Twenty!\n"
            "No zooms. Slow-mo on the jump.\n"
            "Don't use the dark night clip.\n", encoding="utf-8")
        (root / "notes.yaml").write_text("footage/day1/IMG_2047.mp4: nice transition shot\n", encoding="utf-8")


def _build_aesthetic_cooking(root, truth, *, face, md, quick, sidecars, with_brief):
    ct = "2026-10-12T09:{:02d}:00Z"
    chop = root / "footage/.chop.wav"
    A.write_wav(chop, A.sfx("chop"))
    sizzle = root / "footage/.sizzle.wav"
    A.write_wav(sizzle, A.sfx("sizzle"))
    _broll(root, truth, "footage/VID_001.mp4", "food", seed=31, dur=5, move="push_in", ct=ct.format(1), vertical=True, audio=chop)
    _broll(root, truth, "footage/VID_002.mp4", "cafe", seed=32, dur=5, move="static", ct=ct.format(3), vertical=True)
    _broll(root, truth, "footage/VID_003.mp4", "food", seed=33, dur=6, move="pan_right", ct=ct.format(6), vertical=True, audio=sizzle)
    out, peak = V.action_clip(V.scenery("cafe", seed=34), root / "footage/VID_004.mp4", dur=4, creation_time=ct.format(8))
    truth["clips"]["footage/VID_004.mp4"] = {"kind": "broll", "scene": "cafe", "move": "action", "fps": 60, "action_peak": peak, "flags": []}
    _broll(root, truth, "footage/VID_005.mp4", "room", seed=35, dur=5, move="pan_left", ct=ct.format(12), vertical=True)
    _broll(root, truth, "footage/VID_006.mp4", "food", seed=36, dur=8, move="static", ct=ct.format(15), vertical=True, audio=chop)
    chop.unlink(missing_ok=True)
    sizzle.unlink(missing_ok=True)
    _music(root, truth, "soft_morning_76", bpm=76, minor=False, mood="calm", seed=9,
           sections=[("intro", 2, 0.2), ("verse", 8, 0.35), ("outro", 2, 0.2)])
    _music(root, truth, "hype_trap_140", bpm=140, mood="hype", seed=10,
           sections=[("intro", 2, 0.4), ("drop", 8, 1.0), ("outro", 2, 0.4)])
    truth["expect"] = {"playbooks": ["aesthetic"], "music_mode": "front_or_light", "no_memes": True, "prefer_track": "music/soft_morning_76.wav"}


def _build_hype_reel(root, truth, *, face, md, quick, sidecars, with_brief):
    ct = "2026-10-13T16:{:02d}:00Z"
    for i, (scene, move) in enumerate([("city", "pan_right"), ("mountain", "pan_left"), ("sunset", "whip_out"),
                                       ("beach", "pan_right"), ("forest", "tilt_up"), ("market", "pan_left")]):
        _broll(root, truth, f"clips/C{i + 1:03d}.mp4", scene, seed=40 + i, dur=4, move=move, ct=ct.format(i * 3), loc=MUMBAI)
    out, peak = V.action_clip(V.scenery("city", seed=49), root / "clips/C007.mp4", dur=4, creation_time=ct.format(30))
    truth["clips"]["clips/C007.mp4"] = {"kind": "broll", "scene": "city", "move": "action", "fps": 60, "action_peak": peak, "flags": []}
    _music(root, truth, "drift_phonk_140", bpm=140, mood="hype", seed=12,
           sections=[("intro", 2, 0.35), ("build", 2, 0.7), ("drop", 8, 1.0), ("outro", 1, 0.4)])
    _sfx_pack(root, ("whoosh", "impact", "riser"))
    truth["expect"] = {"playbooks": ["hype_reel"], "music_mode": "front", "cuts_on_beats": True}


def _build_talking_head(root, truth, *, face, md, quick, sidecars, with_brief):
    lines = [
        A.Line("Hi everyone, it's me again.", kind="greeting", keep=False, pause_after=0.7),
        A.Line("Three editing mistakes that are killing your views.", kind="hook", emphasis=["killing"], pause_after=0.8),
        A.Line("Mistake number one, umm, is", kind="false_start", keep=False, pause_after=1.2, group="m1"),
        A.Line("Mistake number one is a slow intro.", group="m1", emphasis=["slow intro"], pause_after=0.6),
        A.Line("Nobody waits for your logo animation.", pause_after=1.6),
        A.Line("Mistake number two is music that is louder than your voice.", emphasis=["louder"], pause_after=0.5),
        A.Line("Like, you know, basically", kind="filler", keep=False, pause_after=0.9),
        A.Line("Keep the music at least twelve decibels under your voice.", emphasis=["twelve decibels"], pause_after=0.7),
        A.Line("Mistake number three is no captions.", emphasis=["no captions"], pause_after=0.4),
        A.Line("Most people watch on mute.", kind="punchline", pause_after=1.0),
        A.Line("Fix these three and your retention goes up. Follow for more.", kind="cta", pause_after=1.0),
    ]
    _aroll(root, truth, "A001.mp4", lines, face=face, seed=4, ct="2026-10-14T11:00:00Z", loc=None, sidecars=sidecars)
    _broll(root, truth, "broll/B001.mp4", "room", seed=51, dur=5, move="push_in")
    _music(root, truth, "lofi_bed_85", bpm=85, mood="chill", seed=13, sections=[("intro", 2, 0.3), ("verse", 12, 0.45), ("outro", 2, 0.3)])
    truth["expect"] = {"playbooks": ["talking_head"], "hook_contains": "Three editing mistakes", "music_mode": "bed"}


def _build_podcast_long(root, truth, *, face, md, quick, sidecars, with_brief):
    """~2.5 min of talking with three planted Short-worthy moments (gold1–3) between rambling, for the Shorts finder."""
    (root / "podcast").mkdir(parents=True, exist_ok=True)
    L = A.Line
    lines = [
        L("Hey guys, welcome back to the podcast.", kind="greeting", keep=False, pause_after=0.8),
        L("So, uh, yeah, today we're just gonna talk about, you know, stuff.", kind="aside", pause_after=0.9),
        L("I lost ten thousand dollars on my first channel.", kind="hook", group="gold1", emphasis=["ten thousand"], pause_after=0.5),
        L("I bought a fancy camera, a gimbal and three lenses before I had a single viewer.", group="gold1", pause_after=0.4),
        L("Six months later I had forty subscribers.", group="gold1", emphasis=["forty"], pause_after=0.5),
        L("The gear was never the problem. My first ten seconds were boring.", group="gold1", pause_after=0.4),
        L("So here is the lesson: fix your hook before you buy anything.", kind="punchline", group="gold1", emphasis=["hook"], pause_after=1.2),
        L("And then we kind of talked about it for a while and stuff.", kind="aside", pause_after=0.8),
        L("Anyway, where was I, let me check my notes here.", kind="aside", pause_after=1.4),
        L("Why do some videos get a million views from a phone camera?", kind="hook", group="gold2", emphasis=["million"], pause_after=0.5),
        L("Because people don't watch cameras, they watch stories.", group="gold2", pause_after=0.4),
        L("Every viral video I studied had the same three parts.", group="gold2", pause_after=0.4),
        L("A promise in the first three seconds, a twist in the middle, and a payoff at the end.", group="gold2", pause_after=0.4),
        L("That's it. That's the whole secret.", kind="punchline", group="gold2", emphasis=["secret"], pause_after=1.3),
        L("Like I said before, it depends, it really depends on the niche I guess.", kind="aside", pause_after=1.0),
        L("And also, you know, the algorithm and whatever.", kind="aside", pause_after=1.2),
        L("The worst mistake beginners make is talking too slowly.", kind="hook", group="gold3", emphasis=["worst"], pause_after=0.5),
        L("Cut every pause longer than half a second.", group="gold3", pause_after=0.4),
        L("Cut every um, every so, every like.", group="gold3", pause_after=0.4),
        L("Your video will feel twice as fast without losing a single idea.", group="gold3", emphasis=["twice"], pause_after=0.4),
        L("Try it on your next upload and watch your retention.", kind="punchline", group="gold3", pause_after=1.2),
        L("So yeah, that's kind of it for today I guess.", kind="aside", pause_after=0.6),
        L("Thanks for listening, follow for more episodes.", kind="cta", pause_after=1.0),
    ]
    spoken = _aroll(root, truth, "podcast/EP12_cam_a.mp4", lines, face=face, seed=12, ct="2026-10-20T16:00:00Z", loc=None, sidecars=sidecars)
    gold = {}
    for s in spoken:
        if s.group and s.group.startswith("gold"):
            g = gold.setdefault(s.group, [s.t0, s.t1])
            g[0], g[1] = min(g[0], s.t0), max(g[1], s.t1)
    truth["expect"] = {"playbooks": ["podcast_clip", "talking_head"], "shorts": [{"id": k, "t0": v[0], "t1": v[1]} for k, v in sorted(gold.items())]}


def _build_comedy_skit(root, truth, *, face, md, quick, sidecars, with_brief):
    lines = [
        A.Line("Mom, I want to become a YouTuber.", pitch=60, pause_after=0.6),
        A.Line("Okay beta, first finish your homework.", pitch=30, speed=150, pause_after=0.5),
        A.Line("But Mom, MrBeast never did homework!", pitch=62, kind="setup", pause_after=0.9),
        A.Line("MrBeast also never failed maths three times.", pitch=28, speed=150, kind="punchline", emphasis=["three times"], pause_after=1.6),
        A.Line("Emotional damage.", pitch=60, speed=130, kind="punchline", pause_after=1.2),
    ]
    _aroll(root, truth, "skit/take1.mp4", lines, face=face, seed=6, ct="2026-10-15T19:00:00Z", loc=None, sidecars=sidecars, vertical=True)
    _broll(root, truth, "skit/reaction.mp4", "room", seed=61, dur=3, move="push_in", vertical=True)
    _memes(root)
    A.write_wav(root / "sfx/laugh.wav", A.sfx("laugh"))
    A.write_wav(root / "sfx/vine_boom.wav", A.sfx("boom"))
    A.write_wav(root / "sfx/record_scratch.wav", A.sfx("scratch"))
    truth["expect"] = {"playbooks": ["comedy"], "meme_after_kind": "punchline"}


def _build_gaming(root, truth, *, face, md, quick, sidecars, with_brief):
    lines = [
        A.Line("Okay okay, one more round.", speed=180, pause_after=2.0),
        A.Line("Oh my god, behind you!", speed=200, pitch=70, amplitude=190, kind="hype", pause_after=1.5),
        A.Line("Double kill! Let's go!", speed=200, pitch=72, amplitude=200, kind="punchline", pause_after=3.0),
        A.Line("Wait, wait, I am so low.", speed=185, pitch=60, pause_after=2.5),
        A.Line("Victory! We actually won!", speed=190, pitch=70, amplitude=200, kind="payoff", pause_after=1.5),
    ]
    voice = root / "gameplay/.voice.wav"
    spoken = _write_speech(lines, voice, seed=7)
    import soundfile as sf

    v, sr = sf.read(str(voice), dtype="float32")
    mix = v.copy()
    boom = A.sfx("explosion")
    for ln in spoken:
        if ln.kind in ("hype", "punchline", "payoff"):
            at = int(max(0, ln.t0 - 0.4) * sr)
            mix[at: at + len(boom)] += boom[: max(0, min(len(boom), len(mix) - at))] * 0.5
    A.write_wav(voice, mix)
    dur = len(mix) / sr
    events = [(ln.t0, "DOUBLE KILL" if "Double" in ln.text else "VICTORY") for ln in spoken if ln.kind in ("punchline", "payoff")]
    V.screen_clip(root / "gameplay/match_01.mp4", dur=dur, audio=voice, facecam=face, events=events)
    voice.unlink(missing_ok=True)
    if sidecars:
        write_sidecar(root / "gameplay/match_01.mp4", spoken, "en")
    truth["clips"]["gameplay/match_01.mp4"] = {"kind": "screen", "lines": [asdict(s) for s in spoken], "events": events}
    _music(root, truth, "montage_dnb_174", bpm=174, mood="hype", seed=14, sections=[("intro", 2, 0.5), ("drop", 8, 1.0), ("outro", 2, 0.4)])
    _memes(root)
    truth["expect"] = {"playbooks": ["gaming"], "highlights": [e[0] for e in events]}


def _build_hindi_vlog(root, truth, *, face, md, quick, sidecars, with_brief):
    lines = [
        A.Line("नमस्ते दोस्तों, आज हम मुंबई में हैं।", lang="hi", romanized="Namaste doston, aaj hum Mumbai mein hain.", pause_after=0.8),
        A.Line("यह वडा पाव सिर्फ पंद्रह रुपये का है।", lang="hi", kind="hook", romanized="Yeh vada pav sirf pandrah rupaye ka hai.",
               emphasis=["पंद्रह"], pause_after=0.6),
        A.Line("अम्म", lang="hi", kind="filler", keep=False, romanized="Umm", pause_after=0.7),
        A.Line("और स्वाद एकदम कमाल है!", lang="hi", kind="punchline", romanized="Aur swaad ekdum kamaal hai!", pause_after=1.2),
        A.Line("Follow karo for part two.", lang="en-us", kind="cta", romanized="Follow karo for part two.", pause_after=1.0),
    ]
    wav = root / "footage/.hi.wav"
    spoken = _write_speech(lines, wav, seed=9)
    V.presenter_clip(wav, root / "footage/VID_hi_01.mp4", face_video=face, seed=9, creation_time="2026-10-16T13:00:00Z",
                     location=MUMBAI, vertical=True)
    wav.unlink(missing_ok=True)
    # No offline Hindi recogniser is bundled: ship the phone-style sidecar transcript (Devanagari)
    write_sidecar(root / "footage/VID_hi_01.mp4", spoken, "hi")
    truth["clips"]["footage/VID_hi_01.mp4"] = {"kind": "aroll", "lines": [asdict(s) for s in spoken], "place": "Mumbai"}
    _broll(root, truth, "footage/VID_hi_02.mp4", "market", seed=71, dur=5, move="pan_right", ct="2026-10-16T13:05:00Z", loc=MUMBAI, vertical=True)
    _broll(root, truth, "footage/VID_hi_03.mp4", "food", seed=72, dur=5, move="push_in", ct="2026-10-16T13:08:00Z", loc=MUMBAI, vertical=True)
    _music(root, truth, "desi_upbeat_110", bpm=110, minor=False, mood="happy", seed=15, sections=[("intro", 2, 0.4), ("verse", 8, 0.7), ("outro", 2, 0.4)])
    _memes(root)
    truth["expect"] = {"playbooks": ["story_vlog", "hype_reel"], "caption_lang": "hi", "hinglish_available": True}


def style_references(out: Path, *, talking_clip: Path | None = None, seed: int = 0) -> dict[str, Path]:
    """Two reference videos with known style for Style DNA tests:
    - fast_montage.mp4: 0.6 s shots of different scenes cut to music, no talking, no text (hype style);
    - talky_captions.mp4: one talking shot with big burned-in captions, no music (talking-head style)."""
    from ..config import assets_dir
    from ..media.ffmpeg import run_ffmpeg

    out.mkdir(parents=True, exist_ok=True)
    scenes = ["beach", "mountain", "forest", "city", "sunset", "food", "cafe", "market", "room"]
    parts = []
    for k in range(20):
        img = V.scenery(scenes[k % len(scenes)], seed=seed + k)
        p = out / f"_shot{k}.mp4"
        V.still_clip(img, p, dur=0.6, move="static", vertical=True)
        parts.append(p)
    y, _ = A.procedural_music(bpm=128, sections=[("drop", 8, 1.0)], seed=seed + 3)
    A.write_wav(out / "_music.wav", y)
    lst = out / "_list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    fast = out / "fast_montage.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(out / "_music.wav"), "-map", "0:v", "-map", "1:a", "-shortest",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", str(fast)], timeout=600)
    refs = {"fast": fast}
    if talking_clip and talking_clip.exists():
        font = (assets_dir() / "fonts" / "Anton-Regular.ttf").as_posix().replace(":", "\\:")
        lines = ["THREE EDITING", "MISTAKES", "KILLING YOUR", "VIEWS", "NUMBER ONE", "SLOW INTRO", "NOBODY WAITS", "FOR YOUR LOGO"]
        draws = ",".join(f"drawtext=fontfile='{font}':text='{t}':fontsize=h/11:fontcolor=white:borderw=6:bordercolor=black:"
                         f"x=(w-text_w)/2:y=h*0.72:enable='between(t,{i * 2},{i * 2 + 2})'" for i, t in enumerate(lines))
        talky = out / "talky_captions.mp4"
        run_ffmpeg(["-i", str(talking_clip), "-t", "16", "-vf", draws, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(talky)], timeout=600)
        refs["talky"] = talky
    for p in [*parts, out / "_music.wav", lst]:
        p.unlink(missing_ok=True)
    return refs
