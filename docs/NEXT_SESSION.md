# Prompt for the next session

Paste this into a new Claude Code session started in the cloned PrePro folder.

```text
You're continuing work on PrePro, my desktop pre-edit engine for Instagram and YouTube creators
(github.com/buildcool/PrePro). Work on the `dev` branch.

Read docs/HANDOFF.md first ("Current state", "Set up a PC", "Release", "Environment notes"), then CHANGELOG.md,
docs/QA.md and docs/PLAN.md.

Where things stand: v0.7.0 is released (gaming pack + Windows fixes). `dev` carries the v0.8.0 work — GPU video
encoding when it's measurably faster, and podcast two-shots (frame whoever is talking, conversations cut in order,
steady captions) — see CHANGELOG [Unreleased]. If it isn't released yet: run every test file one at a time, then
release v0.8.0 with the steps in HANDOFF. Then carry on with "Next steps" in HANDOFF, releasing each milestone.

How I want you to work:
- Think like the world's best professional video editor. The output must never feel like random stitching that
  causes ghinn or chhidh (cringe, irritation). Review your own output, including the storyboards in
  <shoot>/.prepro/qa/, the paper edits and the review UI, and fix taste problems, not only failing tests.
- Every edit decision carries a reason, and the creator can reject it in the review app.
- Privacy: footage never leaves the PC. Only text and thumbnails go to AI, never file names, paths or exact GPS.
- Use the GPU when it is available and actually helps; otherwise the CPU. Not every PC has a GPU.
- Loop: handoff/docs, build, fix/improve, commit and push, test, release, repeat. Keep HANDOFF, CHANGELOG and
  QA current at every step. Run long tests in the background so building can continue.
- Commits: author buildcool (its GitHub no-reply address, set in the repo's git config) with Claude as co-author.
- Commit and push `dev` often so nothing is lost. To release: bump the version in pyproject.toml,
  src/prepro/__init__.py and desktop/package.json; push `dev`; wait for green CI (Ubuntu and Windows); then
  `git push origin dev:main`. The release workflow tags it and builds the installers.
- Don't open pull requests unless I ask.
```
