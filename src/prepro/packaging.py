"""Packaging: what a creator needs around the cut before posting.

- thumbnail picks (a big clear face, a peak action moment, a sharp striking shot) + text mock-ups at the right size
  (1280×720 for YouTube, 1080×1920 cover for Shorts/Reels);
- title options built from the hook's numbers, places and promise (≤ 70 characters, no clickbait the video
  can't pay off);
- YouTube chapters (first at 0:00, ≥ 3 chapters, each ≥ 10 s — otherwise none, with the reason);
- a description with hashtags.
Rules-based and offline; an AI connector can be asked for better titles later.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from .brain.basic import text_hook, words_to_digits
from .project import Project
from .schema.analysis import ProjectAnalysis
from .schema.timeline import Timeline


class Thumb(BaseModel):
    path: str                       # relative to the shoot folder
    frame: str                      # the clean frame (no text)
    asset_id: str
    t: float
    why: str
    score: float


class Packaging(BaseModel):
    titles: list[str] = Field(default_factory=list)
    chapters: list[tuple[float, str]] = Field(default_factory=list)
    chapters_note: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    thumbs: list[Thumb] = Field(default_factory=list)
    text_on_thumb: str = ""


def _mmss(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def _hook_text(tl: Timeline, pa: ProjectAnalysis) -> str:
    """The spoken words of the cut's first line."""
    a1 = sorted((i for i in tl.items if i.track == "A1" and i.role not in ("natural",)), key=lambda i: i.rec_in)
    if not a1:
        return ""
    it = a1[0]
    words = [w.text for w in pa.words(it.asset_id) if it.src_in - 0.05 <= w.t0 and w.t1 <= it.src_out + 0.05 and not w.filler and not w.text.startswith("[")]
    return " ".join(words)


def _places(tl: Timeline, pa: ProjectAnalysis) -> list[str]:
    seen: list[str] = []
    for it in sorted(tl.items, key=lambda i: i.rec_in):
        if it.asset_id and it.asset_id in pa.clips:
            p = pa.clips[it.asset_id].place
            if p and p not in seen:
                seen.append(p)
    return seen


def titles(tl: Timeline, pa: ProjectAnalysis) -> list[str]:
    hook = _hook_text(tl, pa)
    digits = words_to_digits(hook).strip().rstrip(".")
    digits = re.sub(r"\b(\d{4,})\b", lambda m: f"{int(m.group(1)):,}", digits)
    digits = re.sub(r"(\d[\d,]*)\s*(rupees|rs|inr)\b", r"₹\1", digits, flags=re.I)
    digits = re.sub(r"(\d[\d,]*)\s*(dollars|bucks)\b", r"$\1", digits, flags=re.I)
    places = _places(tl, pa)
    out: list[str] = []

    def add(t: str) -> None:
        t = re.sub(r"\s+", " ", t).strip(" ,;")
        if t and len(t) <= 70 and t.lower() not in {x.lower() for x in out}:
            out.append(t[0].upper() + t[1:])

    # 1. the hook itself, from its strongest clause (what the video literally promises); never split "5,000" / "2.5"
    clauses = [c.strip() for c in re.split(r",(?!\d)|;|(?<!\d)\.(?!\d)|!|\band\b(?=\s+i\b)", digits) if c.strip()]
    strong = max(clauses, key=lambda c: (bool(re.search(r"[\d₹$]", c)), -abs(len(c.split()) - 8)), default="")
    strong = re.sub(r"^(so|okay|ok|and|today)\s+", "", strong, flags=re.I).strip()
    if strong:
        add(strong)
    # 2. natural rewrites of the same promise (no claims the video can't pay off)
    q = re.match(r"^why (do|does|did|are|is) (.+?)\??$", strong, re.I)
    if q:
        add(f"The real reason {q.group(2)}")
    m = re.match(r"^(\d+) (.+?) mistakes?\b(.*)$", strong, re.I)
    if m:
        add(f"Stop making these {m.group(1)} {m.group(2)} mistakes")
    m = re.match(r"^i (lost|spent|made|tried|quit|built|learned|saved) (.+)$", strong, re.I)
    if m:
        add(f"How I {m.group(1).lower()} {m.group(2)}")
    money = re.search(r"(₹|\$|€|£)\s?[\d,]+", digits)
    days = re.search(r"\b(\d+)\s+(full\s+)?(days?|nights?|hours?|weeks?)\b", digits)
    if len(places) >= 2 and money:
        add(f"{places[0]} → {places[-1]} on {money.group(0)}?")
    if money and days:
        add(f"{days.group(1)} {days.group(3)}" + (f" in {' & '.join(places[:2])}" if places else "") + f" for {money.group(0)}")
    if places and (days or money):
        add(f"{' to '.join(places[:2])}" + (f" in {days.group(1)} {days.group(3)}" if days else "") + (" — what it really costs" if money else ""))
    return out[:5]


