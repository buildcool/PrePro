import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import Brains from "./pages/Brains";
import Home from "./pages/Home";
import Project from "./pages/Project";

export type Route = { page: "home" } | { page: "project"; pid: string; tab: string; tid?: string };

function parse(hash: string): Route {
  const p = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (p[0] === "p" && p[1]) return { page: "project", pid: p[1], tab: p[2] || "footage", tid: p[3] };
  return { page: "home" };
}

export const go = (r: Route) => {
  window.location.hash = r.page === "home" ? "#/" : `#/p/${r.pid}/${r.tab}${r.tid ? "/" + r.tid : ""}`;
};

interface ToastCtx {
  say: (msg: string, kind?: "info" | "error") => void;
}
const Ctx = createContext<ToastCtx>({ say: () => {} });
export const useToast = () => useContext(Ctx);

export default function App() {
  const [route, setRoute] = useState<Route>(parse(window.location.hash));
  const [toast, setToast] = useState<{ msg: string; kind: string } | null>(null);
  const [brains, setBrains] = useState(false);
  const [title, setTitle] = useState<string>("");
  const [health, setHealth] = useState<{ version: string; ffmpeg: boolean } | null>(null);

  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", on);
    api<{ version: string; ffmpeg: boolean }>("/health").then(setHealth).catch(() => setHealth(null));
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const say = useCallback((msg: string, kind: "info" | "error" = "info") => {
    setToast({ msg, kind });
    window.clearTimeout((say as any)._t);
    (say as any)._t = window.setTimeout(() => setToast(null), kind === "error" ? 9000 : 5000);
  }, []);

  return (
    <Ctx.Provider value={{ say }}>
      <div className="app">
        <header className="topbar">
          <div className="brand" onClick={() => go({ page: "home" })} title="All shoots">
            <span className="logo">P</span> PrePro
          </div>
          {route.page === "project" && (
            <div className="crumbs">
              <span className="hide-sm">/</span>
              <b>{title}</b>
            </div>
          )}
          <div className="spacer" />
          {health && !health.ffmpeg && <span className="chip bad">ffmpeg not found</span>}
          <button className="btn small" onClick={() => setBrains(true)} title="AI connectors and privacy">
            Brains &amp; privacy
          </button>
          {health && <span className="dim small">v{health.version}</span>}
        </header>
        <main className="main">
          {route.page === "home" ? <Home /> : <Project key={route.pid} route={route} setTitle={setTitle} />}
        </main>
        {brains && <Brains onClose={() => setBrains(false)} />}
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
