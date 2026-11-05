"""ffprobe → :class:`MediaInfo` (fps, VFR, rotation, creation time, GPS)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..schema.media import GeoPoint, MediaInfo
from .ffmpeg import ffprobe_json

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
GIF_EXT = {".gif"}
_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)?")


def _rate(s: str | None) -> float | None:
    if not s or s in ("0/0", "0"):
        return None
    if "/" in s:
        n, d = s.split("/", 1)
        try:
            return float(n) / float(d) if float(d) else None
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_iso6709(s: str | None) -> GeoPoint | None:
    if not s:
        return None
    m = _ISO6709.search(s)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    alt = float(m.group(3)) if m.group(3) else None
    return GeoPoint(lat=lat, lon=lon, alt=alt)


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


EXIF_ROTATION = {3: 180, 6: 90, 8: 270}     # EXIF orientation → degrees (phone photos are often stored sideways)


def _exif_gps(gps: dict) -> GeoPoint | None:
    try:
        def deg(v) -> float:
            d, m, s = (float(x) for x in v)
            return d + m / 60 + s / 3600

        lat, lon = deg(gps[2]), deg(gps[4])
        lat = -lat if str(gps.get(1, "N")).upper().startswith("S") else lat
        lon = -lon if str(gps.get(3, "E")).upper().startswith("W") else lon
        return GeoPoint(lat=lat, lon=lon) if (-90 <= lat <= 90 and -180 <= lon <= 180 and (lat or lon)) else None
    except Exception:
        return None


def photo_exif(path: str | Path) -> tuple[int, datetime | None, GeoPoint | None]:
    """(rotation, capture time, GPS) from a photo's EXIF, read locally with Pillow; (0, None, None) when absent."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            ex = im.getexif()
            rot = EXIF_ROTATION.get(int(ex.get(274, 1) or 1), 0)
            sub = ex.get_ifd(0x8769)
            when = _parse_time(str(sub.get(36867) or sub.get(36868) or ex.get(306) or "") or None)
            if when is not None and when.tzinfo is None:     # phone EXIF is the camera's local time; videos carry UTC
                off = str(sub.get(36881) or sub.get(36880) or "").strip()
                try:
                    when = when.replace(tzinfo=datetime.strptime(off, "%z").tzinfo) if off else when.astimezone()
                except ValueError:
                    when = when.astimezone()
            gps = _exif_gps(dict(ex.get_ifd(0x8825)))
            return rot, when, gps
    except Exception:
        return 0, None, None


def probe(path: str | Path) -> MediaInfo:
    p = Path(path)
    data = ffprobe_json(p)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    tags = {k.lower(): str(v) for k, v in (fmt.get("tags") or {}).items()}
    info = MediaInfo(
        path=str(p),
        size=int(fmt.get("size") or (p.stat().st_size if p.exists() else 0)),
        format_name=fmt.get("format_name", ""),
        duration=float(fmt.get("duration") or 0.0),
        bitrate=int(fmt["bit_rate"]) if fmt.get("bit_rate", "").isdigit() else None,
    )
    ext = p.suffix.lower()
    vstreams = [s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    if vstreams:
        v = vstreams[0]
        info.has_video = True
        info.width, info.height = v.get("width"), v.get("height")
        info.vcodec = v.get("codec_name")
        info.pix_fmt = v.get("pix_fmt")
        avg, rr = _rate(v.get("avg_frame_rate")), _rate(v.get("r_frame_rate"))
        info.fps = avg or rr
        if avg and rr and rr < 1000 and abs(avg - rr) / rr > 0.02:
            info.vfr = True
        rot = 0
        vt = {k.lower(): str(val) for k, val in (v.get("tags") or {}).items()}
        if "rotate" in vt:
            try:
                rot = int(float(vt["rotate"]))
            except ValueError:
                rot = 0
        for sd in v.get("side_data_list") or []:
            if "rotation" in sd:
                try:
                    rot = int(float(sd["rotation"]))
                except (TypeError, ValueError):
                    pass
        info.rotation = rot % 360 if rot >= 0 else (rot % 360)
        tags.update({f"v.{k}": val for k, val in vt.items()})
        if ext in IMAGE_EXT or (info.vcodec in ("mjpeg", "png", "webp", "bmp", "tiff") and info.duration <= 0.05):
            info.is_image = True
        if ext in GIF_EXT:
            info.is_image = info.duration <= 0.05
        if not info.duration:
            info.duration = float(v.get("duration") or 0.0)
    if astreams:
        a = astreams[0]
        info.has_audio = True
        info.acodec = a.get("codec_name")
        info.sample_rate = int(a["sample_rate"]) if a.get("sample_rate") else None
        info.channels = a.get("channels")
        if not info.duration:
            info.duration = float(a.get("duration") or 0.0)
    info.creation_time = _parse_time(tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate") or tags.get("date"))
    info.location = parse_iso6709(
        tags.get("location") or tags.get("com.apple.quicktime.location.iso6709") or tags.get("location-eng")
    )
    if info.is_image and ext in IMAGE_EXT:          # photos keep their story in EXIF: when, where, which way up
        rot, when, gps = photo_exif(p)
        info.rotation = rot or info.rotation
        info.creation_time = info.creation_time or when
        info.location = info.location or gps
    info.tags = {k: v for k, v in tags.items() if len(v) < 300}
    return info
