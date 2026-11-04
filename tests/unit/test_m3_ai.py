"""M3: AI brain contract — validation, fallbacks, brief guarantees, privacy, sent-data log, CLI connectors (no real AI calls)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

from prepro.brain.ai import AIBrain, paper_edit
from prepro.brain.providers import (
    ClaudeCodeCLI,
    CodexCLI,
    PrivacyBlocked,
    ProviderError,
    StubProvider,
    make_provider,
)
from prepro.config import ConnectorConfig
from prepro.engine import analysis, brief_for

pytestmark = [needs_tts, needs_ffmpeg]
STUBS = Path(__file__).resolve().parents[1] / "stubs"


@pytest.fixture(scope="module")
def ctx(shoot_factory):
    root = shoot_factory("travel_vlog", brief=True)
    pa = analysis(root)
    return root, pa, brief_for(root, pa)


def _stub(root, responses, privacy="thumbs"):
    return StubProvider(name="stub", cfg=ConnectorConfig(kind="stub"), sent_dir=Path(root) / ".prepro" / "sent", privacy=privacy, responses=responses)


def test_ai_output_is_validated_and_brief_survives(ctx):
    root, pa, brief = ctx
    hook = next(r.target for r in brief.rules if r.kind == "hook")
    greeting = next(s.id for s in pa.all_segments() if "greeting" in s.tags)
    shots = [s.id for s in pa.all_shots() if pa.asset(s.asset_id).kind.value == "broll" and not s.flags][:3]
    epic = next(a.id for a in pa.assets if a.name.startswith("epic_build"))
    responses = {
        "TASK: propose": {"directions": [
            {"playbook": "not_a_playbook", "name": "x", "aspect": "9:16", "target_seconds": 30, "why": "", "hooks": [], "outline": [], "coverage_gaps": []},
            {"playbook": "story_vlog", "name": "Goa on ₹5000", "aspect": "9:16", "target_seconds": 30, "why": "talking + places",
             "hooks": [{"refs": ["ZZ.s9"], "kind": "bold_claim", "text_hook": "Nope", "why": "bad id"}], "outline": ["a"], "coverage_gaps": ["Film a sunrise"]}]},
        "TASK: build the story": {"items": [
            {"ref": greeting, "role": "setup", "section": "s", "t0": None, "t1": None, "note": ""},
            {"ref": "ZZ.k1", "role": "montage", "section": "s", "t0": 0, "t1": 1, "note": ""},
            *[{"ref": sid, "role": "montage", "section": "m", "t0": None, "t1": None, "note": ""} for sid in shots]],
            "sections": [{"name": "m", "music_mode": "front", "card": None}], "why": "test"},
        "TASK: polish": {"music": [{"section": "m", "mode": "front", "track_id": "FAKE", "mood": "epic", "search_terms": [], "why": ""}],
                         "effects": [{"type": "zoom", "at": "nonexistent.w1", "asset": None, "value": 1.2, "text": None, "style": None, "why": "x", "confidence": 0.9},
                                     {"type": "meme", "at": shots[0], "asset": "meme:vine-boom", "value": None, "text": None, "style": None, "why": "after reveal", "confidence": 0.6},
                                     {"type": "sfx", "at": shots[0], "asset": "NOPE", "value": None, "text": None, "style": None, "why": "x", "confidence": 0.9}],
                         "broll_gaps": [], "vo_script": [], "look": "warm"},
    }
    prov = _stub(root, responses)
    brain = AIBrain(pa, brief, {k: prov for k in ("director", "story", "polish")})
    ds = brain.directions()
    assert [d.playbook for d in ds.directions] == ["story_vlog"]
    d = ds.directions[0]
    assert d.hooks and d.hooks[0].refs == [hook]                      # brief hook wins, invalid refs dropped
    assert "Film a sunrise" in d.coverage_gaps
    story = brain.story(d)
    refs = [i.ref for i in story.items]
    assert refs[0] == hook and greeting not in refs and "ZZ.k1" not in refs
    pol = brain.polish(d, story)
    assert all(e.at != "nonexistent.w1" for e in pol.effects)
    assert not any(e.type == "sfx" and e.asset == "NOPE" for e in pol.effects)
    assert any(e.asset == "meme:vine-boom" for e in pol.effects)
    assert any(m.track_id == epic for m in pol.music)                # brief "use epic_build_128" beats the AI
    assert any(e.confidence >= 1.0 for e in pol.effects)             # brief-forced cues survive
    # sent-data log: written, and never contains footage file names or raw GPS
    logs = list((Path(root) / ".prepro" / "sent").glob("*_director_stub.json"))
    assert logs
    sent = json.loads(logs[-1].read_text())["user_text"]
    assert "IMG_20" not in sent and "+15.55" not in sent and "Calangute" in sent


def test_failures_fall_back_to_rules(ctx):
    root, pa, brief = ctx
    prov = _stub(root, {})          # every call raises "no recorded response"
    brain = AIBrain(pa, brief, {k: prov for k in ("director", "story", "polish")})
    ds = brain.directions()
    assert ds.directions and brain.warnings and "rules engine" in brain.warnings[0]


def test_privacy_local_blocks_cloud_connectors(ctx):
    root, pa, brief = ctx
    p = make_provider("claude-api", ConnectorConfig(kind="anthropic"), privacy="local")
    with pytest.raises(PrivacyBlocked):
        p.complete_json("s", "u", {"type": "object"})
    brain = AIBrain(pa, brief, {"director": p})
    assert brain.directions().directions and any("privacy" in w for w in brain.warnings)


def test_text_only_privacy_strips_images(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8fake")
    p = StubProvider(name="s", cfg=ConnectorConfig(kind="stub"), privacy="text", responses={"*": {"ok": True}})
    p.complete_json("s", "hello", {"type": "object"}, images=[img])
    assert p.log[-1]["images"] == []


def test_claude_code_cli_connector(tmp_path, monkeypatch):
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({"directions": []}))
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", str(reply))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    p = ClaudeCodeCLI(name="claude-plan", cfg=ConnectorConfig(kind="claude_code", extra={"path": str(STUBS / "claude")}))
    rep = p.complete_json("sys", "user text", {"type": "object"}, pass_name="director")
    assert rep.data == {"directions": []} and rep.usage.plan_usage
    call = json.loads(log.read_text().splitlines()[-1])
    assert not call["has_bare"]                        # subscription login needs the non-bare mode
    assert "prepro-cc-" in call["cwd"]                  # runs in an empty temp folder
    assert "--json-schema" in call["args"] and "dontAsk" in call["args"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    with pytest.raises(ProviderError, match="limit"):
        p.complete_json("sys", "user", {"type": "object"})


def test_codex_cli_connector(tmp_path, monkeypatch):
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({"ok": True}))
    monkeypatch.setenv("FAKE_CODEX_REPLY", str(reply))
    p = CodexCLI(name="chatgpt-plan", cfg=ConnectorConfig(kind="codex", extra={"path": str(STUBS / "codex")}))
    assert p.complete_json("sys", "u", {"type": "object"}).data == {"ok": True}


def test_paper_edit_reads_like_an_edit(ctx):
    from prepro.engine import build

    root, pa, _ = ctx
    res = build(root, render=False)
    pe = paper_edit(res.timeline, pa)
    assert "PICTURE" in pe and "“" in pe and "[TEXT" in pe


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("PREPRO_LIVE_CLAUDE"), reason="set PREPRO_LIVE_CLAUDE=1 to spend plan usage on a real call")
def test_live_claude_code_directions(ctx):
    root, pa, brief = ctx
    p = make_provider("claude-plan", ConnectorConfig(kind="claude_code"), sent_dir=Path(root) / ".prepro" / "sent", privacy="text")
    brain = AIBrain(pa, brief, {"director": p})
    ds = brain.directions()
    assert ds.directions and not brain.warnings, brain.warnings
