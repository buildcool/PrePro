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

### v0.6 (Editor's Craft v2): reviewed as an editor, genre by genre
- **Talking heads.** 8 jump cuts on the same framing (the stitched look). The polish pass did add reframes, but the
  over-stimulation lint counted them as zoom effects and stripped them. After that, the alternation followed a
  parity counter, not the framing actually on screen, so it went 100 % → 100 % after contiguous lines. Fixed both.
  All genres now score 10/10 `no_cringe`, except a brief that forbids zooms.
- **Comedy.**
  1. Comedy was never offered as a direction (genre detection had no comedy rule).
  2. "first finish your homework" counted as a punchline (the "numbers" tag).
  3. The hold after one line and the beat before the next both claimed the same pause, so it played twice.
  4. Storyboard review found the opening text hook was the punchline ("MRBEAST ALSO NEVER FAILED MATHS 3?!").
  5. The perfect "emotional damage" meme in the folder was unused.

  All fixed. Now: premise text, beats before punchlines, the reaction meme after the roast, and the matching meme
  after the button.
- **A Hindi vlog read as comedy** after the comedy rule landed (memes plus short Hinglish lines). Comedy now requires
  dialogue-led footage (B-roll under 35 %).
- **Montages.**
  - With few clips, two moments of the same angle could sit back to back. The flow order now penalises that.
  - Vertical montages end on the opening image.
- **Re-hook text**, first version: "Every viral video studied had", which was clipped and too short to read (the
  cringe guard caught it). It is now number-centred ("3 parts") and on screen long enough to read.

### v0.7 (gaming pack)
- **Impact detection.** Bass under 250 Hz fired on every voiced syllable, because voices have their fundamental
  there. Measured: explosions carry ~70 % of their energy under 60 Hz, speech onsets ~0 %. Sub-bass is now the boom
  test. Breathy consonants looked noise-like, so noise-like impacts must be ≥ 15 dB and not at a word start. Result:
  3/3 planted explosions, 0 false hits on talking, podcast and comedy clips.
- **Gaming storyboard review:**
  1. The victory payoff was dropped, because the target came from speech length.
  2. The cold open played at 1.5× and silent: the new dull-stretch fix thought gameplay was dull and sped it up.
  3. The callout used the first reaction in the window ("OH MY GOD,") instead of the best ("DOUBLE KILL!").
  4. "REPLAY" was squeezed at the very end.

  All fixed. The plays set the target, the last play is always kept, speed-ups are for wordless B-roll only, and
  moving content is never a dead zone.

### v0.7 on Windows: the first full run on a Windows PC
Machine: Windows 11, i9-14900HX, 16 GB, RTX 4070 (driver only, no CUDA toolkit), Intel UHD. Python 3.12 (uv),
ffmpeg 8.0, espeak-ng 1.52, Shotcut 26.9 for `melt`. Windows CI has no espeak-ng, so before this run nearly every
engine test had been skipped on Windows, not passed.
- **Results.** Unit: M0 8, M1 11, M3 8, packaging 3, speech models 6. End to end: M2 11 (with the render), M4 10
  (with `melt`), M5 revise 11, M5 server 3, packaging 1, Shorts 2, Style DNA 2, Craft 8, Gaming 3. Craft and Gaming
  were also run on shoots built with the real faces. Real footage passed with both PocketSphinx and Whisper.
- **Windows-only bugs found:**
  1. pocketsphinx was compiled at install (no cp312 wheel), by MinGW, and couldn't load: `DLL load failed`.
     `prepro doctor` called it "not installed". Every clip without subtitles got an empty transcript, with no warning.
  2. Whisper picked the GPU because the RTX 4070 was visible, but cuBLAS isn't installed. It would have failed and
     silently dropped to PocketSphinx.
  3. Through npm's `claude.cmd`, cmd.exe broke the JSON schema argument (`json.loads` failed in the CLI). Pipes
     used cp1252, so ₹/Hindi crashed, and CRLF reached the CLI.
  4. The Hindi fixture handed Devanagari to espeak-ng as an argument. It arrived as "????": 0.3 s of noise instead
     of 2.5 s of speech.
  5. Test-only: extensionless stub scripts, `read_text()` in cp1252, `/D:/…` paths from `file://` URLs.
- **Speech on real footage (JFK inaugural, 11 s; `scripts/check_asr.py`), word error rate:**
  - Whisper small, on the CPU: 0.0 %, 9.8 s including loading the model.
  - PocketSphinx: 50.0 % ("ask not what your country…" came out as "and not like you on the train").

  Whisper is not optional for quality: the rough recogniser is only a fallback for timing.
- **Release pipeline.** The v0.6.0 release run had failed on Linux (the johnvansickle.com download), so v0.6.0 has
  no AppImage/.deb. Nobody had noticed because the job logs need admin rights; the public API only showed
  "failure". The build now retries and falls back to BtbN's static build.

