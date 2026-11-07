# PrePro for iPhone: native app, zero dollars to start

## Context
Creators asked to use PrePro on iPhone. The desktop app (Electron + a Python engine using ffmpeg, librosa/numba,
OpenCV, faster-whisper and the Claude/Codex/Gemini CLIs) cannot be packaged for iOS: no Electron, no helper processes,
no JIT (numba), and none of those native libraries. So this is a **native SwiftUI app** that carries PrePro's editing
brain over and does the media work with Apple's own frameworks. A **PC companion** comes later.

Goals: the same promise as the desktop app (one action → a finished, export-ready first cut; every decision explained
and reversible; footage never leaves the device), as good as the desktop or better, and **$0 until you choose to
publish**.

Decided with you: **no Mac** (Windows only); **iOS 26 and newer**. You don't have an iPhone; testing is done by
others: **primary iPhone 17 Pro, secondary iPhone 17**. Both run Apple Intelligence, so the free on-device AI editor
gets tested for real, on the Pro and the base chip and memory.

## Straight answers to your questions
- **Claude Code in an iPhone terminal (iSH, a-Shell, "Termux for iPhone"): not usable.** iSH emulates 32-bit x86 and
  modern Node.js reportedly crashes in it. a-Shell has no Node. Even if one worked, iOS doesn't let our app run another
  app's programs or exchange edits with it. Paid cloud terminals exist, but they cost money. Separately, **Anthropic's
  terms allow a Pro/Max plan only in Claude.ai and Claude Code**. Using the plan's login inside another app is
  forbidden (docs Feb 2026, enforced from Apr 2026), and doing it would put your account at risk. "By hook or crook"
  stops there.
- **The working way to use your Claude / ChatGPT / Gemini plans from the iPhone is the PC companion (M6).** The phone
  hands the AI work to PrePro on your PC, which runs the official CLIs exactly as it does today.
- **Apple Intelligence: yes, the main free AI editor.** Apple's Foundation Models framework runs Apple's on-device
  model (iOS 26, A17 Pro / iPhone 15 Pro and newer, Apple Intelligence switched on). It's free, offline and private,
  and returns structured output, which suits directions, titles, line-to-clip matching and captions. Limits: a
  4,096-token context per session and **text only** on iOS 26 (pictures first go through Vision, which gives
  labels, faces, saliency and an aesthetics score, also free and on device).
