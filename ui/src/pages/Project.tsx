import { useEffect, useRef, useState } from "react";
import { api, followJob, frameUrl, isOver, mediaUrl, type Job, mmss } from "../api";
import { go, type Route, useToast } from "../App";
import Icon from "../components/Icon";
import TaskProgress from "../components/TaskProgress";
import { refThumb, type Asset, type Brief, type Direction, type Summary } from "../types";
import Export from "./Export";
import Review from "./Review";

const TABS: [string, string, string][] = [
  ["footage", "Footage", "film"],
  ["brief", "Brief", "brief"],
  ["directions", "Directions", "compass"],
  ["review", "Review", "eye"],
  ["export", "Export", "export"],
];

/** Kept for pages that show a running job inline. */
export function JobBar({ job }: { job: Job | null }) {
  return job ? <TaskProgress job={job} /> : null;
}

export default function Project({ route, setTitle }: { route: Extract<Route, { page: "project" }>; setTitle: (s: string) => void }) {
  const { pid, tab } = route;
  const [s, setS] = useState<Summary | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const following = useRef<string | null>(null);
  const { say } = useToast();

  const load = () =>
    api<Summary>(`/projects/${pid}`)
      .then((x) => {
        setS(x);
        setTitle(x.name);
        return x;
      })
      .catch((e) => {
        say(e.message, "error");
        return null;
      });

  /** Follow a job to its end: live progress here, then the result (a finished cut opens in Review). */
  const follow = async (j: Job, label: string) => {
    if (following.current === j.id) return null;
    following.current = j.id;
    setJob(j);
    try {
      const done = await followJob(j, setJob);
      await load();
      if (done.kind === "autocut" && done.result?.timeline) {
        say(`Your first cut is ready: ${done.result.direction} · ${Math.round(done.result.duration)} s. Exports are in the shoot folder.`);
        go({ page: "project", pid, tab: "review", tid: done.result.timeline });
      }
      return done.result;
    } catch (e: any) {
      if (j.kind !== "autocut" || !String(e.message).includes("stopped")) say(`${label} didn't finish: ${e.message}`, "error");
      await load();
      return null;
    } finally {
      following.current = null;
      setJob(null);
    }
  };

  useEffect(() => {
    load().then((x) => {
      const live = x?.jobs?.find((j) => !isOver(j)); // work started elsewhere (e.g. opening the shoot): pick it up here
      if (live) follow(live, "The task");
    });
  }, [pid]);

  const run = async (path: string, body: unknown, label: string) => {
    try {
      const j = await api<Job>(path, { body: body ?? {} });
      return await follow(j, label);
    } catch (e: any) {
      say(`${label} failed: ${e.message}`, "error");
      return null;
    }
  };
  const autocut = () => run(`/projects/${pid}/autocut`, {}, "The cut");

  if (!s) return <div className="col" style={{ gap: 14 }}><div className="skeleton" style={{ height: 70 }} /><div className="skeleton" style={{ height: 260 }} /></div>;
  const tid = route.tid || s.timelines[0]?.id;
  const count = (k: string) => (k === "review" ? s.timelines.length : k === "directions" ? s.directions?.directions.length ?? 0 : 0);
  const has = s.timelines.length > 0;

  return (
    <div className="col" style={{ gap: 14 }}>
      <header className="page-head">
        <div className="col" style={{ gap: 2, minWidth: 0 }}>
          <h1 className="ellipsis">{s.name}</h1>
          <span className="sub small ellipsis" title={s.path}>{s.path}</span>
        </div>
        <div className="row">
          {has && (
            <button className="btn" onClick={autocut} disabled={!!job} title="Watch, edit, render and export again from scratch">
              <Icon name="refresh" size={15} /> Make a new cut
            </button>
          )}
          {has ? (
            tab !== "review" && (
              <button className="btn primary" onClick={() => go({ page: "project", pid, tab: "review", tid })} disabled={!!job}>
                <Icon name="eye" size={15} /> Open the cut
              </button>
            )
          ) : (
            <button className="btn primary big" onClick={autocut} disabled={!!job}>
              <Icon name="sparkles" /> Make my first cut
            </button>
          )}
        </div>
      </header>
      {job && <TaskProgress job={job} onStopped={() => say("Stopped. Nothing you had before was changed.")} />}
      {!job && !has && s.analysed && (
        <div className="callout acc row nowrap">
          <Icon name="sparkles" />
          <span className="grow">Everything is ready for an edit. <b>Make my first cut</b> picks the best direction for this footage and edits it end to end — you can change any decision after.</span>
        </div>
      )}
      <nav className="tabs" aria-label="Steps">
        {TABS.map(([k, label, icon]) => (
          <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => go({ page: "project", pid, tab: k, tid })}>
            <Icon name={icon} size={15} /> {label}
            {count(k) > 0 && <span className="n">{count(k)}</span>}
          </button>
        ))}
      </nav>
      {tab === "footage" && <Footage s={s} run={run} busy={!!job} />}
      {tab === "brief" && <BriefTab s={s} onSaved={load} />}
      {tab === "brief" && <StyleCard s={s} run={run} busy={!!job} reload={load} />}
      {tab === "directions" && <Directions s={s} run={run} busy={!!job} />}
      {tab === "review" &&
        (tid ? (
          <Review pid={pid} tid={tid} timelines={s.timelines} run={run} busy={!!job} />
        ) : (
          <div className="card empty-state">
            <div className="big"><Icon name="sparkles" size={36} /></div>
            <b>No cut yet</b>
            <div className="small">Click <b>Make my first cut</b> above — or pick a direction yourself under Directions.</div>
          </div>
        ))}
      {tab === "export" && (tid ? <Export pid={pid} tid={tid} run={run} busy={!!job} /> : <div className="card empty-state">Build a cut first.</div>)}
    </div>
  );
}

