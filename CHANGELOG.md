# Changelog

All notable changes to PrePro are recorded here. Versions follow the release ladder in `docs/PLAN.md` §12.

## [Unreleased]
### Added — photo reels
- **A folder of photos and a song becomes a photo-dump Reel.** It's cut on the song's beat, about 1.2 s a photo,
  from the start of the song's chorus or drop (found from its bar lines). Photos play in the order they were taken
  (EXIF capture time, not file name). The cover goes first: a striking photo of a person that fills the 9:16 frame.
  The Reel ends back on the cover, continuing the cover's own move, so it replays without a seam. With no words of
  yours, the cover gets where and when from the photos ("Calangute · Oct 2026").
- **One photo, a few lines and a song.** Put your lines in the brief under `Text:` (one per line; a "POV: …" line
  or a line in quotes counts too). Your first line is on screen from the first frame, since it's the hook. Each next
  line arrives on the beat and stays up long enough to read; the last one holds to the end. They appear word for
  word, and brief compliance checks that.
- **Photos are read like a phone's camera roll.** Sideways-stored photos are turned upright from EXIF, capture times
  keep their time zone, and the place comes from GPS. Burst duplicates, blurry photos and dark photos are left out
  (you can bring any back). A photo is judged by its sharpest part, so a portrait-mode photo with a soft background
  is not "blurry".
- **Photos move like a camera.** A slow push-in, a pull-out, or a drift onto the subject, at about 6% of the frame a
  second. Frames are drawn at sub-pixel precision, so the motion glides instead of stepping a pixel at a time.
- **Nobody is cut out of a group photo.** When the faces won't all fit a 9:16 crop (or the photo is a panorama), it's
  shown whole, like a print, on a soft wash of its own colours. Such a photo is never picked as the cover.
- **Words on photos have their own look.** A clean sans with a soft shadow; lines are broken by measured width, never
  ending on "the" or "a". Text goes where the face isn't (above the head or below the chin, inside the platform's
  safe area), and is set a little smaller when a close-up leaves little room.
- **Every photo-reel decision can be undone in the review app.** Each photo left out says why (a burst shot, blurry,
  dark, or to keep the reel tight) and can be brought back; it returns in the order it was taken. Rejecting the
  cover opens on the next most striking photo, with the loop following it. The loop ending, the photos' motion,
  the title and your lines can each be turned off. However the reel changes, every photo still holds whole beats of
  the song, your lines move with their photos, and the last photo still holds longest.
- Photo cards on the Footage page show portrait/landscape and the time taken, instead of "0.0 s · 25 fps".
### Fixed — the desktop app
- **v0.8.0's desktop app could not start on Windows** ("engine exited during start-up", `UnicodeEncodeError … '→'`).
  The app reads the engine's output through a pipe, and Windows encodes piped output in the system code page
  (cp1252), which has no "→"; the engine died printing its first line. Output now goes out as UTF-8 to pipes and
  files, and a character a console can't show is replaced instead of crashing. `prepro --help` had the same crash.
  A test now starts the engine exactly that way, and the desktop build starts the frozen engine's `ui` before
  packaging, so a build like this can't ship again.

### Fixed — every video
- **Bar lines were two beats off** in songs whose kick plays beats 1 and 3. Downbeats now come from chord changes as
  well as the kick; all fixture songs but one (half-time drum'n'bass, a beat-tracking limit) now get every bar line
  right.
- **Cuts drifted off the beat over a long cut.** Each piece was rounded to whole frames on its own; frame counts now
  come from the rounded cut points.
- **True peak.** The limiter now measures peaks between samples too, so -1 dBTP holds. When limiting costs loudness
  (a dense music-only mix), the level is topped up, by at most 3 dB. A music-only Reel had measured -15.2 LUFS with a
  -0.1 dBTP peak; it now measures -14.3 LUFS and -1.3 dBTP.
- **A zoom that pulled out crashed the render** (ffmpeg scaled the picture under its own crop window).

