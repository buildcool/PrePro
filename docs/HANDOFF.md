# Handoff (read this first when resuming)

**Repo:** github.com/buildcool/PrePro · day-to-day work on `dev`; releases fast-forward `main` + tag `vX.Y.Z`
(the `release` workflow creates the tag, builds the wheel and publishes a GitHub Release from `docs/releases/<tag>.md` whenever main carries a new version — tag pushes from the container are denied by policy, HTTP 403).
**Plan:** `docs/PLAN.md` (approved). **Release ladder:** v0.1 offline engine → v0.2 AI brain + exports →
v0.3 review UI → v0.4 desktop app → v0.5+ Phase 2 → v1.0.

## Current state
- **v0.7.0: the gaming pack + Windows fixes.** The first full run on a Windows PC; see QA "v0.7 on Windows".
  - Gaming: `analyze/sound.impacts`, `BasicBrain._game_events` / `_story_gaming` (cold open, plays with build-up,
    replay, payoff), callouts; the compiler handles talky shot windows (full volume, captioned) and the `replay` role.
  - Windows fixes:
    - pocketsphinx pinned `<5.1`
    - a speech-failure warning (`asr.failed_note`)
    - Whisper picks the GPU only when cuBLAS/cuDNN load, with a CPU fallback (`asr.gpu_unusable`, `whisper_device`)
    - CLI connectors resolve npm `.cmd` shims (`providers.launch_command`), use `--system-prompt-file`, and pass
      UTF-8 bytes
    - espeak-ng fixtures read their text from a UTF-8 file
  - Desktop CI: the Linux ffmpeg download retries, then falls back to BtbN. v0.6.0 has no Linux installers; re-run
    its desktop job from the Actions tab if they're needed.
  - Verified on Windows: every engine test file, one at a time, slow render tests included.
    - Real footage passed with PocketSphinx and with Whisper.
    - `scripts/check_asr.py`: Whisper small 0 % WER on JFK, PocketSphinx 50 %.
    - Not run on Windows: the browser UI test (needs Playwright) and the desktop smoke test (Linux/Xvfb).
- **In progress (branch `v0.8-wip`, merged into `dev` after the v0.7.0 release): GPU video encoding.**
  `media/encoders.py` picks NVENC → Quick Sync → AMF after a real test encode, else x264; a GPU failure mid-render
  redoes that piece on the CPU. `Settings.render.encoder` / `PREPRO_ENCODER` = auto|cpu|nvenc|qsv|amf.
- v0.6.0: Editor's Craft v2 (released).
  - `knowledge/craft.yaml` technique cards
  - J/L splits (`compiler._apply_split_edits`), open loops and re-hooks (`basic._open_loop`/`_rehooks`)
  - dead-zone fixes (`editlint._fix_deadzone`), comedy timing (`speech_pieces` lead/hold) and comedy detection
  - montage flow + loop endings (`basic._flow_order`), cringe guard (`lint/ghinn.py`), path previews
    (`previews.py`)
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

## Set up a PC
Run one test file per command; all at once can run out of memory. Use `.venv\Scripts\` on Windows.
- **Linux:** apt `espeak-ng melt sox fonts-noto-core ffmpeg`, then the commands below.
- **Windows** (done on the current dev PC, see *Environment notes*):
  - `winget install astral-sh.uv eSpeak-NG.eSpeak-NG`, and put `C:\Program Files\eSpeak NG` on PATH
  - ffmpeg via `choco install ffmpeg`
  - Shotcut for `melt` (optional; only the MLT render test needs it)
  - without espeak-ng, the speech-based tests are skipped, not run
```bash
git clone https://github.com/buildcool/PrePro.git && cd PrePro && git checkout dev
uv venv --seed --python 3.12 .venv
uv pip install --python .venv -e ".[asr,ai,geo,export,dev]"
.venv/bin/prepro doctor
.venv/bin/prepro testmedia fetch
.venv/bin/prepro models --download small                  # Whisper; ~480 MB from huggingface.co
.venv/bin/python scripts/check_asr.py                     # word error rate per recogniser on real speech
.venv/bin/pytest tests/e2e/test_p4_gaming.py -m "not live" # one file per command
```

## Release
1. Set the version in `pyproject.toml`, `src/prepro/__init__.py`, `desktop/package.json` (and the two root entries in
   `desktop/package-lock.json`).
2. In `CHANGELOG.md`, turn `## [Unreleased]` into `## [X.Y.Z] — <date>`; write `docs/releases/vX.Y.Z.md`.
3. Commit and push `dev`, wait for CI to be green on Ubuntu and Windows.
4. `git push origin dev:main`. The `release` workflow tags it and builds the wheel, sdist and installers. Check that
   the run *and* its desktop jobs succeeded and that the release has the `.exe`, `.AppImage` and `.deb`.

## How to test
- `uv pip install --python .venv -e ".[asr,ai,geo,export,dev]"`; apt `espeak-ng melt sox fonts-noto-core`.
- UI: `npm --prefix ui install && npm --prefix ui run build`. The browser test (`tests/ui`, slow) needs node +
  playwright.
- Run tests with `.venv/bin/pytest` (pytest's `pythonpath` puts the repo root on `sys.path` for `tests.conftest`).
- `.venv/bin/prepro testmedia fetch` (real media into ~/.cache/prepro/testmedia), then
  `.venv/bin/python -m pytest tests -q` (synthetic shoots are cached in /tmp/prepro-test-shoots).
- Review storyboards in `<shoot>/.prepro/qa/` after `prepro build`.

## Environment notes (Windows dev PC, from v0.7)
- Windows 11, i9-14900HX, 16 GB, RTX 4070 (driver only: no cuBLAS, so Whisper runs on the CPU), Intel UHD.
- PyPI and GitHub (Fastly) download at about 200 KB/s here; Hugging Face is fast (about 8 MB/s). uv puts every
  download on one HTTP/2 connection. For big installs, fetch the large wheels in parallel with `curl -Z`, check them
  against the PyPI JSON sha256, `uv pip install --no-deps` them, then run the normal install.
- C: has little free space; caches go on D:: `UV_CACHE_DIR`, `PREPRO_TEST_SHOOTS` (a path with a space, on purpose),
  `TMP`/`TEMP`.
- MinGW gcc is on PATH and MSVC is not. Anything compiled at install time is built with MinGW and may not load in
  Python, which is how pocketsphinx broke.
- The `gh` CLI isn't installed. Pushes use the stored `buildcool` credential (remote URL
  `https://buildcool@github.com/...`); commits are authored as `Claude <noreply@anthropic.com>` like the rest of the
  history.
- CI status comes from the public API (`/repos/buildcool/PrePro/actions/runs`). Job logs need admin rights, so they
  can't be read anonymously.

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
0. **v0.8.0 in progress:** GPU video encoding (branch `v0.8-wip`), then podcast/talking-head speaker switching
   (a 9:16 crop that follows whoever is talking, switching at sentence ends with a minimum hold, so Shorts cut from
   a two-person podcast never sit on the empty gap between the speakers).
1. **Genre packs, more:**
   - gaming: HUD/kill-feed flashes, facecam enlarge on big reactions, fail memes
   - lifestyle "satisfying moment" detection
   - talking-head/podcast speaker switching
2. **Phase 2**, more:
   - AI titles/thumbnail text through the brain, as a `package` pass
   - stock/GIF search
   - VO recording + scratch TTS
   - privacy blur
3. UI ideas not done yet:
   - drag-to-trim on the timeline
   - a waveform in the voice lane
   - a meme/music browser with alternatives
   - saved brief templates
   - a creative-freedom slider in the brief step
