// Launch the real desktop app (Electron + frozen engine) and check the security bridge + that a shoot opens.
// usage: node electron_smoke.js <electron-binary> <desktop-dir> <work-dir> <shoot-dir>
const { _electron: electron } = require("playwright");
const [electronBin, desktopDir, work, shoot] = process.argv.slice(2);
(async () => {
  const app = await electron.launch({
    executablePath: electronBin,
    args: [desktopDir, "--no-sandbox"],
    env: { ...process.env, PREPRO_DATA_DIR: work + "/data", PREPRO_CONFIG_DIR: work + "/data" },
  });
  const win = await app.firstWindow();
  await win.waitForSelector("text=Open a shoot", { timeout: 180000 });
  const bridge = await win.evaluate(() => !!(window.prepro && window.prepro.isDesktop && typeof window.prepro.pickFolder === "function"));
  const nodeInPage = await win.evaluate(() => typeof require !== "undefined" || typeof process !== "undefined");
  const local = /^http:\/\/127\.0\.0\.1:\d+\/$/.test(win.url());
  await win.fill('input[aria-label="Shoot folder path"]', shoot);
  await win.click('button:has-text("Open")');
  await win.waitForSelector(".asset, button:has-text(\"Analyse footage\")", { timeout: 300000 });
  await win.screenshot({ path: work + "/desktop.png" });
  await app.close();
  console.log(JSON.stringify({ bridge, nodeInPage, local }));
})().catch((e) => {
  console.error("FAILED", e);
  process.exit(1);
});
