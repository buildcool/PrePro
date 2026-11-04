import { useEffect, useState } from "react";
import { api } from "../api";
import { go, useToast } from "../App";
import type { ProjectRow } from "../types";

export default function Home() {
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const { say } = useToast();

  const load = () => api<ProjectRow[]>("/projects").then(setRows).catch((e) => say(e.message, "error"));
  useEffect(() => {
    load();
  }, []);

  const open = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try {
      const p = await api<ProjectRow>("/projects", { body: { path: path.trim() } });
      go({ page: "project", pid: p.id, tab: "footage" });
    } catch (e: any) {
      say(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="card">
        <h1>Open a shoot</h1>
        <p className="mute" style={{ marginTop: -6 }}>
          Point PrePro at the folder with your clips (and optionally music/, memes/, sfx/, a brief.md). Everything is analysed on this computer —
          your footage is never uploaded.
        </p>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input
            type="text"
            placeholder="/home/you/Videos/Goa trip  or  D:\Shoots\Goa"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && open()}
            aria-label="Shoot folder path"
          />
          {window.prepro?.pickFolder && (
            <button className="btn" onClick={async () => {
              const p = await window.prepro!.pickFolder();
              if (p) setPath(p);
            }}>Browse…</button>
          )}
          <button className="btn primary" onClick={open} disabled={busy || !path.trim()}>
            Open
          </button>
        </div>
      </div>
      <div>
        <h3>Recent shoots</h3>
        {rows === null ? (
          <p className="mute">Loading…</p>
        ) : rows.length === 0 ? (
          <div className="card empty-state">No shoots yet — open a folder above.</div>
        ) : (
          <div className="grid projects">
            {rows.map((r) => (
              <div key={r.id} className="card" style={{ cursor: r.exists ? "pointer" : "default", opacity: r.exists ? 1 : 0.6 }}
                onClick={() => r.exists && go({ page: "project", pid: r.id, tab: r.timelines ? "review" : "footage" })}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <b>{r.name}</b>
                  <button className="btn small ghost" title="Remove from this list (files stay)"
                    onClick={async (e) => {
                      e.stopPropagation();
                      await api(`/projects/${r.id}`, { method: "DELETE" });
                      load();
                    }}>
                    ✕
                  </button>
                </div>
                <div className="small dim" style={{ wordBreak: "break-all" }}>{r.path}</div>
                <div className="row" style={{ marginTop: 8 }}>
                  {!r.exists && <span className="chip bad">folder missing</span>}
                  <span className={`chip ${r.analysed ? "ok" : ""}`}>{r.analysed ? "analysed" : "not analysed"}</span>
                  {r.timelines > 0 && <span className="chip">{r.timelines} cut{r.timelines > 1 ? "s" : ""}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
