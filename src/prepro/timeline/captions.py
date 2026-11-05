"""Caption chunking/styling and ASS (libass) subtitle writing for captions + text cards."""

from __future__ import annotations

import functools
import math
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
    "photo": ("Montserrat", 0.044, "&H00FFFFFF", "&H60000000", -1, False),      # words on a photo: a soft edge, not a subtitle box
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
        caps.append(Caption(id=f"cap{i}", t0=round(t0, 3), t1=round(t1, 3), words=ch, style=style, pos="lower"))
    if face_boxes_at is not None and caps:
        _place(caps, face_boxes_at, vertical)
    return caps


# where captions sit (fraction of the frame height, top → bottom), matching write_ass's margins for two lines
ZONES = {True: {"lower": (0.64, 0.77), "upper": (0.19, 0.32)}, False: {"lower": (0.80, 0.93), "upper": (0.10, 0.22)}}


def _covers_mouth(fb, zone) -> bool:
    """A caption zone that reaches up over the mouth/chin (the lower ~30 % of the face) or down over the eyes."""
    if not fb:
        return False
    _x, y, _w, h = fb
    top, bottom = y - h / 2, y + h / 2
    return zone[0] < bottom - 0.22 * h and zone[1] > top + 0.2 * h


def _place(caps: list[Caption], face_at, vertical: bool) -> None:
    """One caption position for the whole video — text that hops above and below the face from cut to cut feels
    jittery. The position that keeps the most captions off the face wins; a caption moves only where it really would
    cover the mouth."""
    z = ZONES[vertical]
    faces = [face_at((c.t0 + c.t1) / 2) for c in caps]
    clash = {p: sum(_covers_mouth(fb, z[p]) for fb in faces) for p in ("lower", "upper")}
    default = "lower" if clash["lower"] <= clash["upper"] else "upper"
    other = "upper" if default == "lower" else "lower"
    for c, fb in zip(caps, faces, strict=True):
        c.pos = other if _covers_mouth(fb, z[default]) and not _covers_mouth(fb, z[other]) else default


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


def balance_lines(text: str, cap: float, measure=len) -> list[str]:
    """On-screen text in as few lines as fit ``cap`` (in ``measure`` units: characters, or pixels with a font), of
    similar length, never ending a line on a glue word ("the", "a", "to"…): "POV: you finally took / the trip you kept
    postponing", not "…took the / trip…"."""
    words = text.split()
    total = measure(text)
    if total <= cap or len(words) < 2:
        return [text]
    found: list[tuple[float, list[str]]] = []
    for n in range(max(2, math.ceil(total / cap)), len(words) + 1):     # fewest lines that fit — or one more, when
        if len(found) == 2 or (found and found[0][0] < 0.1):             # that is what keeps a "the" off a line end
            break
        target = total / n

        def cost(i: int, j: int, target: float = target) -> float:
            w = measure(" ".join(words[i:j]))
            c = ((w - target) / cap) ** 2 + (1e6 if w > cap and j - i > 1 else 0.0)
            if j < len(words) and re.sub(r"[^\w']", "", words[j - 1].lower()) in GLUE:
                c += 0.15
            return c

        memo: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}

        def best(i: int, k: int, cost=cost, memo=memo) -> tuple[float, tuple[int, ...]]:
            if (i, k) not in memo:
                if k == 1:
                    memo[i, k] = (cost(i, len(words)), (len(words),))
                else:
                    memo[i, k] = min(((cost(i, j) + best(j, k - 1)[0], (j, *best(j, k - 1)[1])) for j in range(i + 1, len(words) - k + 2)),
                                     default=(float("inf"), (len(words),)))
            return memo[i, k]

        score, cuts = best(0, n)
        if score < 1e6 or n == len(words):
            out, i = [], 0
            for j in cuts:
                out.append(" ".join(words[i:j]))
                i = j
            found.append((score + 0.1 * len(found), out))
    return min(found, key=lambda x: x[0])[1] if found else words


# libass's drawn width ÷ Pillow's (default instance, basic layout, sized by line height) for the bundled fonts — measured by rendering one
# line through ffmpeg's ass filter (QA log, v0.9); a property of the font files and libass's sizing, not of the machine
LIBASS_WIDTH = {"Montserrat": 0.974, "Anton": 0.872, "Bebas Neue": 0.925, "Playfair Display": 0.952}


@functools.cache
def _font(name: str, bold: bool):
    """The bundled font file for a style (its default instance, whatever the weight: see LIBASS_WIDTH), and its line
    height at size 100 — ASS sizes a font by its line height, so widths are measured on that scale."""
    try:
        from PIL import ImageFont

        from ..config import assets_dir

        files = sorted((assets_dir() / "fonts").glob(name.replace(" ", "") + "*.ttf"))
        if not files:
            return None
        # the font's default instance with Pillow's basic layout: the same widths on every OS (picking a variable
        # font's Bold instance, or raqm layout, depends on how Pillow was built — Linux broke lines differently)
        f = ImageFont.truetype(str(files[0]), 100, layout_engine=ImageFont.Layout.BASIC)
        asc, desc = f.getmetrics()
        return f, asc + desc
    except Exception:
        return None


