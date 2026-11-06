"""Project-level context: asset kinds, recording order, day/place clusters, genre (playbook) guesses."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime

from ..schema.analysis import ClipAnalysis, GenreGuess, ProjectAnalysis
from ..schema.media import Asset, AssetKind
from . import clock

MEME_WORDS = re.compile(r"meme|reaction|bruh|lol|wtf|shock|facepalm|damage|vine|boom|sticker|cringe|wait.?what", re.I)
SCREEN_WORDS = re.compile(r"screen|gameplay|obs|record|capture|match|stream|valorant|bgmi|pubg|minecraft|fortnite|freefire", re.I)


def initial_kind(media: str, hint: str | None, name: str, info) -> tuple[AssetKind, str]:
    if media == "lut":
        return AssetKind.LUT, "LUT file"
    if media == "audio":
        if hint == "music":
            return AssetKind.MUSIC, "in a music folder"
        if hint in ("sfx", "meme"):
            return AssetKind.SFX, "in an SFX/meme folder"
        if hint == "voiceover":
            return AssetKind.VOICEOVER, "in a voice-over folder"
        if info.duration < 12:
            return AssetKind.SFX, "short audio"
        return AssetKind.MUSIC, "long audio (refined by analysis)"
    if media == "image":
        if hint == "meme" or MEME_WORDS.search(name) or name.lower().endswith(".gif"):
            return AssetKind.MEME_IMAGE, "meme folder / name / GIF"
        return AssetKind.IMAGE, "photo"
    # video
    if hint == "meme":
        return AssetKind.MEME_VIDEO, "in a meme folder"
    if hint == "screen" or SCREEN_WORDS.search(name):
        return AssetKind.SCREEN, "screen/gameplay folder or name"
    if hint == "aroll":
        return AssetKind.AROLL, "in an A-roll folder"
    if hint == "broll":
        return AssetKind.BROLL, "in a B-roll folder"
    if info.duration <= 4 and MEME_WORDS.search(name):
        return AssetKind.MEME_VIDEO, "short clip with a meme-like name"
    return AssetKind.UNKNOWN, "decided after analysis"


def refine_kind(a: Asset, ca: ClipAnalysis, musicality: float | None, hint: str | None) -> None:
    if (a.kind == AssetKind.MUSIC and musicality is not None and hint != "music"
            and ca.audio.speech_ratio > 0.45 and musicality < 0.45):
        a.kind, a.kind_reason = AssetKind.VOICEOVER, f"speech {ca.audio.speech_ratio:.0%}, not musical"
    if a.kind != AssetKind.UNKNOWN:
        return
    words = len(ca.transcript.words) if ca.transcript else 0
    face = max((s.face_ratio for s in ca.shots), default=0.0)
    static = max((s.static_ratio for s in ca.shots), default=0.0)
    hud = max((s.hud for s in ca.shots), default=0.0)
    motion = max((s.motion for s in ca.shots), default=0.0)
    if 0.01 < static < 0.6 and hud > 0.06 and motion > 0.04 and face < 0.5:
        a.kind, a.kind_reason = AssetKind.SCREEN, f"static text/HUD regions ({static:.0%}, edges {hud:.0%}) over moving content"
    elif ca.audio.speech_ratio >= 0.3 and words >= 5:
        a.kind, a.kind_reason = AssetKind.AROLL, f"speech {ca.audio.speech_ratio:.0%}, {words} words, face {face:.0%}"
    else:
        a.kind, a.kind_reason = AssetKind.BROLL, f"little speech ({ca.audio.speech_ratio:.0%})"


def haversine_km(a, b) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def place_name(pt) -> str | None:
    try:
        import reverse_geocoder as rg

        res = rg.search([(pt.lat, pt.lon)], mode=1, verbose=False)
        if res:
            r = res[0]
            return r.get("name") or r.get("admin1")
    except Exception:
        return None
    return None


# bump when days/places/genre logic changes: cached analyses get just this cheap stage re-run (no re-analysis)
CONTEXT_VERSION = 6          # 5: photo reels; 6: days on the creator's clock (4 am to 4 am), day in my life, retakes
                             #    only within half an hour


RETAKE_WINDOW = 30 * 60      # seconds: the same view again within half an hour is a retake


def split_far_duplicates(pa: ProjectAnalysis) -> None:
    """Near-identical shots are retakes only when they were shot close together: your room at 6:42 am and again at
    11:05 pm are the morning and the night of your day, not two takes of one shot. A look-alike group is split where
    more than half an hour passes; each part keeps its own best take (shots without a capture time stay grouped)."""
    zone = clock.shoot_zone(a.info for a in pa.assets)
    groups: dict[str, list] = {}
    for a in pa.assets:
        for s in (pa.clips[a.id].shots if a.id in pa.clips else []):
            if s.dup_group:
                # the same clock as everything else: a clip may carry only its local time (no UTC creation_time)
                t = clock.plausible(clock.local_time(a.info, zone))
                groups.setdefault(s.dup_group, []).append((s, t.timestamp() if t is not None else None))
    for g, members in groups.items():
        timed = sorted((m for m in members if m[1] is not None), key=lambda m: m[1])
        parts: list[list] = []
        for m in timed:
            if parts and m[1] - parts[-1][-1][1] <= RETAKE_WINDOW:
                parts[-1].append(m)
            else:
                parts.append([m])
        if len(parts) <= 1:
            continue
        untimed = [m for m in members if m[1] is None]
        parts[0] += untimed
        for k, part in enumerate(parts):
            part.sort(key=lambda m: m[0].dup_rank)          # the analysis already ranked the takes: keep that order
            for r, (s, _t) in enumerate(part):
                s.dup_group, s.dup_rank = (f"{g}.{k}" if len(part) > 1 else None), (r if len(part) > 1 else 0)


def cluster_context(pa: ProjectAnalysis) -> None:
    """Recording order, day index (shooting days on the creator's own clock) and place clusters (with offline
    reverse-geocoded names)."""
    split_far_duplicates(pa)
    vids = [a for a in pa.assets if a.kind in (AssetKind.AROLL, AssetKind.BROLL, AssetKind.SCREEN, AssetKind.IMAGE, AssetKind.UNKNOWN)]
    zone = clock.shoot_zone(a.info for a in vids)
    if zone is not None:
        pa.stats["utc_offset_min"] = zone.utcoffset(None).total_seconds() / 60
    else:
        pa.stats.pop("utc_offset_min", None)
    times: list[tuple[Asset, datetime | None]] = [(a, clock.plausible(clock.local_time(a.info, zone))) for a in vids]
    days = sorted({clock.shooting_day(t) for _, t in times if t})
    day_no = {d: k + 1 for k, d in enumerate(days)}               # Day 1, Day 2… = distinct shooting days
    for i, (a, t) in enumerate(sorted(times, key=lambda x: (x[1].timestamp() if x[1] else 1e18, x[0].path))):
        ca = pa.clips.setdefault(a.id, ClipAnalysis(asset_id=a.id))
        ca.order_key = t.timestamp() if t else 1e12 + i
        if t:
            ca.day_index = day_no[clock.shooting_day(t)]
    # places: greedy clustering within 25 km
    centers: list[tuple] = []
    for a in vids:
        loc = a.info.location
        if not loc:
            continue
        ca = pa.clips[a.id]
        for k, (c, _name) in enumerate(centers):
            if haversine_km(c, loc) < 25:
                ca.place_cluster = k
                break
        else:
            centers.append((loc, place_name(loc)))
            ca.place_cluster = len(centers) - 1
        ca.place = centers[ca.place_cluster][1] or f"Place {ca.place_cluster + 1}"
    pa.stats["places"] = len(centers)
    pa.stats["days"] = max((c.day_index or 0) for c in pa.clips.values()) if pa.clips else 0


DAY_NAMES = re.compile(r"ditl|day.?in.?(the|my).?life|my.?day|daily.?vlog|routine", re.I)


def day_shape(pa: ProjectAnalysis) -> dict | None:
    """The footage's main shooting day: how many video clips it holds (and what share of all dated clips that is), and
    the hours it spans on the creator's clock. None without dated video clips."""
    zone = clock.zone_from_stats(pa.stats)
    times = []
    for a in pa.assets:
        if a.kind in (AssetKind.BROLL, AssetKind.AROLL) and a.info.has_video and not a.info.is_image:
            t = clock.plausible(clock.local_time(a.info, zone))
            if t is not None:
                times.append(t)
    if not times:
        return None
    day, n = Counter(clock.shooting_day(t) for t in times).most_common(1)[0]
    on = sorted(t for t in times if clock.shooting_day(t) == day)
    return {"day": day, "clips": n, "share": n / len(times), "first": on[0], "last": on[-1],
            "hours": (on[-1] - on[0]).total_seconds() / 3600}


