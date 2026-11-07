"""AI connectors behind one provider-neutral contract.

Every connector takes a system prompt, a user message (text + optional images) and a JSON Schema and
returns a parsed JSON object plus usage. Validation, repair and fallbacks live in :mod:`brain.ai`.

Connectors (kind):
  claude_code  — the user's own Claude Code CLI (`claude -p`), signed in with their Claude plan
  codex        — the user's own OpenAI Codex CLI (`codex exec`), signed in with ChatGPT
  anthropic    — Claude API key (official SDK, structured outputs, prompt caching, refusal fallback)
  openai       — OpenAI API key (official SDK)
  xai          — Grok via xAI's OpenAI-compatible API (official docs)
  openrouter   — one key, many models (OpenAI-compatible API, data_collection=deny)
  gemini       — Google Gemini API (google-genai SDK; free or paid tier)
  ollama       — local models (nothing leaves the PC)
  stub         — recorded responses / test double
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ...config import ConnectorConfig, get_secret

TRAINING = {
    "claude_code": "Your Claude plan: used for training only if “Help improve Claude” is on (claude.ai → Settings → Privacy). Turn it off to opt out.",
    "codex": "Your ChatGPT plan: used for training by default — turn off “Improve the model for everyone” (it covers Codex too).",
    "gemini_cli": "Your Google account: with a personal account Google may use what is sent to improve its products — see the Gemini CLI privacy notice; Workspace / Code Assist licences differ.",
    "antigravity_cli": "Your Google account (free, Google AI Pro or Ultra) through Antigravity: Google's Antigravity terms and privacy notice apply, and with a personal account Google may use what is sent to improve its products.",
    "anthropic": "Not used for training (Claude API commercial terms).",
    "openai": "Not used for training by default (OpenAI API).",
    "xai": "xAI API: reportedly not used for training without permission — check xAI's current terms.",
    "openrouter": "Depends on the routed provider — PrePro asks OpenRouter to use only providers that don't collect data.",
    "gemini_free": "Free tier: Google may use what is sent to improve its products, and human reviewers may read it.",
    "gemini_paid": "Paid tier: not used to improve Google products.",
    "ollama": "Local model — nothing leaves this PC.",
    "stub": "Test double — nothing is sent.",
}
LOCAL_KINDS = {"ollama", "stub"}
PRICES = {  # USD per million tokens (input, output) — first-party list prices used for estimates only
    "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
}
DEFAULT_MODEL = {"anthropic": "claude-opus-5-5", "claude_code": None, "codex": None, "openai": None, "xai": None,
                 "openrouter": None, "gemini": None, "ollama": "llama3.1"}


class ProviderError(RuntimeError):
    pass


class PrivacyBlocked(ProviderError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    usd: float = 0.0
    plan_usage: bool = False      # billed to a subscription plan's limits, not per token
    seconds: float = 0.0


@dataclass
class Reply:
    data: dict
    usage: Usage
    raw: str = ""
    model: str = ""


@dataclass
class Provider:
    name: str
    cfg: ConnectorConfig
    sent_dir: Path | None = None
    privacy: str = "thumbs"
    log: list = field(default_factory=list)
    sees_images = True                 # False: a connector with no documented way to pass pictures (gets text only)

    @property
    def kind(self) -> str:
        return self.cfg.kind

    def training_badge(self) -> str:
        if self.kind == "gemini":
            return TRAINING["gemini_paid" if self.cfg.extra.get("tier") == "paid" else "gemini_free"]
        return TRAINING.get(self.kind, "Unknown — check the provider's terms.")

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def _complete(self, system: str, user: str, schema: dict, images: list[Path], effort: str) -> Reply:
        raise NotImplementedError

    def complete_json(self, system: str, user: str, schema: dict, *, images: list[Path] | None = None, effort: str = "high",
                      pass_name: str = "") -> Reply:
        if self.privacy == "local" and self.kind not in LOCAL_KINDS:
            raise PrivacyBlocked(f"privacy level 'local' — {self.name} would send data off this PC")
        imgs = list(images or [])
        if self.privacy != "thumbs" or not self.sees_images:
            imgs = []
        t0 = time.time()
        rep = self._complete(system, user, schema, imgs, effort)
        rep.usage.seconds = round(time.time() - t0, 2)
        self._record(pass_name, system, user, imgs, rep)
        return rep

    def _record(self, pass_name: str, system: str, user: str, images: list[Path], rep: Reply) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pass": pass_name, "connector": self.name, "kind": self.kind,
            "model": rep.model or self.cfg.model, "privacy": self.privacy, "training": self.training_badge(),
            "system_sha1": hashlib.sha1(system.encode()).hexdigest()[:12], "user_text": user,
            "images": [{"file": p.name, "sha1": hashlib.sha1(p.read_bytes()).hexdigest()[:12]} for p in images],
            "usage": rep.usage.__dict__, "response": rep.data,
        }
        self.log.append(entry)
        if self.sent_dir:
            self.sent_dir.mkdir(parents=True, exist_ok=True)
            (self.sent_dir / f"{entry['ts'].replace(':', '')}_{pass_name or 'call'}_{self.name}.json").write_text(
                json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")


def _img_b64(p: Path) -> tuple[str, str]:
    mt = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return mt, base64.b64encode(p.read_bytes()).decode()


def _parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    if not t.startswith("{"):
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            t = t[a: b + 1]
    return json.loads(t)


# ---------------------------------------------------------------- subscription CLIs
CLAUDE_INSTALL_HINT = ("install Claude Code (Windows: winget install Anthropic.ClaudeCode, or in PowerShell "
                       "irm https://claude.ai/install.ps1 | iex; macOS/Linux: curl -fsSL https://claude.ai/install.sh | bash), "
                       "then run `claude` once to sign in")


def launch_command(exe: str, *, windows: bool | None = None) -> list[str]:
    """How to start a CLI that was found on PATH.

    On Windows, npm installs ``.cmd`` shims. Running one goes through cmd.exe, which re-parses the command line
    (quotes inside JSON, ``%``, ``&``, ``<``, ``>``) and caps it at 8191 characters — the JSON schema we pass
    arrives broken. So a shim is resolved to the program it launches (the package's ``.exe``, or ``node`` + its
    script) and that is run directly. Anything that can't be resolved is returned unchanged."""
    windows = os.name == "nt" if windows is None else windows
    p = Path(exe)
    if not windows or p.suffix.lower() not in (".cmd", ".bat"):
        return [exe]
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [exe]
    import re

    targets = re.findall(r'"%~?dp0%?\\?([^"%]+?\.(?:exe|js|cjs|mjs))"', text, re.I)
    for rel in reversed(targets):                 # the launched program comes last; node.exe is only the runner
        t = p.parent / rel.replace("\\", "/")
        if t.name.lower() == "node.exe" or not t.exists():
            continue
        if t.suffix.lower() == ".exe":
            return [str(t)]
        node = p.parent / "node.exe"
        runner = str(node) if node.exists() else shutil.which("node")
        if runner:
            return [runner, str(t)]
    return [exe]


