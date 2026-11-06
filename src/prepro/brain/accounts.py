"""AI accounts the creator can connect, in the words the settings window uses.

Three ways in, all optional (PrePro edits without AI too):
- **Your plan** — the subscription you already pay for, through the provider's own CLI and its own sign-in:
  Claude Pro/Max (Claude Code), ChatGPT Plus/Pro (Codex CLI), Google AI Pro / a Google account (Gemini CLI).
  PrePro never sees or stores those logins; it runs the unmodified CLI.
- **Your API key (BYOK)** — Anthropic, OpenAI, Google Gemini, xAI, OpenRouter. Keys go to the OS keychain and are
  never sent back to the page (only "•••• last 4").
- **Local** — Ollama on this PC; nothing leaves it.

"Connect" opens a terminal window running the provider's official install or sign-in command — only on the
creator's click, only these fixed commands.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..config import ConnectorConfig, Settings, config_dir, delete_secret, get_secret, set_secret

PLANS = [
    {"id": "claude-plan", "kind": "claude_code", "name": "Claude", "plan": "Claude Pro or Max", "via": "Claude Code", "exe": "claude",
     "install": {"nt": "irm https://claude.ai/install.ps1 | iex", "posix": "curl -fsSL https://claude.ai/install.sh | bash"},
     "signin": "{exe}", "signin_note": "Sign in with your Claude account when it asks, then close the window.",
     "docs": "https://docs.anthropic.com/en/docs/claude-code/setup"},
    {"id": "chatgpt-plan", "kind": "codex", "name": "ChatGPT", "plan": "ChatGPT Plus or Pro", "via": "Codex CLI", "exe": "codex",
     "install": {"nt": "npm install -g @openai/codex", "posix": "npm install -g @openai/codex"}, "needs_npm": True,
     "signin": "{exe} login", "signin_note": "Choose “Sign in with ChatGPT” in the browser, then close the window.",
     "docs": "https://github.com/openai/codex"},
    {"id": "gemini-plan", "kind": "gemini_cli", "name": "Gemini", "plan": "Google AI Pro or a Google account", "via": "Gemini CLI", "exe": "gemini",
     "install": {"nt": "npm install -g @google/gemini-cli", "posix": "npm install -g @google/gemini-cli"}, "needs_npm": True,
     "signin": "{exe}", "signin_note": "Pick “Login with Google” when it asks, then close the window.",
     "docs": "https://github.com/google-gemini/gemini-cli"},
]
KEYS = [
    {"id": "claude-api", "kind": "anthropic", "name": "Anthropic API", "secret": "anthropic_api_key", "model": "claude-opus-5-5",
     "prefix": "sk-ant-", "get": "https://console.anthropic.com/settings/keys"},
    {"id": "openai-api", "kind": "openai", "name": "OpenAI API", "secret": "openai_api_key", "model": "gpt-5", "prefix": "sk-",
     "get": "https://platform.openai.com/api-keys"},
    {"id": "gemini", "kind": "gemini", "name": "Google Gemini API", "secret": "gemini_api_key", "model": "gemini-2.5-flash", "prefix": "",
     "get": "https://aistudio.google.com/apikey"},
    {"id": "xai-api", "kind": "xai", "name": "xAI (Grok) API", "secret": "xai_api_key", "model": "grok-4", "prefix": "xai-",
     "get": "https://console.x.ai"},
    {"id": "openrouter", "kind": "openrouter", "name": "OpenRouter", "secret": "openrouter_api_key", "model": "openrouter/auto", "prefix": "sk-or-",
     "get": "https://openrouter.ai/keys"},
]
STATUS_FILE = "ai_status.json"


# ---------------------------------------------------------------- finding CLIs
@functools.lru_cache(maxsize=1)
def _npm_prefix() -> str | None:
    npm = shutil.which("npm")
    if not npm:
        return None
    try:
        r = subprocess.run([npm, "config", "get", "prefix"], capture_output=True, text=True, timeout=10, shell=os.name == "nt" and npm.lower().endswith(".cmd"))
        out = r.stdout.strip()
        return out or None
    except Exception:
        return None


def find_cli(name: str) -> str | None:
    """A CLI on PATH, or where its installer puts it — a just-installed CLI isn't on the PATH of an app that was
    already running, and the Claude desktop app doesn't put `claude` on PATH at all."""
    hit = shutil.which(name)
    if hit:
        return hit
    home = Path.home()
    cands: list[Path] = []
    if os.name == "nt":
        cands += [home / ".local" / "bin" / f"{name}.exe"]
        for env in ("APPDATA",):
            if os.environ.get(env):
                cands.append(Path(os.environ[env]) / "npm" / f"{name}.cmd")
        if os.environ.get("LOCALAPPDATA"):
            cands.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / name / f"{name}.exe")
        pre = _npm_prefix()
        if pre:
            cands.append(Path(pre) / f"{name}.cmd")
    else:
        cands += [home / ".local" / "bin" / name, home / ".claude" / "local" / name, Path("/opt/homebrew/bin") / name,
                  Path("/usr/local/bin") / name, home / ".npm-global" / "bin" / name]
        pre = _npm_prefix()
        if pre:
            cands.append(Path(pre) / "bin" / name)
    return next((str(c) for c in cands if c.is_file()), None)


