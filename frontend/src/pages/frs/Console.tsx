import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Fingerprint, Radar, ScanFace, ShieldAlert, UserPlus } from "lucide-react";
import { get } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useStreamListener } from "../../lib/stream";
import { isDemo } from "../../lib/datamode";
import { ago, dur, fmtTime, sim } from "../../lib/format";
import WebcamPanel from "../../components/WebcamPanel";
import { Badge, Card, DemoBadge, Empty, Img, SkeletonRows } from "../../components/ui";
import { FrsShell, OutcomeChip, StateChip, STATE, frsImg } from "./common";

interface LivePerson {
  camera_id: string; track_uid: string; local_id: number; identity_id: string | null; label: string;
  display_name: string | null; state: string; locked: boolean; similarity: number | null; face_observations: number;
  best_face_quality: number; best_face_px: number; frs_searched: boolean;
  watchlist: { criminal_id: string; name: string } | null; in_view_s: number; face: string | null;
}

const NEED_VIEWS = 3;

export default function FrsConsole() {
  const { can } = useAuth();
  const live = useQuery({
    queryKey: ["frs-live"],
    queryFn: () => get<{ tracks: LivePerson[]; cameras: Record<string, string> }>("/api/frs/live"),
    refetchInterval: 1000,
  });
  const people = live.data?.tracks ?? [];
  return (
    <FrsShell title="Console" subtitle="Live face recognition: persistent IDs from pooled face evidence, FRS watchlist search at each person's best face">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-w-0 flex-col gap-4">
          <div className="card p-3">
            {can("analyst") ? <WebcamPanel /> : <Empty icon={ScanFace} title="Streaming a camera requires the analyst role" />}
          </div>
          <Feed />
        </div>
        <Card title={<span className="flex items-center gap-2"><Radar size={14} className="text-[#9085e9]" /> In view now ({people.length})</span>}
          actions={<span className="text-[11px] text-muted">{Object.entries(live.data?.cameras ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</span>}
          bodyClass="p-2 max-h-[calc(100vh-220px)] overflow-y-auto">
          {live.isLoading ? <SkeletonRows n={3} h="h-20" /> : people.length === 0 ? (
            <Empty icon={ScanFace} title="Nobody in view" hint="People appear here the moment they are tracked; a face ID follows after a few good views." />
          ) : (
            <div className="flex flex-col gap-2">{people.map((p) => <PersonCard key={p.track_uid} p={p} />)}</div>
          )}
        </Card>
      </div>
    </FrsShell>
  );
}

function PersonCard({ p }: { p: LivePerson }) {
  const nav = useNavigate();
  const st = STATE[p.state]?.color ?? "#898781";
  return (
    <div className="rounded-lg border bg-surface-2/40 p-2.5" style={{ borderColor: st + "55" }}>
      <div className="flex gap-3">
        <Img src={p.face} alt="" className="h-[72px] w-[60px] shrink-0 rounded-md object-cover" fallback={<ScanFace size={18} />} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <button disabled={!p.identity_id} onClick={() => p.identity_id && nav(`/frs/identities/${p.identity_id}`)}
              className="truncate text-left font-semibold hover:text-accent disabled:hover:text-ink">
              {p.display_name ?? p.label}
            </button>
            <span className="tabular text-[11px] text-muted">{dur(p.in_view_s)}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <StateChip state={p.state} />
            {p.identity_id && <span className="font-mono text-[11px] text-muted">{p.identity_id}</span>}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-[11.5px] text-ink-2">
            {p.similarity !== null && <span className="font-mono">{sim(p.similarity)}</span>}
            {p.state === "collecting" || !p.locked ? (
              <span>collecting {Math.min(p.face_observations, NEED_VIEWS)}/{NEED_VIEWS} views</span>
            ) : <span>{p.face_observations} views pooled</span>}
            {p.best_face_px > 0 && <span className="text-muted">best face {Math.round(p.best_face_px)} px · q {p.best_face_quality.toFixed(2)}</span>}
          </div>
          <div className="mt-1 text-[11px] text-muted">
            FRS watchlist: {p.watchlist ? "candidate on record for this identity" : p.frs_searched ? "searched — no candidate" : p.identity_id ? "search pending (best face ≥ 56 px)" : "searched after identification"}
          </div>
        </div>
      </div>
      {!p.locked && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-3">
          <div className="h-full rounded-full bg-[#fab219]" style={{ width: `${(Math.min(p.face_observations, NEED_VIEWS) / NEED_VIEWS) * 100}%` }} />
        </div>
      )}
      {p.watchlist && (
        <Link to={`/frs/watchlist/${p.watchlist.criminal_id}`}
          className="mt-2 flex items-center gap-2 rounded-md border border-[#e6676755] bg-[#e6676714] px-2.5 py-1.5 text-[12px] hover:bg-[#e6676722]">
          <ShieldAlert size={13} className="text-kind-watchlist" />
          <span className="font-semibold text-ink">{p.watchlist.name}</span>
          <span className="text-kind-watchlist">candidate — verify</span>
          <span className="ml-auto text-muted">open record →</span>
        </Link>
      )}
    </div>
  );
}

function Feed() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["frs-feed"], queryFn: () => get<any[]>("/api/frs/feed?limit=40"), refetchInterval: 20000 });
  useStreamListener((m) => {
    if (m.topic === "identity.created" || m.topic === "frs.search" || (m.topic === "event.created" && m.data?.type === "watchlist_match"))
      qc.invalidateQueries({ queryKey: ["frs-feed"] });
  });
  return (
    <Card title={<span className="flex items-center gap-2"><Activity size={14} /> Recent recognition activity</span>} bodyClass="p-2 max-h-[520px] overflow-y-auto">
      {q.isLoading ? <SkeletonRows n={5} /> : (q.data ?? []).length === 0 ? <Empty title="No recognition activity yet" /> : (
        <ul className="flex flex-col">
          {q.data!.map((it, i) => <FeedItem key={it.id ?? `${it.kind}-${it.ts}-${i}`} it={it} onOpen={nav} />)}
        </ul>
      )}
    </Card>
  );
}

