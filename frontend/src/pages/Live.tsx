import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Cctv, FlaskConical, Maximize2, Moon, PersonStanding, PlugZap, Webcam } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { patch } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { isDemo } from "../lib/datamode";
import { get, type Camera, type Paged, type VEvent } from "../lib/api";
import { dur, KIND_COLOR, KIND_LABEL } from "../lib/format";
import LiveCanvas, { type LiveHeader } from "../components/LiveCanvas";
import { Badge, Card, DemoBadge, Empty, Meter, PageHeader, SkeletonRows, Toggle, Skeleton, cx } from "../components/ui";
import { EventLine } from "../components/domain";

function StatusChip({ c }: { c: Camera }) {
  const s = c.stats;
  if (c.source_type === "demo") return <DemoBadge />;
  if (!c.enabled) return <Badge color="#898781">disabled</Badge>;
  if (!s) return <Badge color="#898781">stopped</Badge>;
  if (s.status !== "running") return <Badge color="#fab219">{s.status}</Badge>;
  if (s.idle) return <Badge color="#6da7ec"><Moon size={10} /> idle</Badge>;
  return <Badge color="#0ca30c">{s.fps.toFixed(1)} fps</Badge>;
}

export function LiveWall() {
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => get<Camera[]>("/api/cameras"), refetchInterval: 5000 });
  const running = (cams.data ?? []).filter((c) => c.stats && c.enabled);
  const offline = (cams.data ?? []).filter((c) => !(c.stats && c.enabled));
  const [cols, setCols] = useState(2);
  const nav = useNavigate();
  const { can } = useAuth();
  return (
    <div className="mx-auto max-w-[1700px]">
      <PageHeader
        title="Live"
        subtitle="Annotated streams · boxes coloured by identity kind · idle scenes are motion-gated to ~1 fps"
        actions={
          <div className="flex items-center gap-1">
            {can("analyst") && <button className="btn btn-primary mr-2" onClick={() => nav("/webcam")}><Webcam size={14} /> Connect laptop webcam</button>}
            {[1, 2, 3].map((n) => (
              <button key={n} className={cx("btn btn-sm", cols === n && "btn-primary")} onClick={() => setCols(n)}>{n}×</button>
            ))}
          </div>
        }
      />
      <Legend />
      {cams.isLoading ? (
        <div className="mt-3 grid grid-cols-2 gap-3"><Skeleton className="aspect-video" /><Skeleton className="aspect-video" /></div>
      ) : running.length === 0 ? (
        <Card className="mt-3"><Empty icon={Cctv} title="No running cameras" hint={<>Connect your <Link className="text-accent" to="/webcam">laptop webcam</Link> or <Link className="text-accent" to="/cameras">configure cameras</Link>.</>} /></Card>
      ) : (
        <div className="mt-3 grid gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {running.map((c) => (
            <div key={c.id} className="card overflow-hidden">
              <div className="flex items-center justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate font-medium">{c.name}</div>
                  <div className="truncate text-[11px] text-muted">{c.location ?? c.id}</div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusChip c={c} />
                  <Link to={`/live/${c.id}`} className="btn btn-ghost btn-sm" title="Open"><Maximize2 size={13} /></Link>
                </div>
              </div>
              <LiveCanvas cameraId={c.id} opts={{ skeleton: false }} />
            </div>
          ))}
        </div>
      )}
      {offline.length > 0 && (
        <>
          <div className="label mb-2 mt-5">Not streaming</div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
            {offline.map((c) => <OfflineCard key={c.id} c={c} />)}
          </div>
        </>
      )}
    </div>
  );
}

function OfflineCard({ c }: { c: Camera }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const reconnect = useMutation({
    mutationFn: () => patch(`/api/cameras/${c.id}`, { enabled: true }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["cameras"] }); toast({ kind: "success", title: `Reconnecting ${c.name}` }); },
    onError: (e) => toast({ kind: "error", title: "Reconnect failed", body: (e as Error).message }),
  });
  const demo = isDemo(c);
  const note = c.config?.reconnect_note as string | undefined;
  return (
    <div className="card flex flex-col gap-2 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{c.name}</div>
          <div className="truncate font-mono text-[11px] text-muted">{c.id}</div>
        </div>
        {demo ? <DemoBadge /> : <Badge color="#898781">{c.enabled ? "stopped" : note ? "disabled — reconnect" : "disabled"}</Badge>}
      </div>
      <div className="flex aspect-video items-center justify-center rounded-md border border-dashed border-line bg-surface-2 text-center text-[12px] text-muted"
        style={demo ? { background: "repeating-linear-gradient(135deg, rgba(250,178,25,0.06) 0 12px, transparent 12px 24px)" } : undefined}>
        {demo ? <span className="flex items-center gap-1.5"><FlaskConical size={13} /> synthetic — no stream</span> : <span className="flex items-center gap-1.5"><PlugZap size={13} /> {c.enabled ? "not running" : "disconnected"}</span>}
      </div>
      {!demo && note && <div className="text-[11.5px] leading-relaxed text-muted">{note}</div>}
      {!demo && !c.enabled && can("admin") && (
        <button className="btn btn-sm self-start" disabled={reconnect.isPending} onClick={() => reconnect.mutate()}><PlugZap size={12} /> {note ? "Reconnect" : "Enable"}</button>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-[11.5px] text-ink-2">
      {Object.entries(KIND_LABEL).map(([k, l]) => (
        <span key={k} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND_COLOR[k] }} /> {l}
        </span>
      ))}
      <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border border-dashed border-[#d03b3b]" /> restricted zone</span>
    </div>
  );
}