### Added — gaming Shorts
- **The webcam in a stream is found.** A streamer's picture-in-picture is located from a steady face in a corner and
  the border that stays put around it (checked per colour channel, and at higher resolution than the rest of the
  analysis, because a webcam face is small). On the test streams, with a drawn face and with a real one, it lands
  within 3 px of the true box.
- **Vertical gaming Shorts are offered next to the YouTube cut.** When there is a webcam they are stacked: the
  webcam on top at its own shape, the game below. Hook text and titles sit under the webcam, never over the face.
  Rejecting the layout gives one plain 9:16 crop.
- **The webcam gets big on the biggest win** (half the frame in a Short; a picture-in-picture twice the size on
  YouTube). It happens once per video, and as a decision you can reject.
- **Fails get their meme.** A death ("Noooo! How did he even hit that?") stays its own beat and is followed by a
  fail meme from your folder. It never opens the video and never gets a hype callout.
- Timeline items can be placed in a panel of the frame (`place`), which is how layouts render.
### Fixed
- **GIF memes failed to render.** Every image was opened with `-loop 1`, which GIFs don't accept; they now loop with
  `-stream_loop`.
- **A callout and the caption drew the same words on top of each other** ("DCDOUBLE KILL!LL!"). The callout now
  replaces the captions while it is on screen, and any other bottom text stacks above a caption.
- **"REPLAY"** is a corner tag like a broadcast replay; it was tiny centred text.
- **On-screen text that only repeats the captioned words is dropped** ("DOUBLE KILL! LET'S" over "DOUBLE KILL!"),
  and a reaction is shown whole, never as a dangling "LET'S".

## [0.8.0] — 2026-11-05
### Added — podcast and interview two-shots
- **Who is talking.** In a shot with two or more people sitting still (one wide camera on a podcast), PrePro finds
  each person's seat. It then works out who says each line from whose mouth moves, with nodding and bobbing
  subtracted. Unclear lines get no speaker rather than a guess. 11/11 lines right on the two-person test podcast.
- **9:16 Shorts from a two-shot follow the conversation:**
  - The frame is on whoever is talking, and the cut lands at the end of a line.
  - A quick "yeah" doesn't trigger a cut.
  - An exclamation ("Eleven times!") gets a short reaction shot.
  - The frame never sits on the empty gap between the people.
  - Each cut is a decision with its reason. Reject it and the frame stays on who was on screen.
- **Conversations are cut in the order they were said:**
  - one stretch, opening on a line that stands on its own (never on a reply)
  - every answer stays with its question
  - it ends on a landing, not on a hanging question
- **Faster renders with your GPU when it helps.** NVIDIA NVENC, Intel Quick Sync and AMD AMF are used only when a
  one-time test on your PC shows they are clearly faster than the CPU; otherwise the CPU is used. If the GPU fails
  mid-render, the CPU finishes the job. `prepro doctor` shows the choice and the measured times.
- Review app: a "framing" filter for the speaker cuts.
### Fixed
- **Captions hopped above and below the face** from cut to cut. Placement looked at the biggest face anywhere in the
  source, often the person not on screen, and ignored the crop and punch-ins. Now it uses the face actually on
  screen, keeps one position for the whole video, and moves a caption only where it would cover the mouth.
