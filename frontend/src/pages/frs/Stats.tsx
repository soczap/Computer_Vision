import type { ReactNode } from "react";
import { Activity, Cpu, Database, Gauge, Radar, ScanFace, Timer } from "lucide-react";
import { num } from "../../lib/format";
import { StatTile, BarList } from "../../components/charts";
import { Badge, Card, Empty, KV, Skeleton, SkeletonRows } from "../../components/ui";
import { FrsShell, OUTCOME, useFrsOverview } from "./common";

interface LatRow { key: string; label: ReactNode; p50: number; p95: number; note?: string }

/** One axis (ms): bar = p50, tick = p95. Values stay in ink; the bar carries identity. */
function LatencyChart({ rows }: { rows: LatRow[] }) {
  if (!rows.length) return <Empty title="No latency samples yet" />;
  const max = Math.max(1, ...rows.map((r) => r.p95));
  return (
    <div className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[minmax(0,210px)_1fr_120px] items-center gap-3" title={`p50 ${r.p50.toFixed(1)} ms · p95 ${r.p95.toFixed(1)} ms`}>
          <span className="min-w-0">
            <span className="block truncate text-[12.5px] text-ink-2">{r.label}</span>
            {r.note && <span className="block truncate text-[10.5px] text-muted">{r.note}</span>}
          </span>
          <span className="relative h-3 rounded-r bg-surface-2">
            <span className="absolute inset-y-0 left-0 rounded-r bg-[#3987e5]" style={{ width: `${(r.p50 / max) * 100}%`, minWidth: 2 }} />
            {r.p95 > r.p50 && <span className="absolute -top-1 bottom-[-4px] w-[2px] rounded bg-ink" style={{ left: `calc(${(r.p95 / max) * 100}% - 1px)` }} />}
          </span>
          <span className="tabular text-right text-[12px] text-ink">{r.p50.toFixed(1)} {r.p95 > r.p50 ? <span className="text-muted">/ {r.p95.toFixed(1)} ms</span> : <span className="text-muted">ms</span>}</span>
        </div>
      ))}
      <div className="mt-1 flex items-center gap-4 text-[11px] text-muted">
        <span className="flex items-center gap-1.5"><span className="h-2 w-4 rounded-sm bg-[#3987e5]" /> p50</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-[2px] bg-ink" /> p95</span>
      </div>
    </div>
  );
}

