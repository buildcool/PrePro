# PrePro — AI "pre-edit" engine for Insta/YouTube creators (working name)

## Context

Creators shoot dozens of clips. Then comes the slowest, most skill-heavy step: deciding what to cut and merge, the order, and where music, memes, SFX, captions (big vs small text), zooms, slow-mo, speed-ups and transitions go. They also have to decide how long the video should be. Today's AI tools either do one narrow job (silence removal, captions) or produce generic "random stitching". That means out-of-context clips, unmotivated zooms/SFX and a recognisable template look, and viewers find it irritating ("ghinn / chidh").

**Goal:** a desktop app for **Linux + Windows**. Point it at a shoot folder (footage + music + memes/SFX). Optionally the creator adds a **brief**: video type, plan, text, captions, music, memes, effects. Anything left out is decided automatically (**Auto mode**). It analyses everything **locally** and proposes **2–4 creative directions** (story vlog, cinematic travel film, hype reel, teaser…). It then builds the chosen direction as a **first cut where every edit carries a stated reason**. The creator reviews and toggles suggestions, then exports to an editor or renders a finished MP4. It works like an assistant editor, and every suggestion can be reviewed. It is not a black-box auto-editor.

**Decided with you:**
- v1 is the after-shooting engine; a pre-shoot planner comes later.
- Exports: Premiere/Resolve, phone apps (InShot/VN/KineMaster/Edits) and Kdenlive/Shotcut.
- AI is hybrid local-first. Footage never leaves the PC; the AI only sees text plus small thumbnails.
- **Any AI, subscription-first.** The brain works with Claude, ChatGPT/OpenAI, Gemini, Grok, OpenRouter or local models. By default it reuses a subscription you already pay for, through that provider's own official CLI, or a free tier. That means no per-project spend before you've seen the quality.
- First genre family tuned deeply: **vlog / travel / lifestyle**. Other genres get baseline playbooks in v1 and deep tuning in Phase 2.
- Captions are multilingual (any language Whisper supports), with an optional romanized-Hinglish caption mode.

**Starting point:** `/home/user` is empty (greenfield). The container has Python 3.13, uv, ffmpeg 6.1, Node 22, git and the `claude` CLI, and no GPU. The project will live in `/home/user/prepro`.

---

## 1. The editor's brain: research turned into rules

### 1.1 Who we learn from and what the engine encodes
| Source | Encoded as |
|---|---|
| Walter Murch, *In the Blink of an Eye* | **Rule of Six** priority for every conflicting cut decision: emotion > story > rhythm > eye-trace > 2D plane > 3D space. Cut where a thought or emotion ends. |
| MrBeast production memo | The first minute is where most viewers leave. The opening must deliver what the title/thumbnail promised. Plan a re-engagement around ~3 min. Metrics: CTR, AVD, AVP. |
| Jenny Hoyos (Shorts) | Hook < 3 s, visual, understandable on mute, foreshadows the payoff. Pacing curve: fast hook → medium → peak/joke mid-way → medium → fast end. Loop endings. |
| Alex Hormozi | **Hook → Retain → Reward** units, chained so each reward opens the next hook. Bold word-by-word captions for talking content. |
| Paddy Galloway | The first ~30 s of a long video should work as a standalone Short. |
| Casey Neistat | Three-act day story. B-roll *advances* the story rather than just covering cuts. Time-lapses and whip pans as transitions. Location as a character. An occasional mid-sentence "cut-off". |
| Trailer editors | Setup → escalation → climax → **button** (stinger). Silence before the hit; risers and hits land on beats. Dialogue lines used as rhythm. Music backtimed to the climax. |
| Comedy editors | Hold before and after a punchline, or cut fast to the reaction. Memes/SFX go *after* the joke, never over it. |
| Trey Parker & Matt Stone | Beats connect with "but / therefore", never "and then". |
| CapCut 2026 trends | Velocity edits (speed ramps on bass hits) and beat sync, used only in hype directions. |
| Podcast clippers | One idea per clip. Keep the setup and qualifiers. Speaker-locked framing; switch on speaker change, not mechanically. |
| Retention-editing critics | Pattern interrupts help, but effects added out of habit read as noise. Over-editing exhausts viewers. |

There was no solid public breakdown of Indian creators' styles (CarryMinati, Dhruv Rathee etc.). Phase 2 **Style DNA** will measure those styles from reference videos instead of guessing.

### 1.2 Editor's constitution
It appears in three places: the rules engine, the AI system prompt and the critic rubric.
1. **Rule of Six order** decides conflicts.
2. **Every effect needs a motivation**: a word, an action, an emotion beat or a music hit. No motivation, no effect.
3. **Story spine before polish.** Every kept moment has a role (hook, setup, escalation, payoff, breather, CTA). Moments with no role get cut.
4. **Short-form hook ≤ 3 s** with visual + spoken + on-screen text layers. It must make sense on mute and foreshadow the payoff.
5. **Enter late, leave early.** Cut on action, breath or beat, never mid-word.
6. **Vary the rhythm.** Accelerate into climaxes, and give peaks room to land.
7. **Restraint budgets per genre**: max zooms/SFX/memes/transitions per minute, minimum spacing, no repeats.
8. **Sound is half the video.** Speech is always intelligible, music sits ≥ 12 dB under speech, output is −14 LUFS / −1 dBTP, and every cut gets a crossfade.
9. **Never lose context.** No orphan references ("as I said…"), and claims keep their qualifiers.
10. **Respect the genre.** An aesthetic GRWM and a hype reel get different pacing, captions and effects.

### 1.3 Why AI edits feel like random stitching, and the countermeasure for each cause
| Root cause | Countermeasure |
|---|---|
| No story; clips in shooting order | Story pass assigns roles; acts are built from time/GPS clusters (days, places) |
| Out-of-context clips, cut mid-thought | Sentence/breath snapping, context-dependency check, keep qualifiers |
| Effects at fixed intervals (the "template look") | Motivation rule + budgets + EditLint |
| Monotone or jarring rhythm | Beat/breath-aligned cuts, shot-length variation lint, punch-in alternation on jump cuts |
| Mood mismatch | Emotion tags per moment drive music/SFX/meme choice; no memes in sad, tense or aesthetic moments |
| Sensory fatigue | Loudness and ducking lints, face-aware captions, platform safe zones |
| Visual inconsistency | Shaky/blurry/dark filtering, best-take picking, colour-jump warnings |

The emotion taxonomy, inspired by the Navarasa, is: fun, wonder, hype, calm, beauty, tension, sad/nostalgic, absurd, shock, gross-out. It drives music mood, SFX/meme intent, pacing and caption style.

### 1.4 Direction engine: the "multiple paths"
After analysis, the Director proposes **2–4 direction cards** that fit the footage. If your brief asks for a specific direction, that one is built first (see 1.9). Each card shows:
- format and target length
- a fit score with reasons
- **3 hook options** (each with quote/shot and thumbnail)
- a beat outline
- default knobs
- **coverage gaps**, for example "no establishing shot of Day 2" or "no closing line; record a 5 s outro". This is pre-production feedback for the next shoot.

