# QA & taste log

How quality is checked when nobody is watching each step:

1. **Ground truth.** Synthetic shoots (`prepro demo …`) carry `.groundtruth.json`: which lines must be cut
   (greetings, false starts, fillers, retakes), which shots are bad (shaky/blurry/dark/duplicate), action
   peaks, punchlines, music beats/sections. Tests score the engine against it.
2. **Real media.** `prepro testmedia fetch` downloads openly licensed clips/music/speech (faces, people,
   streets, driving, food, podcast, LibriSpeech, Kevin MacLeod…) used in the shoots and robustness tests.
3. **Storyboards.** Every render writes `.prepro/qa/<timeline>_storyboard.jpg` (one frame per cut, captions
   and overlays visible) which is reviewed visually.
4. **Metrics.** Loudness (−14 LUFS ±1), true peak ≤ −1 dBTP, speech-to-music ratio, lint and critic scores.

## Log

### v0.1 (M2) — travel vlog with brief (30 s reel)
Storyboard review rounds, as an editor would give notes:
1. *Wrong B-roll on the hook* (Jaipur food over the Goa line, face hidden) → overlays now same-place only
   and never in the first 3 s of the hook.
2. *Slow-mo crop missed the action* (9:16 centre crop) → subject tracks (faces or moving subject) +
   operator-style reframing (hold steady, ease to re-centre near the edge).
3. *CTA card over the face, caption repeating the same words* → CTA in the lower third; duplicate captions
   dropped while a card says the same thing.
4. *Whip pan into a talking head* → whips only between B-roll shots.
5. *Captions too small and broken mid-phrase* ("YOU EXACTLY HOW") → bold word-pop captions on vertical talking
   formats; phrase-aware chunking (no ending on "the/to/my", break before "how/where/because", no orphans).
6. *Music under talking although the brief said no* → envelope rebuilt as a sampled function (minimum wins);
   compliance now reads the envelope.
7. *Hang* in music layout when < 1 s of a section remained → bounded loop.
Result: brief 100 % met, critic hook 10 / clarity 10 / pacing 9.4 / sound 10 / restraint 10, −14.2 LUFS,
−1.1 dBTP.

### v0.2 (M3) — live AI editor (Claude Code on the user's plan, privacy "text")
4 calls (director, story, polish, critic) · 174 s · ≈ $1.55 equivalent billed to the plan · no warnings.
- Directions were sharper than the rules engine's (named "₹5,000 for 3 Days: Goa → Jaipur Budget Breakdown",
  a teaser built on the "most expensive hotel" part-2 promise) and coverage gaps were genuinely useful
  ("show a UPI payment screen to prove the ₹5,000 claim", "transport shots to motivate Goa → Jaipur").
- Story was written as but/therefore beats; polish added "Kachori = ₹20" + ding, punch-in on "Twenty!".
- The AI critic was harder than the rules critic (hook 6.5, story 5.0) and right:
  1. the hook's payload ("₹5,000") was only spoken at 2.6 s → **hook tightening**: a long hook line now enters
     late at the clause that carries the numbers/claim;
  2. "Let me show you how I did it" was followed by B-roll without costs (broken promise) → noted for the
     revise pass (story re-ordering is not auto-applied yet);
  3. ding + impact 1.3 s apart → critic fixes can now target `type:anchor` effects and are applied.

### v0.2 (M4): exports, read back by independent tools
- **FCP7 XML → OTIO `fcp_xml` adapter:** 10/10 V1 clips with the same cut points, 9/9 markers, 31.83 s vs 31.84 s.
  - Bins by day · place come through: "B-roll · Day 1 · Calangute" and "B-roll · Day 2 · Jaipur".
- **OTIO round-trip:** 31.87 s (2 frames of transition overlap).
- **`melt` rendered the Shotcut file 6.4 s too long.** Two bugs:
  1. Slow-mo entries were counted in source frames, so V1 came out 51 frames short of A1. Speed changes now use
     MLT `timewarp` producers, so all tracks are 955 frames.
  2. The `melt` CLI ignored the file's `<profile>` and rendered at 25 fps: 955 frames became 38.2 s. Shotcut reads
     the profile; tests pass `-profile`.
- **Phone pack came out H.264 4:4:4**, from the overlay/ASS pass. Phones and Instagram need 4:2:0. All outputs
  are now `-pix_fmt yuv420p`.
- **Editor brief, read as the person receiving it:**
  1. "Missing material: a shot of spent / only / five / thousand" was keyword soup. It is now an editor's request
     from a concept map: "close-up of the food being served … show the price too", with place-aware search terms.
  2. Music sections that are silent by the brief still showed search terms. Those are hidden now.
  3. Decisions were not in time order, and empty tables were blank. Both fixed.
- **Re-ingest bug.** After an export into `<shoot>/PrePro_exports/`, the next build analysed our own rendered MP4s
  and SFX as new footage, and a phone-pack file became the hook. The scanner now ignores `PrePro_exports/` (and
  OS clutter folders). There is a regression test.

