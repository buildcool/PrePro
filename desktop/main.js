// PrePro desktop shell: starts the local engine (frozen Python, bundled in resources/engine) on a free
// 127.0.0.1 port and shows the review app in a sandboxed window. Footage never leaves the computer.
const { app, BrowserWindow, dialog, ipcMain, shell, Menu } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");
const updates = require("./updater");

let engine = null;
let win = null;
let port = 0;
let quitting = false;
const log = [];

if (!app.requestSingleInstanceLock()) app.quit();

function engineCommand() {
  const exe = process.platform === "win32" ? "prepro-engine.exe" : "prepro-engine";
  const candidates = [
    app.isPackaged ? path.join(process.resourcesPath, "engine", exe) : null,
    process.env.PREPRO_ENGINE || null,
    path.join(__dirname, "..", "dist", "prepro-engine", exe),
  ].filter(Boolean);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return process.platform === "win32" ? "prepro.exe" : "prepro"; // a pip-installed engine on PATH
}

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
}

function healthy(p) {
  return new Promise((resolve) => {
    const req = http.get({ host: "127.0.0.1", port: p, path: "/api/health", timeout: 1000 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function startEngine() {
  port = await freePort();
  const cmd = engineCommand();
  engine = spawn(cmd, ["ui", "--no-browser", "--port", String(port)], {
    // UTF-8 output whatever the Windows code page (v0.8.0 crashed printing "→" into a cp1252 pipe)
    env: { ...process.env, PREPRO_DESKTOP: "1", PYTHONUNBUFFERED: "1", PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
    windowsHide: true,
  });
  const keep = (d) => {
    log.push(String(d));
    if (log.length > 200) log.shift();
  };
  engine.stdout.on("data", keep);
  engine.stderr.on("data", keep);
  engine.on("error", (e) => keep(`spawn error: ${e.message}`));
  engine.on("exit", (code) => {
    engine = null;
    if (!quitting) fail(`The PrePro engine stopped (exit code ${code}).`);
  });
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    if (!engine) throw new Error("engine exited during start-up");
    if (await healthy(port)) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("the engine did not start within 2 minutes");
}

function fail(msg) {
  const detail = log.join("").slice(-1800);
  if (win && !win.isDestroyed()) {
    win.webContents
      .executeJavaScript(`document.getElementById('msg') && (document.getElementById('msg').textContent = ${JSON.stringify(msg + "\n\n" + detail)})`)
      .catch(() => {});
  }
  dialog.showErrorBox("PrePro", `${msg}\n\n${detail}`);
}

function isLocal(url) {
  try {
    const u = new URL(url);
    return u.protocol === "http:" && u.hostname === "127.0.0.1" && Number(u.port) === port;
  } catch {
    return false;
  }
}

async function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 900,
    minHeight: 600,
    title: "PrePro",
    backgroundColor: "#0f1012",
    icon: path.join(__dirname, "build", "icon.png"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isLocal(url)) return { action: "allow" }; // exported reports / renders open in an app window
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!isLocal(url) && !url.startsWith("file:")) {
      e.preventDefault();
      if (/^https?:/.test(url)) shell.openExternal(url);
    }
  });
  updates.init(win);
  await win.loadFile(path.join(__dirname, "splash.html"));
  try {
    await startEngine();
    await win.loadURL(`http://127.0.0.1:${port}/`);
  } catch (e) {
    fail(`Could not start PrePro: ${e.message}`);
  }
}

ipcMain.handle("prepro:pick-folder", async () => {
  const r = await dialog.showOpenDialog(win, { title: "Choose your shoot folder", properties: ["openDirectory"] });
  return r.canceled || !r.filePaths.length ? null : r.filePaths[0];
});
ipcMain.handle("prepro:reveal", async (_e, p) => {
  if (p && fs.existsSync(p)) shell.showItemInFolder(p);
});

app.on("second-instance", () => {
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});
app.whenReady().then(() => {
  if (process.platform !== "darwin") Menu.setApplicationMenu(null);
  createWindow();
});
app.on("before-quit", () => {
  quitting = true;
  if (engine) engine.kill();
});
app.on("window-all-closed", () => app.quit());
