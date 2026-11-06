import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { LogoTile } from "./components/BrandLogo";
import Icon from "./components/Icon";
import Home from "./pages/Home";
import Project from "./pages/Project";
import Settings from "./pages/Settings";
import { UpdatePill } from "./pages/Updates";
import { getTheme, setTheme, type ThemeMode } from "./theme";
import type { AIOverview } from "./types";

export type Route =
  | { page: "home" }
  | { page: "project"; pid: string; tab: string; tid?: string }
  | { page: "settings"; section: string };

function parse(hash: string): Route {
  const p = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (p[0] === "p" && p[1]) return { page: "project", pid: p[1], tab: p[2] || "footage", tid: p[3] };
  if (p[0] === "settings") return { page: "settings", section: p[1] || "general" };
  return { page: "home" };
}

export const go = (r: Route) => {
  window.location.hash =
    r.page === "home" ? "#/" : r.page === "settings" ? `#/settings/${r.section}` : `#/p/${r.pid}/${r.tab}${r.tid ? "/" + r.tid : ""}`;
};

interface ToastCtx {
  say: (msg: string, kind?: "info" | "error") => void;
}
const Ctx = createContext<ToastCtx>({ say: () => {} });
export const useToast = () => useContext(Ctx);

const THEME_NEXT: Record<ThemeMode, ThemeMode> = { system: "light", light: "dark", dark: "system" };
const THEME_ICON: Record<ThemeMode, string> = { system: "monitor", light: "sun", dark: "moon" };
const THEME_LABEL: Record<ThemeMode, string> = { system: "Theme: match my computer", light: "Theme: light", dark: "Theme: dark" };

/** Who edits right now, as the sidebar shows it. */
function AIChip({ ai }: { ai: AIOverview | null }) {
  const id = ai?.editor ?? "basic";
  const plan = ai?.plans.find((p) => p.id === id);
  const key = ai?.keys.find((k) => k.id === id);
  const local = ai?.local.find((l) => l.id === id);
  const name = id === "basic" ? "Rules engine" : plan?.name ?? key?.name ?? local?.name ?? id;
  const test = plan?.test ?? key?.test ?? local?.test ?? null;
  const tone = id === "basic" ? "" : test ? (test.ok ? "ok" : "bad") : "warn";
  return (
    <button className="ai-chip" onClick={() => go({ page: "settings", section: "ai" })} title={`AI editor: ${name} — open settings`}>
      <LogoTile id={id} />
      <span className="txt col grow" style={{ gap: 0 }}>
        <span className="who ellipsis">{name}</span>
        <span className="what">{id === "basic" ? "No AI connected · connect one" : plan ? "Your plan" : key ? "Your API key" : "On this PC"}</span>
      </span>
      <span className={`dot ${tone}`} />
    </button>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(parse(window.location.hash));
  const [toast, setToast] = useState<{ msg: string; kind: string } | null>(null);
  const [title, setTitle] = useState<string>("");
  const [health, setHealth] = useState<{ version: string; ffmpeg: boolean } | null>(null);
  const [ai, setAi] = useState<AIOverview | null>(null);
  const [theme, setT] = useState<ThemeMode>(getTheme());

  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", on);
    api<{ version: string; ffmpeg: boolean }>("/health").then(setHealth).catch(() => setHealth(null));
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    const refresh = () => api<AIOverview>("/ai").then(setAi).catch(() => setAi(null));
    refresh(); // on every page change, and the moment Settings changes the AI editor or a connection
    window.addEventListener("prepro:ai-changed", refresh);
    return () => window.removeEventListener("prepro:ai-changed", refresh);
  }, [route.page, route.page === "settings" ? route.section : ""]);

  const say = useCallback((msg: string, kind: "info" | "error" = "info") => {
    setToast({ msg, kind });
    window.clearTimeout((say as any)._t);
    (say as any)._t = window.setTimeout(() => setToast(null), kind === "error" ? 9000 : 5000);
  }, []);
  const cycleTheme = () => {
    const n = THEME_NEXT[theme];
    setTheme(n);
    setT(n);
  };

  return (
    <Ctx.Provider value={{ say }}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand" onClick={() => go({ page: "home" })} title="All shoots">
            <span className="logo">P</span>
            <span className="col" style={{ gap: 0 }}>
              <b>PrePro</b>
              {health && <span className="ver">v{health.version}</span>}
            </span>
          </div>
          <button className={`nav${route.page === "home" ? " on" : ""}`} onClick={() => go({ page: "home" })}>
            <Icon name="home" /> <span className="lbl">Shoots</span>
          </button>
          {route.page === "project" && (
            <button className="nav on" onClick={() => go({ page: "project", pid: route.pid, tab: "footage" })} title={title}>
              <Icon name="folder" /> <span className="lbl ellipsis">{title || "This shoot"}</span>
            </button>
          )}
          <div className="side-foot">
            {health && !health.ffmpeg && <span className="chip bad" style={{ alignSelf: "flex-start" }}>ffmpeg not found</span>}
            <UpdatePill onOpen={() => go({ page: "settings", section: "updates" })} />
            <AIChip ai={ai} />
            <div className="row nowrap foot-acts" style={{ gap: 4 }}>
              <button className={`nav grow${route.page === "settings" ? " on" : ""}`} onClick={() => go({ page: "settings", section: "general" })}>
                <Icon name="settings" /> <span className="lbl">Settings</span>
              </button>
              <button className="icon-btn" onClick={cycleTheme} title={THEME_LABEL[theme]} aria-label={THEME_LABEL[theme]}>
                <Icon name={THEME_ICON[theme]} />
              </button>
            </div>
          </div>
        </aside>
        <main className="main">
          {route.page === "home" && <div className="page"><Home /></div>}
          {route.page === "project" && <div className="page"><Project key={route.pid} route={route} setTitle={setTitle} /></div>}
          {route.page === "settings" && <Settings section={route.section} />}
        </main>
        {toast && (
          <div className="toast" role="status" onClick={() => setToast(null)}>
            <div className="card" style={{ borderLeftColor: toast.kind === "error" ? "var(--bad)" : undefined }}>
              {toast.msg}
            </div>
          </div>
        )}
      </div>
    </Ctx.Provider>
  );
}
