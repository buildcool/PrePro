# Changelog

All notable changes to PrePro are recorded here. Versions follow the release ladder in `docs/PLAN.md` §12.

## [Unreleased]

## [0.6.0] — 2026-11-04
### Added — Editor's Craft v2 (what top editors do; every technique is a reasoned, rejectable decision)
- **Technique cards** (`knowledge/craft.yaml`): one card per technique with its trigger, recipe, "not when"
  guardrails, budget and source. The rules engine follows them, they go into the AI brain's system prompt, and the
  critic checks against them.
- **J/L split edits.** The voice starts under the previous shot (J) or runs on under the next picture (L) at
  talking ↔ B-roll and place changes.
  - Only the picture cut moves, so words are never clipped.
  - Amounts are set per genre; comedy and hype stay crisp.
  - Exported to every NLE as is.
- **Open loops.**
  - A 1–1.3 s flash-forward of the payoff right after the hook, with "later…" on screen.
  - It must be paid off later in the cut; the new `open_loop_unpaid` lint removes it otherwise.
  - Rejecting it keeps the payoff.
- **Re-hooks.** In long talks, at the start of a later part, the part's own number/question/"but" line goes on
  screen (with a soft riser). Shorts get one every 20–30 s after the first 30 s; long-form every 2–3 minutes. The
  text is readable and stays up long enough.
- **Dull stretches get fixed, not just flagged:**
  - talking: a same-place B-roll cutaway, else a punch-in on the strongest word
  - wordless B-roll: a gentle speed-up
  - aesthetic holds are left alone
- **Jump cuts on talking heads alternate framing (100 ↔ 112 %)** on every cut, based on the framing actually on
  screen. Reframes no longer count as zoom "effects", so the over-stimulation check stopped stripping them.
- **Comedy.**
  - Detected automatically: dialogue-led footage with short punchy lines and a meme/SFX kit.
  - Punchlines are the "!" line, the comeback and the short button line.
  - A beat before each punchline and a hold after it, and the pause is never played twice.
  - The meme from your folder that matches the line goes after it ("Emotional damage." → `emotional_damage_fail.mp4`).
  - The text hook teases the premise, never the punchline.
- **Montages:**
  - moments ordered for motion/colour flow, with the same angle never back to back
  - vertical cuts end on a fresh moment of the opening image, so Shorts loop seamlessly
- **Cringe guard** (`lint/ghinn.py`). A `no_cringe` score with every failed check named:
  - empty frames
  - a repeated moment
  - effects without a reason
  - effect density beyond the genre
  - music that stops dead
  - text too short to read
  - loudness jumps
  - jump cuts without reframing
  - memes in serious moments
- **Path previews.** "Show me each path" renders the first 6 s of every direction (360p, free, local) right in its
  card.
- Shot-size lint (`samesize`). New decision filters in the review app: open loop, split, timing, loop.
### Fixed
- **Style DNA** missed captions drawn over a dark shirt. An outlined-text detector fixes it; this was a CI-only
  case with the drawn presenter.
- **A test needing espeak-ng** wasn't marked; Windows CI failed on it.

