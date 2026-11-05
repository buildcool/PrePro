// Light / dark / system. Stored per computer; "system" follows the OS live.
export type ThemeMode = "system" | "light" | "dark";
const KEY = "prepro-theme";

export function getTheme(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(mode: ThemeMode = getTheme()): void {
  const root = document.documentElement;
  if (mode === "system") delete root.dataset.theme;
  else root.dataset.theme = mode;
  window.prepro?.setTheme?.(mode); // the desktop window's own chrome follows too
}

export function setTheme(mode: ThemeMode): void {
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    /* private mode: this session only */
  }
  applyTheme(mode);
}

/** The theme actually showing now (system resolved). */
export function effectiveTheme(): "light" | "dark" {
  const m = getTheme();
  if (m !== "system") return m;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