- **BYOK: yes, same list as desktop** (Anthropic, OpenAI, Gemini, xAI, OpenRouter), with keys in the iOS Keychain. Two of
  them have **free tiers**: the Gemini API (free tier; Google may use what's sent to improve its products) and
  OpenRouter's `:free` models (rate-limited).
- **Zero dollars: yes, for building it and using it on your own iPhone. Giving it to other users costs $99 a year**
  (Apple Developer Program: TestFlight and the App Store; there is no free way to distribute iPhone apps widely).

## Zero-dollar toolchain (no Mac)
- Code lives in this repo under `ios/` (the repo is public, so **GitHub's macOS runners are free**).
- `ios/project.yml` (XcodeGen) generates the Xcode project on CI, so nothing Xcode-only is edited by hand on Windows.
- `.github/workflows/ios.yml` on `macos` runners: generate the project, build, run unit and UI tests on the iOS
  Simulator, and produce an **unsigned .ipa**. That's published as an artifact and on an `ios-nightly` pre-release.
  Failures go out as public annotations, the same trick used for the desktop CI now.
- **Install on the testers' iPhones for $0, without them coming to your PC:** **SideStore**, signed with the
  **tester's own free Apple ID**.
  - Setup, once per phone: any computer (Windows or Mac) for about 15 minutes, then turn on Developer Mode.
  - After that, everything happens on the phone. A new build is a tap on the `ios-nightly` link → "Open in
    SideStore". The 7-day re-sign happens on the phone too (SideStore's on-device refresh with its small VPN helper
    app).
  - Limits: at most 3 sideloaded apps per Apple ID, and an app expires if it isn't refreshed for 7 days.
  - AltStore + AltServer on a PC is the fallback.
  - A step-by-step guide written for a non-developer tester: `docs/IOS_INSTALL.md`.
- **Test reports from the phones:** an in-app "Send test report" shares, through the share sheet (WhatsApp, mail…),
  the project's decisions, timeline JSON, timings, device model, iOS version and thermal/memory peaks. **No footage**
  unless the tester also attaches the exported cut. You pass the report to me in chat and I review it as an editor.
- Optional speed-up: Swift for Windows to compile and test the pure-Swift core locally (C: is nearly full, so only if
  it installs on D:). Otherwise every compile is a CI round trip of about 10 minutes.

## Architecture
**PreProCore**: a Swift package that ports the decision layer and keeps PrePro's knowledge as data.
- Bundles `src/prepro/knowledge/playbooks.yaml` (and the other knowledge YAML) **unchanged**: one source of truth for
  both apps (read with Yams).
- Mirrors the JSON shapes of `schema/analysis.py`, `schema/plan.py` and `schema/timeline.py` (Codable), so projects
  and timelines move between phone and PC (needed for M6).
- Ports, in order of the lifestyle priority, from these sources:
  - `brain/basic.py`: `_story_photo_reel`/`_polish_photo_reel`, `_story_day_in_life`/`_polish_day_in_life`,
    `_story_text_reel`/`_polish_text_reel`, `_reel_grid`, `_day_beat`, `day_moments`, `_moment_score`, `hook_options`,
    `directions`, `target_length`;
  - `timeline/compiler.py`: the beat-grid layout (`_beat_len`), text anchors (`photo:`, `clip:`, moment spans,
    stamps), face-avoiding text (`_beside_face`), `_lay_music` levels and envelope, `photo_motion`;
  - `timeline/captions.py`: `STYLES`, `text_block` / line balancing;
  - `analyze/clock.py`, `analyze/context.py` (`guess_genres`, `day_shape`, `split_far_duplicates`),
    `assist/music.py` (`brief_for`, `rank_tracks`), `analyze/sound.py` (`mood_tags`);
  - `lint/ghinn.py`, `lint/critic.py`, `lint/editlint.py`, `revise.py` (accept/reject keys, `_insert_moment`,
    `_insert_photo`, `stamps`).
- **Parity tests:** a new `scripts/export_parity.py` runs the desktop engine on the synthetic fixtures (`photo_dump`,
  `photo_single`, `day_in_life`, `aesthetic_cooking` + a brief) and writes their analysis JSON plus the expected
  story, polish and timeline to `ios/Tests/Golden/`. Swift tests feed the same analysis into PreProCore and must
  reach the same decisions: order, beats, stamps, text, music offset, left-outs. Analysis differs by platform (Vision
  vs OpenCV), so parity is checked at the decision layer.

**App (SwiftUI, iOS 26):**
- **Import:** the Photos picker (limited access is enough). PHAsset and AVAsset metadata give the capture time with
  its offset, the GPS and orientation, so Day in my life gets exact times for free.
- **Analysis:**
  - frames: AVAssetReader samples ~4 fps;
  - Vision: face rectangles, optical flow (motion, camera moves, shake), feature prints (duplicates, replacing
    phash), image classification (shot tags), aesthetics score, saliency;
  - sharpness and exposure: Core Image / Accelerate;
  - audio: a Swift beat tracker on Accelerate (onset strength → tempo → dynamic-programming beats → downbeats and
    sections) replaces librosa/numba;
  - speech: on-device SpeechAnalyzer with word times.
- **Edit and review:** PreProCore decides; the review screen keeps the desktop's decisions list (✓/✕ with the reason),
  one-tap decisions (stamps, photo motion), "bring it back" and the timeline.
- **Preview with no wait:** AVPlayer plays an AVMutableComposition and video composition live, so each change shows
  instantly. That's **better than desktop**, where you render first.
- **Render:** AVAssetWriter with hardware HEVC/H.264 and a Core Image compositor for crops, Ken Burns, the look and
  text in the same styles. Audio: AVMutableAudioMix ramps for ducking; −14 LUFS from a Swift EBU R128 meter and a
  true-peak limiter.
- **Export:** save to Photos, the share sheet straight to Instagram / TikTok / YouTube, `.srt`; later FCPXML for
  LumaFusion and Final Cut for iPad.
- **AI editor:** the order is
  1. Apple on-device (default when available);
  2. BYOK (URLSession, keys in the Keychain);
  3. the PC's plans (M6);
  4. the rules engine (always there).

  The privacy modes (nothing / text only / text + small thumbnails), face blur and the "sent" log stay. Beat-cut
  formats keep the rules layout; the AI picks clips, titles and words.
- **Background:** long analysis runs while the app is open (progress UI like desktop), plus `BGProcessingTask` to
  finish while charging.
- **UI:** the desktop's design language (tokens, light/dark, brand logos in Settings → AI editor), built for one hand.

## Milestones (each ends green on CI with an .ipa you can install)
| # | What you get | Sessions |
|---|---|---|
| M0 | `ios/` project via XcodeGen, `ios.yml` CI (build, Simulator tests on an iPhone 17 Pro simulator, unsigned .ipa on `ios-nightly`), the tester install guide (SideStore); a starter app with build number and "Send test report" installed on the iPhone 17 Pro; the PreProCore skeleton with the schemas and the playbooks loader | 1 |
| M1 | **Photo reel on iPhone**: Photos import with metadata, Swift beat tracker, photo reel port, live preview, render, save/share, review ✓/✕; parity tests | 3 |
| M2 | **Day in my life + your words on video + aesthetic**: video analysis with Vision, duplicates, clock, genre guess, the three ports, natural-sound mix, loudness | 4 |
| M3 | **AI editor**: Apple on-device (titles, line↔clip matching from Vision labels, soft captions for silent vlogs), BYOK (5 providers, Gemini/OpenRouter free tiers), Keychain, privacy, Settings with logos | 2 |
| M4 | **Talking formats**: SpeechAnalyzer transcripts, filler/retake/false-start cuts, story vlog + talking head, word-pop captions, speaker framing | 4 |
| M5 | **Real-phone polish** with your footage: speed, memory, heat, background finishing, one-hand UX | 2 |
| M6 | **PC companion, one scan to connect** (details below): the phone offers the PC for the heavy lifting when a cut looks messy or the job is big; the PC uses your Claude/ChatGPT/Gemini plans and does its exports; results come back to the phone | 2–3 |
| M7 | **Publishing** (when you decide to pay $99/yr): TestFlight, App Store listing and privacy labels | 1 |

**Where it stands**
- **M0: done** (2026-11-07). The starter app is built on GitHub's Mac and is on `ios-nightly` for the testers.
- **M1: in progress.**
  - Done: the photo reel's editing brain runs in PreProCore and makes the same decisions as the desktop on the
    fixture shoots, checked on every build: which photos and in what order, the cover, the song, where in the song
    the cut starts, every photo's beats, your lines and the reasons.
  - Next: the timeline (layout on the beat, photo motion, words placed off faces, the music), the Swift beat
    tracker, Photos import, live preview, render, save and share.

## M6 in detail: "for the full heavy lifting, connect your PC"
**When the phone suggests it.** Never as a nag: one calm card on the review screen with the reason in plain words,
plus "Connect my PC" and "Not now" buttons. It appears when:
- **the cut looks messy to the critic:** a low ghinn / critic score, or failed cringe checks it can't fix itself (a
  cut inside a word, a moment repeated, text too fast to read, a jump cut it couldn't hide). Example: "3 things still
  look rough here: your PC can re-edit this with your Claude plan and fix them";
- **the job is too big for a phone:** long talking footage (podcasts, a 20-minute vlog), many clips, 4K renders,
  Premiere/Resolve exports;
- **the phone is struggling:** hot (thermal state serious), low battery while not charging, or a render that would
  take longer than the PC would;
- **you ask for something only the PC has:** your Claude / ChatGPT / Gemini plan as the AI editor, or exports for
  Premiere, Resolve and Final Cut.

**Connecting is one scan.**
- The desktop app shows a QR code in Settings → "iPhone".
- Scanning it with the iPhone camera (or in PrePro) opens PrePro and connects. Nothing to type: the QR carries the
  PC's address, a one-time pairing code and the PC's certificate fingerprint.
- The phone finds the PC again by itself on the same Wi-Fi (Bonjour) and reconnects on later launches. It shows
  "Connected to <PC name>" like a headphone pairing.
- Security: LAN only; the engine still binds to localhost and a pairing-only endpoint lets the paired phone in with
  a per-device token, revocable in desktop Settings.

**The handoff is seamless.**
- The phone sends the project (its analysis JSON, your decisions, and the clips at the size the PC needs), and the
  progress bar continues on the phone.
- The PC re-edits with its full engine and your plan, and returns the timeline and the rendered video.
- The review screen updates in place; your ✓/✕ decisions and notes carry over.
- If the PC goes away mid-job, the phone keeps its own cut and says so.

## Time on Opus 5.5 (max effort)
- A "session" is a working stretch like today's: a few hours of building and checking, ending in a commit and a green
  CI build.
- **About 19–20 sessions in all.** A first app you can use daily (photo reel, Day in my life, words on video, rules
  engine) arrives after **~8 sessions (M0–M2)**, and with Apple's free AI editor after **~10**.
- At about one session a day, that's roughly **3–4 weeks to full desktop-level formats** and **~2 weeks to the first
  real app**.
- What slows it most: no local Mac (every compile is a ~10-min CI round trip) and on-phone checks done by someone
  else. Each milestone waits for the testers to install the build, film, and send a report back through you; plan
  about a day of tester turnaround per milestone.
- Cost: $0 beyond your current Claude plan. Long max-effort sessions do use the plan's usage limits, so spreading
  them out avoids hitting the weekly cap.

## Risks and how they're handled
- **Beat tracking quality without librosa:** port the same algorithm and check it against the desktop on the
  fixture songs (the parity tests compare beat times within 20 ms).
- **Apple's on-device model is small (4k tokens):** short, structured prompts per task (one direction, one title,
  one line↔clip set). BYOK or the PC companion for heavier passes; the rules engine always works.
