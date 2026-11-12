# Handoff (read this first when resuming)

**Repo:** github.com/buildcool/PrePro · day-to-day work on `dev`; releases fast-forward `main` + tag `vX.Y.Z`
(the `release` workflow creates the tag, builds the wheel and publishes a GitHub Release from `docs/releases/<tag>.md` whenever main carries a new version — tag pushes from the container are denied by policy, HTTP 403).
**Plan:** `docs/PLAN.md` (approved). **Release ladder:** v0.1 offline engine → v0.2 AI brain + exports →
v0.3 review UI → v0.4 desktop app → v0.5+ Phase 2 → v1.0.

## Current state
- **Vision (the user's, 2026-11-06): an autonomous pre-editor** — one action from a shoot folder to ~90 % of the edit,
  export-ready; choices are refinements, never gates. See `docs/VISION.md`; judge features by it.
- **v0.12.3 (2026-11-07) = v0.12.2 + the Windows installer.** v0.12.2's release run failed on Windows only: gyan.dev
  answered 503 for `ffmpeg-release-essentials.zip.sha256`, so the GitHub release v0.12.2 has the Linux builds and the
  wheel but no `.exe` / `latest.yml` (left as is). `desktop.yml`'s Windows ffmpeg step now tries gyan.dev, then falls
  back to BtbN's `ffmpeg-n<ver>-latest-win64-gpl-<ver>.zip` checked against its `checksums.sha256` (like the Linux
  step). Note: the `.sha256` reads come back as bytes, hence `AsText`. Logic dry-run here in pwsh 7.6; the zip's layout
  checked from its central directory.
- **v0.12.2 (2026-11-07; CHANGELOG [0.12.2], QA "v0.12.2"): changing the song re-cuts a beat-cut cut on it.**
  `revise.apply_ops(..., brief)` (both callers pass the brief): when the base story is beat-cut (`_beat_cut`: playbook in
  `BEAT_CUT` and items with `beats`) and the ops hold a `swap_track` to a music asset, `_on_song` rebuilds story and
  polish with `BasicBrain` and a `use_music` rule for the last swapped track (then lint + `apply_fixes`, as a build
  does), sets the cue's alternatives to the unheard songs then the old ones and prefixes its why with "your pick: ";
  the other ops replay on top; `reject music:*` before the last swap is skipped, after it still applies. Plain swaps
  (talking formats) now put the old song last in `alternatives`. `_reel_grid` tries a start whose remaining song
  carries the whole cut first (photo reels: `need`, then the old `min(need, 8)`; day/words: `need × 1.15`) and returns
  `room` (song left after the start); `_story_photo_reel` caps its target to `room - 0.3`, `_story_day_in_life` its
  target and cap to `room - 0.5`. The cover's reading time counts the auto title (`photo_title`) when there are no
  lines; the compiler's `line_on` takes any applied photo-style words at `photo:i`, not only brief lines. Swift port
  updated alike (`ReelGrid.room`). Tests: `tests/unit/test_song_swap.py` (goldens, no media) and
  `test_change_the_song_rebuilds_the_reel_on_its_beat` (e2e, a second synthesized song).
- **v0.12.1 (2026-11-07; CHANGELOG [0.12.1], QA "v0.12.1"): Gemini via Antigravity, who's signed in.** Google stopped
  Gemini CLI for personal accounts (18 June 2026): `accounts.PLANS["gemini-plan"]` is now kind `antigravity_cli`
  (`providers.AntigravityCLI`: stream-json stdin/stdout, `--json-schema`, `sees_images = False`; installer
  `antigravity.google/cli/install.ps1`, exe `agy` in `%LOCALAPPDATA%\agy\bin` — `find_cli` looks there). `GeminiCLI`
  maps Google's "no longer supported" error to plain words. `Settings.load` migrates a saved `gemini_cli` connector;
  `record_test(kind=…)` + `_current_test` drop results made by another tool. Who's signed in: `accounts.account()`
  (status commands only: `claude auth status --json`, `codex login status`, `agy auth status` only if `--help` lists
  it; cached 120 s, forgotten on test/sign-in). `overview()` sorts `ready` working → untested → failing and returns
  `failing`; the UI hides failing ones from the "Who edits" picker (except the current editor) and sorts each section
  working → untested → not set up → failing. Not yet run against a real signed-in `agy`.