// ---------------------------------------------------------------- 1 · footage
function Footage({ s, run, busy }: { s: Summary; run: (p: string, b: unknown, l: string) => Promise<any>; busy: boolean }) {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const pid = s.id;
  useEffect(() => {
    if (s.analysed) api<Asset[]>(`/projects/${pid}/assets`).then(setAssets).catch(() => setAssets([]));
  }, [s.analysed, pid]);
  const search = async () => setHits(q.trim() ? await api<any[]>(`/projects/${pid}/search?q=${encodeURIComponent(q)}`) : null);

  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="card row" style={{ justifyContent: "space-between" }}>
        <div className="row small">
          {Object.entries(s.counts).map(([k, n]) => (
            <span key={k} className="chip">{n} {k.replace("_", " ")}</span>
          ))}
          {s.stats.days ? <span className="chip">{s.stats.days} day(s)</span> : null}
          {s.stats.places ? <span className="chip">{s.stats.places} place(s)</span> : null}
          {!s.analysed && !busy && <span className="mute">Not watched yet — “Make my first cut” does this on the way.</span>}
        </div>
        <div className="row">
          <button className="btn ghost small" disabled={busy} onClick={() => run(`/projects/${pid}/analyze`, { force: true }, "Analysis")}>
            <Icon name="refresh" size={14} /> Watch again
          </button>
          {s.analysed && (
            <button className="btn small" onClick={() => go({ page: "project", pid, tab: "brief" })}>
              <Icon name="brief" size={14} /> Add a brief (optional)
            </button>
          )}
        </div>
      </div>
      {s.asr.includes("pocketsphinx") && (
        <div className="callout warn row nowrap">
          <Icon name="mic" />
          <span className="grow">
            Speech was recognised with the basic offline recogniser, so words and captions may be rough. Download the Whisper model once (about
            480 MB) and PrePro redoes those transcripts automatically.
          </span>
          <button className="btn small" onClick={() => go({ page: "settings", section: "speech" })}>Open speech settings</button>
        </div>
      )}
      {s.warnings.length > 0 && (
        <div className="card small">{s.warnings.map((w, i) => <div key={i} className="gap">⚠ {w}</div>)}</div>
      )}
      {s.genres.length > 0 && (
        <div className="row small mute">Looks like: {s.genres.slice(0, 3).map((g) => <span key={g.playbook} className="chip">{g.playbook.replace("_", " ")} {Math.round(g.score * 100)}%</span>)}</div>
      )}
      {s.analysed && (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input type="text" placeholder='Search what was said or shown — "kachori", "beach", "laughing"' value={q}
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} aria-label="Search footage" />
          <button className="btn" onClick={search}>Search</button>
        </div>
      )}
      {hits && (
        <div className="card col">
          <b className="small">{hits.length} result(s)</b>
          {hits.map((h) => (
            <div key={h.type + h.id} className="row small">
              {h.thumb && <img src={frameUrl(pid, h.thumb)} alt="" style={{ width: 64, borderRadius: 4 }} />}
              <span className="chip">{h.type}</span> <code>{h.id}</code> <span className="dim">{mmss(h.t)}</span> {h.text}
            </div>
          ))}
        </div>
      )}
      {assets && (
        <div className="grid assets">
          {assets.map((a) => {
            const bad = a.shots.flatMap((x) => x.flags).filter((f) => ["dark", "blurry", "shaky", "pocket"].includes(f));
            return (
              <div key={a.id} className="card asset" title={a.path}>
                <div className={`thumb ${a.thumb ? "" : "audio"}`} style={{ backgroundImage: a.thumb ? `url(${frameUrl(pid, a.thumb)})` : undefined }}>
                  {!a.thumb && <span className="glyph" aria-hidden>{a.kind === "music" ? "♪" : a.kind === "sfx" ? "✶" : "▶"}</span>}
                  <span className="chip kind" style={{ background: "rgba(0,0,0,.6)", color: "#fff", borderColor: "transparent" }}>{a.kind.replace("_", " ")}</span>
                </div>
                <div className="body">
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><code>{a.id}</code> {a.name}</div>
                  <div className="dim">
                    {a.kind === "image"
                      ? `${a.size ? (a.size[0] >= a.size[1] ? "landscape" : "portrait") : "photo"}${a.taken ? ` · ${a.taken}` : ""}`
                      : `${a.duration.toFixed(1)}s${a.fps ? ` · ${Math.round(a.fps)} fps` : ""}`}
                    {a.place ? ` · ${a.place}` : ""}{a.day ? ` · day ${a.day}` : ""}
                  </div>
                  {a.music && <div className="dim">{Math.round(a.music.bpm)} BPM · {a.music.mood.join(", ")}</div>}
                  {bad.length > 0 && <div style={{ color: "var(--warn)" }}>⚠ {[...new Set(bad)].join(", ")}</div>}
                  {a.segments.length > 0 && <div className="mute" style={{ marginTop: 4 }}>“{a.segments.map((x) => x.text).join(" ").slice(0, 90)}…”</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- 2 · brief
const QUICK = [
  "Insta Reel, about 30 seconds.",
  "Hook: use the line where I say …",
  "No music while I talk.",
  "Use the … song for the montage.",
  "Add text at the end: Follow for part 2",
  "Add a meme after I say …",
  "Slow-mo on the jump.",
  "No zooms.",
  "Don't use the dark night clip.",
  "Captions in Hinglish.",
];

function BriefTab({ s, onSaved }: { s: Summary; onSaved: () => void }) {
  const [text, setText] = useState(s.brief.text || "");
  const [parsed, setParsed] = useState<Brief | null>(s.brief.parsed);
  const { say } = useToast();
  const save = async () => {
    try {
      setParsed(await api<Brief>(`/projects/${s.id}/brief`, { method: "PUT", body: { text } }));
      onSaved();
      say("Brief saved — it will be followed in every direction.");
    } catch (e: any) {
      say(e.message, "error");
    }
  };
  return (
    <div className="review" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(280px, 380px)" }}>
      <div className="card col">
        <h2>Tell PrePro about this video (optional)</h2>
        <p className="small mute" style={{ marginTop: -6 }}>
          Write it like a note to your editor — English, Hindi or Hinglish. Anything you leave out is decided automatically. Files in the shoot folder
          (brief.md, notes.yaml, HOOK_/MUST_/SKIP_ file names) are read too.
        </p>
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={"Reel, 30 sec. Hook: the line where I say five thousand rupees.\nNo music while I talk. Meme after I say Twenty!\nEnd text: Follow for part 2"} aria-label="Brief" />
        <div className="row">
          {QUICK.map((q) => (
            <button key={q} className="chip click" onClick={() => setText((t) => (t.trim() ? t.trim() + "\n" : "") + q)}>+ {q}</button>
          ))}
        </div>
        <div className="row">
          <button className="btn primary" onClick={save}>Save brief</button>
          <button className="btn" onClick={() => go({ page: "project", pid: s.id, tab: "directions" })}>Next: directions →</button>
        </div>
      </div>
      <div className="card">
        <h2>What PrePro understood</h2>
        {!parsed || (parsed.rules.length === 0 && parsed.questions.length === 0) ? (
          <p className="small mute">Nothing yet — Auto mode decides everything.</p>
        ) : (
          <div className="col small">
            {parsed.rules.map((r, i) => (
              <div key={i} className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
                <span title={r.resolved ? "found in the footage" : "not found yet"}>{r.resolved ? "✅" : "❔"}</span>
                <div>
                  <b>{r.kind.replace(/_/g, " ")}</b> {r.target ? <code>{r.target}</code> : null}
                  <div className="dim">“{r.source.trim().slice(0, 90)}”</div>
                </div>
              </div>
            ))}
            {parsed.questions.map((q, i) => <div key={i} className="gap">❓ {q.text}</div>)}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 3 · directions
function Directions({ s, run, busy }: { s: Summary; run: (p: string, b: unknown, l: string) => Promise<any>; busy: boolean }) {
  const ds = s.directions?.directions ?? [];
  const build = async (d: Direction) => {
    const r = await run(`/projects/${s.id}/build`, { direction: d.id, render: true }, "Build");
    if (r?.timeline) go({ page: "project", pid: s.id, tab: "review", tid: r.timeline });
  };
  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="mute" style={{ margin: 0 }}>
          Different ways to cut this footage. Each has 3 hook options and tells you what's missing for next time. Pick one (or several — each becomes its own cut).
        </p>
        <div className="row">
          {ds.length > 0 && (
            <button className="btn" disabled={busy} title="Render the first 6 seconds of every path (free, local)"
              onClick={() => run(`/projects/${s.id}/previews`, {}, "Previews")}>
              {Object.keys(s.previews || {}).length ? "Refresh previews" : "Show me each path"}
            </button>
          )}
          <button className="btn" disabled={busy || !s.analysed} onClick={() => run(`/projects/${s.id}/directions`, {}, "Directions")}>
            {ds.length ? "Suggest again" : "Suggest directions"}
          </button>
        </div>
      </div>
      {!s.analysed && <div className="card empty-state">Analyse the footage first (step 1).</div>}
      <div className="grid directions">
        {ds.map((d) => (
          <div key={d.id} className="card direction col">
            <h2>
              <span>{d.name}</span>
              <span className="fit">fit {Math.round(d.fit_score * 100)}%</span>
            </h2>
            <div className="row small">
              <span className="chip">{d.playbook.replace("_", " ")}</span>
              <span className="chip">{d.aspect}</span>
              <span className="chip">~{Math.round(d.knobs.target_length ?? d.target_max)} s</span>
              {d.from_brief && <span className="chip acc">from your brief</span>}
            </div>
            <div className="small mute">{d.why}</div>
            {s.previews?.[d.id] && (
              <video src={mediaUrl(s.id, s.previews[d.id], s.previews[d.id])} controls muted loop playsInline preload="metadata"
                style={{ width: "100%", maxHeight: 320, background: "#000", borderRadius: 8 }} aria-label={`Preview of ${d.name}`} />
            )}
            <h3>Hooks</h3>
            {d.hooks.map((h) => (
              <div key={h.id} className="hook small row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
                {h.refs[0] && <img src={frameUrl(s.id, refThumb(h.refs[0]))} alt="" style={{ width: 56, borderRadius: 5, flex: "none" }}
                  onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />}
                <div style={{ minWidth: 0 }}>
                  <b>{h.kind.replace(/_/g, " ")}</b> {h.text_hook && <span className="chip">“{h.text_hook}”</span>}
                  <div className="dim">{h.why}</div>
                </div>
              </div>
            ))}
            {d.outline.length > 0 && (
              <>
                <h3>Outline</h3>
                <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{d.outline.map((o, i) => <li key={i}>{o}</li>)}</ul>
              </>
            )}
            {d.coverage_gaps.length > 0 && (
              <>
                <h3>Shoot next time</h3>
                <ul className="small gap" style={{ margin: 0, paddingLeft: 18 }}>{d.coverage_gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
              </>
            )}
            <div className="spacer" />
            <button className="btn primary" disabled={busy} onClick={() => build(d)}>Build this cut</button>
          </div>
        ))}
      </div>
      {s.analysed && s.talk_seconds >= 60 && <Shorts s={s} run={run} busy={busy} />}
      {s.timelines.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Your cuts</h3>
          {s.timelines.map((t) => (
            <div key={t.id} className="row small" style={{ justifyContent: "space-between" }}>
              <span>{t.name} <span className="dim">· {t.aspect} · {mmss(t.duration, 0)}</span></span>
              <button className="btn small" onClick={() => go({ page: "project", pid: s.id, tab: "review", tid: t.id })}>Review</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- long → Shorts
function Shorts({ s, run, busy }: { s: Summary; run: (p: string, b: unknown, l: string) => Promise<any>; busy: boolean }) {
  const [count, setCount] = useState(3);
  const found = s.shorts?.directions ?? [];
  const tidOf = (d: Direction) => `${d.id}-${d.playbook}`;
  return (
    <div className="card col">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>Shorts from long talks</h2>
          <div className="small mute">
            {Math.round(s.talk_seconds / 60)} min of talking found. PrePro looks for moments that work on their own: a first line with a number, question
            or claim, one idea, and a landing — then cuts each as a vertical Short with bold captions.
          </div>
        </div>
        <div className="row">
          <select value={count} onChange={(e) => setCount(+e.target.value)} style={{ width: "auto" }} aria-label="How many Shorts">
            {[1, 2, 3, 4, 5, 6, 8].map((n) => <option key={n} value={n}>{n} Short{n > 1 ? "s" : ""}</option>)}
          </select>
          <button className="btn primary" disabled={busy} onClick={() => run(`/projects/${s.id}/shorts`, { count }, "Shorts")}>
            {found.length ? "Find again" : "Find Shorts"}
          </button>
        </div>
      </div>
      {found.length > 0 && (
        <div className="grid directions">
          {found.map((d) => (
            <div key={d.id} className="hook col small" style={{ gap: 4 }}>
              <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
                {d.hooks[0]?.refs[0] && <img src={frameUrl(s.id, refThumb(d.hooks[0].refs[0]))} alt="" style={{ width: 56, borderRadius: 5, flex: "none" }}
                  onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />}
                <div style={{ minWidth: 0 }}>
                  <b>{d.name}</b>
                  <div className="dim">~{Math.round(d.knobs.target_length ?? d.target_max)} s · fit {Math.round(d.fit_score * 100)}% · {d.why}</div>
                </div>
              </div>
              <button className="btn small" style={{ alignSelf: "flex-start" }}
                onClick={() => go({ page: "project", pid: s.id, tab: "review", tid: tidOf(d) })}>Review this Short</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Style DNA
function StyleCard({ s, run, busy, reload }: { s: Summary; run: (p: string, b: unknown, l: string) => Promise<any>; busy: boolean; reload: () => void }) {
  const { say } = useToast();
  const dna = s.style;
  const toggle = async (enabled: boolean) => {
    try {
      await api(`/projects/${s.id}/style`, { method: "PUT", body: { enabled } });
      reload();
    } catch (e: any) {
      say(e.message, "error");
    }
  };
  return (
    <div className="card col">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>Style DNA (optional)</h2>
          <div className="small mute">
            Put 1–5 videos whose editing you like into a <code>style/</code> folder in this shoot. PrePro measures their pace, cut rhythm, captions,
            music and length — they are never cut into your video or uploaded.
          </div>
        </div>
        <button className="btn" disabled={busy || s.style_refs.length === 0} onClick={() => run(`/projects/${s.id}/style`, {}, "Style DNA")}>
          {dna ? "Measure again" : `Measure ${s.style_refs.length || ""} reference${s.style_refs.length === 1 ? "" : "s"}`}
        </button>
      </div>
      {s.style_refs.length === 0 && !dna && <div className="small dim">No reference videos found in a style/ folder yet.</div>}
      {dna && (
        <div className="col small">
          <label className="row"><input type="checkbox" checked={dna.enabled} onChange={(e) => toggle(e.target.checked)} /> Cut in this style</label>
          {dna.summary.map((x, i) => <div key={i}>· {x}</div>)}
          <div className="dim">{dna.refs.map((r) => r.name).join(", ")}</div>
        </div>
      )}
    </div>
  );
}
