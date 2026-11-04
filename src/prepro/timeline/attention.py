"""Retention heat strip: a rough per-moment "swipe-away risk" drawn under the timeline.

It is a heuristic, not a prediction. Risk grows the longer nothing changes on screen or in the sound (cut, overlay,
text, punch-in, SFX hit, music change) and is damped while someone is talking. It is stricter in vertical
short-form than in long horizontal videos, and the first seconds count double (the hook)."""

from __future__ import annotations

import math

from ..schema.timeline import Timeline


def change_events(tl: Timeline) -> list[tuple[float, float]]:
    """(time, strength) of every on-screen / sound change."""
    ev: list[tuple[float, float]] = [(0.0, 1.0)]
    for it in tl.items:
        if it.track == "V1":
            ev.append((it.rec_in, 1.0))
            if it.transform and it.transform.zoom > 1.01:
                ev.append((it.rec_in, 0.6))
            if it.transform and it.transform.keys:
                ev += [(it.rec_in + k.t, 0.3) for k in it.transform.keys[1:]]
        elif it.track in ("V2", "V3"):
            ev += [(it.rec_in, 0.9), (it.rec_out, 0.5)]
        elif it.kind == "text":
            ev.append((it.rec_in, 0.7))
        elif it.track == "A3":
            ev.append((it.rec_in, 0.4))
        elif it.track == "A2":
            ev.append((it.rec_in, 0.5))
    ev += [(c.t0, 0.15) for c in tl.captions]
    return sorted(ev)


def attention_curve(tl: Timeline, step: float = 0.5) -> list[float]:
    vertical = tl.height > tl.width
    tau = 2.6 if vertical else (4.0 if tl.duration < 120 else 6.0)
    speech = sorted((i.rec_in, i.rec_out) for i in tl.items if i.track == "A1" and i.role not in ("natural",))
    ev = change_events(tl)
    n = max(1, int(math.ceil(tl.duration / step)))
    out: list[float] = []
    j = 0
    energy = 0.0          # decaying "something just happened" level
    last_t = 0.0
    for k in range(n):
        tc = (k + 0.5) * step
        while j < len(ev) and ev[j][0] <= tc:
            t_e, s_e = ev[j]
            energy = energy * math.exp(-(t_e - last_t) / tau) + s_e
            last_t = t_e
            j += 1
        level = energy * math.exp(-(tc - last_t) / tau)
        risk = 1.0 - min(1.0, level)
        talking = any(a <= tc < b for a, b in speech)
        if talking:
            risk *= 0.6
        if tc < 3.0:                     # the hook: dead air here costs the most
            risk = min(1.0, risk * 1.6)
        out.append(round(max(0.0, min(1.0, risk)), 3))
    return out
