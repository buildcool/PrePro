// Unit check of desktop/updater.js without Electron: version order, release notes as plain text, the settings file,
// and that a build that can't install itself only points to the download page. Run: node tests/desktop/updater_check.js
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "prepro-upd-"));
const handlers = {};
const opened = [];
const fake = {
  app: { getVersion: () => "0.9.0", getPath: () => tmp, isPackaged: false },
  ipcMain: { handle: (name, fn) => (handlers[name] = fn) },
  shell: { openExternal: (u) => opened.push(u) },
};
const load = Module._load;
Module._load = function (req, ...rest) {
  return req === "electron" ? fake : load.call(this, req, ...rest);
};
const u = require(path.join(__dirname, "..", "..", "desktop", "updater.js"));

assert.ok(u.newer("0.10.0", "0.9.0"), "0.10 is newer than 0.9 (not a string compare)");
assert.ok(u.newer("v1.0.0", "0.9.9"));
assert.ok(!u.newer("0.9.0", "0.9.0") && !u.newer("0.8.5", "0.9.0"));
assert.strictEqual(u.plain("<h2>Photo reels</h2><p>Cut on the <b>beat</b> &amp; more</p>"), "Photo reels\nCut on the beat & more");

(async () => {
  u.init({ isDestroyed: () => false, webContents: { send: () => {} } });
  let s = await handlers["prepro:update-get"]();
  assert.strictEqual(s.mode, "notify", "nothing downloads until you choose to");
  assert.strictEqual(s.canInstall, false, "a dev run / .deb can't replace itself");
  s = await handlers["prepro:update-mode"](null, "off");
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(tmp, "updates.json"), "utf8")).mode, "off");
  await handlers["prepro:update-mode"](null, "nonsense");
  assert.strictEqual((await handlers["prepro:update-get"]()).mode, "off", "unknown modes are ignored");
  await handlers["prepro:update-download"]();
  assert.ok(opened[0] && opened[0].startsWith("https://github.com/buildcool/PrePro/releases"), "no installer here: the page opens");
  console.log("updater ok");
  process.exit(0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
