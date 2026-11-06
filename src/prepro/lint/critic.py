"""Rules-based critic: a scorecard over the compiled timeline (the AI critic adds taste on top)."""

from __future__ import annotations

from statistics import median

from .. import knowledge as K
from ..schema.analysis import ProjectAnalysis
from ..schema.plan import CriticReport, Direction
from ..schema.timeline import Timeline


def rules_critic(tl: Timeline, pa: ProjectAnalysis, d: Direction, findings) -> CriticReport:
    pb = K.playbook(d.playbook)
    by = {}
    for f in findings:
        by.setdefault(f.rule, []).append(f)
    hook = 4.0 + 6.0 * (d.hooks[0].score if d.hooks else 0.2)
    hook -= 2.0 * len(by.get("slowstart", []))
    clarity = 10 - 2.5 * len(by.get("brief", [])) - 1.5 * len(by.get("midword", []))
    target = d.knobs.target_length or tl.duration
    pacing = 10 - 1.5 * len(by.get("deadzone", [])) - 1.0 * len(by.get("monotone", [])) - 0.5 * len(by.get("microshot", []))
    pacing -= min(3.0, abs(tl.duration - target) / max(target, 1) * 5)
    sound = 10 - 2.0 * len(by.get("loudness", [])) - 2.5 * len(by.get("ducking", []))
    restraint = 10 - 2.0 * len(by.get("overstim", [])) - 1.0 * len(by.get("repeat", []))
    quality = 10 - 3.0 * len(by.get("quality", [])) - 0.5 * len(by.get("colorjump", []))
    # genre fit: signature techniques present in the cut
    sig = set(pb.signature)
    v1 = [i for i in tl.items if i.track == "V1"]
    present = set()
    if any(i.role == "establishing" for i in v1):
        present.add("establishing_first")
    if any(i.kind == "text" and i.style == "card" for i in tl.items):
        present.add("location_cards")
    if any(i.track == "V2" for i in tl.items):
        present |= {"broll_advances_story", "broll_on_nouns"}
    if any(i.transform and i.transform.zoom > 1.01 for i in v1):
        present |= {"jump_cut_punch_in_alternation", "facecam_punch_in_on_reactions", "dramatic_zoom_on_reaction"}
    if v1 and v1[0].role == "hook":
        present |= {"hook_first", "frame1_spectacle", "best_moment_cold_open", "satisfying_open"}
    if any(abs(i.speed - 1) > 0.01 and i.speed < 1 for i in v1):
        present |= {"slowmo_on_peaks", "speed_ramps_on_hits", "replay_slowmo"}
    if any(i.kind == "text" and i.style == "hook" for i in tl.items):
        present.add("text_hook")
    if any(i.track == "A2" for i in tl.items) and d.playbook in ("travel_film", "hype_reel", "teaser"):
        present |= {"cut_on_beat", "backtime_music"}
    if any(i.role == "meme" for i in v1):
        present |= {"meme_after_joke", "meme_after_reaction"}
    if d.playbook == "aesthetic" and v1 and min(i.rec_dur for i in v1) >= 1.8:
        present |= {"hold_satisfying_actions"}
    if d.playbook == "gaming":
        src = sum(pa.asset(a).info.duration for a in {i.asset_id for i in v1 if i.asset_id and pa.asset(i.asset_id).kind.value == "screen"})
        if src and tl.duration < 0.85 * src:
            present.add("cut_dead_gameplay")
        if any(i.kind == "text" and i.style == "callout" for i in tl.items):
            present.add("text_callouts")
    if any(s.type == "split" and s.status == "applied" for s in tl.suggestions):
        present |= {"jcut_new_place", "split_edits"}
    photos = [i for i in v1 if i.kind == "image" and i.asset_id and pa.asset(i.asset_id).kind.value == "image"]
    if photos:
        if v1[0] in photos and v1[0].role == "hook":
            present.add("cover_photo_first")
        if any(i.transform and i.transform.keys for i in photos):
            present.add("slow_push_in_on_stills")
        if any(i.kind == "text" and any(p.rec_in <= i.rec_in < p.rec_out for p in photos) for i in tl.items):
            present.add("text_on_photo")
        if v1[-1].role == "loop" and v1[-1].asset_id == v1[0].asset_id:
            present.add("loop_back_to_cover")
        if len(v1) == 1:                                 # one photo: nothing to loop back to
            sig.discard("loop_back_to_cover")
    if d.playbook == "text_reel":
        words = [i for i in tl.items if i.kind == "text" and i.style == "photo" and i.text]
        if any(i.rec_in < 0.2 for i in words):
            present.add("hook_line_first_frame")
        if words:
            present.add("your_words_word_for_word")          # only your own lines go on screen in this format
        if words and all((i.duration or 0) >= 0.6 + len(i.text.split()) / 3.0 for i in words):
            present.add("readable_lines")
    if d.playbook in ("photo_reel", "day_in_life", "text_reel"):
        music = next((i for i in tl.items if i.track == "A2" and i.asset_id and pa.clips.get(i.asset_id) and pa.clips[i.asset_id].music), None)
        if music is not None and len(pa.clips[music.asset_id].music.beats) > 2:
            # every cut (one photo: every new line) within a frame or two of a beat; past the analysed beats (a quiet
            # outro) the grid carries on at the song's tempo, as the compiler lays it
            beats = [b - music.src_in + music.rec_in for b in pa.clips[music.asset_id].music.beats]
            period = median(b - a for a, b in zip(beats[:64], beats[1:65], strict=False))

            def off_beat(c: float) -> float:
                if c <= beats[-1] + 0.07:
                    return min(abs(c - b) for b in beats)
                return abs(c - (beats[-1] + round((c - beats[-1]) / period) * period))

            cuts = [i.rec_in for i in v1[1:]] or sorted(i.rec_in for i in tl.items if i.kind == "text")[1:]
            if cuts and all(off_beat(c) <= 0.07 for c in cuts):
                present.add("cut_on_the_beat")
    if d.playbook == "day_in_life":
        when = [pa.clips[i.asset_id].order_key + (0.0 if i.kind == "image" else i.src_in) for i in v1 if i.asset_id in pa.clips]
        if len(when) > 1 and all(a <= b + 1e-6 for a, b in zip(when, when[1:], strict=False)):
            present.add("chronological_order")
        if any(i.kind == "text" and i.style == "stamp" for i in tl.items):
            present.add("time_stamps")
        if any(i.track == "A1" and i.role == "natural" and i.gain_db >= -8 for i in tl.items):
            present.add("natural_sound_kept")
        if any(i.kind == "text" and i.style in ("photo", "hook") and i.rec_in < 0.5 for i in tl.items):
            present.add("text_hook")
    fit = 6 + 4 * (len(sig & present) / max(1, len(sig)))
    # the cringe guard: every check a viewer would notice, named when it fails
    from .ghinn import checks, score

    cs = checks(tl, pa, d)
    scores = {k: round(max(0.0, min(10.0, v)), 1) for k, v in
              dict(hook=hook, clarity=clarity, pacing=pacing, sound=sound, restraint=restraint, quality=quality, genre_fit=fit,
                   no_cringe=score(cs)).items()}
    issues = [f"cringe check · {c.id.replace('_', ' ')}: {c.detail}" for c in cs if not c.ok]
    issues += [f.msg for f in findings if f.severity in ("error", "warn")]
    issues = issues[:12]
    overall = sum(scores.values()) / len(scores)
    summary = (f"{overall:.1f}/10 — " + ("ready for a quick human pass" if overall >= 8 else "needs attention: " + "; ".join(issues[:3])))
    return CriticReport(scores=scores, issues=issues, summary=summary, source="rules")