You can pick several directions, and each becomes its own timeline (one shoot → vlog + reel + teaser). Knobs on every direction:
- pace (calm ↔ fast)
- effects (clean / **balanced** / bold)
- captions (off / clean / bold word-pop)
- humour (off / light / heavy)
- music track
- target length

### 1.5 Decision grammar: answers to "where is a cut / merge / slow-mo / meme… needed?"
| Decision | Signals the engine reads | Decided by | Guardrail |
|---|---|---|---|
| **Cut** | silences, fillers, retakes/false starts, off-topic tangents, shaky/blurry/dark/"pocket" shots, near-duplicates | rules first; AI for retakes and tangents | never mid-word; keep 2–6 frames of breath; vlogs stay less tight than explainers |
| **Merge / order** | creation time, GPS place clusters, transcript continuity, story role | AI story pass | causal flow, no orphan references |
| **Best moment inside a long clip** | stability, sharpness, motion interest, aesthetic score, faces | rules + vision tags | enter late / leave early, cut on action |
| **Slow-mo** | motion peaks (splash, jump, pour, hair flip), source fps ≥ 2× timeline fps | rules propose, AI confirms meaning | true high-fps only; otherwise marked "optical flow in NLE"; ≤ 1–2/min in vlogs |
| **Speed-up / time-lapse** | long low-information continuous shots (walking, driving, cooking steps) | rules | 2–16×; never over speech |
| **Speed ramp** | motion + music hits/drops | rules, beat-aligned | hype/velocity directions only |
| **Music** | speech coverage per section (→ soundtrack mode, see 1.8), content emotion, direction, track BPM/energy/sections | AI writes the music brief and picks; rules match, place, duck and backtime | bed mode: ≥ 12 dB under speech, no vocals under speech; front mode: cut to the music; ends on a downbeat |
| **Memes / SFX** | punchlines, irony, fails, reactions (transcript + prosody), on-screen action | AI intent + your library + meme catalogue (see 1.8) | after the punchline; budgets; no repeats; none in emotional/aesthetic moments |
| **Captions** | speech, platform, direction | rules (chunking/layout) | ≤ 2 lines, readable speed, face-aware, safe zones |
| **Big vs small text** | emphasis (prosody + meaning): numbers, names, claims, punchlines → big; asides → small | AI + prosody | ≤ 1 highlighted word per chunk; consistent styles |
| **Zoom / punch-in** | emphasis words, jump cuts with the same framing, reactions | rules + AI | alternate 100/115 %; budget per minute; no random drifting zooms |
| **Transitions** | location/time change, act boundary, whip pans already in the footage, music section change | rules + AI | hard cut by default; stylised only at section changes; one style per video |
| **B-roll overlay** | nouns/places in speech ↔ shot tags | AI | covers jump cuts; relevant; ≥ 1.5 s |
| **Title cards** | day/place/time changes, chapters | rules + AI | minimal in aesthetic styles |
| **Duration** | direction target + strength of the material | AI + rules | never pad; flag if the material is thin |

### 1.6 Genre playbooks
Stored as versioned YAML (`knowledge/playbooks/*.yaml`). Each holds detection cues, offered directions, structure template, pacing ranges, effect budgets, caption/music/SFX/meme policy, signature techniques and don'ts. **The same file feeds the rules engine, the AI prompt and the critic.**

| v1 deep playbook | Format / length | Structure | Signature techniques | Restraint |
|---|---|---|---|---|
| **Story vlog** | 16:9, 8–15 min | cold open (peak moment, 5–15 s) → ≤ 3 s title → setup → journey/conflict (re-hook at each new place, ~every 2–3 min) → payoff → reflection → ≤ 10 s outro | establishing → medium → detail → reaction scene grammar; B-roll moves the story; time-lapse compresses travel; J-cut ambient sound into new places; cards like "Day 2 · Udaipur · 6:10 AM" | zooms ≤ 3/min, SFX ≤ 4/min, stylised transitions only at location changes, memes only if the tone is comedic |
| **Cinematic travel film** | 16:9 or 9:16, 1–4 min | mapped to music sections: intro (establishing, slow) → build (cut every 2 beats) → drop (best kinetic shots on beats, ramps on hits) → break (slow-mo/people) → outro (wide/sunset) | motion-direction continuity, match cuts, whip pans found in the footage, natural-sound accents under music, consistent grade | minimal text, 1 transition style |
| **Hype / velocity reel** | 9:16, 7–15 s or 15–30 s | frame-1 spectacle → beat-synced escalation → loop ending | speed ramps on bass hits, flash/shake only on drops, 3–7-word text hook | flash/shake ≤ 1 per 4 bars; can export without music so trending audio can be added in-app |
| **Aesthetic / day-in-life / GRWM / cooking** | 9:16 30–60 s or 16:9 5–10 min | most satisfying shot first → calm progression → final reveal | hold satisfying actions, close-ups, ASMR foley up and music down, slow push-ins, slow-mo pours, 2–8× for long steps, soft small text | no cartoon SFX, no memes, no hard zooms |
| **Teaser / trailer** (for any long video) | 15–30 s | setup → escalation → climax → button after a silence | dialogue lines as beats, riser → silence → hit, music backtimed | ≤ 30 s |

**Baseline playbooks in v1, deep-tuned in Phase 2:** talking head/educational, podcast clips, gaming, comedy/skits, tech review, fitness.

### 1.7 Quality gate (the anti-irritation system)
- **EditLint** is deterministic and auto-fixes where safe. It checks for:
  - mid-word cuts and missing audio crossfades
  - shots < 0.4 s outside montages, and monotone shot lengths
  - **dead zones** (no visual, audio or information change for longer than the playbook limit) and **over-stimulation** (effect density above budget)
  - repeated SFX/memes, unmotivated effects, and jump cuts with no framing change
  - caption problems: more than 2 lines, over a face, outside safe zones, too fast to read, too many highlighted words
  - loudness off target, music ducked less than 12 dB under speech, or music vocals under speech
  - shaky/blurry/dark shots kept, colour jumps between adjacent shots
  - slow starts (a greeting before the hook, or the first word after 0.5 s), dead endings, Shorts that don't loop
  - duration outside the target
- **Critic pass**: the AI acts as a senior editor reviewing a junior's cut. It reads the annotated **paper edit**: the final-order transcript with `[ZOOM] [SFX] [MEME] [B-ROLL] [MUSIC] [CARD]` marks, plus the attention-curve metrics and lint results.
  - It scores hook, clarity, story, pacing, payoff, emotional consistency, over-editing risk and genre fit.
  - It returns fix ops from a whitelist: drop/move effect, swap hook, trim/drop segment, shift music, lower density.
  - Safe ops are applied automatically, for at most 2 rounds. The scorecard is shown in the UI.
