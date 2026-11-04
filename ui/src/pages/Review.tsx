import { useEffect, useMemo, useRef, useState } from "react";
import { api, frameUrl, mediaUrl, mmss } from "../api";
import { go, useToast } from "../App";
import { capText, itemDur, refThumb, type Item, type Knobs, type Suggestion, type View } from "../types";

type Run = (p: string, b: unknown, l: string) => Promise<any>;

const ROLE_COLOR: Record<string, string> = {
  hook: "var(--r-hook)", setup: "var(--r-talk)", body: "var(--r-talk)", payoff: "var(--r-talk)", reflection: "var(--r-talk)",
  cta: "var(--r-cta)", outro: "var(--r-cta)", broll: "var(--r-broll)", establishing: "var(--r-broll)", montage: "var(--r-broll)",
  natural: "var(--r-broll)", meme: "var(--r-meme)", text: "var(--r-text)", music: "var(--r-music)", sfx: "var(--r-sfx)",
};
const LANES: [string, string][] = [["T1", "TEXT"], ["V2", "OVER"], ["V1", "PIC"], ["A1", "VOICE"], ["A2", "MUSIC"], ["A3", "SFX"]];
const TYPES = ["all", "cut", "hook", "open_loop", "split", "timing", "loop", "framing", "broll", "speed", "zoom", "meme", "sfx", "text", "music",
  "transition", "caption", "filler"];

