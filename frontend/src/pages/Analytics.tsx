import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get, type Camera } from "../lib/api";
import { dur, num, SEV_COLOR, SEVERITIES, SERIES, typeLabel } from "../lib/format";
import { BarList, Histogram, SeriesChart, StatTile } from "../components/charts";
import { Card, DemoBadge, Empty, PageHeader, Skeleton, SkeletonRows, Toggle, cx } from "../components/ui";
import { isDemo, useDataMode } from "../lib/datamode";
import { bucketLabel, type Overview } from "./CommandCenter";

const RANGES = [{ h: 1, l: "1h" }, { h: 6, l: "6h" }, { h: 24, l: "24h" }, { h: 168, l: "7d" }, { h: 720, l: "30d" }];

export default function Analytics() {
  const nav = useNavigate();
  const { mode } = useDataMode();
  const [hours, setHours] = useState(24);
  const [camera, setCamera] = useState("");
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => get<Camera[]>("/api/cameras") });
  const ov = useQuery({
    queryKey: ["overview", hours, camera],
    queryFn: () => get<Overview>(`/api/analytics/overview?hours=${hours}${camera ? `&camera_id=${encodeURIComponent(camera)}` : ""}`),
    refetchInterval: 60000,
  });
  const camStats = useQuery({
    queryKey: ["cam-stats", hours],
    queryFn: () => get<{ camera_id: string; name: string; sightings: number; events: number }[]>(`/api/analytics/cameras?hours=${hours}`),
  });
  const o = ov.data;
  const byType = useMemo(() => Object.entries(o?.events_by_type ?? {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, label: typeLabel(k), value: v })), [o]);
  const bySev = useMemo(() => SEVERITIES.slice().reverse().filter((s) => o?.events_by_severity[s]).map((s) => ({ key: s, label: s, value: o!.events_by_severity[s], color: SEV_COLOR[s] })), [o]);
  const heatCam = camera || cams.data?.find((c) => c.stats)?.id || cams.data?.[0]?.id || "";

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader
        title="Analytics"
        subtitle={<>Footfall, dwell, behaviour and event trends{mode !== "exclude" && <> · <span className="font-semibold text-[#fab219]">{mode === "only" ? "demo data only" : "incl. demo data"}</span></>}</>}
        actions={
          <>
            <select className="input" value={camera} onChange={(e) => setCamera(e.target.value)} aria-label="Camera">
              <option value="">All cameras</option>
              {(cams.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <div className="flex gap-1">
              {RANGES.map((r) => <button key={r.h} className={cx("btn btn-sm", hours === r.h && "btn-primary")} onClick={() => setHours(r.h)}>{r.l}</button>)}
            </div>
          </>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {o ? (
          <>
            <StatTile label="Sightings" value={num(o.sightings)} />
            <StatTile label="Unique identities" value={num(o.unique_identities)} />
            <StatTile label="Identified share" value={`${Math.round(o.identified_share * 100)}%`} />
            <StatTile label="Median dwell" value={dur(o.dwell.median_s)} sub={`p90 ${dur(o.dwell.p90_s)}`} />
            <StatTile label="Events" value={num(o.events)} />
          </>
        ) : Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[84px]" />)}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Sightings">{o ? <SeriesChart data={o.series} dataKey="sightings" name="Sightings" color={SERIES[0]} xFmt={bucketLabel} height={180} /> : <Skeleton className="h-[180px]" />}</Card>
        <Card title="Events">{o ? <SeriesChart data={o.series} dataKey="events" name="Events" color={SERIES[1]} xFmt={bucketLabel} height={180} /> : <Skeleton className="h-[180px]" />}</Card>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Events by type">{o ? <BarList items={byType} onClick={(k) => nav(`/events?type=${k}`)} empty={<Empty title="No events" />} /> : <SkeletonRows n={4} h="h-4" />}</Card>
        <Card title="Events by severity">{o ? <BarList items={bySev} onClick={(k) => nav(`/events?severity=${k}`)} empty={<Empty title="No events" />} /> : <SkeletonRows n={4} h="h-4" />}</Card>
        <Card title="Dwell time per sighting">{o ? <Histogram data={o.dwell.histogram} name="Sightings" /> : <Skeleton className="h-[160px]" />}</Card>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        {cams.isLoading ? <Skeleton className="h-[420px]" /> : heatCam ? <SpatialCard cameraId={heatCam} cameras={cams.data ?? []} hours={hours} /> : <Card title="Spatial"><Empty title="No cameras" /></Card>}
        <Card title="Per camera" bodyClass="p-0">
          {camStats.isLoading ? <div className="p-4"><SkeletonRows n={3} /></div> : (
            <table className="w-full text-left text-[12.5px]">
              <thead className="border-b border-line text-[11.5px] text-muted"><tr><th className="px-4 py-2 font-medium">Camera</th><th className="px-2 py-2 text-right font-medium">Sightings</th><th className="px-4 py-2 text-right font-medium">Events</th></tr></thead>
              <tbody>
                {(camStats.data ?? []).map((c) => (
                  <tr key={c.camera_id} className="border-b border-line last:border-0">
                    <td className="px-4 py-2"><span className="flex items-center gap-1.5">{c.name}{isDemo({ camera_id: c.camera_id }) && <DemoBadge compact />}</span><div className="font-mono text-[11px] text-muted">{c.camera_id}</div></td>
                    <td className="tabular px-2 py-2 text-right">{c.sightings}</td>
                    <td className="tabular px-4 py-2 text-right">{c.events}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}

function SpatialCard({ cameraId, cameras, hours }: { cameraId: string; cameras: Camera[]; hours: number }) {
  const [cam, setCam] = useState(cameraId);
  const [showHeat, setShowHeat] = useState(true);
  const [showPaths, setShowPaths] = useState(true);
  const heat = useQuery({ queryKey: ["heat", cam], queryFn: () => get<{ rows: number; cols: number; samples: number; grid: number[][] | null }>(`/api/analytics/heatmap/${cam}`) });
  const paths = useQuery({
    queryKey: ["paths", cam, hours],
    queryFn: () => get<{ id: string; identity_id: string | null; path: [number, number][]; anomaly: number }[]>(`/api/analytics/track-paths/${cam}?hours=${Math.min(hours, 24)}&limit=300`),
  });
  const zones = useQuery({
    queryKey: ["zone-stats", cam, hours],
    queryFn: () => get<{ zone_id: string; name: string; kind: string; visits: number; mean_dwell_s: number; max_dwell_s: number }[]>(`/api/analytics/zones/${cam}?hours=${hours}`),
  });
  const running = cameras.find((c) => c.id === cam)?.stats;
  const [snapErr, setSnapErr] = useState(false);
  const g = heat.data?.grid;
  return (
    <Card
      title="Where people go"
      actions={
        <>
          <Toggle checked={showHeat} onChange={setShowHeat} label="Heat" />
          <Toggle checked={showPaths} onChange={setShowPaths} label="Paths" />
          <select className="input" value={cam} onChange={(e) => { setCam(e.target.value); setSnapErr(false); }} aria-label="Camera">
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </>
      }
    >
      <div className="relative aspect-video w-full overflow-hidden rounded-lg border border-line bg-black">
        {running && !snapErr && <img src={`/api/cameras/${cam}/snapshot?t=${Math.floor(Date.now() / 60000)}`} alt="" className="absolute inset-0 h-full w-full object-cover opacity-70" onError={() => setSnapErr(true)} />}
        <svg viewBox="0 0 1000 562.5" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
          {showHeat && g && g.map((row, r) => row.map((v, c) => v > 0.02 && (
            <rect key={`${r}-${c}`} x={(c / heat.data!.cols) * 1000} y={(r / heat.data!.rows) * 562.5} width={1000 / heat.data!.cols + 0.5} height={562.5 / heat.data!.rows + 0.5}
              fill="#3987e5" opacity={0.1 + v * 0.7} />
          )))}
          {showPaths && (paths.data ?? []).map((p) => p.path.length > 1 && (
            <polyline key={p.id} points={p.path.map(([x, y]) => `${x * 1000},${y * 562.5}`).join(" ")} fill="none"
              stroke={p.anomaly > 0.3 ? "#e66767" : p.identity_id ? "#6da7ec" : "#c3c2b7"} strokeOpacity={0.55} strokeWidth={1.6} />
          ))}
        </svg>
        {!g && !heat.isLoading && <div className="absolute inset-0 flex items-center justify-center text-[12px] text-muted">No occupancy data yet for this camera</div>}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-4 text-[11.5px] text-muted">
        <span>{num(heat.data?.samples)} foot-point samples (learned occupancy model)</span>
        <span className="flex items-center gap-1.5">low <span className="h-2 w-16 rounded-sm" style={{ background: "linear-gradient(90deg, rgba(57,135,229,0.12), rgba(57,135,229,0.8))" }} /> high traffic</span>
        <span className="flex items-center gap-1"><span className="h-0.5 w-3 bg-[#e66767]" /> anomalous path</span>
        <span>{paths.data?.length ?? 0} paths (≤24 h)</span>
      </div>
      {(zones.data ?? []).length > 0 && (
        <table className="mt-3 w-full text-left text-[12px]">
          <thead className="text-[11px] text-muted"><tr><th className="py-1 font-medium">Zone</th><th className="font-medium">Kind</th><th className="text-right font-medium">Visits</th><th className="text-right font-medium">Mean dwell</th><th className="text-right font-medium">Max dwell</th></tr></thead>
          <tbody>{zones.data!.map((z) => (
            <tr key={z.zone_id} className="border-t border-line"><td className="py-1">{z.name}</td><td className="text-muted">{z.kind}</td><td className="tabular text-right">{z.visits}</td><td className="tabular text-right">{dur(z.mean_dwell_s)}</td><td className="tabular text-right">{dur(z.max_dwell_s)}</td></tr>
          ))}</tbody>
        </table>
      )}
    </Card>
  );
}
