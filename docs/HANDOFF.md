# Handoff (read this first when resuming)

**Repo:** github.com/buildcool/PrePro · day-to-day work on `dev`; releases fast-forward `main` + tag `vX.Y.Z`
(the `release` workflow builds the wheel and publishes a GitHub Release from `docs/releases/<tag>.md`).
**Plan:** `docs/PLAN.md` (approved). **Release ladder:** v0.1 offline engine → v0.2 AI brain + exports →
v0.3 review UI → v0.4 desktop app → v0.5+ Phase 2 → v1.0.

## Current state
- v0.1.0: M0–M2 done. `prepro demo|testmedia|analyze|directions|build|doctor` work end to end with the
  rules-only Basic brain. See `CHANGELOG.md` and `docs/QA.md` (taste log).
- Main modules: `analyze/` (pipeline, asr, speech, visual, sound, context), `brain/basic.py`,
  `brief/` (parse, resolve), `assist/` (music, looks), `timeline/` (compiler, captions), `lint/` (editlint,
  critic), `export/render.py`, `engine.py` (high-level API), `knowledge/` (playbooks, memes, hooks…).

## How to test
- `uv pip install --python .venv -e ".[asr,ai,geo,dev]"`; apt `espeak-ng melt sox fonts-noto-core`.
- `.venv/bin/prepro testmedia fetch` (real media into ~/.cache/prepro/testmedia), then
  `.venv/bin/python -m pytest tests -q` (synthetic shoots are cached in /tmp/prepro-test-shoots).
- Review storyboards in `<shoot>/.prepro/qa/` after `prepro build`.

## Environment notes (cloud container)
- Network policy blocks huggingface.co (Whisper models), wikimedia, archive.org, pexels/pixabay/freesound,
  blender.org, youtube. Reachable: PyPI, npm, apt, raw.githubusercontent.com, Google Fonts.
- So Whisper ASR cannot be exercised here; PocketSphinx (bundled English model) and transcript sidecars
  are used for end-to-end tests. Never report Whisper results as tested here.
- `gh` CLI token is invalid in the container: git push works through the proxy, GitHub API calls do not —
  releases are created by the tag-triggered workflow.

## Next steps
1. M3 AI brain: provider contract + router; connectors (Claude Code CLI, Codex CLI, Anthropic API,
   OpenAI, Gemini, xAI, OpenRouter, Ollama); passes (vision tags, director, story, polish, critic, brief,
   revise); privacy levels + sent-data log; cost meter; `prepro brains --compare`.
2. M4 exports: FCP7 XML (bins/markers/motion/speed/levels), OTIO, MLT (melt-verified), phone pack, SRT/VTT/ASS,
   caption overlay (ProRes 4444), HTML editor brief.
3. M5 UI, M6 desktop — see `docs/PLAN.md` §8.
