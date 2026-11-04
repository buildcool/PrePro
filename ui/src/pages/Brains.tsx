import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../App";
import type { Brains as B } from "../types";

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
  const { say } = useToast();
  useEffect(() => {
    api<B>("/brains").then(setB).catch((e) => say(e.message, "error"));
  }, []);
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
