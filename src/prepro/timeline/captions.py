"""Caption chunking/styling and ASS (libass) subtitle writing for captions + text cards."""

from __future__ import annotations

import re
from pathlib import Path

from ..schema.timeline import Caption, CaptionWord, Item, Timeline

SAFE = {  # (top, bottom, side) margins as fraction of height/width — platform UI overlays
    "9:16": (0.13, 0.24, 0.08),
    "16:9": (0.06, 0.08, 0.05),
}

STYLES = {
    # name: (font, size as fraction of height, primary, outline, bold, uppercase)
    "clean": ("Montserrat", 0.040, "&H00FFFFFF", "&H00000000", -1, False),
    "bold": ("Montserrat", 0.052, "&H00FFFFFF", "&H00000000", -1, True),
    "big": ("Anton", 0.075, "&H0000E5FF", "&H00000000", 0, True),
    "small": ("Montserrat", 0.030, "&H00E0E0E0", "&H00000000", 0, False),
    "hook": ("Anton", 0.068, "&H00FFFFFF", "&H00000000", 0, True),
    "card": ("Bebas Neue", 0.070, "&H00FFFFFF", "&H00000000", 0, True),
    "title": ("Bebas Neue", 0.090, "&H00FFFFFF", "&H00000000", 0, True),
    "cta": ("Poppins", 0.058, "&H00FFFFFF", "&H00000000", -1, True),
    "callout": ("Anton", 0.060, "&H0000E5FF", "&H00000000", 0, True),
    "aesthetic": ("Playfair Display", 0.036, "&H00FFFFFF", "&H40000000", 0, False),
    "devanagari": ("Noto Sans Devanagari", 0.046, "&H00FFFFFF", "&H00000000", -1, False),
}


GLUE = {"the", "a", "an", "my", "your", "his", "her", "our", "their", "its", "to", "of", "in", "on", "at", "for", "with", "from",
        "and", "but", "or", "so", "is", "are", "was", "were", "i", "we", "let", "this", "that", "very", "too", "not", "no"}
CLAUSE = {"how", "what", "where", "when", "why", "because", "which", "who", "and", "but", "so", "if", "then"}


def _w(x: CaptionWord) -> str:
    return re.sub(r"[^\w']", "", x.text.lower())


def chunk_words(words: list[CaptionWord], *, min_w: int, max_w: int, max_gap: float = 0.6, max_chars: int = 32) -> list[list[CaptionWord]]:
    """Group words into caption chunks at natural phrase boundaries (never end on 'the/to/my…',
    prefer breaking before 'how/where/because…', no single-word orphans at sentence ends)."""
    chunks: list[list[CaptionWord]] = []
    cur: list[CaptionWord] = []
    n = len(words)
    for i, w in enumerate(words):
        if cur:
            gap = w.t0 - cur[-1].t1
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            end_punct = bool(re.search(r"[.!?।,]$", cur[-1].text))
            full = len(cur) >= max_w or chars > max_chars
            soft = _w(w) in CLAUSE and len(cur) >= (2 if max_w <= 4 else min_w + 1)
            # orphan guard: if only one word of this sentence is left, keep it with the current chunk
            rest_one = (i + 1 == n or re.search(r"[.!?।]$", w.text)) and len(cur) <= max_w and chars <= max_chars + 4
            if gap > max_gap or (end_punct and len(cur) >= min_w) or soft or (full and not (rest_one and re.search(r"[.!?।]$", w.text))):
                if len(cur) > 1 and _w(cur[-1]) in GLUE and gap <= max_gap and not end_punct:
                    carry = cur.pop()
                    chunks.append(cur)
                    cur = [carry]
                else:
                    chunks.append(cur)
                    cur = []
        cur.append(w)
    if cur:
        merged_chars = sum(len(x.text) + 1 for x in chunks[-1] + cur) if chunks else 0
        if chunks and len(cur) < min_w and cur[0].t0 - chunks[-1][-1].t1 < 0.3 and len(chunks[-1]) + len(cur) <= max_w + 1 and merged_chars <= max_chars + 2:
            chunks[-1].extend(cur)
        else:
            chunks.append(cur)
    return chunks


