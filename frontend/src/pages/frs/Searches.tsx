import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { get, qs, type FrsSearch } from "../../lib/api";
import { fmtDateTime, sim } from "../../lib/format";
import { Badge, Empty, ErrorBox, Img, SkeletonRows, Tabs, cx } from "../../components/ui";
import { Pager } from "../Incidents";
import { FrsShell, OutcomeChip } from "./common";

interface HistoryRow {
  id: string; created_at: string; outcome: string; score: number | null; matched_criminal_id: string | null; by_vigil: boolean;
  query_url: string | null; top_k: { name: string; criminal_id: string; score: number; image_url: string | null }[];
}

export default function FrsSearches() {
  const [tab, setTab] = useState<"vigil" | "backend">("vigil");
  return (
    <FrsShell title="Searches" subtitle="Every 1:N watchlist search — the ones VIGIL made, and the FRS backend's own match log">
      <div className="card">
        <div className="px-4 pt-2"><Tabs value={tab} onChange={setTab} tabs={[{ id: "vigil", label: "VIGIL searches" }, { id: "backend", label: "FRS backend match log" }]} /></div>
        {tab === "vigil" ? <VigilSearches /> : <BackendLog />}
      </div>
    </FrsShell>
  );
}

function VigilSearches() {
  const [outcome, setOutcome] = useState("");
  const [identity, setIdentity] = useState("");
  const [page, setPage] = useState(0);
  const limit = 40;
  const q = useQuery({
    queryKey: ["frs-searches", outcome, identity, page],
    queryFn: () => get<{ total: number; items: FrsSearch[] }>(`/api/frs/searches${qs({ outcome, identity_id: identity.trim().toUpperCase(), limit, offset: page * limit })}`),
    refetchInterval: 15000,
  });
  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {["", "match", "no_match", "no_face", "error"].map((o) => (
          <button key={o} className={cx("btn btn-sm", outcome === o && "btn-primary")} onClick={() => { setOutcome(o); setPage(0); }}>{o ? o.replace("_", " ") : "all outcomes"}</button>
        ))}
        <input className="input ml-auto w-[200px]" placeholder="Identity (P-00012)" value={identity} onChange={(e) => { setIdentity(e.target.value); setPage(0); }} />
      </div>
      {q.error && <ErrorBox error={q.error} />}
      {q.isLoading ? <SkeletonRows n={6} h="h-14" /> : (q.data?.items ?? []).length === 0 ? <Empty icon={History} title="No searches" hint="VIGIL searches the FRS watchlist once per identity at its best face, rate-limited; analysts can also trigger one from a profile." /> : (
        <table className="w-full text-left text-[12px]">
          <thead className="border-b border-line text-[11px] text-muted">
            <tr><th className="py-2 pr-2 font-medium">Query face</th><th className="px-2 font-medium">Time</th><th className="px-2 font-medium">Identity</th><th className="px-2 font-medium">Outcome</th><th className="px-2 font-medium">Top candidates</th><th className="px-2 text-right font-medium">Latency</th><th className="px-2 font-medium">Trigger</th></tr>
          </thead>
          <tbody>
            {q.data!.items.map((x) => (
              <tr key={x.id} className="border-b border-line last:border-0 align-top">
                <td className="py-2 pr-2"><Img src={x.face_url} alt="" className="h-12 w-12 rounded object-cover" /></td>
                <td className="px-2 py-2 text-ink-2">{fmtDateTime(x.ts)}<div className="text-[11px] text-muted">{x.camera_id}</div></td>
                <td className="px-2 py-2">{x.identity_id ? <Link className="font-mono text-accent" to={`/frs/identities/${x.identity_id}`}>{x.identity_id}</Link> : "—"}</td>
                <td className="px-2 py-2">
                  <OutcomeChip outcome={x.outcome} />
                  {x.outcome === "match" && x.criminal_id && <div className="mt-1"><Link className="text-accent" to={`/frs/watchlist/${x.criminal_id}`}>{x.name}</Link> · <span className="font-mono">{sim(x.score)}</span><div className="text-kind-watchlist">candidate — verify</div></div>}
                  {x.error && <div className="mt-1 text-sev-high">{x.error}</div>}
                </td>
                <td className="px-2 py-2 font-mono text-[11px] text-ink-2">{x.top_k.map((t) => <div key={t.criminal_id}>{t.name} · sim {t.score.toFixed(2)}</div>)}</td>
                <td className="tabular px-2 py-2 text-right">{x.latency_ms != null ? `${Math.round(x.latency_ms)} ms` : "—"}</td>
                <td className="px-2 py-2"><Badge color={x.trigger === "manual" ? "#9085e9" : "#6da7ec"}>{x.trigger}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Pager total={q.data?.total ?? 0} page={page} limit={limit} onPage={setPage} />
    </div>
  );
}

function BackendLog() {
  const [limit, setLimit] = useState(50);
  const q = useQuery({ queryKey: ["frs-history", limit], queryFn: () => get<HistoryRow[]>(`/api/frs/history?limit=${limit}`), refetchInterval: 20000 });
  return (
    <div className="p-4">
      <div className="mb-3 text-[12px] text-muted">Source: FRS backend (read-only) — its match_events log, including searches made by other FRS clients. Rows marked <Badge color="#9085e9">by VIGIL</Badge> came from this system.</div>
      {q.error && <ErrorBox error={q.error} />}
      {q.isLoading ? <SkeletonRows n={6} h="h-14" /> : (q.data ?? []).length === 0 ? <Empty title="FRS match log is empty" /> : (
        <table className="w-full text-left text-[12px]">
          <thead className="border-b border-line text-[11px] text-muted">
            <tr><th className="py-2 pr-2 font-medium">Query</th><th className="px-2 font-medium">Time</th><th className="px-2 font-medium">Outcome</th><th className="px-2 font-medium">Top candidates (FRS enrolment photo)</th><th className="px-2 font-medium">Client</th></tr>
          </thead>
          <tbody>
            {q.data!.map((r) => (
              <tr key={r.id} className="border-b border-line last:border-0 align-top">
                <td className="py-2 pr-2"><Img src={r.query_url} alt="" className="h-12 w-12 rounded object-cover" /></td>
                <td className="px-2 py-2 text-ink-2">{fmtDateTime(r.created_at)}</td>
                <td className="px-2 py-2"><OutcomeChip outcome={r.outcome} />{r.score != null && <div className="mt-1 font-mono">{sim(r.score)}</div>}</td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap gap-2">
                    {r.top_k.slice(0, 3).map((t) => (
                      <Link key={t.criminal_id} to={`/frs/watchlist/${t.criminal_id}`} className="flex items-center gap-1.5 rounded border border-line py-0.5 pl-0.5 pr-2 hover:bg-surface-2">
                        <Img src={t.image_url} alt="" className="h-8 w-8 rounded object-cover" />
                        <span className="text-[11px]"><span className="text-ink">{t.name}</span><br /><span className="font-mono text-muted">sim {t.score.toFixed(2)}</span></span>
                      </Link>
                    ))}
                  </div>
                </td>
                <td className="px-2 py-2">{r.by_vigil ? <Badge color="#9085e9">by VIGIL</Badge> : <span className="text-muted">FRS / other</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(q.data?.length ?? 0) >= limit && <div className="mt-3 flex justify-center"><button className="btn btn-sm" onClick={() => setLimit(limit + 50)}>Load more</button></div>}
    </div>
  );
}
