import { type ReactNode, useEffect, useState } from "react";
import { api, followJob, type Job } from "../api";
import { go, useToast } from "../App";
import { LogoTile } from "../components/BrandLogo";
import Icon from "../components/Icon";
import TaskProgress from "../components/TaskProgress";
import { getTheme, setTheme, type ThemeMode } from "../theme";
import type { AIOverview, GeneralSettings, KeyAccount, PlanAccount, SpeechModels, TestResult } from "../types";
import { UpdatesPanel, useUpdates } from "./Updates";

/** Tell the sidebar the AI editor or a connection changed. */
export const aiChanged = () => window.dispatchEvent(new Event("prepro:ai-changed"));

export const SECTIONS: [string, string, string][] = [
  ["general", "General", "settings"],
  ["ai", "AI editor", "sparkles"],
  ["privacy", "Privacy", "shield"],
  ["speech", "Speech recognition", "mic"],
  ["render", "Rendering", "cpu"],
  ["updates", "Updates", "download"],
  ["about", "About", "info"],
];

const PASSES: [string, string][] = [
  ["director", "Directions, hooks, what's missing"], ["story", "Story order"], ["polish", "Music, memes, SFX, text"],
  ["critic", "Senior-editor review"], ["vision", "Shot tags from thumbnails"], ["brief", "Reading your brief"], ["revise", "Your timeline notes"],
];

function Row({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="set-row">
      <div className="lbl"><b>{title}</b>{sub && <span>{sub}</span>}</div>
      {children}
    </div>
  );
}

