import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, GitMerge, Save, ScanSearch, ShieldQuestion, Trash2, Users } from "lucide-react";
import { del, frsMedia, get, mediaUrl, patch, post, type FrsSearch, type Identity, type Track } from "../lib/api";
import { OutcomeChip } from "./frs/common";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { ago, dur, fmtDateTime, fmtTime, KIND_COLOR, parseTs, SERIES, sim, titleCase } from "../lib/format";
import {
  Badge, Card, DemoBadge, Empty, ErrorBox, Img, KindBadge, KV, Modal, PageHeader, SkeletonRows, Spinner, WatchlistBadge,
} from "../components/ui";
import { isDemo } from "../lib/datamode";
import { EventLine } from "../components/domain";
import { CATEGORIES, CAT_COLOR, identityKind } from "./Identities";

export default function IdentityProfile({ embedded }: { embedded?: boolean } = {}) {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const q = useQuery({ queryKey: ["identity", id], queryFn: () => get<Identity>(`/api/identities/${id}`), refetchInterval: 20000 });
  const [edit, setEdit] = useState<{ display_name: string; category: string; notes: string } | null>(null);
  const [merge, setMerge] = useState(false);
  const [into, setInto] = useState("");
  const frsRec = useQuery({
    queryKey: ["frs-crim", q.data?.frs_criminal_id],
    queryFn: () => get<any[]>("/api/frs/criminals"),
    enabled: !!q.data?.frs_criminal_id,
    staleTime: 300_000,
  });
  const save = useMutation({
    mutationFn: (b: Record<string, unknown>) => patch<Identity>(`/api/identities/${id}`, b),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["identity", id] }); qc.invalidateQueries({ queryKey: ["identities"] }); setEdit(null); toast({ kind: "success", title: "Saved" }); },
    onError: (e) => toast({ kind: "error", title: "Save failed", body: (e as Error).message }),
  });
  const check = useMutation({
    mutationFn: () => post<{ result: any; identity: Identity }>(`/api/identities/${id}/check-watchlist`),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["identity", id] });
      toast({ kind: r.result?.matched ? "high" : "info", title: r.result?.matched ? `FRS candidate: ${r.result.name}` : "No FRS watchlist match",
        body: r.result ? `best ${r.result.name ?? "—"} · sim ${Number(r.result.score).toFixed(2)}` : "FRS found no usable face or no candidate." });
    },
    onError: (e) => toast({ kind: "error", title: "Watchlist check failed", body: (e as Error).message }),
  });
  const doMerge = useMutation({
    mutationFn: () => post<Identity>(`/api/identities/${id}/merge`, { into: into.trim().toUpperCase() }),
    onSuccess: (r) => { toast({ kind: "success", title: `Merged into ${r.id}` }); qc.invalidateQueries({ queryKey: ["identities"] }); nav(`/identities/${r.id}`); },
    onError: (e) => toast({ kind: "error", title: "Merge failed", body: (e as Error).message }),
  });
  const remove = useMutation({
    mutationFn: () => del(`/api/identities/${id}`),
    onSuccess: () => { toast({ kind: "success", title: `Deleted ${id}` }); qc.invalidateQueries({ queryKey: ["identities"] }); nav("/identities"); },
    onError: (e) => toast({ kind: "error", title: "Delete failed", body: (e as Error).message }),
  });

  if (q.isLoading) return <SkeletonRows n={8} h="h-12" />;
  if (q.error || !q.data) return <ErrorBox error={q.error ?? "Not found"} />;
  const i = q.data;
  const k = identityKind(i);
  const crim = (frsRec.data ?? []).find((c) => c.id === i.frs_criminal_id);

  return (
    <div className={embedded ? "" : "mx-auto max-w-[1500px]"}>
      <Link to={embedded ? "/frs/identities" : "/identities"} className="mb-2 inline-flex items-center gap-1 text-[12px] text-muted hover:text-ink"><ArrowLeft size={13} /> Identities</Link>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2">{i.display_name ?? i.frs_name ?? i.id} <span className="font-mono text-[13px] font-normal text-muted">{i.id}</span>{isDemo(i) && <DemoBadge />}</span>}
        subtitle={<>First seen {fmtDateTime(i.first_seen)} · last seen {ago(i.last_seen)} on {i.last_camera_id ?? "—"} · {i.sightings} sightings · {i.appearances ?? 0} identified appearances · {i.face_vectors ?? 0} face vectors</>}
        actions={
          <>
            {i.watchlist ? <WatchlistBadge name={i.frs_name} /> : <KindBadge kind={k} />}
            <Link className="btn" to={`/search?identity=${i.id}`}><ScanSearch size={13} /> Similar appearance</Link>
            {can("analyst") && <button className="btn" disabled={isDemo(i)} title={isDemo(i) ? "Demo identities cannot be merged" : undefined} onClick={() => setMerge(true)}><GitMerge size={13} /> Merge</button>}
            {can("admin") && (
              <button className="btn btn-danger" onClick={() => confirm(`Delete ${i.id} and its face vectors? Sightings stay but lose the link.`) && remove.mutate()}>
                <Trash2 size={13} />
              </button>
            )}
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <Card bodyClass="p-0">
            <div className="relative">
              <Img src={mediaUrl(i.face_url)} alt={i.label} className="aspect-square w-full rounded-t-[10px] object-cover" fallback={<Users size={36} />} />
              <span className="absolute inset-x-0 bottom-0 h-1" style={{ background: KIND_COLOR[k] }} />
            </div>
            <div className="p-4">
              {edit ? (
                <div className="flex flex-col gap-2">
                  <input className="input" placeholder="Display name" value={edit.display_name} onChange={(e) => setEdit({ ...edit, display_name: e.target.value })} />
                  <select className="input" value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })}>
                    {CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
                  </select>
                  <textarea className="input min-h-[90px]" placeholder="Notes" value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
                  <div className="flex justify-end gap-2">
                    <button className="btn btn-sm" onClick={() => setEdit(null)}>Cancel</button>
                    <button className="btn btn-primary btn-sm" disabled={save.isPending}
                      onClick={() => save.mutate({ display_name: edit.display_name || null, category: edit.category, notes: edit.notes || null })}>
                      <Save size={12} /> Save
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col">
                  <KV k="Kind" v={i.kind} />
                  <KV k="Category" v={<Badge color={CAT_COLOR[i.category]}>{i.category}</Badge>} />
                  <KV k="Created" v={fmtDateTime(i.created_at)} />
                  {i.notes && <p className="mt-2 whitespace-pre-wrap text-[12px] leading-relaxed text-ink-2">{i.notes}</p>}
                  {can("analyst") && (
                    <button className="btn btn-sm mt-3 self-start" onClick={() => setEdit({ display_name: i.display_name ?? "", category: i.category, notes: i.notes ?? "" })}>Edit</button>
                  )}
                </div>
              )}
            </div>
          </Card>

          <Card title={<span className="flex items-center gap-2"><ShieldQuestion size={14} /> FRS watchlist</span>}>
            {i.watchlist ? (
              <div className="flex flex-col gap-3">
                <div className="rounded-md border border-[#e6676755] bg-[#e6676712] p-2.5 text-[12px] leading-relaxed">
                  <b>{i.frs_name}</b> · {sim(i.frs_score)}<br />
                  <span className="text-muted">Candidate from the FRS system. Compare faces before acting.</span>
                </div>
                {crim && (
                  <div className="grid grid-cols-2 gap-2">
                    <div><div className="label mb-1">Seen here</div><Img src={mediaUrl(i.face_url)} alt="" className="aspect-square w-full rounded object-cover" /></div>
                    <div><div className="label mb-1">FRS record</div><Img src={frsMedia(crim.photo_url)} alt="" className="aspect-square w-full rounded object-cover" /></div>
                  </div>
                )}
                {crim && (
                  <div className="text-[12px]">
                    {[crim.group, crim.subgroup].filter(Boolean).join(" / ")}
                    {Object.entries(crim.metadata ?? {}).filter(([kk]) => ["case_type", "charges", "police_station", "fir_number"].includes(kk)).map(([kk, v]) => (
                      <KV key={kk} k={titleCase(kk)} v={String(v)} />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-[12px] text-muted">
                No watchlist match{i.frs_checked_at ? ` (last checked ${ago(i.frs_checked_at)})` : " (not checked yet)"}.
              </div>
            )}
            {can("analyst") && (
              <button className="btn btn-sm mt-3" disabled={check.isPending || isDemo(i)} title={isDemo(i) ? "Not available for demo identities" : undefined} onClick={() => check.mutate()}>
                {check.isPending ? <Spinner /> : <ShieldQuestion size={12} />} Check watchlist now
              </button>
            )}
            <div className="mt-2 text-[11px] text-muted">Each check is one search logged by FRS.</div>
          </Card>

          <Card title="Cameras visited">
            {(i.cameras ?? []).length === 0 ? <Empty title="No sightings" /> : (
              <div className="flex flex-col">
                {i.cameras!.map((c) => (
                  <div key={c.camera_id} className="flex justify-between py-1 text-[12.5px]">
                    <Link to={`/live/${c.camera_id}`} className="text-ink-2 hover:text-ink">{c.camera_id}</Link>
                    <span className="tabular text-muted">{c.sightings}× · {dur(c.dwell_s)}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Movement across cameras">
            <Swimlane tracks={i.tracks ?? []} />
          </Card>
          <Card title={`Sightings (${(i.tracks ?? []).length})`} bodyClass="p-3">
            {(i.tracks ?? []).length === 0 ? <Empty title="No sightings recorded" /> : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2.5">
                {i.tracks!.slice(0, 48).map((t) => (
                  <div key={t.id} className="overflow-hidden rounded-lg border border-line bg-surface-2">
                    <Img src={mediaUrl(t.person_url ?? t.face_url)} alt="" className="h-[150px] w-full bg-black object-contain" />
                    <div className="p-2 text-[11.5px]">
                      <div className="truncate font-medium text-ink">{t.camera_id}</div>
                      <div className="text-muted">{fmtDateTime(t.started_at)}</div>
                      <div className="flex justify-between text-muted"><span>{dur(t.duration_s)}</span><span>{t.identity_score !== null ? sim(t.identity_score) : ""}</span></div>
                      <Link to={`/search?track=${encodeURIComponent(t.id)}`} className="text-accent">find similar →</Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <FrsHistory searches={i.frs_searches ?? []} />
          <Card title={`Events involving ${i.id}`} bodyClass="p-1.5">
            {(i.events ?? []).length === 0 ? <Empty title="No events" /> : i.events!.map((e) => (
              <EventLine key={e.id} e={e} onClick={() => nav(e.incident_id ? `/incidents/${e.incident_id}` : `/events?focus=${e.id}`)} />
            ))}
          </Card>
        </div>
      </div>

      <Modal open={merge} onClose={() => setMerge(false)} title={`Merge ${i.id} into another identity`}
        footer={<>
          <button className="btn" onClick={() => setMerge(false)}>Cancel</button>
          <button className="btn btn-primary" disabled={!into.trim() || doMerge.isPending} onClick={() => doMerge.mutate()}><GitMerge size={13} /> Merge</button>
        </>}>
        <p className="mb-3 text-[12.5px] leading-relaxed text-ink-2">
          Use when an operator is sure two IDs are the same person. All sightings and face vectors of <b>{i.id}</b> move to the target; {i.id} is retired.
        </p>
        <input className="input w-full" placeholder="Target identity, e.g. P-00012" value={into} onChange={(e) => setInto(e.target.value)} />
        <ErrorBox error={doMerge.error} />
      </Modal>
    </div>
  );
}

function Swimlane({ tracks }: { tracks: Track[] }) {
  const data = useMemo(() => {
    const ts = tracks.map((t) => ({ t, a: parseTs(t.started_at)!.getTime(), b: (parseTs(t.ended_at) ?? parseTs(t.started_at)!).getTime() }));
    if (!ts.length) return null;
    const cams = Array.from(new Set(ts.map((x) => x.t.camera_id))).sort();
    const lo = Math.min(...ts.map((x) => x.a));
    const hi = Math.max(...ts.map((x) => x.b), lo + 60_000);
    return { ts, cams, lo, hi };
  }, [tracks]);
  const [hover, setHover] = useState<{ t: Track; x: number; y: number } | null>(null);
  if (!data) return <Empty title="No sightings" />;
  const W = 1000, rowH = 30, left = 150, top = 8;
  const H = top + data.cams.length * rowH + 26;
  const x = (v: number) => left + ((v - data.lo) / (data.hi - data.lo)) * (W - left - 12);
  const ticks = Array.from({ length: 6 }, (_, k) => data.lo + ((data.hi - data.lo) * k) / 5);
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Sightings per camera over time">
        {data.cams.map((c, r) => (
          <g key={c}>
            <line x1={left} x2={W - 12} y1={top + r * rowH + rowH / 2} y2={top + r * rowH + rowH / 2} stroke="#2c2c2a" />
            <text x={left - 10} y={top + r * rowH + rowH / 2 + 4} textAnchor="end" fontSize={11} fill="#c3c2b7">{c.length > 22 ? c.slice(0, 21) + "…" : c}</text>
          </g>
        ))}
        {ticks.map((t, n) => (
          <text key={t} x={x(t)} y={H - 6} textAnchor={n === 0 ? "start" : n === ticks.length - 1 ? "end" : "middle"} fontSize={10} fill="#898781">{fmtTime(t)}</text>
        ))}
        {data.ts.map(({ t, a, b }) => {
          const r = data.cams.indexOf(t.camera_id);
          const x1 = x(a);
          const w = Math.max(4, x(b) - x1);
          const color = SERIES[r % SERIES.length];
          return (
            <rect key={t.id} x={x1} y={top + r * rowH + 7} width={w} height={rowH - 14} rx={3} fill={color}
              stroke="#1a1a19" strokeWidth={2}
              onMouseEnter={(e) => setHover({ t, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })}
              onMouseLeave={() => setHover(null)} />
          );
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute z-10 rounded-md border border-line-strong bg-surface-2 px-2.5 py-1.5 text-[12px] shadow-xl"
          style={{ left: hover.x + 12, top: hover.y + 8 }}>
          <div className="font-medium">{hover.t.camera_id}</div>
          <div className="text-muted">{fmtDateTime(hover.t.started_at)} · {dur(hover.t.duration_s)}</div>
        </div>
      )}
    </div>
  );
}

function FrsHistory({ searches }: { searches: FrsSearch[] }) {
  return (
    <Card title={<span className="flex items-center gap-2"><ShieldQuestion size={14} /> FRS watchlist searches ({searches.length})</span>} bodyClass="p-0">
      {searches.length === 0 ? <Empty title="No FRS searches for this person yet" hint="VIGIL searches the FRS watchlist once per identity at its best face (rate-limited), or on demand." /> : (
        <table className="w-full text-left text-[12px]">
          <thead className="border-b border-line text-[11px] text-muted">
            <tr><th className="px-3 py-2 font-medium">Query face</th><th className="px-2 py-2 font-medium">Time</th><th className="px-2 py-2 font-medium">Outcome</th><th className="px-2 py-2 font-medium">Top candidates</th><th className="px-2 py-2 text-right font-medium">Latency</th><th className="px-3 py-2 font-medium">Trigger</th></tr>
          </thead>
          <tbody>
            {searches.map((x) => (
              <tr key={x.id} className="border-b border-line last:border-0 align-top">
                <td className="px-3 py-2"><Img src={mediaUrl(x.face_url)} alt="" className="h-12 w-12 rounded object-cover" /></td>
                <td className="px-2 py-2 text-ink-2">{fmtDateTime(x.ts)}<div className="text-[11px] text-muted">{x.camera_id}</div></td>
                <td className="px-2 py-2"><OutcomeChip outcome={x.outcome} />{x.outcome === "match" && x.criminal_id && <div className="mt-1"><Link className="text-accent" to={`/frs/watchlist/${x.criminal_id}`}>{x.name}</Link> <span className="text-kind-watchlist">candidate — verify</span></div>}{x.error && <div className="mt-1 text-sev-high">{x.error}</div>}</td>
                <td className="px-2 py-2 font-mono text-[11px] text-ink-2">{x.top_k.map((t) => <div key={t.criminal_id}>{t.name} · sim {t.score.toFixed(2)}</div>)}</td>
                <td className="tabular px-2 py-2 text-right">{x.latency_ms != null ? `${Math.round(x.latency_ms)} ms` : "—"}</td>
                <td className="px-3 py-2"><Badge color={x.trigger === "manual" ? "#9085e9" : "#6da7ec"}>{x.trigger}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
