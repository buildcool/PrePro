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

### v0.9 (photo reels), reviewed as an editor
New fixtures: `photo_dump` (11 phone photos from a day in Goa, two stored sideways, a burst duplicate, a blurry and a
dark photo, a group of three, capture times out of file-name order, a 100 BPM song) and `photo_single` (one portrait,
three lines in a `Text:` brief, a 92 BPM song). Each was built with real faces and with drawn ones (what CI has), then
rendered and reviewed frame by frame.
1. **Both photos with a person were thrown out as "blurry"** (whole-frame sharpness 14, limit 25). A portrait's
   background is soft on purpose, so the whole-frame measure rejects exactly the photos people like most. A photo is
   now judged by its sharpest tile or its face: the portraits score 32, the truly blurred photo 2.
2. **The song started two beats into a bar** (15.6 s instead of the chorus at 14.4 s). The cover's cut fell
   mid-bar. With the kick on beats 1 and 3, low end alone can't tell the bar line from beat 3. Downbeats now also
   follow chord changes. Across the fixture songs, every bar line is right on 11 of 12; the twelfth, a 174 BPM
   drum'n'bass track, is tracked at half time on the snare (a beat-tracking limit, noted in HANDOFF).
3. **Cuts would drift off the beat.** Item lengths were whole multiples of a median beat (80 ms off after 20 beats),
   and each rendered piece was rounded to whole frames on its own. Cuts now sit on the detected beats, and frame
   counts come from the rounded cut points. Every cut is within 50 ms of a true beat.
4. **The loop had a seam.** The closing clip of the cover ended on a different framing than the one the Reel opens
   on. It now carries the cover's own move at the same speed and stops on the cover's first frame, so the replay
   continues the motion. A push-in can't be continued backwards past the full photo, so the cover pulls out.
5. **Rendering crashed on that pull-out.** ffmpeg scaled the picture per frame under a crop window sized for the
   first frame. This was never caught because photo reels had never been rendered. Photo frames are now drawn with
   OpenCV at sub-pixel precision and piped to the encoder. A pan measures -5.73 px a frame, varying by 0.015 px, so
   it glides instead of stepping. 36 full-HD frames take 0.4 s. The pan itself was too brisk (16 % of the frame a
   second) and is capped at about 6 %, like the push-ins.
6. **Loudness: -15.2 LUFS and -0.1 dBTP** on a music-only Reel. The limiter only saw sample peaks, and limiting a
   dense mix cost loudness. A true-peak limiter plus a capped top-up now give -14.3 LUFS and -1.26 dBTP.
7. **The group photo opened the Reel cropped to the middle person.** The other two were cut off at the sides. A
   photo whose faces won't all fit a 9:16 crop is now shown whole. The first fill behind it (a blurred crop of the
   photo) showed smeared shirt-coloured columns. It's now a soft gradient of the photo's own colours, with a print's
   shadow under the photo. A framed photo can't be the cover: the cover must fill the frame.
8. **Words on photos looked like subtitles.** A thick outline, and a line ending on "took the". They have their own
   style now (a soft shadow), with lines broken by measured width that never end on a glue word. Pillow overestimated
   libass's widths by 12 % (libass sizes a font by its line height), so the measure is calibrated by rendering a
   line through ffmpeg.
9. **On a tight close-up, the first line touched the chin.** The e2e test caught it: the slow push-in grows the face
   while the line is up. Text is now placed against the face at both ends of its time on screen, in the larger
   free band (above the head with room for hair, or below the chin), and set up to 24 % smaller when the band is
   short.
10. **One photo + lines:** the POV line (the hook) didn't appear until 2.6 s, later lines drifted off the phrase grid
    (6.2 s against a bar at 5.2 s), and line one was up 3.45 s for 9 words (the cringe guard wants 3.6 s). Now line
    one is on frame one, each next line lands on a beat, and each stays up long enough to read.
11. **CI's drawn faces were invisible to the face detector,** so every face rule would have gone untested in CI. Tiling
    the photo for the detector found "faces" in the blurry market photo, so tiling was rejected. The fixtures draw a
    more face-like person instead (shaded skin, brows, irises, a nose shadow, lips, ears), found at 0.97–1.0
    confidence even at 14 % of the photo's width.
