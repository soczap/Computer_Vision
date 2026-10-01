import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ScanFace, UserPlus } from "lucide-react";
import { get, qs, type Identity, type Paged } from "../../lib/api";
import { isDemo } from "../../lib/datamode";
import { ago, fmtDateTime } from "../../lib/format";
import { DemoBadge, Empty, ErrorBox, Img, Skeleton, WatchlistBadge, cx } from "../../components/ui";
import { Pager } from "../Incidents";
import { FrsShell, STATE } from "./common";

const FILTERS: { id: string; label: string; params: Record<string, string> }[] = [
  { id: "all", label: "All", params: {} },
  { id: "known", label: "Known (enrolled)", params: { kind: "enrolled" } },
  { id: "unknown", label: "Unknown (re-identified)", params: { kind: "unknown" } },
  { id: "watchlist", label: "Watchlist candidates", params: { watchlist: "true" } },
];

export function identityState(i: Identity): string {
  if (i.watchlist) return "watchlist_candidate";
  if (i.kind === "enrolled") return "known";
  return "reidentified";
}

export default function FrsIdentities() {
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const f = sp.get("f") ?? "all";
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [qd, setQd] = useState(q);
  const [page, setPage] = useState(0);
  const limit = 48;
  useEffect(() => {
    const t = setTimeout(() => setQd(q), 300);
    return () => clearTimeout(t);
  }, [q]);
  const params = FILTERS.find((x) => x.id === f)?.params ?? {};
  const res = useQuery({
    queryKey: ["identities", "frs", f, qd, page],
    queryFn: () => get<Paged<Identity>>(`/api/identities${qs({ ...params, q: qd, sort: "last_seen", limit, offset: page * limit })}`),
    refetchInterval: 15000,
  });
  return (
    <FrsShell title="Identities" subtitle="Everyone the face pipeline has resolved: enrolled people, re-identified unknowns (P-numbers), and FRS watchlist candidates"
      actions={<button className="btn btn-primary" onClick={() => nav("/frs/enroll")}><UserPlus size={14} /> Enrol person</button>}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((x) => (
          <button key={x.id} className={cx("btn btn-sm", f === x.id && "btn-primary")} onClick={() => { setSp(x.id === "all" ? {} : { f: x.id }); setPage(0); }}>{x.label}</button>
        ))}
        <input className="input ml-auto w-[260px]" placeholder="Search ID or name…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
      </div>
      {res.error && <ErrorBox error={res.error} />}
      {res.isLoading ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-3">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[150px]" />)}</div>
      ) : (res.data?.items ?? []).length === 0 ? (
        <div className="card"><Empty icon={ScanFace} title="No identities match" /></div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
          {res.data!.items.map((i) => {
            const st = STATE[identityState(i)];
            return (
              <button key={i.id} onClick={() => nav(`/frs/identities/${i.id}`)} className="card flex gap-3 p-2.5 text-left hover:border-line-strong" style={{ borderLeft: `3px solid ${st.color}` }}>
                <Img src={i.face_url} alt="" className="h-[104px] w-[86px] shrink-0 rounded-md object-cover" fallback={<ScanFace size={20} />} />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-semibold">{i.display_name ?? i.frs_name ?? i.id}</span>
                    {isDemo(i) && <DemoBadge compact />}
                  </div>
                  <div className="font-mono text-[11px] text-muted">{i.id}</div>
                  <div className="text-[11.5px]" style={{ color: st.color }}>{st.label}</div>
                  {i.watchlist && <WatchlistBadge name={i.frs_name} />}
                  <div className="mt-auto grid grid-cols-2 gap-x-2 text-[11px] text-muted">
                    <span>{i.sightings} sightings</span>
                    <span className="text-right">last {ago(i.last_seen)}</span>
                    <span className="col-span-2 truncate" title={fmtDateTime(i.first_seen)}>first {fmtDateTime(i.first_seen)}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
      <Pager total={res.data?.total ?? 0} page={page} limit={limit} onPage={setPage} />
    </FrsShell>
  );
}
