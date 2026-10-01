import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ScanSearch, Search as SearchIcon } from "lucide-react";
import { get, mediaUrl, post, type Camera, type Identity } from "../lib/api";
import { dur } from "../lib/format";
import { Card, DemoBadge, Empty, ErrorBox, Img, PageHeader, Skeleton, Spinner } from "../components/ui";
import { isDemo } from "../lib/datamode";

interface Hit {
  track_id: string;
  camera: string;
  start: string;
  end: string | null;
  duration_s: number;
  identity: string | null;
  similarity: number;
  person_url: string | null;
}
interface SearchRes {
  query?: string;
  track_id?: string;
  results?: Hit[];
  error?: string;
}

const SUGGEST = ["person in a white shirt", "man carrying a backpack", "person in a police uniform", "woman in a red dress", "person wearing a cap", "person in dark jacket"];

export default function Search() {
  const [sp, setSp] = useSearchParams();
  const [text, setText] = useState(sp.get("q") ?? "");
  const [hours, setHours] = useState(24);
  const [camera, setCamera] = useState("");
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => get<Camera[]>("/api/cameras") });
  const m = useMutation({
    mutationFn: (body: Record<string, unknown>) => post<SearchRes>("/api/search/appearance", body),
  });
  const trackParam = sp.get("track");
  const identityParam = sp.get("identity");

  useEffect(() => {
    if (trackParam) m.mutate({ track_id: trackParam, hours: 24 * 7, limit: 24 });
  }, [trackParam]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!identityParam) return;
    get<Identity>(`/api/identities/${identityParam}`).then((i) => {
      const t = (i.tracks ?? [])[0];
      if (t) setSp({ track: t.id }, { replace: true });
    });
  }, [identityParam]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = (e?: FormEvent, q?: string) => {
    e?.preventDefault();
    const v = (q ?? text).trim();
    if (!v) return;
    setText(v);
    setSp({ q: v }, { replace: true });
    m.mutate({ text: v, hours, camera_id: camera || null, limit: 24 });
  };
  const res = m.data;
  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader title="Search" subtitle="Find people by appearance across cameras (CLIP). Similarity ranks candidates — it is a lead, not an identity." />
      <Card>
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[280px] flex-1">
            <SearchIcon size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
            <input className="input w-full pl-8" placeholder="Describe the person: clothing, colours, carried items…" value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <select className="input" value={camera} onChange={(e) => setCamera(e.target.value)} aria-label="Camera">
            <option value="">All cameras</option>
            {(cams.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="input" value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Window">
            <option value={1}>Last hour</option><option value={24}>Last 24 h</option><option value={168}>Last 7 days</option><option value={720}>Last 30 days</option>
          </select>
          <button className="btn btn-primary" disabled={m.isPending || !text.trim()}>{m.isPending ? <Spinner /> : <ScanSearch size={14} />} Search</button>
        </form>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {SUGGEST.map((s) => <button key={s} className="btn btn-sm" onClick={() => submit(undefined, s)}>{s}</button>)}
        </div>
      </Card>
      <div className="mt-4">
        {m.isPending ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[260px]" />)}</div>
        ) : m.error ? <ErrorBox error={m.error} /> : res?.error ? <ErrorBox error={res.error} /> : res ? (
          <>
            <div className="mb-2 text-[12px] text-muted">
              {res.query ? <>Results for “{res.query}”</> : <>Sightings resembling track <span className="font-mono">{res.track_id}</span></>} · {res.results?.length ?? 0} candidates
            </div>
            {(res.results ?? []).length === 0 ? <Card><Empty icon={ScanSearch} title="No sightings with appearance descriptors in this window" /></Card> : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3">
                {res.results!.map((h) => (
                  <div key={h.track_id} className="card overflow-hidden">
                    <Img src={mediaUrl(h.person_url)} alt="" className="h-[190px] w-full bg-black object-contain" />
                    <div className="flex flex-col gap-0.5 p-2.5 text-[11.5px]">
                      <div className="flex justify-between"><span className="font-mono text-ink">sim {h.similarity.toFixed(2)}</span><span className="text-muted">{dur(h.duration_s)}</span></div>
                      <div className="flex items-center gap-1.5"><span className="truncate text-ink-2">{h.camera}</span>{isDemo({ camera: h.camera }) && <DemoBadge compact />}</div>
                      <div className="text-muted">{h.start}</div>
                      <div className="flex justify-between">
                        {h.identity ? <Link to={`/identities/${h.identity}`} className="font-mono text-accent">{h.identity}</Link> : <span className="text-muted">no face ID</span>}
                        <button className="text-accent" onClick={() => setSp({ track: h.track_id })}>similar</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <Card><Empty icon={ScanSearch} title="Search by description or from a sighting" hint="Open an identity and choose “Similar appearance”, or describe what the person wore." /></Card>
        )}
      </div>
    </div>
  );
}