- Low-confidence suggestions are **not applied**. They appear as optional markers instead.

### 1.8 Assistant suggestions beyond the cut
**Soundtrack modes.** The engine measures how much of each section contains speech, then picks the music's role:

| Situation | Mode | What the music does | Rules |
|---|---|---|---|
| Voice-led (talking to camera, voice-over) | **Bed** | supports the voice, never competes | instrumental, low–mid energy, ducked 12–18 dB under speech, swells in pauses and B-roll gaps, changes at section boundaries |
| No voice (montage, cinematic, aesthetic, hype) | **Front** | leads the edit | cuts follow beats and sections, the drop lands on the best moment, vocals allowed, natural-sound accents |
| Mixed (vlog: talking + montages) | **Bed ↔ Front** | switches per section | music swells in (J-cut) before a montage and ducks back for talking; one consistent family of tracks |
| Natural-sound-led (ASMR, cooking, nature) | **Light or none** | foley is the star | very soft music, or a "no music" suggestion |

**Music suggestions** (per direction and section):
- **Music brief**: mood, energy curve, BPM range, genre/instruments, vocals yes/no, structural needs (e.g. "drop at 0:12 for the reveal") and length.
- **Your library first.** Tracks in your music folder are analysed once (BPM, key, energy curve, sections, length, vocals tag). The top 3 matches come with reasons, e.g. "88 BPM fits the walking shots; its energy rise at 0:45 lands on your reveal".
- **No good match → "find it" search terms** to paste into YouTube Audio Library, a royalty-free library you use, or Instagram's in-app audio. The AI never invents track names; it only names tracks from catalogues it can check (your library now, library APIs later).
- **Copyright notes.** Commercial songs are safest added inside Instagram's own music picker (personal/creator accounts). Baked into the video file they can be muted or claimed, and on YouTube they trigger Content ID claims. The app warns based on file tags.
- **Trending audio.** For music you'll add in-app, the engine exports a no-music version plus a beat plan. Drop in the audio you picked and it re-cuts to those beats.

**Meme and SFX suggestions:**
- The AI marks **meme moments** (punchline, irony, fail, shock, awkward pause, flex, relatable, wholesome) with intent and intensity. It also marks **no-meme zones**: sad, serious, aesthetic and sponsor segments.
- Matches come from **your meme library** (tagged once) and a curated **meme catalogue** (`knowledge/memes.yaml`).
  - Each catalogue entry records name, type (sound / visual / GIF / template), intent, tone (clean/edgy), culture (global / Indian-Hinglish / Gen-Z), duration, placement notes and a freshness date.
  - The catalogue stores names and search terms, never the copyrighted clips themselves.
- The AI may only suggest from the catalogue or your library, so it can't make up memes. Items you don't have come with search terms.
- **Settings:** meme flavour, tone, and frequency (off / light / heavy).
- **SFX:** motivated sounds (whoosh on movement, pop on text, riser → hit on reveals, ambience beds per location), from your library plus the bundled starter pack.

**More editor helpers in v1:**
| Helper | What it does |
|---|---|
| **Voice polish** | detects noise, hum, wind, clipping and echo; applies safe local fixes (denoise, high-pass, de-ess, compression, loudness) or asks for a re-record ("people forgive bad video, not bad sound") |
| **Voice-over script** | when there's no narration or a context gap, writes a short VO (hook line, bridges, outro) in your language; you record it, drop it in, and the engine re-cuts around it |
| **B-roll gaps** | "cover this line with a shot of X": from your own footage first, otherwise stock-footage search terms |
| **Text & graphics** | location/day cards, number/price callouts, list counters, text hooks |
| **Look suggestions** | mood-based grade presets (warm travel, teal-orange cinematic, soft pastel aesthetic, punchy hype) as LUTs we generate ourselves, plus colour-jump flags between shots |
| **Retention heat strip** | the attention curve drawn over the timeline, showing likely drop-off zones |
| **Light safety checks** | profanity bleep/mute suggestions (incl. Hindi) for brand-safe or family-friendly versions |
| **Organised bins** | the NLE export arrives sorted: A-roll, B-roll by day/place, best takes, rejects, music, SFX, memes; plus a search box over transcript and shot tags ("laughing at the beach") |
| **Editor brief** | the HTML report becomes a hand-off doc: story outline, chosen direction, music brief, every suggestion with timecode and reason, missing assets |

**Later phases:**
- **Phase 2:**
  - thumbnail frame picks with text-overlay mock-ups; titles, descriptions, hashtags, chapters
  - in-app stock search (Pexels/Pixabay APIs) and GIF search (GIPHY/Tenor)
  - in-app VO recording with a scratch TTS voice
  - AI music-generation connectors (licences checked first)
  - audio-fingerprint copyright check
  - privacy blur for bystander faces, number plates and screens
- **Phase 3:** trend-aware audio/format suggestions per niche; translated captions and dubbing.

### 1.9 Creator brief and comments: guided or auto
Before processing, the creator can tell the engine what they want, in as much or as little detail as they like. Anything left out is decided automatically. With no brief at all, the engine runs in **Auto mode**.

**Ways to give a brief:**
- **Wizard step "Tell us about this video"**: a short form plus a free-text box in any language, Hinglish included.
- **Files in the shoot folder**, so a creator can send footage + instructions to an editor in one folder:
  - `brief.md` / `brief.yaml`, or a voice note `brief.m4a` (transcribed locally)
  - an optional `notes.yaml` with per-clip notes
  - optional filename tags: `HOOK_`, `MUST_`, `SKIP_`
- **Clip notes in the app**: click a clip or a moment and type, e.g. "use as hook", "funny bit at 0:32", "sponsor part", "don't show my friend's face".

**What a brief can contain (all optional):**
| Area | Examples |
|---|---|
| Type, platform, length | "travel vlog for YouTube, ~10 min" · "Insta Reel, 30 s" · "vlog + 2 reels + teaser" |
| Goal and audience | "make people want to visit Udaipur" · "Hindi-speaking 18–25" |
| Story plan / script | outline or script, must-include and must-cut moments, preferred hook |
| Text | title cards, on-screen lines, CTA ("follow for part 2"), sponsor lines, custom caption text |
| Captions | on/off, style, language (English / Hindi / Hinglish), words to highlight |
| Music | "use song X for the montage", "no music while I talk", "I'll add trending audio in Instagram", or just a mood |
| Memes, GIFs, SFX | specific ones at specific moments, flavour, or "no memes" |
| Effects | "slow-mo on the cliff jump", "speed up the drive", "no zooms", transition style |
| Look and pace | warm/cinematic look, calm ↔ fast, effects intensity |
| Don'ts | faces, topics or words to keep out; "no swearing" |

**How the engine uses it:**
- An AI **brief parser** turns free text into a structured brief with three parts:
  - **hard rules**: must / never, a specific asset at a specific moment, deliverables
  - **preferences**: style, mood, pace, references
  - **open questions**