- **7-day free signing:** AltServer refreshes it automatically on the same Wi-Fi; paying $99 removes the limit.
- **Two implementations drifting apart:** the shared playbooks YAML, the shared JSON schemas and the golden parity
  tests on every CI run.
- **iOS stops background work:** keep the app open while it analyses, plus `BGProcessingTask` while charging.

## Verification (every milestone)
- CI: PreProCore unit and parity tests, app UI tests on the iOS Simulator (import the fixtures, make the cut, check
  the timeline JSON and an exported file's duration, loudness and frames), a lint (SwiftLint), and an .ipa artifact.
- On the **iPhone 17 Pro (primary)**, then the **iPhone 17 (secondary: less memory, the base chip, for speed and
  heat)**:
  1. The tester installs the milestone's build from `ios-nightly` via SideStore.
  2. They run its checklist (`docs/QA.md`, "iOS") on their own footage.
  3. They send the in-app test report, plus the exported cut and a screen recording if they like.
  4. I review it as an editor and fix taste issues, then the next build goes out.
- Because the testing is remote, each milestone's checklist is short (5–10 steps, plain words), and every build shows
  its version and build number on the start screen, so reports name the build they came from.
- Desktop unchanged: the existing Python CI stays green; `scripts/export_parity.py` runs in CI so golden files can't
  go stale.

## Files
- New: `ios/project.yml`, `ios/PreProCore/` (Swift package: Schema, Knowledge, Clock, Context, Music, Brain/*,
  Compiler, Captions, Lint, Revise), `ios/PrePro/` (SwiftUI app: Import, Analysis, Render, Review, Settings, AI),
  `ios/Tests/`, `.github/workflows/ios.yml`, `scripts/export_parity.py`, `docs/IOS_INSTALL.md`, `docs/IOS_PLAN.md`
  (this plan, kept current).
- Reused as is: `src/prepro/knowledge/*.yaml`, the fixtures in `src/prepro/fixtures/` (via the parity export), the
  design tokens and copy from `ui/src/styles.css` and `ui/src/pages/Settings.tsx`, and the brand logos in
  `ui/src/assets/brands/`.

## Sources
- Apple: [TN3193, the on-device model's context window](https://developer.apple.com/tutorials/data/documentation/technotes/tn3193-managing-the-on-device-foundation-model-s-context-window.md),
  [managing the context window](https://developer.apple.com/tutorials/data/documentation/foundationmodels/managing-the-context-window.json)
- Device/OS requirements and the iOS 27 image-input note (third-party, unverified):
  [blakecrosley.com](https://blakecrosley.com/blog/apple-foundation-models-framework)
- Plan logins in third-party apps: [gigazine](https://gigazine.net/gsc_news/en/20260220-anthropic-third-party-block),
  [falcao.org](https://falcao.org/posts/anthropic-claude-access-crackdown-ecosystem-fallout/)
- iPhone terminals (a vendor's guides; the iSH claim is unverified):
  [Claude Code on iPhone](https://cosyra.com/guides/claude-code-on-iphone.html),
  [Cosyra vs iSH](https://cosyra.com/guides/cosyra-vs-ish.html)
