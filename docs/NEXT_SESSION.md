# Prompt for the next session

Paste this into a new Claude Code session started in the cloned PrePro folder.

```text
You're continuing work on PrePro, my desktop pre-edit engine for Instagram and YouTube creators
(github.com/buildcool/PrePro). I'm on a Windows PC now. Work on the `dev` branch.

Read docs/HANDOFF.md first ("Current state" and "Resume on your own PC"), then CHANGELOG.md, docs/QA.md and
docs/PLAN.md.

Where things stand:
- v0.6.0 is released.
- The gaming pack is committed on `dev` but not released; the version is still 0.6.0.
- Since the gaming changes, tests/e2e/test_p3_craft.py and tests/e2e/test_realmedia.py have not been re-run.

Do these first, in order:
1. Set up this PC for development (HANDOFF lists the commands): a Python 3.12 venv with
   `pip install -e ".[asr,ai,geo,export,dev]"`, plus ffmpeg and espeak-ng on PATH. Run `prepro doctor` to check.
   Without espeak-ng the speech-based tests are skipped, not passed, so check they really ran. Windows CI has no
   espeak-ng, so these tests have never run on Windows: a failure that only happens here is a real Windows bug
   to fix.
2. Run the tests one file per command (all at once can run out of memory) and fix anything that fails.
3. Run `prepro testmedia fetch`, then the real-footage test. This PC can reach Hugging Face, which the cloud
   session couldn't, so also download a Whisper model and check transcription on real footage. Report Whisper
   results honestly; never fake them.
4. Release v0.7.0 with the steps in HANDOFF.

Then carry on with "Next steps" in HANDOFF, releasing each milestone.

How I want you to work:
- Think like the world's best professional video editor. The output must never feel like random stitching that
  causes ghinn or chhidh (cringe, irritation). Review your own output, including the storyboards in
  <shoot>/.prepro/qa/, the paper edits and the review UI, and fix taste problems, not only failing tests.
- Every edit decision carries a reason, and the creator can reject it in the review app.
- Privacy: footage never leaves the PC. Only text and thumbnails go to AI, never file names, paths or exact GPS.
- Loop: handoff/docs, build, fix/improve, commit and push, test, release, repeat. Keep HANDOFF, CHANGELOG and
  QA current at every step.
- Commit and push `dev` often so nothing is lost. To release: bump the version in pyproject.toml,
  src/prepro/__init__.py and desktop/package.json; push `dev`; wait for green CI (Ubuntu and Windows); then
  `git push origin dev:main`. The release workflow tags it and builds the installers.
- Don't open pull requests unless I ask.
```
