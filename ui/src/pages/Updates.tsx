import { useEffect, useState } from "react";
import Icon from "../components/Icon";
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

/** Live update state from the desktop shell (null in a browser, where there is no updater). */
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

/** The sidebar pill: shows only when there is something to do. */
export function UpdatePill({ onOpen }: { onOpen: () => void }) {
  const s = useUpdates();
  if (!s || !["available", "downloading", "ready"].includes(s.status)) return null;
  return (
    <button className="nav" onClick={() => (s.status === "ready" ? window.prepro?.updates?.install() : onOpen())} title="App update">
      <Icon name="download" />
      <span className="lbl">
        {s.status === "ready" ? "Restart to update" : s.status === "downloading" ? `Updating… ${s.progress}%` : `Update to v${s.latest}`}
      </span>
      <span className="dot live" style={{ marginLeft: "auto" }} />
    </button>
  );
}

export function UpdatesPanel() {
  const u = window.prepro?.updates;
  const s = useUpdates();
  if (!u || !s) return null;
  return (
    <>
      <div className="set-group">
        <div className="set-row">
          <div className="lbl"><b>{line(s)}</b><span>PrePro {s.current}</span></div>
          {s.status === "available" && (
            <button className="btn primary" onClick={() => u.download()}>
              <Icon name="download" size={15} /> {s.canInstall ? `Download v${s.latest}` : "Open the download page"}
            </button>
          )}
          {s.status === "ready" && <button className="btn primary" onClick={() => u.install()}>Restart to update</button>}
          {s.status !== "downloading" && s.status !== "ready" && (
            <button className="btn" disabled={s.busy} onClick={() => u.check()}><Icon name="refresh" size={15} /> Check now</button>
          )}
        </div>
        {s.status === "downloading" && (
          <div className="set-row"><div className="progress grow"><div style={{ width: `${Math.max(2, s.progress)}%` }} /></div></div>
        )}
        {s.status === "ready" && (
          <div className="set-row"><span className="small mute">Finish or stop any render first: PrePro closes, installs and opens again. Your shoots and edits stay as they are.</span></div>
        )}
        {(s.status === "available" || s.status === "downloading" || s.status === "ready") && s.notes && (
          <div className="set-row" style={{ display: "block" }}>
            <b>What's new in v{s.latest}</b>
            <div className="small mute" style={{ whiteSpace: "pre-wrap", maxHeight: 260, overflow: "auto", marginTop: 6 }}>{s.notes}</div>
          </div>
        )}
      </div>
      <h3>Check for updates</h3>
      <div className="set-group">
        <div className="set-row">
          <div className="lbl"><b>{MODE_LABEL[s.mode]}</b><span>{MODE_HELP[s.mode]}</span></div>
          <div className="seg" role="radiogroup" aria-label="Check for updates">
            {(["auto", "notify", "off"] as const).map((m) => (
              <button key={m} className={s.mode === m ? "on" : ""} onClick={() => u.setMode(m)} role="radio" aria-checked={s.mode === m}>
                {MODE_LABEL[m]}
              </button>
            ))}
          </div>
        </div>
        {!s.canInstall && (
          <div className="set-row"><span className="small mute">This copy of PrePro can't replace itself (a .deb install or a developer build), so updates come from the download page.</span></div>
        )}
        <div className="set-row">
          <span className="small mute">Checking only asks GitHub which version is the latest, so GitHub sees your IP address and PrePro version. No footage, file names or projects are sent.</span>
        </div>
      </div>
    </>
  );
}
