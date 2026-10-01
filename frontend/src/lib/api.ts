// Typed API client for the VIGIL backend (same origin; session cookie + bearer fallback).

export type Role = "viewer" | "analyst" | "admin";
export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface Me {
  id: string;
  username: string;
  role: Role;
}

export interface CameraStats {
  camera_id: string;
  status: string;
  fps: number;
  latency_ms: number | null;
  active_tracks: number;
  frames: number;
  resolution: [number, number] | null;
  viewers: number;
  source_connected: boolean;
  source_error: string | null;
  reconnects: number;
  progress: number | null;
  violence: Record<string, number>;
  stage_ms?: Record<string, number>;
  idle?: boolean;
  motion?: number;
  skipped_frames?: number;
  tracks_total: number;
  signals: number;
  faces: number;
}

export interface Camera {
  is_demo?: boolean;
  id: string;
  name: string;
  source_type: "frs" | "rtsp" | "http" | "file" | "demo" | "browser";
  source_uri: string;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  enabled: boolean;
  loop: boolean;
  realtime: boolean;
  analysis_fps: number | null;
  config: Record<string, unknown>;
  created_at: string | null;
  stats: CameraStats | null;
  zones?: Zone[];
}

export interface Zone {
  id: string;
  camera_id: string;
  name: string;
  kind: "restricted" | "monitored" | "entry";
  polygon: [number, number][];
  rules: Record<string, unknown>;
  enabled: boolean;
}

export interface Evidence {
  keyframe: string | null;
  clip: string | null;
  frames: string[];
}

export interface Verification {
  verdict?: string;
  confidence?: number;
  answer?: string;
  observations?: string[];
  model?: string;
  reasoning?: string;
  run_id?: string;
  human?: { verdict: string; by: string; note: string | null; at: string };
}

export interface VEvent {
  is_demo?: boolean;
  id: string;
  ts: string;
  camera_id: string | null;
  type: string;
  severity: Severity;
  confidence: number;
  title: string;
  description: string | null;
  track_ids: string[];
  identity_ids: string[];
  explanation: Record<string, any>;
  evidence: Evidence;
  status: string;
  verification: Verification;
  incident_id: string | null;
  agent_runs?: AgentRun[];
}

export interface Conclusion {
  summary?: string;
  timeline?: string[];
  persons?: { id?: string; role?: string; notes?: string }[];
  assessment?: string;
  threat_level?: string;
  confidence?: number;
  key_evidence?: string[];
  recommended_actions?: string[];
  run_id?: string;
  at?: string;
  _tool_calls?: number;
}

export interface Incident {
  is_demo?: boolean;
  id: string;
  created_at: string;
  updated_at: string;
  title: string;
  type: string;
  severity: Severity;
  status: string;
  camera_id: string | null;
  summary: string | null;
  conclusion: Conclusion;
  confidence: number;
  identity_ids: string[];
  report_md?: string | null;
  notes: { ts: string; by: string; text: string; changes?: Record<string, unknown> }[];
  assigned_to: string | null;
  event_count?: number;
  events?: VEvent[];
  agent_runs?: AgentRun[];
}

export interface AgentStep {
  i: number;
  t: number;
  kind: string;
  text?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  output?: any;
  action?: boolean;
  tools?: string[];
  [k: string]: unknown;
}

export interface AgentRun {
  id: string;
  agent: string;
  trigger: string;
  incident_id: string | null;
  event_id: string | null;
  status: string;
  model: string | null;
  started_at: string;
  finished_at: string | null;
  steps: AgentStep[];
  output: any;
  error: string | null;
  step_count?: number;
}

export interface Identity {
  is_demo?: boolean;
  id: string;
  display_name: string | null;
  label: string;
  kind: string;
  category: string;
  notes: string | null;
  tags: string[];
  watchlist: boolean;
  frs_criminal_id: string | null;
  frs_name: string | null;
  frs_score: number | null;
  frs_checked_at: string | null;
  first_seen: string | null;
  last_seen: string | null;
  last_camera_id: string | null;
  sightings: number;
  face_url: string | null;
  created_at: string | null;
  face_vectors?: number;
  appearances?: number;
  frs_searches?: FrsSearch[];
  tracks?: Track[];
  events?: VEvent[];
  cameras?: { camera_id: string; sightings: number; dwell_s: number }[];
}

