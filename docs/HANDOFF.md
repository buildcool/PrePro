# Handoff (read this first when resuming)

**Repo:** github.com/buildcool/PrePro · day-to-day work on `dev`; releases fast-forward `main` + tag `vX.Y.Z`
(the `release` workflow creates the tag, builds the wheel and publishes a GitHub Release from `docs/releases/<tag>.md` whenever main carries a new version — tag pushes from the container are denied by policy, HTTP 403).
**Plan:** `docs/PLAN.md` (approved). **Release ladder:** v0.1 offline engine → v0.2 AI brain + exports →
v0.3 review UI → v0.4 desktop app → v0.5+ Phase 2 → v1.0.

## Current state
- v0.5.0: Phase 2 has started.
  - `repurpose.py`: Long → Shorts.
  - `packaging.py`: thumbnails, titles, chapters, description.
  - `style.py`: Style DNA from `style/` reference videos → knobs (pace, `shot_len`, `tightness`, captions,
    effects, length).
- v0.4.0: M0–M6 done. The desktop app has three parts:
  - `desktop/`: Electron main/preload/splash + electron-builder config
  - `scripts/build_engine.py`: PyInstaller, one folder → `dist/prepro-engine`
  - CI (`.github/workflows/desktop.yml`, called by `release.yml`): AppImage + .deb + NSIS with bundled,
    checksum-verified ffmpeg
- v0.3.0: M0–M5. The review app is `prepro ui`:
  - `server/app.py`: FastAPI with jobs + SSE, token, Host guard
  - `ui/`: React + Vite + TS; the build goes to `src/prepro/server/static` and is committed
  - `revise.py`: suggestion keys, ops replay, comment rules, AI revise pass
- v0.2.0: M0–M4.
  - `prepro demo|testmedia|analyze|directions|build|export|brains|doctor` work end to end.
  - Basic (rules) brain, or an AI brain through any connector: Claude Code CLI, Codex CLI, Anthropic, OpenAI,
    xAI, OpenRouter, Gemini, Ollama.
  - Exports: FCP7 XML, OTIO/.kdenlive, MLT, phone pack, SRT/VTT, ProRes 4444 overlay, HTML editor brief.
  - See `CHANGELOG.md` and `docs/QA.md` (taste log).
- Main modules:
  - `analyze/` (pipeline, asr, speech, visual, sound, context)
  - `brain/basic.py` (rules) and `brain/ai.py` (AI passes)
  - `brain/providers/` (connectors, privacy, sent log)
  - `brief/` (parse, resolve), `assist/` (music, looks), `timeline/` (compiler, captions)
  - `lint/` (editlint, critic)
  - `export/` (render, nle = FCP7/OTIO/MLT/captions, package = phone pack + editor brief + export_all)
  - `engine.py` (high-level API)
  - `knowledge/` (playbooks, memes, hooks, emotions, sfx, broll concepts, constitution)
- Known gaps:
  - **Story re-ordering from the AI critic is not auto-applied.** It is only reported.
  - **FCP7 Basic Motion centre values** follow the Premiere convention (offset ÷ sequence size, per axis). This
    needs a real import check, as does the `.kdenlive` file.
  - **MLT files carry their `<profile>`.** Shotcut uses it; the `melt` CLI needs `-profile` (see the M4 test).

## How to test
- `uv pip install --python .venv -e ".[asr,ai,geo,export,dev]"`; apt `espeak-ng melt sox fonts-noto-core`.
- UI: `npm --prefix ui install && npm --prefix ui run build`. The browser test (`tests/ui`, slow) needs node +
  playwright.
- Run tests with `.venv/bin/pytest` (pytest's `pythonpath` puts the repo root on `sys.path` for `tests.conftest`).
- `.venv/bin/prepro testmedia fetch` (real media into ~/.cache/prepro/testmedia), then
  `.venv/bin/python -m pytest tests -q` (synthetic shoots are cached in /tmp/prepro-test-shoots).
- Review storyboards in `<shoot>/.prepro/qa/` after `prepro build`.

## Environment notes (cloud container)
- Network policy blocks huggingface.co (Whisper models), wikimedia, archive.org, pexels/pixabay/freesound,
  blender.org, youtube. Reachable: PyPI, npm, apt, raw.githubusercontent.com, Google Fonts.
- So Whisper ASR cannot be exercised here; PocketSphinx (bundled English model) and transcript sidecars
  are used for end-to-end tests. Never report Whisper results as tested here.
- The `gh` CLI token is invalid in the container. git push works through the proxy, and the repo is public,
  so read CI status and job logs anonymously:
  - status: `curl https://api.github.com/repos/buildcool/PrePro/actions/runs`
  - logs: `.../actions/jobs/<id>/logs`
- Releases are created by the workflow on `main`.

## Desktop notes
- The frozen engine is about 810 MB unpacked:
  - llvmlite 153 MB (numba, used by librosa)
  - PyAV's ffmpeg 126 MB (used by faster-whisper)
  - OpenCV 150 MB
  - ctranslate2 140 MB
- Ideas to trim it:
  - stub `av` (we feed Whisper numpy audio)
  - drop pocketsphinx from desktop builds
  - UPX-compress on Windows
- OTIO plugin adapters must ship as `.py` files: OTIO loads them by path.
- electron-builder needs an `author.email`. It is set to `buildcool@users.noreply.github.com`; replace it with the
  real contact before public distribution.
- Not code-signed. Windows SmartScreen will warn until there is a signing certificate.
- ffmpeg is GPL. It ships as separate executables with its licence text, which is mere aggregation. A legal
  review is still needed before commercial distribution.

## Next steps
1. **Phase 2** by value; see `docs/PLAN.md` §8. Next:
   - AI titles/thumbnail text through the brain, as a `package` pass
   - stock/GIF search
   - VO recording + scratch TTS
   - privacy blur
2. UI ideas not done yet:
   - drag-to-trim on the timeline
   - a waveform in the voice lane
   - a meme/music browser with alternatives
   - saved brief templates
   - a creative-freedom slider in the brief step