12. The critic scored "genre fit" 6/10 because it didn't know the photo-reel signature. It now checks each part
    (cover first, cuts on the beat, moving stills, text on photo, loop back to the cover); both reels score 10/10,
    and 10/10 on the cringe guard.

Analysis: 0.2 s a photo; the song takes about 18 s (most of it librosa warming up).
13. **Review app** (driven in the built-in browser on the photo dump):
    - Rejecting the cover did nothing: it carried the generic "hook" key, and only one cover was offered. The cover
      is now `cover:<photo>`, with the three best covers on offer. In the app, ✕ on the cover reopened the reel on
      the evening portrait; the old cover went back among the photos in the order taken, every cut still on a beat.
    - Any revision would have broken the reel. The words sat at fixed times (dropping a photo would leave them on the
      wrong picture), and a swapped cover lost its beat-timed length. Photos now hold whole beats that the compiler
      lays on the song's grid, and lines anchor to "photo i". The e2e test drops a photo, brings back the blurry
      one, swaps the cover and stills the motion, and checks the lines and the beat grid after each step.
    - After the swap, the long last-photo hold had moved to a middle photo. The reel's rhythm (cover and last photo
      two counts, the rest one) is now re-derived whenever the set of photos changes.
    - The left-out photos weren't listed, so they couldn't be brought back. Each now says why. Photo motion had no
      decision and no filter chip; it has both now. Photo cards said "0.0 s · 25 fps"; they show the orientation and
      the time taken.

### Lifestyle formats (research, 2026-11-05) — what to build next
Sources are mostly 2026 trend roundups (Buffer, async.com, Epidemic Sound via mean.ceo, gyre.pro), so the claims are
loose; the formats below are the ones they agree on, ranked by how well they fit "your footage in, a finished edit
out":
1. **Done: photo dump / one photo + text + song** (above).
2. **Done (v0.11): day in my life (short):** chronological clips of one day, small time stamps from the capture
   time ("6:42 am"), light music, natural sound kept, ~1–2 s a clip. Its own playbook (`day_in_life`); see
   "v0.11" below.
3. **Done (v0.12): POV / text on video + a song:** your lines on the beat over short clips, the hook line on frame
   one. Its own playbook (`text_reel`); see "v0.12" below.
4. **Silent / aesthetic vlog** (non-verbal Shorts are a named 2026 trend): no talking, foley up (pour, steps, keys),
   soft music, minimal lowercase captions, slow holds.
5. **GRWM / storytime over a routine:** talking (or a voiceover) over getting-ready B-roll. Needs the talk to stay
   whole while the B-roll cuts on its own rhythm.
6. **Before → after reveal** (outfit change, room makeover, "reverse reveal" that opens on the result): a match cut
   on the beat at the moment of change.
Lo-fi / unpolished is also called a 2026 trend, which argues for restraint (few effects), PrePro's default taste.

### v0.8.0 desktop start-up crash (reported by the user, 2026-11-05)
- The installed v0.8.0 app showed "engine exited during start-up": `UnicodeEncodeError: 'charmap' codec can't encode
  character '\u2192'`, from `serve`'s first line, "PrePro 0.8.0 → http://…". Electron reads the engine's output
  through a pipe, and Windows encodes piped output in the ANSI code page (cp1252). It's a run-time error that no check
  caught, because every place the engine ran in tests was UTF-8: pytest's capture, CI shells, terminals. The desktop
  CI only ran `prepro-engine version` and `doctor` (no arrow in either), never `ui`, the command the app starts.
- Reproduced with `PYTHONIOENCODING=cp1252` and a piped stdout; `prepro --help` failed the same way. Fixed in
  `cli._safe_output` (UTF-8 for pipes/files, `errors="replace"` for consoles), and the app also sets `PYTHONUTF8=1`.
- Guards: `tests/unit/test_engine_startup.py` starts `ui`, `version` and `--help` in a cp1252 pipe, and the desktop
  workflow starts the frozen engine's `ui` with redirected output and fails unless the server answers.
- Same round: CI on Ubuntu caught `encode_frames` closing ffmpeg's stdin before `communicate()`, which flushes it on
  Linux ("flush of closed file"); Windows doesn't flush, so the local runs had passed.

### App updates (desktop), checked in the built-in browser
- The panel was driven with a stand-in desktop bridge reporting "v0.9.1 is out". Download showed a progress bar and
  the top button followed it ("Downloading v0.9.1… 42%"); a finished download turned it into "Restart to update";
  Automatic was saved; the restart called the installer. In a plain browser there is no Updates button.