### v0.8 (GPU encoding + podcast two-shots), reviewed as an editor
- **GPU encoding, measured instead of assumed.** "Always use the GPU" would have been wrong here:
  - On a 540p preview of a 32 s cut, the GPU encoders were slower than x264 (NVENC 12.3 s, Quick Sync 17.1 s, CPU
    10.7 s), because a preview is many short pieces and starting a GPU encoder costs more than encoding a small piece.
  - NVENC at x264's numbers made files 3.5× bigger. Matching by SSIM gives NVENC crf+6 and Quick Sync crf+1.
  - A clean test pattern made x264 look fastest even at 1080p (it compresses trivially). With sensor-like grain,
    x264 needed 13.8 s for 8 s of 1080p, Quick Sync 3.2 s and NVENC 1.2 s.
  - So "auto" times a grainy, render-like encode once per PC and picks a GPU only when it is ≥ 15 % faster. Here it
    chose the CPU for previews (10.8 s) and NVENC for 1080p (18.1 s, against 21.8 s on the CPU). GPU renders match
    the CPU's picture: SSIM 0.993 (NVENC) and 0.992 (Quick Sync).
  - A first benchmark that ran next to a background test had blamed x264 2× too much; only quiet-machine numbers
    are kept.
- **Podcast two-shot (new `podcast_duo` fixture: two drawn people, each mouth driven only by that person's voice):**
  1. No seats were found at first. The face detector saw the darker-skinned guest in far fewer frames than the
     host, so the 40 % presence rule dropped them and the shot looked like one person. Seats now use
     lower-confidence detections (0.35) seen in ≥ 25 % of frames at a steady position: 2 seats, the guest at 87 %.
  2. Speaker per line: 11/11 right, including a 0.4 s "Right." and a 1 s "Eleven times!".
  3. The first cut was edited like a monologue. The guest's best line became the hook, then the host's "Wait, you
     almost did not upload it?" played after it, answering a line that had been cut. A viewer hears a question about
     something they never heard. Conversations are now one stretch in the order said, never opening on a reply.
  4. The setup line was still missing. "…it started with one video I almost did not upload." and the host's echo
     had been grouped as retakes of each other, so the earlier one was cut. Retakes by different speakers are
     replies now.
  5. "Welcome back. Today I have a creator who went from zero to a million…" was cut whole as a greeting. The
     greeting sentence is its own line now, and the rest opens the clip.
  6. The minimum hold kept the host on screen for the guest's "Right.", although the guest kept talking, so the cut
     came half a second late. Holds are measured per turn now. "Eleven times!" (1 s) became a reaction shot, which
     is how podcast editors use short exclamations.
  7. Storyboard: captions hopped above the head and below the chin from cut to cut. They were placed against the
     biggest face in the source (often the person off screen), ignoring the crop and punch-ins, from a face list
     cut off at 24 entries. Now they use the face on screen and one position: 40/40 captions under the chin,
     none over a mouth.

  Result: a 33 s Short in conversation order, always framing the speaker, 10/10 on the cringe guard.
- **Review app, driven in the built-in browser** (Footage → Review on the two-shot):
  - The decisions list reads well, and the "framing" chip filters the 8 speaker cuts.
  - The on-screen hook said **"Started with 1 video almost did?!"**. It was cut at 6 words mid-phrase, the "not"
    that carried the meaning was lost, and it teased the guest's line while the cut opens on the host's. Phrases are
    now picked whole (never ending on "did/with/every", never cut before a "not"); the result is "Zero to 1M
    subscribers in 1 year?!", with a unit test of garbled cases.
  - The longer hook then failed the cringe guard's reading-time check (7 words in 2.6 s). The hook's time on screen
    now follows its length.
- **Gaming Shorts (stacked webcam), reviewed frame by frame** — the storyboard takes one frame per shot and missed the
  important moments, so frames were also grabbed at the reaction, the replay and the payoff:
  1. Facecam detection found nothing at first: at 960 px the drawn webcam face scored 0.32–0.45, because the whole
     frame is squeezed to 300×300 for the detector. Corners are now searched one at a time.
  2. The webcam's inner edge came out 5 % too far in: edges inside the webcam picture (shoulders, the room) beat the
     border. The border is the line with the longest unbroken run, and it is found in colour, because in the drawn
     test the blue-grey webcam and the green game had the same brightness. Within 3 px on both test streams.
  3. "DOUBLE KILL" was on screen three times at once (the game's banner, our hook text, the caption), and the hook
     text ended on "LET'S". The duplicate is gone, and reactions are shown whole.
  4. At the big reaction, the callout "DOUBLE KILL!" was drawn over the caption with the same words:
     "DCDOUBLE KILL!LL!". This had been there since v0.7 and was missed because the storyboard never sampled that
     moment. The callout now replaces the caption.
  5. The death merged into the victory window and its meme had nowhere to go. A death and a win are separate beats
     now: death → facepalm GIF → comeback. The GIF then failed to render (`-loop 1` on a GIF), which no test had
     ever rendered before.
- **Phone pack on the GPU** failed the constant-frame-rate check: 30.0006 fps. The NVENC pieces were 1 timestamp tick
  short each (3.233008 s for 97 frames), and the stream-copy join of the clean version carried that over. GPU pieces
  are joined with one more GPU encode now.
