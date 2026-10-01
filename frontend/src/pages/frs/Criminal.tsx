import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Lock, ShieldAlert } from "lucide-react";
import { get, type FrsSearch, type Identity } from "../../lib/api";
import { fmtDateTime, sim, titleCase } from "../../lib/format";
import { Badge, Card, Empty, ErrorBox, Img, KV, SkeletonRows } from "../../components/ui";
import { FrsShell, OutcomeChip, frsImg } from "./common";

interface CriminalDetail {
  id: string; name: string; group: string | null; subgroup: string | null; metadata: Record<string, any>; created_at?: string;
  images: { url: string; quality: number | null }[];
  frs_detections: { id: string; camera_id: string | null; time: string; similarity: number | null; state: string; review: string; thumb_url: string | null }[];
  vigil_identities: Identity[];
  vigil_matches: FrsSearch[];
  read_only: boolean;
}

const CASE_FIELDS = ["crime_number", "fir_number", "case_type", "police_station", "district", "charges", "blacklisted", "case_id"];

export default function FrsCriminal() {
  const { criminalId = "" } = useParams();
  const q = useQuery({ queryKey: ["frs-criminal", criminalId], queryFn: () => get<CriminalDetail>(`/api/frs/criminals/${criminalId}`) });
  const c = q.data;
  return (
    <FrsShell title={c ? <span className="flex items-center gap-2">{c.name} {c.metadata?.blacklisted && <Badge color="#e66767">blacklisted</Badge>}</span> : "Watchlist subject"}
      subtitle={<span className="flex items-center gap-1.5"><Lock size={12} /> Source: FRS backend (read-only) · {c ? [c.group, c.subgroup].filter(Boolean).join(" / ") : ""}</span>}
      actions={<Link to="/frs/watchlist" className="btn btn-sm"><ArrowLeft size={13} /> Watchlist</Link>}>
      {q.isLoading ? <SkeletonRows n={6} h="h-14" /> : q.error || !c ? <ErrorBox error={q.error ?? "Not found"} /> : (
        <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            <Card title="Enrolment photos (FRS)" bodyClass="p-3">
              <div className="grid grid-cols-2 gap-2">
                {c.images.map((im) => (
                  <div key={im.url}>
                    <Img src={frsImg(im.url)} alt="" className="aspect-square w-full rounded-md object-cover" />
                    {im.quality != null && <div className="mt-0.5 text-[10.5px] text-muted">quality {im.quality.toFixed(2)}</div>}
                  </div>
                ))}
              </div>
            </Card>
            <Card title="Case record">
              {CASE_FIELDS.filter((k) => k in (c.metadata ?? {})).map((k) => <KV key={k} k={titleCase(k)} v={String(c.metadata[k] === "" ? "—" : c.metadata[k])} />)}
              {c.created_at && <KV k="Enrolled in FRS" v={fmtDateTime(c.created_at)} />}
            </Card>
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            <div className="rounded-lg border border-[#e6676744] bg-[#e667670d] px-4 py-2.5 text-[12.5px] text-ink-2">
              <ShieldAlert size={13} className="mr-1.5 inline text-kind-watchlist" />
              Matches against this subject are <b className="text-ink">candidates — verify</b> the face against the enrolment photos before acting.
            </div>
            <Card title={`Linked VIGIL identities (${c.vigil_identities.length})`} bodyClass="p-3">
              {c.vigil_identities.length === 0 ? <Empty title="No VIGIL identity has matched this subject" /> : (
                <div className="flex flex-wrap gap-3">
                  {c.vigil_identities.map((i) => (
                    <Link key={i.id} to={`/frs/identities/${i.id}`} className="flex items-center gap-3 rounded-lg border border-line p-2 pr-4 hover:bg-surface-2">
                      <Img src={i.face_url} alt="" className="h-14 w-12 rounded object-cover" />
                      <div>
                        <div className="font-medium">{i.display_name ?? i.id}</div>
                        <div className="font-mono text-[11px] text-muted">{i.id} · {sim(i.frs_score)}</div>
                        <div className="text-[11px] text-muted">{i.sightings} sightings · last {fmtDateTime(i.last_seen)}</div>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </Card>
            <Card title={`VIGIL searches that returned this subject (${c.vigil_matches.length})`} bodyClass="p-0">
              {c.vigil_matches.length === 0 ? <Empty title="None" /> : (
                <table className="w-full text-left text-[12px]">
                  <tbody>
                    {c.vigil_matches.map((m) => (
                      <tr key={m.id} className="border-b border-line last:border-0">
                        <td className="px-3 py-2"><Img src={m.face_url} alt="" className="h-11 w-11 rounded object-cover" /></td>
                        <td className="px-2 py-2 text-ink-2">{fmtDateTime(m.ts)}</td>
                        <td className="px-2 py-2">{m.identity_id && <Link className="font-mono text-accent" to={`/frs/identities/${m.identity_id}`}>{m.identity_id}</Link>}</td>
                        <td className="px-2 py-2"><OutcomeChip outcome={m.outcome} /></td>
                        <td className="px-2 py-2 font-mono">{sim(m.score)}</td>
                        <td className="px-3 py-2 text-muted">{m.camera_id} · {m.trigger}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <Card title={`FRS detection history (${c.frs_detections.length})`} bodyClass="p-3">
              {c.frs_detections.length === 0 ? <Empty title="FRS has no detections of this subject" /> : (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2.5">
                  {c.frs_detections.map((d) => (
                    <div key={d.id} className="overflow-hidden rounded-lg border border-line bg-surface-2">
                      <Img src={frsImg(d.thumb_url)} alt="" className="aspect-square w-full object-cover" />
                      <div className="p-2 text-[11px]">
                        <div className="font-mono text-ink">{sim(d.similarity)}</div>
                        <div className="text-muted">{fmtDateTime(d.time)}</div>
                        <div className="truncate text-muted">{d.camera_id ?? "search / upload"} · {d.state.toLowerCase()} · {d.review.replace(/_/g, " ")}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </FrsShell>
  );
}