FUNCTION_WORDS = {"your", "the", "a", "an", "of", "to", "my", "for", "in", "on", "at", "with", "and", "that", "are", "is", "from", "some", "do",
                  "does", "make", "makes", "get", "gets"}


def thumb_text(hook: str, max_words: int = 6) -> str:
    """Punchy thumbnail words: the number + its noun ("1M views"), then the kicker ("phone camera") — never ending
    on "your"/"the". Without a number: the first content words of the hook."""
    toks = [re.sub(r"^([₹$€£]?)(\d{5,})$", lambda m: m.group(1) + f"{int(m.group(2)):,}", t.strip(",.")) for t in text_hook(hook, max_words=12).rstrip("?!").split()]
    if not toks:
        return ""
    n = next((i for i, t in enumerate(toks) if re.search(r"[\d₹$€£]", t)), None)
    if n is None:
        words = [t for t in toks if t.lower() not in FUNCTION_WORDS][:4]
    else:
        main = toks[n: n + 3]
        while len(main) > 1 and main[-1].lower() in FUNCTION_WORDS:
            main.pop()
        rest = toks[n + len(main):]
        kicker = rest[-3:] if rest else []
        while kicker and kicker[0].lower() in FUNCTION_WORDS:
            kicker.pop(0)
        words = (main + kicker)[:max_words]
    while words and words[-1].lower() in FUNCTION_WORDS:
        words.pop()
    out = " ".join(words)
    return out + ("?" if "?" in hook and out else "")


def chapters(tl: Timeline, pa: ProjectAnalysis) -> tuple[list[tuple[float, str]], str]:
    if tl.duration < 60:
        return [], "no chapters: YouTube needs a video of at least a minute with 3+ chapters"
    starts: dict[str, float] = {}
    for it in sorted(tl.items, key=lambda i: i.rec_in):
        if it.track == "V1" and it.section and it.section not in starts:
            starts[it.section] = it.rec_in
    cards = {round(i.rec_in, 1): i.text for i in tl.items if i.kind == "text" and i.style == "card" and i.text}
    out: list[tuple[float, str]] = []
    for sec, t0 in sorted(starts.items(), key=lambda kv: kv[1]):
        if sec in ("cold_open", "hook", "intro", "open"):
            name = "Intro"
        elif sec in ("outro", "cta", "end"):
            name = "Outro"
        else:
            card = next((txt for tt, txt in cards.items() if abs(tt - t0) < 1.5), None)
            if card:
                name = card
            else:
                a1 = next((i for i in sorted(tl.items, key=lambda i: i.rec_in) if i.track == "A1" and i.rec_in >= t0 - 0.05 and i.role != "natural"), None)
                words = [w.text for w in pa.words(a1.asset_id) if a1.src_in - 0.05 <= w.t0 <= a1.src_out][:6] if a1 else []
                name = " ".join(words).strip(" ,.") or sec.replace("_", " ").title()
        if out and t0 - out[-1][0] < 10:            # YouTube: each chapter ≥ 10 s
            if out[-1][1] == "Intro":               # a short intro folds into the first real chapter
                out[-1] = (out[-1][0], name)
            continue
        out.append((0.0 if not out else round(t0), name))
    if len(out) < 3:
        return [], f"no chapters: only {len(out)} part(s) of 10 s+ (YouTube needs 3)"
    return out, ""


