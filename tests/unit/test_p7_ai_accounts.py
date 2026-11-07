"""AI accounts in the settings window: plans found where installers put them, keys kept in the keychain and never
shown again, one "AI editor" that every task uses, the Gemini CLI connector, and jobs that can be stopped."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

STUBS = Path(__file__).resolve().parents[1] / "stubs"


class _MemKeyring:
    """An in-memory keychain, so tests never touch the real Windows Credential Manager / macOS Keychain."""

    def __init__(self):
        import keyring.backend

        class K(keyring.backend.KeyringBackend):
            priority = 1
            store: dict = {}

            def get_password(self, s, u):
                return self.store.get((s, u))

            def set_password(self, s, u, p):
                self.store[(s, u)] = p

            def delete_password(self, s, u):
                self.store.pop((s, u), None)

        self.backend = K()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import keyring

    monkeypatch.setenv("PREPRO_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("PREPRO_DATA_DIR", str(tmp_path / "data"))
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    old = keyring.get_keyring()
    keyring.set_keyring(_MemKeyring().backend)
    from prepro.brain import accounts

    monkeypatch.setattr(accounts, "find_cli", lambda name: None)       # this PC has no AI CLIs, whatever is installed
    yield tmp_path
    keyring.set_keyring(old)


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from prepro.server import create_app

    c = TestClient(create_app(token="t"), base_url="http://127.0.0.1")
    c.headers["x-prepro-token"] = "t"
    return c


def test_keys_are_kept_secret_and_connecting_one_makes_it_the_editor(client):
    r = client.get("/api/ai").json()
    assert r["editor"] == "basic" and not any(k["set"] for k in r["keys"]) and {p["id"] for p in r["plans"]} == {"claude-plan", "chatgpt-plan", "gemini-plan"}
    bad = client.put("/api/ai/keys/claude-api", json={"key": "sk-wrong-provider-key"})
    assert bad.status_code == 400 and "sk-ant-" in bad.json()["detail"]
    key = "sk-ant-test-0000000000000000wxyz"
    r = client.put("/api/ai/keys/claude-api", json={"key": key})
    assert r.status_code == 200 and key not in r.text                 # never sent back to the page
    slot = next(k for k in r.json()["keys"] if k["id"] == "claude-api")
    assert slot["set"] and slot["masked"] == "•••• wxyz" and r.json()["editor"] == "claude-api"
    assert key not in client.get("/api/ai").text
    from prepro.config import Settings, get_secret

    assert get_secret("anthropic_api_key") == key and Settings.load().ai_editor == "claude-api"
    r = client.delete("/api/ai/keys/claude-api").json()
    assert r["editor"] == "basic" and not next(k for k in r["keys"] if k["id"] == "claude-api")["set"] and get_secret("anthropic_api_key") is None


def test_editor_must_be_connected_and_plans_open_only_their_own_commands(client, monkeypatch):
    from prepro.brain import accounts

    assert client.put("/api/ai", json={"editor": "claude-plan"}).status_code == 400   # not installed here
    opened = []
    monkeypatch.setattr(accounts, "open_terminal", lambda title, cmd: opened.append((title, cmd)))
    monkeypatch.setattr(accounts.shutil, "which", lambda name: "npm" if name == "npm" else None)
    r = client.post("/api/ai/claude-plan/open", json={"action": "install"})
    assert r.status_code == 200 and "claude.ai/install" in opened[-1][1]
    assert client.post("/api/ai/claude-plan/open", json={"action": "signin"}).status_code == 400   # install it first
    assert client.post("/api/ai/claude-plan/open", json={"action": "rm -rf /"}).status_code == 400
    r = client.post("/api/ai/gemini-plan/open", json={"action": "install"})
    assert "antigravity.google/cli/install" in opened[-1][1]          # Google's own installer: no Node.js needed


def test_auto_routing_follows_the_ai_editor_and_old_settings_migrate(env):
    from prepro.config import ConnectorConfig, Settings, config_dir

    (config_dir() / "settings.json").write_text(json.dumps({"routing": {k: "basic" for k in ("vision", "director", "story", "polish",
                                                                                               "critic", "brief", "revise")}}), encoding="utf-8")
    s = Settings.load()
    assert set(s.routing.model_dump().values()) == {"auto"}           # never customised → follows the AI editor
    from prepro.engine import make_brain
    from prepro.schema.analysis import ProjectAnalysis
    from prepro.schema.brief import CreatorBrief

    pa = ProjectAnalysis(root=str(env), assets=[], clips={})
    assert type(make_brain(pa, CreatorBrief(), s, env)).__name__ == "BasicBrain"   # no AI editor yet: the rules engine
    s.connectors["fake"] = ConnectorConfig(kind="stub")
    s.ai_editor = "fake"
    b = make_brain(pa, CreatorBrief(), s, env)
    assert type(b).__name__ == "AIBrain" and all(p is not None and p.name == "fake" for p in b.providers.values())


def test_plans_are_found_where_installers_put_them(tmp_path, monkeypatch):
    import importlib

    from prepro.brain import accounts

    importlib.reload(accounts)
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    monkeypatch.setattr(accounts, "_npm_prefix", lambda: None)
    monkeypatch.setattr(accounts.Path, "home", classmethod(lambda cls: tmp_path))
    name = "claude.exe" if sys.platform == "win32" else "claude"
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    (tmp_path / ".local" / "bin" / name).write_bytes(b"")
    assert accounts.find_cli("claude") == str(tmp_path / ".local" / "bin" / name)   # the native installer's place, off PATH
    assert accounts.find_cli("codex") is None


def test_cli_versions_read_cleanly_and_are_asked_once(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from prepro.brain import accounts

    asked = []

    def run(cmd, **kw):
        asked.append(cmd)
        return SimpleNamespace(returncode=0, stdout=b"2.1.318 (Claude Code)\n", stderr=b"")

    monkeypatch.setattr(accounts.subprocess, "run", run)
    monkeypatch.setattr(accounts, "_VERSIONS", {})
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"")
    assert accounts.cli_version(str(exe), ask=False) is None              # nothing known yet, and nothing launched
    assert accounts.cli_version(str(exe)) == "2.1.318"                     # the card already says "Claude Code"
    assert accounts.cli_version(str(exe), ask=False) == "2.1.318"          # a click's quick refresh keeps it on the card
    assert len(asked) == 1


def test_gemini_goes_through_antigravity(tmp_path, monkeypatch):
    """Google stopped Gemini CLI for personal accounts on 18 June 2026; the Gemini plan now goes through the Antigravity
    CLI: the prompt on stdin as one stream-json line (no command-line limit, UTF-8 intact), the answer checked against
    the schema, no pictures (Google documents no way to attach them), and plain words when it isn't signed in."""
    from prepro.brain.providers import AntigravityCLI, ProviderError
    from prepro.config import ConnectorConfig

    p = AntigravityCLI(name="gemini-plan", cfg=ConnectorConfig(kind="antigravity_cli", extra={"command": [sys.executable, str(STUBS / "agy")]}))
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"\xff\xd8\xff")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    monkeypatch.setenv("FAKE_AGY_ECHO", "1")
    rep = p.complete_json("system words", "user words: ₹5000 “Goa” मुंबई " + "x" * 40000, schema, images=[sheet], pass_name="t")
    assert rep.data["ok"] is True and "₹5000 “Goa” मुंबई" in rep.data["prompt"] and len(rep.data["prompt"]) > 40000
    assert rep.data["schema"] == schema and rep.data["files"] == ["answer.schema.json"]    # an empty folder, no pictures
    assert rep.usage.input_tokens == 900 and rep.usage.plan_usage
    monkeypatch.delenv("FAKE_AGY_ECHO")
    monkeypatch.setenv("FAKE_AGY_SIGNED_OUT", "1")
    with pytest.raises(ProviderError, match="not signed in to Antigravity"):
        p.complete_json("s", "u", schema)
    monkeypatch.delenv("FAKE_AGY_SIGNED_OUT")
    monkeypatch.setenv("FAKE_AGY_QUOTA", "1")
    with pytest.raises(ProviderError, match="plan usage limit"):
        p.complete_json("s", "u", schema)


