import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Download, FileText, Gauge, ListOrdered, Play, Send, ShieldCheck, Users } from "lucide-react";
import { get, patch, post, type Incident, type VEvent } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useStreamListener } from "../lib/stream";
import { useToast } from "../lib/toast";
import { ago, conf, fmtDateTime, fmtTime, SEV_COLOR, typeLabel } from "../lib/format";
import {
  Badge, Card, DemoBadge, Empty, ErrorBox, Markdown, PageHeader, SeverityBadge, SkeletonRows, Spinner, StatusBadge, Tabs,
} from "../components/ui";
import { isDemo } from "../lib/datamode";
import { EvidenceView, Explanation, RunView, VerificationView } from "../components/domain";

const STATUSES = ["new", "investigating", "confirmed", "false_positive", "resolved"];

export default function IncidentDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { can } = useAuth();
  const toast = useToast();
  const q = useQuery({ queryKey: ["incident", id], queryFn: () => get<Incident>(`/api/incidents/${id}`), refetchInterval: 20000 });
  const [tab, setTab] = useState<"events" | "trace" | "report">("events");
  const [note, setNote] = useState("");

  useStreamListener((m) => {
    const d = m.data ?? {};
    if ((m.topic === "agent.step" || m.topic === "agent.run") && d.incident_id === id) qc.invalidateQueries({ queryKey: ["incident", id] });
    if (m.topic === "incident.updated" && d.id === id) qc.invalidateQueries({ queryKey: ["incident", id] });
    if ((m.topic === "event.updated" || m.topic === "event.created") && d.incident_id === id) qc.invalidateQueries({ queryKey: ["incident", id] });
  }, [id]);

  const upd = useMutation({
    mutationFn: (body: Record<string, unknown>) => patch<Incident>(`/api/incidents/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incident", id] });
      qc.invalidateQueries({ queryKey: ["incidents"] });
      setNote("");
    },
    onError: (e) => toast({ kind: "error", title: "Update failed", body: String((e as Error).message) }),
  });
  const investigate = useMutation({
    mutationFn: () => post(`/api/incidents/${id}/investigate`),
    onSuccess: () => { toast({ kind: "info", title: "Investigation started", body: "The agent's reasoning streams into the trace tab." }); setTab("trace"); },
    onError: (e) => toast({ kind: "error", title: "Could not start investigation", body: (e as Error).message }),
  });
  const report = useMutation({
    mutationFn: () => post(`/api/incidents/${id}/report`),
    onSuccess: () => { toast({ kind: "info", title: "Report generation started" }); setTab("report"); },
    onError: (e) => toast({ kind: "error", title: "Report failed", body: (e as Error).message }),
  });

  if (q.isLoading) return <SkeletonRows n={8} h="h-10" />;
  if (q.error || !q.data) return <ErrorBox error={q.error ?? "Incident not found"} />;
  const i = q.data;
  const c = i.conclusion ?? {};
  const running = (i.agent_runs ?? []).some((r) => r.status === "running" && (r.agent === "investigator" || r.agent === "reporter"));
  const events = i.events ?? [];

  return (
    <div className="mx-auto max-w-[1500px]">
      <Link to="/incidents" className="mb-2 inline-flex items-center gap-1 text-[12px] text-muted hover:text-ink"><ArrowLeft size={13} /> Incidents</Link>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2"><SeverityBadge severity={i.severity} /> {i.title} {isDemo(i) && <DemoBadge />}</span>}
        subtitle={<>{typeLabel(i.type)} · {i.camera_id ?? "multi-camera"} · opened {fmtDateTime(i.created_at)} · updated {ago(i.updated_at)} · <span className="font-mono">{i.id}</span></>}
        actions={
          <>
            <StatusBadge status={i.status} />
            {can("analyst") && (
              <>
                <button className="btn" onClick={() => investigate.mutate()} disabled={investigate.isPending || running || isDemo(i)} title={isDemo(i) ? "Demo incidents cannot be investigated" : undefined}>
                  {running ? <Spinner /> : <Play size={13} />} {running ? "Agent working…" : "Investigate"}
                </button>
                <button className="btn" onClick={() => report.mutate()} disabled={report.isPending}><FileText size={13} /> Generate report</button>
              </>
            )}
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card title={<span className="flex items-center gap-2"><Bot size={14} className="text-accent" /> Investigation conclusion</span>}
            actions={c.at && <span className="text-[11.5px] text-muted">{ago(c.at)} · {c._tool_calls ?? 0} tool calls</span>}>
            {!c.summary ? (
              <Empty icon={Bot} title={running ? "The investigation agent is working…" : "Not investigated yet"}
                hint={running ? "Follow its reasoning live in the Agent trace tab." : "High and critical incidents are investigated automatically; you can also start one."} />
            ) : (
              <div className="flex flex-col gap-4">
                <p className="text-[13.5px] leading-relaxed text-ink">{c.summary}</p>
                <div className="flex flex-wrap gap-2">
                  {c.assessment && <Badge color={c.assessment === "real_threat" ? SEV_COLOR.critical : c.assessment === "likely_benign" ? "#0ca30c" : "#fab219"}><ShieldCheck size={11} /> {c.assessment.replace("_", " ")}</Badge>}
                  {c.threat_level && <Badge color={SEV_COLOR[c.threat_level] ?? "#898781"}><Gauge size={11} /> threat: {c.threat_level}</Badge>}
                  {c.confidence !== undefined && <Badge>confidence {conf(c.confidence)}</Badge>}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  {c.key_evidence && c.key_evidence.length > 0 && (
                    <div><div className="label mb-1.5">Key evidence</div><ul className="ml-4 list-disc text-[12.5px] leading-relaxed text-ink-2">{c.key_evidence.map((x, k) => <li key={k}>{x}</li>)}</ul></div>
                  )}
                  {c.recommended_actions && c.recommended_actions.length > 0 && (
                    <div><div className="label mb-1.5">Recommended actions</div><ol className="ml-4 list-decimal text-[12.5px] leading-relaxed text-ink-2">{c.recommended_actions.map((x, k) => <li key={k}>{x}</li>)}</ol></div>
                  )}
                </div>
                {c.timeline && c.timeline.length > 0 && (
                  <div><div className="label mb-1.5 flex items-center gap-1"><ListOrdered size={11} /> Timeline</div>
                    <ul className="flex flex-col gap-1 border-l border-line pl-3 text-[12.5px] text-ink-2">{c.timeline.map((x, k) => <li key={k}>{x}</li>)}</ul></div>
                )}
                {c.persons && c.persons.length > 0 && (
                  <div><div className="label mb-1.5 flex items-center gap-1"><Users size={11} /> Persons</div>
                    <div className="flex flex-col gap-1 text-[12.5px]">
                      {c.persons.map((p, k) => (
                        <div key={k} className="flex gap-2">
                          {p.id && /^P-\d+$/.test(p.id) ? <Link className="font-mono text-accent" to={`/identities/${p.id}`}>{p.id}</Link> : <span className="font-mono">{p.id}</span>}
                          <span className="text-ink">{p.role}</span>
                          <span className="text-muted">{p.notes}</span>
                        </div>
                      ))}
                    </div></div>
                )}
              </div>
            )}
          </Card>

          <div className="card">
            <div className="px-4 pt-2">
              <Tabs
                value={tab}
                onChange={setTab}
                tabs={[
                  { id: "events", label: `Events (${events.length})` },
                  { id: "trace", label: `Agent trace (${(i.agent_runs ?? []).length})` },
                  { id: "report", label: "Report" },
                ]}
              />
            </div>
            <div className="p-4">
              {tab === "events" && (
                events.length === 0 ? <Empty title="No events attached" /> : (
                  <div className="flex flex-col gap-5">{events.map((e) => <IncidentEvent key={e.id} e={e} />)}</div>
                )
              )}
              {tab === "trace" && (
                (i.agent_runs ?? []).length === 0 ? <Empty icon={Bot} title="No agent runs yet" /> : (
                  <div className="flex flex-col gap-2">
                    {[...(i.agent_runs ?? [])].reverse().map((r, k) => <RunView key={r.id} run={r} defaultOpen={k === 0} />)}
                  </div>
                )
              )}
              {tab === "report" && (
                i.report_md ? (
                  <div>
                    <div className="mb-3 flex justify-end">
                      <a className="btn btn-sm" href={`/api/incidents/${id}/report.md`} download><Download size={13} /> Download .md</a>
                    </div>
                    <Markdown text={i.report_md} />
                  </div>
                ) : (
                  <Empty icon={FileText} title={running ? "Report is being written…" : "No report yet"} hint="Critical incidents get a report automatically after investigation; analysts can generate one any time." />
                )
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          {can("analyst") && (
            <Card title="Workflow">
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-1">
                  {STATUSES.map((s) => (
                    <button key={s} className={`btn btn-sm ${i.status === s ? "btn-primary" : ""}`} disabled={upd.isPending || i.status === s}
                      onClick={() => upd.mutate({ status: s, note: note || undefined })}>
                      {s.replace("_", " ")}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <span className="label w-16">Severity</span>
                  <select className="input flex-1" value={i.severity} onChange={(e) => upd.mutate({ severity: e.target.value })}>
                    {["low", "medium", "high", "critical"].map((s) => <option key={s}>{s}</option>)}
                  </select>
                </div>
                <div className="flex items-center gap-2">
                  <span className="label w-16">Assignee</span>
                  <input className="input flex-1" defaultValue={i.assigned_to ?? ""} placeholder="unassigned"
                    onBlur={(e) => e.target.value !== (i.assigned_to ?? "") && upd.mutate({ assigned_to: e.target.value })} />
                </div>
                <div className="flex gap-2">
                  <input className="input flex-1" placeholder="Add a note…" value={note} onChange={(e) => setNote(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && note.trim() && upd.mutate({ note })} />
                  <button className="btn" disabled={!note.trim() || upd.isPending} onClick={() => upd.mutate({ note })}><Send size={13} /></button>
                </div>
              </div>
            </Card>
          )}
          {i.identity_ids.length > 0 && (
            <Card title="People involved">
              <div className="flex flex-wrap gap-1.5">
                {i.identity_ids.map((p) => <Link key={p} to={`/identities/${p}`} className="rounded-md border border-line px-2 py-1 font-mono text-[12px] text-accent hover:bg-surface-2">{p}</Link>)}
              </div>
            </Card>
          )}
          <Card title="Log" bodyClass="p-3 max-h-[520px] overflow-y-auto">
            {(i.notes ?? []).length === 0 ? <Empty title="No notes" /> : (
              <ul className="flex flex-col gap-2.5">
                {[...i.notes].reverse().map((n, k) => (
                  <li key={k} className="border-l-2 pl-2.5" style={{ borderColor: n.by.startsWith("agent") || n.by === "orchestrator" ? "#3987e5" : "#c3c2b7" }}>
                    <div className="text-[11px] text-muted">{n.by} · {fmtDateTime(n.ts)}</div>
                    <div className="text-[12.5px] leading-relaxed text-ink-2">{n.text}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function IncidentEvent({ e }: { e: VEvent }) {
  return (
    <div className="grid gap-4 border-b border-line pb-5 last:border-0 last:pb-0 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      <EvidenceView evidence={e.evidence} />
      <div className="flex min-w-0 flex-col gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={e.severity} />
            <StatusBadge status={e.status} />
            {isDemo(e) && <DemoBadge compact />}
            <span className="text-[11.5px] text-muted">{fmtTime(e.ts)} · {e.camera_id} · <span className="font-mono">{e.id}</span></span>
          </div>
          <div className="mt-1.5 font-medium">{e.title}</div>
          {e.description && <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">{e.description}</p>}
        </div>
        <div><div className="label mb-1.5">Why it fired</div><Explanation event={e} /></div>
        <div><div className="label mb-1.5">Verification</div><VerificationView v={e.verification} /></div>
      </div>
    </div>
  );
}
