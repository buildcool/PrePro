export interface ProjectRow {
  id: string;
  name: string;
  path: string;
  exists: boolean;
  analysed: boolean;
  timelines: number;
  opened?: number;
}

export interface HookOption {
  id: string;
  kind: string;
  refs: string[];
  text_hook: string | null;
  why: string;
  score: number;
}

export interface Knobs {
  pace: number;
  effects: "clean" | "balanced" | "bold";
  captions: "off" | "clean" | "bold";
  humour: "off" | "light" | "heavy";
  target_length: number | null;
  look: string | null;
}

export interface Direction {
  id: string;
  playbook: string;
  name: string;
  aspect: string;
  target_min: number;
  target_max: number;
  fit_score: number;
  why: string;
  hooks: HookOption[];
  outline: string[];
  knobs: Knobs;
  coverage_gaps: string[];
  from_brief: boolean;
}

export interface Rule {
  kind: string;
  target: string | null;
  anchor: string | null;
  value: unknown;
  source: string;
  resolved: boolean;
}

export interface Brief {
  rules: Rule[];
  prefs: Record<string, unknown>;
  questions: { text: string }[];
  raw_text: string;
}

export interface Summary {
  id: string;
  path: string;
  name: string;
  analysed: boolean;
  counts: Record<string, number>;
  stats: Record<string, number>;
  warnings: string[];
  genres: { playbook: string; score: number; why?: string }[];
  timelines: { id: string; name: string; duration: number; playbook: string; updated: number; aspect: string }[];
  directions: { directions: Direction[]; notes: string } | null;
  shorts: { directions: Direction[]; notes: string } | null;
  talk_seconds: number;
  brief: { text: string; parsed: Brief | null };
}

export interface Asset {
  id: string;
  name: string;
  path: string;
  kind: string;
  duration: number;
  fps: number | null;
  size: [number, number] | null;
  day: number | null;
  place: string | null;
  thumb: string | null;
  shots: { id: string; t0: number; t1: number; flags: string[]; tags: string[]; desc: string | null; quality: number; move: string; thumb: string }[];
  segments: { id: string; t0: number; t1: number; text: string; cut: string | null }[];
  music: { bpm: number; mood: string[]; key: string | null } | null;
}

export interface Item {
  id: string;
  ref: string | null;
  track: string;
  kind: string;
  asset_id: string | null;
  src_in: number;
  src_out: number;
  rec_in: number;
  speed: number;
  transform: { zoom: number } | null;
  transition_in: string;
  text: string | null;
  style: string | null;
  duration: number | null;
  role: string | null;
  section: string | null;
  note: string;
}

export interface Suggestion {
  id: string;
  type: string;
  status: "applied" | "optional" | "rejected";
  confidence: number;
  reason: string;
  source: string;
  t: number | null;
  payload: Record<string, any>;
  alternatives: string[];
}

export interface Caption {
  t0: number;
  t1: number;
  text?: string;
  words: { text: string }[];
}

export const capText = (c: Caption) => c.text ?? c.words.map((w) => w.text).join(" ");

/** Thumbnail for a story ref: shots have their own keyframes; a spoken line uses its clip's first shot. */
export const refThumb = (ref: string) => `frames/${ref.includes(".k") ? ref : ref.split(".")[0] + ".k0"}_1.jpg`;

export interface Timeline {
  id: string;
  name: string;
  direction_id: string;
  playbook: string;
  fps: number;
  width: number;
  height: number;
  items: Item[];
  captions: Caption[];
  suggestions: Suggestion[];
  look: string | null;
  meta: Record<string, any>;
}

export interface Comment {
  id: string;
  t: number;
  text: string;
  status: "applied" | "partly" | "not_understood";
  reply: string;
  source: string;
}

export interface View {
  timeline: Timeline;
  duration: number;
  assets: Record<string, string>;
  lint: { rule: string; severity: string; msg: string; t: number | null }[];
  critic: { scores: Record<string, number>; issues: string[]; summary: string; source: string } | null;
  compliance: { ok: boolean; rule: string; source: string; detail: string }[];
  revision: { ops: unknown[]; comments: Comment[] };
  direction: Direction | null;
  attention: number[];
  paper_edit: string;
  render: string | null;
  render_stale: boolean;
  packaging: Packaging | null;
}

export interface Packaging {
  titles: string[];
  chapters: [number, string][];
  chapters_note: string;
  description: string;
  hashtags: string[];
  thumbs: { path: string; frame: string; asset_id: string; t: number; why: string; score: number }[];
  text_on_thumb: string;
}

export interface Brains {
  connectors: { name: string; kind: string; model: string | null; detected: boolean; training: string; local: boolean }[];
  kinds: string[];
  routing: Record<string, string>;
  privacy: "local" | "text" | "thumbs";
  blur_faces: boolean;
  monthly_cap_usd: number;
}

export const itemDur = (i: Item) =>
  ["text", "image", "color"].includes(i.kind) && i.duration != null ? i.duration : Math.max(0, (i.src_out - i.src_in) / Math.max(i.speed || 1, 1e-6));