export default function Review({ pid, tid, timelines, run, busy }: {
  pid: string; tid: string; timelines: { id: string; name: string }[]; run: Run; busy: boolean;
}) {
  const [v, setV] = useState<View | null>(null);
  const [t, setT] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [note, setNote] = useState("");
  const [side, setSide] = useState("decisions");
  const [bust, setBust] = useState(Date.now());
  const [saving, setSaving] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const { say } = useToast();

  const load = () => api<View>(`/projects/${pid}/timelines/${tid}`).then(setV).catch((e) => say(e.message, "error"));
  useEffect(() => {
    load();
  }, [pid, tid]);

  const mutate = async (fn: () => Promise<View>) => {
    setSaving(true);
    try {
      setV(await fn());
    } catch (e: any) {
      say(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const seek = (x: number) => {
    setT(x);
    if (video.current) video.current.currentTime = x;
  };
  const toggle = (s: Suggestion, status: "applied" | "rejected") =>
    mutate(() => api<View>(`/projects/${pid}/timelines/${tid}/suggestions`, { body: { key: s.payload.key, status } }));
  const comment = async () => {
    const text = note.trim();
    if (!text) return;
    setSaving(true);
    try {
      const r = await api<{ comment: any; view: View }>(`/projects/${pid}/timelines/${tid}/comments`, { body: { t, text } });
      setV(r.view);
      setNote("");
      say((r.comment.status === "applied" ? "✓ " : "⚠ ") + r.comment.reply, r.comment.status === "applied" ? "info" : "error");
    } catch (e: any) {
      say(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const render = async () => {
    const r = await run(`/projects/${pid}/timelines/${tid}/render`, { quality: "preview" }, "Render");
    if (r) {
      setBust(Date.now());
      load();
    }
  };
  const rebuild = async (knobs: Partial<Knobs>) => {
    const r = await run(`/projects/${pid}/build`, { direction: v?.timeline.direction_id, knobs, render: true }, "Rebuild");
    if (r) {
      setBust(Date.now());
      load();
    }
  };

  if (!v) return <p className="mute">Loading the cut…</p>;
  const tl = v.timeline;
  // timeline order first (what you see while playing), then what was left out of the cut
  const sugg = tl.suggestions.filter((s) => filter === "all" || s.type === filter)
    .sort((a, b) => (a.t == null ? 1e9 : a.t) - (b.t == null ? 1e9 : b.t));
  const counts = tl.suggestions.reduce<Record<string, number>>((m, s) => ((m[s.type] = (m[s.type] || 0) + 1), m), {});
  const vertical = tl.height > tl.width;

  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          {timelines.length > 1 ? (
            <select value={tid} onChange={(e) => go({ page: "project", pid, tab: "review", tid: e.target.value })} style={{ width: "auto" }} aria-label="Cut">
              {timelines.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          ) : (
            <b>{tl.name}</b>
          )}
          <span className="chip">{tl.width}×{tl.height}</span>
          <span className="chip">{mmss(v.duration)}</span>
          {tl.look && <span className="chip">look: {tl.look}</span>}
          {v.revision.ops.length > 0 && <span className="chip acc">{v.revision.ops.length} change(s) by you</span>}
          {saving && <span className="dim small">updating…</span>}
        </div>
        <div className="row">
          {v.revision.ops.length > 0 && (
            <button className="btn small" onClick={() => confirm("Undo all your accept/reject choices and notes on this cut?") &&
              mutate(() => api<View>(`/projects/${pid}/timelines/${tid}/reset`, { body: {} }))}>Reset my changes</button>
          )}
          <button className="btn small" disabled={busy} onClick={render}>Render preview</button>
          <button className="btn small primary" onClick={() => go({ page: "project", pid, tab: "export", tid })}>Export →</button>
        </div>
      </div>

      <div className="review">
        <div className="col" style={{ minWidth: 0 }}>
          <div className="player" style={{ aspectRatio: vertical ? undefined : "16/9" }}>
            {v.render || v.render_stale ? (
              <>
                {(v.render || v.render_stale) && (
                  <video ref={video} key={bust} controls playsInline preload="metadata"
                    src={mediaUrl(pid, v.render ?? `.prepro/renders/${tid}_preview.mp4`, bust)}
                    onTimeUpdate={(e) => setT((e.target as HTMLVideoElement).currentTime)}
                    style={{ height: vertical ? "62vh" : undefined }} />
                )}
                {v.render_stale && (
                  <div className="stale">
                    <span>The preview is older than your latest changes.</span>
                    <button className="btn small primary" disabled={busy} onClick={render}>Render</button>
                  </div>
                )}
              </>
            ) : (
              <div className="empty">
                No preview yet.<br />
                <button className="btn primary" style={{ marginTop: 10 }} disabled={busy} onClick={render}>Render a preview</button>
              </div>
            )}
          </div>

          <Lanes v={v} t={t} seek={seek} sel={sel} onSel={(s) => { setSel(s.id); if (s.t != null) seek(s.t); setSide("decisions"); }} />

          <div className="row" style={{ flexWrap: "nowrap" }}>
            <span className="chip" title="Your note is pinned at the playhead">📍 {mmss(t)}</span>
            <input type="text" value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === "Enter" && comment()}
              placeholder='Note for this moment — "remove zoom", "big text: ₹500 only", "meme here", "faster", "change song"…' aria-label="Timeline note" />
            <button className="btn" disabled={!note.trim() || saving} onClick={comment}>Add note</button>
          </div>
        </div>

        <div className="side">
          <nav className="tabs" style={{ marginBottom: 0 }}>
            {[["decisions", "Decisions"], ["notes", "Notes"], ["score", "Score"], ["hooks", "Hook"], ["more", "More"]].map(([k, l]) => (
              <button key={k} className={`tab ${side === k ? "on" : ""}`} onClick={() => setSide(k)}>
                {l}
                {k === "notes" && v.revision.comments.length > 0 && <span className="n">{v.revision.comments.length}</span>}
              </button>
            ))}
          </nav>

          {side === "decisions" && (
            <div className="card col">
              <div className="row small">
                {TYPES.filter((x) => x === "all" || counts[x]).map((x) => (
                  <button key={x} className={`chip click ${filter === x ? "acc" : ""}`} onClick={() => setFilter(x)}>
                    {x}{x !== "all" ? ` ${counts[x]}` : ""}
                  </button>
                ))}
              </div>
              <div className="list">
                {sugg.map((s) => (
                  <SuggestionRow key={s.id + s.status} s={s} sel={sel === s.id} onPick={() => { setSel(s.id); if (s.t != null) seek(s.t); }} onToggle={toggle} />
                ))}
              </div>
            </div>
          )}

          {side === "notes" && (
            <div className="card col">
              {v.revision.comments.length === 0 ? (
                <p className="small mute">Play the cut, pause where something bugs you and type a note under the timeline. PrePro turns it into an edit; delete the note to undo it.</p>
              ) : (
                v.revision.comments.map((c) => (
                  <div key={c.id} className={`comment ${c.status}`}>
                    <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                      <span><a href="#" onClick={(e) => { e.preventDefault(); seek(c.t); }}>{mmss(c.t)}</a> “{c.text}”</span>
                      <button className="btn small ghost" title="Delete note (undo)" onClick={() => mutate(() => api<View>(`/projects/${pid}/timelines/${tid}/comments/${c.id}`, { method: "DELETE" }))}>✕</button>
                    </div>
                    <div className="small mute">{c.source === "ai" ? "🤖 " : ""}{c.reply}</div>
                  </div>
                ))
              )}
            </div>
          )}

          {side === "score" && <Score v={v} seek={seek} />}
          {side === "hooks" && <HookKnobs v={v} pid={pid} busy={busy} pick={(id) => mutate(() => api<View>(`/projects/${pid}/timelines/${tid}/hook`, { body: { hook_id: id } }))} rebuild={rebuild} />}
          {side === "more" && <More v={v} pid={pid} busy={busy} makePackage={async () => {
            const r = await run(`/projects/${pid}/timelines/${tid}/package`, {}, "Packaging");
            if (r) load();
          }} />}
        </div>
      </div>
    </div>
  );
}

function SuggestionRow({ s, sel, onPick, onToggle }: { s: Suggestion; sel: boolean; onPick: () => void; onToggle: (s: Suggestion, st: "applied" | "rejected") => void }) {
  const key = s.payload?.key as string | undefined;
  const can = !!key && key !== "hook" && !(s.status === "optional" && s.payload.acceptable === false);
  return (
    <div className={`sugg ${s.status} ${sel ? "sel" : ""}`} onClick={onPick}>
      <div className="why">{s.reason}</div>
      <div>
        {can ? (
          <div className="toggle" onClick={(e) => e.stopPropagation()}>
            <button className={s.status === "applied" ? "on" : ""} title="Keep / apply" onClick={() => s.status !== "applied" && onToggle(s, "applied")}>✓</button>
            <button className={s.status !== "applied" ? "on" : ""} title={s.status === "optional" ? "Leave out" : "Reject"} onClick={() => s.status === "applied" && onToggle(s, "rejected")}>✕</button>
          </div>
        ) : s.status === "optional" ? <span className="chip warn small">needs a file</span> : null}
      </div>
      <div className="meta">
        <span>{s.type}</span>
        {s.t != null && <span>{mmss(s.t)}</span>}
        <span>{s.source}</span>
        <span>conf {Math.round(s.confidence * 100)}%</span>
        {s.status !== "applied" && <span>{s.status}</span>}
        {s.payload?.search?.length ? <span>search: {s.payload.search.slice(0, 2).join(", ")}</span> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- timeline lanes
function Lanes({ v, t, seek, sel, onSel }: { v: View; t: number; seek: (x: number) => void; sel: string | null; onSel: (s: Suggestion) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(800);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const ro = new ResizeObserver((e) => setW(Math.max(300, e[0].contentRect.width - 36)));
    if (box.current) ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  const tl = v.timeline;
  const dur = Math.max(1, v.duration);
  const pps = (w / dur) * zoom;
  const width = dur * pps;
  const byLane = useMemo(() => {
    const m: Record<string, Item[]> = {};
    for (const it of tl.items) {
      const lane = it.track === "A4" ? "A3" : it.track === "V3" ? "V2" : it.track;
      (m[lane] ||= []).push(it);
    }
    return m;
  }, [tl]);
  const capAt = (a: number, b: number) => tl.captions.filter((c) => c.t1 > a && c.t0 < b).map(capText).join(" ");
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((x) => x * pps >= 46) ?? 600;   // ticks never collide
  const click = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    seek(Math.max(0, Math.min(dur, (e.clientX - r.left) / pps)));
  };
  const label = (it: Item) => {
    if (it.kind === "text") return it.text ?? "";
    if (it.track === "A1" && it.role !== "natural") return capAt(it.rec_in, it.rec_in + itemDur(it)) || it.ref || "";
    if (it.track === "A3") return (it.note || "").replace("builtin:", "") || v.assets[it.asset_id ?? ""] || "sfx";
    const name = v.assets[it.asset_id ?? ""] ?? "";
    return `${it.role ?? ""}${it.speed !== 1 ? ` ${it.speed}x` : ""} · ${name}`;
  };

  return (
    <div>
      <div className="row small" style={{ justifyContent: "space-between", marginTop: 8 }}>
        <span className="mute">Timeline · click to jump · dots are decisions, 📍 are your notes</span>
        <span className="row">
          <button className="btn small" onClick={() => setZoom((z) => Math.max(1, z / 1.6))} aria-label="Zoom out">−</button>
          <button className="btn small" onClick={() => setZoom((z) => Math.min(12, z * 1.6))} aria-label="Zoom in">+</button>
        </span>
      </div>
      <div className="tl" ref={box}>
        <div className="tl-inner" style={{ width: width + 36 }}>
          <div style={{ display: "flex" }}>
            <div className="lane-label" style={{ height: 22 }}>s</div>
            <div className="ruler" style={{ width }} onClick={click}>
              {Array.from({ length: Math.floor(dur / step) + 1 }, (_, k) => (
                <div key={k} className="tick" style={{ left: k * step * pps }}>{mmss(k * step, 0)}</div>
              ))}
            </div>
          </div>
          <div style={{ display: "flex" }} title="Retention heat: red = viewers are likely to swipe away here">
            <div className="lane-label" style={{ height: 8 }} />
            <div className="heat" style={{ width }}>
              {v.attention.map((r, k) => (
                <div key={k} style={{ width: 0.5 * pps, background: `hsl(${(1 - r) * 120} 70% 45% / ${0.25 + r * 0.6})` }} />
              ))}
            </div>
          </div>
          <div style={{ display: "flex" }}>
            <div className="lane-label" style={{ height: 16 }} />
            <div className="marks" style={{ width }}>
              {tl.suggestions.filter((s) => s.t != null).map((s) => (
                <div key={s.id} className="mark" title={`${s.type}: ${s.reason}`} onClick={() => onSel(s)}
                  style={{ left: (s.t ?? 0) * pps, background: s.status === "applied" ? "var(--ok)" : s.status === "optional" ? "var(--warn)" : "var(--dim)",
                    outline: sel === s.id ? "2px solid var(--fg)" : undefined }} />
              ))}
              {v.revision.comments.map((c) => (
                <span key={c.id} className="pin" style={{ left: c.t * pps }} title={`${c.text} → ${c.reply}`} onClick={() => seek(c.t)}>📍</span>
              ))}
            </div>
          </div>
          {LANES.map(([lane, name]) => (
            <div key={lane} style={{ display: "flex" }}>
              <div className={`lane-label`} style={{ height: lane === "V1" || lane === "A1" ? 40 : 30 }}>{name}</div>
              <div className={`lane ${lane === "V1" || lane === "A1" ? "tall" : ""}`} style={{ width }} onClick={click}>
                {(byLane[lane] || []).map((it) => {
                  const bg = ROLE_COLOR[it.kind === "text" ? "text" : it.track === "A2" ? "music" : it.track === "A3" || it.track === "A4" ? "sfx" : it.role ?? "body"] ?? "var(--r-talk)";
                  const isSel = !!sel && tl.suggestions.find((s) => s.id === sel)?.payload?.key === it.ref;
                  return (
                    <div key={it.id} className={`blk ${isSel ? "sel" : ""}`} title={`${label(it)} · ${mmss(it.rec_in)}–${mmss(it.rec_in + itemDur(it))}`}
                      style={{ left: it.rec_in * pps, width: Math.max(2, itemDur(it) * pps - 1), background: bg,
                        opacity: it.role === "natural" ? 0.55 : 1, borderLeft: it.transition_in !== "cut" ? "3px double #fff" : undefined }}>
                      {it.transform && it.transform.zoom > 1.01 && <span className="x">⤢</span>}
                      {label(it)}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="playhead" style={{ left: 36 + t * pps }} />
        </div>
      </div>
      <div className="legend">
        <span><i style={{ background: "var(--r-hook)" }} />hook</span>
        <span><i style={{ background: "var(--r-talk)" }} />talking</span>
        <span><i style={{ background: "var(--r-broll)" }} />b-roll</span>
        <span><i style={{ background: "var(--r-meme)" }} />meme</span>
        <span><i style={{ background: "var(--r-cta)" }} />CTA</span>
        <span><i style={{ background: "var(--r-text)" }} />text</span>
        <span><i style={{ background: "var(--r-music)" }} />music</span>
        <span><i style={{ background: "var(--r-sfx)" }} />sfx</span>
        <span>⤢ punch-in</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- side panels
function Score({ v, seek }: { v: View; seek: (x: number) => void }) {
  const c = v.critic;
  const color = (x: number) => (x >= 8 ? "var(--ok)" : x >= 6 ? "var(--warn)" : "var(--bad)");
  return (
    <div className="card col">
      {c ? (
        <>
          {Object.entries(c.scores).map(([k, x]) => (
            <div key={k} className="score">
              <span>{k.replace("_", " ")}</span>
              <div className="bar"><div style={{ width: `${x * 10}%`, background: color(x) }} /></div>
              <b>{x.toFixed(1)}</b>
            </div>
          ))}
          <div className="small">{c.summary}</div>
          {c.issues.length > 0 && <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{c.issues.map((x, i) => <li key={i}>{x}</li>)}</ul>}
        </>
      ) : <p className="mute small">Not scored.</p>}
      <h3>Your brief</h3>
      {v.compliance.length === 0 ? <p className="small mute">No brief — Auto mode.</p> : v.compliance.map((x, i) => (
        <div key={i} className="small">{x.ok ? "✅" : "❌"} {x.source || x.rule} {x.ok ? "" : <span className="dim">— {x.detail}</span>}</div>
      ))}
      <h3>Checks</h3>
      {v.lint.length === 0 ? <p className="small mute">Nothing flagged.</p> : v.lint.map((f, i) => (
        <div key={i} className="small" style={{ cursor: f.t != null ? "pointer" : undefined }} onClick={() => f.t != null && seek(f.t)}>
          <span className={`chip ${f.severity === "error" ? "bad" : f.severity === "warn" ? "warn" : ""}`}>{f.severity}</span> {f.msg}
          {f.t != null && <span className="dim"> @ {mmss(f.t)}</span>}
        </div>
      ))}
    </div>
  );
}

function HookKnobs({ v, pid, busy, pick, rebuild }: { v: View; pid: string; busy: boolean; pick: (id: string) => void; rebuild: (k: Partial<Knobs>) => void }) {
  const d = v.direction;
  const [k, setK] = useState<Knobs | null>(d ? { ...d.knobs } : null);
  const first = [...v.timeline.items].filter((i) => i.track === "V1").sort((a, b) => a.rec_in - b.rec_in)[0];
  if (!d || !k) return <div className="card small mute">No direction info.</div>;
  const seg = <T extends string>(field: keyof Knobs, opts: T[]) => (
    <div className="seg3">
      {opts.map((o) => <button key={o} className={(k as any)[field] === o ? "on" : ""} onClick={() => setK({ ...k, [field]: o })}>{o}</button>)}
    </div>
  );
  return (
    <div className="card col">
      <h3 style={{ marginTop: 0 }}>Hook</h3>
      {d.hooks.map((h) => {
        const on = first?.ref === h.refs[0];
        return (
          <div key={h.id} className="hook small row" style={{ borderColor: on ? "var(--acc)" : undefined, flexWrap: "nowrap", alignItems: "flex-start" }}>
            {h.refs[0] && <img src={frameUrl(pid, refThumb(h.refs[0]))} alt="" style={{ width: 56, borderRadius: 5, flex: "none" }} onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <b>{h.kind.replace(/_/g, " ")}</b>
                {on ? <span className="chip acc">in use</span> : <button className="btn small" onClick={() => pick(h.id)}>Use this hook</button>}
              </div>
              {h.text_hook && <div>“{h.text_hook}”</div>}
              <div className="dim">{h.why}</div>
            </div>
          </div>
        );
      })}
      <h3>Knobs</h3>
      <p className="small dim" style={{ marginTop: -4 }}>Rebuilds the cut with the same brain; your accept/reject choices and notes are kept.</p>
      <div className="knob"><span>Pace</span><input type="range" min={0} max={1} step={0.1} value={k.pace} onChange={(e) => setK({ ...k, pace: +e.target.value })} aria-label="Pace" /></div>
      <div className="knob"><span>Effects</span>{seg("effects", ["clean", "balanced", "bold"])}</div>
      <div className="knob"><span>Captions</span>{seg("captions", ["off", "clean", "bold"])}</div>
      <div className="knob"><span>Humour</span>{seg("humour", ["off", "light", "heavy"])}</div>
      <div className="knob"><span>Length (s)</span>
        <input type="number" min={5} max={3600} value={k.target_length ?? ""} placeholder="auto" onChange={(e) => setK({ ...k, target_length: e.target.value ? +e.target.value : null })} />
      </div>
      <button className="btn primary" disabled={busy} onClick={() => rebuild(k)}>Rebuild with these settings</button>
    </div>
  );
}

function More({ v, pid, busy, makePackage }: { v: View; pid: string; busy: boolean; makePackage: () => void }) {
  const m = v.timeline.meta;
  const pk = v.packaging;
  const copy = (t: string) => navigator.clipboard?.writeText(t).catch(() => {});
  return (
    <div className="card col small">
      <h3 style={{ marginTop: 0 }}>Packaging</h3>
      {!pk ? (
        <div className="col">
          <span className="mute">Thumbnail picks with text, title options, YouTube chapters and a description.</span>
          <button className="btn small primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={makePackage}>Make thumbnails &amp; titles</button>
        </div>
      ) : (
        <div className="col">
          <div className="row" style={{ alignItems: "flex-start" }}>
            {pk.thumbs.map((th) => (
              <a key={th.path} href={mediaUrl(pid, th.path, th.t)} target="_blank" rel="noreferrer" title={th.why}>
                <img src={mediaUrl(pid, th.path, th.t)} alt={th.why} style={{ height: 120, borderRadius: 6, display: "block" }} />
              </a>
            ))}
          </div>
          <b>Titles</b>
          {pk.titles.map((t) => (
            <div key={t} className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
              <span>{t}</span><button className="btn small ghost" onClick={() => copy(t)} title="Copy">⧉</button>
            </div>
          ))}
          <b>Chapters</b>
          {pk.chapters.length ? pk.chapters.map(([t, n]) => <div key={t}>{mmss(t, 0)} {n}</div>) : <div className="dim">{pk.chapters_note}</div>}
          <div className="row" style={{ justifyContent: "space-between" }}><b>Description</b><button className="btn small ghost" onClick={() => copy(pk.description)}>Copy</button></div>
          <div className="pe" style={{ maxHeight: 160 }}>{pk.description}</div>
          <button className="btn small" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={makePackage}>Remake</button>
        </div>
      )}
      <h3>Music plan</h3>
      {(m.music ?? []).map((x: any, i: number) => (
        <div key={i}><b>{x.section}</b>: {x.mode} {x.track_id ? <code>{v.assets[x.track_id] ?? x.track_id}</code> : <span className="dim">no track</span>} <span className="dim">— {x.why}</span>
          {!x.track_id && x.mode !== "none" && x.brief?.search_terms?.length ? <div className="dim">search: {x.brief.search_terms.slice(0, 3).join(", ")}</div> : null}
        </div>
      ))}
      <h3>Shoot / find next</h3>
      {(v.direction?.coverage_gaps ?? []).map((g, i) => <div key={"g" + i} className="gap">• {g}</div>)}
      {(m.broll_gaps ?? []).map((g: any, i: number) => <div key={"b" + i}>• {g.want}{g.search_terms?.length ? <span className="dim"> — search: {g.search_terms.join(", ")}</span> : null}</div>)}
      {(m.vo_script ?? []).length > 0 && (<><h3>Suggested voice-over</h3>{m.vo_script.map((x: string, i: number) => <div key={i}>“{x}”</div>)}</>)}
      <h3>Paper edit</h3>
      <div className="pe">{v.paper_edit}</div>
    </div>
  );
}