- **PrePro for iPhone (started 2026-11-07): plan `docs/IOS_PLAN.md` (approved), tester guide `docs/IOS_INSTALL.md`.**
  Native SwiftUI app (iOS 26), $0 toolchain: no Mac here. GitHub's macOS runners (`.github/workflows/ios.yml`,
  `runs-on: macos-26`, free for this public repo) generate the project with XcodeGen (`ios/project.yml`), run
  `swift test` for `ios/PreProCore` and UI tests on an iPhone 17 Pro simulator, and put an unsigned `PrePro.ipa` on
  the `ios-nightly` pre-release. Testers (primary iPhone 17 Pro, secondary iPhone 17) install it with SideStore and
  their own free Apple ID. `PreProCore` mirrors the desktop JSON (schema/timeline.py, plan.py) and reads
  `src/prepro/knowledge/*.yaml` (copied in by CI, gitignored); golden decisions from `scripts/export_parity.py`.
  Milestones M0–M7 in the plan; M0 = core skeleton + clock port + starter app (build number, Apple Intelligence status,
  clip-time check, test report). CI failures show as public annotations (logs need a sign-in).
  **M1 so far (2026-11-07): the photo reel brain.** `Schema/Analysis.swift` + `Brief.swift` (every field of
  schema/analysis.py, media.py, brief.py), `Music.swift` (assist/music.py: `brief(for:)`, `rankTracks`, `hasVocals`,
  `soundtrackMode`), `Brain/RulesBrain.swift` (BasicBrain: rules sets, `photos`, `textLines`, `photoTitle`,
  `musicPlan`, `reelGrid` → `ReelGrid`) and `Brain/PhotoReel.swift` (`_story_photo_reel` / `_polish_photo_reel`),
  `Py.swift` (Python's `round` via `%.nf`, `str.split`, code-point order, numpy median, stable sort — so every beat and
  reason matches to the digit). Goldens per case: `analysis/brief/direction.json` (inputs), `brain_story/
  brain_polish.json` (the brain before the editor's checks; identical to story/polish for all four today),
  `music.json` (front/bed/light briefs and rankings, the beat grid). `BrainParityTests.swift` checks them on the Mac;
  `tests/unit/test_ios_goldens.py` re-runs the desktop brain on the same inputs so a desktop change can't silently
  leave the phone behind (re-export, then port). The export always uses the rules engine.
  **Then the photo reel timeline:** `Compiler/Compiler.swift` (compiler.py's photo-reel path only — it throws
  `BrainError.notOnPhoneYet` for talking or video clips): left-out suggestions, `beatLength` (`_beat_len`, grid
  re-derived at 4 decimals), `photoMotion`, `seamlessLoop`, `faceLookup`, `besideFace`, text anchors (start/end/
  section/span/t:/clip:/photo:), stamps, `layMusic` (spans, groups, `Music.bestOffset`, the 50 ms envelope via
  `Py.arange` = numpy's fill, loop items, music suggestion). `TextLayout.swift` = captions.py `text_block` /
  `balance_lines` with `Resources/text_metrics.json` (committed; written by export_parity: every bundled font's
  per-code-point advance at size 100, Pillow basic layout, only those ≠ .notdef, plus STYLES/SAFE/GLUE/LIBASS_WIDTH —
  Pillow's measure is a plain sum of advances, so line breaks match exactly). Goldens: `text_blocks.json` (18 lines,
  all styles, scales, Devanagari, emoji). `CompilerParityTests.swift` compares both photo reel timelines field by
  field; the desktop guard now also recompiles all four golden timelines (pa.root = "", nothing read from disk) and
  re-measures every advance.
  **Then the music analysis (2026-11-07):** `Sound/DSP.swift` (librosa's front end with Accelerate at its precision:
  scipy's Hann formula to the bit, double FFT stored as float32, Slaney mel filters bit-identical, float32 dB, numpy's
  pairwise float32 sum/std, chroma filters, MFCC as ortho DCT-II, RMS, percentile, median), `Sound/BeatTracker.swift`
  (onset_strength, tempo, librosa's numba DP tracker step for step, the 70–180 folding), `Sound/MusicAnalysis.swift`
  (bar lines, energy curve, sections with a neighbours-only Ward merge = scikit-learn's on a chain, key, brightness,
  mood tags → `MusicInfo`). Test songs: `scripts/portable_song.py` ↔ `Fixtures/SongSynth.swift` (the fixture synth with
  SplitMix64 + Box–Muller noise, made at 22.05 kHz; its root is the labelled key — the fixture synth's `45 + NOTE[key]`
  puts its "A" songs in F#). `Golden/songs/*.json`: librosa's onset envelope, tempo bin, beat frames and the desktop's
  `music_info` for four songs; `BeatParityTests` (beats to librosa's exact frames from its envelope; end to end within a
  frame; the whole analysis) and the desktop guard `test_song_analysis_is_current`. Known simplifications on the phone:
  chroma tuning 0 (the desktop estimates it; no change on the test songs) and the key from a 4096-point STFT chroma, not
  constant-Q (same mode; Am–F–C–G: desktop F major, phone C major). Seen on the way, for both apps: librosa hears the
  all-drop 140 BPM trap test song at 112 BPM (tempo prior pulls a wrong peak; margin 0.014) — a reel on it would be cut
  off the beat; worth a check of the top tempo candidates against beat alignment.
  **Then reading a song file (2026-11-12):** `Sound/AudioDecoder.swift` = `librosa.load(sr=22050, mono=True,
  duration=600)`: AVAudioFile reads in pieces until every frame is in (a read may return less than asked), channels are
  averaged by hand, AVAudioConverter (mastering algorithm, max quality) resamples, fed in pieces of at most what it asks
  for, cut or padded to librosa's length ceil(n · 22050 / rate). `AudioDecoderTests`: a 3 s tone keeps its length,
  level and pitch to the end; a float32 WAV at 22.05 kHz reads back bit for bit and gives the golden's beats; the test
  song made at 44.1 kHz in stereo sounds as it does on the desktop (`from_44k` in `Golden/songs/happy_100.json` is the
  desktop's own decode of that file: the same 99.38 BPM, beats within a frame give or take one, the same sections). The
  tests write their WAVs byte by byte: a file written by AVAudioFile read back 179 frames short (which side lost them
  wasn't pinned down; the decoder now reads until the file has no more). Seen on the way: on the 44.1 kHz file the
  desktop hears 48 beats where the 22.05 kHz song has 56, because librosa's tracker stops before the quiet outro; a
  reel's grid carries on at the song's tempo past the last beat heard (`_beat_at`), so its cuts stay on the beat.
  **Then the photos (2026-11-13):** the desktop's photo math moved into `analyze/pipeline.py photo_measures(im, boxes)`
  (no behaviour change: fresh analyses of the fixture shoots are identical), and the phone does the same to the bit.
  `Photos/Pillow.swift`: Pillow's `Image.thumbnail((480, 480))` (Reduce.c box reduction with its fixed-point
  multiplier and the last row/column/corner, then Resample.c bicubic in 22-bit fixed point with the float32 box) and
  `exif_transpose` for all eight orientations. `Photos/PhotoMeasures.swift`: OpenCV's grey (15-bit: 9798/19235/3735)
  and Laplacian (BORDER_REFLECT_101), numpy's pairwise float64/float32 sums (np.var of a slice: mean exact, squares
  summed as a fresh contiguous array; the mean colour added row by row in float32), imagehash's phash (Pillow's grey,
  Lanczos to 32×32, the DCT's 8×8 against the median). numpy's float32 `** 2` uses the C library's powf, which can be
  one bit off x·x on a tie: the only allowed difference (the striking score's last digit). `Photos/Faces.swift`: Vision
  face rectangles reported like res10 (centre, y down, conf ≥ 0.6, ≥ 3 %). `Photos/PhotoFile.swift`: ImageIO EXIF
  (DateTimeOriginal + OffsetTimeOriginal, else this phone's zone like `astimezone()`; GPS signed; orientation), pixels
  decoded as stored without colour conversion, `fast_hash`. `Photos/Places.swift`: reverse_geocoder's lookup — the
  nearest of GeoNames' cities1000 in plain degrees (rg 1.5.1 builds its k-d tree on raw lat/lon, not ECEF) — from
  `Resources/places.bin`, packed on the Mac before every build by `scripts/export_places.py` (all coordinates are whole
  1/100000 degrees, so exact; 233 cities share a coordinate with another and rg always answers with the same one,
  which is the one kept). `Photos/PhotoShoot.swift`: `input(url)` (file → upright thumbnail → faces) and
  `analysis(photos:music:)` = assign ids (song first, photos in name order), `_image_shot`'s Shot, `duplicate_groups`
  (burst, 12 bits), `split_far_duplicates`, `cluster_context` (order, days, 25 km places), `guess_genres` for photos.
  Tests on pixels both apps make (`scripts/portable_picture.py` ↔ `Fixtures/PictureSynth.swift`, integer formulas +
  SplitMix64 noise): `Golden/photos/measures.json` (14 photos: reductions ×2/×3, odd sizes, every orientation,
  blurry, dark, a burst, faces — thumbnail fingerprints and measures), `shoot.json` (a Goa day like photo_dump with
  given face boxes → the desktop's analysis, direction, story, polish, timeline), `places.json`, `faces.json` (res10 on
  three frames of Intel's face video; the CI downloads it and `FacesTests` checks Vision lands on the same face). The
  desktop guards: `test_photo_measures_are_current`, `test_photo_shoot_is_current`, `test_place_names_are_current`;
  `python scripts/export_parity.py --photos` re-exports only these. `Brain/Directions.swift`: `directions()` for a
  shoot of photos (target_length ≈ 2.4 + 1.2 s a photo, one photo 10 + 3.5 s a line past two; hook_options = the three
  best covers by `coverScore`; direction_name; outline; knobs from the brief) — anything with video clips throws
  `notOnPhoneYet` rather than guess; `DirectionTests` against photo_reel, photo_single and the test day. The app:
  `ios/PrePro/PhotoReelCard.swift` (`ReelMaker`: PhotosPicker originals → `PhotoShoot.input` off the main actor → the
  song from Files (`.fileImporter`, copied in) → analysis → directions → story → polish → `Compiler.compile`;
  `ReelView` shows the cover with its title, the order and every decision; the test report gets the decisions with
  asset ids for file names, faces, bursts, flags, days/zone). Testers' steps: docs/IOS_INSTALL.md "M1". Next in M1:
  live preview, render, save/share, ✓/✕ on each decision.
- **v0.12.0 (2026-11-06; CHANGELOG [0.12.0], QA "v0.12"): your words on video.** Playbook `text_reel` (a
  brief-driven direction: `BasicBrain.directions` inserts it when the brief has `text_line` rules and `_words_fit()`
  — ≥ 2 good B-roll shots, not more photos than clips, little talking; after `day_in_life` when that leads).
  `_story_text_reel`: cover = best `_moment_score`, then clips in shooting order; each line gets one or more clips
  (k beats ≈ 1.3 s, up to 2k per clip, never a sliver left) until `_read_time(line)` (+0.5 s for the last) is
  covered; fresh windows when clips run out, a repeat only as a last resort; `self._words` = (line, first clip
  index, duration). `_polish_text_reel`: the song on the grid (section "words") and each line as a `photo`-style
  text at `clip:<k>` (new compiler anchor: the k-th V1 item). `BEAT_CUT` includes it. `_reel_grid` makes a day's or a
  reel's song cover the whole cut. Critic: text_reel signature checks; the beat check carries the grid past the
  last analysed beat. Tests `e2e/test_p9_words_on_video.py` (aesthetic_cooking + a brief).
- **v0.11.0 (2026-11-06; CHANGELOG [0.11.0], QA "v0.11"): Day in my life.** Playbook `day_in_life` (9:16, BPM
  80–125 via the new `music.bpm` key read by `assist.music.brief_for`). `analyze/clock.py`: the creator's local clock
  (`local_time`: iPhone `com.apple.quicktime.creationdate`, photo EXIF offset, else UTC in `shoot_zone` / the PC's
  zone; `pa.stats["utc_offset_min"]`), `shooting_day` (4 am to 4 am), `part_of_day`, `stamp`. `context.day_shape` +
  the genre guess (≥ 5 video clips of one day over ≥ 3 h, B-roll ≥ 50 %, not more photos than clips);
  `split_far_duplicates` (look-alikes are retakes only within 30 min; CONTEXT_VERSION 6, no re-analysis).
  `BasicBrain`: `day_moments`, `_day_beat` (k beats ≈ 1.6 s), `_story_day_in_life` (chronological, first/last 2k
  beats, evenly spread picks when it doesn't fit, sections = parts of the day, items carry `beats`),
  `_polish_day_in_life` (song cue with the grid's offset on every section, title, the brief's lines, stamps with
  `intent="stamp"`). `BEAT_CUT = ("photo_reel", "day_in_life")`: `AIBrain.story/polish` return the rules plan for
  them. Compiler: video items with `beats` are laid on the grid like photos; text anchored to a moment with `dur=None`
  lasts the moment; stamps avoid a face up top and share one review decision (`key="stamps"`, revise removes them);
  "Left out" suggestions for unused moments; natural sound −5 dB. `revise._is_reel` now needs section "reel";
  `_insert_moment` brings a moment back in time order. Captions: `stamp` style (Montserrat 0.030, top centre).
  `render.mix_audio`: speech-to-music only over talking A1 items. Fixture `day_in_life` (`still_clip/action_clip`
  `local_time=` writes the Apple tag); tests `unit/test_p8_day_clock.py`, `e2e/test_p8_day_in_life.py`.
- **v0.10.1 (2026-11-06; CHANGELOG [0.10.1]): brand logos for the AI accounts.** `ui/src/components/BrandLogo.tsx`
  (`BrandLogo`, `LogoTile`) inlines the vendored SVGs in `ui/src/assets/brands/` (LobeHub lobe-icons 1.95.1, MIT,
  see `NOTICE.md`; licence shipped as `ui/public/brands/LICENSE-lobe-icons.txt`) via Vite `?raw`; one-colour marks use
  `currentColor`, Gemini's gradient ids are made unique per copy (`useId`). Used by the account cards, the "Who edits"
  picker and the sidebar `AIChip`. Simple Icons was tried first but has no OpenAI or xAI logos. `accounts.cli_version`
  now returns just the version number and `ask=False` reads the cached one (so PUT responses keep it).
- **v0.10.0 (released 2026-11-06; CHANGELOG [0.10.0], QA "v0.10"): the autonomous pre-editor, AI accounts, a redesigned app.**
  - One click: `POST /projects/{pid}/autocut` (server/app.py) runs analysis → build("auto") → preview render → export
    (fcp7, otio, srt, report) as one job with steps (`Jobs.submit(steps=…)`, `Job.phase(k, lo, hi)` maps each step's
    own progress forward-only; `_analysis_progress` maps the analysis stages onto one scale). `Job.cancel` + `POST
    /jobs/{id}/cancel` (stop raises `JobCancelled` at the next progress report). Progress inside files: `analyse_asset(note=…)`,
    `music_info(note=…)`, build steps (plan/edit), render steps (pieces, join, overlays, mix, storyboard).
    `Settings.autocut_on_open` (Home starts the autocut on open).
  - AI accounts: `brain/accounts.py` (PLANS: claude_code / codex / gemini_cli via their CLIs, `find_cli` looks beyond
    PATH; KEYS: anthropic / openai / gemini / xai / openrouter in the keychain via `config.set_secret/delete_secret`;
    `terminal_command` + `open_terminal` run only fixed install/sign-in commands; `record_test` → `<config>/ai_status.json`).
    `Settings.ai_editor` + routing "auto" (`engine.make_brain` resolves it; all-"basic" saved routing migrates to "auto").
    New connector `providers.GeminiCLI` (stdin prompt, `--output-format json`, `@file` contact sheets; stub `tests/stubs/gemini`;
    not yet run against a real signed-in Gemini CLI). Endpoints `/api/ai`, `/api/ai/keys/{id}`, `/api/ai/{id}/test|open|model`,
    `/api/settings`.
  - UI (`ui/src`): shell with sidebar (`App.tsx`), `pages/Settings.tsx` (general, ai, privacy, speech, render, updates,
    about; `aiChanged()` event refreshes the sidebar chip), `components/TaskProgress.tsx` (stepper, sheen/stalled bar,
    elapsed + ETA, Stop), `components/Icon.tsx` (own line icons), `theme.ts` (system/light/dark → `data-theme`, desktop
    `nativeTheme` via the `setTheme` bridge), `styles.css` design tokens for both themes, Inter from `ui/public/fonts`.
    The Brains modal is gone (Settings replaces it). `tests/ui/flow.js` drives the new flow (needs node + playwright).
  - `analyze/visual._seats`: two seats only with two faces on screen together (ANALYSIS_VERSION 13).
- **v0.9.1 (released 2026-11-06; CHANGELOG [0.9.1]): app updates.** `desktop/updater.js` (electron-updater 6.3.9, GitHub provider from the
  `build.publish` config; modes auto / notify (default) / off in `<userData>/updates.json`; checks 15 s after start, then
  daily; installs only on "Restart to update" or the next quit). Installable: the NSIS build and the AppImage; a .deb or a
  dev run asks GitHub's API and opens the release page. Bridge `window.prepro.updates`; UI `ui/src/pages/Updates.tsx`.
  Checks: `tests/desktop/updater_check.js` (CI ui job); desktop.yml fails without `latest*.yml`.
- **v0.9.0 (released 2026-11-06; CHANGELOG [0.9.0], QA "v0.9"): photo reels** (the user's priority now: lifestyle and vlogs),
  the v0.8.0 desktop start-up crash fixed (`cli._safe_output`), gaming Shorts.
  - Photos: `media/probe.photo_exif` (orientation, capture time with its offset, GPS); `analyze/pipeline._image_shot`
    writes an upright working copy (`photo_copy`, ≤ 2560 px) and judges sharpness by the sharpest tile or the face;
    `visual.duplicate_groups(prefix="burst")`; ANALYSIS_VERSION 12; genre `photo_reel` (CONTEXT_VERSION 5).
  - Brain: `BasicBrain.photos/text_lines/photo_title/_cover_score/_reel_grid/_story_photo_reel/_polish_photo_reel`.
    The grid is the song's detected beats from the strongest section's downbeat; every item length is a whole number
    of beats (`_beat_at`). One photo: line slots in half bars. `MusicCue.offset` fixes the song's start.
  - Compiler: `photo_motion` (pans ≤ 6 %/s, push/pull 1.0↔1.07, `Transform.fit` for group photos and panoramas via
    `analyze.visual.photo_fills`), `_seamless_loop`, `_beside_face` (`Item.text_y` / `text_scale`), text anchors
    `t:<seconds>`.
  - Render: `export/render.photo_frames` draws photo frames with OpenCV (sub-pixel), piped through
    `media/encoders.encode_frames`; frame counts from rounded cut points; true-peak `_limit`; loudness top-up.
  - Captions: style `photo`, `balance_lines` / `text_block` measured with the bundled fonts (`LIBASS_WIDTH` calibration).
  - `analyze/sound.music_info` downbeats from chord changes + low end.
  - Brief: `Text:` block → `HardRule(kind="text_line")`; compliance checks each line word for word.
  - Revisions: `StoryItem.beats` (the compiler's `_beat_len` lays photos on the song's grid), lines anchored `photo:<i>`;
    keys `cover:<photo>` (next cover from `Direction.hooks`), `shot:<photo>` (bring back, `revise._insert_photo`),
    `photomotion` (`Knobs.photo_motion`), `loop:<photo>`; `revise._swap_cover/_reel_rhythm` keep the rhythm.
  - Fixtures `photo_dump` (11 photos: sideways, burst, blurry, dark, a group of three, EXIF times out of file order)
    and `photo_single` (one portrait + a `Text:` brief); `fixtures/visual.photo` writes phone-style EXIF and
    `photo_face` draws faces the detector finds (CI has no real media). Tests: `tests/e2e/test_p6_photo_reels.py`,
    `tests/unit/test_p6_photo_units.py`.
- **Gaming Shorts (in v0.9.0):**
  - `analyze/visual.find_facecam` → `ClipAnalysis.facecam` (ANALYSIS_VERSION 11)
  - `Item.place` panels in the renderer
  - `compiler._facecam_layout` (stacked 9:16, `Knobs.layout`, `layout:<asset>` rejection) and `_facecam_moments`
    (`facecam` cue on the biggest win)
  - gaming fails (`BasicBrain.FAIL/WIN`, a fail meme keyed `<shot>@<t0>`)
  - a 9:16 gaming direction is offered next to the 16:9 one
  - fixture: a drawn streamer webcam + a planted death; FIXTURE_VERSION 6
- **Next, at the user's request: more lifestyle and vlog formats** (photo reels are done). Gaming is paused.
- **v0.8.0 (released 2026-11-05; CHANGELOG [0.8.0], QA "v0.8"):**
  - GPU video encoding (`media/encoders.py`):
    - candidates NVENC → Quick Sync → AMF, each after a real test encode
    - "auto" times a grainy render-like encode once per PC/size (`<data>/encoders.json`) and uses a GPU only when
      it is ≥ 15 % faster than x264
    - a mid-render GPU failure is redone on the CPU
    - `Settings.render.encoder` / `PREPRO_ENCODER`
  - Podcast two-shots:
    - seats + mouth movement (`analyze/visual._seats/_mouth_series`), a speaker per line
      (`analyze/speakers.assign_speakers`), cross-speaker "retakes" undone
    - `BasicBrain._story_dialogue` cuts conversations in order; `responds()` finds replies/echoes
    - `compiler.speaker_frame` frames the speaker in 9:16 crops (turn-based hold 1.2 s, 0.8 s reaction shots for
      exclamations); `speaker:<line>` rejection keeps the current framing
    - cringe guard `framing_gap`
  - Captions: one position per video against the face on screen (`compiler._face_lookup` in output coordinates,
    `captions._place`).
  - Fixture `podcast_duo`; FIXTURE_VERSION 5; ANALYSIS_VERSION 10.
- **v0.7.0 (released): the gaming pack + Windows fixes.** The first full run on a Windows PC; see QA "v0.7 on Windows".
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
  `https://buildcool@github.com/...`).
- **Commit authorship (asked by the owner):** author `buildcool <331665223+buildcool@users.noreply.github.com>`,
  set repo-locally with `git config user.name/user.email`, plus the trailer
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The PC's global git identity is someone else's.
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
0. Two-shots, later: multi-camera podcasts (one camera per person, synced by audio), a stacked split-screen
   layout for rapid back-and-forth, and 16:9 "virtual multicam" (wide ↔ punch-in on the speaker).
1. **Genre packs, more:**
   - lifestyle/vlog (the user's priority): see "Lifestyle formats" in `docs/QA.md` (v0.9) for the researched list;
     photo reels are done. HEIC photos (iPhone default) need `pillow-heif`; Live Photos are a still + a 3 s clip.
   - lifestyle "satisfying moment" detection
   - gaming (paused): HUD/kill-feed flashes
   - known limit: a 174 BPM drum'n'bass track is tracked at half time (87 BPM) with the beat on the snare, so its
     bar lines are off; the beat tracker, not the downbeat finder, would need a tempo prior for fast genres
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
