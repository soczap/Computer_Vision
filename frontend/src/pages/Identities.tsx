import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, UserPlus, Users } from "lucide-react";
import { get, mediaUrl, postForm, qs, type Identity, type Paged } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { ago, KIND_COLOR, titleCase } from "../lib/format";
import { Badge, DemoBadge, Empty, ErrorBox, Field, Img, Modal, PageHeader, Skeleton, Spinner, WatchlistBadge, cx } from "../components/ui";
import { isDemo } from "../lib/datamode";
import { Pager } from "./Incidents";

export const CATEGORIES = ["none", "staff", "vip", "watch", "banned"];
export const CAT_COLOR: Record<string, string> = { staff: "#0ca30c", vip: "#9085e9", watch: "#d95926", banned: "#d03b3b", none: "#898781" };

export function identityKind(i: Identity): string {
  if (i.watchlist) return "watchlist";
  if (i.category === "watch" || i.category === "banned") return "watch";
  if (i.kind === "enrolled") return "known";
  return "reidentified";
}

export default function Identities() {
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const { can } = useAuth();
  const [page, setPage] = useState(0);
  const [qText, setQText] = useState(sp.get("q") ?? "");
  const [enrol, setEnrol] = useState(false);
  const limit = 60;
  const f = { q: sp.get("q") ?? "", kind: sp.get("kind") ?? "", category: sp.get("category") ?? "", watchlist: sp.get("watchlist") ?? "", sort: sp.get("sort") ?? "last_seen" };
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v); else n.delete(k);
    setSp(n, { replace: true });
    setPage(0);
  };
  useEffect(() => {
    const t = setTimeout(() => qText !== f.q && set("q", qText), 300);
    return () => clearTimeout(t);
  }, [qText]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useQuery({
    queryKey: ["identities", f, page],
    queryFn: () => get<Paged<Identity>>(`/api/identities${qs({ ...f, limit, offset: page * limit })}`),
    refetchInterval: 20000,
  });
  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader
        title="Identities"
        subtitle="Persistent person IDs from pooled face evidence. Unknown people get a P-number and keep it when they return."
        actions={can("analyst") && <button className="btn btn-primary" onClick={() => setEnrol(true)}><UserPlus size={14} /> Enrol person</button>}
      />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input className="input w-[260px]" placeholder="Search ID or name…" value={qText} onChange={(e) => setQText(e.target.value)} />
        <select className="input" value={f.kind} onChange={(e) => set("kind", e.target.value)} aria-label="Kind">
          <option value="">Enrolled + unknown</option><option value="enrolled">Enrolled</option><option value="unknown">Unknown (re-identified)</option>
        </select>
        <select className="input" value={f.category} onChange={(e) => set("category", e.target.value)} aria-label="Category">
          <option value="">Any category</option>{CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
        </select>
        <select className="input" value={f.watchlist} onChange={(e) => set("watchlist", e.target.value)} aria-label="Watchlist">
          <option value="">Watchlist: any</option><option value="true">FRS watchlist candidates</option><option value="false">Not on watchlist</option>
        </select>
        <select className="input ml-auto" value={f.sort} onChange={(e) => set("sort", e.target.value)} aria-label="Sort">
          <option value="last_seen">Last seen</option><option value="sightings">Most sightings</option><option value="created">Newest</option>
        </select>
      </div>
      {q.error && <ErrorBox error={q.error} />}
      {q.isLoading ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-3">{Array.from({ length: 12 }).map((_, i) => <Skeleton key={i} className="h-[236px]" />)}</div>
      ) : (q.data?.items ?? []).length === 0 ? (
        <div className="card"><Empty icon={Users} title="No identities yet" hint="Identities appear automatically when a face is seen clearly enough (≥3 good observations), or when you enrol someone." /></div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-3">
          {(q.data?.items ?? []).map((i) => {
            const k = identityKind(i);
            return (
              <button key={i.id} onClick={() => nav(`/identities/${i.id}`)} className="card group overflow-hidden text-left hover:border-line-strong">
                <div className="relative">
                  <Img src={mediaUrl(i.face_url)} alt={i.label} className="aspect-[4/5] w-full object-cover" fallback={<Users size={28} />} />
                  <span className="absolute inset-x-0 bottom-0 h-1" style={{ background: KIND_COLOR[k] }} />
                  {i.watchlist && <span className="absolute left-2 top-2 rounded-md bg-black/80 backdrop-blur-sm"><WatchlistBadge /></span>}
                  {isDemo(i) && <span className="absolute bottom-2.5 left-2"><DemoBadge /></span>}
                </div>
                <div className="flex flex-col gap-1 p-2.5">
                  <div className="truncate font-medium">{i.display_name ?? i.frs_name ?? i.id}</div>
                  <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
                    <span className="font-mono">{i.id}</span>
                    <span>{i.sightings} seen</span>
                  </div>
                  <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
                    {i.category !== "none" ? <Badge color={CAT_COLOR[i.category]}>{i.category}</Badge> : <span>{i.kind}</span>}
                    <span>{ago(i.last_seen)}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
      <Pager total={q.data?.total ?? 0} page={page} limit={limit} onPage={setPage} />
      <EnrolModal open={enrol} onClose={() => setEnrol(false)} />
    </div>
  );
}

interface EnrolResult {
  identity: Identity;
  photos_used: number;
  merged_existing_unknown: boolean;
  match_score: number | null;
  warnings: string[];
}

export function EnrolModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [category, setCategory] = useState("none");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [res, setRes] = useState<EnrolResult | null>(null);
  const reset = () => { setName(""); setCategory("none"); setNotes(""); setFiles([]); setRes(null); m.reset(); };
  const m = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.set("name", name);
      fd.set("category", category);
      if (notes) fd.set("notes", notes);
      files.forEach((f) => fd.append("files", f));
      return postForm<EnrolResult>("/api/identities/enroll", fd);
    },
    onSuccess: (r) => { setRes(r); qc.invalidateQueries({ queryKey: ["identities"] }); toast({ kind: "success", title: `Enrolled ${r.identity.label}` }); },
  });
  const warnings = res?.warnings ?? ((m.error as any)?.detail?.warnings as string[] | undefined) ?? [];
  return (
    <Modal open={open} onClose={() => { reset(); onClose(); }} title="Enrol a person" width={600}
      footer={res ? (
        <>
          <button className="btn" onClick={reset}>Enrol another</button>
          <Link className="btn btn-primary" to={`/identities/${res.identity.id}`} onClick={() => { reset(); onClose(); }}>Open profile</Link>
        </>
      ) : (
        <>
          <button className="btn" onClick={() => { reset(); onClose(); }}>Cancel</button>
          <button className="btn btn-primary" disabled={!name.trim() || !files.length || m.isPending} onClick={() => m.mutate()}>
            {m.isPending ? <Spinner /> : <UserPlus size={14} />} Enrol
          </button>
        </>
      )}>
      {res ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <Img src={mediaUrl(res.identity.face_url)} alt="" className="h-20 w-20 rounded-md object-cover" />
            <div>
              <div className="text-[15px] font-semibold">{res.identity.label}</div>
              <div className="font-mono text-[12px] text-muted">{res.identity.id}</div>
              <div className="text-[12px] text-ink-2">{res.photos_used} photo(s) used</div>
            </div>
          </div>
          {res.merged_existing_unknown && (
            <div className="rounded-md border border-[#3987e555] bg-[#3987e514] px-3 py-2 text-[12.5px]">
              These photos matched an existing unknown identity ({res.identity.id}, sim {res.match_score?.toFixed(2)}). It was upgraded in place, so their sighting history is kept.
            </div>
          )}
          {warnings.length > 0 && <ul className="ml-4 list-disc text-[12px] text-sev-medium">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Category">
              <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
              </select>
            </Field>
            <Field label="Notes"><input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          </div>
          <Field label="Photos (1–10, one person, face ≥ 60 px)" hint="Use a frontal photo plus ~30–60° turns. All photos must be the same person.">
            <label className={cx("flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line-strong px-4 py-6 text-ink-2 hover:bg-surface-2")}>
              <ImagePlus size={20} />
              <span>{files.length ? `${files.length} file(s) selected` : "Choose images"}</span>
              <input type="file" accept="image/*" multiple className="hidden" onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 10))} />
            </label>
          </Field>
          {files.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {files.map((f) => <img key={f.name} src={URL.createObjectURL(f)} alt={f.name} className="h-16 w-16 rounded object-cover" />)}
            </div>
          )}
          <ErrorBox error={m.error} />
          {warnings.length > 0 && <ul className="ml-4 list-disc text-[12px] text-sev-medium">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        </div>
      )}
    </Modal>
  );
}
