import { useEffect, useState } from "react";
import type { UpdateState } from "../desktop";

const MODE_LABEL: Record<UpdateState["mode"], string> = { auto: "Automatic", notify: "Tell me", off: "Off" };
const MODE_HELP: Record<UpdateState["mode"], string> = {
  auto: "Checks once a day and downloads new versions in the background. It installs only when you click “Restart to update” or next close PrePro.",
  notify: "Checks once a day and tells you when a new version is out. Downloading and installing are your call.",
  off: "PrePro never asks the internet about updates. You can still check by hand here.",
};

function line(s: UpdateState): string {
  switch (s.status) {
    case "checking":
      return "Checking for a new version…";
    case "latest":
      return `You have the latest version (v${s.current}).`;
    case "available":
      return `PrePro v${s.latest} is out — you have v${s.current}.`;
    case "downloading":
      return `Downloading v${s.latest}… ${s.progress}%`;
    case "ready":
      return `v${s.latest} is downloaded and ready to install.`;
    case "error":
      return `Couldn't check: ${s.error}`;
    default:
      return s.checkedAt ? `Last checked ${new Date(s.checkedAt).toLocaleString()}.` : "Not checked yet.";
  }
}

/** The topbar button: your version, with a dot when a new one is out or ready. */
export function UpdatesButton({ onOpen }: { onOpen: () => void }) {
  const s = useUpdates();
  if (!s) return null;
  const news = s.status === "available" || s.status === "ready";
  return (
    <button className={`btn small${news ? " primary" : ""}`} onClick={onOpen} title="App updates">
      {s.status === "ready" ? "Restart to update" : s.status === "downloading" ? `Downloading v${s.latest}… ${s.progress}%` : news ? `Update: v${s.latest}` : "Updates"}
    </button>
  );
}

export function useUpdates(): UpdateState | null {
  const u = window.prepro?.updates;
  const [s, setS] = useState<UpdateState | null>(null);
  useEffect(() => {
    if (!u) return;
    u.get().then(setS).catch(() => setS(null));
    return u.onChange(setS);
  }, []);
  return u ? s : null;
}

export default function Updates({ onClose }: { onClose: () => void }) {
  const u = window.prepro?.updates;
  const s = useUpdates();
  if (!u || !s) return null;
  const set = (m: UpdateState["mode"]) => u.setMode(m);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="card modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Updates">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Updates</h2>
          <button className="btn small ghost" onClick={onClose}>✕</button>
        </div>
        <p>
          <b>{line(s)}</b>
        </p>
        <div className="row">
          {s.status === "available" && (
            <button className="btn primary" onClick={() => u.download()}>
              {s.canInstall ? `Download v${s.latest}` : "Open the download page"}
            </button>
          )}
          {s.status === "ready" && (
            <button className="btn primary" onClick={() => u.install()}>
              Restart to update
            </button>
          )}
          {s.status !== "downloading" && s.status !== "ready" && (
            <button className="btn" disabled={s.busy} onClick={() => u.check()}>
              Check now
            </button>
          )}
          {s.status === "downloading" && <progress max={100} value={s.progress} style={{ width: 220 }} />}
        </div>
        {s.status === "ready" && (
          <p className="small mute">Finish or stop any render first: PrePro closes, installs and opens again. Your shoots and edits stay as they are.</p>
        )}
        {(s.status === "available" || s.status === "downloading" || s.status === "ready") && s.notes && (
          <>
            <h3>What's new in v{s.latest}</h3>
            <div className="small" style={{ whiteSpace: "pre-wrap", maxHeight: 260, overflow: "auto" }}>{s.notes}</div>
          </>
        )}
        <h3>Check for updates</h3>
        <div className="seg3" role="radiogroup">
          {(["auto", "notify", "off"] as const).map((m) => (
            <button key={m} className={s.mode === m ? "on" : ""} onClick={() => set(m)} role="radio" aria-checked={s.mode === m}>
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
        <p className="small mute">{MODE_HELP[s.mode]}</p>
        {!s.canInstall && (
          <p className="small mute">
            This copy of PrePro can't replace itself (a .deb install or a developer build), so updates come from the download page.
          </p>
        )}
        <p className="small mute">
          Checking only asks GitHub which version is the latest, so GitHub sees your IP address and PrePro version. No footage, file names or
          projects are sent.
        </p>
      </div>
    </div>
  );
}
