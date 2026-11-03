# QA & taste log

How quality is checked when nobody is watching each step:

1. **Ground truth.** Synthetic shoots (`prepro demo …`) carry `.groundtruth.json`: which lines must be cut
   (greetings, false starts, fillers, retakes), which shots are bad (shaky/blurry/dark/duplicate), action
   peaks, punchlines, music beats/sections. Tests score the engine against it.
2. **Real media.** `prepro testmedia fetch` downloads openly licensed clips/music/speech (faces, people,
   streets, driving, food, podcast, LibriSpeech, Kevin MacLeod…) for robustness tests.
3. **Storyboards.** Every built timeline renders a storyboard PNG (one frame per cut with captions/overlays)
   into `.prepro/qa/`, which is inspected visually.
4. **Metrics.** Loudness (−14 LUFS ±1), speech-to-music ratio, beat alignment error, lint and critic scores.

## Log
(entries added per milestone)
