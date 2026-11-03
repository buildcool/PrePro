# Handoff (read this first when resuming)

**Repo:** github.com/buildcool/PrePro · work on `dev`, releases fast-forward `main` + tag.
**Plan:** `docs/PLAN.md` (approved). **Release ladder:** v0.1 offline engine → v0.2 AI brain + exports →
v0.3 review UI → v0.4 desktop app → v0.5+ Phase 2 → v1.0.

## Current state
- M0 in progress: scaffold, schema, media probe, project scan, synthetic fixture generator, real test-media
  fetcher, CLI (`version`, `doctor`, `demo`, `testmedia`).

## Environment notes (cloud container)
- Network policy blocks huggingface.co (Whisper models), wikimedia, archive.org, pexels/pixabay/freesound,
  blender.org, youtube. Reachable: PyPI, npm, apt, raw.githubusercontent.com, Google Fonts.
- So Whisper ASR cannot be exercised here; PocketSphinx (bundled English model) and transcript sidecars
  are used for end-to-end tests. Never report Whisper results as tested here.
- Dev setup: `uv venv --python 3.12 .venv && uv pip install --python .venv -e ".[asr,ai,geo,dev]"`;
  apt: `espeak-ng melt sox fonts-noto-core`.

## Next steps
See the task list in `docs/PLAN.md` §8/§12 and `CHANGELOG.md`.
