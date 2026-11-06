"""The creator's clock: a clip's local time from what the phone wrote (an iPhone's local creation date, a photo's EXIF
offset, UTC put in the shoot's zone), shooting days that run 4 am to 4 am, "6:42 am" stamps, and look-alike shots
that are retakes only when shot within half an hour of each other."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from prepro.analyze import clock
from prepro.analyze.context import split_far_duplicates
from prepro.schema.analysis import ClipAnalysis, ProjectAnalysis, Shot
from prepro.schema.media import Asset, AssetKind, MediaInfo

IST = timezone(timedelta(hours=5, minutes=30))


def _info(**kw) -> MediaInfo:
    return MediaInfo(path="x.mp4", has_video=True, **kw)


def test_a_clips_local_time_is_what_the_phone_showed():
    iphone = _info(creation_time=datetime(2026, 10, 17, 1, 12, tzinfo=UTC),
                   tags={"com.apple.quicktime.creationdate": "2026-10-17T06:42:00+0530"})
    assert clock.local_time(iphone) == datetime(2026, 10, 17, 6, 42, tzinfo=IST)            # its own local stamp wins
    android = _info(creation_time=datetime(2026, 10, 17, 1, 12, tzinfo=UTC))
    assert clock.local_time(android, IST).strftime("%H:%M") == "06:42"                       # UTC, in the shoot's zone
    photo = _info(creation_time=datetime(2026, 10, 17, 6, 42, tzinfo=IST), is_image=True)
    assert clock.local_time(photo, UTC).strftime("%H:%M") == "06:42"                # EXIF is the camera's clock
    assert clock.shoot_zone([android, iphone, photo]) == IST                                 # what the files state
    assert clock.shoot_zone([android]) is None
    assert clock.local_time(_info()) is None


def test_days_run_four_to_four_and_stamps_read_like_a_phone():
    late = datetime(2026, 10, 18, 1, 30, tzinfo=IST)
    assert clock.shooting_day(late) == datetime(2026, 10, 17).date()                         # the ride home is the night before
    assert clock.shooting_day(datetime(2026, 10, 18, 4, 10)) == datetime(2026, 10, 18).date()
    assert [clock.stamp(datetime(2026, 10, 17, h, m)) for h, m in ((6, 42), (0, 5), (12, 0), (18, 42), (23, 5))] == \
        ["6:42 am", "12:05 am", "12:00 pm", "6:42 pm", "11:05 pm"]
    assert [clock.part_of_day(datetime(2026, 10, 17, h, 0)) for h in (7, 12, 15, 19, 22, 2)] == \
        ["morning", "midday", "afternoon", "evening", "night", "night"]
    assert clock.plausible(datetime(1970, 1, 1, tzinfo=UTC)) is None                # a dead camera clock


def test_look_alike_shots_are_retakes_only_within_half_an_hour():
    def asset(aid: str, hhmm: str) -> Asset:
        t = datetime(2026, 10, 17, int(hhmm[:2]), int(hhmm[3:]), tzinfo=IST)
        return Asset(id=aid, path=f"footage/{aid}.mp4", hash=aid, kind=AssetKind.BROLL, info=_info(creation_time=t))

    room_am, sunset, sunset2, room_pm = asset("C01", "06:42"), asset("C02", "18:15"), asset("C03", "18:16"), asset("C04", "23:05")
    pa = ProjectAnalysis(root=".", assets=[room_am, sunset, sunset2, room_pm])
    for a, (g, r) in zip(pa.assets, [("dup0", 0), ("dup1", 0), ("dup1", 1), ("dup0", 1)], strict=True):
        pa.clips[a.id] = ClipAnalysis(asset_id=a.id, shots=[Shot(id=f"{a.id}.k0", asset_id=a.id, t0=0, t1=5, dup_group=g, dup_rank=r)])
    split_far_duplicates(pa)
    shot = {a.id: pa.clips[a.id].shots[0] for a in pa.assets}
    assert shot["C01"].dup_group is None and shot["C04"].dup_group is None                   # the morning and the night: both kept
    assert shot["C04"].dup_rank == 0
    assert shot["C02"].dup_group == shot["C03"].dup_group == "dup1" and shot["C03"].dup_rank == 1   # a minute apart: a retake
    split_far_duplicates(pa)                                                                  # running it again changes nothing
    assert shot["C03"].dup_rank == 1 and shot["C01"].dup_group is None


def test_a_clip_with_only_its_local_time_still_counts():
    # ffmpeg 9 writes no UTC creation_time next to an iPhone-style local creation date: the clock must still read it
    def asset(aid: str, local: str) -> Asset:
        return Asset(id=aid, path=f"footage/{aid}.mp4", hash=aid, kind=AssetKind.BROLL,
                     info=_info(tags={"com.apple.quicktime.creationdate": local}))

    am, pm = asset("C01", "2026-10-17T06:42:00+0530"), asset("C02", "2026-10-17T23:05:00+0530")
    pa = ProjectAnalysis(root=".", assets=[am, pm])
    for a, r in ((am, 0), (pm, 1)):
        pa.clips[a.id] = ClipAnalysis(asset_id=a.id, shots=[Shot(id=f"{a.id}.k0", asset_id=a.id, t0=0, t1=5, dup_group="dup0", dup_rank=r)])
    split_far_duplicates(pa)
    assert all(pa.clips[a.id].shots[0].dup_group is None for a in pa.assets)                 # 16 hours apart: two moments
