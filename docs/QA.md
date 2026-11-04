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
