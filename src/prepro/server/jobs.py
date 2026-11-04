"""Tiny in-process job runner: long work (analysis, builds, renders, exports) runs in threads, the UI follows it over SSE."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    kind: str
    project: str
    status: str = "queued"          # queued | running | done | error
    stage: str = ""
    frac: float = 0.0
    message: str = ""
    result: Any = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    rev: int = 0                     # bumps on every change (SSE uses it)

    def progress(self, stage: str, i: float = 0, n: float = 1, msg: str = "") -> None:
        self.stage, self.frac, self.message = stage, max(0.0, min(1.0, float(i) / max(float(n), 1e-9))), str(msg)[:200]
        self.touch()

    def touch(self) -> None:
        self.updated = time.time()
        self.rev += 1

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "project": self.project, "status": self.status, "stage": self.stage,
                "frac": round(self.frac, 3), "message": self.message, "result": self.result, "error": self.error, "rev": self.rev}


class Jobs:
    def __init__(self, workers: int = 2) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="prepro-job")
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def submit(self, kind: str, project: str, fn: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, project=project)
        with self.lock:
            self.jobs[job.id] = job
            # keep the registry small
            old = sorted(self.jobs.values(), key=lambda j: j.created)[:-200]
            for j in old:
                self.jobs.pop(j.id, None)

        def run() -> None:
            job.status = "running"
            job.touch()
            try:
                job.result = fn(job)
                job.status, job.frac = "done", 1.0
            except Exception as e:  # report, never crash the server
                job.status, job.error = "error", f"{type(e).__name__}: {e}"
                job.message = traceback.format_exc(limit=3)[-600:]
            job.touch()

        self.pool.submit(run)
        return job

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def running(self, project: str, kind: str | None = None) -> Job | None:
        return next((j for j in self.jobs.values() if j.project == project and j.status in ("queued", "running") and (kind is None or j.kind == kind)), None)
