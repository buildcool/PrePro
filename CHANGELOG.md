# Changelog

All notable changes to PrePro are recorded here. Versions follow the release ladder in `docs/PLAN.md` §12.

## [Unreleased]
### Added
- M3 AI brain: provider-neutral contract with connectors for Claude Code CLI (your Claude plan), Codex CLI (your
  ChatGPT plan), Anthropic API (claude-opus-5-5, structured outputs, prompt caching, server-side refusal fallback),
  OpenAI, xAI Grok, OpenRouter (data_collection=deny), Gemini (free/paid), Ollama (local) and a stub.
- AI passes (vision tags from contact sheets, director, story, polish, critic, brief parsing) that improve the rules
  draft; strict JSON schemas, ID validation, one repair round, fallback to rules on any failure; brief rules always win.
- Privacy levels (local / text / thumbs, optional face blur), sent-data log (`.prepro/sent/`), training badges,
  cost/plan-usage meter; `prepro brains list|add|key|route|privacy|compare`.
- Hook tightening (enter late at the payload clause); critic fixes targetable by `type:anchor`.

## [0.1.0] — 2026-11-04
### Added
- M0 scaffold: package layout, CLI, docs, synthetic shoots with ground truth (7 genres), real test-media fetcher, CI.
- M1 local analysis: ASR (sidecar / faster-whisper / PocketSphinx) + Silero VAD, fillers, retakes, false starts,
  greetings, emphasis; shots, quality flags, camera moves, whips, faces, subject tracks, action peaks, duplicates;
  music BPM/beats/downbeats/sections/key/mood; audio report; days/places; genre guesses; brief parser (EN + Hinglish).
- M2 Basic brain (directions, hooks, coverage gaps, per-genre stories, polish), compiler (speech tightening with
  acoustic snapping, jump-cut punch-ins, operator reframing, transitions, overlays, memes, text, SFX, music with
  drop alignment/backtiming and ducking, captions), EditLint + critic, renderer (−14 LUFS, storyboards).