def hashtags(tl: Timeline, pa: ProjectAnalysis) -> list[str]:
    tags: list[str] = []
    by_pb = {"story_vlog": ["vlog", "travelvlog"], "travel_film": ["travel", "cinematic"], "hype_reel": ["reels"], "aesthetic": ["aesthetic"],
             "talking_head": ["tips"], "podcast_clip": ["podcast"], "gaming": ["gaming"], "comedy": ["comedy"], "teaser": []}
    tags += by_pb.get(tl.playbook, [])
    tags += [re.sub(r"\W+", "", p.lower()) for p in _places(tl, pa)[:3]]
    hook = _hook_text(tl, pa).lower()
    if re.search(r"rupees|₹|budget|cheap|cost|spent|money|dollars", hook):
        tags.append("budgettravel" if tl.playbook in ("story_vlog", "travel_film") else "money")
    if tl.height > tl.width and tl.duration <= 60:
        tags.append("shorts")
    out = []
    for t in tags:
        if t and f"#{t}" not in out:
            out.append(f"#{t}")
    return out[:6]


def _frame_candidates(tl: Timeline, pa: ProjectAnalysis) -> list[tuple[float, str, float, str, tuple | None]]:
    """(score, asset_id, source time, why, face box) for frames worth a thumbnail."""
    cands = []
    for it in tl.items:
        if it.track not in ("V1", "V2") or it.kind != "video" or not it.asset_id or it.role == "meme":
            continue
        for sh in pa.clips[it.asset_id].shots:
            if sh.t1 < it.src_in or sh.t0 > it.src_out or set(sh.flags) & {"dark", "blurry", "shaky", "pocket"}:
                continue
            faces = [f for f in sh.faces if it.src_in <= f.t <= it.src_out] or list(sh.faces)
            if faces:
                f = max(faces, key=lambda f: f.w * f.h * f.conf)
                area = f.w * f.h
                sc = 0.45 + min(0.35, area * 3) + 0.2 * sh.quality
                t = min(max(f.t, it.src_in), it.src_out)
                cands.append((sc, it.asset_id, t, "a big, clear face (faces get clicked)", (f.x, f.y, f.w, f.h)))
            if sh.action_peaks:
                t = next((p for p in sh.action_peaks if it.src_in <= p <= it.src_out), None)
                if t is not None:
                    cands.append((0.45 + 0.3 * sh.quality, it.asset_id, t, "the peak action moment", None))
            if not faces:
                mid = min(max((sh.t0 + sh.t1) / 2, it.src_in), it.src_out)
                cands.append((0.3 + 0.4 * sh.quality + 0.2 * (sh.aesthetic or 0), it.asset_id, mid, "a sharp, striking shot", None))
    cands.sort(key=lambda c: -c[0])
    picked, assets, kinds = [], set(), set()
    for rnd in (0, 1):                      # first one of each kind (face / action / scenery), then the rest
        for c in cands:
            if c[1] in assets or (rnd == 0 and c[3] in kinds):
                continue
            picked.append(c)
            assets.add(c[1])
            kinds.add(c[3])
    return picked