export interface Track {
  is_demo?: boolean;
  id: string;
  camera_id: string;
  local_id: number;
  identity_id: string | null;
  identity_score: number | null;
  identity_method: string | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number;
  max_speed: number;
  mean_speed: number;
  zones: Record<string, number>;
  face_url: string | null;
  person_url: string | null;
  attributes: Record<string, unknown>;
  anomaly_score: number;
  closed: boolean;
  path?: [number, number, number][];
}

export interface FrsSearch {
  id: string;
  ts: string;
  identity_id: string | null;
  camera_id: string | null;
  track_id: string | null;
  trigger: string;
  outcome: "match" | "no_match" | "no_face" | "error" | string;
  criminal_id: string | null;
  name: string | null;
  score: number | null;
  top_k: { name: string; criminal_id: string; score: number }[];
  latency_ms: number | null;
  face_url: string | null;
  error: string | null;
  is_demo?: boolean;
}

export interface Paged<T> {
  total: number;
  items: T[];
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

const TOKEN_KEY = "vigil.token";
export const token = {
  get: () => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string | null) => {
    try {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable: cookie session still works */
    }
  },
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function detailMessage(detail: unknown, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join("; ");
  if (typeof detail === "object" && detail && "message" in detail) return String((detail as any).message);
  return JSON.stringify(detail);
}

// ── demo-data mode: applied centrally to every list / analytics call ──
export type DemoMode = "exclude" | "include" | "only";
let demoMode: DemoMode = "include";
export const getDemoMode = () => demoMode;
export const setDemoModeForApi = (m: DemoMode) => {
  demoMode = m;
};
const DEMO_AWARE = /^\/api\/(events|incidents|identities|tracks|cameras|frs\/feed|analytics\/overview|analytics\/cameras)(\?|$)/;
function withDemo(path: string, method?: string): string {
  if ((method ?? "GET") !== "GET" || !DEMO_AWARE.test(path) || /[?&]demo=/.test(path)) return path;
  return path + (path.includes("?") ? "&" : "?") + "demo=" + demoMode;
}

export async function api<T = any>(path: string, opts: RequestInit & { json?: unknown } = {}): Promise<T> {
  path = withDemo(path, opts.method);
  const headers = new Headers(opts.headers);
  const t = token.get();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  let body = opts.body;
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opts.json);
  }
  const res = await fetch(path, { ...opts, headers, body, credentials: "same-origin" });
  if (res.status === 401 && !path.startsWith("/api/auth/login")) {
    onUnauthorized?.();
  }
  const ct = res.headers.get("content-type") ?? "";
  const payload = ct.includes("application/json") ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    const detail = payload && typeof payload === "object" ? (payload as any).detail : payload;
    throw new ApiError(res.status, detailMessage(detail, `${res.status} ${res.statusText}`), detail);
  }
  return payload as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, json?: unknown) => api<T>(p, { method: "POST", json: json ?? {} });
export const patch = <T = any>(p: string, json: unknown) => api<T>(p, { method: "PATCH", json });
export const put = <T = any>(p: string, json: unknown) => api<T>(p, { method: "PUT", json });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });
export const postForm = <T = any>(p: string, form: FormData) => api<T>(p, { method: "POST", body: form });

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

/** Media URLs are authenticated by the HttpOnly session cookie (same origin); no token in URLs. */
export function mediaUrl(u: string | null | undefined): string | undefined {
  return u ?? undefined;
}

/** FRS media paths (/media/uploads/criminals/...) are served through our authenticated proxy. */
export function frsMedia(u: string | null | undefined): string | undefined {
  if (!u) return undefined;
  return mediaUrl("/api/frs/media/" + u.replace(/^\/?media\//, ""));
}

export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const t = token.get();
  return `${proto}://${location.host}${path}${t ? `?token=${encodeURIComponent(t)}` : ""}`;
}
