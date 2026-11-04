"""Robustness on real footage (Intel/OpenCV sample videos, LibriSpeech/JFK speech, Kevin MacLeod music…): odd sizes and
frame rates, no-audio clips, real camera motion. Not a taste test — the engine must never crash, never reference
media that isn't there, and deliver to spec. Needs `prepro testmedia fetch`."""

from __future__ import annotations

import shutil

import pytest
from tests.conftest import needs_ffmpeg

from prepro.fixtures import realmedia
from prepro.media.ffmpeg import run_ffmpeg

pytestmark = [pytest.mark.realmedia, pytest.mark.slow, needs_ffmpeg]


@pytest.fixture(scope="module")
def real_shoot(tmp_path_factory):
    md = realmedia.available()
    need = ["face/head-pose-face-detection-female.mp4", "speech/jfk.flac", "people/face-demographics-walking.mp4",
            "street/person-bicycle-car-detection.mp4", "food/fruit-and-vegetable-detection.mp4", "nature/bear-1280x720.mp4",
            "music/vibe_ace.ogg", "music/choice_drum_bass.ogg"]
    root_md = realmedia.cache_dir()
    if not all((root_md / n).exists() for n in need):
        pytest.skip("real test media not fetched (prepro testmedia fetch)")
    _ = md
    root = tmp_path_factory.mktemp("real") / "real_shoot"
    (root / "footage").mkdir(parents=True)
    (root / "music").mkdir()
    # a talking A-roll: the face clip with real speech laid under it (looped/trimmed to the speech)
    run_ffmpeg(["-stream_loop", "-1", "-i", str(root_md / "face/head-pose-face-detection-female.mp4"), "-i", str(root_md / "speech/jfk.flac"),
                "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(root / "footage" / "talk_jfk.mp4")], timeout=600)
    for n in need[2:6]:
        shutil.copy(root_md / n, root / "footage" / n.split("/")[-1])
    for n in need[6:]:
        shutil.copy(root_md / n, root / "music" / n.split("/")[-1])
    return root


def test_real_footage_end_to_end(real_shoot, tmp_path):
    from prepro.engine import analysis, build
    from prepro.export.package import export_all
    from prepro.schema.media import AssetKind

    pa = analysis(real_shoot)
    kinds = {a.path: a.kind for a in pa.assets}
    assert kinds["footage/talk_jfk.mp4"] == AssetKind.AROLL
    assert sum(1 for k in kinds.values() if k == AssetKind.BROLL) >= 3
    assert sum(1 for k in kinds.values() if k == AssetKind.MUSIC) == 2
    talk = pa.clips[next(a.id for a in pa.assets if a.path == "footage/talk_jfk.mp4")]
    assert talk.transcript and len(talk.transcript.words) > 10          # real speech was recognised (sphinx or whisper)
    from prepro.analyze.asr import whisper_available
    from prepro.config import Settings

    if whisper_available(Settings.load().asr.whisper_model):            # a downloaded model must actually be used
        assert talk.transcript.backend == "faster-whisper", talk.transcript.note
        heard = " ".join(w.text for w in talk.transcript.words).lower()
        assert "ask not what your country can do for you" in heard.replace(",", "").replace(".", ""), heard
    res = build(real_shoot, render=True)
    tl = res.timeline
    assert tl.duration > 5 and not [f for f in res.lint if f.severity == "error"], [f.msg for f in res.lint if f.severity == "error"]
    for it in tl.items:                                                 # never reach past the end of a clip
        if it.asset_id and it.kind in ("video", "audio"):
            assert it.src_out <= pa.asset(it.asset_id).info.duration + 0.06, (it.asset_id, it.src_out)
    r = res.render
    assert r.video.exists() and abs(r.duration - tl.duration) < 0.5 and r.lufs is not None and abs(r.lufs + 14) <= 1.5
    made = export_all(tl, pa, tmp_path / "ex", formats=["fcp7", "otio", "mlt", "srt", "report"], project_root=real_shoot)
    assert {"fcp7", "otio", "mlt", "report"} <= set(made)