def _run_cli(cmd: list[str], stdin_text: str, *, cwd: str, timeout: float, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a CLI with the prompt on stdin, as UTF-8 bytes both ways: transcripts carry ₹, “quotes” and Hindi, and on
    Windows text-mode pipes would use cp1252 and turn every newline into CRLF."""
    p = subprocess.run(cmd, input=stdin_text.encode("utf-8"), capture_output=True, cwd=cwd, env=env, timeout=timeout)
    return subprocess.CompletedProcess(p.args, p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))


def _cli_prefix(cfg: ConnectorConfig, exe: str | None) -> list[str] | None:
    """``extra.command`` (a full launcher, e.g. ``["wsl", "claude"]`` or an interpreter + script) wins over the exe."""
    cmd = cfg.extra.get("command")
    if cmd:
        return [str(c) for c in cmd] if isinstance(cmd, list | tuple) else [str(cmd)]
    return launch_command(exe) if exe else None


@dataclass
class ClaudeCodeCLI(Provider):
    """The user's own Claude Code CLI, signed in with their Claude plan (Anthropic's own login).
    We run the unmodified binary headless in an empty temp folder; we never read or store tokens."""

    def exe(self) -> str | None:
        from ..accounts import find_cli

        return self.cfg.extra.get("path") or find_cli("claude")

    def available(self) -> tuple[bool, str]:
        exe = self.exe()
        if self.cfg.extra.get("command"):
            return True, " ".join(map(str, self.cfg.extra["command"]))
        return (True, exe) if exe else (False, f"Claude Code CLI not found — {CLAUDE_INSTALL_HINT}")

    def _complete(self, system, user, schema, images, effort):
        prefix = _cli_prefix(self.cfg, self.exe())
        if not prefix:
            raise ProviderError("claude CLI not installed")
        if Path(prefix[0]).suffix.lower() in (".cmd", ".bat"):
            raise ProviderError(f"{prefix[0]} is a Windows .cmd shim PrePro can't hand the request to safely (cmd.exe breaks "
                                f"the JSON it needs) — {CLAUDE_INSTALL_HINT}, or set this connector's path to claude.exe")
        with tempfile.TemporaryDirectory(prefix="prepro-cc-") as td:
            names = []
            for i, p in enumerate(images):
                dst = Path(td) / f"sheet_{i}{p.suffix}"
                shutil.copy(p, dst)
                names.append(dst.name)
            prompt = user
            if names:
                prompt += "\n\nContact sheets to look at (read them with the Read tool): " + ", ".join(names)
            # the system prompt goes in a file: Windows caps command lines (32 767 chars) and it is the longest part
            sp = Path(td) / "system_prompt.txt"
            sp.write_text(system, encoding="utf-8")
            cmd = [*prefix, "-p", "--output-format", "json", "--json-schema", json.dumps(schema), "--system-prompt-file", str(sp),
                   "--permission-mode", "dontAsk"]
            cmd += ["--allowedTools", "Read"] if names else ["--allowedTools", ""]
            if self.cfg.model:
                cmd += ["--model", self.cfg.model]
            if self.cfg.max_usd_per_project:
                cmd += ["--max-budget-usd", str(self.cfg.max_usd_per_project)]
            env = dict(os.environ)
            env.pop("ANTHROPIC_API_KEY", None) if self.cfg.extra.get("plan_only", True) else None
            p = _run_cli(cmd, prompt, cwd=td, env=env, timeout=float(self.cfg.extra.get("timeout", 900)))
        out = p.stdout.strip()
        try:
            res = json.loads(out.splitlines()[-1]) if out else {}
        except json.JSONDecodeError as e:
            raise ProviderError(f"claude CLI returned non-JSON: {out[:300]} {p.stderr[-300:]}") from e
        if res.get("is_error") or p.returncode != 0:
            msg = str(res.get("result") or p.stderr)[:400]
            if "limit" in msg.lower():
                raise ProviderError(f"plan usage limit reached: {msg}")
            raise ProviderError(f"claude CLI error: {msg}")
        data = res.get("structured_output")
        if data is None:
            data = _parse_json(str(res.get("result", "")))
        u = res.get("usage") or {}
        usage = Usage(input_tokens=int(u.get("input_tokens", 0)), output_tokens=int(u.get("output_tokens", 0)),
                      cached_tokens=int(u.get("cache_read_input_tokens", 0)), usd=float(res.get("total_cost_usd") or 0.0), plan_usage=True)
        return Reply(data=data, usage=usage, raw=out[-2000:], model=str(res.get("model", self.cfg.model or "claude-code")))


@dataclass
class CodexCLI(Provider):
    """The user's own OpenAI Codex CLI signed in with ChatGPT (plan limits apply)."""

    def exe(self) -> str | None:
        from ..accounts import find_cli

        return self.cfg.extra.get("path") or find_cli("codex")

    def available(self) -> tuple[bool, str]:
        exe = self.exe()
        if self.cfg.extra.get("command"):
            return True, " ".join(map(str, self.cfg.extra["command"]))
        return (True, exe) if exe else (False, "Codex CLI not found (npm i -g @openai/codex, then `codex login` → Sign in with ChatGPT)")

    def _complete(self, system, user, schema, images, effort):
        prefix = _cli_prefix(self.cfg, self.exe())
        if not prefix:
            raise ProviderError("codex CLI not installed")
        with tempfile.TemporaryDirectory(prefix="prepro-codex-") as td:
            sp = Path(td) / "schema.json"
            sp.write_text(json.dumps(schema), encoding="utf-8")
            outp = Path(td) / "last.txt"
            cmd = [*prefix, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--output-schema", str(sp), "-o", str(outp)]
            for p in images:
                cmd += ["-i", str(p)]
            if self.cfg.model:
                cmd += ["-m", self.cfg.model]
            cmd.append("-")
            p = _run_cli(cmd, f"{system}\n\n{user}", cwd=td, timeout=float(self.cfg.extra.get("timeout", 900)))
            txt = outp.read_text(encoding="utf-8") if outp.exists() else p.stdout
        if p.returncode != 0 and not txt.strip():
            msg = (p.stderr or p.stdout)[-400:]
            raise ProviderError(("plan usage limit reached: " if "limit" in msg.lower() else "codex error: ") + msg)
        return Reply(data=_parse_json(txt), usage=Usage(plan_usage=True), raw=txt[-2000:], model=self.cfg.model or "codex")


@dataclass
class GeminiCLI(Provider):
    """The user's own Gemini CLI, signed in with their Google account (Google's own login, Google AI Pro limits).
    Headless: the prompt on stdin, ``--output-format json`` (the reply is under "response"); contact sheets are
    copied into an empty temp folder and attached with Gemini CLI's ``@file`` references. We never read tokens."""

    def exe(self) -> str | None:
        from ..accounts import find_cli

        return self.cfg.extra.get("path") or find_cli("gemini")

    def available(self) -> tuple[bool, str]:
        exe = self.exe()
        if self.cfg.extra.get("command"):
            return True, " ".join(map(str, self.cfg.extra["command"]))
        return (True, exe) if exe else (False, "Gemini CLI not found (npm install -g @google/gemini-cli, then run `gemini` once to sign in)")

    def _complete(self, system, user, schema, images, effort):
        prefix = _cli_prefix(self.cfg, self.exe())
        if not prefix:
            raise ProviderError("gemini CLI not installed")
        with tempfile.TemporaryDirectory(prefix="prepro-gemini-") as td:
            refs = []
            for i, p in enumerate(images):
                dst = Path(td) / f"sheet_{i}{p.suffix}"
                shutil.copy(p, dst)
                refs.append(f"@{dst.name}")
            prompt = (f"{system}\n\n{user}\n\nAnswer with one JSON object and nothing else. It must match this JSON Schema:\n"
                      f"{json.dumps(schema)}")
            if refs:
                prompt += "\n\nContact sheets to look at: " + " ".join(refs)
            cmd = [*prefix, "--output-format", "json"]
            if self.cfg.model:
                cmd += ["-m", self.cfg.model]
            p = _run_cli(cmd, prompt, cwd=td, timeout=float(self.cfg.extra.get("timeout", 900)))
        out = p.stdout.strip()
        try:
            res = json.loads(out[out.find("{"):]) if "{" in out else {}
        except json.JSONDecodeError:
            res = {}
        err = res.get("error")
        if p.returncode != 0 or err or "response" not in res:
            msg = str((err or {}).get("message") if isinstance(err, dict) else err or p.stderr or out)[-400:]
            if GEMINI_CLI_ENDED in msg:
                raise ProviderError(GEMINI_CLI_ENDED_WORDS)
            raise ProviderError(("plan usage limit reached: " if ("quota" in msg.lower() or "limit" in msg.lower()) else "gemini CLI error: ") + msg)
        data = _parse_json(str(res.get("response", "")))
        toks = {"input": 0, "output": 0}
        for m in ((res.get("stats") or {}).get("models") or {}).values():
            t = m.get("tokens") or {}
            toks["input"] += int(t.get("prompt", 0) or 0)
            toks["output"] += int(t.get("candidates", 0) or 0)
        return Reply(data=data, usage=Usage(toks["input"], toks["output"], plan_usage=True), raw=out[-2000:], model=self.cfg.model or "gemini-cli")


# Google stopped serving Gemini CLI to personal accounts (free, Google AI Pro, Ultra) on 18 June 2026; its sign-in now
# fails with this message, and the Antigravity CLI is Google's replacement.
GEMINI_CLI_ENDED = "no longer supported for Gemini Code Assist for individuals"
GEMINI_CLI_ENDED_WORDS = ("Google stopped Gemini CLI for personal Google accounts on 18 June 2026. PrePro now uses Google's "
                          "Antigravity CLI for your Google account: Settings → AI editor → Gemini → Install, then Sign in.")


@dataclass
class AntigravityCLI(Provider):
    """The user's own Antigravity CLI (`agy`), signed in with their Google account (free, Google AI Pro or Ultra):
    Google's replacement for Gemini CLI. Headless, as Google documents it: one ``{"event": "user", …}`` line on stdin
    with ``--input-format stream-json --output-format stream-json`` (no command-line length limit, UTF-8 intact), the
    answer constrained by ``--json-schema`` and read from the ``result`` event's ``structured_output``. It runs in an
    empty temp folder and nothing is pre-approved, so it can't touch files. Attaching pictures isn't documented, so this
    connector doesn't get contact sheets (the AI editor works from the shot descriptions). We never read tokens."""

    sees_images = False

    def exe(self) -> str | None:
        from ..accounts import find_cli

        return self.cfg.extra.get("path") or find_cli("agy")

    def available(self) -> tuple[bool, str]:
        exe = self.exe()
        if self.cfg.extra.get("command"):
            return True, " ".join(map(str, self.cfg.extra["command"]))
        return (True, exe) if exe else (False, "Antigravity CLI not found (Settings → AI editor → Gemini → Install, then Sign in)")

    def _complete(self, system, user, schema, images, effort):
        prefix = _cli_prefix(self.cfg, self.exe())
        if not prefix:
            raise ProviderError("Antigravity CLI not installed")
        prompt = (f"{system}\n\n{user}\n\nAnswer with one JSON object and nothing else. It must match this JSON Schema:\n"
                  f"{json.dumps(schema)}")
        line = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
        with tempfile.TemporaryDirectory(prefix="prepro-agy-") as td:
            schema_file = Path(td) / "answer.schema.json"
            schema_file.write_text(json.dumps(schema), encoding="utf-8")
            cmd = [*prefix, "--input-format", "stream-json", "--output-format", "stream-json", "--json-schema", str(schema_file),
                   "--print-timeout", f"{int(float(self.cfg.extra.get('timeout', 900)))}s"]
            if self.cfg.model:
                cmd += ["--model", self.cfg.model]
            if effort in ("low", "medium", "high"):
                cmd += ["--effort", effort]
            p = _run_cli(cmd, line, cwd=td, timeout=float(self.cfg.extra.get("timeout", 900)) + 30)
        result: dict = {}
        for raw in p.stdout.splitlines():
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "result":
                result = ev.get("result") or {}
            elif not result and ("structured_output" in ev or "response" in ev):     # the plain json envelope
                result = ev
        err = result.get("error")
        if p.returncode != 0 or err or not (result.get("structured_output") or result.get("response")):
            msg = str((err or {}).get("message") if isinstance(err, dict) else err or p.stderr or p.stdout)[-400:]
            low = msg.lower()
            if "authentication required" in low or "not signed in" in low or "sign in" in low:
                raise ProviderError("not signed in to Antigravity yet: Settings → AI editor → Gemini → Sign in")
            raise ProviderError(("plan usage limit reached: " if ("quota" in low or "limit" in low) else "Antigravity CLI error: ") + msg)
        data = result.get("structured_output")
        if not isinstance(data, dict):
            data = _parse_json(str(result.get("response", "")))
        u = result.get("usage") or {}
        return Reply(data=data, usage=Usage(int(u.get("input_tokens", 0) or 0), int(u.get("output_tokens", 0) or 0), plan_usage=True),
                     raw=p.stdout[-2000:], model=self.cfg.model or "antigravity")


# ---------------------------------------------------------------- API keys
@dataclass
class AnthropicAPI(Provider):
    def available(self) -> tuple[bool, str]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "pip install prepro[ai]"
        key = get_secret("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        return (True, "API key set") if key else (False, "no Anthropic API key (prepro brains key anthropic)")

    def _complete(self, system, user, schema, images, effort):
        import anthropic

        client = anthropic.Anthropic(api_key=get_secret("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY"))
        model = self.cfg.model or DEFAULT_MODEL["anthropic"]
        content: list[dict] = []
        for p in images:
            mt, data = _img_b64(p)
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
        content.append({"type": "text", "text": user})
        kwargs = dict(
            model=model, max_tokens=32000, system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            thinking={"type": "adaptive"}, cache_control={"type": "ephemeral"},
        )
        if model in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"):
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            with client.beta.messages.stream(**kwargs) as st:
                msg = st.get_final_message()
        except anthropic.RateLimitError as e:
            raise ProviderError(f"rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {str(e)[:300]}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"cannot reach the Anthropic API: {e}") from e
        if msg.stop_reason == "refusal":
            raise ProviderError("the model declined this request")
        text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
        u = msg.usage
        pin, pout = PRICES.get(model, (4.0, 20.0))
        cached = int(getattr(u, "cache_read_input_tokens", 0) or 0)
        usd = (u.input_tokens * pin + cached * pin * 0.05 + u.output_tokens * pout) / 1e6
        return Reply(data=_parse_json(text), usage=Usage(u.input_tokens, u.output_tokens, cached, round(usd, 5)), raw=text[-2000:], model=model)


@dataclass
class OpenAICompatible(Provider):
    """OpenAI, xAI (Grok) and OpenRouter through the official OpenAI SDK (their documented API shape)."""

    BASE = {"openai": None, "xai": "https://api.x.ai/v1", "openrouter": "https://openrouter.ai/api/v1"}
    KEY = {"openai": "openai_api_key", "xai": "xai_api_key", "openrouter": "openrouter_api_key"}

    def available(self) -> tuple[bool, str]:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False, "pip install prepro[ai]"
        if not self.cfg.model:
            return False, "choose a model (prepro brains add … --model …)"
        return (True, "API key set") if get_secret(self.KEY[self.kind]) else (False, f"no {self.kind} API key")

    def _complete(self, system, user, schema, images, effort):
        import openai

        client = openai.OpenAI(api_key=get_secret(self.KEY[self.kind]), base_url=self.cfg.base_url or self.BASE[self.kind])
        content: list[dict] = [{"type": "text", "text": user}]
        for p in images:
            mt, data = _img_b64(p)
            content.append({"type": "image_url", "image_url": {"url": f"data:{mt};base64,{data}"}})
        extra = {"provider": {"data_collection": "deny"}} if self.kind == "openrouter" else None
        try:
            r = client.chat.completions.create(
                model=self.cfg.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                response_format={"type": "json_schema", "json_schema": {"name": "plan", "schema": schema, "strict": False}},
                extra_body=extra,
            )
        except openai.APIError as e:
            raise ProviderError(f"{self.kind} API error: {str(e)[:300]}") from e
        text = r.choices[0].message.content or ""
        u = r.usage
        return Reply(data=_parse_json(text), usage=Usage(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)),
                     raw=text[-2000:], model=self.cfg.model or "")


@dataclass
class GeminiAPI(Provider):
    def available(self) -> tuple[bool, str]:
        try:
            from google import genai  # noqa: F401
        except ImportError:
            return False, "pip install prepro[ai]"
        if not self.cfg.model:
            return False, "choose a Gemini model (free tier: a Flash / Flash-Lite model)"
        return (True, "API key set") if get_secret("gemini_api_key") else (False, "no Gemini API key (free from Google AI Studio)")

    def _complete(self, system, user, schema, images, effort):
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=get_secret("gemini_api_key"))
        parts = [types.Part.from_bytes(data=p.read_bytes(), mime_type=_img_b64(p)[0]) for p in images] + [user]
        cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", response_json_schema=schema)
        try:
            r = client.models.generate_content(model=self.cfg.model, contents=parts, config=cfg)
        except Exception as e:
            raise ProviderError(f"Gemini API error: {str(e)[:300]}") from e
        text = r.text or ""
        um = getattr(r, "usage_metadata", None)
        return Reply(data=_parse_json(text), usage=Usage(getattr(um, "prompt_token_count", 0) or 0, getattr(um, "candidates_token_count", 0) or 0),
                     raw=text[-2000:], model=self.cfg.model or "")


@dataclass
class OllamaLocal(Provider):
    def available(self) -> tuple[bool, str]:
        try:
            import ollama

            ollama.list()
            return True, "Ollama running"
        except Exception:
            return False, "Ollama not running (https://ollama.com) — local and private"

    def _complete(self, system, user, schema, images, effort):
        import ollama

        msg = {"role": "user", "content": user}
        if images:
            msg["images"] = [str(p) for p in images]
        r = ollama.chat(model=self.cfg.model or DEFAULT_MODEL["ollama"], messages=[{"role": "system", "content": system}, msg], format=schema)
        text = r["message"]["content"]
        return Reply(data=_parse_json(text), usage=Usage(int(r.get("prompt_eval_count", 0) or 0), int(r.get("eval_count", 0) or 0)),
                     raw=text[-2000:], model=self.cfg.model or "")


@dataclass
class StubProvider(Provider):
    """Replays recorded responses ({pass_name: response}) — for tests and offline demos."""

    responses: dict = field(default_factory=dict)

    def available(self) -> tuple[bool, str]:
        return True, "stub"

    def _complete(self, system, user, schema, images, effort):
        key = next((k for k in self.responses if k in user), None) or ("*" if "*" in self.responses else None)
        data = self.responses.get(key) if key else None
        if callable(data):
            data = data(system, user, schema)
        if data is None:
            raise ProviderError("no recorded response")
        return Reply(data=json.loads(json.dumps(data)), usage=Usage(len(user) // 4, 200), model="stub")


KINDS = {"claude_code": ClaudeCodeCLI, "codex": CodexCLI, "gemini_cli": GeminiCLI, "antigravity_cli": AntigravityCLI,
         "anthropic": AnthropicAPI, "openai": OpenAICompatible,
         "xai": OpenAICompatible, "openrouter": OpenAICompatible, "gemini": GeminiAPI, "ollama": OllamaLocal, "stub": StubProvider}


def make_provider(name: str, cfg: ConnectorConfig, *, sent_dir: Path | None = None, privacy: str = "thumbs") -> Provider:
    cls = KINDS.get(cfg.kind)
    if cls is None:
        raise ProviderError(f"unknown connector kind {cfg.kind!r}; choose from {sorted(KINDS)}")
    return cls(name=name, cfg=cfg, sent_dir=sent_dir, privacy=privacy)


def detect_connectors() -> dict[str, ConnectorConfig]:
    """What this PC already has: subscription CLIs (on PATH or where their installers put them) and API keys."""
    from ..accounts import KEYS, PLANS, find_cli

    out: dict[str, ConnectorConfig] = {}
    for p in PLANS:
        exe = find_cli(p["exe"])
        if exe:
            out[p["id"]] = ConnectorConfig(kind=p["kind"], extra={"path": exe})
    for k in KEYS:
        if get_secret(k["secret"]) or (k["kind"] == "anthropic" and os.environ.get("ANTHROPIC_API_KEY")):
            out[k["id"]] = ConnectorConfig(kind=k["kind"], model=k["model"], extra={"tier": "free"} if k["kind"] == "gemini" else {})
    return out
