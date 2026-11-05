"""The autonomous pre-edit over HTTP: one call takes a shoot folder to a rendered, exported first cut, reporting named
steps with progress that only moves forward — the app's "Make my first cut" button (and opening a new shoot)."""

from __future__ import annotations

import shutil
import time

import pytest
from tests.conftest import needs_ffmpeg

pytestmark = [needs_ffmpeg]


def test_one_click_from_folder_to_exported_cut(shoot_factory, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from prepro.server import create_app

    monkeypatch.setenv("PREPRO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PREPRO_CONFIG_DIR", str(tmp_path / "config"))
    src = shoot_factory("photo_dump")
    root = tmp_path / "Goa day"
    shutil.copytree(src, root, ignore=shutil.ignore_patterns("renders", "exports", "timelines"))
    c = TestClient(create_app(token="t"), base_url="http://127.0.0.1")
    c.headers["x-prepro-token"] = "t"
    pid = c.post("/api/projects", json={"path": str(root)}).json()["id"]
    job = c.post(f"/api/projects/{pid}/autocut", json={}).json()
    assert [s["label"] for s in job["steps"]] == ["Watching and listening", "Finding the story", "Editing", "Rendering your cut",
                                                  "Getting exports ready"]
    seen, t0 = [], time.time()
    while job["status"] in ("queued", "running"):
        assert time.time() - t0 < 900, job
        time.sleep(0.2)
        job = c.get(f"/api/jobs/{job['id']}").json()
        seen.append((job["step"], job["frac"]))
    assert job["status"] == "done", job
    fr = [f for _s, f in seen]
    assert fr == sorted(fr) and max(s for s, _f in seen) == 4                      # forward only, through every step
    res = job["result"]
    assert (root / res["video"]).exists() and res["duration"] > 5
    files = res["files"]
    assert {"fcp7", "report"} <= set(files) and all((root / f).exists() for f in files.values())   # (no speech: no .srt)
    tl = c.get(f"/api/projects/{pid}/timelines/{res['timeline']}").json()
    assert tl["render"] == res["video"] and not tl["render_stale"]               # the review opens on a fresh render
    again = c.post(f"/api/projects/{pid}/autocut", json={}).json()               # a second click while idle starts a new one…
    busy = c.post(f"/api/projects/{pid}/autocut", json={}).json()                # …and a click while it runs follows it
    assert busy["id"] == again["id"]
    c.post(f"/api/jobs/{again['id']}/cancel")
    for _ in range(600):
        again = c.get(f"/api/jobs/{again['id']}").json()
        if again["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert again["status"] in ("cancelled", "done")                             # Stop works (or it had already finished)


@pytest.mark.parametrize("missing", ["nope"])
def test_autocut_of_an_unknown_shoot_is_404(missing, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from prepro.server import create_app

    monkeypatch.setenv("PREPRO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PREPRO_CONFIG_DIR", str(tmp_path / "config"))
    c = TestClient(create_app(token="t"), base_url="http://127.0.0.1")
    c.headers["x-prepro-token"] = "t"
    assert c.post(f"/api/projects/{missing}/autocut", json={}).status_code == 404
