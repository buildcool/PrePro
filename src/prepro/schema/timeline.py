"""Timeline model — the compiled, frame-exact edit (what gets rendered and exported).

Tracks follow NLE conventions:
  V1 main picture (A-roll / montage), V2 B-roll & cutaways, V3 memes/stickers/overlays, T1 text cards
  A1 dialogue/natural sound, A2 music, A3 SFX, A4 ambience/memes audio
Video and its own audio are separate, linked items (``link``) so J/L cuts are just different in/out
points — exactly how Premiere/Resolve represent them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ItemKind = Literal["video", "audio", "image", "text", "color"]
SuggestionStatus = Literal["applied", "optional", "rejected"]


class TransformKey(BaseModel):
    t: float                          # seconds from item start (timeline time)
    cx: float = 0.5                   # crop centre in source, normalised
    cy: float = 0.5
    zoom: float = 1.0                 # 1 = fill output frame; 1.15 = punch-in


class Transform(BaseModel):
    cx: float = 0.5
    cy: float = 0.5
    zoom: float = 1.0
    keys: list[TransformKey] = Field(default_factory=list)
    fit: bool = False                 # photos: the whole picture on a soft blurred copy of itself (a group photo is never cut)

    @property
    def is_identity(self) -> bool:
        return not self.keys and abs(self.zoom - 1) < 1e-3 and abs(self.cx - 0.5) < 1e-3 and abs(self.cy - 0.5) < 1e-3

    def at(self, t: float) -> tuple[float, float, float]:
        """(cx, cy, zoom) at item time t: straight lines between keys, held before the first and after the last."""
        ks = self.keys
        if not ks:
            return self.cx, self.cy, self.zoom
        if t <= ks[0].t:
            return ks[0].cx, ks[0].cy, ks[0].zoom
        for a, b in zip(ks, ks[1:], strict=False):
            if t <= b.t:
                f = (t - a.t) / max(b.t - a.t, 1e-6)
                return a.cx + (b.cx - a.cx) * f, a.cy + (b.cy - a.cy) * f, a.zoom + (b.zoom - a.zoom) * f
        return ks[-1].cx, ks[-1].cy, ks[-1].zoom


class Item(BaseModel):
    id: str
    ref: str | None = None            # story ref (segment/shot id) or effect key this item came from
    track: str
    kind: ItemKind
    asset_id: str | None = None
    src_in: float = 0.0
    src_out: float = 0.0
    rec_in: float = 0.0
    speed: float = 1.0
    link: str | None = None
    transform: Transform | None = None
    # where the picture goes in the output frame, (x, y, w, h) normalised — a panel of a layout (facecam on top,
    # gameplay below); None = the whole frame. The crop (transform) is taken at the panel's shape.
    place: tuple[float, float, float, float] | None = None
    gain_db: float = 0.0
    envelope: list[tuple[float, float]] = Field(default_factory=list)  # (timeline t, gain dB) e.g. ducking
    fade_in: float = 0.0
    fade_out: float = 0.0
    transition_in: str = "cut"        # cut|dissolve|whip|zoom|fade_black|slide
    transition_dur: float = 0.0
    text: str | None = None
    style: str | None = None
    position: str | None = None
    text_y: float | None = None       # text: centre height (0..1) when placed in the free space beside a face
    text_scale: float | None = None   # text: size relative to its style, when set smaller to fit the space beside a face
    duration: float | None = None     # for text/image/color items
    role: str | None = None
    section: str | None = None
    look: str | None = None
    suggestion_ids: list[str] = Field(default_factory=list)
    note: str = ""

    @property
    def rec_dur(self) -> float:
        if self.kind in ("text", "image", "color") and self.duration is not None:
            return self.duration
        return max(0.0, (self.src_out - self.src_in) / max(self.speed, 1e-6))

    @property
    def rec_out(self) -> float:
        return self.rec_in + self.rec_dur


class CaptionWord(BaseModel):
    text: str
    t0: float
    t1: float
    emph: bool = False


class Caption(BaseModel):
    id: str
    t0: float
    t1: float
    words: list[CaptionWord]
    style: str = "normal"             # normal|big|small|title|hook
    pos: str = "lower"                # lower|center|upper (resolved against safe zones)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


class Marker(BaseModel):
    t: float
    name: str
    note: str = ""
    color: str = "blue"
    suggestion_id: str | None = None


class Suggestion(BaseModel):
    id: str                           # "sg12"
    type: str                         # cut|retake|filler|silence|zoom|sfx|meme|music|speed|transition|broll|text|caption|look|vo|gap|bleep|hook|reorder
    status: SuggestionStatus = "applied"
    confidence: float = 0.8
    reason: str
    source: str = "rules"             # rules|ai|brief|critic|lint|user
    t: float | None = None            # timeline time it relates to
    item_ids: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    alternatives: list[str] = Field(default_factory=list)
    lint: list[str] = Field(default_factory=list)


class MusicSpan(BaseModel):
    t0: float
    t1: float
    mode: str                         # bed|front|light|none
    section: str = ""


class Timeline(BaseModel):
    id: str
    name: str
    direction_id: str
    playbook: str
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    items: list[Item] = Field(default_factory=list)
    captions: list[Caption] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    music_spans: list[MusicSpan] = Field(default_factory=list)
    look: str | None = None
    meta: dict = Field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max((i.rec_out for i in self.items if i.track.startswith(("V", "A", "T"))), default=0.0)

    @property
    def aspect(self) -> str:
        if self.height > self.width:
            return "9:16" if abs(self.width / self.height - 9 / 16) < 0.02 else f"{self.width}:{self.height}"
        return "16:9" if abs(self.width / self.height - 16 / 9) < 0.02 else f"{self.width}:{self.height}"

    def track(self, name: str) -> list[Item]:
        return sorted((i for i in self.items if i.track == name), key=lambda i: i.rec_in)

    def tracks(self) -> list[str]:
        order = {"V": 0, "T": 1, "A": 2}
        return sorted({i.track for i in self.items}, key=lambda t: (order.get(t[0], 9), t))

    def suggestion(self, sid: str) -> Suggestion:
        for s in self.suggestions:
            if s.id == sid:
                return s
        raise KeyError(sid)
