// The only bridge between the review app and the OS: pick a folder, reveal a file. No Node in the page.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("prepro", {
  isDesktop: true,
  pickFolder: () => ipcRenderer.invoke("prepro:pick-folder"),
  reveal: (p) => ipcRenderer.invoke("prepro:reveal", String(p)),
});
