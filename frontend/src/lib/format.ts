import type { Severity } from "./api";

export const TZ = "Asia/Kolkata";

const dtFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});
const tFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});
const dFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "2-digit", month: "short", year: "numeric" });

export function parseTs(s: string | number | null | undefined): Date | null {
  if (s === null || s === undefined || s === "") return null;
  if (typeof s === "number") return new Date(s < 1e12 ? s * 1000 : s);
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : s + "Z");
  return isNaN(d.getTime()) ? null : d;
}

export const fmtDateTime = (s: string | number | null | undefined) => {
  const d = parseTs(s);
  return d ? dtFmt.format(d) : "—";
};
export const fmtTime = (s: string | number | null | undefined) => {
  const d = parseTs(s);
  return d ? tFmt.format(d) : "—";
};
export const fmtDate = (s: string | number | null | undefined) => {
  const d = parseTs(s);
  return d ? dFmt.format(d) : "—";
};

export function ago(s: string | number | null | undefined): string {
  const d = parseTs(s);
  if (!d) return "—";
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export function dur(s: number | null | undefined): string {
  if (s === null || s === undefined || isNaN(s)) return "—";
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

/** Similarity is a cosine, never a percentage or probability. */
export const sim = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `sim ${v.toFixed(2)}`);
export const num = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined || isNaN(v) ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
export const conf = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(2));

export const SEVERITIES: Severity[] = ["info", "low", "medium", "high", "critical"];
export const SEV_RANK: Record<string, number> = { info: 0, low: 1, medium: 2, high: 3, critical: 4 };
export const SEV_COLOR: Record<string, string> = {
  info: "#898781", low: "#6da7ec", medium: "#fab219", high: "#ec835a", critical: "#d03b3b",
};

export const KIND_COLOR: Record<string, string> = {
  watchlist: "#e66767", watch: "#d95926", known: "#0ca30c", reidentified: "#3987e5", unresolved: "#898781",
};
export const KIND_LABEL: Record<string, string> = {
  watchlist: "Watchlist candidate", watch: "Watch / banned", known: "Enrolled", reidentified: "Re-identified", unresolved: "Unresolved",
};

export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

export const EVENT_TYPE_LABEL: Record<string, string> = {
  violence: "Physical violence", watchlist_match: "Watchlist match (FRS)", weapon: "Weapon visible",
  fall: "Person down / fall", zone_intrusion: "Restricted zone intrusion", loitering: "Loitering",
  abandoned_object: "Unattended object", crowd: "Crowd gathering", running: "Running",
  after_hours: "After-hours presence", pacing: "Pacing / casing", anomalous_path: "Anomalous trajectory",
  repeated_appearance: "Repeated appearance", occupancy: "Zone over capacity",
  suspicious_pattern: "Correlated suspicious behaviour",
};
export const typeLabel = (t: string) => EVENT_TYPE_LABEL[t] ?? t.replace(/_/g, " ");

export const STATUS_LABEL: Record<string, string> = {
  open: "Open", pending_verification: "Verifying", verified: "Verified", rejected: "Rejected by VLM",
  needs_review: "Needs review", dismissed: "Dismissed", new: "New", investigating: "Investigating",
  confirmed: "Confirmed", false_positive: "False positive", resolved: "Resolved",
};
export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s;

export function titleCase(s: string) {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
