"""The creator's own clock: what their phone showed when they shot each clip.

"6:42 am" on a day-in-my-life cut has to be the time the creator lived, not the file's UTC stamp. Phones write it in
different ways:
- an iPhone video carries its local creation date with the offset (``com.apple.quicktime.creationdate``);
- a phone photo carries its EXIF time, with ``OffsetTimeOriginal`` when the camera wrote one;
- most Android videos carry only UTC (``creation_time``).
So a clip's local time is its own local stamp when it has one; a UTC-only clip is put in the shoot's time zone (the one
the shoot's other files state, else this computer's).

A shooting day runs from 4 am to 4 am: the 1 am ride home belongs to the night before, not to a second day.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

DAY_STARTS_AT = 4                       # hours after midnight

PARTS = [  # (until hour, name) — the part of the day a moment belongs to, in the creator's words
    (4.0, "night"), (11.5, "morning"), (14.0, "midday"), (17.5, "afternoon"), (21.0, "evening"), (24.01, "night")]


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def own_local(info) -> datetime | None:
    """The clip's own local time, when the file states it (with its offset); None when it only has UTC or nothing."""
    t = _parse((info.tags or {}).get("com.apple.quicktime.creationdate"))
    if t is not None and t.tzinfo is not None:
        return t
    if info.is_image and info.creation_time is not None:
        return info.creation_time       # EXIF time is the camera's own clock (with its offset, or this computer's)
    return None


def shoot_zone(infos) -> timezone | None:
    """The shoot's UTC offset as its files state it (the most common one), None when no file states one."""
    offs = Counter(t.utcoffset() for t in (own_local(i) for i in infos) if t is not None and t.tzinfo is not None)
    return timezone(offs.most_common(1)[0][0]) if offs else None


def local_time(info, zone: timezone | None = None) -> datetime | None:
    """When this was shot, on the creator's clock."""
    own = own_local(info)
    if own is not None:
        return own
    t = info.creation_time
    if t is None:
        return None
    if t.tzinfo is None:                # written without a zone: already the camera's local time
        return t
    return t.astimezone(zone) if zone is not None else t.astimezone()


def zone_from_stats(stats: dict) -> timezone | None:
    off = stats.get("utc_offset_min")
    return timezone(timedelta(minutes=float(off))) if off is not None else None


def shooting_day(t: datetime) -> date:
    return (t - timedelta(hours=DAY_STARTS_AT)).date()


def part_of_day(t: datetime) -> str:
    h = t.hour + t.minute / 60
    return next(name for until, name in PARTS if h < until)


def stamp(t: datetime) -> str:
    """'6:42 am' — the small time stamp on a day-in-my-life moment."""
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def plausible(t: datetime | None, now: datetime | None = None) -> datetime | None:
    """Cameras with a dead clock write 1970/1904/2000-01-01 or future dates: those count as unknown."""
    if t is None:
        return None
    ts = t.timestamp()
    limit = (now or datetime.now()).timestamp() + 2 * 86400
    return t if 946771200 <= ts <= limit else None          # 2000-01-02 … now