## [0.5.0] — 2026-11-04
### Added
- **Packaging** (Export → "Packaging", Review → More → "Make thumbnails & titles", `--formats package`):
  - **Thumbnails.** Three thumbnail picks of different kinds: a big clear face, the peak action moment, a striking
    shot. Each has a text mock-up at 1280×720 or 1080×1920. The text is centred on the number ("₹5000 for 3
    days", "1M views phone camera?") and never ends on "your" or "the".
  - **Titles.** Up to 5 options, at most 70 characters, built from the hook's own promise:
    - natural rewrites: "The real reason …", "How I lost $10,000 …", "Stop making these 3 editing mistakes"
    - journey titles: "Calangute → Jaipur on ₹5,000?"
    - no "(watch till the end)" clickbait
  - **YouTube chapters.** First at 0:00, 3 or more, each at least 10 s; otherwise none, with the reason. A short
    intro folds into the first real chapter.
  - **Description and hashtags.**
  - All of it also appears in the editor brief and in `packaging/packaging.md`.
- **Style DNA** (`prepro style`, Brief step → "Style DNA"). Drop 1–5 videos you like into `style/`; they are
  measured locally and never edited or uploaded.
  - **What is measured:** cut rate, shot lengths, talking share, pause lengths, music share, on-screen text share
    and length.
  - **What it sets:** pace, B-roll shot length, how tightly speech is cut, captions, effects intensity and
    target length. The creator's own knobs and brief rules still win.
  - **Checked against references with known answers:**
    - a 0.6 s-shot montage measured 95 cuts/min against a true 95
    - a captioned talking head had text on screen 100 % of the time, against 0 % for the raw clip
- The scanner keeps `style/` / `references/` videos out of the footage.
- **Speech models.** Speech models can be downloaded with real progress: Brains & privacy → Speech recognition, or
  `prepro models --download small`.
  - Before this, a fresh install never used Whisper and silently fell back to PocketSphinx.
  - The Footage step now says when the rough recogniser was used.
  - Once Whisper is available, those transcripts are redone automatically; other clips stay cached.
  - Model names map correctly (`large-v3-turbo`).
- `words_to_digits` understands "a million" / "two billion" (→ 1M / 2B).
### Fixed
- **Real footage** (new `tests/e2e/test_realmedia.py`: Intel/OpenCV sample clips, JFK speech, Kevin MacLeod music):
  - **Montage reuse.** The montage gave up after one pass over its shots, producing a 3 s "film" from three long
    clips. Long shots now yield several distinct moments.
  - **Empty moments.** Montages could cut to an empty conveyor belt or an empty parking lot. Moments are now
    chosen by activity (tracked subject / action peak), start when the subject enters, and slow-mo lands only on
    the moment with the action.
  - **Repeated moment.** The same slow-mo moment was repeated 5×. Now there is one slow-mo per shot.
  - **Montage length** now follows the variety of angles (at most 3 moments per angle). There is a new
    "film more angles" gap when there are fewer than 6.
  - **Day numbering.** Days were counted as a date span ("3082 days"). They are now distinct shooting dates, and
    dead-clock timestamps are ignored. Cached analyses get only this cheap stage re-run (`CONTEXT_VERSION`).
- **CI collection had failed since M0.** The bare `pytest` script couldn't import `tests.conftest`; pytest now
  sets `pythonpath`. CI status is now checked from the public API every release.

## [0.4.0] — 2026-11-04
### Added
- **Desktop app** (`desktop/`): an Electron shell for Linux and Windows that runs the frozen engine on a free
  127.0.0.1 port and shows the review app in a sandboxed window.
  - Security: context isolation, no Node in the page, and a two-call bridge (native folder picker, "Show in
    folder"). External links open in the system browser.
  - Runs a single instance; the engine stops when the window closes.
- **Frozen engine** (`scripts/build_engine.py`): PyInstaller, one folder. It bundles fonts, knowledge files, the
  built UI and the OTIO adapters. ffmpeg comes from the system or from `engine/bin`; CI bundles
  checksum-verified static builds with their licence.
- **Packaging:** Linux AppImage + .deb, built here and checked. The Windows NSIS installer is built in GitHub
  Actions (`desktop.yml`), which `release.yml` calls for every new version and attaches to the GitHub
  Release.
- **Long → Shorts** (`prepro shorts`, "Shorts from long talks" in the Directions step). It finds self-contained
  20–60 s moments in long talking footage:
  - the first line has a number, question or claim, never "and so… like I said";
  - one idea, ending on its landing;
  - no overlap between Shorts.
  Each becomes a vertical, captioned cut that can be reviewed, revised and exported like any other. On a planted
  podcast fixture it found all three moments with exact boundaries and skipped the rambling.
- The frozen engine is about 100 MB smaller: a stub replaces PyAV (we hand Whisper decoded audio).
- `prepro doctor` now lists the available OTIO adapters.
- Desktop smoke test (`tests/desktop`): Electron + frozen engine under Xvfb. It checks the bridge, that no Node
  reaches the page, that the page is local-only, and that the engine stops on quit.
### Fixed
- **Kdenlive export in the frozen app.** It failed because OTIO loads plugin adapters from `.py` files by path;
  they are now shipped as source. Kdenlive export failures are now reported instead of silently skipped.
- **Kdenlive projects of vertical cuts** opened as 1920×1080 landscape (the adapter hard-codes it). The profile
  is now rewritten to the cut's real size and frame rate.
- **Duplicate OpenCV.** The unused `scenedetect` dependency pulled in a second OpenCV (`opencv-python` next to
  `opencv-python-headless`), which can break `cv2`. It is removed.

## [0.3.0] — 2026-11-04
### Added
- **Review app** (`prepro ui`): a React app served by a local FastAPI server on 127.0.0.1 only.
  - Steps: Footage (analysis progress, asset grid, search), Brief (live parse into rules), Directions
    (cards with hook thumbnails and shoot-next-time gaps), Review, Export.
  - Review step: player, timeline lanes, decision dots, retention heat strip, ✓/✕ on every decision, notes at
    the playhead, hook picker, knobs, scorecard, brief checklist, lint, music plan, paper edit.
- **Revise layer** (`prepro.revise`): every decision carries a stable key.
  - Accepting or rejecting a decision recompiles the cut in about a second with no AI call. Rejected
    decisions stay listed so they can be turned back on.
  - Timeline notes become edit ops from rules (English and Hinglish). Examples: "remove zoom",
    "big/small text: …", "meme here", "whoosh", "faster/slower", "cut this", "change song", "music
    quieter", "another hook", "keep the pauses".
  - Unclear notes go to an AI "revise" pass when one is connected; otherwise they are reported as not
    understood rather than guessed.
  - Notes that override the brief say so. Your choices survive a rebuild.
- Server security:
  - per-launch token
  - Host-header check against DNS rebinding
  - media served only from inside opened shoot folders (path traversal tested)
  - no CORS
- Retention heat strip (`timeline/attention.py`); `engine.directions()` (Director pass only); knob
  overrides on `build`.
- Hook and direction explanations in plain words ("open on the action at Calangute … 60 fps so it can go
  real slow-mo").
- Browser end-to-end test (`tests/ui`) that drives the real UI through the whole flow in Chromium.
### Fixed
- **`Project()` race.** Concurrent `Project()` calls could delete each other's write-probe and silently move the
  cache to another folder. Server threads hit this; it showed up as missing thumbnails.
- **Project registry.** It is now held in memory and saved atomically.

## [0.2.0] — 2026-11-04
### Added
- M4 exports (`prepro export <shoot> --formats all`):
  - **Premiere Pro / DaVinci Resolve:** FCP7 XML (xmeml v5) with organised bins (A-roll, B-roll by day · place,
    rejects with the reason, music, SFX, memes), punch-ins/reframes as Basic Motion, slow-mo/speed-ups as Time
    Remap, ducking as Audio Levels keyframes, cross dissolves, and a marker with its reason for every decision.
  - **Kdenlive:** OTIO + `.kdenlive` (via the OTIO Kdenlive adapter). **Shotcut:** MLT XML with timewarp
    producers for speed changes (verified by rendering it headless with `melt`).
  - **Phone apps (InShot / VN / KineMaster / Edits):** captioned MP4, clean MP4 without text, a no-music version
    for trending audio, dialogue/music/SFX stems, SRT, a cue sheet (what text to add where, ideas needing a
    decision, B-roll to shoot) and a beat plan (BPM + cut points for picking a trending sound).
  - Captions as SRT/VTT and as a transparent ProRes 4444 overlay for any NLE; the grade's `.cube` LUT.
  - Self-contained HTML **editor brief**: storyboard, scorecard, brief checklist, every decision with its reason,
    optional ideas, music plan, missing material, lint, paper edit, file list.
- B-roll requests read like an editor's notes ("close-up of the food being served — show the price too",
  search terms with the place name) from a concept map in `knowledge/broll.yaml`.
- `export` extra (`pip install prepro[export]`) for the OTIO FCP-XML and Kdenlive adapters.
- M3 AI brain: provider-neutral contract with connectors for Claude Code CLI (your Claude plan), Codex CLI (your
  ChatGPT plan), Anthropic API (claude-opus-5-5, structured outputs, prompt caching, server-side refusal fallback),
  OpenAI, xAI Grok, OpenRouter (data_collection=deny), Gemini (free/paid), Ollama (local) and a stub.
- AI passes (vision tags from contact sheets, director, story, polish, critic, brief parsing) that improve the rules
  draft; strict JSON schemas, ID validation, one repair round, fallback to rules on any failure; brief rules always win.
- Privacy levels (local / text / thumbs, optional face blur), sent-data log (`.prepro/sent/`), training badges,
  cost/plan-usage meter; `prepro brains list|add|key|route|privacy|compare`.
- Hook tightening (enter late at the payload clause); critic fixes targetable by `type:anchor`.
### Fixed
- The scanner ignores `PrePro_exports/`; our own renders were re-ingested as footage on the next build.
- Rendered MP4s are now 4:2:0 (`yuv420p`); the overlay pass produced 4:4:4 H.264 that many phones and
  phone editors refuse.

## [0.1.0] — 2026-11-04
### Added
- M0 scaffold: package layout, CLI, docs, synthetic shoots with ground truth (7 genres), real test-media fetcher, CI.
- M1 local analysis: ASR (sidecar / faster-whisper / PocketSphinx) + Silero VAD, fillers, retakes, false starts,
  greetings, emphasis; shots, quality flags, camera moves, whips, faces, subject tracks, action peaks, duplicates;
  music BPM/beats/downbeats/sections/key/mood; audio report; days/places; genre guesses; brief parser (EN + Hinglish).
- M2 Basic brain (directions, hooks, coverage gaps, per-genre stories, polish), compiler (speech tightening with
  acoustic snapping, jump-cut punch-ins, operator reframing, transitions, overlays, memes, text, SFX, music with
  drop alignment/backtiming and ducking, captions), EditLint + critic, renderer (−14 LUFS, storyboards).