export default function FrsStats() {
  const ov = useFrsOverview();
  const d = ov.data;
  const v = d?.vigil;
  const b = d?.frs_backend;
  const lat: LatRow[] = [];
  if (v?.face_pipeline_ms != null) lat.push({ key: "vp", label: "VIGIL face pipeline", p50: v.face_pipeline_ms, p95: v.face_pipeline_ms, note: "detect + align + embed per batch (mean)" });
  if (v?.frs_search_latency_ms) lat.push({ key: "rt", label: "FRS search round-trip", p50: v.frs_search_latency_ms.p50, p95: v.frs_search_latency_ms.p95, note: "VIGIL → :8000 /api/match (24 h)" });
  const names: Record<string, string> = { person_detect: "FRS person detect", face_detect: "FRS face detect", embed: "FRS embed", vector_search: "FRS vector search" };
  for (const [k, x] of Object.entries(b?.latency_ms ?? {})) lat.push({ key: k, label: names[k] ?? k, p50: x.p50, p95: x.p95, note: `FRS internal · ${x.count} samples` });
  const outcomes = Object.entries(v?.frs_searches_by_outcome ?? {}).map(([k, n]) => ({ key: k, label: OUTCOME[k]?.label ?? k, value: n, color: OUTCOME[k]?.color }));

  return (
    <FrsShell title="Stats" subtitle="Recognition performance, gallery sizes, search outcomes and operating thresholds — VIGIL and the FRS backend side by side">
      {!d ? <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[84px]" />)}</div> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <StatTile label="VIGIL face pipeline" icon={<Timer size={13} />} value={v!.face_pipeline_ms != null ? `${v!.face_pipeline_ms.toFixed(1)} ms` : "—"} sub={v!.face_on_gpu ? "on GPU (CUDA)" : v!.face_on_gpu === false ? "CPU fallback" : "—"} />
            <StatTile label="FRS search round-trip" icon={<Radar size={13} />} value={v!.frs_search_latency_ms ? `${v!.frs_search_latency_ms.p50.toFixed(0)} ms` : "—"} sub={v!.frs_search_latency_ms ? `p95 ${v!.frs_search_latency_ms.p95.toFixed(0)} ms` : "no searches in 24 h"} />
            <StatTile label="FRS embed / search" icon={<Cpu size={13} />} value={b?.latency_ms?.embed ? `${b.latency_ms.embed.p50.toFixed(1)} ms` : "—"} sub={b?.latency_ms?.vector_search ? `vector search p50 ${b.latency_ms.vector_search.p50.toFixed(2)} ms` : "—"} />
            <StatTile label="FRS searches (24 h)" icon={<Activity size={13} />} value={num(v!.frs_searches_24h)} sub={`${v!.frs_searches_by_outcome.match ?? 0} candidate matches`} />
            <StatTile label="Identified (24 h)" icon={<ScanFace size={13} />} value={num(v!.identified_appearances_24h)} sub={`${v!.counters.matches ?? 0} track matches since start`} />
            <StatTile label="FRS analysed fps" icon={<Gauge size={13} />} value={b?.analysed_fps != null ? b.analysed_fps.toFixed(1) : "—"} sub="its own cameras, station-wide" />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card title="Recognition latency (ms)"><LatencyChart rows={lat} /></Card>
            <Card title="Watchlist search outcomes (24 h)">
              <BarList items={outcomes} empty={<Empty title="No searches in the last 24 h" />} />
              <div className="mt-3 text-[11px] leading-relaxed text-muted">A candidate match needs FRS's two-recogniser agreement and open-set gate. It is always a candidate for human verification.</div>
            </Card>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card title={<span className="flex items-center gap-2"><Database size={14} /> VIGIL gallery</span>}>
              <KV k="Identities" v={num(v!.identities)} mono />
              <KV k="Enrolled (named)" v={num(v!.enrolled)} mono />
              <KV k="Unknown (re-identified)" v={num(v!.unknown)} mono />
              <KV k="Watchlist candidates" v={num(v!.watchlist_candidates)} mono />
              <KV k="Face vectors" v={num(v!.gallery_vectors)} mono />
            </Card>
            <Card title={<span className="flex items-center gap-2"><Database size={14} /> FRS gallery (read-only)</span>}>
              {b?.gallery ? (
                <>
                  <KV k="Subjects" v={num(b.gallery.subjects)} mono />
                  <KV k="Embeddings" v={num(b.gallery.embeddings)} mono />
                  <KV k="FAISS vectors" v={num(b.gallery.faiss_vectors)} mono />
                  <KV k="Match events logged" v={num(b.gallery.match_events)} mono />
                  <KV k="Detections today" v={num(b.gallery.detections_today)} mono />
                </>
              ) : <SkeletonRows n={4} h="h-5" />}
            </Card>
            <Card title="Operating thresholds">
              <div className="label mb-1">VIGIL re-identification</div>
              <KV k="Match cosine" v={`sim ≥ ${v!.thresholds.match.toFixed(2)}`} mono />
              <KV k="Margin over runner-up" v={v!.thresholds.margin.toFixed(2)} mono />
              <KV k="Min face size" v={`${v!.thresholds.min_face_px} px`} mono />
              <KV k="Min face quality" v={v!.thresholds.min_quality.toFixed(2)} mono />
              <div className="label mb-1 mt-3">FRS watchlist</div>
              <KV k="Match cosine" v={b?.thresholds ? `sim ≥ ${b.thresholds.threshold.toFixed(2)}` : "—"} mono />
              <KV k="Open-set z-gate" v={b?.thresholds ? `z ≥ ${b.thresholds.open_set_z_min}` : "—"} mono />
              <KV k="Top-k" v={b?.thresholds?.top_k ?? "—"} mono />
            </Card>
            <Card title="FRS backend health">
              <KV k="Link" v={b?.reachable ? <Badge color="#0ca30c">reachable</Badge> : <Badge color="#d03b3b">unreachable</Badge>} />
              <KV k="Status" v={b?.status ?? b?.error ?? "—"} />
              <KV k="GPU" v={b?.gpu ? <Badge color="#0ca30c">CUDA</Badge> : b?.gpu === false ? <Badge color="#d03b3b">degraded</Badge> : "—"} />
              <KV k="Access" v={<Badge color="#9085e9">read-only</Badge>} />
              <KV k="URL" v={<span className="font-mono text-[11px]">{b?.url}</span>} />
              <div className="mt-2 text-[11px] text-muted">VIGIL counters: {Object.entries(v!.counters).map(([k, n]) => `${k.replace(/_/g, " ")} ${n}`).join(" · ")}</div>
            </Card>
          </div>
        </>
      )}
    </FrsShell>
  );
}
