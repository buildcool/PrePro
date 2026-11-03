# Architecture

PrePro is a Python engine (CLI + local HTTP server) with a React review UI wrapped in an Electron shell.

## Pipeline

| Stage | Module(s) | Output |
|---|---|---|
| 0 Brief | `brief/` | `CreatorBrief` (hard rules, preferences, open questions) |
| 1 Ingest | `project.py`, `media/probe.py`, `media/proxy.py`, `analyze/classify.py` | `Asset` list with stable IDs (C01 video, A01 audio, I01 image, L01 LUT), proxies, 16 kHz audio |
| 2 Analyse | `analyze/*` | `ClipAnalysis` per asset → `ProjectAnalysis` (`.prepro/analysis.json`) |
| 3 Decide | `brain/` (`basic` rules brain or AI connectors in `brain/providers/`) | `DirectionSet`, `StoryPlan`, `PolishPlan`, `CriticReport` |
| 4 Compile | `timeline/compiler.py` (+ `timeline/captions.py`, `timeline/audio_mix.py`, `timeline/reframe.py`) | `Timeline` (frame-exact, NLE-style tracks) |
| Gate | `lint/` (EditLint) + critic pass | lint findings, auto-fixes, scorecard |
| 5 Review | `server/` + `ui/` | accept/reject suggestions, knobs, comments → revise pass |
| 6 Export | `export/` | FCP7 XML, OTIO, MLT, phone pack, SRT/VTT/ASS, MP4, HTML editor brief |

## Rules that keep edits from feeling like "random stitching"

1. **IDs, not timestamps.** Brains reference segment/word/shot/asset IDs only; the compiler resolves them
   to times, snaps cuts to low-energy points (never mid-word) and adds handles.
2. **Every effect carries a motivation** (`Suggestion.reason`); EditLint drops unmotivated effects.
3. **Restraint budgets** per playbook (zooms/SFX/memes/transitions per minute, spacing, no repeats).
4. **Sound first:** speech intelligible, music ducked ≥ 12 dB under speech (bed mode), −14 LUFS master.
5. **Low-confidence ideas are optional markers**, not applied edits.

## Data model (src/prepro/schema)

- `media.py` — `MediaInfo`, `Asset`, `AssetKind`
- `analysis.py` — `Word`, `Segment`, `Transcript`, `Shot`, `MusicInfo`, `AudioReport`, `ClipAnalysis`, `ProjectAnalysis`
- `plan.py` — `Direction`, `HookOption`, `Knobs`, `StoryPlan`, `PolishPlan`, `EffectCue`, `MusicCue`, `CriticReport`, `FixOp`
- `brief.py` — `CreatorBrief`, `HardRule`, `Preferences`
- `timeline.py` — `Timeline`, `Item` (linked video/audio items → J/L cuts), `Caption`, `Marker`, `Suggestion`

## Cache layout (`<shoot>/.prepro/`)

`proxies/` 540p CFR proxies · `audio/` 16 kHz mono WAVs · `frames/` keyframes & contact sheets ·
`analysis.json` · `timelines/` · `renders/` · `exports/` · `qa/` storyboards · `sent/` sent-data log.
