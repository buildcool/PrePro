// The only bridge between the review app and the OS: pick a folder, reveal a file, and app updates. No Node in the page.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("prepro", {
  isDesktop: true,
  pickFolder: () => ipcRenderer.invoke("prepro:pick-folder"),
  reveal: (p) => ipcRenderer.invoke("prepro:reveal", String(p)),
  updates: {
    get: () => ipcRenderer.invoke("prepro:update-get"),
    check: () => ipcRenderer.invoke("prepro:update-check"),
    setMode: (m) => ipcRenderer.invoke("prepro:update-mode", String(m)),
    download: () => ipcRenderer.invoke("prepro:update-download"),
    install: () => ipcRenderer.invoke("prepro:update-install"),
    openPage: () => ipcRenderer.invoke("prepro:update-page"),
    onChange: (cb) => {
      const h = (_e, s) => cb(s);
      ipcRenderer.on("prepro:update-state", h);
      return () => ipcRenderer.removeListener("prepro:update-state", h);
    },
  },
});