- References like "the cliff jump" or "when I say 'best momos'" are resolved to moments through the transcript and shot tags. Unclear ones become quick questions with thumbnails ("Which clip is the cliff jump?").
- **Hard rules** are enforced by the compiler and checked by a **brief-compliance lint**. **Preferences** steer the Director, Story and Polish passes. Auto fills the rest.
- **Your instruction wins, but conflicts are explained, never silently ignored.** Example: "10 must-have moments add up to 40 s but you asked for a 15 s reel; keep all, or let me pick the best 15 s?" Technical safety (loudness, clipping) still applies.
- **Creative freedom slider:**
  - *Follow my brief strictly*: only what you asked, plus technical cleanup
  - *Balanced* (default): your brief, plus the engine's own ideas marked optional
  - *Surprise me*: your brief is a starting point, with bolder alternatives
- **Brief checklist in the UI**: every instruction is shown as ✓ done or ✗ couldn't, with the reason.
- **Saved briefs**: save a brief as a reusable template ("My travel reel style"). It works as a lightweight personal style until Style DNA arrives in Phase 2.
- **Basic mode (no AI connector):** form fields, filename tags and clip notes still work. Free-text briefs need an AI connector.

**Comments on the first cut (the revision loop):**
- Leave timeline comments the way you'd give notes to an editor: "faster here", "meme here", "big text: ₹500 only", "swap this song".
- A **revise pass** turns them into edit ops for just that region, shown as a before/after that you accept or reject.
- Simple notes ("add text", "remove this zoom") also work as direct UI actions with no AI.

---

## 2. Ideal durations
These are defaults that you can change. Later the engine learns targets from the creator's own analytics.

| Format | Default target | Notes |
|---|---|---|
| Instagram Reel, hype/trend/velocity | 7–15 s | loopable, beat-synced |
| Instagram Reel, story/value/aesthetic | 30–60 s (≤ 90 s) | 45–60 s was the top engagement bracket in Socialinsider's data |
| YouTube Short | 20–40 s (cap 3 min) | about half of viral Shorts are 20–40 s; some library songs cap length at 30/60/90 s |
| Cinematic travel film | 1–4 min | one or two tracks |
| YouTube story vlog | 8–15 min | cold open 5–15 s; re-hook every ~2–3 min |
| Teaser for a vlog | 15–30 s | trailer structure |
| Long explainer (Phase 2 tune) | 8–12 min | hook + promise within ~15–30 s |

Sources disagree on platform caps (the Reels limit grew past 3 min in 2025–26), and retention matters more than raw length.

---

## 3. Pipeline

```
Shoot folder (footage/, music/, memes/, sfx/ — or flat; optional brief.md/.yaml/voice note, notes.yaml, LUTs)
  │
 [0 Brief]    optional: wizard form · brief file / voice note · clip notes · filename tags → hard rules + preferences (none → Auto)
  │
 [1 Ingest]   scan · classify · ffprobe (fps/VFR/rotation/creation time/GPS) · content-hash cache in <shoot>/.prepro/
  │           540p proxies · 16 kHz audio · optional CFR conform · optional DNxHR+PCM (Resolve on Linux)
 [2 Analyse]  (all local) ASR words+VAD · fillers · retakes · prosody emphasis · scenes · blur/exposure/shake ·
  │           motion & camera-move · near-duplicates · faces · best-moment windows · music beats/bars/sections ·
  │           loudness · day/place clusters (offline reverse-geocode) · vision tags by the AI on contact sheets (opt-out)
 [3 Decide]   Director → direction cards + hooks + gaps  ─► user picks
  │           Story pass → compile → Polish pass → compile → EditLint → Critic (≤ 2 rounds)
  │           (no AI connector → rules-only "Basic" brain)
 [4 Compile]  IDs → frame-exact times · acoustic snap (±150 ms to low-energy points) · handles · beat snap ·
  │           J/L cuts · punch-in alternation · face/subject-aware reframe · caption layout · ducking · music backtiming
 [5 Review]   player + timeline lanes + suggestion list with reasons · knobs · critic scorecard · lint panel ·
  │           brief checklist · timeline comments → revise pass
 [6 Export]   Premiere/Resolve XML · OTIO · MLT · phone pack · SRT/ASS/captions overlay · preview/final MP4 · HTML report
```

### Key analysis details
- **Classification.** Folder names override everything. Otherwise:
  - audio > 30 s → music; shorter audio → SFX
  - images/GIFs → meme overlays
  - speech ratio > 25 % with a face → A-roll, else B-roll
  - DJI naming → aerial; screen captures are detected separately
- **Fillers.** Whisper tends to drop "um/uh". We combine a verbatim prompt, a lexical list (including Hindi fillers such as "matlab" and "toh"), and an *unaccounted-speech* signal: VAD speech with no ASR words for > 150 ms.
- **Retakes.** Adjacent sentences with token similarity ≥ 0.6, or false starts. The default keeps the last fluent take, and the AI can override.
- **Best-moment windows.** Long phone clips are scored per second (stability, sharpness, motion interest, aesthetic, faces), and the top 2–5 s windows are taken with minimum spacing.
- **Music.** librosa beats + onset strength. Bar phase and sections (intro/build/drop/break/outro) come from energy plus a self-similarity novelty curve. The "instrumental" tag is user-settable, because there is no vocal detector without PyTorch in v1.
- **Motion.** Farneback optical flow on proxies gives pan/tilt/push/static/shake. Whip-pan bursts at clip ends become seamless transitions.

---

## 4. AI brain: any provider, subscription-first

The brain is **provider-neutral**. Every pass sends the same plain-text prompt (constitution + playbook + footage dossier) and a JSON Schema generated from our Pydantic models. Every reply is validated, every ID is checked, and a failed reply gets one repair round. So any capable model can be plugged in.

| Connector | You pay | Setup | Notes |
|---|---|---|---|
| **Basic (no AI)** | free | none | Rules only: silence/filler/retake cuts, best moments, beat-synced montage, captions, ducking, loudness, EditLint. Lets you judge the craft engine at zero cost. |
| **Claude Pro/Max via Claude Code** | your plan's normal limits | install Claude Code and sign in with your Claude account (Anthropic's own login) | Calls the unmodified `claude -p --output-format json --json-schema …` in an empty temp folder, with tools limited to reading our contact-sheet images. Anthropic's terms allow users to sign in to the unmodified Claude Code binary with their own plan. The app never reads or stores tokens. |
| **ChatGPT Plus/Pro via Codex CLI** | your plan's limits | install Codex CLI and "Sign in with ChatGPT" | `codex exec --output-schema … -i <image>` in a read-only sandbox. OpenAI's docs recommend API keys for scripting, but ChatGPT sign-in works. |
| **Gemini API free tier** | free, rate-limited | free key from Google AI Studio | Flash / Flash-Lite models; good for vision tagging. On the free tier Google may use what's sent (text + thumbnails only) to improve its products. A Google AI Pro subscription isn't usable through the API. Its CLI route changed in mid-2026, and I'll re-check it when building this connector. |
| **API keys (bring your own)** | pay per use | paste a key | Anthropic (Claude; default `claude-opus-5-5`), OpenAI, Google Gemini, xAI Grok, and OpenRouter (one key for many models, some free), each via its official SDK/API. SuperGrok subscriptions aren't usable programmatically, so Grok needs an API key. |
| **Local (Ollama)** | free | install Ollama + a model | Private and offline; quality depends on your GPU and model. |

