"""Rules-based critic: a scorecard over the compiled timeline (the AI critic adds taste on top)."""

from __future__ import annotations

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
    if any(s.type == "split" and s.status == "applied" for s in tl.suggestions):
        present |= {"jcut_new_place", "split_edits"}
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