export function LiveCamera() {
  const { cameraId = "" } = useParams();
  const nav = useNavigate();
  const [hdr, setHdr] = useState<LiveHeader | null>(null);
  const [opts, setOpts] = useState({ skeleton: true, trails: true, zones: true, labels: true });
  const cam = useQuery({ queryKey: ["camera", cameraId], queryFn: () => get<Camera>(`/api/cameras/${cameraId}`), refetchInterval: 4000 });
  const evs = useQuery({
    queryKey: ["events", "camera", cameraId],
    queryFn: () => get<Paged<VEvent>>(`/api/events?camera_id=${encodeURIComponent(cameraId)}&limit=15`),
    refetchInterval: 15000,
  });
  const c = cam.data;
  const v = hdr?.violence ?? {};
  const fused = typeof v.fused === "number" ? v.fused : null;

  return (
    <div className="mx-auto max-w-[1700px]">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <button className="btn btn-ghost btn-sm" onClick={() => nav("/live")}><ArrowLeft size={14} /> Wall</button>
        <h1 className="text-[18px] font-semibold">{c?.name ?? cameraId}</h1>
        {c && <StatusChip c={c} />}
        <span className="text-[12px] text-muted">{c?.location}</span>
        <div className="ml-auto flex flex-wrap items-center gap-4">
          <Toggle checked={opts.skeleton} onChange={(x) => setOpts({ ...opts, skeleton: x })} label="Skeleton" />
          <Toggle checked={opts.trails} onChange={(x) => setOpts({ ...opts, trails: x })} label="Trails" />
          <Toggle checked={opts.zones} onChange={(x) => setOpts({ ...opts, zones: x })} label="Zones" />
          <Toggle checked={opts.labels} onChange={(x) => setOpts({ ...opts, labels: x })} label="Labels" />
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="card overflow-hidden">
            <LiveCanvas cameraId={cameraId} opts={opts} onHeader={setHdr} />
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line px-3 py-2 text-[11.5px] text-muted">
              <span>{hdr ? `${hdr.w}×${hdr.h}` : "—"}</span>
              <span>analysis {c?.stats?.fps?.toFixed(1) ?? "—"} fps</span>
              <span>latency {c?.stats?.latency_ms ?? "—"} ms</span>
              <span>{c?.stats?.tracks_total ?? 0} tracks total</span>
              <span>{c?.stats?.faces ?? 0} face observations</span>
              {c?.stats?.idle && <span className="text-sev-low">Idle: no motion — analysing ~1 fps until something moves</span>}
            </div>
          </div>
          <Legend />
        </div>
        <div className="flex flex-col gap-3">
          <Card title="Violence monitor">
            {fused === null ? (
              <div className="text-[12px] text-muted">No close-range interaction evaluated yet. Stage 2 runs only when two or more people are close.</div>
            ) : (
              <div className="flex flex-col gap-2">
                <div className="flex items-baseline justify-between">
                  <span className="text-muted">fused score</span>
                  <span className="tabular text-[18px] font-semibold" style={{ color: fused >= 0.78 ? "#d03b3b" : fused >= 0.5 ? "#fab219" : "#f4f4f2" }}>{fused.toFixed(2)}</span>
                </div>
                <Meter value={fused} color={fused >= 0.78 ? "#d03b3b" : fused >= 0.5 ? "#fab219" : "#3987e5"} />
                <div className="grid grid-cols-2 gap-2 text-[12px]">
                  <div><div className="text-muted">VideoMAE</div><div className="tabular">{v.videomae_component?.toFixed(2)} <span className="text-muted">(logit {v.videomae_logit})</span></div></div>
                  <div><div className="text-muted">Pose interaction</div><div className="tabular">{v.pose_component?.toFixed(2)}</div></div>
                </div>
                <div className="text-[11px] text-muted">Fires at ≥ 0.85 once, or ≥ 0.78 on two consecutive evaluations; then a VLM verifies.</div>
              </div>
            )}
          </Card>
          <Card title={`In view (${hdr?.tracks.length ?? 0})`} bodyClass="p-2 max-h-[340px] overflow-y-auto">
            {!hdr || hdr.tracks.length === 0 ? (
              <Empty icon={PersonStanding} title="Nobody in view" />
            ) : (
              <div className="flex flex-col">
                {hdr.tracks.map((t) => (
                  <button
                    key={t.uid}
                    disabled={!t.identity}
                    onClick={() => t.identity && nav(`/identities/${t.identity}`)}
                    className="grid grid-cols-[10px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-surface-2 disabled:hover:bg-transparent"
                  >
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND_COLOR[t.kind] }} />
                    <div className="min-w-0">
                      <div className="truncate font-medium">{t.label}</div>
                      <div className="truncate text-[11px] text-muted">
                        {KIND_LABEL[t.kind]}{t.score !== null && t.identity ? ` · sim ${t.score.toFixed(2)}` : ""} · {t.speed.toFixed(1)} bh/s
                        {t.posture === "down" && " · DOWN"}
                      </div>
                    </div>
                    <span className="tabular text-[11.5px] text-ink-2">{dur(t.dwell)}</span>
                  </button>
                ))}
              </div>
            )}
          </Card>
          <Card title="Recent events" actions={<Link to={`/events?camera_id=${cameraId}`} className="text-[12px] text-accent">All →</Link>} bodyClass="p-1.5 max-h-[420px] overflow-y-auto">
            {evs.isLoading ? <SkeletonRows n={3} /> : (evs.data?.items ?? []).length === 0 ? <Empty title="No events on this camera" /> : (
              (evs.data?.items ?? []).map((e) => (
                <EventLine key={e.id} e={e} onClick={() => nav(e.incident_id ? `/incidents/${e.incident_id}` : `/events?focus=${e.id}`)} />
              ))
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