- **Not supported, on purpose:** driving the ChatGPT/Claude/Gemini *websites* with your login cookies. It violates provider terms, gets accounts banned, and breaks often.
- **Per-pass routing:** each pass can use a different connector. For example, vision tagging on the free Gemini key, and Director/Story/Critic on your Claude or ChatGPT plan. A project needs about 10–15 AI calls.
- **Spend safety:**
  - free and subscription connectors come first, and a fresh install defaults to them
  - for pay-per-use keys: a cost estimate before every run, hard per-project and monthly caps, and a usage meter
  - **"Preview directions first"** runs only the Director call (direction cards + hooks), so you can judge quality before a full build
- **"Which brain is best?" report:** the eval harness runs the same test shoots through every connector you've set up and scores the results, so you know whether paying for anything is worth it.
- **Rough cost per project:**
  - $0 extra on a subscription or free tier
  - about $0.50–2 with pay-per-use top models (estimated at Claude Opus 5.5 rates of $4 in / $20 out per MTok)
- **Subscription limits:** usage counts toward your plan's normal limits. A Pro-tier plan can run out of its usage window on a big project; the app then pauses and offers to resume or switch connector.
- **Claude API adapter** (when you use an Anthropic key):
  - `client.messages.parse(output_format=<Pydantic>)` with adaptive thinking and explicit effort per pass (`high` for Director/Story/Critic, `medium` for Polish, `low` for vision)
  - no forced `tool_choice`, no sampling params
  - one append-only conversation with a cached system prompt and dossier
  - server-side refusal fallback **on by default** (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`); `stop_reason` checked; streaming for long outputs
- **Other adapters** use each provider's own structured-output mode and prompt caching where available. I'll check the exact SDK calls against each provider's current docs while building them.
- **IDs only:** the AI references segment/word/shot/beat/asset IDs, never raw timestamps.
- **Before distributing the app to other creators**, the company must accept Anthropic's Commercial Terms. Their conditions for running Claude Code inside a product: the binary is unmodified, each user signs in with their own plan, nobody resells usage, and "Claude Code" isn't used in our product name. OpenAI's and Google's terms get re-checked at the same point.

### Privacy: what leaves your PC and who can train on it
- **Raw videos, photos and audio never leave the PC**, in any mode. Analysis, rendering and exports all run locally. The app has no server of its own in v1, collects no footage, transcripts or usage data, and never uses anything to train a model of ours. Any future crash reporting will be opt-in and media-free.
- **What an AI connector receives** (only when one is switched on): the transcript text, clip facts (length, time) and, if enabled, small low-res still frames.
  - Clips are referred to by ID (`C07`), never by file name or path.
  - GPS is reduced to a city name, or dropped.
- **Three privacy levels**, set globally and per project:
  - **Local only:** the Basic brain or Ollama; nothing leaves the PC.
  - **Text only:** transcript and clip facts, no images.
  - **Text + thumbnails:** adds small frames, with optional face-blurring before upload.
- **"Private project" switch:** limits that project to local or no-training connectors.
- **Sent-data log:** a local, viewable record of exactly what was sent to which AI, per project.
- **Training badge in connector setup**, with a link to the provider's opt-out setting:

| Connector | Can the provider train on what's sent? |
|---|---|
| Basic / Ollama (local) | No; nothing is sent |
| Claude API key | No (commercial terms) |
| Claude Pro/Max via Claude Code | Yes if "Help improve Claude" is on; turn it off in Claude's privacy settings |
| ChatGPT Plus/Pro via Codex | Yes by default; turn off "Improve the model for everyone" (covers Codex too) |
| OpenAI API key | No by default |
| Gemini API free tier | Yes: used to improve Google products, and human reviewers may read it |
| Gemini API paid tier | No |
| xAI Grok API | Reportedly no without permission; verify before enabling |
| OpenRouter | Depends on the routed provider; request no-training providers where supported |

- **Local data:** caches live in `<shoot>/.prepro/`, with a "delete analysis cache" button. API keys go in the OS keychain (`keyring`).

---

## 5. Exports
| Target | Format | Contents |
|---|---|---|
| **Premiere Pro + DaVinci Resolve** | FCP7 XML (xmeml v5), our own writer | Tracks: A-roll, B-roll, memes, captions overlay, dialogue, music, SFX. Also constant-speed segments, scale/position keyframes (punch-ins, reframe), audio-level keyframes (ducking), cross-dissolves, and **markers carrying every suggestion and its reason** |
| **Kdenlive** | OpenTimelineIO `.otio` | cuts, tracks, markers |
| **Shotcut** | MLT XML | cuts, tracks, speed, basic filters |
| **Phone apps** (InShot, VN, KineMaster, Edits) | MP4 pack | H.264/AAC CFR clean cut (no captions), captioned version, music and SFX stems, SRT, and a cue sheet saying what to add where |
| **Any** | renders | Fast 540p preview; final 1080p at −14 LUFS; SRT/VTT/ASS; captions overlay as ProRes 4444 with alpha for NLEs; HTML edit report |

- Premiere's OTIO support is still beta, so Premiere gets FCP7 XML.
- Resolve's free Linux build can't decode H.264/AAC, so we offer DNxHR+PCM transcodes.
- CapCut drafts are deferred (unofficial format).

---

## 6. Tech stack
- **Engine:** Python 3.12 (uv-managed).
  - `faster-whisper` (includes Silero VAD), `opencv-python-headless` (incl. YuNet faces), `scenedetect`, `librosa`, `pyloudnorm`, `imagehash`
  - `opentimelineio`, `pydantic` v2, `typer`, `fastapi` + `uvicorn`, `keyring`, `platformdirs`, `reverse_geocoder`
  - **No PyTorch in v1**, which keeps installers small. Whisper models download on first run: `small`/`medium` int8 on CPU, `large-v3-turbo` on NVIDIA CUDA.
- **AI connectors:** official SDKs (`anthropic`, `openai`, `google-genai`, xAI's SDK/API, `ollama`) and OpenRouter's documented API. Subscription connectors shell out to the user's own `claude` / `codex` CLIs.
- **Media:** ffmpeg/ffprobe, bundled as separate executables (static builds with libass + harfbuzz). Rendering uses filtergraphs: trim/concat, `setpts`/`atempo`, `scale eval=frame` + crop for zooms/reframe, overlay, `ass` captions, `xfade`, `sidechaincompress`, 2-pass `loudnorm`.
- **Captions:** ASS styles with word-pop/karaoke, plus bundled OFL fonts: Montserrat, Bebas Neue, Inter, a serif and a handwritten face for aesthetic styles, and Noto Sans + Devanagari. Romanized Hinglish comes from AI transliteration.
- **UI:** React + TypeScript + Vite review app, talking to the engine over localhost REST + SSE progress.
- **Desktop:** an **Electron** shell (bundled Chromium plays H.264/AAC on Linux and Windows; Tauri's Linux webview depends on system GStreamer codecs). The engine runs as a sidecar, frozen with PyInstaller per OS.
  - Linux: AppImage/.deb, built in this container
  - Windows: NSIS installer, built on a GitHub Actions Windows runner

---

## 7. Repo layout (`/home/user/prepro`)
```
pyproject.toml · uv.lock
src/prepro/
  cli.py            # prepro analyze | directions | build | export | render | ui | brains
  config.py · project.py            # settings, keychain, <shoot>/.prepro cache, hashing
  media/            # probe, ffmpeg runner + progress, proxies, conform/transcode
  analyze/          # classify, asr, fillers, retakes, prosody, scenes, quality, motion, dupes,
                    # faces, best_moments, music, loudness, audio_issues, geo_time, vision_tags
  knowledge/        # constitution.md, hooks.yaml, structures.yaml, emotions.yaml, memes.yaml, playbooks/*.yaml
  assist/           # soundtrack_modes, music_match, memes, sfx, broll_gaps, looks (LUT presets),
                    # voice_polish, safety, search
  brief/            # CreatorBrief schema, parsers (form, brief.md/.yaml, voice note, notes.yaml, filename tags),
                    # anchor resolution, compliance lint, saved templates
  brain/            # dossier, schemas (Direction/StoryPlan/PolishPlan/CriticReport), passes, router,
    providers/      # base contract, basic_rules, cli_claude_code, cli_codex, anthropic_api, openai_api,
                    # gemini_api, xai_api, openrouter_api, ollama_local
    prompts/        # provider-neutral prompt templates
  timeline/         # model (tracks/items/keyframes/markers/Suggestion), compiler, snapping, reframe,
                    # captions, audio_mix, attention_curve
  lint/             # EditLint rules + autofixes
  export/           # fcp7_xml, otio_out, mlt_xml, phone_pack, subtitles, caption_overlay, render, report
  server/           # FastAPI app, job runner + SSE, range-request media streaming
ui/                 # React review app
desktop/            # Electron main/preload + electron-builder config
assets/             # OFL fonts, procedurally generated SFX starter pack (whoosh/pop/riser/impact)
scripts/            # make_fixtures.py, build_engine.py (PyInstaller)
tests/              # unit/, golden/, e2e/, stubs/ (fake claude/codex executables)
```

---

## 8. Milestones
**Phase 1: MVP (this session builds it, in this order, with tests green at each step)**
- **M0 Scaffold + fixtures.**
  - uv project, CLI skeleton, settings, ffmpeg discovery.
  - `make_fixtures.py` builds a synthetic vlog shoot with known ground truth:
    - TTS speech (Piper/espeak-ng) with planted retakes, fillers and silences
    - B-roll with pans, shake, blur, darkness and duplicates
    - click-track music with known BPM and sections
    - creation-time and GPS metadata
- **M1 Ingest + analyse.** `prepro analyze <folder>` writes `.prepro/analysis/*.json` and a readable summary. It also runs the one-time music-library analysis (BPM, key, energy curve, sections) and audio-problem detection (noise, hum, wind, clipping, echo). Brief files (`brief.md`/`.yaml`, voice note, `notes.yaml`, filename tags) are read into the brief schema.
- **M2 Timeline core with the Basic (no-AI) brain.** Model, compiler, EditLint and ffmpeg preview/final render, plus voice polish, soundtrack modes, rules-based music matching, and the brief's hard rules (enforced by the compiler, checked by the compliance lint). `prepro build <folder> --direction story-vlog --brain basic` gives a full end-to-end loop at zero cost.
- **Early spike, right after M2.** A sample XML/OTIO/MLT package goes to you to import in Premiere, Resolve, Kdenlive and Shotcut, to de-risk exports early.
- **M3 AI brain.**
  - Provider contract, router and the passes: vision tagging, Director (directions + hooks + gaps), Story, Polish, Critic.
  - The Polish pass also produces the music brief, meme/SFX suggestions (catalogue + library only), VO script, B-roll gaps and look suggestions.
  - Brief parser pass (free text → hard rules, preferences, questions) and revise pass (timeline comments → edit ops for that region).
  - Connector build order, changeable to match what you own: Claude Code CLI → Codex CLI → Gemini API (free key) → Anthropic / OpenAI / xAI / OpenRouter APIs → Ollama.
  - Cost meter, caps and `prepro brains --compare`, which produces the "which brain is best" report.
- **M4 Exports.** FCP7 XML (with organised bins), OTIO, MLT, phone pack (incl. no-music version + beat plan), SRT/ASS/overlay, and the HTML editor brief.
- **M5 Review UI.**
  - new-shoot wizard with the optional brief step, and analysis progress
  - clip notes, timeline comments with before/after review, creative-freedom slider, brief checklist, saved brief templates
  - "Brains" settings with detected CLIs and keys, plus per-pass routing
  - direction cards and hook picker
  - player + timeline lanes + suggestion list (accept/reject, with reasons) and knobs
  - music and meme panels with alternatives ("swap track", "try another meme"), retention heat strip, footage search
  - critic scorecard, lint panel and export dialog
- **M6 Desktop app.** Electron + frozen engine + bundled ffmpeg + first-run model download. Linux AppImage/.deb built here; Windows installer via CI.

**Phase 2:**
- Deep-tune the talking head/podcast, gaming and comedy playbooks.
- **Style DNA**: drop in reference videos, measure shot-length distribution, cut density, zoom frequency, caption style (OCR), music/SFX density, B-roll ratio and hook pattern, and turn that into a custom playbook overlay.
- Long → Shorts repurposing; rendered A/B hook variants (e.g. for Instagram trial reels).
- Local CLIP (ONNX) for semantic B-roll search and match cuts; emoji captions.
- External-mic audio sync; automatic shot colour matching; stabilisation; "send to phone" over LAN with a QR code.
- The Phase 2 helpers listed in 1.8 (packaging, stock/GIF search, VO recording + scratch TTS, AI music generation, fingerprint copyright check, privacy blur).

**Phase 3:**
- Pre-shoot planner (idea → hook → script → shot list), with the script then guiding take selection.
- Learning loop from YouTube Analytics retention curves.
- Optional CapCut drafts; hosted accounts; optional cloud processing.

---

## 9. Verification
1. **`uv run pytest`, unit tests on synthetic ground truth:**
   - silence boundaries ±50 ms, BPM ±1, exact retake groups, duplicates found, shake/blur/dark flagged
   - compiler invariants: no cut inside a word, beat-aligned cuts within 1 frame, budgets respected, duration within target
   - every EditLint rule has a failing and a passing fixture
   - soundtrack mode: the speech-heavy fixture gets "bed", the no-speech fixture gets "front"
   - music matching: synthetic tracks with known BPM/energy rank as expected, and every suggested track exists in the library
   - meme suggestions come only from the catalogue or library; voice polish raises the measured signal-to-noise ratio on a noisy fixture
   - brief compliance: a fixture brief with must/never clips, a song bound to the montage, a text card, a meme at a set moment and "no zooms" produces a cut that meets every hard rule
   - an impossible brief (too many must-haves for the length) produces a conflict notice; a voice-note brief is transcribed and parsed; a timeline comment becomes the right edit op
2. **Connectors, at zero usage:**
   - the provider contract is tested against **stub `claude`/`codex` executables** and recorded API responses: valid JSON, invalid JSON → repair, "usage limit reached" → pause, wrong IDs rejected
   - live calls only run with your OK, because they use your plan or key
   - privacy levels: Local-only mode makes no network calls at all; in Text-only mode the sent-data log holds no images, file names or GPS coordinates
3. **Exporters:**
   - FCP7 XML parsed back by OTIO's FCP XML adapter must give the same cut list; OTIO round-trips
   - MLT XML rendered headlessly with `melt` (apt), with duration checked via ffprobe
   - phone pack checked with ffprobe (resolution, CFR, codecs) and ffmpeg `ebur128` (−14 ±1 LUFS)
4. **End to end:** `uv run prepro build fixtures/travel_demo --direction auto --brain basic --export all`. Every output exists and plays, and the report lists every suggestion with its reason.
5. **UI:** a Playwright script (pre-installed Chromium) opens a project, picks a direction, rejects a meme, re-renders and exports. Screenshots are reviewed.
6. **Taste eval:**
   - 3–5 real vlog/travel/lifestyle shoots from you, rated blind on a rubric: hook, story, pacing, no-cringe, "would you post this first cut?"
   - run for the Basic brain and each connector you have, so `prepro brains --compare` shows which one is worth it
7. **Manual checklist (you):** imports into Premiere (Windows), Resolve (Windows + Linux), Kdenlive and Shotcut; phone pack opened in InShot/VN/Edits.

---

## 10. Risks and mitigations
- **Word-timing imprecision:** acoustic snapping + handles.
- **Whisper drops fillers:** unaccounted-speech heuristic + verbatim prompt.
- **FCP7 XML quirks between Premiere and Resolve:** early import spike, a conservative writer, and markers for anything not portable.
- **Phone VFR footage:** CFR conform for proxies and exports.
- **Over-editing:** budgets + EditLint + critic, with "balanced" as the default.
- **AI ID/time hallucination:** IDs only, plus validation and repair.
- **Subscription terms or CLI behaviour changes:**
  - CLI connectors feature-detect flags, and their version is shown in the app
  - other connectors remain available as fallbacks
  - terms get re-checked before public release
- **Quality varies by provider:** the critic, EditLint and the "which brain" report make the differences visible. The Basic brain guarantees a sane floor.
- **Free tiers:** rate limits are handled by queueing. Free-tier data use is disclosed, and thumbnails can be turned off.
- **App size:** no PyTorch in v1; models download on first run.
- **Licensing:**
  - ffmpeg ships as a separate executable (needs a GPL compliance review)
  - OFL fonts; only procedurally generated SFX are bundled
  - user music/memes are the user's responsibility, and the app warns about platform copyright

## 11. What I need from you
- **2–3 real raw shoots** (vlog/travel/lifestyle) with the music/memes/SFX you'd actually use. This is the most important input for tuning quality.
- Your **meme flavour** (global / Indian-Hinglish / Gen-Z) and favourite meme sounds/formats, to seed the meme catalogue.
- For one of those shoots, the **brief you'd naturally write (or say in a voice note)**, so the brief parser is tuned on real instructions.
- **Which subscriptions you have** (Claude Pro/Max, ChatGPT Plus/Pro, Google AI Pro, SuperGrok), so I build and test that connector first. A free Gemini API key is optional and useful for vision tagging. **No paid API key is needed.**
- Your OK before any live AI test call, since it uses your plan.
- Import tests on your Premiere/Resolve/Kdenlive/Shotcut setups and phone apps.
- A GitHub repo, if you want Windows installers built in CI.

## 12. Autonomous execution protocol (you're away; budget ≈ $89)
**Loop per milestone:** Docs/handoff → Build → Fix/Improve → Commit & push → Test → Release → Repeat.
- **Docs/handoff:** `docs/HANDOFF.md` (current state, decisions, next steps), `CHANGELOG.md` and per-phase notes are updated every milestone, so any later session can resume cold.
- **Build → Fix/Improve:**
  - ruff + pyright/mypy and the test suite must be green before every commit
  - self code review of each milestone diff, with fixes applied
- **Commit & push:** small logical commits on a `dev` branch.
- **Release:** fast-forward `main`, tag `vX.Y.0`, write release notes, and build artifacts (wheel/sdist; Linux AppImage once the desktop app exists).
- **Self-review of creative quality**, since you won't check each step:
  - every test output gets a rendered storyboard (one frame per cut, with captions/overlays visible) and a paper edit, which I inspect myself
  - plus metrics: loudness, SNR, beat alignment, lint and critic scores
  - findings and fixes go into `docs/QA.md`
- **Release ladder** (each release usable on its own, so running out of credits mid-way still leaves a working product):

| Version | Contents |
|---|---|
| v0.1 | M0–M2: offline engine end to end |
| v0.2 | M3–M4: AI brain + exports |
| v0.3 | M5: review UI |
| v0.4 | M6: Linux desktop app |
| v0.5+ | Phase 2 features, by value |
| v1.0 | refinement pass |

**Test media (no files from you):**
- **Real video:** Google's public sample-video bucket (Blender open movies, CC-BY, plus real-camera driving/outdoor/people clips), and OpenCV/Intel sample videos (people, faces, walking) via raw GitHub. Test use only; never committed.
- **Real speech + music:** librosa's example data (LibriSpeech readings; Kevin MacLeod tracks, CC-BY: jazz, waltz, blues, lo-fi, drum & bass).
- **Images:** OpenCV samples and scikit-image's bundled photos. **Fonts:** Google Fonts.
- **Synthetic media with exact ground truth:**
  - espeak-ng TTS in English and Hindi/Hinglish, with planted retakes, fillers, silences and punchlines
  - procedural music with known BPM and sections
  - procedural SFX, memes and GIFs
  - ffmpeg B-roll with known pans, shake, blur, darkness and duplicates; a gaming-style screen capture with a facecam box
- **Test case types:**
  - hook variants
  - story vlog, cinematic travel montage, hype/velocity reel, aesthetic/lifestyle
  - talking head/podcast, comedy/meme, gaming-style
  - Hindi/Hinglish speech
  - briefs (strict, conflicting, empty → Auto) and timeline comments
- Media is downloaded by `scripts/fetch_test_media.py` from a manifest (URL, licence, sha256) into a cache outside git.

**Environment limits, reported honestly:**
- **Speech recognition:** huggingface.co is blocked, so Whisper models can't be downloaded here.
  - The Whisper backend is built and unit-tested at the interface.
  - End-to-end tests use a second recogniser that installs from PyPI/apt (e.g. PocketSphinx), scored against the TTS ground truth (word error rate, boundary error).
  - Whisper results will be reported as "not run here", never faked.
- **AI connectors:** live smoke tests only through the `claude` CLI already in this container, with small inputs and a handful of calls. All other connectors are tested with stub executables and recorded responses, and labelled as such.
- **GitHub:** `buildcool/PrePro` is attached, with read and push access confirmed. The repo is empty.
  - `main` gets the initial scaffold commit; day-to-day work goes on `dev` and is pushed regularly.
  - Each release fast-forwards `main`, then gets a tag and a GitHub release.
  - GitHub Actions workflows for the Linux and Windows builds are included.

**Order:**
1. Phase 1 (M0 → M6).
2. Phase 2 by value: long → Shorts repurposing, packaging (thumbnails/titles/chapters), Style DNA, stock/GIF search, VO recording + scratch TTS, privacy blur, the deep genre playbooks.
3. Phase 3 last.

Stop when the credits run out or all phases are done, with `HANDOFF.md` always current.

## Sources
- Durations: [Socialinsider: Reels length](https://socialinsider.io/blog/instagram-reels-length/) · [Klap: Reels 2026](https://klap.app/blog/how-long-should-reels-be) · [Piktochart: Shorts 2026](https://piktochart.com/blog/how-long-youtube-shorts/) · [Bytecap: Shorts research](https://www.bytecap.io/research/best-youtube-shorts-length)
- Hooks/retention: [MrBeast memo (Alexander Jarvis)](https://www.alexanderjarvis.com/memo-how-to-succeed-in-mrbeast-production/) · [Creator Handbook takeaways](https://www.creatorhandbook.net/leaked-document-allegedly-reveals-mrbeasts-secrets-to-youtube-success-the-key-takeaways/) · [vidIQ: Jenny Hoyos](https://vidiq.com/blog/post/how-jenny-hoyos-gets-10m-views-per-youtube-short/) · [Hook-Retain-Reward](https://aivolve.beehiiv.com/p/hook-retain-reward) · [vidIQ: YouTube hooks](https://vidiq.com/blog/post/youtube-intros/) · [Captions.ai: hook layers](https://captions.ai/blog/video-hooks-how-to-write-a-scroll-stopping-opening) · [AIR: retention editing](https://air.io/en/youtube-glossary/what-is-retention-editing)
- Craft: [No Film School: Murch Rule of Six](https://nofilmschool.com/2016/11/6-rules-good-cutting-according-oscar-winning-editor-walter-murch) · [Jonny Elwyn: trailer editing](https://jonnyelwyn.co.uk/film-and-video-editing/inside-professional-trailer-editing/) · [Artlist: Casey Neistat](https://artlist.io/blog/editing-storytelling-techniques-casey-neistat/) · [No Film School: Neistat storytelling](https://nofilmschool.com/2016/08/7-storytelling-techniques-you-can-learn-filmmaker-youtube-star-casey-neistat) · [PremiumBeat: comedy editing](https://www.premiumbeat.com/blog/how-to-edit-comedy-scenes-for-maximum-laughs) · [Insta360: film transitions](https://www.insta360.com/blog/tips/how-to-create-film-transitions.html) · [CapCut: 2026 trends](https://www.capcut.com/help/latest-capcut-editing-trends) · [Soundstripe: podcast clips](https://www.soundstripe.com/blogs/how-to-clip-a-podcast)
- Anti-patterns: [Tasty Edits: amateur red flags](https://www.tastyedits.com/red-flags-of-amateur-video-editors/) · [c-istudios: editing mistakes](https://c-istudios.com/video-editing-mistakes-that-kill-engagement-and-reduce-watch-time/) · [eesel: OpusClip reviews](https://www.eesel.ai/blog/opusclip-reviews) · [Impact: Opus Clip review](https://www.impactplus.com/blog/ai-video-tool-opus-clip-review)
- AI access and terms: [Claude Code legal & compliance](https://code.claude.com/docs/en/legal-and-compliance) · [Claude Code headless (`claude -p`)](https://code.claude.com/docs/en/headless) · [Claude help: Agent SDK with your plan](https://support.claude.com/en/articles/15036540-use-the-agent-sdk-with-your-claude-plan) · [The Register: Claude subs & third-party harnesses](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access) · [OpenAI Codex auth](https://developers.openai.com/codex/auth) · [OpenAI Codex CLI](https://developers.openai.com/codex/cli) · [MindStudio: OpenAI vs Anthropic subscription stance](https://www.mindstudio.ai/blog/openai-codex-anthropic-subscription-change) · [Gemini API free tier (CostBench)](https://www.costbench.com/software/llm-api-providers/google-gemini-api/free-plan/) · [Gemini CLI cheat sheet](https://computingforgeeks.com/gemini-cli-cheat-sheet/)
- Privacy/training: [TechCrunch: Anthropic consumer training choice](https://www.techcrunch.com/2025/08/28/anthropic-users-face-a-new-choice-opt-out-or-share-your-data-for-ai-training) · [MacRumors: Claude opt-out](https://www.macrumors.com/2025/08/28/anthropic-claude-chat-training) · [OpenAI: data controls (ChatGPT & Codex)](https://help.openai.com/en/articles/7730893-data-controls-faq) · [Google: Gemini API terms](https://ai.google.dev/gemini-api/terms_preview) · [Simon Willison on Gemini terms](https://simonwillison.net/2024/Oct/17/gemini-terms-of-service) · [xAI privacy policy](https://x.ai/legal/privacy-policy)
- Tooling: [Eddie AI rough cuts](https://www.heyeddie.ai/features/roughcuts) · [OTIO adopters](https://github.com/PixarAnimationStudios/OpenTimelineIO/wiki/Tools-and-Projects-Using-OpenTimelineIO) · [Premiere OTIO beta](https://community.adobe.com/t5/premiere-pro-beta-discussions/now-in-beta-otio-import-and-export/m-p/14985932) · [roughcut.com: XML to Resolve](https://roughcut.com/blog/multicam-xml-export-premiere-resolve-fcp) · [NixOS wiki: Resolve on Linux](https://wiki.nixos.org/wiki/DaVinci_Resolve) · [pycapcut](https://pypi.org/project/pycapcut/)
