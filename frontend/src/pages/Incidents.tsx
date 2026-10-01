import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bot, FileWarning } from "lucide-react";
import { get, qs, type Incident, type Paged } from "../lib/api";
import { ago, fmtDateTime, SEVERITIES, typeLabel } from "../lib/format";
import { Card, DemoBadge, Empty, PageHeader, SeverityBadge, SkeletonRows, StatusBadge, cx } from "../components/ui";
import { isDemo } from "../lib/datamode";

const STATUS_SETS: Record<string, string> = {
  active: "new,investigating,confirmed",
  all: "",
  new: "new",
  investigating: "investigating",
  confirmed: "confirmed",
  resolved: "resolved",
  false_positive: "false_positive",
};

export default function Incidents() {
  const nav = useNavigate();
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(0);
  const limit = 40;
  const q = useQuery({
    queryKey: ["incidents", status, severity, page],
    queryFn: () => get<Paged<Incident>>(`/api/incidents${qs({ status: STATUS_SETS[status], severity, limit, offset: page * limit })}`),
    refetchInterval: 15000,
  });
  const items = q.data?.items ?? [];
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Incidents" subtitle="Correlated, verified events escalated for investigation" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {Object.keys(STATUS_SETS).map((s) => (
            <button key={s} className={cx("btn btn-sm", status === s && "btn-primary")} onClick={() => { setStatus(s); setPage(0); }}>
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
        <select className="input ml-auto" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(0); }} aria-label="Severity">
          <option value="">All severities</option>
          {SEVERITIES.slice(1).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <Card bodyClass="p-0">
        {q.isLoading ? <div className="p-4"><SkeletonRows n={6} /></div> : items.length === 0 ? (
          <Empty icon={FileWarning} title="No incidents match" />
        ) : (
          <table className="w-full text-left">
            <thead className="border-b border-line text-[11.5px] text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Severity</th>
                <th className="px-2 py-2 font-medium">Incident</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Agent assessment</th>
                <th className="px-2 py-2 text-right font-medium">Events</th>
                <th className="px-4 py-2 text-right font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2" onClick={() => nav(`/incidents/${i.id}`)}>
                  <td className="px-4 py-2.5"><SeverityBadge severity={i.severity} /></td>
                  <td className="max-w-[520px] px-2 py-2.5">
                    <div className="flex items-center gap-1.5"><span className="truncate font-medium">{i.title}</span>{isDemo(i) && <DemoBadge />}</div>
                    <div className="truncate text-[11.5px] text-muted">{typeLabel(i.type)} · {i.camera_id ?? "—"} · opened {fmtDateTime(i.created_at)}</div>
                  </td>
                  <td className="px-2 py-2.5"><StatusBadge status={i.status} /></td>
                  <td className="px-2 py-2.5 text-[12px] text-ink-2">
                    {i.conclusion?.assessment ? (
                      <span className="flex items-center gap-1.5"><Bot size={12} className="text-accent" />{i.conclusion.assessment.replace("_", " ")} · {i.conclusion.threat_level}</span>
                    ) : <span className="text-muted">—</span>}
                  </td>
                  <td className="tabular px-2 py-2.5 text-right">{i.event_count}</td>
                  <td className="px-4 py-2.5 text-right text-[12px] text-muted">{ago(i.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Pager total={q.data?.total ?? 0} page={page} limit={limit} onPage={setPage} />
    </div>
  );
}

export function Pager({ total, page, limit, onPage }: { total: number; page: number; limit: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (total <= limit) return <div className="mt-2 text-right text-[12px] text-muted">{total} total</div>;
  return (
    <div className="mt-3 flex items-center justify-end gap-2 text-[12px] text-muted">
      <span>{total} total · page {page + 1} of {pages}</span>
      <button className="btn btn-sm" disabled={page === 0} onClick={() => onPage(page - 1)}>Prev</button>
      <button className="btn btn-sm" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  );
}