function FeedItem({ it, onOpen }: { it: any; onOpen: (to: string) => void }) {
  const ts = it.ts ?? it.time ?? it.created_at;
  let icon = <Fingerprint size={14} className="text-muted" />, title: ReactNode = it.kind, sub: ReactNode = null, to: string | undefined, img = it.face_url ?? it.thumb_url;
  switch (it.kind) {
    case "identity_created":
      icon = <ScanFace size={14} style={{ color: STATE.new_identity.color }} />;
      title = <>New identity <b>{it.label ?? it.identity_id}</b></>;
      sub = "first clear face — persistent ID assigned";
      to = `/frs/identities/${it.identity_id}`;
      break;
    case "identity_enrolled":
      icon = <UserPlus size={14} style={{ color: STATE.known.color }} />;
      title = <>Enrolled <b>{it.label ?? it.identity_id}</b></>;
      sub = "added to VIGIL gallery";
      to = `/frs/identities/${it.identity_id}`;
      break;
    case "frs_search":
      icon = <Radar size={14} className="text-[#9085e9]" />;
      title = <span className="flex flex-wrap items-center gap-1.5">Watchlist search for <b>{it.identity_id ?? "—"}</b> <OutcomeChip outcome={it.outcome} />{it.outcome === "match" && <b>{it.name}</b>}</span>;
      sub = <>{it.score != null && <span className="font-mono">{sim(it.score)}</span>} · {it.trigger} · {it.latency_ms != null ? `${Math.round(it.latency_ms)} ms` : ""} · {it.camera_id}</>;
      to = it.identity_id ? `/frs/identities/${it.identity_id}` : "/frs/searches";
      break;
    case "watchlist_event":
      icon = <ShieldAlert size={14} className="text-kind-watchlist" />;
      title = <span className="flex items-center gap-1.5">{it.title} <Badge color="#e66767">candidate — verify</Badge></span>;
      sub = <>{it.camera_id} · {sim(it.confidence)}</>;
      to = it.incident_id ? `/incidents/${it.incident_id}` : `/events?focus=${it.id}`;
      img = it.evidence?.keyframe ?? img;
      break;
    case "frs_backend_detection":
      icon = <Fingerprint size={14} className="text-[#c98500]" />;
      title = <>FRS camera detection: <b>{it.name ?? "unknown"}</b> {it.kind_label ?? ""}</>;
      sub = <>port-8000 camera {it.camera_id ?? "—"}{it.similarity != null && <> · <span className="font-mono">{sim(it.similarity)}</span></>}{it.state ? ` · ${it.state}` : ""}</>;
      to = it.criminal_id ? `/frs/watchlist/${it.criminal_id}` : undefined;
      break;
  }
  return (
    <li>
      <button disabled={!to} onClick={() => to && onOpen(to)} className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-surface-2 disabled:hover:bg-transparent">
        <span className="flex w-4 justify-center">{icon}</span>
        {img ? <Img src={frsImg(img)} alt="" className="h-9 w-9 shrink-0 rounded object-cover" /> : <span className="h-9 w-9 shrink-0" />}
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-[12.5px] text-ink"><span className="min-w-0 truncate">{title}</span>{isDemo(it) && <DemoBadge compact />}</span>
          <span className="block truncate text-[11px] text-muted">{sub}</span>
        </span>
        <span className="tabular text-right text-[11px] text-muted" title={ts}>{fmtTime(ts)}<br />{ago(ts)}</span>
      </button>
    </li>
  );
}
