// Thin client for the local PrePro engine (127.0.0.1). Every call carries the per-launch token.

export const TOKEN: string =
  document.querySelector('meta[name="prepro-token"]')?.getAttribute("content")?.replace("__PREPRO_TOKEN__", "") ||
  (import.meta.env.VITE_PREPRO_TOKEN as string | undefined) ||
  "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, msg: string) {
    super(msg);
    this.status = status;
  }
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "x-prepro-token": TOKEN };
  if (opts.body !== undefined) headers["content-type"] = "application/json";
  const r = await fetch("/api" + path, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = j.detail ?? msg;
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, msg);
  }
  return (await r.json()) as T;
}

const enc = (rel: string) => rel.split("/").map(encodeURIComponent).join("/");
export const mediaUrl = (pid: string, rel: string, bust?: number | string) =>
  `/api/projects/${pid}/media/${enc(rel)}?token=${encodeURIComponent(TOKEN)}${bust ? `&v=${bust}` : ""}`;
export const frameUrl = (pid: string, thumb: string) =>
  `/api/projects/${pid}/${enc(thumb)}?token=${encodeURIComponent(TOKEN)}`;

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  stage: string;
  frac: number;
  message: string;
  result: any;
  error: string | null;
  steps?: { id: string; label: string }[];
  step?: number;
  elapsed?: number;
}

export const isOver = (j: Job) => j.status === "done" || j.status === "error" || j.status === "cancelled";
export const stopJob = (j: Job) => api<Job>(`/jobs/${j.id}/cancel`, { body: {} });

/** Follow a job over SSE (falls back to polling) until it ends. */
export function followJob(job: Job, onUpdate?: (j: Job) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    if (job.status === "done") return resolve(job);
    if (job.status === "error" || job.status === "cancelled") return reject(new Error(job.error ?? "failed"));
    let done = false;
    const finish = (j: Job) => {
      if (done) return;
      done = true;
      if (j.status === "done") resolve(j);
      else reject(new Error(j.error ?? "failed"));
    };
    try {
      const es = new EventSource(`/api/jobs/${job.id}/events?token=${encodeURIComponent(TOKEN)}`);
      es.onmessage = (ev) => {
        const j = JSON.parse(ev.data) as Job;
        onUpdate?.(j);
        if (isOver(j)) {
          es.close();
          finish(j);
        }
      };
      es.onerror = () => {
        es.close();
        poll();
      };
    } catch {
      poll();
    }
    function poll() {
      const tick = async () => {
        if (done) return;
        try {
          const j = await api<Job>(`/jobs/${job.id}`);
          onUpdate?.(j);
          if (isOver(j)) return finish(j);
        } catch (e) {
          done = true;
          return reject(e);
        }
        setTimeout(tick, 500);
      };
      tick();
    }
  });
}

export const mmss = (t: number | null | undefined, dec = 1) => {
  if (t === null || t === undefined || Number.isNaN(t)) return "–";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(dec).padStart(dec ? 3 + dec : 2, "0")}`;
};
