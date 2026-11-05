"""M5 local server: security guards, project flow (analyse → brief → directions → build → review → export) over HTTP."""

from __future__ import annotations

import time

import pytest
from tests.conftest import needs_ffmpeg, needs_tts

pytestmark = [needs_tts, needs_ffmpeg]
TOKEN = "test-token-123"


@pytest.fixture(scope="module")
def client(tmp_path_factory, shoot_factory):
    import os

    from fastapi.testclient import TestClient

    from prepro.server import create_app

    os.environ["PREPRO_DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    os.environ["PREPRO_CONFIG_DIR"] = str(tmp_path_factory.mktemp("config"))
    root = shoot_factory("travel_vlog", brief=True)
    for suffix in (".base.json", ".revision.json"):
        p = root / ".prepro" / "timelines" / f"d1-story_vlog{suffix}"
        if p.exists():
            p.unlink()
    c = TestClient(create_app(token=TOKEN), base_url="http://127.0.0.1")
    c.headers["x-prepro-token"] = TOKEN
    c.root = root  # type: ignore[attr-defined]
    return c


def _wait(c, job: dict, timeout: float = 600) -> dict:
    t0 = time.time()
    while job["status"] not in ("done", "error"):
        assert time.time() - t0 < timeout, job
        time.sleep(0.2)
        job = c.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done", job
    return job["result"]


def test_guards(client):
    from fastapi.testclient import TestClient

    assert client.get("/api/health").json()["ok"]
    anon = TestClient(client.app, base_url="http://127.0.0.1")
    assert anon.get("/api/projects").status_code == 401                         # no token
    evil = TestClient(client.app, base_url="http://evil.example")
    assert evil.get("/api/health", headers={"x-prepro-token": TOKEN}).status_code == 403   # DNS-rebinding host
    assert client.post("/api/projects", json={"path": "/definitely/not/here"}).status_code == 400


def test_full_review_flow(client):
    c, root = client, client.root
    p = c.post("/api/projects", json={"path": str(root)}).json()
    pid = p["id"]
    assert any(x["id"] == pid for x in c.get("/api/projects").json())
    _wait(c, c.post(f"/api/projects/{pid}/analyze", json={}).json())
    s = c.get(f"/api/projects/{pid}").json()
    assert s["analysed"] and s["counts"]["aroll"] >= 2
    assets = c.get(f"/api/projects/{pid}/assets").json()
    assert any(a["segments"] for a in assets) and any(a["kind"] == "music" and a["music"] for a in assets)
    hits = c.get(f"/api/projects/{pid}/search", params={"q": "kachori"}).json()
    assert hits and hits[0]["type"] == "line" and "kachori" in hits[0]["text"].lower()
    thumb = next(a["thumb"] for a in assets if a["thumb"])
    assert c.get(f"/api/projects/{pid}/{thumb.replace('frames/', 'frames/')}").status_code == 200

    parsed = c.put(f"/api/projects/{pid}/brief", json={"text": "Reel, 30 sec. No zooms. Add text at the end: Follow for part 2"}).json()
    assert {r["kind"] for r in parsed["rules"]} >= {"no_effect", "add_text"}
    ds = _wait(c, c.post(f"/api/projects/{pid}/directions").json())["directions"]
    assert 2 <= len(ds["directions"]) <= 4 and all(d["hooks"] for d in ds["directions"])

    res = _wait(c, c.post(f"/api/projects/{pid}/build", json={"direction": ds["directions"][0]["id"], "render": False}).json())
    tid = res["timeline"]
    v = c.get(f"/api/projects/{pid}/timelines/{tid}").json()
    assert v["duration"] > 5 and v["attention"] and v["critic"]["scores"] and v["paper_edit"]
    assert all(x["ok"] for x in v["compliance"]), v["compliance"]

    # reject a decision, then comment, then undo both
    key = next(s["payload"]["key"] for s in v["timeline"]["suggestions"] if s["type"] in ("sfx", "text", "meme") and s["status"] == "applied")
    v2 = c.post(f"/api/projects/{pid}/timelines/{tid}/suggestions", json={"key": key, "status": "rejected"}).json()
    assert any(s["payload"].get("key") == key and s["status"] == "rejected" for s in v2["timeline"]["suggestions"])
    r = c.post(f"/api/projects/{pid}/timelines/{tid}/comments", json={"t": 8.0, "text": "big text: only ₹5000"}).json()
    assert r["comment"]["status"] == "applied"
    assert any(i["kind"] == "text" and "5000" in (i["text"] or "") for i in r["view"]["timeline"]["items"])
    v3 = c.delete(f"/api/projects/{pid}/timelines/{tid}/comments/{r['comment']['id']}").json()
    assert not any(i["kind"] == "text" and "only ₹5000" in (i["text"] or "") for i in v3["timeline"]["items"])
    v4 = c.post(f"/api/projects/{pid}/timelines/{tid}/reset").json()
    assert not v4["revision"]["ops"]
    # the hook picker
    hooks = v4["direction"]["hooks"]
    if len(hooks) > 1:
        v5 = c.post(f"/api/projects/{pid}/timelines/{tid}/hook", json={"hook_id": hooks[1]["id"]}).json()
        first = min((i for i in v5["timeline"]["items"] if i["track"] == "V1"), key=lambda i: i["rec_in"])
        assert first["ref"] == hooks[1]["refs"][0]
        c.post(f"/api/projects/{pid}/timelines/{tid}/reset")

    # export (fast formats) and fetch a file back through the media route
    ex = _wait(c, c.post(f"/api/projects/{pid}/timelines/{tid}/export", json={"formats": ["fcp7", "srt", "report"]}).json())
    rel = ex["files"]["fcp7"]
    got = c.get(f"/api/projects/{pid}/media/{rel}")
    assert got.status_code == 200 and b"<xmeml" in got.content
    # no escaping the project folder
    for bad in (f"/api/projects/{pid}/media/../../../../etc/passwd", f"/api/projects/{pid}/media/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
                f"/api/projects/{pid}/media/{'%2e%2e%2f' * 6}etc%2fpasswd", f"/api/projects/{pid}/frames/..%2f..%2f..%2fanalysis.json"):
        r = c.get(bad)
        assert b"root:" not in r.content and b'"assets"' not in r.content, bad


def test_brains_settings_roundtrip(client):
    b = client.get("/api/brains").json()
    # every task follows "your AI editor" ("auto"); with none connected that is the rules engine
    assert b["routing"]["director"] == "auto" and b["privacy"] in ("local", "text", "thumbs")
    assert client.get("/api/ai").json()["editor"] == "basic"
    b2 = client.put("/api/brains", json={"privacy": "text", "routing": {"director": "no-such-connector"}}).json()
    assert b2["privacy"] == "text" and b2["routing"]["director"] == "auto"   # unknown connectors are refused
