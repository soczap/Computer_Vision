import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bot, Cctv, FileWarning, Fingerprint, Radio, ShieldAlert, Users, Eye, Moon } from "lucide-react";
import { get, type Camera, type Incident, type Paged } from "../lib/api";
import { ago, fmtTime, num, SEV_COLOR, SEV_RANK, SERIES, typeLabel } from "../lib/format";
import { useStream } from "../lib/stream";
import { BarList, SeriesChart, StatTile } from "../components/charts";
import { Badge, Card, DemoBadge, Empty, PageHeader, SeverityBadge, SkeletonRows, Skeleton, StatusBadge } from "../components/ui";
import { isDemo, useDataMode } from "../lib/datamode";
import { agentLabel } from "../components/domain";

export interface Overview {
  hours: number;
  sightings: number;
  unique_identities: number;
  identified_share: number;
  events: number;
  open_incidents: number;
  identities_total: number;
  watchlist_identities: number;
  events_by_type: Record<string, number>;
  events_by_severity: Record<string, number>;
  events_by_status: Record<string, number>;
  sightings_by_camera: Record<string, number>;
  series: { bucket: string; sightings: number; events: number }[];
  dwell: { median_s: number; p90_s: number; histogram: { bin: string; count: number }[] };
}

export const bucketLabel = (b: string) => (b.includes("T") ? b.slice(11, 16) : b.slice(5));

