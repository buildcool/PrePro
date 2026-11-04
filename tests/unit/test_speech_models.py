"""Speech-model downloads report real progress, and rough fallback transcripts are redone once Whisper is available."""

from __future__ import annotations

import time

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

import prepro.speech_models as sm


def test_download_reports_megabytes_as_they_arrive(tmp_path, monkeypatch):
    pytest.importorskip("faster_whisper")
    folder = tmp_path / "models--Systran--faster-whisper-small"
    monkeypatch.setattr(sm, "_repo_dir", lambda repo: folder)

    def fake_download(name):
        (folder / "blobs").mkdir(parents=True)
        for k in range(3):                       # three chunks of 1 MB, like a slow connection
            (folder / "blobs" / f"part{k}").write_bytes(b"\0" * 1_000_000)
            time.sleep(0.6)
        return str(folder)

    import faster_whisper.utils

    monkeypatch.setattr(faster_whisper.utils, "download_model", fake_download)
    seen = []
    path = sm.download("small", lambda stage, i, n, msg: seen.append((i, n, msg)))
    assert path == str(folder)
    mbs = [i for i, _n, _m in seen]
    assert mbs == sorted(mbs) and mbs[-1] == seen[-1][1]          # monotonic, ends at 100 %
    assert any(0 < i < seen[-1][1] for i in mbs)                 # intermediate progress was reported
    assert "ready" in seen[-1][2]


def test_status_lists_every_model_with_its_size():
    st = sm.status("small")
    assert [m["name"] for m in st][:3] == ["tiny", "base", "small"]
    assert next(m for m in st if m["name"] == "small")["current"]
    assert sm.repo_for("large-v3-turbo") != "Systran/faster-whisper-large-v3-turbo" or not sm.installed()


def test_broken_recogniser_is_reported_not_silent():
    """A recogniser that can't even load (pocketsphinx's DLL on Windows) must surface as a warning with the fix,
    and those clips get transcribed again once Whisper is there."""
    from prepro.analyze.asr import can_improve, failed_note
    from prepro.schema.analysis import Transcript, Word

    broken = Transcript(asset_id="C01", backend="none", note="pocketsphinx failed: DLL load failed while importing _pocketsphinx")
    assert "DLL load failed" in failed_note(broken) and can_improve(broken)
    fine = Transcript(asset_id="C01", backend="pocketsphinx", words=[Word(id="C01.w0", t0=0, t1=0.4, text="hi")])
    assert failed_note(fine) is None and can_improve(fine)
    silent = Transcript(asset_id="C01", backend="none")          # nothing to recognise: no warning
    assert failed_note(silent) is None and not can_improve(silent)


def test_doctor_tells_broken_from_missing(monkeypatch):
    import importlib

    from prepro.cli import _import_state

    assert _import_state("json")[0].endswith("installed")
    assert "not installed" in _import_state("surely_not_a_module_xyz")[0]
    real = importlib.import_module

    def boom(name, *a, **k):
        if name == "json":
            raise ImportError("DLL load failed while importing _json: The specified module could not be found.")
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", boom)
    state, detail = _import_state("json")
    assert "won't load" in state and "DLL load failed" in detail


@needs_tts
@needs_ffmpeg
def test_rough_transcripts_are_redone_when_whisper_arrives(shoot_factory, tmp_path, monkeypatch):
    import shutil

    from prepro.analyze import asr, pipeline
    from prepro.engine import analysis

    src = shoot_factory("talking_head")
    root = tmp_path / "shoot"
    root.mkdir()
    shutil.copy(src / "A001.mp4", root / "A001.mp4")              # no transcript sidecar → offline recogniser
    monkeypatch.setattr(asr, "whisper_available", lambda model="small": False)
    pa = analysis(root)
    aid = pa.assets[0].id
    assert pa.clips[aid].transcript.backend == "pocketsphinx"
    # now the model is "downloaded": the next analysis redoes only that transcript, with Whisper
    monkeypatch.setattr(asr, "whisper_available", lambda model="small": True)
    monkeypatch.setattr(pipeline, "_whisper_ready", lambda settings: True)
    monkeypatch.setattr(asr, "transcribe_whisper", lambda y, **kw: ([asr.RawWord("hello", 0.7, 1.0, 0.99), asr.RawWord("everyone", 1.0, 1.5, 0.98)], "en"))
    pa2 = analysis(root)
    assert pa2.clips[aid].transcript.backend == "faster-whisper"