def test_gemini_plan_moves_to_antigravity(env, monkeypatch, tmp_path):
    import os

    from prepro.brain import accounts
    from prepro.config import ConnectorConfig, Settings, config_dir

    # saved before the move: the Gemini CLI connector with its own model name, and Google's sign-in error on the card
    (config_dir() / "settings.json").write_text(json.dumps({"ai_editor": "gemini-plan", "connectors": {"gemini-plan": {
        "kind": "gemini_cli", "model": "gemini-2.5-pro", "extra": {"path": "C:/old/gemini.cmd", "timeout": 600}}}}), encoding="utf-8")
    (config_dir() / "ai_status.json").write_text(json.dumps({"gemini-plan": {"ok": False, "msg": "gemini CLI error: This client is no "
                                                             "longer supported for Gemini Code Assist for individuals"}}), encoding="utf-8")
    s = Settings.load()
    c = s.connectors["gemini-plan"]
    assert c.kind == "antigravity_cli" and c.model is None and c.extra == {"timeout": 600}
    plan = next(p for p in accounts.overview(s, versions=False)["plans"] if p["id"] == "gemini-plan")
    assert plan["via"] == "Antigravity CLI" and plan["account"] == "Google" and plan["test"] is None   # the old error is gone
    accounts.record_test("gemini-plan", True, "answered in 3 s", kind="antigravity_cli")
    plan = next(p for p in accounts.overview(s, versions=False)["plans"] if p["id"] == "gemini-plan")
    assert plan["test"]["ok"] is True
    assert accounts.connector_for("claude-plan", s) is not None and ConnectorConfig(kind="antigravity_cli").kind == "antigravity_cli"
    # where Google's installer puts agy
    import importlib

    importlib.reload(accounts)
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    monkeypatch.setattr(accounts, "_npm_prefix", lambda: None)
    monkeypatch.setattr(accounts.Path, "home", classmethod(lambda cls: tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
        exe = tmp_path / "AppData" / "Local" / "agy" / "bin" / "agy.exe"
    else:
        exe = tmp_path / ".local" / "bin" / "agy"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert accounts.find_cli("agy") == str(exe)


def test_cards_say_who_is_signed_in_and_failing_ones_go_last(env, monkeypatch):
    """Each plan card says who it's signed in as — from the CLI's own status command, never a token file — and an
    account that failed (its last test, or the CLI says it's signed out) is never offered at the top."""
    from prepro.brain import accounts, providers

    run = {f"fake-{n}": [sys.executable, str(STUBS / n)] for n in ("claude", "codex", "agy")}
    monkeypatch.setattr(accounts, "find_cli", lambda name: f"fake-{name}")
    monkeypatch.setattr(providers, "launch_command", lambda exe, **kw: run.get(exe, [exe]))
    accounts.forget_account()
    claude = accounts.account("claude_code", "fake-claude")
    assert claude == {"signed_in": True, "who": "Asha", "email": "asha@example.com", "plan_name": "Claude Max"}
    assert accounts.account("codex", "fake-codex") == {"signed_in": True, "plan_name": "ChatGPT"}      # Codex names no one
    assert accounts.account("antigravity_cli", "fake-agy")["who"] == "asha.k@example.com"

    monkeypatch.setenv("FAKE_CLAUDE_SIGNED_OUT", "1")
    assert accounts.account("claude_code", "fake-claude")["who"] == "Asha"                           # still the cached answer
    accounts.record_test("claude-plan", False, "not signed in", kind="claude_code")                 # a test forgets it
    assert accounts.account("claude_code", "fake-claude") == {"signed_in": False}

    accounts.record_test("chatgpt-plan", True, "answered in 2 s", kind="codex")
    s = __import__("prepro.config", fromlist=["Settings"]).Settings.load()
    ov = accounts.overview(s, versions=False)
    assert ov["ready"][0] == "chatgpt-plan"                          # works: first
    assert ov["ready"][-1] == "claude-plan" and ov["failing"] == ["claude-plan"]                     # failed: last
    cards = {p["id"]: p for p in ov["plans"]}
    assert cards["gemini-plan"]["who"] == "asha.k@example.com" and cards["claude-plan"]["signed_in"] is False
    accounts.forget_account()


def test_gemini_cli_says_what_google_changed(monkeypatch):
    from prepro.brain.providers import GeminiCLI, ProviderError
    from prepro.config import ConnectorConfig

    p = GeminiCLI(name="gemini-plan", cfg=ConnectorConfig(kind="gemini_cli", extra={"command": [sys.executable, str(STUBS / "gemini")]}))
    monkeypatch.setenv("FAKE_GEMINI_ENDED", "1")
    with pytest.raises(ProviderError, match="Google stopped Gemini CLI for personal Google accounts.*Antigravity"):
        p.complete_json("s", "u", {"type": "object"})


def test_gemini_cli_connector(tmp_path, monkeypatch):
    from prepro.brain.providers import GeminiCLI, ProviderError
    from prepro.config import ConnectorConfig

    p = GeminiCLI(name="gemini-plan", cfg=ConnectorConfig(kind="gemini_cli", extra={"command": [sys.executable, str(STUBS / "gemini")]}))
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"\xff\xd8\xff")
    monkeypatch.setenv("FAKE_GEMINI_ECHO", "1")
    rep = p.complete_json("system words", "user words: ₹5000 “Goa”", {"type": "object"}, images=[sheet], pass_name="t")
    assert rep.data["ok"] is True and "₹5000 “Goa”" in rep.data["prompt"] and "@sheet_0.jpg" in rep.data["prompt"]
    assert rep.data["files"] == ["sheet_0.jpg"] and rep.usage.input_tokens == 1200 and rep.usage.plan_usage
    monkeypatch.setenv("FAKE_GEMINI_FAIL", "1")
    with pytest.raises(ProviderError, match="plan usage limit"):
        p.complete_json("s", "u", {"type": "object"})


def test_a_job_can_be_stopped():
    from prepro.server.jobs import Jobs

    js = Jobs(workers=1)

    def work(job):
        for i in range(200):
            job.progress("step", i, 200, f"item {i}")
            time.sleep(0.01)
        return "finished"

    j = js.submit("long", "p", work, steps=[("a", "First"), ("b", "Second")])
    time.sleep(0.15)
    j.cancel = True
    for _ in range(100):
        if j.status not in ("queued", "running"):
            break
        time.sleep(0.05)
    pub = j.public()
    assert pub["status"] == "cancelled" and pub["result"] is None and [s["label"] for s in pub["steps"]] == ["First", "Second"]


def test_phases_only_move_forward():
    from prepro.server.jobs import Job

    j = Job(id="x", kind="k", project="p")
    a = j.phase(0, 0.0, 0.5)
    a("watch", 1, 2)
    assert j.frac == pytest.approx(0.25)
    a("watch", 0, 2)                                                    # a stage restarting never moves the bar back
    assert j.frac == pytest.approx(0.25)
    b = j.phase(1, 0.5, 1.0)
    b("edit", 1, 4)
    assert j.step == 1 and j.frac == pytest.approx(0.625)
