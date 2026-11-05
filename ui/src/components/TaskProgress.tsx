import { useEffect, useRef, useState } from "react";
import { type Job, stopJob } from "../api";
import Icon from "./Icon";

const TITLE: Record<string, string> = {
  autocut: "Making your cut",
  analyze: "Watching and listening to your footage",
  build: "Editing your cut",
  render: "Rendering",
  export: "Exporting",
  package: "Making titles, thumbnails and chapters",
  shorts: "Finding Shorts in your video",
  previews: "Making quick previews",
  directions: "Finding directions",
  style: "Measuring your reference videos",
  model: "Downloading the speech model",
  ai_test: "Testing the connection",
};

const STAGE: Record<string, string> = {
  probe: "Reading your files",
  analyse: "Watching each clip",
  context: "Working out days, places and the genre",
  done: "Analysis saved",
  plan: "Finding the story",
  edit: "Editing",
  render: "Rendering",
  export: "Exporting",
  directions: "Choosing a direction",
};

/** What it's doing, in words: a bare file path becomes "Looking at IMG_0004.jpg". */
function words(stage: string, msg: string): string {
  if (!msg) return STAGE[stage] ?? "Starting…";
  if ((stage === "analyse" || stage === "probe") && !msg.includes(" ") && /[\\/]|\.\w{2,4}$/.test(msg)) {
    const name = msg.split(/[\\/]/).pop();
    return stage === "probe" ? `Reading ${name}` : `Looking at ${name}`;
  }
  return msg.charAt(0).toUpperCase() + msg.slice(1);
}

function clock(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return m ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
}

function eta(elapsed: number, frac: number): string | null {
  if (frac < 0.06 || elapsed < 4 || frac >= 0.995) return null;
  const left = (elapsed * (1 - frac)) / frac;
  if (left < 8) return "a few seconds left";
  if (left < 60) return `about ${Math.round(left / 5) * 5}s left`;
  const m = Math.round(left / 60);
  return `about ${m} min left`;
}

/** A running task, alive while it works: what it's doing in words, a stepper for multi-step work, a bar that keeps
 *  moving (a sheen; stripes when an update is slow to come), elapsed time that ticks, a time-left estimate, Stop. */
export default function TaskProgress({ job, compact = false, onStopped }: { job: Job; compact?: boolean; onStopped?: () => void }) {
  const [now, setNow] = useState(Date.now());
  const base = useRef<{ at: number; elapsed: number }>({ at: Date.now(), elapsed: job.elapsed ?? 0 });
  const lastChange = useRef<{ at: number; frac: number; msg: string }>({ at: Date.now(), frac: job.frac, msg: job.message });
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    base.current = { at: Date.now(), elapsed: job.elapsed ?? base.current.elapsed };
    if (job.frac !== lastChange.current.frac || job.message !== lastChange.current.msg) {
      lastChange.current = { at: Date.now(), frac: job.frac, msg: job.message };
    }
  }, [job.elapsed, job.frac, job.message]);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const elapsed = base.current.elapsed + (now - base.current.at) / 1000;
  const frac = Math.max(0.02, Math.min(1, job.frac || 0));
  const stalled = now - lastChange.current.at > 4000;
  const steps = job.steps ?? [];
  const title = TITLE[job.kind] ?? "Working";
  const detail = words(job.stage, job.message);
  const left = eta(elapsed, frac);

  const stop = async () => {
    setStopping(true);
    try {
      await stopJob(job);
      onStopped?.();
    } catch {
      setStopping(false);
    }
  };

  if (compact) {
    return (
      <div className="col" style={{ gap: 6 }}>
        <div className="row small nowrap">
          <span className="spinner" />
          <span className="ellipsis grow">{detail}</span>
          <span className="dim tiny">{Math.round(frac * 100)}%</span>
        </div>
        <div className={`progress${stalled ? " stalled" : ""}`}><div style={{ width: `${frac * 100}%` }} /></div>
      </div>
    );
  }
  return (
    <div className="task" role="status" aria-live="polite">
      <div className="row nowrap" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div className="col" style={{ gap: 2, minWidth: 0 }}>
          <div className="title"><span className="dot live" /> {title}</div>
          <div className="detail ellipsis">{detail}</div>
        </div>
        <div className="row nowrap" style={{ gap: 14 }}>
          <span className="pct">{Math.round(frac * 100)}%</span>
          {job.status === "running" && (
            <button className="btn small" onClick={stop} disabled={stopping} title="Stop this task">
              <Icon name="stop" size={14} /> {stopping ? "Stopping…" : "Stop"}
            </button>
          )}
        </div>
      </div>
      {steps.length > 0 && (
        <div className="steps">
          {steps.map((s, i) => {
            const st = i < (job.step ?? 0) ? "done" : i === (job.step ?? 0) ? "now" : "";
            return (
              <div key={s.id} className={`stp ${st}`}>
                <span className="b">{st === "done" ? <Icon name="check" size={12} /> : st === "now" ? null : i + 1}</span>
                {s.label}
              </div>
            );
          })}
        </div>
      )}
      <div className={`progress${stalled ? " stalled" : ""}`} style={{ marginTop: steps.length ? 0 : 14 }}>
        <div style={{ width: `${frac * 100}%` }} />
      </div>
      <div className="row meta" style={{ marginTop: 10, justifyContent: "space-between" }}>
        <span>{stalled ? "Still working — this part takes a moment" : STAGE[job.stage] ?? job.stage}</span>
        <span>
          {clock(elapsed)} elapsed{left ? ` · ${left}` : ""}
        </span>
      </div>
    </div>
  );
}