def _mockup(frame: Path, out: Path, text: str, size: tuple[int, int], face: tuple | None) -> Path:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont

    from .config import assets_dir

    W, H = size
    im = Image.open(frame).convert("RGB")
    # cover-crop to the target aspect, keeping the face (or the centre) in frame
    s = max(W / im.width, H / im.height)
    im = im.resize((max(W, int(im.width * s)), max(H, int(im.height * s))), Image.LANCZOS)
    cx = int((face[0] if face else 0.5) * im.width)
    cy = int((face[1] if face else 0.45) * im.height)
    if W > H and face:          # landscape: face on one third, text on the other
        cx = int(cx + W * (0.18 if face[0] >= 0.5 else -0.18))
    x0 = min(max(0, cx - W // 2), im.width - W)
    y0 = min(max(0, cy - H // 2), im.height - H)
    im = im.crop((x0, y0, x0 + W, y0 + H))
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.15)).enhance(1.08)
    if text:
        d = ImageDraw.Draw(im)
        font_path = assets_dir() / "fonts" / "Anton-Regular.ttf"
        words = text.upper().split()
        lines = [" ".join(words[:2]), " ".join(words[2:4]), " ".join(words[4:])] if len(words) > 2 else [" ".join(words)]
        lines = [ln for ln in lines if ln]
        size_px = int(H * (0.17 if W > H else 0.085))
        font = ImageFont.truetype(str(font_path), size_px)
        while max(d.textlength(ln, font=font) for ln in lines) > W * (0.5 if W > H and face else 0.9) and size_px > 20:
            size_px = int(size_px * 0.9)
            font = ImageFont.truetype(str(font_path), size_px)
        block_h = len(lines) * int(size_px * 1.05)
        if W > H:
            left = face is None or face[0] >= 0.5
            x = int(W * 0.05) if left else int(W * 0.95)
            anchor = "la" if left else "ra"
            y = (H - block_h) // 2
        else:
            x, anchor, y = W // 2, "ma", int(H * 0.12)
        for k, ln in enumerate(lines):
            fill = (255, 229, 0) if k == len(lines) - 1 else (255, 255, 255)
            d.text((x, y + k * int(size_px * 1.05)), ln, font=font, fill=fill, anchor=anchor, stroke_width=max(3, size_px // 12), stroke_fill=(0, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=90)
    return out


def package(tl: Timeline, pa: ProjectAnalysis, out_dir: Path, *, project_root=None, n_thumbs: int = 3) -> Packaging:
    from .media.proxy import grab_frame

    root = Path(project_root or pa.root)
    proj = Project(root)
    pk = Packaging(titles=titles(tl, pa), hashtags=hashtags(tl, pa))
    pk.chapters, pk.chapters_note = chapters(tl, pa)
    pk.text_on_thumb = thumb_text(_hook_text(tl, pa))
    size = (1080, 1920) if tl.height > tl.width else (1280, 720)
    for k, (sc, aid, t, why, face) in enumerate(_frame_candidates(tl, pa)[:n_thumbs], start=1):
        a = pa.asset(aid)
        frame = grab_frame(proj.path(a.path), t, out_dir / f"frame_{k}.jpg", width=1920)
        mock = _mockup(frame, out_dir / f"thumbnail_{k}.jpg", pk.text_on_thumb, size, face)
        pk.thumbs.append(Thumb(path=str(mock.relative_to(root)) if mock.is_relative_to(root) else str(mock),
                               frame=str(frame.relative_to(root)) if frame.is_relative_to(root) else str(frame),
                               asset_id=aid, t=round(t, 2), why=why, score=round(sc, 3)))
    lines = [pk.titles[0] if pk.titles else tl.name, ""]
    places = _places(tl, pa)
    if places:
        lines.append(f"Filmed in {', '.join(places)}.")
    if pk.chapters:
        lines += ["", "Chapters"] + [f"{_mmss(t)} {name}" for t, name in pk.chapters]
    if pk.hashtags:
        lines += ["", " ".join(pk.hashtags)]
    pk.description = "\n".join(lines).strip()
    md = ["# Packaging — " + tl.name, "", "## Title options"] + [f"{i}. {t}" for i, t in enumerate(pk.titles, 1)]
    md += ["", "## Thumbnail text", pk.text_on_thumb or "(none)", "", "## Thumbnails"]
    md += [f"- `{Path(t.path).name}` — {t.why} ({t.asset_id} at {t.t:.1f} s)" for t in pk.thumbs]
    md += ["", "## Chapters"] + ([f"{_mmss(t)} {name}" for t, name in pk.chapters] or [pk.chapters_note])
    md += ["", "## Description", "```", pk.description, "```"]
    (out_dir / "packaging.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    proj.save_model(f"timelines/{tl.id}.package.json", pk)
    return pk
