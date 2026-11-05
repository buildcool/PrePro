"""Read creator briefs (brief.md / .txt / .yaml / voice note, filename tags, UI form) and parse common
instructions into hard rules + preferences without any AI. Free text the rules can't understand is kept
in ``raw_text`` for an AI brief parser (when a connector is enabled).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..schema.brief import CreatorBrief, HardRule, Preferences

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
             "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90}

PLAYBOOK_WORDS = [
    (r"\bteaser|trailer|promo\b", "teaser"),
    (r"\bcinematic\b|travel film|film\b", "travel_film"),
    (r"\bhype\b|velocity|beat[- ]?sync|montage reel|edit reel", "hype_reel"),
    (r"\baesthetic|cozy|cosy|grwm|get ready with me|cooking|recipe|day in (my|the) life|morning routine|asmr", "aesthetic"),
    (r"\bpodcast\b", "podcast_clip"),
    (r"\bgaming|gameplay|stream highlights", "gaming"),
    (r"\bcomedy|skit|funny video|prank", "comedy"),
    (r"\btutorial|tips|explainer|talking head|educational", "talking_head"),
    (r"\bvlog|story\b|travel vlog|trip vlog", "story_vlog"),
]
LOOKS = ["warm", "cinematic", "teal orange", "teal-orange", "pastel", "black and white", "b&w", "vintage", "moody", "punchy", "natural"]
SFX_NAMES = r"(vine boom|boom|whoosh|swoosh|pop|ding|riser|laugh(?:ter)?|record scratch|scratch|impact|click|airhorn)"


def _num(tok: str) -> float | None:
    tok = tok.lower().strip()
    if tok.replace(".", "", 1).isdigit():
        return float(tok)
    return float(NUM_WORDS[tok]) if tok in NUM_WORDS else None


def _clean(s: str) -> str:
    return s.strip().strip(".!,;:'\"“”‘’ ").strip()


TEXT_BLOCK = re.compile(r"^(?:on[- ]screen\s+)?(?:text|lines|words|text on (?:the )?(?:photo|photos|picture|video|reel))\s*:\s*(.*)$", re.I)
KEY_LINE = re.compile(r"^[A-Za-z][\w ]{0,24}:\s")
TEXT_LIKE = re.compile(r"^(pov|me when|when you|that one|tell me)\b", re.I)


def _text_lines(raw: str) -> tuple[list[str], str]:
    """The creator's own on-screen lines, in order, and the rest of the brief. A "Text:" (or "Lines:") block — one
    line each, until a blank line or another "Key:" line — plus any "POV: …" line or a line in quotes."""
    out, rest, block = [], [], False
    for ln in raw.splitlines():
        s = ln.strip()
        m = TEXT_BLOCK.match(s)
        if m:
            block = True
            if _clean(m.group(1)):
                out.append(m.group(1).strip().strip("\"“”"))
            continue
        if block:
            if not s:
                block = False
                continue
            if not (KEY_LINE.match(s) and not TEXT_LIKE.match(s)):
                out.append(s.strip(" -•*\t").strip("\"“”").strip())
                continue
            block = False
        if TEXT_LIKE.match(s) or (len(s) > 2 and s[0] in "\"“" and s[-1] in "\"”"):
            out.append(s.strip("\"“”").strip())
            continue
        rest.append(ln)
    return [x for x in out if x], "\n".join(rest)


def parse_text(text: str, brief: CreatorBrief | None = None) -> CreatorBrief:
    b = brief or CreatorBrief()
    p = b.prefs
    raw = text.strip()
    if not raw:
        return b
    b.raw_text = (b.raw_text + "\n" + raw).strip()
    lines, raw = _text_lines(raw)
    for k, t in enumerate(lines):
        b.rules.append(HardRule(kind="text_line", target=t, value=k, source=t))
    for line in re.split(r"[\n]+|(?<=[.!?])\s+(?=[A-Z])", raw):
        line = line.strip(" -•*\t")
        if not line:
            continue
        low = line.lower()
        src = line
        # ---------- format / platform / length
        if re.search(r"\b(insta(gram)?|ig)\b.*\breels?\b|\breels?\b|\bshorts?\b|tiktok|vertical", low):
            p.aspect = p.aspect or "9:16"
        if re.search(r"\byoutube\b(?!.*shorts?)|horizontal|landscape|16[:x]9", low) and not re.search(r"shorts?", low):
            p.aspect = p.aspect or "16:9"
        m = re.search(r"\b(\d+(?:\.\d+)?|" + "|".join(NUM_WORDS) + r")\s*[- ]?(s|sec|secs|second|seconds|min|mins|minute|minutes)\b", low)
        if m and not re.search(r"slow|speed", low):
            v = _num(m.group(1))
            if v:
                secs = v * (60 if m.group(2).startswith("m") else 1)
                if re.search(r"\b(under|max(imum)?|at most|less than|no longer than)\b", low):
                    b.rules.append(HardRule(kind="max_length", value=secs, source=src))
                elif re.search(r"\b(at least|min(imum)?|longer than)\b", low):
                    b.rules.append(HardRule(kind="min_length", value=secs, source=src))
                else:
                    p.target_length = secs
        for pat, pb in PLAYBOOK_WORDS:
            if re.search(pat, low) and not p.playbook:
                p.playbook = pb
                break
        m = re.search(r"\b(and|plus|also)\s+(\d+|two|three|four)\s+(reels|shorts|clips)\b", low)
        if m:
            p.deliverables.append(f"{int(_num(m.group(2)) or 2)}x short")
        # ---------- hook
        m = re.search(r"\bhook\b\s*(?:mein|me|:|-|should be|is)?\s*(?:use|start with|with)?\s*(?:the (?:line|part|bit|moment) (?:where|when) i (?:say|said|talk about)|when i say|where i say)?\s*(.+)", line, re.I)
        if m and len(_clean(m.group(1))) > 2:
            b.rules.append(HardRule(kind="hook", anchor=_clean(re.sub(r"^(the )?(line|part)\s+", "", _clean(m.group(1)), flags=re.I)), source=src))
        # ---------- music
        if re.search(r"\bno music\b.*\b(talk|speak|bol)|music\b.*\b(nahi|mat)\b.*\b(bol|talk)|\bno music (while|when)", low):
            b.rules.append(HardRule(kind="no_music_under_speech", source=src))
        elif re.search(r"\bno (background )?music\b|without music|music (nahi|mat)", low):
            b.rules.append(HardRule(kind="no_effect", target="music", source=src))
        if re.search(r"(add|use|put).*(trending|in[- ]app).*(audio|music|song)|(audio|music|song).*(in|on) (insta(gram)?|the app)\b", low):
            b.rules.append(HardRule(kind="no_effect", target="music", arg={"in_app": True}, source=src))
        m = re.search(r"\buse (?:the )?['\"“]?([\w\- .]+?)['\"”]? (?:song|track|music|beat|audio)(?: for (?:the )?(\w+))?", line, re.I)
        if m:
            b.rules.append(HardRule(kind="use_music", target=_clean(m.group(1)), anchor=(m.group(2) or "all").lower(), source=src))
        # ---------- text
        m = re.search(r"\b(?:add|put|show|write)\s+(?:a\s+)?(?:text|title|caption|card)(?:\s+(?:at|in)\s+the\s+(end|start|beginning|intro|outro))?\s*[:\-–]\s*(.+)", line, re.I)
        if m:
            where = (m.group(1) or "end").lower().replace("beginning", "start").replace("intro", "start").replace("outro", "end")
            b.rules.append(HardRule(kind="add_text", target=_clean(m.group(2)), anchor=where, source=src))
        m = re.search(r"\b(?:end|last)\s+(?:mein|me|par)\s+(?:text|likho)\s*[:\-–]?\s*(.+?)\s*(?:daalo|likho|lagao)?$", line, re.I)
        if m:
            b.rules.append(HardRule(kind="add_text", target=_clean(m.group(1)), anchor="end", source=src))
        # ---------- memes / sfx
        m = re.search(r"\badd (?:a |an |the )?([\w\- ]*?)\s*meme (?:after|when|where|at) (?:i say |i said |the )?(.+)", line, re.I)
        if m:
            b.rules.append(HardRule(kind="add_meme", target=_clean(m.group(1)), anchor=_clean(m.group(2)), source=src))
        if re.search(r"\bno memes?\b|without memes|memes? (nahi|mat)", low):
            b.rules.append(HardRule(kind="no_effect", target="meme", source=src))
        m = re.search(r"\badd (?:a |an |the )?" + SFX_NAMES + r"(?: sound| sfx| effect)? (?:on|at|after|when|where) (?:i say |the )?(.+)", line, re.I)
        if m:
            b.rules.append(HardRule(kind="add_sfx", target=m.group(1).lower(), anchor=_clean(m.group(2)), source=src))
        # ---------- effects
        if re.search(r"\bno zooms?\b|without zoom|zoom (mat|nahi)|don'?t zoom", low):
            b.rules.append(HardRule(kind="no_effect", target="zoom", source=src))
        if re.search(r"\bno transitions?\b|only hard cuts|no fancy transitions", low):
            b.rules.append(HardRule(kind="no_effect", target="transition", source=src))
        if re.search(r"\bno (sound effects|sfx)\b|without (sfx|sound effects)", low):
            b.rules.append(HardRule(kind="no_effect", target="sfx", source=src))
        if re.search(r"\bno captions?\b|without captions|no subtitles", low):
            b.rules.append(HardRule(kind="captions", value="off", source=src))
            p.captions = "off"
        elif re.search(r"\b(bold|big|hormozi|word[- ]by[- ]word)\s+(captions?|subtitles)", low):
            p.captions = "bold"
        elif re.search(r"\b(minimal|clean|small|simple)\s+(captions?|subtitles)", low):
            p.captions = "clean"
        m = re.search(r"\b(?:captions?|subtitles)\b.*\b(hindi|hinglish|english)\b|\b(hindi|hinglish|english)\s+(?:captions?|subtitles)", low)
        if m:
            p.caption_lang = (m.group(1) or m.group(2)).lower()
        m = re.search(r"\bslow[- ]?mo(?:tion)?\b\s*(?:on|for|of|at)?\s*(?:the\s+)?(.+)", line, re.I)
        if m and len(_clean(m.group(1))) > 1:
            b.rules.append(HardRule(kind="speed", anchor=_clean(m.group(1)), value=0.5, source=src))
        m = re.search(r"\b(?:speed up|fast[- ]forward|timelapse|time[- ]lapse)\s+(?:the\s+)?(.+)", line, re.I)
        if m:
            b.rules.append(HardRule(kind="speed", anchor=_clean(m.group(1)), value=4.0 if "lapse" in low else 2.0, source=src))
        # ---------- exclusions / inclusions
        m = re.search(r"\b(?:don'?t|do not|dont|never|mat)\s+(?:use|show|include|put)\s+(?:the\s+|my\s+)?(.+?)(?:\s+(?:clip|shot|part|scene|video))?\s*$", line, re.I)
        if m and not re.search(r"zoom|meme|music|transition|caption|sfx|sound effect", m.group(1), re.I):
            b.rules.append(HardRule(kind="must_exclude", anchor=_clean(m.group(1)), source=src))
        m = re.search(r"\bcut (?:out )?(?:the part (?:where|when) i (?:talk about|say|mention)\s+)(.+)", line, re.I)
        if m:
            b.rules.append(HardRule(kind="must_exclude", anchor=_clean(m.group(1)), source=src))
        m = re.search(r"\b(?:must|definitely|make sure to|please)\s+(?:include|use|show|keep)\s+(?:the\s+)?(.+)", line, re.I)
        if m:
            b.rules.append(HardRule(kind="must_include", anchor=_clean(m.group(1)), source=src))
        if re.search(r"\bno (swearing|cursing|bad words|gaali|gali|abuses?)\b|family[- ]friendly|bleep", low):
            b.rules.append(HardRule(kind="no_profanity", source=src))
        # ---------- feel
        if re.search(r"\bfast[- ]paced|\bfast\b|energetic|high energy|punchy", low):
            p.pace = 0.8
        elif re.search(r"\bslow[- ]paced|\bcalm\b|relaxed|chill|soothing", low) and "slow-mo" not in low and "slow mo" not in low:
            p.pace = 0.25
        if re.search(r"\b(minimal|clean|simple|subtle)\b(?!.*captions?)", low):
            p.effects = "clean"
        elif re.search(r"\b(bold|crazy|lots of effects|heavy edit)\b", low):
            p.effects = "bold"
        if re.search(r"\bfunny|humou?r|memes?\b", low) and not re.search(r"no memes?", low):
            p.humour = "heavy" if re.search(r"lots of memes|very funny|meme[- ]heavy", low) else "light"
        if re.search(r"\b(desi|indian|hinglish) memes?\b", low):
            p.meme_flavour = "indian"
        for lk in LOOKS:
            if re.search(r"\b" + re.escape(lk) + r"\b.*\b(look|grade|colou?rs?|feel|vibe)\b", low):
                p.look = lk.replace(" ", "_").replace("&", "")
                break
        m = re.search(r"\b(?:for|audience|target)\s*[:\-]?\s*((?:my )?\d{2}\s*[-–to ]+\s*\d{2}.*|(?:hindi|english)[- ]speaking.*)$", low)
        if m:
            p.audience = _clean(m.group(1))
        m = re.search(r"\b(?:goal|aim|purpose)\s*[:\-]\s*(.+)$", line, re.I)
        if m:
            p.goal = _clean(m.group(1))
        if re.search(r"\bstrict(ly)?\b|exactly as (i|I) (said|wrote)", low):
            p.freedom = "strict"
        if re.search(r"surprise me|be creative|go wild", low):
            p.freedom = "surprise"
    if b.rules or p != Preferences():
        b.parsed_by = "rules"
    return b


def parse_yaml(data: dict, brief: CreatorBrief | None = None) -> CreatorBrief:
    """Structured brief.yaml — keys mirror the UI form."""
    b = brief or CreatorBrief()
    p = b.prefs
    for k in ("playbook", "aspect", "goal", "audience", "mood", "captions", "caption_lang", "humour", "look", "meme_flavour", "freedom"):
        if k in data and data[k] is not None:
            setattr(p, k, str(data[k]))
    for k in ("target_length", "pace"):
        if k in data and data[k] is not None:
            setattr(p, k, float(data[k]))
    if "effects" in data:
        p.effects = str(data["effects"])
    p.outline += [str(x) for x in data.get("outline", []) or []]
    p.deliverables += [str(x) for x in data.get("deliverables", []) or []]
    for r in data.get("rules", []) or []:
        try:
            b.rules.append(HardRule(**r))
        except Exception:
            continue
    if data.get("notes") or data.get("text"):
        parse_text(str(data.get("notes") or data.get("text")), b)
    b.parsed_by = "rules"
    return b


def load_brief(brief_files: list[Path], *, transcribe_voice=None) -> CreatorBrief:
    b = CreatorBrief()
    for f in brief_files:
        suf = f.suffix.lower()
        try:
            if suf in (".yaml", ".yml"):
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                parse_yaml(data if isinstance(data, dict) else {"text": str(data)}, b)
            elif suf in (".md", ".txt", ".json"):
                parse_text(f.read_text(encoding="utf-8"), b)
            elif transcribe_voice is not None:
                text = transcribe_voice(f)
                if text:
                    parse_text(text, b)
            else:
                continue
            b.sources.append(f.name)
        except Exception as e:  # never fail a project because of a brief
            b.raw_text += f"\n[could not read {f.name}: {e}]"
    return b