_VERSIONS: dict[tuple[str, float], str | None] = {}


def _ask_version(exe: str) -> str | None:
    from .providers import launch_command

    try:
        r = subprocess.run([*launch_command(exe), "--version"], capture_output=True, timeout=15)
        out = (r.stdout or r.stderr).decode("utf-8", "replace").strip().splitlines()
    except Exception:
        return None
    if not out or r.returncode != 0:
        return None
    m = re.search(r"\d+(?:\.\d+)+", out[0])        # "2.1.318 (Claude Code)" -> "2.1.318": the card already names the tool
    return m.group(0) if m else out[0][:40]


def cli_version(exe: str, *, ask: bool = True) -> str | None:
    """The installed CLI's version. Asked once per install (kept until the file changes); ask=False only reads what's known."""
    try:
        stamp = Path(exe).stat().st_mtime
    except OSError:
        stamp = 0.0
    key = (exe, stamp)
    if key not in _VERSIONS and ask:
        _VERSIONS[key] = _ask_version(exe)
    return _VERSIONS.get(key)


# ---------------------------------------------------------------- status
def _status() -> dict:
    p = config_dir() / STATUS_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record_test(cid: str, ok: bool, msg: str, model: str = "") -> None:
    s = _status()
    s[cid] = {"ok": ok, "msg": msg[:300], "model": model, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (config_dir() / STATUS_FILE).write_text(json.dumps(s, indent=1), encoding="utf-8")


def _mask(v: str | None) -> str | None:
    return f"•••• {v[-4:]}" if v and len(v) >= 8 else ("••••" if v else None)


def overview(settings: Settings | None = None, *, versions: bool = True) -> dict:
    """Everything the AI section of the settings window shows."""
    from .providers import TRAINING, detect_connectors

    s = settings or Settings.load()
    tests = _status()
    found = detect_connectors()
    plans = []
    for p in PLANS:
        exe = find_cli(p["exe"])
        plans.append({**{k: v for k, v in p.items() if k not in ("install", "signin")},
                      "installed": bool(exe), "path": exe, "version": cli_version(exe, ask=versions) if exe else None,
                      "install_cmd": p["install"]["nt" if os.name == "nt" else "posix"], "npm": bool(shutil.which("npm")),
                      "test": tests.get(p["id"]), "training": TRAINING.get(p["kind"], ""),
                      "model": (s.connectors.get(p["id"]) or ConnectorConfig(kind=p["kind"])).model})
    keys = []
    for k in KEYS:
        v = get_secret(k["secret"])
        cfg = s.connectors.get(k["id"]) or found.get(k["id"])
        badge = TRAINING.get("gemini_free" if k["kind"] == "gemini" else k["kind"], "")
        keys.append({**{x: y for x, y in k.items() if x != "secret"}, "set": bool(v), "masked": _mask(v),
                     "model": (cfg.model if cfg and cfg.model else k["model"]), "test": tests.get(k["id"]), "training": badge})
    local = []
    if shutil.which("ollama"):
        local.append({"id": "ollama", "name": "Ollama (on this PC)", "model": (s.connectors.get("ollama") or ConnectorConfig(kind="ollama")).model or "llama3.1",
                      "test": tests.get("ollama"), "training": TRAINING["ollama"]})
    ready = [p["id"] for p in plans if p["installed"]] + [k["id"] for k in keys if k["set"]] + [x["id"] for x in local]
    ready += [n for n in s.connectors if n not in ready]
    return {"editor": s.ai_editor if (s.ai_editor in ready or s.ai_editor == "basic") else "basic", "ready": ready,
            "plans": plans, "keys": keys, "local": local, "routing": s.routing.model_dump(),
            "privacy": s.privacy, "blur_faces": s.blur_faces_in_thumbs, "monthly_cap_usd": s.monthly_cap_usd}


def connector_for(cid: str, settings: Settings | None = None) -> ConnectorConfig | None:
    """The connector behind an account id: the user's saved one (their model choice), else the defaults."""
    s = settings or Settings.load()
    if cid in s.connectors:
        return s.connectors[cid]
    for p in PLANS:
        if p["id"] == cid:
            return ConnectorConfig(kind=p["kind"], extra={"path": find_cli(p["exe"])} if find_cli(p["exe"]) else {})
    for k in KEYS:
        if k["id"] == cid and get_secret(k["secret"]):
            return ConnectorConfig(kind=k["kind"], model=k["model"], extra={"tier": "free"} if k["kind"] == "gemini" else {})
    if cid == "ollama":
        return ConnectorConfig(kind="ollama", model="llama3.1")
    return None


# ---------------------------------------------------------------- changes
def save_key(cid: str, value: str, model: str | None = None) -> dict:
    k = next((x for x in KEYS if x["id"] == cid), None)
    if k is None:
        raise ValueError(f"unknown key slot {cid!r}")
    value = (value or "").strip()
    if len(value) < 12 or any(c.isspace() for c in value):
        raise ValueError("that doesn't look like an API key")
    if k["prefix"] and not value.startswith(k["prefix"]):
        raise ValueError(f"{k['name']} keys start with “{k['prefix']}”")
    set_secret(k["secret"], value)
    s = Settings.load()
    s.connectors[cid] = ConnectorConfig(kind=k["kind"], model=model or k["model"], extra={"tier": "free"} if k["kind"] == "gemini" else {})
    if s.ai_editor == "basic":                      # you just connected it: it edits from now on
        s.ai_editor = cid
    s.save()
    return overview(s, versions=False)


def remove_key(cid: str) -> dict:
    k = next((x for x in KEYS if x["id"] == cid), None)
    if k is None:
        raise ValueError(f"unknown key slot {cid!r}")
    delete_secret(k["secret"])
    s = Settings.load()
    s.connectors.pop(cid, None)
    if s.ai_editor == cid:
        s.ai_editor = "basic"
    s.save()
    st = _status()
    st.pop(cid, None)
    (config_dir() / STATUS_FILE).write_text(json.dumps(st, indent=1), encoding="utf-8")
    return overview(s, versions=False)


def set_model(cid: str, model: str) -> dict:
    s = Settings.load()
    cfg = connector_for(cid, s)
    if cfg is None:
        raise ValueError("connect it first")
    s.connectors[cid] = cfg.model_copy(update={"model": (model or "").strip() or None})
    s.save()
    return overview(s, versions=False)


def terminal_command(cid: str, action: str) -> tuple[str, str]:
    """(title, command) for a plan's install or sign-in — fixed commands, never anything from the request."""
    p = next((x for x in PLANS if x["id"] == cid), None)
    if p is None or action not in ("install", "signin"):
        raise ValueError("unknown account or action")
    if action == "install":
        if p.get("needs_npm") and not shutil.which("npm"):
            raise ValueError("this needs Node.js first — install it from https://nodejs.org, then try again")
        return f"PrePro — install {p['via']}", p["install"]["nt" if os.name == "nt" else "posix"]
    exe = find_cli(p["exe"])
    if not exe:
        raise ValueError(f"install {p['via']} first")
    quoted = f'& "{exe}"' if os.name == "nt" else f'"{exe}"'
    return f"PrePro — sign in to {p['name']}", p["signin"].replace("{exe}", quoted)


def open_terminal(title: str, command: str) -> None:
    """A visible terminal window running ``command`` (the creator watches and answers its questions)."""
    if os.name == "nt":
        subprocess.Popen(["cmd.exe", "/c", "start", title, "powershell.exe", "-NoExit", "-NoProfile", "-Command", command],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    if shutil.which("osascript"):
        script = command.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{script}"', "-e", 'tell application "Terminal" to activate'])
        return
    shell = f"{command}; exec bash"
    for term, args in (("x-terminal-emulator", ["-e", "bash", "-lc", shell]), ("gnome-terminal", ["--", "bash", "-lc", shell]),
                       ("konsole", ["-e", "bash", "-lc", shell]), ("xfce4-terminal", ["-e", f"bash -lc '{shell}'"]),
                       ("xterm", ["-e", "bash", "-lc", shell])):
        if shutil.which(term):
            subprocess.Popen([term, *args])
            return
    raise RuntimeError("no terminal app found — run this yourself: " + command)