def guess_genres(pa: ProjectAnalysis) -> list[GenreGuess]:
    k = {kind: [a for a in pa.assets if a.kind == kind] for kind in AssetKind}
    dur = lambda xs: sum(a.info.duration for a in xs)  # noqa: E731
    aroll_t, broll_t, screen_t = dur(k[AssetKind.AROLL]), dur(k[AssetKind.BROLL]), dur(k[AssetKind.SCREEN])
    video_t = aroll_t + broll_t + screen_t + 1e-6
    places = pa.stats.get("places", 0)
    days = pa.stats.get("days", 0)
    music = len(k[AssetKind.MUSIC])
    motion = [s.motion for a in k[AssetKind.BROLL] for s in pa.clips[a.id].shots] if k[AssetKind.BROLL] else []
    mean_motion = sum(motion) / len(motion) if motion else 0.0
    tags = " ".join(t for a in pa.assets for s in pa.clips.get(a.id, ClipAnalysis(asset_id=a.id)).shots for t in s.tags)
    food_hint = any(w in tags for w in ("food", "plate", "cooking", "coffee", "kitchen")) or any(
        re.search(r"cook|food|recipe|grwm|morning|routine|cafe", a.path, re.I) for a in pa.assets)
    vertical = sum(1 for a in pa.assets if a.info.is_vertical and a.kind in (AssetKind.AROLL, AssetKind.BROLL))
    out: list[GenreGuess] = []

    def add(pb, score, why):
        out.append(GenreGuess(playbook=pb, score=round(min(1.0, score), 3), why=why))

    if screen_t / video_t > 0.5:
        add("gaming", 0.9, f"{screen_t / video_t:.0%} of footage is screen/gameplay")
    if aroll_t / video_t > 0.6 and broll_t / video_t < 0.35:
        add("talking_head", 0.75 + 0.2 * (aroll_t / video_t), f"{aroll_t / video_t:.0%} talking footage")
        add("podcast_clip", 0.45, "long talking footage can be clipped into Shorts")
    if aroll_t > 0 and broll_t > 0:
        s = 0.55 + 0.15 * min(places, 3) / 3 + 0.1 * min(days, 3) / 3 + 0.1 * (broll_t / video_t)
        add("story_vlog", s, f"talking + B-roll across {places or 1} place(s), {days or 1} day(s)")
    mtags = [set(pa.clips[a.id].music.mood_tags) for a in k[AssetKind.MUSIC] if a.id in pa.clips and pa.clips[a.id].music]
    has_hype = any(t & {"hype", "energetic"} for t in mtags)
    has_cine = any((t & {"epic", "happy", "warm", "chill", "calm", "upbeat"}) and not (t & {"hype"}) for t in mtags)
    if broll_t / video_t > 0.3 and music:
        talk = aroll_t / video_t   # a wordless film throws away the creator's narration
        add("travel_film", 0.45 + 0.25 * (broll_t / video_t) + 0.1 * (places > 1) + 0.05 * (days > 1) + 0.1 * has_cine - 0.3 * talk,
            f"{broll_t:.0f} s of B-roll and music" + (f" across {places} places" if places > 1 else "") + " — a wordless film cut to the music")
        energy = "lots of movement" if mean_motion > 0.2 else ("some movement" if mean_motion > 0.08 else "mostly calm shots")
        add("hype_reel", 0.45 + min(0.35, mean_motion * 0.6) + 0.15 * has_hype + 0.1 * (broll_t < 60) - 0.15 * (aroll_t / video_t),
            f"{energy} in the B-roll" + (", and a high-energy track" if has_hype else "") + ("" if mean_motion > 0.08 else " — a hype cut would be a stretch"))
    # a day in my life: one shooting day's clips from morning to night, mostly without talking (a day of photos is a
    # photo dump, below)
    shape = day_shape(pa)
    n_photos = sum(1 for a in k[AssetKind.IMAGE] if a.id in pa.clips)
    day = None
    if (shape and shape["clips"] >= 5 and shape["hours"] >= 3.0 and shape["share"] >= 0.75 and broll_t / video_t >= 0.5
            and n_photos <= shape["clips"]):
        named = any(DAY_NAMES.search(a.path) for a in pa.assets)
        day = 0.66 + 0.25 * min(1.0, (shape["hours"] - 3.0) / 5.0) + 0.06 * (shape["clips"] >= 10) + 0.1 * named
        add("day_in_life", day, f"{shape['clips']} clips from one day, {clock.stamp(shape['first'])} to {clock.stamp(shape['last'])}"
            " — your day in the order it happened, cut on the beat, with small time stamps")
    if broll_t / video_t > 0.5 and (food_hint or (mean_motion < 0.25 and vertical)):
        add("aesthetic", 0.6 + 0.25 * food_hint - (0.1 if day else 0.0), "calm close-ups / routine footage" + (" with food" if food_hint else ""))
    # comedy: punchline-style talking + a meme/SFX kit in the folder (skits, roasts, reaction bits)
    memes_n = len(k[AssetKind.MEME_IMAGE]) + len(k[AssetKind.MEME_VIDEO])
    comedic_sfx = any(re.search(r"laugh|scratch|boom|bruh|fail|airhorn|rimshot", a.path, re.I) for a in k[AssetKind.SFX])
    lines = [s for a in k[AssetKind.AROLL] if a.id in pa.clips and pa.clips[a.id].transcript for s in pa.clips[a.id].transcript.segments]
    punchy = sum(1 for s in lines if s.text.strip().endswith("!") or len(s.text.split()) <= 4) / max(1, len(lines))
    if aroll_t > 0 and (memes_n or comedic_sfx) and punchy >= 0.25 and broll_t / video_t < 0.35:   # skits are dialogue-driven
        add("comedy", 0.7 + 0.15 * bool(memes_n) + 0.1 * comedic_sfx + 0.15 * min(1.0, punchy),
            f"short punchy lines with {memes_n} meme(s)" + (" and comedy sound effects" if comedic_sfx else "") + " in the folder")
    if video_t > 45 and broll_t > 10:
        add("teaser", 0.4, "enough strong moments for a 15–30 s teaser that sells the full video")
    # photos (a photo dump, or one photo with text): a Reel cut to the song's beat
    photos = [a for a in k[AssetKind.IMAGE] if a.id in pa.clips]
    if photos and (video_t < 5 or (len(photos) >= 3 and len(photos) * 1.5 >= 0.5 * video_t)):
        one = len(photos) == 1
        add("photo_reel", (0.9 if video_t < 5 else 0.62) + 0.05 * bool(music),
            ("one photo" if one else f"{len(photos)} photos") + (" and a song" if music else "")
            + (" — your words on the photo, timed to the music" if one else " — a photo reel cut on the beat"))
    if not out:
        add("story_vlog", 0.4, "default")
    out.sort(key=lambda g: -g.score)
    return out
