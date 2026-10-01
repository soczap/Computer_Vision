import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Database, Gauge, Link2, ScanFace, Search } from "lucide-react";
import { get, type FrsSearch } from "../../lib/api";
import { Badge, cx } from "../../components/ui";

export interface FrsOverview {
  vigil: {
    identities: number; enrolled: number; unknown: number; watchlist_candidates: number; gallery_vectors: number;
    identified_appearances_24h: number;
    counters: Record<string, number>;
    face_pipeline_ms: number | null; face_on_gpu: boolean | null;
    frs_searches_24h: number; frs_searches_by_outcome: Record<string, number>;
    frs_search_latency_ms: { p50: number; p95: number } | null;
    thresholds: { match: number; margin: number; min_face_px: number; min_quality: number };
  };
  frs_backend: {
    url: string; reachable: boolean; status?: string; gpu?: boolean;
    gallery?: { subjects: number; embeddings: number; faiss_vectors: number; match_events: number; detections_today: number };
    recognition?: Record<string, unknown>;
    thresholds?: { threshold: number; open_set_z_min: number; top_k: number };
    latency_ms?: Record<string, { p50: number; p95: number; p99: number; count: number }>;
    analysed_fps?: number;
    error?: string;
  };
  read_only: boolean;
}

export const useFrsOverview = () =>
  useQuery({ queryKey: ["frs-overview"], queryFn: () => get<FrsOverview>("/api/frs/overview"), refetchInterval: 15000 });

/** Identity states used consistently across the FRS workspace. */
export const STATE: Record<string, { label: string; color: string }> = {
  watchlist_candidate: { label: "Watchlist candidate — verify", color: "#e66767" },
  known: { label: "Known (enrolled)", color: "#0ca30c" },
  reidentified: { label: "Re-identified", color: "#3987e5" },
  new_identity: { label: "New identity", color: "#9085e9" },
  collecting: { label: "Collecting views", color: "#fab219" },
  no_face: { label: "No usable face", color: "#898781" },
};

export function StateChip({ state }: { state: string }) {
  const s = STATE[state] ?? { label: state, color: "#898781" };
  return (
    <Badge color={s.color}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </Badge>
  );
}

export const OUTCOME: Record<string, { label: string; color: string }> = {
  match: { label: "Candidate match", color: "#e66767" },
  MATCH: { label: "Candidate match", color: "#e66767" },
  no_match: { label: "No match", color: "#0ca30c" },
  NO_MATCH: { label: "No match", color: "#0ca30c" },
  no_face: { label: "No usable face", color: "#898781" },
  NO_FACE: { label: "No usable face", color: "#898781" },
  error: { label: "Error", color: "#fab219" },
};
export function OutcomeChip({ outcome }: { outcome: string }) {
  const o = OUTCOME[outcome] ?? { label: outcome.replace(/_/g, " ").toLowerCase(), color: "#898781" };
  return <Badge color={o.color}>{o.label}</Badge>;
}

export const frsImg = (u: string | null | undefined) =>
  !u ? undefined : u.startsWith("/api/") || u.startsWith("data:") || u.startsWith("/media/demo") ? u : u.startsWith("/media/uploads") || u.startsWith("/media/alerts") ? "/api/frs" + u : u;

const TABS = [
  { to: "/frs", label: "Console", end: true },
  { to: "/frs/identities", label: "Identities" },
  { to: "/frs/enroll", label: "Enrol" },
  { to: "/frs/watchlist", label: "Watchlist" },
  { to: "/frs/searches", label: "Searches" },
  { to: "/frs/stats", label: "Stats" },
];

/** Header strip for every FRS page: link status, gallery sizes, searches today. */
export function FrsShell({ title, subtitle, actions, children }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  const ov = useFrsOverview();
  const b = ov.data?.frs_backend;
  const v = ov.data?.vigil;
  return (
    <div className="mx-auto max-w-[1600px]">
      <div className="mb-4 overflow-hidden rounded-[10px] border border-[#9085e944] bg-[linear-gradient(90deg,rgba(144,133,233,0.10),rgba(57,135,229,0.04))]">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 text-[12px]">
          <span className="flex items-center gap-2 text-[13px] font-semibold tracking-wide text-ink"><ScanFace size={16} className="text-[#9085e9]" /> FRS · Face recognition</span>
          <span className="flex items-center gap-1.5 text-ink-2" title={b?.url}>
            <Link2 size={12} />
            FRS backend :8000
            {ov.isLoading ? <span className="text-muted">…</span> : b?.reachable ? <Badge color="#0ca30c">linked · read-only</Badge> : <Badge color="#d03b3b">unreachable</Badge>}
          </span>
          <span className="flex items-center gap-1.5 text-ink-2"><Database size={12} /> FRS watchlist <b className="tabular text-ink">{b?.gallery?.subjects ?? "—"}</b> subjects</span>
          <span className="flex items-center gap-1.5 text-ink-2"><ScanFace size={12} /> VIGIL gallery <b className="tabular text-ink">{v?.identities ?? "—"}</b> identities · <b className="tabular text-ink">{v?.gallery_vectors ?? "—"}</b> vectors</span>
          <span className="flex items-center gap-1.5 text-ink-2"><Search size={12} /> Watchlist searches (24 h) <b className="tabular text-ink">{v?.frs_searches_24h ?? "—"}</b></span>
          {v?.face_pipeline_ms != null && <span className="flex items-center gap-1.5 text-ink-2"><Gauge size={12} /> face pipeline <b className="tabular text-ink">{v.face_pipeline_ms.toFixed(1)} ms</b> {v.face_on_gpu ? "GPU" : "CPU"}</span>}
        </div>
        <nav className="flex gap-1 border-t border-[#9085e933] px-3">
          {TABS.map((t) => (
            <NavLink key={t.to} to={t.to} end={t.end}
              className={({ isActive }) => cx("-mb-px border-b-2 px-3 py-2 text-[12.5px] font-medium", isActive ? "border-[#9085e9] text-ink" : "border-transparent text-muted hover:text-ink-2")}>
              {t.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[18px] font-semibold tracking-tight">{title}</h1>
          {subtitle && <div className="mt-0.5 text-[12.5px] text-muted">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export type { FrsSearch };