- Release notes first showed in a monospace font (looked like a log); they're normal text now.
- `tests/desktop/updater_check.js` (Electron stubbed) checks version order ("0.10.0" > "0.9.0", not a string
  compare), the HTML-to-text notes, the saved mode, that unknown modes are ignored, and that a build that can't
  install itself opens the release page. The real download and install can only be tested once a release carries
  `latest.yml`, which is why desktop.yml now fails without it.

### v0.10 (autonomous pre-editor, AI accounts, settings, themes), checked in the built-in browser
Asked by the user: why no AI options, where BYOK went, a real settings window with connected accounts, light/dark,
top-class UI, progress that doesn't look frozen, and the vision: an autonomous pre-editor (about 90 % done).
1. **No AI options.** This PC had no Claude Code, Codex or Gemini CLI, and no keys, so only the rules engine was
   listed. The Claude desktop app doesn't put a `claude` command on PATH. Worse, every task's routing defaulted to
   "basic", so even a connected AI did nothing until seven dropdowns were changed. Now there is one AI editor, routing
   defaults to "auto" (old all-"basic" settings migrate), and CLIs are also found in their installers' folders.
2. **BYOK was never in the app**, only the CLI (`prepro brains key`). The first Brains screen already pointed there;
   nothing was removed. Keys are now added in Settings and kept in the keychain. Checked in the app with an obviously
   fake test key: it was saved, shown as "•••• abcd", became the AI editor, never appeared in the page, and was
   removed again. The test server used keyring's fail backend, so the test key went to the isolated test config
   folder, never the real Windows Credential Manager.
3. Screenshot review of Settings: the account cards collapsed into a one-word-wide column, with a stray "R" tile
   over the title. The tiles used `.mark`, which the review timeline already uses for absolutely-positioned dots.
   Renamed to `.amark`.
4. The sidebar chip still said "Rules engine" after a key made OpenAI the editor. It only refreshed on page changes;
   Settings now announces AI changes.
5. **Progress.** Watching a run: the bar jumped from 58 % back to 2 % (each analysis stage restarted its own scale).
   A song's analysis then sat at 2 % for about 18 s (no reports inside a file), and the detail showed a raw path
   ("music/golden_hour_100.wav"). Now: stages share one forward-only scale; the song analysis, transcription, shots,
   the edit and the render report their steps ("Finding the beat in …", "Finding the chorus and the drop in …",
   "Cutting piece 3 of 9"); paths read "Looking at IMG_0004.jpg"; and a stalled bar gets a sweeping glow plus
   "Still working".
6. Deleting `.prepro/analysis` to test a slow run crashed the next analysis with FileNotFoundError. A user cleaning up
   space would hit the same thing. The folder is now recreated; a regression test covers it.
7. **End to end on a fresh folder:** pasting the path and pressing Enter opened the shoot and started "Making your
   cut" at once. The stepper showed "Watching and listening" with "Finding the beat in warm_acoustic_92.wav". About
   40 s later Review opened by itself on the 13 s photo reel. The shoot folder had the Premiere/Resolve XML, OTIO and
   the editor's report. The "Not watched yet" hint showed during the watching; it now hides while a task runs.
8. Light theme, Settings → General → Light: tokens switch (selected nav uses the light `--panel-3`), and "Match my
   computer" follows the OS. One screenshot caught a mid-transition frame; the live state was correct.
9. **A real bug from the v0.8 two-shot work.** The full test run with real-media fixtures failed the retake check:
   "Okay so the best part, the best part is the lassi." wasn't flagged as a retake of the next line. The transcript
   was identical to the drawn-face run, where it passes. The real face video's head moves between two spots
   (x ≈ 0.31 and 0.48), never two faces in one frame, so it was read as two seats. The two attempts got two
   speakers and were treated as a reply. Any vlogger who leans or walks would hit this. Two seats now need two faces
   on screen together in ≥ 15 % of the sampled frames (ANALYSIS_VERSION 13). It went unnoticed since v0.8 because
   the real-media round of the verification covers only the craft, gaming, speaker and photo files. test_m1 now
   runs in that round too.

