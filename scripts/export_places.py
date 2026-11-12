"""The desktop's offline place names, packed for the iPhone app.

The desktop names a place from a photo's GPS with ``reverse_geocoder`` (analyze/context.py ``place_name``): the city
from GeoNames' cities1000 list (CC BY 4.0, geonames.org) whose (lat, lon) is nearest in plain degrees, its name, else
its region. The iPhone looks places up offline the same way (PreProCore Photos/Places.swift), from this file:

    "PPL1", n (uint32), lat × n (int32, 1/100000 degree), lon × n (int32), then the n names, one per line (UTF-8)

Every coordinate in the list is a whole number of 1/100000 degrees, so the phone reads back exactly the doubles the
desktop parses. Where two cities share one coordinate, the desktop's k-d tree always answers with the same one of them:
that one is kept, so the phone's nearest-city search gives the desktop's answer. Run on the Mac before building the app
(.github/workflows/ios.yml) with reverse_geocoder 1.5.1:

    python scripts/export_places.py ios/PreProCore/Sources/PreProCore/Resources/places.bin
"""

from __future__ import annotations

import csv
import struct
import sys
from array import array
from pathlib import Path


def rows() -> list[dict]:
    import reverse_geocoder as rg

    src = Path(rg.__file__).with_name("rg_cities1000.csv")
    with src.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def tie_winners(table: list[dict]) -> set[int]:
    """Row indices that lose to another row at the very same coordinate (the desktop never answers with them)."""
    import reverse_geocoder as rg

    groups: dict[tuple[str, str], list[int]] = {}
    for i, r in enumerate(table):
        groups.setdefault((r["lat"], r["lon"]), []).append(i)
    ties = [(k, v) for k, v in groups.items() if len(v) > 1]
    if not ties:
        return set()
    won = rg.search([(float(a), float(b)) for (a, b), _ in ties], mode=1, verbose=False)
    lose: set[int] = set()
    for (_, idx), w in zip(ties, won, strict=True):
        winner = next(i for i in idx if all(table[i][c] == w[c] for c in ("name", "admin1", "admin2", "cc")))
        lose |= {i for i in idx if i != winner}
    return lose


def pack(table: list[dict], drop: set[int]) -> bytes:
    lat, lon, names = array("i"), array("i"), []
    for i, r in enumerate(table):
        if i in drop:
            continue
        a, b = round(float(r["lat"]) * 100000), round(float(r["lon"]) * 100000)
        assert a / 100000 == float(r["lat"]) and b / 100000 == float(r["lon"]), r      # exact on the phone too
        name = r["name"] or r["admin1"]                                                   # place_name's answer
        assert "\n" not in name
        lat.append(a)
        lon.append(b)
        names.append(name)
    if sys.byteorder != "little":
        lat.byteswap()
        lon.byteswap()
    return struct.pack("<4sI", b"PPL1", len(names)) + lat.tobytes() + lon.tobytes() + "\n".join(names).encode("utf-8")


def main(out: str) -> None:
    table = rows()
    drop = tie_winners(table)
    data = pack(table, drop)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(data)
    print(f"{len(table) - len(drop)} places ({len(drop)} same-coordinate twins left out), {len(data) / 1e6:.1f} MB -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ios/PreProCore/Sources/PreProCore/Resources/places.bin")
