import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { get } from "../../lib/api";
import { titleCase } from "../../lib/format";
import { Badge, Empty, ErrorBox, Img, Skeleton, cx } from "../../components/ui";
import { FrsShell, frsImg } from "./common";

export interface Criminal {
  id: string; name: string; group: string | null; subgroup: string | null;
  metadata: Record<string, any>; image_count: number; photo_url: string | null;
}

export default function FrsWatchlist() {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["frs-criminals"], queryFn: () => get<Criminal[]>("/api/frs/criminals"), staleTime: 60000 });
  const [group, setGroup] = useState("");
  const [text, setText] = useState("");
  const groups = useMemo(() => Array.from(new Set((q.data ?? []).map((c) => c.group ?? "ungrouped"))).sort(), [q.data]);
  const rows = (q.data ?? []).filter((c) => (!group || (c.group ?? "ungrouped") === group) && (!text || c.name.toLowerCase().includes(text.toLowerCase())));
  return (
    <FrsShell title="Watchlist" subtitle={<>Source: <b className="text-ink-2">FRS backend (read-only)</b> — subjects enrolled in the port-8000 system. VIGIL searches against it; it never writes to it.</>}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button className={cx("btn btn-sm", !group && "btn-primary")} onClick={() => setGroup("")}>All ({q.data?.length ?? 0})</button>
        {groups.map((g) => (
          <button key={g} className={cx("btn btn-sm", group === g && "btn-primary")} onClick={() => setGroup(g)}>
            {titleCase(g)} ({(q.data ?? []).filter((c) => (c.group ?? "ungrouped") === g).length})
          </button>
        ))}
        <input className="input ml-auto w-[240px]" placeholder="Filter by name…" value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      {q.error && <ErrorBox error={q.error} />}
      {q.isLoading ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3">{Array.from({ length: 12 }).map((_, i) => <Skeleton key={i} className="h-[250px]" />)}</div>
      ) : rows.length === 0 ? <div className="card"><Empty icon={ShieldAlert} title="No subjects" /></div> : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3">
          {rows.map((c) => (
            <button key={c.id} onClick={() => nav(`/frs/watchlist/${c.id}`)} className="card overflow-hidden text-left hover:border-line-strong">
              <div className="relative">
                <Img src={frsImg(c.photo_url)} alt={c.name} className="aspect-[4/5] w-full object-cover" fallback={<ShieldAlert size={24} />} />
                {c.metadata?.blacklisted && <span className="absolute left-2 top-2 rounded-md bg-black/80"><Badge color="#e66767">blacklisted</Badge></span>}
              </div>
              <div className="flex flex-col gap-0.5 p-2.5">
                <div className="truncate font-semibold">{c.name}</div>
                <div className="truncate text-[11px] text-muted">{[c.group, c.subgroup].filter(Boolean).join(" / ") || "—"}</div>
                <div className="truncate text-[11px] text-ink-2">{c.metadata?.case_type ?? ""}{c.metadata?.police_station ? ` · ${c.metadata.police_station}` : ""}</div>
                <div className="text-[11px] text-muted">{c.image_count} photo(s)</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </FrsShell>
  );
}
