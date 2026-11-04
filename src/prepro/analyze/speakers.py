"""Who says each line in a multi-person shot (podcast or interview two-shot).

The visual analysis finds the seats (people sitting still) and how much each seat's mouth moves, with the head's
own movement subtracted. A line belongs to the seat whose mouth moves clearly more than usual while it is spoken.
Unclear lines (both talking, a face turned away, a very short "yeah") get no speaker rather than a guess; the editor
then holds the framing it already has instead of cutting to someone at random.
"""

from __future__ import annotations

import numpy as np

from ..schema.analysis import ClipAnalysis

SERIES_HZ = 4.0          # the analysis frame rate the mouth series is sampled at
MIN_SCORE = 1.25         # the speaker's mouth moves at least this much more than its own typical level…
MIN_MARGIN = 1.5         # …and this much more than anyone else's


def assign_speakers(ca: ClipAnalysis) -> int:
    """Fill ``speaker`` / ``speaker_conf`` on the clip's lines. Returns how many lines got a speaker."""
    if not ca.transcript:
        return 0
    n = 0
    for seg in ca.transcript.segments:
        seg.speaker, seg.speaker_conf = None, 0.0
        mid = (seg.t0 + seg.t1) / 2
        sh = next((s for s in ca.shots if s.t0 <= mid <= s.t1 and len(s.seats) >= 2 and len(s.mouth) == len(s.seats)), None)
        if sh is None:
            continue
        scores = []
        for series in sh.mouth:
            arr = np.asarray(series, dtype=np.float32)
            i0 = max(0, int((seg.t0 - sh.t0) * SERIES_HZ))
            i1 = min(len(arr), int(np.ceil((seg.t1 - sh.t0) * SERIES_HZ)) + 1)
            if arr.size < 4 or i1 - i0 < 2:
                scores.append(0.0)
                continue
            typical = float(np.median(arr)) + 0.5              # + a floor so a perfectly still face isn't divided by ~0
            scores.append(float(arr[i0:i1].mean()) / typical)
        order = sorted(range(len(scores)), key=lambda k: -scores[k])
        best, second = scores[order[0]], scores[order[1]]
        if best >= MIN_SCORE and best >= MIN_MARGIN * max(second, 0.2):
            seg.speaker = order[0]
            seg.speaker_conf = round(min(1.0, (best - second) / best), 2)
            n += 1
    _untangle_retakes(ca)
    return n


def _untangle_retakes(ca: ClipAnalysis) -> None:
    """A retake is the same person saying a line again. When the "retakes" were said by different people it is a
    reply that echoes the words ("…I almost did not upload." → "Wait, you almost did not upload it?"): keep both."""
    groups: dict[str, list] = {}
    for s in ca.transcript.segments:
        if s.retake_group:
            groups.setdefault(s.retake_group, []).append(s)
    for members in groups.values():
        if len({s.speaker for s in members if s.speaker is not None}) >= 2:
            for s in members:
                s.retake_group, s.retake_rank, s.false_start = None, 0, False
                s.tags = [t for t in s.tags if t != "false_start"]