function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button className={`switch${on ? " on" : ""}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} />;
}

function TestLine({ t }: { t: TestResult | null }) {
  if (!t) return null;
  return t.ok ? (
    <span className="chip ok"><Icon name="check" size={12} /> Connected · {t.msg}</span>
  ) : (
    <span className="chip bad" title={t.msg}><Icon name="x" size={12} /> {t.msg.length > 70 ? t.msg.slice(0, 70) + "…" : t.msg}</span>
  );
}

export default function Settings({ section }: { section: string }) {
  const sec = SECTIONS.some(([k]) => k === section) ? section : "general";
  const updates = useUpdates();
  return (
    <div className="settings">
      <nav className="settings-nav" aria-label="Settings sections">
        <h1>Settings</h1>
        {SECTIONS.filter(([k]) => k !== "updates" || updates).map(([k, label, icon]) => (
          <button key={k} className={`nav${sec === k ? " on" : ""}`} onClick={() => go({ page: "settings", section: k })}>
            <Icon name={icon} /> <span className="lbl">{label}</span>
          </button>
        ))}
      </nav>
      <div className="settings-body">
        {sec === "general" && <General />}
        {sec === "ai" && <AISection />}
        {sec === "privacy" && <Privacy />}
        {sec === "speech" && <Speech />}
        {sec === "render" && <Rendering />}
        {sec === "updates" && (updates ? <><h2>Updates</h2><p className="lead">Keep PrePro current — on your terms.</p><UpdatesPanel /></> : null)}
        {sec === "about" && <About />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- general
function General() {
  const [g, setG] = useState<GeneralSettings | null>(null);
  const [theme, setT] = useState<ThemeMode>(getTheme());
  const { say } = useToast();
  useEffect(() => {
    api<GeneralSettings>("/settings").then(setG).catch((e) => say(e.message, "error"));
  }, []);
  const save = async (patch: Partial<GeneralSettings>) => setG(await api<GeneralSettings>("/settings", { method: "PUT", body: patch }));
  const pick = (m: ThemeMode) => {
    setTheme(m);
    setT(m);
  };
  return (
    <>
      <h2>General</h2>
      <p className="lead">How PrePro works for you.</p>
      <h3>Making cuts</h3>
      <div className="set-group">
        <Row title="Make the first cut as soon as I open a shoot"
          sub="PrePro watches the footage, picks the best direction, edits, renders and prepares exports on its own. You refine after.">
          {g && <Switch on={g.autocut_on_open} onChange={(v) => save({ autocut_on_open: v })} label="Make the first cut automatically" />}
        </Row>
      </div>
      <h3>Appearance</h3>
      <div className="set-group">
        <div className="theme-tiles" role="radiogroup" aria-label="Theme">
          {(["system", "light", "dark"] as const).map((m) => (
            <button key={m} className={`theme-tile${theme === m ? " on" : ""}`} role="radio" aria-checked={theme === m} onClick={() => pick(m)}>
              <div className={`pv ${m === "system" ? "sys" : m}`}><i /><div><u /><b /></div></div>
              <div className="row nowrap small" style={{ gap: 6 }}>
                <Icon name={m === "system" ? "monitor" : m === "light" ? "sun" : "moon"} size={15} />
                <b>{m === "system" ? "Match my computer" : m === "light" ? "Light" : "Dark"}</b>
              </div>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- AI
function AISection() {
  const [ai, setAi] = useState<AIOverview | null>(null);
  const [testing, setTesting] = useState<Record<string, Job>>({});
  const { say } = useToast();
  const load = () => api<AIOverview>("/ai").then(setAi).catch((e) => say(e.message, "error"));
  useEffect(() => {
    load();
  }, []);
  if (!ai) return <><h2>AI editor</h2><div className="skeleton" style={{ height: 220 }} /></>;

  const put = async (body: object) => {
    try {
      setAi(await api<AIOverview>("/ai", { method: "PUT", body }));
      aiChanged();
    } catch (e: any) {
      say(e.message, "error");
    }
  };
  const test = async (id: string) => {
    try {
      const j = await api<Job>(`/ai/${id}/test`, { body: {} });
      setTesting((t) => ({ ...t, [id]: j }));
      await followJob(j, (x) => setTesting((t) => ({ ...t, [id]: x })));
      say("Connected — it answered.");
    } catch (e: any) {
      say(`The test didn't work: ${e.message}`, "error");
    } finally {
      setTesting((t) => {
        const c = { ...t };
        delete c[id];
        return c;
      });
      load().then(aiChanged);
    }
  };
  const label = (id: string) =>
    id === "basic" ? "Rules engine" : ai.plans.find((p) => p.id === id)?.name ?? ai.keys.find((k) => k.id === id)?.name ?? ai.local.find((l) => l.id === id)?.name ?? id;
  const sub = (id: string) =>
    id === "basic" ? "Free, offline — no AI" : ai.plans.find((p) => p.id === id) ? "Your plan" : ai.keys.find((k) => k.id === id) ? "Your API key" : "On this PC";

  return (
    <>
      <h2>AI editor</h2>
      <p className="lead">
        PrePro edits on its own with its rules engine. Connect an AI you already use and it becomes your <b>AI editor</b>: it reads the
        transcripts (and, if you allow, small thumbnails) and makes the editorial calls. Your footage never leaves this computer.
      </p>
      <h3>Who edits</h3>
      <div className="set-group">
        <div className="editor-pick" role="radiogroup" aria-label="AI editor">
          {["basic", ...ai.ready].map((id) => (
            <button key={id} className={`pick${ai.editor === id ? " on" : ""}`} role="radio" aria-checked={ai.editor === id} onClick={() => put({ editor: id })}>
              <LogoTile id={id} />
              <div className="col" style={{ gap: 0 }}>
                <span className="t">{label(id)}</span>
                <span className="s">{sub(id)}</span>
              </div>
            </button>
          ))}
        </div>
        {ai.ready.length === 0 && (
          <div className="set-row"><span className="small mute">Nothing connected yet — pick one below. Connecting one makes it your AI editor straight away.</span></div>
        )}
      </div>

      <h3>Use a subscription you already pay for</h3>
      <div className="set-group">
        {ai.plans.map((p) => (
          <PlanCard key={p.id} p={p} editor={ai.editor} testing={testing[p.id]} onTest={() => test(p.id)} onUse={() => put({ editor: p.id })} reload={load} />
        ))}
      </div>

      <h3>Use your own API key</h3>
      <div className="set-group">
        {ai.keys.map((k) => (
          <KeyCard key={k.id} k={k} editor={ai.editor} testing={testing[k.id]} onTest={() => test(k.id)} onUse={() => put({ editor: k.id })} onChange={setAi} />
        ))}
      </div>

      {ai.local.length > 0 && (
        <>
          <h3>On this computer</h3>
          <div className="set-group">
            {ai.local.map((l) => (
              <div key={l.id} className="acct">
                <LogoTile id={l.id} />
                <div className="col" style={{ gap: 2 }}>
                  <div className="name">{l.name} <span className="chip ok">nothing leaves this PC</span></div>
                  <div className="sub">Model {l.model}</div>
                  <TestLine t={l.test} />
                </div>
                <div className="acts">
                  <button className="btn small" onClick={() => test(l.id)} disabled={!!testing[l.id]}>Test</button>
                  {ai.editor !== l.id && <button className="btn small" onClick={() => put({ editor: l.id })}>Use as AI editor</button>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="set-group">
        <details className="adv">
          <summary><Icon name="chevron" size={14} /> Advanced: give a task to a different AI</summary>
          <div style={{ padding: "6px 16px 14px" }}>
            {PASSES.map(([k, lbl]) => (
              <div key={k} className="knob">
                <span className="small">{lbl}</span>
                <select value={ai.routing[k] ?? "auto"} onChange={(e) => put({ routing: { ...ai.routing, [k]: e.target.value } })}>
                  <option value="auto">Your AI editor ({label(ai.editor)})</option>
                  <option value="basic">Rules engine (free, offline)</option>
                  {ai.ready.map((id) => <option key={id} value={id}>{label(id)}</option>)}
                </select>
              </div>
            ))}
            <div className="knob">
              <span className="small">Monthly budget</span>
              <div className="row nowrap">
                <input type="number" min={0} step={1} defaultValue={ai.monthly_cap_usd} style={{ maxWidth: 120 }}
                  onBlur={(e) => put({ monthly_cap_usd: Number(e.target.value || 0) })} />
                <span className="small dim">USD a month for API keys (plans use their own limits)</span>
              </div>
            </div>
          </div>
        </details>
      </div>
    </>
  );
}

function PlanCard({ p, editor, testing, onTest, onUse, reload }: { p: PlanAccount; editor: string; testing?: Job; onTest: () => void; onUse: () => void; reload: () => void }) {
  const { say } = useToast();
  const [cmd, setCmd] = useState<string | null>(null);
  const open = async (action: "install" | "signin") => {
    try {
      const r = await api<{ command: string }>(`/ai/${p.id}/open`, { body: { action } });
      setCmd(r.command);
      say(action === "install" ? `A terminal window opened to install ${p.via}. When it finishes, click “Check again”.` : `A terminal window opened. ${p.signin_note}`);
    } catch (e: any) {
      say(e.message, "error");
    }
  };
  const needsNode = p.needs_npm && !p.npm;
  return (
    <div className="acct">
      <LogoTile id={p.id} />
      <div className="col" style={{ gap: 3, minWidth: 0 }}>
        <div className="name">
          {p.name} <span className="dim small" style={{ fontWeight: 500 }}>· {p.plan}</span>
          {editor === p.id && <span className="chip soft"><Icon name="sparkles" size={12} /> AI editor</span>}
        </div>
        <div className="sub">
          {p.installed ? <>Through {p.via}{p.version ? ` ${p.version}` : ""} — signs in with your {p.name} account</> : <>Needs {p.via} (free) — PrePro uses your plan through it</>}
        </div>
        <div className="row">{p.installed ? <TestLine t={p.test} /> : <span className="chip">Not installed</span>}</div>
      </div>
      <div className="acts">
        {!p.installed ? (
          needsNode ? (
            <a className="btn small" href="https://nodejs.org" target="_blank" rel="noreferrer"><Icon name="external" size={14} /> Get Node.js first</a>
          ) : (
            <button className="btn small primary" onClick={() => open("install")}><Icon name="download" size={14} /> Install</button>
          )
        ) : (
          <>
            <button className="btn small" onClick={() => open("signin")}><Icon name="link" size={14} /> Sign in</button>
            <button className="btn small" onClick={onTest} disabled={!!testing}>{testing ? "Testing…" : "Test"}</button>
            {editor !== p.id && <button className="btn small primary" onClick={onUse}>Use as AI editor</button>}
          </>
        )}
        {!p.installed && <button className="btn small ghost" onClick={reload} title="Look for it again"><Icon name="refresh" size={14} /> Check again</button>}
      </div>
      {(cmd || testing || (!p.installed && !needsNode)) && (
        <div className="more">
          {testing && <TaskProgress job={testing} compact />}
          {(cmd || !p.installed) && (
            <div className="cmd" title="The command PrePro runs in the terminal window">
              <Icon name="terminal" size={14} /> <code>{cmd ?? p.install_cmd}</code>
              <button className="btn small ghost" onClick={() => navigator.clipboard?.writeText(cmd ?? p.install_cmd)}>Copy</button>
            </div>
          )}
          <span className="tiny dim">{p.training}</span>
        </div>
      )}
    </div>
  );
}

function KeyCard({ k, editor, testing, onTest, onUse, onChange }: { k: KeyAccount; editor: string; testing?: Job; onTest: () => void; onUse: () => void; onChange: (a: AIOverview) => void }) {
  const [val, setVal] = useState("");
  const [model, setModel] = useState(k.model);
  const [busy, setBusy] = useState(false);
  const { say } = useToast();
  const save = async () => {
    setBusy(true);
    try {
      onChange(await api<AIOverview>(`/ai/keys/${k.id}`, { method: "PUT", body: { key: val } }));
      aiChanged();
      setVal("");
      say(`${k.name} key saved to your computer's keychain.`);
    } catch (e: any) {
      say(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    try {
      onChange(await api<AIOverview>(`/ai/keys/${k.id}`, { method: "DELETE" }));
      aiChanged();
      say(`${k.name} key removed.`);
    } catch (e: any) {
      say(e.message, "error");
    }
  };
  const saveModel = async () => {
    if (model.trim() && model !== k.model) onChange(await api<AIOverview>(`/ai/${k.id}/model`, { method: "PUT", body: { model } }));
  };
  return (
    <div className="acct">
      <LogoTile id={k.id} />
      <div className="col" style={{ gap: 3, minWidth: 0 }}>
        <div className="name">
          {k.name}
          {k.set && <span className="chip"><Icon name="lock" size={12} /> {k.masked}</span>}
          {editor === k.id && <span className="chip soft"><Icon name="sparkles" size={12} /> AI editor</span>}
        </div>
        <div className="sub">{k.set ? <>Pay-as-you-go on your {k.name} account</> : <>Bring your own key — billed by {k.name.replace(" API", "")}, kept in your computer's keychain</>}</div>
        {k.set && <div className="row"><TestLine t={k.test} /></div>}
      </div>
      <div className="acts">
        {k.set ? (
          <>
            <button className="btn small" onClick={onTest} disabled={!!testing}>{testing ? "Testing…" : "Test"}</button>
            {editor !== k.id && <button className="btn small primary" onClick={onUse}>Use as AI editor</button>}
            <button className="btn small danger" onClick={remove}>Remove</button>
          </>
        ) : (
          <a className="btn small ghost" href={k.get} target="_blank" rel="noreferrer"><Icon name="external" size={14} /> Get a key</a>
        )}
      </div>
      <div className="more">
        {testing && <TaskProgress job={testing} compact />}
        {!k.set ? (
          <div className="row nowrap">
            <input type="password" placeholder={k.prefix ? `${k.prefix}…` : "Paste your API key"} value={val} autoComplete="off" spellCheck={false}
              onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && val && save()} aria-label={`${k.name} key`} />
            <button className="btn primary" onClick={save} disabled={busy || !val.trim()}><Icon name="key" size={14} /> Save key</button>
          </div>
        ) : (
          <div className="row nowrap">
            <span className="small dim" style={{ whiteSpace: "nowrap" }}>Model</span>
            <input type="text" value={model} onChange={(e) => setModel(e.target.value)} onBlur={saveModel} aria-label={`${k.name} model`} />
          </div>
        )}
        <span className="tiny dim">{k.training}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- privacy
function Privacy() {
  const [ai, setAi] = useState<AIOverview | null>(null);
  const { say } = useToast();
  useEffect(() => {
    api<AIOverview>("/ai").then(setAi).catch((e) => say(e.message, "error"));
  }, []);
  const put = async (body: object) => setAi(await api<AIOverview>("/ai", { method: "PUT", body }));
  const OPTS: [AIOverview["privacy"], string, string, string][] = [
    ["local", "Nothing", "lock", "No AI calls at all, except an AI running on this PC (Ollama)."],
    ["text", "Text only", "brief", "Transcripts and shot descriptions — never pictures."],
    ["thumbs", "Text + small thumbnails", "eye", "Adds small contact sheets so the AI editor can judge shots."],
  ];
  return (
    <>
      <h2>Privacy</h2>
      <p className="lead">Your videos, photos and audio never leave this computer, whatever you pick. File names and exact GPS are never sent.</p>
      <h3>What the AI editor may see</h3>
      <div className="set-group">
        {!ai ? <div className="skeleton" style={{ height: 110, margin: 14 }} /> : (
          <div className="privacy-opts" role="radiogroup" aria-label="What leaves this computer">
            {OPTS.map(([v, t, icon, s]) => (
              <button key={v} className={`pick${ai.privacy === v ? " on" : ""}`} role="radio" aria-checked={ai.privacy === v} onClick={() => put({ privacy: v })}>
                <div className="row nowrap"><Icon name={icon} size={16} /> <span className="t">{t}</span></div>
                <span className="s">{s}</span>
              </button>
            ))}
          </div>
        )}
        {ai && (
          <Row title="Blur faces in thumbnails" sub="Faces in the small contact sheets are blurred before they are sent.">
            <Switch on={ai.blur_faces} onChange={(v) => put({ blur_faces: v })} label="Blur faces in thumbnails" />
          </Row>
        )}
        <Row title="A record of everything sent" sub={<>Each AI call is saved in <code>.prepro/sent/</code> inside the shoot folder, so you can read exactly what left.</>} />
      </div>
    </>
  );
}

// ---------------------------------------------------------------- speech
function Speech() {
  const [sm, setSm] = useState<SpeechModels | null>(null);
  const [dl, setDl] = useState<Job | null>(null);
  const { say } = useToast();
  useEffect(() => {
    api<SpeechModels>("/models").then(setSm).catch(() => setSm(null));
  }, []);
  const download = async (name: string) => {
    try {
      const j = await api<Job>(`/models/${name}/download`, { body: {} });
      setDl(j);
      await followJob(j, setDl);
      say(`The ${name} speech model is ready — open a shoot to transcribe with it.`);
    } catch (e: any) {
      say(`Download failed: ${e.message}`, "error");
    } finally {
      setDl(null);
      setSm(await api<SpeechModels>("/models"));
    }
  };
  return (
    <>
      <h2>Speech recognition</h2>
      <p className="lead">Transcripts drive captions, the story and every cut on talking. They're made on this computer; your audio never leaves it.</p>
      <div className="set-group">
        {!sm ? <div className="skeleton" style={{ height: 200, margin: 14 }} /> : !sm.installed ? (
          <Row title="Not available in this build" sub="Only the basic offline recogniser is installed (English, rough words)." />
        ) : (
          sm.models.map((m) => (
            <div key={m.name} className="set-row">
              <input type="radio" name="asr" checked={m.current} disabled={!m.cached} aria-label={m.name}
                onChange={async () => setSm(await api<SpeechModels>("/models", { method: "PUT", body: { model: m.name } }))} />
              <div className="lbl"><b>{m.name}</b><span>{m.note}</span></div>
              {m.cached ? <span className="chip ok"><Icon name="check" size={12} /> On this PC</span> : (
                <button className="btn small" disabled={!!dl} onClick={() => download(m.name)}>
                  <Icon name="download" size={14} /> {m.size_mb >= 1000 ? `${(m.size_mb / 1000).toFixed(1)} GB` : `${m.size_mb} MB`}
                </button>
              )}
            </div>
          ))
        )}
      </div>
      {dl && <TaskProgress job={dl} />}
      <p className="small dim">Without a downloaded model PrePro uses a basic offline recogniser. Models download once from huggingface.co.</p>
    </>
  );
}

// ---------------------------------------------------------------- rendering
function Rendering() {
  const [g, setG] = useState<GeneralSettings | null>(null);
  useEffect(() => {
    api<GeneralSettings>("/settings").then(setG).catch(() => setG(null));
  }, []);
  const save = async (encoder: GeneralSettings["encoder"]) => setG(await api<GeneralSettings>("/settings", { method: "PUT", body: { encoder } }));
  const OPTS: [GeneralSettings["encoder"], string][] = [["auto", "Automatic"], ["cpu", "CPU"], ["nvenc", "NVIDIA"], ["qsv", "Intel"], ["amf", "AMD"]];
  return (
    <>
      <h2>Rendering</h2>
      <p className="lead">PrePro times your graphics card and your CPU once, then uses whichever is faster here. Not every PC has a usable GPU, and that's fine.</p>
      <div className="set-group">
        <Row title="Video encoder" sub="Automatic picks the GPU only when it is clearly faster on this PC; if the GPU fails mid-render, the CPU finishes.">
          {g && (
            <div className="seg" role="radiogroup" aria-label="Video encoder">
              {OPTS.map(([v, l]) => <button key={v} className={g.encoder === v ? "on" : ""} role="radio" aria-checked={g.encoder === v} onClick={() => save(v)}>{l}</button>)}
            </div>
          )}
        </Row>
        {g && Object.keys(g.encoder_times).length > 0 && (
          <Row title="Measured on this PC" sub="8 seconds of 1080p video">
            <div className="col" style={{ gap: 2, alignItems: "flex-end" }}>
              {Object.entries(g.encoder_times).sort((a, b) => a[1] - b[1]).map(([n, t], i) => (
                <span key={n} className={`small${i === 0 ? "" : " dim"}`}>{n}: <b>{t.toFixed(1)} s</b>{i === 0 ? " · fastest" : ""}</span>
              ))}
            </div>
          </Row>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- about
function About() {
  const [g, setG] = useState<GeneralSettings | null>(null);
  useEffect(() => {
    api<GeneralSettings>("/settings").then(setG).catch(() => setG(null));
  }, []);
  return (
    <>
      <h2>About PrePro</h2>
      <p className="lead">The AI pre-editor for creators: your shoot in, a finished first cut out — about 90 % of the edit, ready for you to refine.</p>
      <div className="set-group">
        <Row title="Version" sub={g ? `PrePro ${g.version}` : "…"} />
        <Row title="Your data" sub={g ? g.data_dir : "…"} />
        <Row title="Releases and what's new"><a className="btn small" href="https://github.com/buildcool/PrePro/releases" target="_blank" rel="noreferrer"><Icon name="external" size={14} /> Open</a></Row>
        <Row title="Privacy" sub="Footage never leaves this PC. Only text (and, if you allow, small thumbnails) goes to the AI editor you choose." />
        <Row title="Logos" sub="Claude, Anthropic, ChatGPT, OpenAI, Gemini, Grok, xAI, OpenRouter and Ollama are trademarks of their owners, shown only to name the service you connect; PrePro isn't affiliated with them. Logo files: LobeHub lobe-icons (MIT)." />
      </div>
    </>
  );
}
