import { useEffect, useState } from "react";
import { api, followJob, type Job } from "../api";
import { useToast } from "../App";
import type { Brains as B, SpeechModels } from "../types";

const PASSES: [string, string][] = [
  ["director", "Directions, hooks, what's missing"],
  ["story", "Story order"],
  ["polish", "Music, memes, SFX, text"],
  ["critic", "Senior-editor review"],
  ["vision", "Shot tags from thumbnails"],
  ["brief", "Reading your brief"],
  ["revise", "Your timeline notes"],
];

export default function Brains({ onClose }: { onClose: () => void }) {
  const [b, setB] = useState<B | null>(null);
  const [sm, setSm] = useState<SpeechModels | null>(null);
  const [dl, setDl] = useState<Job | null>(null);
  const { say } = useToast();
  useEffect(() => {
    api<B>("/brains").then(setB).catch((e) => say(e.message, "error"));
    api<SpeechModels>("/models").then(setSm).catch(() => setSm(null));
  }, []);
  const download = async (name: string) => {
    try {
      const j = await api<Job>(`/models/${name}/download`, { body: {} });
      setDl(j);
      await followJob(j, setDl);
      say(`The ${name} speech model is ready — analyse again for better captions.`);
    } catch (e: any) {
      say(`Download failed: ${e.message}`, "error");
    } finally {
      setDl(null);
      setSm(await api<SpeechModels>("/models"));
    }
  };
  const save = async (patch: Partial<B>) => {
    try {
      setB(await api<B>("/brains", { method: "PUT", body: patch }));
    } catch (e: any) {
      say(e.message, "error");
    }
  };
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="card modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Brains and privacy">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Brains &amp; privacy</h2>
          <button className="btn small ghost" onClick={onClose}>✕</button>
        </div>
        {!b ? (
          <p className="mute">Loading…</p>
        ) : (
          <>
            <h3>What leaves this computer</h3>
            <div className="seg3" role="radiogroup">
              {(["local", "text", "thumbs"] as const).map((p) => (
                <button key={p} className={b.privacy === p ? "on" : ""} onClick={() => save({ privacy: p })}>
                  {p === "local" ? "Nothing (local only)" : p === "text" ? "Text only" : "Text + small thumbnails"}
                </button>
              ))}
            </div>
            <p className="small mute">
              Raw videos, photos and audio never leave this PC in any mode. File names and GPS are never sent. Everything sent is logged in
              <code> .prepro/sent/ </code> inside the shoot folder.
            </p>
            <h3>Speech recognition (on this computer)</h3>
            {!sm ? <p className="small mute">Checking…</p> : !sm.installed ? (
              <p className="small mute">Speech recognition isn't installed in this build — only the basic offline recogniser is available.</p>
            ) : (
              <div className="col">
                {sm.models.map((m) => (
                  <div key={m.name} className="row small" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                    <label className="row" style={{ flexWrap: "nowrap" }}>
                      <input type="radio" name="asr" checked={m.current} disabled={!m.cached}
                        onChange={async () => setSm(await api<SpeechModels>("/models", { method: "PUT", body: { model: m.name } }))} />
                      <span><b>{m.name}</b> <span className="dim">· {m.note}</span></span>
                    </label>
                    {m.cached ? <span className="chip ok">on this PC</span> : (
                      <button className="btn small" disabled={!!dl} onClick={() => download(m.name)}>Download {m.size_mb >= 1000 ? `${(m.size_mb / 1000).toFixed(1)} GB` : `${m.size_mb} MB`}</button>
                    )}
                  </div>
                ))}
                {dl && (
                  <div className="col" style={{ gap: 4 }}>
                    <div className="small mute">{dl.message || "Starting download…"}</div>
                    <div className="progress"><div style={{ width: `${Math.round((dl.frac || 0.02) * 100)}%` }} /></div>
                  </div>
                )}
                <p className="small dim">Without a downloaded model PrePro uses a basic offline recogniser (English only, rough words). The download comes from huggingface.co once; your audio never leaves this computer.</p>
              </div>
            )}
            <h3>Connected brains</h3>
            {b.connectors.length === 0 ? (
              <p className="small mute">
                None found. PrePro works without AI (rules engine). To use a plan you already pay for, install and sign in to Claude Code or the
                Codex CLI, or add a key with <code>prepro brains key</code>.
              </p>
            ) : (
              <div className="col">
                {b.connectors.map((c) => (
                  <div key={c.name} className="hook">
                    <div className="row">
                      <b>{c.name}</b> <span className="chip">{c.kind}</span> {c.detected && <span className="chip ok">found on this PC</span>}
                      {c.local && <span className="chip ok">local</span>}
                    </div>
                    <div className="small mute">{c.training}</div>
                  </div>
                ))}
              </div>
            )}
            <h3>Who does what</h3>
            {PASSES.map(([k, label]) => (
              <div key={k} className="knob">
                <span className="small">{label}</span>
                <select value={b.routing[k] ?? "basic"} onChange={(e) => save({ routing: { ...b.routing, [k]: e.target.value } })}>
                  <option value="basic">Rules engine (free, offline)</option>
                  {b.connectors.map((c) => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
