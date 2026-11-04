"""Local review server for the PrePro UI (127.0.0.1 only).

Security model for a local app: bind to loopback, reject foreign Host headers (DNS rebinding), require a
per-launch token on every API call (header or ?token= for media tags), and only ever serve files that live
inside a project the user opened. No CORS headers — other origins can't read responses.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from .. import __version__
from ..config import Settings, data_dir
from ..project import Project
from .jobs import Job, Jobs

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
STATIC = Path(__file__).parent / "static"


# ------------------------------------------------------------------ project registry
def _registry_path() -> Path:
    return data_dir() / "projects.json"


def _load_registry() -> dict[str, dict]:
    p = _registry_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _save_registry(reg: dict[str, dict]) -> None:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, indent=1), encoding="utf-8")


def _pid(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:10]


def create_app(*, token: str | None = None, workers: int = 2) -> FastAPI:
    token = token or secrets.token_urlsafe(24)
    app = FastAPI(title="PrePro", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    jobs = Jobs(workers)
    app.state.jobs = jobs

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            got = request.headers.get("x-prepro-token") or request.query_params.get("token")
            if not got or not secrets.compare_digest(got, token):
                return JSONResponse({"detail": "missing or wrong token"}, status_code=401)
        return await call_next(request)

    def project(pid: str) -> Path:
        reg = _load_registry()
        if pid not in reg:
            raise HTTPException(404, "unknown project")
        p = Path(reg[pid]["path"])
        if not p.is_dir():
            raise HTTPException(410, "the shoot folder is gone (moved or deleted)")
        return p

    # ------------------------------------------------------------ basics
    @app.get("/api/health")
    def health():
        from ..media.ffmpeg import find_binary

        try:
            find_binary("ffmpeg")
            ff = True
        except Exception:
            ff = False
        return {"ok": True, "version": __version__, "ffmpeg": ff}

    @app.get("/api/projects")
    def projects():
        reg = _load_registry()
        out = []
        for pid, r in sorted(reg.items(), key=lambda kv: -kv[1].get("opened", 0)):
            p = Path(r["path"])
            out.append({**r, "id": pid, "exists": p.is_dir(), "analysed": (p / ".prepro" / "analysis.json").exists(),
                        "timelines": len(list((p / ".prepro" / "timelines").glob("*-*.json"))) if p.is_dir() else 0})
        return out

    @app.post("/api/projects")
    def add_project(body: dict = Body(...)):
        path = Path(str(body.get("path", ""))).expanduser()
        if not path.is_dir():
            raise HTTPException(400, f"not a folder: {path}")
        path = path.resolve()
        if path == Path.home().resolve() or len(path.parts) <= 1:
            raise HTTPException(400, "pick the shoot folder itself, not your home folder or a drive root")
        reg = _load_registry()
        pid = _pid(path)
        reg[pid] = {"path": str(path), "name": body.get("name") or path.name, "added": reg.get(pid, {}).get("added", time.time()), "opened": time.time()}
        _save_registry(reg)
        return {"id": pid, **reg[pid]}

    @app.delete("/api/projects/{pid}")
    def forget_project(pid: str):
        reg = _load_registry()
        reg.pop(pid, None)
        _save_registry(reg)
        return {"ok": True}

    @app.get("/api/projects/{pid}")
    def project_summary(pid: str):
        root = project(pid)
        proj = Project(root)
        from ..analyze.pipeline import load_analysis
        from ..schema.brief import CreatorBrief
        from ..schema.plan import DirectionSet
        from ..schema.timeline import Timeline

        pa = load_analysis(root)
        tdir = proj.cache / "timelines"
        tls = []
        for p in sorted(tdir.glob("*.json")) if tdir.exists() else []:
            if p.name.count(".") != 1:
                continue
            try:
                t = Timeline.model_validate_json(p.read_text(encoding="utf-8"))
                tls.append({"id": t.id, "name": t.name, "duration": round(t.duration, 2), "playbook": t.playbook,
                            "updated": p.stat().st_mtime, "aspect": t.aspect})
            except Exception:
                continue
        ds = proj.load_model("directions.json", DirectionSet)
        brief = proj.load_model("brief.json", CreatorBrief)
        bt = proj.cache / "brief_text.md"
        counts: dict[str, int] = {}
        if pa:
            for a in pa.assets:
                counts[a.kind.value] = counts.get(a.kind.value, 0) + 1
        reg = _load_registry()
        reg[pid]["opened"] = time.time()
        _save_registry(reg)
        return {"id": pid, "path": str(root), "name": reg[pid]["name"], "analysed": pa is not None,
                "counts": counts, "stats": pa.stats if pa else {}, "warnings": pa.warnings if pa else [],
                "genres": [g.model_dump() for g in pa.genres] if pa else [],
                "timelines": sorted(tls, key=lambda x: -x["updated"]),
                "directions": ds.model_dump() if ds else None,
                "brief": {"text": bt.read_text(encoding="utf-8") if bt.exists() else "", "parsed": brief.model_dump() if brief else None},
                "jobs": [j.public() for j in jobs.jobs.values() if j.project == pid and j.status in ("queued", "running")]}

    # ------------------------------------------------------------ analysis
    @app.post("/api/projects/{pid}/analyze")
    def analyze(pid: str, body: dict = Body(default={})):
        root = project(pid)
        if (j := jobs.running(pid, "analyze")) is not None:
            return j.public()

        def work(job: Job):
            from ..engine import analysis

            pa = analysis(root, force=bool(body.get("force")), progress=job.progress)
            return {"assets": len(pa.assets), "warnings": pa.warnings}

        return jobs.submit("analyze", pid, work).public()

    @app.get("/api/projects/{pid}/assets")
    def assets(pid: str):
        root = project(pid)
        from ..analyze.pipeline import load_analysis
        from ..brain.basic import BasicBrain

        pa = load_analysis(root)
        if pa is None:
            raise HTTPException(409, "not analysed yet")
        bb = BasicBrain(pa, None)
        out = []
        for a in pa.assets:
            ca = pa.clips[a.id]
            shots = [{"id": s.id, "t0": s.t0, "t1": s.t1, "flags": s.flags, "tags": s.tags, "desc": s.desc, "quality": round(s.quality, 2),
                      "move": s.camera_move, "thumb": f"frames/{s.id}_1.jpg"} for s in ca.shots]
            segs = [{"id": s.id, "t0": s.t0, "t1": s.t1, "text": s.text, "cut": bb.is_cut_candidate(s) or None}
                    for s in (ca.transcript.segments if ca.transcript else [])]
            m = ca.music
            out.append({"id": a.id, "name": a.name, "path": a.path, "kind": a.kind.value, "duration": round(a.info.duration, 2),
                        "fps": a.info.fps, "size": a.info.display_size, "day": ca.day_index, "place": ca.place,
                        "thumb": shots[0]["thumb"] if shots else None, "shots": shots, "segments": segs,
                        "music": {"bpm": m.bpm, "mood": m.mood_tags, "key": m.key} if m else None})
        return out

    @app.get("/api/projects/{pid}/frames/{name}")
    def frame(pid: str, name: str):
        root = project(pid)
        p = (Project(root).cache / "frames" / name).resolve()
        if not p.is_relative_to((Project(root).cache / "frames").resolve()) or not p.exists():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/projects/{pid}/media/{rel:path}")
    def media(pid: str, rel: str):
        """Renders, exports and source clips — only files inside the project folder (Range requests supported)."""
        root = project(pid).resolve()
        p = (root / rel).resolve()
        if not p.is_relative_to(root) or not p.is_file():
            raise HTTPException(404)
        return FileResponse(p)

    @app.get("/api/projects/{pid}/search")
    def search(pid: str, q: str):
        root = project(pid)
        from rapidfuzz import fuzz

        from ..analyze.pipeline import load_analysis

        pa = load_analysis(root)
        if pa is None or not q.strip():
            return []
        ql = q.lower().strip()
        hits = []
        for a in pa.assets:
            ca = pa.clips[a.id]
            for s in ca.transcript.segments if ca.transcript else []:
                sc = fuzz.partial_ratio(ql, s.text.lower())
                if sc >= 70:
                    hits.append({"type": "line", "id": s.id, "asset": a.id, "t": s.t0, "text": s.text, "score": sc,
                                 "thumb": f"frames/{ca.shots[0].id}_1.jpg" if ca.shots else None})
            for s in ca.shots:
                hay = " ".join([*s.tags, s.desc or "", s.camera_move, ca.place or "", s.mood or "", s.shot_type or "", a.kind.value]).lower()
                sc = fuzz.token_set_ratio(ql, hay)
                if sc >= 60:
                    hits.append({"type": "shot", "id": s.id, "asset": a.id, "t": s.t0, "text": (s.desc or " ".join(s.tags) or s.camera_move),
                                 "score": sc, "thumb": f"frames/{s.id}_1.jpg"})
        return sorted(hits, key=lambda h: -h["score"])[:30]

    # ------------------------------------------------------------ brief + directions + build
    @app.put("/api/projects/{pid}/brief")
    def put_brief(pid: str, body: dict = Body(...)):
        root = project(pid)
        from ..analyze.pipeline import load_analysis
        from ..brief.parse import parse_text
        from ..brief.resolve import resolve

        text = str(body.get("text", ""))[:8000]
        p = Project(root).cache / "brief_text.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        b = parse_text(text)
        pa = load_analysis(root)
        if pa is not None:
            resolve(b, pa)
        return b.model_dump()

    def _brief_text(root: Path) -> str | None:
        p = Project(root).cache / "brief_text.md"
        return p.read_text(encoding="utf-8") if p.exists() and p.read_text(encoding="utf-8").strip() else None

    @app.post("/api/projects/{pid}/directions")
    def make_directions(pid: str):
        root = project(pid)

        def work(job: Job):
            from ..engine import directions

            job.progress("directions", 0, 1, "reading the footage")
            ds, brief, calls = directions(root, brief_text=_brief_text(root), progress=job.progress)
            return {"directions": ds.model_dump(), "brief": brief.model_dump(), "ai_calls": len(calls)}

        return jobs.submit("directions", pid, work).public()

    @app.post("/api/projects/{pid}/build")
    def make_build(pid: str, body: dict = Body(default={})):
        root = project(pid)
        if (j := jobs.running(pid, "build")) is not None:
            return j.public()

        def work(job: Job):
            from ..engine import build
            from ..revise import load_revision, recompile

            job.progress("build", 0.1, 1, "story → polish → compile → lint")
            res = build(root, direction=body.get("direction") or "auto", brief_text=_brief_text(root), render=False,
                        knobs=body.get("knobs") or None, progress=job.progress)
            tid = res.timeline.id
            base = Project(root).cache / "timelines" / f"{tid}.base.json"
            base.write_text(res.timeline.model_dump_json(indent=1), encoding="utf-8")
            rev = load_revision(root, tid)
            if rev.ops:                    # the creator's earlier choices survive a rebuild
                job.progress("build", 0.8, 1, f"re-applying {len(rev.ops)} of your changes")
                recompile(root, tid, rev)
            if body.get("render", True):
                job.progress("render", 0.85, 1, "rendering a preview")
                _render(root, tid, "preview")
            return {"timeline": tid, "warnings": res.warnings, "ai_calls": len(res.ai_calls), "cost_usd": res.cost_usd}

        return jobs.submit("build", pid, work).public()

    # ------------------------------------------------------------ timeline review
    def _view(root: Path, tid: str) -> dict:
        from ..analyze.pipeline import load_analysis
        from ..brain.ai import paper_edit
        from ..lint.critic import rules_critic
        from ..lint.editlint import compliance, lint_timeline
        from ..revise import load_revision
        from ..schema.brief import CreatorBrief
        from ..schema.plan import DirectionSet
        from ..schema.timeline import Timeline
        from ..timeline.attention import attention_curve

        proj = Project(root)
        p = proj.cache / "timelines" / f"{tid}.json"
        if not p.exists():
            raise HTTPException(404, "no such timeline")
        tl = Timeline.model_validate_json(p.read_text(encoding="utf-8"))
        pa = load_analysis(root)
        ds = proj.load_model("directions.json", DirectionSet)
        d = next((x for x in ds.directions if x.id == tl.direction_id), None) if ds else None
        brief = proj.load_model("brief.json", CreatorBrief) or CreatorBrief()
        findings = lint_timeline(tl, pa, d, brief) if d else []
        critic = rules_critic(tl, pa, d, findings) if d else None
        comp = compliance(tl, pa, d, brief) if d else []
        renders = sorted(proj.sub("renders").glob(f"{tid}_*.mp4"), key=lambda q: q.stat().st_mtime)
        render = None
        if renders and renders[-1].stat().st_mtime >= p.stat().st_mtime - 1:
            render = str(renders[-1].relative_to(root))
        stale = bool(renders) and render is None
        names = {a.id: a.name for a in pa.assets} if pa else {}
        return {"timeline": json.loads(tl.model_dump_json()), "duration": round(tl.duration, 3), "assets": names,
                "lint": [{"rule": f.rule, "severity": f.severity, "msg": f.msg, "t": f.t} for f in findings],
                "critic": critic.model_dump() if critic else None,
                "compliance": [{"ok": c.ok, "rule": c.rule.kind, "source": c.rule.source.strip(), "detail": c.detail} for c in comp],
                "revision": load_revision(root, tid).model_dump(),
                "direction": d.model_dump() if d else None,
                "attention": attention_curve(tl), "paper_edit": paper_edit(tl, pa) if pa else "",
                "render": render, "render_stale": stale or (render is None and not renders)}

    @app.get("/api/projects/{pid}/timelines/{tid}")
    def timeline(pid: str, tid: str):
        return _view(project(pid), tid)

    @app.post("/api/projects/{pid}/timelines/{tid}/suggestions")
    def set_suggestion(pid: str, tid: str, body: dict = Body(...)):
        root = project(pid)
        from ..revise import recompile, toggle

        key, status = str(body.get("key", "")), body.get("status")
        if status not in ("applied", "rejected") or not key:
            raise HTTPException(400, "need key and status applied|rejected")
        try:
            rev = toggle(root, tid, key, status)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        recompile(root, tid, rev)
        return _view(root, tid)

    @app.post("/api/projects/{pid}/timelines/{tid}/comments")
    def comment(pid: str, tid: str, body: dict = Body(...)):
        root = project(pid)
        from ..revise import add_comment, recompile

        text = str(body.get("text", "")).strip()[:500]
        if not text:
            raise HTTPException(400, "empty comment")
        brain = _revise_brain(root)
        rev, c = add_comment(root, tid, float(body.get("t", 0.0)), text, brain=brain)
        recompile(root, tid, rev)
        return {"comment": c.model_dump(), "view": _view(root, tid)}

    @app.delete("/api/projects/{pid}/timelines/{tid}/comments/{cid}")
    def delete_comment(pid: str, tid: str, cid: str):
        root = project(pid)
        from ..revise import recompile, remove_comment

        recompile(root, tid, remove_comment(root, tid, cid))
        return _view(root, tid)

    @app.post("/api/projects/{pid}/timelines/{tid}/hook")
    def pick_hook(pid: str, tid: str, body: dict = Body(...)):
        root = project(pid)
        from ..revise import Op, load_revision, recompile

        rev = load_revision(root, tid)
        rev.ops = [o for o in rev.ops if o.op != "hook"]
        if body.get("hook_id"):
            rev.ops.append(Op(op="hook", value=str(body["hook_id"]), why="hook picker"))
        recompile(root, tid, rev)
        return _view(root, tid)

    @app.post("/api/projects/{pid}/timelines/{tid}/reset")
    def reset(pid: str, tid: str):
        root = project(pid)
        from ..revise import Revision, recompile

        recompile(root, tid, Revision(timeline_id=tid))
        return _view(root, tid)

    def _render(root: Path, tid: str, quality: str, progress=None) -> str:
        from ..analyze.pipeline import load_analysis
        from ..export.render import render
        from ..schema.timeline import Timeline

        proj = Project(root)
        tl = Timeline.model_validate_json((proj.cache / "timelines" / f"{tid}.json").read_text(encoding="utf-8"))
        out = proj.sub("renders") / f"{tid}_{quality}.mp4"
        r = render(tl, load_analysis(root), out, quality=quality, project_root=root)
        return str(r.video.relative_to(root))

    @app.post("/api/projects/{pid}/timelines/{tid}/render")
    def do_render(pid: str, tid: str, body: dict = Body(default={})):
        root = project(pid)
        quality = "final" if body.get("quality") == "final" else "preview"

        def work(job: Job):
            job.progress("render", 0.05, 1, f"{quality} render")
            return {"video": _render(root, tid, quality)}

        return jobs.submit("render", pid, work).public()

    @app.post("/api/projects/{pid}/timelines/{tid}/export")
    def do_export(pid: str, tid: str, body: dict = Body(default={})):
        root = project(pid)
        from ..export.package import FORMATS

        fmts = [f for f in (body.get("formats") or ["fcp7", "otio", "kdenlive", "mlt", "srt", "overlay", "report"]) if f in FORMATS]

        def work(job: Job):
            from ..analyze.pipeline import load_analysis
            from ..export.package import export_all
            from ..lint.critic import rules_critic
            from ..lint.editlint import lint_timeline
            from ..project import EXPORTS_DIR
            from ..schema.brief import CreatorBrief
            from ..schema.plan import DirectionSet
            from ..schema.timeline import Timeline

            proj = Project(root)
            tl = Timeline.model_validate_json((proj.cache / "timelines" / f"{tid}.json").read_text(encoding="utf-8"))
            pa = load_analysis(root)
            ds = proj.load_model("directions.json", DirectionSet)
            d = next((x for x in ds.directions if x.id == tl.direction_id), None) if ds else None
            brief = proj.load_model("brief.json", CreatorBrief)
            findings = lint_timeline(tl, pa, d, brief) if d else []
            critic = rules_critic(tl, pa, d, findings) if d else None
            out = root / EXPORTS_DIR / tid
            job.progress("export", 0.1, 1, ", ".join(fmts))
            made = export_all(tl, pa, out, formats=fmts, project_root=root, critic=critic, lint=findings, direction=d, brief=brief)
            return {"folder": str(out), "files": {k: str(v.relative_to(root)) for k, v in made.items()}}

        return jobs.submit("export", pid, work).public()

    def _revise_brain(root: Path):
        s = Settings.load()
        if s.routing.revise in ("basic", "", None):
            return None
        from ..analyze.pipeline import load_analysis
        from ..engine import make_brain
        from ..schema.brief import CreatorBrief

        pa = load_analysis(root)
        brief = Project(root).load_model("brief.json", CreatorBrief) or CreatorBrief()
        b = make_brain(pa, brief, s, root)
        return b if hasattr(b, "revise") else None

    # ------------------------------------------------------------ brains (AI connectors) + privacy
    @app.get("/api/brains")
    def brains():
        from ..brain.providers import KINDS, TRAINING, detect_connectors

        s = Settings.load()
        found = detect_connectors()
        conns = []
        for name, cfg in {**found, **s.connectors}.items():
            badge = TRAINING.get(cfg.kind if cfg.kind != "gemini" else f"gemini_{cfg.extra.get('tier', 'free')}", "")
            conns.append({"name": name, "kind": cfg.kind, "model": cfg.model, "detected": name in found and name not in s.connectors,
                          "training": badge, "local": cfg.kind in ("ollama", "stub")})
        return {"connectors": conns, "kinds": sorted(k for k in KINDS if k != "stub"), "routing": s.routing.model_dump(),
                "privacy": s.privacy, "blur_faces": s.blur_faces_in_thumbs, "monthly_cap_usd": s.monthly_cap_usd}

    @app.put("/api/brains")
    def set_brains(body: dict = Body(...)):
        s = Settings.load()
        if "routing" in body:
            valid = {"basic"} | set(s.connectors) | set(_detected())
            r = {k: v for k, v in dict(body["routing"]).items() if k in type(s.routing).model_fields and v in valid}
            s.routing = s.routing.model_copy(update=r)
        if body.get("privacy") in ("local", "text", "thumbs"):
            s.privacy = body["privacy"]
        if "blur_faces" in body:
            s.blur_faces_in_thumbs = bool(body["blur_faces"])
        s.save()
        return brains()

    def _detected():
        from ..brain.providers import detect_connectors

        return detect_connectors()

    # ------------------------------------------------------------ jobs
    @app.get("/api/jobs/{jid}")
    def job(jid: str):
        j = jobs.get(jid)
        if j is None:
            raise HTTPException(404)
        return j.public()

    @app.get("/api/jobs/{jid}/events")
    async def job_events(jid: str):
        j = jobs.get(jid)
        if j is None:
            raise HTTPException(404)

        async def stream():
            last = -1
            while True:
                if j.rev != last:
                    last = j.rev
                    yield f"data: {json.dumps(j.public(), default=str)}\n\n"
                if j.status in ("done", "error"):
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------ the UI
    @app.get("/{path:path}")
    def ui(path: str):
        target = (STATIC / path).resolve() if path else None
        if target and target.is_file() and target.is_relative_to(STATIC.resolve()):
            return FileResponse(target, headers={"Cache-Control": "max-age=31536000, immutable"} if "/assets/" in f"/{path}" else None)
        index = STATIC / "index.html"
        if not index.exists():
            return HTMLResponse("<h1>PrePro</h1><p>The UI is not built. Run <code>npm --prefix ui run build</code>.</p>", status_code=200)
        html = index.read_text(encoding="utf-8").replace("__PREPRO_TOKEN__", token)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True, token: str | None = None) -> None:
    import threading
    import webbrowser

    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("PrePro's server only listens on this computer (127.0.0.1).")
    app = create_app(token=token)
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"PrePro {__version__} → {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


__all__: list[Any] = ["create_app", "serve"]