### v0.3 (M5): review app, driven in Chromium and reviewed from screenshots
1. **Thumbnails missing at random.** Concurrent requests built `Project()` at the same time, deleted each other's
   `.write-test` probe and silently fell back to a different cache folder. Fixed: unique probe per thread,
   resolved once per process, plus a regression test. The project registry also moved to memory with atomic
   writes.
2. **The voice lane was blank.** Caption text is a model property and is not serialised. The UI now builds it
   from the words.
3. **Hooks read like debug output** ("peak moment: static shot, quality 1.0"). They are now plain words with
   a thumbnail: "open on the action at Calangute: a steady frame (C06 at 0.2 s, 60 fps so it can go real
   slow-mo) — movement in frame 1 stops the scroll". Genre reasons were rewritten too: "mostly calm shots in
   the B-roll — a hype cut would be a stretch".
4. **Decisions were listed by type.** They are now in timeline order, with what was left out at the end.
   Audio assets get a glyph instead of a black box. Ruler ticks no longer collide at phone width. Hook
   quotes are clipped at a word boundary, so no more "for thre".
5. **Hook swap lost material.** "Another hook" dropped the promise line and ping-ponged between two options.
   Now the old hook line stays in as setup, the latest choice wins, and options rotate through all hooks and
   back to the original.
6. **"Keep this line" on a lone "uh" produced nothing.** Lines brought back by the creator are now kept as
   spoken.

### v0.4 (M6 + Shorts): desktop app and Long → Shorts
- **Frozen engine, run over its API** (analyse → directions → build + render → every export): 93 s, brief 100 %
  met.
- **Kdenlive was silently missing in the frozen app.** OTIO loads plugins from `.py` paths. Fixed, the failure is
  now reported, and the Kdenlive profile now matches vertical cuts.
- **Size.** 991 MB → 812 MB (removed the duplicate OpenCV pulled in by unused scenedetect) → 708 MB (PyAV stub).
- **Packaged AppImage.** Extracted and launched under Xvfb: engine 0.4.0 started, the bridge was present and no
  Node.js reached the page.
- **Electron + frozen engine.** The page is local-only, a shoot opens, and quitting stops the engine.
- **ASR fallback without sidecars (frozen).** PocketSphinx produced a rough transcript of the TTS podcast
  ("…ten thousand dollars on like there's a tunnel i bought a fancy…"). Usable for segmentation; Whisper will
  be far better on real installs.
- **Shorts finder on the planted podcast** (3 gold moments between rambling, a greeting and "like I said"
  asides): it picked exactly gold2, gold1 and gold3 (IoU ≈ 1.0). Every pick opens on its own claim or question and
  ends on its lesson.

### v0.5 (Phase 2): packaging and Style DNA
- **Titles, first pass, read as a creator:**
  - "000 for 3 full days": the clause split broke "5,000"
  - "(watch till the end)": clickbait, and it produced garbled titles
  - "3 Editing Mistakes That Are Killing": cut mid-phrase

  Now: number-safe clause splits, natural rewrites ("The real reason…", "How I lost $10,000…", "Stop making these
  3 editing mistakes"), journey titles, and no clickbait suffixes.
- **Thumbnail text** ended on "your?!" and turned "Why do some videos get…" into nothing. Now it is centred on the
  number ("1M views phone camera?", "$10,000 first channel") and never ends on a function word. "A million"
  became 1M.
- **Thumbnails** were three near-identical faces. Now there is one of each kind (face / action / scenery), and the
  mock-ups were checked visually: bold Anton text, white and yellow with an outline, face kept clear.
- **Style DNA text detector, first version:** 37 % recall on a 100 %-captioned reference, because short words
  slipped through. The morphological text-region detector reads 100 % there, 0 % on raw clips, 61 % on our own
  captioned travel render, and 8 % (one frame) false positives on a scenery montage.
- **CI had never run the tests** (an import-path problem since M0). Fixed; Linux, Windows and UI are green.
- **Real footage end to end** (new realmedia test: 3 Intel sample clips + a face clip under JFK's speech + 2 music
  tracks), reviewed from storyboards:
  1. The "cinematic film" came out 3.3 s long. A loop bug skipped the reuse pass, and each long clip counted as
     one moment.
  2. After fixing that, the film cut to empty frames (bare conveyor belt, empty parking lot) and repeated one
     slow-mo moment 5×.
  3. After activity-aware moments it was 52 s / 43 cuts between the same 3 angles: monotonous.
  4. Final: 14 s, 13 cuts, every moment with a subject, slow-mo on the moving fruit, and a "film more angles"
     gap.
  - Also found: "3082 day(s)" from dates in the sample clips' metadata. Fixed.
- **CI caught a Style DNA miss local runs couldn't.** CI has no real test media, so its talking-head fixture uses
  the drawn presenter. The caption sat on the presenter's dark shirt, and the text-region detector merged them into
  one block that was too tall: 0 % text. An outlined-text detector (bright letters tightly outlined in black) now
  reads 100 % there, 0 % on raw clips, and has the same false-positive rate on scenery. There is a unit regression
  test.