- **A reply that echoes the other person** ("…one video I almost did not upload." → "Wait, you almost did not upload
  it?") was treated as a retake of the same line, and the setup was cut.
- **A greeting sentence took its whole line with it.** "Welcome back. Today I have a creator who…" was cut entirely;
  now only "Welcome back." goes. "Thanks for having me" counts as a greeting.
- **Seat detection is not limited to the faces the detector finds easily.** In our test podcast it found the
  darker-skinned guest in far fewer frames, so seats now use lower-confidence detections at a consistent position.
- **On-screen hook text could garble the line it came from.** "It started with one video I almost did not upload"
  became "Started with 1 video almost did?!": it was cut at 6 words mid-phrase and lost the "not" that carried the
  meaning. Now:
  - a phrase never ends on a word like "did", "with" or "every", and is never cut just before a "not"
  - it keeps the number and runs to the clause's end ("Zero to 1M subscribers in 1 year?!")
  - "did not" becomes "didn't"
  - the text stays up long enough to read
  - in a conversation it teases the line that actually opens the cut
- **GPU renders without overlays weren't exactly constant frame rate.** NVENC pieces end a timestamp tick short, and
  joining them by stream copy carried that into the file (30.0006 fps), which phone editors reject. GPU pieces are
  now joined with one more GPU encode.
- Test fixture: the gaming facecam placeholder was drawn top-left instead of top-right.

## [0.7.0] — 2026-11-04
### Added — gaming pack
- **Impact detection** (`analyze/sound.impacts`): explosions, shots and hits.
  - **Booms:** a third or more of the energy under 60 Hz. **Shots:** noise-like with a jump of 15 dB or more.
  - Voices never qualify; they have no sub-bass, and breathy consonants at word starts are ignored.
  - Gameplay fixture: exactly the 3 planted explosions. Talking, podcast and comedy clips: zero.
- **Highlights** = impact + the streamer's reaction ("Double kill! Let's go!"). A big reaction alone or an impact
  alone counts less.
- **Gaming cut:**
  - a cold open on the best play
  - every play with a 3 s build-up into it, at full volume and captioned
  - dead gameplay in between is cut
  - a 0.5× slow-mo replay of the best play, labelled REPLAY
  - the last play is always kept as the payoff
  - a callout in the streamer's own words ("DOUBLE KILL!")
  - "open on the best play" offered as the top hook
- **Length.** A gaming cut's length now comes from its plays, not its talk.
### Fixed
- **Dull-stretch fixes sped up a gameplay cold open,** silently. Speed-ups now only apply to wordless B-roll, and
  moving content (gameplay, pans, action) is no longer treated as a dead zone.
- **The cringe guard** no longer flags a cold-open preview or the cuts between plays in screen recordings.
### Fixed — Windows (first full run on a Windows PC, with espeak-ng; Windows CI had skipped most tests)
- **The offline speech recogniser never worked on Windows with Python 3.12.** pocketsphinx 5.1.x has no Windows
  wheel for 3.12, so it was compiled on install; a MinGW build can't load (`libgcc_s_seh-1.dll`). It is pinned
  below 5.1 (5.0.4 has wheels for 3.11–3.13 on every platform).
- **Speech that couldn't be recognised was silent.** The clip got an empty transcript and the cut was made blind.
  Now it is a project warning with the fix (download a speech model), and those clips are transcribed again as soon
  as Whisper is there. `prepro doctor` says "won't load" (with the error) instead of "not installed".
- **Whisper on a PC with an NVIDIA GPU but no CUDA libraries** (most gaming PCs) chose the GPU, failed, and dropped
  to the rough recogniser without a word. "Auto" now uses the GPU only when CUDA 12's cuBLAS and cuDNN 9 load,
  finishes on the CPU if the GPU fails on first use, and the transcript and `prepro doctor` say which ran and why.
- **Claude Code / Codex connectors:**
  - npm installs them as `.cmd` shims, and cmd.exe mangled the JSON schema we pass. A shim is now resolved to
    the program it launches.
  - The system prompt goes through `--system-prompt-file`, because Windows caps command lines.
  - Prompts and replies travel as UTF-8 bytes: Windows pipes default to cp1252 and CRLF, which broke ₹, “quotes”
    and Hindi.
  - The install hint now points to the native Claude Code installer (`winget install Anthropic.ClaudeCode`).
- **Desktop release (Linux):** v0.6.0 shipped without the AppImage/.deb because one ffmpeg download from
  johnvansickle.com failed. It now retries, and falls back to BtbN's static build, checked against its sha256.
- **Tests on Windows:**
  - TTS lines go to espeak-ng as a UTF-8 file. Devanagari passed as an argument became "????", so the Hindi
    fixture lines were 0.3 s of noise.
  - The CLI stubs run through an interpreter on every OS.
  - Exported `file://` URLs are read back with `url2pathname`.
  - Shoots built with real media are cached apart from fully drawn ones.
### Added
- `scripts/check_asr.py`: word error rate per speech backend on real speech with a known transcript.

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
