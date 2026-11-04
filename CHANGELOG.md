# Changelog

All notable changes to PrePro are recorded here. Versions follow the release ladder in `docs/PLAN.md` §12.

## [Unreleased]

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
