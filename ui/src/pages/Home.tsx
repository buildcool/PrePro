import { useEffect, useState } from "react";
import { api, frameUrl } from "../api";
import { go, useToast } from "../App";
import Icon from "../components/Icon";
import type { GeneralSettings, ProjectRow } from "../types";

function ago(t?: number): string {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export default function Home() {
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(true);
  const { say } = useToast();

  const load = () => api<ProjectRow[]>("/projects").then(setRows).catch((e) => say(e.message, "error"));
  useEffect(() => {
    load();
    api<GeneralSettings>("/settings").then((g) => setAuto(g.autocut_on_open)).catch(() => {});
  }, []);

  const open = async (p = path) => {
    if (!p.trim()) return;
    setBusy(true);
    try {
      const row = await api<ProjectRow>("/projects", { body: { path: p.trim() } });
      if (auto) await api(`/projects/${row.id}/autocut`, { body: {} }); // the autonomous pre-edit starts right away
      go({ page: "project", pid: row.id, tab: "footage" });
    } catch (e: any) {
      say(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const browse = async () => {
    const p = await window.prepro?.pickFolder();
    if (p) {
      setPath(p);
      open(p);
    }
  };

  return (
    <div className="col" style={{ gap: 26 }}>
      <section className="hero">
        <span className="chip soft" style={{ marginBottom: 12 }}><Icon name="sparkles" size={13} /> Autonomous pre-editor</span>
        <h1>Your shoot in. A finished first cut out.</h1>
        <p className="lead">
          Point PrePro at the folder from your shoot. It watches every clip, finds the story, edits, renders and gets the exports ready —
          about 90 % of the edit. You refine the rest.
        </p>
        <div className="drop">
          <input type="text" placeholder="Paste your shoot folder, e.g. D:\Shoots\Goa trip" value={path} onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && open()} aria-label="Shoot folder path" />
          {window.prepro?.pickFolder && (
            <button className="btn big" onClick={browse} disabled={busy}><Icon name="folder" /> Choose folder…</button>
          )}
          <button className="btn primary big" onClick={() => open()} disabled={busy || !path.trim()}>
            {busy ? <span className="spinner" /> : <Icon name="sparkles" />} {auto ? "Make my first cut" : "Open shoot"}
          </button>
        </div>
        <div className="promise">
          <span><Icon name="lock" size={14} /> Footage never leaves this PC</span>
          <span><Icon name="check" size={14} /> Every edit explained — and undoable</span>
          <span><Icon name="export" size={14} /> Exports for Premiere, Resolve and Final Cut</span>
        </div>
      </section>

      <section>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Recent shoots</h2>
          {rows && rows.length > 0 && <span className="small dim">{rows.length} shoot{rows.length > 1 ? "s" : ""}</span>}
        </div>
        {rows === null ? (
          <div className="grid projects">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 210 }} />)}</div>
        ) : rows.length === 0 ? (
          <div className="card empty-state">
            <div className="big"><Icon name="film" size={40} /></div>
            <b>No shoots yet</b>
            <div className="small">Open a folder above — PrePro makes the first cut while you get a coffee.</div>
          </div>
        ) : (
          <div className="grid projects">
            {rows.map((r) => (
              <div key={r.id} className={`card proj${r.exists ? " click" : ""}`} style={{ opacity: r.exists ? 1 : 0.6 }}
                onClick={() => r.exists && go({ page: "project", pid: r.id, tab: r.timelines ? "review" : "footage" })}>
                <div className="cover" style={{ backgroundImage: r.cover ? `url(${frameUrl(r.id, r.cover)})` : undefined }}>
                  {!r.cover && <div style={{ height: "100%", display: "grid", placeItems: "center", color: "var(--dim)" }}><Icon name="film" size={30} /></div>}
                  <span className="badge">
                    {r.busy ? <span className="chip acc"><span className="spinner" style={{ width: 10, height: 10, borderWidth: 2 }} /> working</span>
                      : r.timelines > 0 ? <span className="chip ok"><Icon name="check" size={12} /> {r.timelines} cut{r.timelines > 1 ? "s" : ""}</span>
                      : <span className="chip">{r.analysed ? "analysed" : "not cut yet"}</span>}
                  </span>
                </div>
                <div className="row nowrap" style={{ justifyContent: "space-between" }}>
                  <b className="ellipsis">{r.name}</b>
                  <button className="icon-btn" title="Remove from this list (files stay)" aria-label="Remove from list"
                    onClick={async (e) => {
                      e.stopPropagation();
                      await api(`/projects/${r.id}`, { method: "DELETE" });
                      load();
                    }}>
                    <Icon name="x" size={15} />
                  </button>
                </div>
                <div className="tiny dim ellipsis" title={r.path}>{r.path}</div>
                <div className="row tiny dim" style={{ marginTop: 6 }}>
                  {!r.exists && <span className="chip bad">folder missing</span>}
                  {r.opened && <span>Opened {ago(r.opened)}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