def text_block(text: str, style: str, W: int, H: int, scale: float = 1.0) -> tuple[list[str], float]:
    """(lines, block height as a fraction of the frame height) for a text item in ``style`` (at ``scale`` × its size):
    the same measure the compiler uses to find room beside a face and the subtitle writer uses to break the lines."""
    name, size, _p, _o, bold, _up = STYLES.get(style, STYLES["clean"])
    vertical = H > W
    fs = H * size * (1.0 if vertical else 0.9) * scale
    side = SAFE["9:16" if vertical else "16:9"][2]
    got = _font(name, bold == -1)
    if got is not None:
        f, line_h = got
        k = fs / line_h * LIBASS_WIDTH.get(name, 0.9) * 1.03     # what libass draws, +3 % to be safe
        measure = lambda s: f.getlength(s) * k                   # noqa: E731
    else:
        measure = lambda s: len(s) * fs * 0.42                   # noqa: E731
    lines = balance_lines(text, W * (1 - 2 * side), measure)
    return lines, len(lines) * fs * 1.22 / H


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
    # a stacked layout (webcam panel on top): top-anchored text starts below the webcam, never over the face
    top = max(top, float(tl.meta.get("layout_top") or 0.0) + 0.02)
    for name, (font, size, prim, outl, bold, _up) in STYLES.items():
        fs = int(H * size * (1.0 if vertical else 0.9))
        outline = max(2, fs // 14)
        shadow, back = max(1, outline // 2), "&H80000000"
        if name == "photo":                                # thin edge + soft drop shadow (blurred in the event)
            outline, shadow, back = max(1, fs // 40), max(2, fs // 16), "&H70000000"
        mv = int(H * bottom) if name not in ("hook", "title", "card") else int(H * top)
        align = 2 if name not in ("hook", "title", "card") else 8
        if name == "card":
            align = 7
            mv = int(H * top)
        lines.append(f"Style: {name},{font},{fs},{prim},&H000000FF,{outl},{back},{bold},0,0,0,100,100,0,0,1,{outline},{shadow},{align},{ml},{ml},{mv},1")
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
    low_caps = [(c.t0, c.t1) for c in tl.captions if c.pos == "lower"]
    cap_block = H * (STYLES["bold"][1] * 2.6 if vertical else STYLES["clean"][1] * 2.4)     # ≈ two caption lines
    for it in tl.items:
        if it.kind != "text" or not it.text:
            continue
        st = it.style if it.style in STYLES else "title"
        txt = _esc(it.text.upper() if STYLES[st][5] else it.text)
        anim = "{\\fad(120,160)\\fscx92\\fscy92\\t(0,140,\\fscx100\\fscy100)}"
        if st == "photo":                                  # words on a photo: balanced lines, a gentle fade, a soft shadow
            sc = it.text_scale or 1.0
            txt = "\\N".join(_esc(x) for x in text_block(it.text, st, W, H, sc)[0])
            fs_tag = f"\\fs{int(H * STYLES[st][1] * (1.0 if vertical else 0.9) * sc)}" if sc < 0.999 else ""
            anim = "{\\fad(180,180)\\blur2" + fs_tag + "}"
        base_y = H * (1 - bottom) - (H * 0.02 if st == "cta" else 0)
        if it.text_y is not None:                          # placed in the free space beside a face
            anim = anim[:-1] + "\\an5\\pos(" + f"{W // 2},{int(H * it.text_y)}" + ")}"
        elif it.position == "center":                     # text on a photo: in the middle, where the eye already is
            anim = anim[:-1] + "\\an5\\pos(" + f"{W // 2},{int(H * 0.46)}" + ")}"
        elif it.position == "upper":
            anim = anim[:-1] + "\\an8\\pos(" + f"{W // 2},{int(H * (top + 0.04))}" + ")}"
        # bottom-anchored text over a caption on screen at the same time goes above it, never on top of it
        elif st not in ("hook", "title", "card") and any(a < it.rec_out and b > it.rec_in for a, b in low_caps):
            anim = anim[:-1] + "\\an2\\pos(" + f"{W // 2},{int(base_y - cap_block)}" + ")}"
        elif st == "cta":
            anim = "{\\fad(150,200)\\an2\\pos(" + f"{W // 2},{int(base_y)}" + ")}"
        lines.append(f"Dialogue: 2,{_ts(it.rec_in)},{_ts(it.rec_out)},{st},,0,0,0,,{anim}{txt}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def items_text(tl: Timeline) -> list[Item]:
    return [i for i in tl.items if i.kind == "text"]