### v0.10.1 (brand logos), checked in the built-in browser
1. **Reported by the user:** the account cards showed letter tiles ("C", "G", "G") instead of the Claude, ChatGPT
   and Gemini logos, so signing in didn't look like their sign-in. The cards, the "Who edits" picker and the sidebar
   chip now show the real logos (LobeHub lobe-icons, MIT). Simple Icons was tried first; it has no OpenAI or xAI logo.
2. Checked at 1280 px in dark and light: every account shows its logo. The one-colour marks (OpenAI, Anthropic, xAI,
   OpenRouter) are white on dark and black on light; Claude stays orange; Gemini keeps its gradient. Making Claude
   the AI editor put its logo in the sidebar chip.
3. Gemini's logo can be on screen four times (plan, key, picker, sidebar), and its gradients are found by id. With
   shared ids, a hidden first copy can blank the others in some browsers. That wasn't seen here; each copy now gets
   its own ids as a precaution.
4. While looking, the Claude card read "Through Claude Code 2.1.318 (Claude Code)", and the version vanished after any
   click (the quick refresh skipped it). The version is now just the number and stays put; a unit test covers both.
5. Narrow window (820 px, collapsed sidebar): the new 30 px logo tile touched the chip's left edge and the status dot
   stuck out 1 px on the right; the Settings button was squeezed to 18 px beside the theme button. The chip is now
   the centred logo with the dot as a corner badge, and Settings and the theme button stack. Wide layout measured
   unchanged.

### v0.11 (day in my life), reviewed as an editor
The `day_in_life` fixture is one Saturday off a phone, 6:42 am to 11:05 pm (+05:30): fifteen vertical clips with
the iPhone local-time tag, some with the sounds of the day, a near-duplicate sunset, a shaky clip, one clip from the
evening before, a warm 96 BPM song and a hype track. Findings from watching the first cuts, all fixed:
1. **The hype track was picked.** A front-mode music brief asks for 90 + 50 × pace BPM (117–162 here), so the 144 BPM
   hype track fitted and the 96 BPM song didn't. A playbook can now set its own range (a day: 80–125 BPM), and its
   mood list starts with happy and warm.
