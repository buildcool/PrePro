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
        if self.privacy != "thumbs":
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
@dataclass
class ClaudeCodeCLI(Provider):
    """The user's own Claude Code CLI, signed in with their Claude plan (Anthropic's own login).
    We run the unmodified binary headless in an empty temp folder; we never read or store tokens."""

    def exe(self) -> str | None:
        return self.cfg.extra.get("path") or shutil.which("claude")

    def available(self) -> tuple[bool, str]:
        exe = self.exe()
        return (True, exe) if exe else (False, "Claude Code CLI not found (npm i -g @anthropic-ai/claude-code, then run `claude` once to sign in)")

    def _complete(self, system, user, schema, images, effort):
        exe = self.exe()
        if not exe:
            raise ProviderError("claude CLI not installed")
        with tempfile.TemporaryDirectory(prefix="prepro-cc-") as td:
            names = []
            for i, p in enumerate(images):
                dst = Path(td) / f"sheet_{i}{p.suffix}"
                shutil.copy(p, dst)
                names.append(dst.name)
            prompt = user
            if names:
                prompt += "\n\nContact sheets to look at (read them with the Read tool): " + ", ".join(names)
            cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema), "--system-prompt", system,
                   "--permission-mode", "dontAsk"]
            cmd += ["--allowedTools", "Read"] if names else ["--allowedTools", ""]
            if self.cfg.model:
                cmd += ["--model", self.cfg.model]
            if self.cfg.max_usd_per_project:
                cmd += ["--max-budget-usd", str(self.cfg.max_usd_per_project)]
            env = dict(os.environ)
            env.pop("ANTHROPIC_API_KEY", None) if self.cfg.extra.get("plan_only", True) else None
            p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=td, env=env,
                               timeout=float(self.cfg.extra.get("timeout", 900)))
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
        return self.cfg.extra.get("path") or shutil.which("codex")

    def available(self) -> tuple[bool, str]:
        exe = self.exe()
        return (True, exe) if exe else (False, "Codex CLI not found (npm i -g @openai/codex, then `codex login` → Sign in with ChatGPT)")

    def _complete(self, system, user, schema, images, effort):
        exe = self.exe()
        if not exe:
            raise ProviderError("codex CLI not installed")
        with tempfile.TemporaryDirectory(prefix="prepro-codex-") as td:
            sp = Path(td) / "schema.json"
            sp.write_text(json.dumps(schema), encoding="utf-8")
            outp = Path(td) / "last.txt"
            cmd = [exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--output-schema", str(sp), "-o", str(outp)]
            for p in images:
                cmd += ["-i", str(p)]
            if self.cfg.model:
                cmd += ["-m", self.cfg.model]
            cmd.append("-")
            p = subprocess.run(cmd, input=f"{system}\n\n{user}", capture_output=True, text=True, cwd=td,
                               timeout=float(self.cfg.extra.get("timeout", 900)))
            txt = outp.read_text(encoding="utf-8") if outp.exists() else p.stdout
        if p.returncode != 0 and not txt.strip():
            msg = (p.stderr or p.stdout)[-400:]
            raise ProviderError(("plan usage limit reached: " if "limit" in msg.lower() else "codex error: ") + msg)
        return Reply(data=_parse_json(txt), usage=Usage(plan_usage=True), raw=txt[-2000:], model=self.cfg.model or "codex")


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


KINDS = {"claude_code": ClaudeCodeCLI, "codex": CodexCLI, "anthropic": AnthropicAPI, "openai": OpenAICompatible,
         "xai": OpenAICompatible, "openrouter": OpenAICompatible, "gemini": GeminiAPI, "ollama": OllamaLocal, "stub": StubProvider}


def make_provider(name: str, cfg: ConnectorConfig, *, sent_dir: Path | None = None, privacy: str = "thumbs") -> Provider:
    cls = KINDS.get(cfg.kind)
    if cls is None:
        raise ProviderError(f"unknown connector kind {cfg.kind!r}; choose from {sorted(KINDS)}")
    return cls(name=name, cfg=cfg, sent_dir=sent_dir, privacy=privacy)


def detect_connectors() -> dict[str, ConnectorConfig]:
    """What this PC already has: subscription CLIs on PATH, keys in the keychain, a running Ollama."""
    out: dict[str, ConnectorConfig] = {}
    if shutil.which("claude"):
        out["claude-plan"] = ConnectorConfig(kind="claude_code")
    if shutil.which("codex"):
        out["chatgpt-plan"] = ConnectorConfig(kind="codex")
    if get_secret("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY"):
        out["claude-api"] = ConnectorConfig(kind="anthropic", model=DEFAULT_MODEL["anthropic"])
    if get_secret("gemini_api_key"):
        out["gemini"] = ConnectorConfig(kind="gemini", model=None, extra={"tier": "free"})
    return out
