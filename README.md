# PrePro — the AI pre-edit engine for creators

Point PrePro at a **shoot folder** (raw clips + music + memes/SFX, optionally a brief) and it gives you a
**reasoned first cut**: every cut, zoom, caption, music cue, meme and speed change comes with the reason it
was made, so you (or your editor) can review it in minutes instead of building it from scratch in hours.

- **Local-first.** Your raw videos, photos and audio never leave your PC. Analysis, rendering and export
  run locally. If you connect an AI, it only sees transcript text, clip facts and (optionally) small
  thumbnails.
- **Thinks like an editor, not a template.** Edits follow a written "editor's constitution" (Murch's Rule of
  Six, hook → retain → reward, "but/therefore" story beats, restraint budgets per genre) and pass a
  quality gate (EditLint + critic) that rejects the things viewers hate: mid-word cuts, music over voice,
  effects with no motivation, captions over faces, dead zones.
- **Several directions, not one guess.** Each shoot gets 2–4 direction cards (story vlog, cinematic travel
  film, hype reel, aesthetic, teaser…), each with three hook options and a list of missing shots.
- **Guided or Auto.** Give a brief (type, plan, text, captions, music, memes, effects) by form, `brief.md`
  or a voice note — or give nothing and let Auto mode decide.
- **Any AI, subscription-first.** Works with no AI at all (Basic mode), with your existing Claude Pro/Max or
  ChatGPT Plus plan through their official CLIs, with Gemini's free API tier, or with API keys for Claude,
  OpenAI, Gemini, Grok, OpenRouter, or local Ollama models.
- **Exports where you finish.** Premiere Pro / DaVinci Resolve (FCP7 XML), Kdenlive (OTIO), Shotcut (MLT),
  phone apps (InShot, VN, KineMaster, Edits — clean MP4 layers + stems + cue sheet), or a finished MP4.

> Status: under active development. See `CHANGELOG.md` and `docs/HANDOFF.md`.

## Quick start (developer install)

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -e ".[asr,ai,geo,dev]"
.venv/bin/prepro doctor
.venv/bin/prepro demo travel_vlog --out demo-shoots      # synthetic shoot with ground truth
.venv/bin/prepro analyze demo-shoots/travel_vlog
.venv/bin/prepro directions demo-shoots/travel_vlog
.venv/bin/prepro build demo-shoots/travel_vlog --direction auto
```

Requirements: Python 3.11–3.13, ffmpeg/ffprobe on `PATH` (or `PREPRO_FFMPEG`). Optional: NVIDIA GPU for
faster transcription.

## How it works

```
[0 Brief] → [1 Ingest] → [2 Analyse (local)] → [3 Decide: Director → Story → Polish → EditLint → Critic]
          → [4 Compile to a frame-exact timeline] → [5 Review] → [6 Export / Render]
```

Read `docs/ARCHITECTURE.md` for the module map and `docs/PLAN.md` for the full product plan and research.

## Privacy

| Mode | What leaves your PC |
|---|---|
| Local only (Basic brain / Ollama) | nothing |
| Text only | transcript text + clip facts (IDs, durations), no images |
| Text + thumbnails | the above + small low-res frames (optional face blur) |

File names, paths and exact GPS coordinates are never sent. Every request is recorded in a local
sent-data log you can inspect. Whether a provider may train on what is sent depends on the provider and
your account settings — the app shows a training badge per connector (see `docs/PLAN.md` §4).

## Licence

Proprietary — © buildcool. All rights reserved. Bundled fonts are SIL OFL 1.1 (see `assets/fonts`).
