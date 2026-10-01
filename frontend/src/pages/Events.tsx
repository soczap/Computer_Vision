import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ListFilter, XCircle } from "lucide-react";
import { get, post, qs, type Camera, type Paged, type VEvent } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { fmtDateTime, SEVERITIES, typeLabel, EVENT_TYPE_LABEL, STATUS_LABEL } from "../lib/format";
import { Card, DemoBadge, Drawer, Empty, ErrorBox, PageHeader, SeverityBadge, SkeletonRows, StatusBadge } from "../components/ui";
import { isDemo } from "../lib/datamode";
import { EvidenceView, Explanation, RunView, VerificationView } from "../components/domain";
import { Pager } from "./Incidents";

const RANGES: Record<string, number | null> = { "1h": 1, "24h": 24, "7d": 168, "30d": 720, all: null };

export default function Events() {
  const [sp, setSp] = useSearchParams();
  const [page, setPage] = useState(0);
  const [qText, setQText] = useState(sp.get("q") ?? "");
  const limit = 50;
  const f = {
    type: sp.get("type") ?? "",
    severity: sp.get("severity") ?? "",
    camera_id: sp.get("camera_id") ?? "",
    status: sp.get("status") ?? "",
    range: sp.get("range") ?? "24h",
    q: sp.get("q") ?? "",
  };
  const focus = sp.get("focus");
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    n.delete("focus");
    setSp(n, { replace: true });
    setPage(0);
  };
  useEffect(() => {
    const t = setTimeout(() => qText !== f.q && set("q", qText), 350);
    return () => clearTimeout(t);
  }, [qText]); // eslint-disable-line react-hooks/exhaustive-deps

  const hours = RANGES[f.range];
  const since = hours ? new Date(Date.now() - hours * 3600e3).toISOString() : undefined;
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => get<Camera[]>("/api/cameras") });
  const q = useQuery({
    queryKey: ["events", f, page],
    queryFn: () => get<Paged<VEvent>>(`/api/events${qs({ type: f.type, severity: f.severity, camera_id: f.camera_id, status: f.status, q: f.q, since, limit, offset: page * limit })}`),
    refetchInterval: 15000,
  });

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader title="Events" subtitle="Every detection the analytics raised, with its measured explanation and verification" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input className="input w-[240px]" placeholder="Search title/description…" value={qText} onChange={(e) => setQText(e.target.value)} />
        <select className="input" value={f.type} onChange={(e) => set("type", e.target.value)} aria-label="Type">
          <option value="">All types</option>
          {Object.entries(EVENT_TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className="input" value={f.severity} onChange={(e) => set("severity", e.target.value)} aria-label="Severity">
          <option value="">All severities</option>
          {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="input" value={f.camera_id} onChange={(e) => set("camera_id", e.target.value)} aria-label="Camera">
          <option value="">All cameras</option>
          {(cams.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="input" value={f.status} onChange={(e) => set("status", e.target.value)} aria-label="Status">
          <option value="">Any status</option>
          {["open", "pending_verification", "verified", "needs_review", "rejected", "dismissed"].map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <div className="ml-auto flex gap-1">
          {Object.keys(RANGES).map((r) => (
            <button key={r} className={`btn btn-sm ${f.range === r ? "btn-primary" : ""}`} onClick={() => set("range", r === "24h" ? "" : r)}>{r}</button>
          ))}
        </div>
      </div>
      <Card bodyClass="p-0">
        {q.isLoading ? <div className="p-4"><SkeletonRows n={8} /></div> : q.error ? <div className="p-4"><ErrorBox error={q.error} /></div> : (q.data?.items ?? []).length === 0 ? (
          <Empty icon={ListFilter} title="No events match these filters" />
        ) : (
          <table className="w-full text-left">
            <thead className="border-b border-line text-[11.5px] text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Time</th>
                <th className="px-2 py-2 font-medium">Severity</th>
                <th className="px-2 py-2 font-medium">Type</th>
                <th className="px-2 py-2 font-medium">Event</th>
                <th className="px-2 py-2 font-medium">Camera</th>
                <th className="px-2 py-2 text-right font-medium">Conf.</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {(q.data?.items ?? []).map((e) => (
                <tr key={e.id} onClick={() => { const n = new URLSearchParams(sp); n.set("focus", e.id); setSp(n); }}
                  className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2">
                  <td className="tabular whitespace-nowrap px-4 py-2 text-[12px] text-ink-2">{fmtDateTime(e.ts)}</td>
                  <td className="px-2 py-2"><SeverityBadge severity={e.severity} /></td>
                  <td className="whitespace-nowrap px-2 py-2 text-[12px] text-ink-2">{typeLabel(e.type)}</td>
                  <td className="max-w-[460px] px-2 py-2 font-medium"><div className="flex items-center gap-1.5"><span className="truncate">{e.title}</span>{isDemo(e) && <DemoBadge compact />}</div></td>
                  <td className="px-2 py-2 text-[12px] text-ink-2">{e.camera_id}</td>
                  <td className="tabular px-2 py-2 text-right text-[12px]">{e.confidence.toFixed(2)}</td>
                  <td className="px-4 py-2"><StatusBadge status={e.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Pager total={q.data?.total ?? 0} page={page} limit={limit} onPage={setPage} />
      <EventDrawer id={focus} onClose={() => { const n = new URLSearchParams(sp); n.delete("focus"); setSp(n); }} />
    </div>
  );
}

export function EventDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const toast = useToast();
  const [note, setNote] = useState("");
  const q = useQuery({ queryKey: ["event", id], queryFn: () => get<VEvent>(`/api/events/${id}`), enabled: !!id, refetchInterval: 10000 });
  const review = useMutation({
    mutationFn: (verdict: string) => post(`/api/events/${id}/review`, { verdict, note: note || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["event", id] });
      qc.invalidateQueries({ queryKey: ["events"] });
      setNote("");
      toast({ kind: "success", title: "Review recorded" });
    },
    onError: (e) => toast({ kind: "error", title: "Review failed", body: (e as Error).message }),
  });
  const e = q.data;
  return (
    <Drawer open={!!id} onClose={onClose} width={860}
      title={e ? <span className="flex items-center gap-2"><SeverityBadge severity={e.severity} /> <span className="truncate">{e.title}</span>{isDemo(e) && <DemoBadge />}</span> : "Event"}>
      {q.isLoading || !e ? <SkeletonRows n={6} h="h-12" /> : (
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
            <StatusBadge status={e.status} />
            <span>{typeLabel(e.type)}</span>·<span>{e.camera_id}</span>·<span>{fmtDateTime(e.ts)}</span>·<span className="font-mono">{e.id}</span>
            {e.incident_id && <Link to={`/incidents/${e.incident_id}`} className="ml-auto text-accent">Open incident →</Link>}
          </div>
          <EvidenceView evidence={e.evidence} />
          {e.description && <p className="leading-relaxed text-ink-2">{e.description}</p>}
          {e.identity_ids.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="label mr-1">People</span>
              {e.identity_ids.map((p) => <Link key={p} to={`/identities/${p}`} className="rounded-md border border-line px-2 py-0.5 font-mono text-[12px] text-accent">{p}</Link>)}
            </div>
          )}
          <section><div className="label mb-2">Why it fired</div><Explanation event={e} /></section>
          <section><div className="label mb-2">Verification</div><VerificationView v={e.verification} /></section>
          {can("analyst") && !isDemo(e) && (
            <section className="rounded-lg border border-line bg-surface-2 p-3">
              <div className="label mb-2">Human review</div>
              <div className="flex flex-wrap gap-2">
                <input className="input min-w-[200px] flex-1" placeholder="Optional note" value={note} onChange={(x) => setNote(x.target.value)} />
                <button className="btn" disabled={review.isPending} onClick={() => review.mutate("confirmed")}><CheckCircle2 size={13} className="text-good" /> Confirm</button>
                <button className="btn" disabled={review.isPending} onClick={() => review.mutate("dismissed")}><XCircle size={13} className="text-muted" /> Dismiss</button>
              </div>
            </section>
          )}
          {(e.agent_runs ?? []).length > 0 && (
            <section><div className="label mb-2">Agent activity</div>
              <div className="flex flex-col gap-2">{e.agent_runs!.map((r) => <RunView key={r.id} run={r} />)}</div>
            </section>
          )}
        </div>
      )}
    </Drawer>
  );
}