def build_captions(words: list[CaptionWord], *, style: str, words_range: tuple[int, int], vertical: bool,
                   face_boxes_at=None) -> list[Caption]:
    if style == "off" or not words:
        return []
    lo, hi = words_range
    if style == "bold":
        lo, hi = (1, min(hi, 3)) if vertical else (2, 5)
    chunks = chunk_words(words, min_w=lo, max_w=hi, max_chars=22 if vertical else 40)
    caps = []
    for i, ch in enumerate(chunks):
        t0, t1 = ch[0].t0, ch[-1].t1 + 0.12
        if i + 1 < len(chunks):
            t1 = min(t1, chunks[i + 1][0].t0 - 0.02)
        t1 = max(t1, t0 + 0.35)
        pos = "lower"
        if face_boxes_at is not None:
            fb = face_boxes_at((t0 + t1) / 2)
            if fb and fb[1] + fb[3] / 2 > (0.62 if vertical else 0.72):
                pos = "upper"
        caps.append(Caption(id=f"cap{i}", t0=round(t0, 3), t1=round(t1, 3), words=ch, style=style, pos=pos))
    return caps


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def _has_devanagari(s: str) -> bool:
    return bool(re.search(r"[ऀ-ॿ]", s))


def write_ass(tl: Timeline, path: Path, *, word_highlight: bool = True) -> Path:
    W, H = tl.width, tl.height
    vertical = H > W
    top, bottom, side = SAFE["9:16" if vertical else "16:9"]
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    ml = int(W * side)
    for name, (font, size, prim, outl, bold, _up) in STYLES.items():
        fs = int(H * size * (1.0 if vertical else 0.9))
        outline = max(2, fs // 14)
        mv = int(H * bottom) if name not in ("hook", "title", "card") else int(H * top)
        align = 2 if name not in ("hook", "title", "card") else 8
        if name == "card":
            align = 7
            mv = int(H * top)
        lines.append(f"Style: {name},{font},{fs},{prim},&H000000FF,{outl},&H80000000,{bold},0,0,0,100,100,0,0,1,{outline},{max(1, outline // 2)},{align},{ml},{ml},{mv},1")
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    upper_mv = int(H * (top + 0.06))
    for c in tl.captions:
        base = "devanagari" if _has_devanagari(c.text) else c.style if c.style in STYLES else "clean"
        upcase = STYLES.get(base, STYLES["clean"])[5]
        mv = f"{upper_mv}" if c.pos == "upper" else "0"
        an = "{\\an8}" if c.pos == "upper" else ""
        pop = "{\\fscx88\\fscy88\\t(0,90,\\fscx104\\fscy104)\\t(90,160,\\fscx100\\fscy100)}" if base in ("bold",) else "{\\fad(60,60)}"

        def word_txt(w: CaptionWord, active: bool, upcase: bool = upcase, base: str = base) -> str:
            t = _esc(w.text.upper() if upcase else w.text)
            if w.emph:
                big = STYLES["big"]
                return "{\\fn" + big[0] + "\\fs" + str(int(H * big[1] * (1.0 if vertical else 0.9))) + "\\c" + big[2] + "&}" + t + "{\\r}"
            if active and word_highlight and base == "bold":
                return "{\\c&H0000E5FF&}" + t + "{\\r}"
            return t

        if word_highlight and base == "bold" and len(c.words) > 1:
            for k, w in enumerate(c.words):
                t0 = w.t0 if k else c.t0
                t1 = c.words[k + 1].t0 if k + 1 < len(c.words) else c.t1
                txt = " ".join(word_txt(x, x is w) for x in c.words)
                lines.append(f"Dialogue: 1,{_ts(t0)},{_ts(t1)},{base},,0,0,{mv},,{an}{pop if k == 0 else ''}{txt}")
        else:
            txt = " ".join(word_txt(x, False) for x in c.words)
            lines.append(f"Dialogue: 1,{_ts(c.t0)},{_ts(c.t1)},{base},,0,0,{mv},,{an}{pop}{txt}")
    for it in tl.items:
        if it.kind != "text" or not it.text:
            continue
        st = it.style if it.style in STYLES else "title"
        txt = _esc(it.text.upper() if STYLES[st][5] else it.text)
        anim = "{\\fad(120,160)\\fscx92\\fscy92\\t(0,140,\\fscx100\\fscy100)}"
        if st == "cta":
            anim = "{\\fad(150,200)\\an2\\pos(" + f"{W // 2},{int(H * (1 - SAFE['9:16' if vertical else '16:9'][1]) - H * 0.02)}" + ")}"
        lines.append(f"Dialogue: 2,{_ts(it.rec_in)},{_ts(it.rec_out)},{st},,0,0,0,,{anim}{txt}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def items_text(tl: Timeline) -> list[Item]:
    return [i for i in tl.items if i.kind == "text"]
