import { useState } from "react";
import { mediaUrl } from "../api";

const FORMATS: [string, string, string][] = [
  ["fcp7", "Premiere Pro / DaVinci Resolve", "XML with bins, punch-ins, speed, ducking and a marker with the reason for every decision"],
  ["kdenlive", "Kdenlive", ".kdenlive + .otio"],
  ["otio", "OpenTimelineIO", "for any OTIO-aware editor"],
  ["mlt", "Shotcut", "MLT project"],
  ["phone", "Phone apps (InShot, VN, KineMaster, Edits)", "captioned + clean + no-music MP4s, stems, cue sheet, beat plan — takes a few minutes"],
  ["srt", "Captions", "SRT + VTT"],
  ["overlay", "Caption overlay", "transparent ProRes 4444 to drop on top of any timeline"],
  ["report", "Editor brief", "one HTML page with every decision and what's missing"],
];

export default function Export({ pid, tid, run, busy }: { pid: string; tid: string; run: (p: string, b: unknown, l: string) => Promise<any>; busy: boolean }) {
  const [pick, setPick] = useState<Record<string, boolean>>({ fcp7: true, kdenlive: true, otio: false, mlt: true, phone: false, srt: true, overlay: true, report: true });
  const [res, setRes] = useState<{ folder: string; files: Record<string, string> } | null>(null);
  const go = async () => {
    const formats = Object.entries(pick).filter(([, on]) => on).map(([k]) => k);
    if (formats.includes("kdenlive") && !formats.includes("otio")) formats.push("otio");
    const r = await run(`/projects/${pid}/timelines/${tid}/export`, { formats }, "Export");
    if (r) setRes(r);
  };
  return (
    <div className="review" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(280px, 420px)" }}>
      <div className="card">
        <h2>Export this cut</h2>
        <div className="checks">
          {FORMATS.map(([k, name, desc]) => (
            <label key={k}>
              <input type="checkbox" checked={!!pick[k]} onChange={(e) => setPick({ ...pick, [k]: e.target.checked })} />
              <span><b>{name}</b><br /><span className="small mute">{desc}</span></span>
            </label>
          ))}
        </div>
        <button className="btn primary" style={{ marginTop: 12 }} disabled={busy} onClick={go}>Export</button>
      </div>
      <div className="card">
        <h2>Files</h2>
        {!res ? <p className="small mute">Exports go to <code>PrePro_exports/{tid}</code> inside your shoot folder.</p> : (
          <div className="col small">
            <div className="dim" style={{ wordBreak: "break-all" }}>{res.folder}</div>
            {window.prepro?.reveal && (
              <button className="btn small" style={{ alignSelf: "flex-start" }} onClick={() => window.prepro!.reveal(res.folder)}>Show in folder</button>
            )}
            {Object.entries(res.files).map(([k, rel]) => (
              <div key={k} className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                <span><span className="chip">{k}</span> <code>{rel.split("/").pop()}</code></span>
                {!rel.endsWith("stems") && <a href={mediaUrl(pid, rel)} target="_blank" rel="noreferrer">open</a>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
