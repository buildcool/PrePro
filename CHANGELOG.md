# Changelog

All notable changes to PrePro are recorded here. Versions follow the release ladder in `docs/PLAN.md` §12.

## [Unreleased]

## [0.1.0] — 2026-11-04
### Added
- M0 scaffold: package layout, CLI, docs, synthetic shoots with ground truth (7 genres), real test-media fetcher, CI.
- M1 local analysis: ASR (sidecar / faster-whisper / PocketSphinx) + Silero VAD, fillers, retakes, false starts,
  greetings, emphasis; shots, quality flags, camera moves, whips, faces, subject tracks, action peaks, duplicates;
  music BPM/beats/downbeats/sections/key/mood; audio report; days/places; genre guesses; brief parser (EN + Hinglish).
- M2 Basic brain (directions, hooks, coverage gaps, per-genre stories, polish), compiler (speech tightening with
  acoustic snapping, jump-cut punch-ins, operator reframing, transitions, overlays, memes, text, SFX, music with
  drop alignment/backtiming and ducking, captions), EditLint + critic, renderer (−14 LUFS, storyboards).