2. **The 11:05 pm bedroom clip was dropped as a "near-duplicate" of the 6:42 am one.** It's the same room 16 hours
   later: the night, the bookend of the day. Look-alike shots are now retakes only within half an hour (a cheap
   context-stage pass, so cached analyses don't need re-analysing).
3. **The song looped mid-cut** (a 22 s track under a 29 s cut). A day's song now starts where the whole cut fits
   (here the verse, building into the chorus), so it plays through and fades out at the end.
4. **Moments held 2.5 s.** Every synthetic pan or push-in has an "action peak", so the "hold action longer" rule
   applied to almost all of them. Now it's an even groove: the same number of beats for every moment (~1.5–1.9 s),
   with only the day's first and last moments held twice as long.
5. **Three good moments were cut, the beach jump among them.** The length was estimated at 1.6 s a moment, but at
   96 BPM a moment is 3 beats (1.88 s), so the day overflowed and the selection dropped the best clip of the
   evening. The length now comes from the song's actual beat: every usable moment of a normal day is in.
6. **No stamp on the last moment.** "11:05 pm" fell within 3 s of the 9:40 pm stamp and was skipped. The first and
   last moments are now always stamped, and the stamps in between keep 3 s clear of both.
7. **"Music only 4 dB under the voice"** on a cut with no voice. The dialogue stem carries the clips' natural sound
   too; the check now counts only real talking.
8. While looking: on the fixture's vertical clips, fast pans read as static and a shaky beach clip as steady. The
   fixture's pans move ~6× faster than its horizontal ones relative to the frame, and its smooth sky and sand give
   optical flow nothing to hold on to. A textured scene for the shaky clip is detected; real-footage behaviour still
   needs a check on real vertical clips.
9. Frames checked in the render (540×960 preview): "6:42 am" small at the top centre, "a day in my life" in clean
   lowercase in the middle, and the day closing on "11:05 pm" in the same room. Loudness −14.4 LUFS, true peak
   −1.3 dBTP; the critic scores pacing and genre fit 10.
10. Found on the way: with an AI editor connected, photo reels (and now days) were sent to the AI story pass, which
    reorders "for causality, not shooting order" and replaces the song cue, so cuts left the beat grid. Beat-cut
    formats now keep the rules layout; a stub-AI test covers both.

### v0.12 (your words on video), reviewed as an editor
The aesthetic cooking shoot (six vertical clips, a calm 76 BPM song and a hype track) with a brief of four lines
("pov: you finally learned to cook" …):
1. The format is chosen from the brief's lines (it's a brief-driven direction, so `guess_genres` doesn't see it):
   first at 0.97, with the footage's own genres after it; a day keeps its own format first, photos their photo reel.
2. Every line arrives with a cut on the beat (76 BPM: a clip holds 3–4 beats), word for word, one at a time, centred
   (no faces here). The last line ran over two clips (3 + 2 beats, 3.9 s), the cut changing under it on the beat.
   Frames checked: balanced line breaks ("pov: you finally / learned to cook"), readable even over the busy plate.
3. **The critic said one cut was off the beat.** It was the cut at 11.05 s, past the last beat the analysis heard
   (the song's quiet outro). The compiler carries the grid on at the song's tempo, so the cut was on the beat. The
   critic now carries the grid on the same way. A reel's song also now has to cover the whole reel when it starts,
   as a day's does.
4. The planned length ignored rounding to whole beats (10.9 s planned, 12.6 s cut). It is now measured in the song's
   beats.
5. Open: the rules engine can't tell which clip fits which line ("pov: you finally learned to cook" opened on the
   room, not the food), because that needs to know what's in the shot. An AI editor could match lines to clips
   without touching the beat grid. Not done yet: beat-cut formats keep the rules layout.
6. **Windows CI failed where this PC passed.** The log needs a GitHub sign-in, so failures now also go out as public
   annotations (tests/conftest.py), with each job's ffmpeg version. Windows CI installs Chocolatey's newest ffmpeg
   (9.0.2; this PC has 8.0, Ubuntu 6.1). ffmpeg 9 writes no UTC `creation_time` next to an iPhone-style local
   creation date, and the retake check read only `creation_time`. So the 9:45 am and 11:05 pm room clips looked
   untimed, stayed grouped as retakes of the 6:42 am one, and were dropped. Retakes, "bring it back" and the footage
   list's "taken" time now read the same local clock as everything else; a unit test covers a clip with only its
   local time.

### v0.12.1 (Gemini via Antigravity, who's signed in), reported by the user
1. **Gemini sign-in failed** in the terminal PrePro opened: "This client is no longer supported for Gemini Code Assist
   for individuals … migrate to the Antigravity suite". Google stopped Gemini CLI for personal accounts (free, AI Pro,
   Ultra) on 18 June 2026. Gemini CLI now serves only paid API keys and Code Assist Standard/Enterprise. Google's
   replacement is the Antigravity CLI. Its headless mode as documented:
   - `agy --input-format stream-json --output-format stream-json`, with one `{"event":"user",…}` line on stdin;
   - `--json-schema` for the answer's shape, read from the `result` event's `structured_output`;
   - an unsigned run fails with "authentication required" instead of hanging.
   Install: `irm https://antigravity.google/cli/install.ps1 | iex`, which puts `agy.exe` in `%LOCALAPPDATA%\agy\bin`.
   Google documents no way to pass images, so the connector is text-only (`sees_images = False`) and the vision
   pass skips it. Checked against a stub that follows the documented format. **Not yet run against a real signed-in
   `agy`**: that needs a Google sign-in on this PC.
2. Saved settings migrate (`gemini-plan`: `gemini_cli` → `antigravity_cli`, the old model name dropped because
   Antigravity rejects unknown ones), and the old CLI's error leaves the card (test results now name their tool).
3. **"Logged in as Name" (user's request).** From each CLI's own status command, never a token file:
   - Claude Code's `claude auth status --json` gives the email, the org and the plan. Checked here with the real
     login: "Signed in as <email> · Claude Pro". This account has no "Name's Organization", so no display name.
   - `codex login status` only says "Logged in using ChatGPT".
   - `agy auth status` is undocumented, so PrePro only asks it when `agy --help` lists `auth`, with an 8 s cap.
4. **Failing providers not on top (user's request).** Checked in the preview with Claude's last test marked failed:
   - the "Who edits" picker kept only the rules engine;
   - the plan cards went ChatGPT, Gemini, Claude;
   - with Claude as the current editor, it stayed in the picker, selected, reading "Not working — fix it below" in
     red, and the sidebar dot turned red.
