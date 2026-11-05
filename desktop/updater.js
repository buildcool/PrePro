// Updates from PrePro's GitHub Releases. The only thing sent is the request for the latest release (GitHub sees the
// app's version and your IP address): never footage, file names or projects.
//   auto   — check on start and once a day, download in the background, ask "Restart to update" (never restarts by itself)
//   notify — check the same way, show what's new; downloading and installing are your call
//   off    — PrePro never asks the internet about updates (you can still check by hand)
// The Windows installer and the Linux AppImage can update themselves; a .deb (or a dev run) can only point to the
// download page.
const { app, ipcMain, shell } = require("electron");
const fs = require("fs");
const https = require("https");
const path = require("path");

const OWNER = "buildcool";
const REPO = "PrePro";
const PAGE = `https://github.com/${OWNER}/${REPO}/releases/latest`;
const DAY = 24 * 60 * 60 * 1000;
const MODES = ["auto", "notify", "off"];

let win = null;
let updater = null; // electron-updater, only where it can install
let timer = null;
const state = {
  current: app.getVersion(),
  mode: "notify",
  status: "idle", // idle | checking | latest | available | downloading | ready | error
  latest: null,
  notes: "",
  page: PAGE,
  progress: 0,
  error: null,
  checkedAt: null,
  canInstall: false,
  busy: false,
};

const settingsFile = () => path.join(app.getPath("userData"), "updates.json");

function load() {
  try {
    const s = JSON.parse(fs.readFileSync(settingsFile(), "utf8"));
    if (MODES.includes(s.mode)) state.mode = s.mode;
    if (s.checkedAt) state.checkedAt = s.checkedAt;
  } catch {
    /* first run: notify */
  }
}

function save() {
  try {
    fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
    fs.writeFileSync(settingsFile(), JSON.stringify({ mode: state.mode, checkedAt: state.checkedAt }, null, 1));
  } catch {
    /* read-only profile: the setting lasts this session */
  }
}

function push(patch = {}) {
  Object.assign(state, patch);
  if (win && !win.isDestroyed()) win.webContents.send("prepro:update-state", { ...state });
}

function newer(a, b) {
  // true when version a is newer than b ("0.10.0" > "0.9.0")
  const pa = String(a).replace(/^v/, "").split(/[.-]/).map((x) => parseInt(x, 10) || 0);
  const pb = String(b).replace(/^v/, "").split(/[.-]/).map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  }
  return false;
}

function plain(notes) {
  // release notes as plain text: electron-updater hands over HTML, the API markdown
  if (Array.isArray(notes)) notes = notes.map((n) => n.note || "").join("\n\n");
  return String(notes || "")
    .replace(/<\/(p|li|h\d)>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .trim()
    .slice(0, 4000);
}

function latestFromApi() {
  // the latest release, straight from GitHub's API (builds that can't install themselves only need to know)
  return new Promise((resolve, reject) => {
    const req = https.get(
      { host: "api.github.com", path: `/repos/${OWNER}/${REPO}/releases/latest`, headers: { "User-Agent": `PrePro/${state.current}`, Accept: "application/vnd.github+json" }, timeout: 15000 },
      (res) => {
        let body = "";
        res.on("data", (d) => (body += d));
        res.on("end", () => {
          if (res.statusCode !== 200) return reject(new Error(`GitHub answered ${res.statusCode}`));
          try {
            const r = JSON.parse(body);
            resolve({ version: String(r.tag_name || "").replace(/^v/, ""), notes: r.body || "", page: r.html_url || PAGE });
          } catch (e) {
            reject(e);
          }
        });
      },
    );
    req.on("timeout", () => req.destroy(new Error("no answer from GitHub")));
    req.on("error", reject);
  });
}

function setupUpdater() {
  // only the Windows installer and the AppImage can replace themselves
  const installable = app.isPackaged && (process.platform === "win32" || !!process.env.APPIMAGE);
  if (!installable) return;
  try {
    ({ autoUpdater: updater } = require("electron-updater"));
  } catch {
    updater = null;
    return;
  }
  state.canInstall = true;
  updater.autoDownload = false; // decided per check from the mode
  updater.autoInstallOnAppQuit = true; // a downloaded update goes in the next time you close PrePro
  updater.logger = null;
  updater.on("update-available", (i) => push({ status: "available", latest: i.version, notes: plain(i.releaseNotes) }));
  updater.on("update-not-available", () => push({ status: "latest", latest: state.current }));
  updater.on("download-progress", (p) => push({ status: "downloading", progress: Math.round(p.percent || 0) }));
  updater.on("update-downloaded", (i) => push({ status: "ready", latest: i.version, progress: 100 }));
  updater.on("error", (e) => push({ status: "error", error: friendly(e), busy: false }));
}

function friendly(e) {
  const m = String((e && e.message) || e || "");
  if (/ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ETIMEDOUT|no answer|net::/i.test(m)) return "No internet connection — try again later.";
  if (/404|latest\.yml|latest-linux\.yml/i.test(m)) return "The latest release has no update file for this build yet — download it from the releases page.";
  return m.split("\n")[0].slice(0, 200);
}

async function check({ manual = false } = {}) {
  if (state.busy || state.status === "downloading" || state.status === "ready") return { ...state };
  if (state.mode === "off" && !manual) return { ...state };
  push({ status: "checking", error: null, busy: true });
  try {
    if (updater) {
      updater.autoDownload = state.mode === "auto";
      await updater.checkForUpdates();
      if (state.status === "checking") push({ status: "latest", latest: state.current });
    } else {
      const r = await latestFromApi();
      push(newer(r.version, state.current) ? { status: "available", latest: r.version, notes: plain(r.notes), page: r.page } : { status: "latest", latest: r.version });
    }
  } catch (e) {
    push({ status: "error", error: friendly(e) });
  }
  state.checkedAt = new Date().toISOString();
  save();
  push({ busy: false });
  return { ...state };
}

function schedule() {
  clearTimeout(timer);
  if (state.mode === "off") return;
  const last = state.checkedAt ? Date.parse(state.checkedAt) : 0;
  const wait = Math.max(15000, last + DAY - Date.now()); // not in the first seconds of start-up, then once a day
  timer = setTimeout(async () => {
    await check();
    schedule();
  }, Math.min(wait, DAY));
}

function init(window) {
  win = window;
  load();
  setupUpdater();
  ipcMain.handle("prepro:update-get", () => ({ ...state }));
  ipcMain.handle("prepro:update-check", () => check({ manual: true }));
  ipcMain.handle("prepro:update-mode", (_e, mode) => {
    if (MODES.includes(mode)) {
      state.mode = mode;
      save();
      push();
      schedule();
      if (mode === "auto" && updater && state.status === "available") updater.downloadUpdate().catch((e) => push({ status: "error", error: friendly(e) }));
    }
    return { ...state };
  });
  ipcMain.handle("prepro:update-download", async () => {
    if (!updater) {
      shell.openExternal(state.page);
      return { ...state };
    }
    if (state.status !== "available") return { ...state };
    push({ status: "downloading", progress: 0 });
    updater.downloadUpdate().catch((e) => push({ status: "error", error: friendly(e) }));
    return { ...state };
  });
  ipcMain.handle("prepro:update-install", () => {
    // only on your click: PrePro closes (the engine with it), installs, and opens again
    if (updater && state.status === "ready") setImmediate(() => updater.quitAndInstall(true, true));
  });
  ipcMain.handle("prepro:update-page", () => shell.openExternal(state.page));
  schedule();
}

module.exports = { init, newer, plain };