export default function CommandCenter() {
  const nav = useNavigate();
  const { mode } = useDataMode();
  const ov = useQuery({ queryKey: ["overview", 24], queryFn: () => get<Overview>("/api/analytics/overview?hours=24"), refetchInterval: 30000 });
  const inc = useQuery({
    queryKey: ["incidents", "queue"],
    queryFn: () => get<Paged<Incident>>("/api/incidents?status=new,investigating,confirmed&limit=12"),
    refetchInterval: 20000,
  });
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => get<Camera[]>("/api/cameras"), refetchInterval: 5000 });
  const o = ov.data;

  const byType = useMemo(
    () => Object.entries(o?.events_by_type ?? {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, label: typeLabel(k), value: v })),
    [o],
  );
  const incidents = useMemo(
    () => [...(inc.data?.items ?? [])].sort((a, b) => SEV_RANK[b.severity] - SEV_RANK[a.severity] || b.updated_at.localeCompare(a.updated_at)),
    [inc.data],
  );

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader title="Command Center" subtitle={<>Last 24 hours · all cameras · times in IST{mode !== "exclude" && <> · <span className="font-semibold text-[#fab219]">{mode === "only" ? "demo data only" : "figures incl. demo data"}</span></>}</>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {o ? (
          <>
            <StatTile label="Sightings" icon={<Eye size={13} />} value={num(o.sightings)} sub={`${Object.keys(o.sightings_by_camera).length} cameras`} />
            <StatTile label="Unique identities" icon={<Users size={13} />} value={num(o.unique_identities)} sub={`${num(o.identities_total)} in gallery`} />
            <StatTile label="Identified share" icon={<Fingerprint size={13} />} value={`${Math.round(o.identified_share * 100)}%`} sub="sightings with a face ID" />
            <StatTile label="Events" icon={<Radio size={13} />} value={num(o.events)} sub={`${o.events_by_severity.critical ?? 0} critical · ${o.events_by_severity.high ?? 0} high`} />
            <StatTile label="Open incidents" icon={<FileWarning size={13} />} tone={o.open_incidents ? SEV_COLOR.high : undefined} value={num(o.open_incidents)} sub="new · investigating · confirmed" />
            <StatTile label="Watchlist candidates" icon={<ShieldAlert size={13} />} tone={o.watchlist_identities ? SEV_COLOR.critical : undefined} value={num(o.watchlist_identities)} sub="FRS matches — verify" />
          </>
        ) : (
          Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[84px]" />)
        )}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Incident queue" actions={<Link to="/incidents" className="text-[12px] text-accent">All incidents →</Link>} bodyClass="p-2">
            {inc.isLoading ? <SkeletonRows n={4} /> : incidents.length === 0 ? (
              <Empty icon={FileWarning} title="No open incidents" hint="Incidents open automatically when medium+ events are raised and verified." />
            ) : (
              <div className="flex flex-col">
                {incidents.map((i) => (
                  <button key={i.id} onClick={() => nav(`/incidents/${i.id}`)} className="grid grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-surface-2">
                    <span className={i.severity === "critical" && i.status === "new" ? "pulse-critical rounded-md" : ""}><SeverityBadge severity={i.severity} /></span>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5"><span className="truncate font-medium">{i.title}</span>{isDemo(i) && <DemoBadge compact />}</div>
                      <div className="truncate text-[11.5px] text-muted">
                        {typeLabel(i.type)} · {i.camera_id ?? "multi-camera"} · {i.event_count ?? 0} events
                        {i.conclusion?.assessment && <> · agent: {i.conclusion.assessment.replace("_", " ")}</>}
                      </div>
                    </div>
                    <StatusBadge status={i.status} />
                    <span className="w-[64px] text-right text-[11.5px] text-muted">{ago(i.updated_at)}</span>
                  </button>
                ))}
              </div>
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Sightings per hour">
              {o ? <SeriesChart data={o.series} dataKey="sightings" name="Sightings" color={SERIES[0]} xFmt={bucketLabel} /> : <Skeleton className="h-[150px]" />}
            </Card>
            <Card title="Events per hour">
              {o ? <SeriesChart data={o.series} dataKey="events" name="Events" color={SERIES[1]} xFmt={bucketLabel} /> : <Skeleton className="h-[150px]" />}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Events by type">
              {o ? <BarList items={byType} onClick={(k) => nav(`/events?type=${k}`)} empty={<Empty title="No events in 24 h" />} /> : <SkeletonRows n={4} h="h-4" />}
            </Card>
            <Card title="Cameras" actions={<Link to="/live" className="text-[12px] text-accent">Live wall →</Link>} bodyClass="p-2">
              {cams.isLoading ? <SkeletonRows n={3} /> : (cams.data ?? []).length === 0 ? <Empty icon={Cctv} title="No cameras configured" /> : (
                <div className="flex flex-col">
                  {(cams.data ?? []).map((c) => <CameraRow key={c.id} c={c} />)}
                </div>
              )}
            </Card>
          </div>
        </div>
        <LiveFeed />
      </div>
    </div>
  );
}

function CameraRow({ c }: { c: Camera }) {
  const s = c.stats;
  const running = s?.status === "running";
  const color = !c.enabled ? "#898781" : running ? (s?.idle ? "#6da7ec" : "#0ca30c") : s ? "#fab219" : "#898781";
  return (
    <Link to={`/live/${c.id}`} className="grid grid-cols-[10px_minmax(0,1fr)_auto] items-center gap-3 rounded-md px-2 py-2 hover:bg-surface-2">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5"><span className="truncate font-medium">{c.name}</span>{isDemo(c) && <DemoBadge compact />}</div>
        <div className="truncate text-[11.5px] text-muted">
          {c.source_type.toUpperCase()} · {c.source_type === "demo" ? "synthetic — no stream" : !c.enabled ? (c.config?.reconnect_note ? "disabled — reconnect" : "disabled") : s ? s.status : "stopped"}
          {running && s?.idle && " · idle (motion-gated)"}
        </div>
      </div>
      <div className="tabular text-right text-[11.5px] text-ink-2">
        {running ? <>{s!.fps.toFixed(1)} fps · {s!.active_tracks} in view</> : "—"}
      </div>
    </Link>
  );
}

function LiveFeed() {
  const { recent, connected } = useStream();
  const { mode } = useDataMode();
  const nav = useNavigate();
  const items = recent
    .filter((m) => ["event.created", "incident.created", "agent.run", "notification", "identity.created"].includes(m.topic))
    .filter((m) => { const d = isDemo(m.data); return mode === "include" || (mode === "only" ? d : !d); })
    .slice(0, 60);
  return (
    <Card
      title="Realtime activity"
      actions={<Badge color={connected ? "#0ca30c" : "#d03b3b"}>{connected ? "live" : "offline"}</Badge>}
      bodyClass="p-2 max-h-[860px] overflow-y-auto"
    >
      {items.length === 0 ? (
        <Empty icon={Radio} title="Waiting for activity" hint="Events, incidents, agent runs and new identities stream here as they happen." />
      ) : (
        <ul className="flex flex-col">
          {items.map((m, idx) => {
            const d = m.data ?? {};
            let icon = <Radio size={13} className="text-muted" />;
            let title: string = m.topic;
            let sub = "";
            let href: string | undefined;
            if (m.topic === "event.created") {
              icon = <span className="mt-0.5 h-2 w-2 rounded-full" style={{ background: SEV_COLOR[d.severity] }} />;
              title = d.title;
              sub = `${typeLabel(d.type)} · ${d.camera_id ?? ""}`;
              href = `/events?focus=${d.id}`;
            } else if (m.topic === "incident.created") {
              icon = <FileWarning size={13} style={{ color: SEV_COLOR[d.severity] }} />;
              title = `Incident opened: ${d.title}`;
              sub = d.severity;
              href = `/incidents/${d.id}`;
            } else if (m.topic === "agent.run") {
              icon = <Bot size={13} className="text-accent" />;
              title = `${agentLabel(d.agent)} ${d.status === "running" ? "started" : d.status}`;
              sub = d.trigger ?? d.error ?? "";
              href = d.incident_id ? `/incidents/${d.incident_id}` : undefined;
            } else if (m.topic === "notification") {
              icon = <ShieldAlert size={13} style={{ color: SEV_COLOR[d.severity] }} />;
              title = d.message;
              sub = `notification · ${d.by ?? ""}`;
              href = d.incident_id ? `/incidents/${d.incident_id}` : undefined;
            } else if (m.topic === "identity.created") {
              icon = <Users size={13} className="text-kind-reid" />;
              title = `${d.enrolled ? "Enrolled" : "New identity"} ${d.id}`;
              sub = d.camera_id ?? "";
              href = `/identities/${d.id}`;
            }
            return (
              <li key={`${m.at}-${idx}`}>
                <button disabled={!href} onClick={() => href && nav(href)} className="flex w-full items-start gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-surface-2 disabled:hover:bg-transparent">
                  <span className="mt-1 flex w-3 justify-center">{icon}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5"><span className="block truncate text-[12.5px] text-ink">{title}</span>{isDemo(d) && <DemoBadge compact />}</span>
                    <span className="block truncate text-[11px] text-muted">{sub}</span>
                  </span>
                  <span className="tabular text-[11px] text-muted">{fmtTime(m.at)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {!connected && <div className="flex items-center gap-2 px-2 py-2 text-[11.5px] text-muted"><Moon size={12} /> Stream disconnected — reconnecting automatically.</div>}
    </Card>
  );
}
