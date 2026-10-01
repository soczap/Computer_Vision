import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cctv, Download, Film, Pause, Pencil, Play, Plus, Power, Trash2, Undo2, Upload, Webcam } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { isDemo } from "../lib/datamode";
import { del, get, patch, post, postForm, type Camera, type Zone } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { Badge, Card, DemoBadge, Empty, ErrorBox, Field, Modal, PageHeader, SkeletonRows, Spinner, Toggle, cx } from "../components/ui";

const ZONE_COLOR: Record<string, string> = { restricted: "#d03b3b", monitored: "#fab219", entry: "#3987e5" };

export default function Cameras() {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const cams = useQuery({ queryKey: ["cameras"], queryFn: () => get<Camera[]>("/api/cameras"), refetchInterval: 5000 });
  const [add, setAdd] = useState(false);
  const [upload, setUpload] = useState(false);
  const [zonesFor, setZonesFor] = useState<Camera | null>(null);
  const inval = () => qc.invalidateQueries({ queryKey: ["cameras"] });
  const act = useMutation({
    mutationFn: ({ fn }: { fn: () => Promise<unknown>; label: string }) => fn(),
    onSuccess: (_, v) => { inval(); toast({ kind: "success", title: v.label }); },
    onError: (e) => toast({ kind: "error", title: "Action failed", body: (e as Error).message }),
  });
  const admin = can("admin");
  const nav = useNavigate();

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader
        title="Cameras"
        subtitle="Sources, analysis status and zones. FRS cameras are pulled from the FRS relay — no second RTSP session."
        actions={
          <>
            <button className="btn" onClick={() => nav("/webcam")}><Webcam size={14} /> Open webcam</button>
            <button className="btn" onClick={() => setUpload(true)}><Upload size={14} /> Analyse video file</button>
            {admin && <button className="btn btn-primary" onClick={() => setAdd(true)}><Plus size={14} /> Add camera</button>}
          </>
        }
      />
      <div className="card mb-4 flex flex-wrap items-center gap-4 p-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#3987e522] text-accent"><Webcam size={18} /></div>
        <div className="min-w-0 flex-1">
          <div className="font-medium">Browser camera (demo / local)</div>
          <div className="text-[12px] text-muted">Stream this computer's webcam as <span className="font-mono">webcam-&lt;username&gt;</span>. It runs the full pipeline — tracking, face re-identification, FRS watchlist search, behaviour rules — and appears on the Live wall for everyone.</div>
        </div>
        <button className="btn btn-primary" onClick={() => nav("/webcam")}><Webcam size={14} /> Open webcam</button>
      </div>
      <Card bodyClass="p-0">
        {cams.isLoading ? <div className="p-4"><SkeletonRows n={4} /></div> : (cams.data ?? []).length === 0 ? (
          <Empty icon={Cctv} title="No cameras yet" hint="Import a camera from the FRS system, add an RTSP stream, or upload a video to analyse." />
        ) : (
          <table className="w-full text-left">
            <thead className="border-b border-line text-[11.5px] text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Camera</th><th className="px-2 py-2 font-medium">Source</th>
                <th className="px-2 py-2 font-medium">Status</th><th className="px-2 py-2 text-right font-medium">FPS</th>
                <th className="px-2 py-2 text-right font-medium">Latency</th><th className="px-2 py-2 text-right font-medium">Tracks</th>
                <th className="px-4 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {cams.data!.map((c) => {
                const s = c.stats;
                return (
                  <tr key={c.id} className="border-b border-line last:border-0">
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-1.5"><Link to={`/live/${c.id}`} className="font-medium hover:text-accent">{c.name}</Link>{isDemo(c) && <DemoBadge compact />}</span>
                      <div className="font-mono text-[11px] text-muted">{c.id}{c.location ? ` · ${c.location}` : ""}</div>
                    </td>
                    <td className="max-w-[260px] px-2 py-2.5 text-[12px]">
                      <Badge color={c.source_type === "frs" ? "#9085e9" : c.source_type === "file" ? "#c98500" : c.source_type === "demo" ? "#fab219" : c.source_type === "browser" ? "#199e70" : "#3987e5"}>{c.source_type}</Badge>
                      <div className="mt-0.5 truncate font-mono text-[11px] text-muted" title={c.source_uri}>{c.source_type === "file" ? String(c.config?.uploaded_filename ?? "video file") : c.source_type === "demo" ? "synthetic — no stream" : c.source_type === "browser" ? "browser webcam (ingest)" : c.source_uri}</div>
                    </td>
                    <td className="px-2 py-2.5 text-[12px]">
                      {c.source_type === "demo" ? <span className="text-[11.5px] text-muted">synthetic — no stream</span> : !c.enabled ? (
                        <div className="flex flex-col items-start gap-0.5"><Badge color="#898781">{c.config?.reconnect_note ? "disabled — reconnect" : "disabled"}</Badge>
                          {c.config?.reconnect_note ? <span className="max-w-[240px] text-[11px] leading-snug text-muted">{String(c.config.reconnect_note)}</span> : null}</div>
                      ) : !s ? <Badge color="#898781">stopped</Badge> : (
                        <div className="flex flex-col items-start gap-0.5">
                          <Badge color={s.status === "running" ? (s.idle ? "#6da7ec" : "#0ca30c") : "#fab219"}>{s.status}{s.status === "running" && s.idle ? " · idle" : ""}</Badge>
                          {s.source_error && <span className="max-w-[220px] truncate text-[11px] text-sev-high" title={s.source_error}>{s.source_error}</span>}
                          {s.progress !== null && s.progress !== undefined && c.source_type === "file" && <span className="text-[11px] text-muted">{Math.round(s.progress * 100)}% of file</span>}
                        </div>
                      )}
                    </td>
                    <td className="tabular px-2 py-2.5 text-right">{s ? s.fps.toFixed(1) : "—"}</td>
                    <td className="tabular px-2 py-2.5 text-right">{s?.latency_ms ? `${s.latency_ms} ms` : "—"}</td>
                    <td className="tabular px-2 py-2.5 text-right">{s ? `${s.active_tracks} / ${s.tracks_total}` : "—"}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex justify-end gap-1">
                        {c.enabled && c.source_type !== "demo" && (s ? (
                          <button className="btn btn-sm" title="Stop analysis" onClick={() => act.mutate({ fn: () => post(`/api/cameras/${c.id}/stop`), label: `Stopped ${c.name}` })}><Pause size={12} /></button>
                        ) : (
                          <button className="btn btn-sm" title="Start analysis" onClick={() => act.mutate({ fn: () => post(`/api/cameras/${c.id}/start`), label: `Started ${c.name}` })}><Play size={12} /></button>
                        ))}
                        {admin && c.source_type !== "demo" && (
                          <>
                            <button className="btn btn-sm" title={c.enabled ? "Disable" : c.config?.reconnect_note ? "Reconnect" : "Enable"} onClick={() => act.mutate({ fn: () => patch(`/api/cameras/${c.id}`, { enabled: !c.enabled }), label: `${c.enabled ? "Disabled" : "Enabled"} ${c.name}` })}><Power size={12} className={c.enabled ? "text-good" : "text-muted"} /></button>
                            <button className="btn btn-sm" title="Zones" onClick={() => setZonesFor(c)}><Pencil size={12} /> Zones</button>
                            <button className="btn btn-sm btn-danger" title="Delete" onClick={() => confirm(`Delete camera ${c.name}? Its events and sightings are kept.`) && act.mutate({ fn: () => del(`/api/cameras/${c.id}`), label: `Deleted ${c.name}` })}><Trash2 size={12} /></button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      <AddCamera open={add} onClose={() => setAdd(false)} onDone={inval} />
      <UploadVideo open={upload} onClose={() => setUpload(false)} onDone={inval} />
      {zonesFor && <ZoneEditor camera={zonesFor} onClose={() => setZonesFor(null)} />}
    </div>
  );
}

function AddCamera({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [mode, setMode] = useState<"frs" | "stream">("frs");
  const [f, setF] = useState({ name: "", source_type: "rtsp", source_uri: "", location: "", analysis_fps: "" });
  const frs = useQuery({ queryKey: ["frs-cams"], queryFn: () => get<any[]>("/api/frs/cameras"), enabled: open && mode === "frs" });
  const existing = useQuery({ queryKey: ["cameras"], queryFn: () => get<Camera[]>("/api/cameras"), enabled: open });
  const imported = new Set((existing.data ?? []).filter((c) => c.source_type === "frs").map((c) => c.source_uri));
  const imp = useMutation({
    mutationFn: (id: string) => post(`/api/frs/cameras/${encodeURIComponent(id)}/import`),
    onSuccess: () => { onDone(); toast({ kind: "success", title: "Camera imported and started" }); },
    onError: (e) => toast({ kind: "error", title: "Import failed", body: (e as Error).message }),
  });
  const create = useMutation({
    mutationFn: () => post("/api/cameras", { name: f.name, source_type: f.source_type, source_uri: f.source_uri, location: f.location || null, analysis_fps: f.analysis_fps ? Number(f.analysis_fps) : null }),
    onSuccess: () => { onDone(); onClose(); toast({ kind: "success", title: `Added ${f.name}` }); setF({ name: "", source_type: "rtsp", source_uri: "", location: "", analysis_fps: "" }); },
  });
  return (
    <Modal open={open} onClose={onClose} title="Add camera" width={640}>
      <div className="mb-4 flex gap-1">
        <button className={cx("btn btn-sm", mode === "frs" && "btn-primary")} onClick={() => setMode("frs")}>From FRS (:8000)</button>
        <button className={cx("btn btn-sm", mode === "stream" && "btn-primary")} onClick={() => setMode("stream")}>RTSP / HTTP stream</button>
      </div>
      {mode === "frs" ? (
        frs.isLoading ? <SkeletonRows n={3} /> : frs.error ? <ErrorBox error={frs.error} /> : (
          <div className="flex flex-col gap-2">
            <p className="text-[12px] text-muted">VIGIL reads the FRS MJPEG relay of cameras FRS already decodes. FRS itself is not modified.</p>
            {(frs.data ?? []).map((c) => (
              <div key={c.id} className="flex items-center gap-3 rounded-md border border-line px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{c.name} <span className="font-mono text-[11px] text-muted">{c.id}</span></div>
                  <div className="text-[11.5px] text-muted">{c.location ?? "—"} · {c.native_resolution ?? c.resolution ?? "?"} · {c.running_in_frs ? `running in FRS (${c.frs_fps ?? "?"} fps)` : "not running in FRS"}</div>
                </div>
                {imported.has(c.id) ? <Badge color="#0ca30c">imported</Badge> : (
                  <button className="btn btn-sm btn-primary" disabled={imp.isPending} onClick={() => imp.mutate(c.id)}><Download size={12} /> Import</button>
                )}
              </div>
            ))}
          </div>
        )
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Type">
              <select className="input" value={f.source_type} onChange={(e) => setF({ ...f, source_type: e.target.value })}>
                <option value="rtsp">RTSP</option><option value="http">HTTP / MJPEG</option>
              </select>
            </Field>
          </div>
          <Field label="Stream URL" hint="Credentials are stored server-side and redacted in the UI."><input className="input font-mono" placeholder="rtsp://user:pass@host:554/stream" value={f.source_uri} onChange={(e) => setF({ ...f, source_uri: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Location"><input className="input" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
            <Field label="Analysis FPS" hint="Default 12"><input className="input" type="number" min={1} max={30} value={f.analysis_fps} onChange={(e) => setF({ ...f, analysis_fps: e.target.value })} /></Field>
          </div>
          <ErrorBox error={create.error} />
          <div className="flex justify-end"><button className="btn btn-primary" disabled={!f.name || !f.source_uri || create.isPending} onClick={() => create.mutate()}>{create.isPending ? <Spinner /> : <Plus size={14} />} Add</button></div>
        </div>
      )}
    </Modal>
  );
}

function UploadVideo({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [realtime, setRealtime] = useState(false);
  const [loop, setLoop] = useState(false);
  const m = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.set("file", file!);
      fd.set("name", name || file!.name.replace(/\.[^.]+$/, ""));
      fd.set("realtime", String(realtime));
      fd.set("loop", String(loop));
      if (location) fd.set("location", location);
      return postForm<Camera>("/api/cameras/upload", fd);
    },
    onSuccess: (c) => { onDone(); onClose(); setFile(null); setName(""); toast({ kind: "success", title: `Analysing ${c.name}`, href: `/live/${c.id}` }); },
  });
  return (
    <Modal open={open} onClose={onClose} title="Analyse a video file"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!file || m.isPending} onClick={() => m.mutate()}>{m.isPending ? <Spinner /> : <Upload size={14} />} Upload & analyse</button></>}>
      <div className="flex flex-col gap-3">
        <label className="flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line-strong px-4 py-6 text-ink-2 hover:bg-surface-2">
          <Film size={20} />
          <span>{file ? `${file.name} (${(file.size / 1e6).toFixed(1)} MB)` : "Choose a video (mp4, avi, mkv, mov…)"}</span>
          <input type="file" accept="video/*,.mkv,.avi,.ts" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={file?.name} /></Field>
          <Field label="Location"><input className="input" value={location} onChange={(e) => setLocation(e.target.value)} /></Field>
        </div>
        <div className="flex gap-6">
          <Toggle checked={realtime} onChange={setRealtime} label="Pace to real time" />
          <Toggle checked={loop} onChange={setLoop} label="Loop" />
        </div>
        <p className="text-[11.5px] text-muted">Unpaced files are analysed as fast as the GPU allows; paced files behave like a live camera.</p>
        <ErrorBox error={m.error} />
      </div>
    </Modal>
  );
}

interface DraftZone { id?: string; name: string; kind: Zone["kind"]; polygon: [number, number][]; loiter_s: string; max_occupancy: string; start: string; end: string; enabled: boolean }

function toDraft(z?: Zone): DraftZone {
  const r = (z?.rules ?? {}) as any;
  return {
    id: z?.id, name: z?.name ?? "", kind: z?.kind ?? "monitored", polygon: z?.polygon ?? [],
    loiter_s: r.loiter_s ? String(r.loiter_s) : "", max_occupancy: r.max_occupancy ? String(r.max_occupancy) : "",
    start: r.schedule?.start ?? "", end: r.schedule?.end ?? "", enabled: z?.enabled ?? true,
  };
}

function ZoneEditor({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const zones = useQuery({ queryKey: ["zones", camera.id], queryFn: () => get<Zone[]>(`/api/cameras/${camera.id}/zones`) });
  const [draft, setDraft] = useState<DraftZone | null>(null);
  const [snapErr, setSnapErr] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const inval = () => { qc.invalidateQueries({ queryKey: ["zones", camera.id] }); qc.invalidateQueries({ queryKey: ["cameras"] }); };
  const save = useMutation({
    mutationFn: (d: DraftZone) => {
      const rules: Record<string, unknown> = {};
      if (d.loiter_s) rules.loiter_s = Number(d.loiter_s);
      if (d.max_occupancy) rules.max_occupancy = Number(d.max_occupancy);
      if (d.start && d.end) rules.schedule = { start: d.start, end: d.end };
      const body = { name: d.name, kind: d.kind, polygon: d.polygon, rules, enabled: d.enabled };
      return d.id ? patch(`/api/zones/${d.id}`, body) : post(`/api/cameras/${camera.id}/zones`, body);
    },
    onSuccess: () => { inval(); setDraft(null); toast({ kind: "success", title: "Zone saved — camera analysis restarted with it" }); },
    onError: (e) => toast({ kind: "error", title: "Save failed", body: (e as Error).message }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => del(`/api/zones/${id}`),
    onSuccess: () => { inval(); setDraft(null); },
  });
  const click = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!draft || !svgRef.current) return;
    const r = svgRef.current.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    setDraft({ ...draft, polygon: [...draft.polygon, [Number(x.toFixed(4)), Number(y.toFixed(4))]] });
  };
  return (
    <Modal open onClose={onClose} title={`Zones · ${camera.name}`} width={1100}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div>
          <div className="relative aspect-video w-full overflow-hidden rounded-lg border border-line bg-black">
            {!snapErr ? <img src={`/api/cameras/${camera.id}/snapshot?t=${Date.now()}`} alt="" className="absolute inset-0 h-full w-full object-cover" onError={() => setSnapErr(true)} /> : (
              <div className="absolute inset-0 flex items-center justify-center text-[12px] text-muted">No live frame — start the camera to see the scene. You can still draw.</div>
            )}
            <svg ref={svgRef} viewBox="0 0 1 1" preserveAspectRatio="none" className={cx("absolute inset-0 h-full w-full", draft && "cursor-crosshair")} onClick={click}>
              {(zones.data ?? []).filter((z) => z.id !== draft?.id).map((z) => (
                <polygon key={z.id} points={z.polygon.map((p) => p.join(",")).join(" ")} fill={ZONE_COLOR[z.kind] + "30"} stroke={ZONE_COLOR[z.kind]} strokeWidth={0.003} />
              ))}
              {draft && draft.polygon.length > 0 && (
                <>
                  <polygon points={draft.polygon.map((p) => p.join(",")).join(" ")} fill={ZONE_COLOR[draft.kind] + "40"} stroke={ZONE_COLOR[draft.kind]} strokeWidth={0.004} strokeDasharray="0.01 0.006" />
                  {draft.polygon.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={0.006} fill="#fff" stroke={ZONE_COLOR[draft.kind]} strokeWidth={0.002} />)}
                </>
              )}
            </svg>
          </div>
          <div className="mt-2 text-[12px] text-muted">{draft ? "Click on the image to add polygon points (≥ 3). Coordinates are stored normalised 0–1." : "Select a zone to edit, or create a new one."}</div>
        </div>
        <div className="flex flex-col gap-3">
          {!draft ? (
            <>
              <button className="btn btn-primary" onClick={() => setDraft(toDraft())}><Plus size={14} /> New zone</button>
              {zones.isLoading ? <SkeletonRows n={3} /> : (zones.data ?? []).length === 0 ? <Empty title="No zones" hint="Zones enable intrusion, loitering thresholds, occupancy limits and schedules." /> : (
                zones.data!.map((z) => (
                  <button key={z.id} onClick={() => setDraft(toDraft(z))} className="flex items-center gap-2 rounded-md border border-line px-3 py-2 text-left hover:bg-surface-2">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: ZONE_COLOR[z.kind] }} />
                    <span className="flex-1 font-medium">{z.name}</span>
                    <span className="text-[11px] text-muted">{z.kind}{z.enabled ? "" : " · off"}</span>
                  </button>
                ))
              )}
            </>
          ) : (
            <>
              <Field label="Name"><input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
              <Field label="Kind">
                <select className="input" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as Zone["kind"] })}>
                  <option value="restricted">Restricted — alert on entry</option><option value="monitored">Monitored — dwell / loitering</option><option value="entry">Entry — counting</option>
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Loiter after (s)"><input className="input" type="number" min={5} value={draft.loiter_s} onChange={(e) => setDraft({ ...draft, loiter_s: e.target.value })} /></Field>
                <Field label="Max occupancy"><input className="input" type="number" min={1} value={draft.max_occupancy} onChange={(e) => setDraft({ ...draft, max_occupancy: e.target.value })} /></Field>
              </div>
              <Field label="Active schedule (optional)" hint="e.g. 20:00 → 06:00 for night-only restriction">
                <div className="flex items-center gap-2">
                  <input className="input w-full" type="time" value={draft.start} onChange={(e) => setDraft({ ...draft, start: e.target.value })} />→
                  <input className="input w-full" type="time" value={draft.end} onChange={(e) => setDraft({ ...draft, end: e.target.value })} />
                </div>
              </Field>
              <Toggle checked={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} label="Enabled" />
              <div className="text-[12px] text-muted">{draft.polygon.length} points</div>
              <div className="flex flex-wrap gap-2">
                <button className="btn btn-sm" disabled={!draft.polygon.length} onClick={() => setDraft({ ...draft, polygon: draft.polygon.slice(0, -1) })}><Undo2 size={12} /> Undo point</button>
                <button className="btn btn-sm" onClick={() => setDraft({ ...draft, polygon: [] })}>Clear</button>
              </div>
              <ErrorBox error={save.error} />
              <div className="flex gap-2">
                <button className="btn btn-primary flex-1 justify-center" disabled={!draft.name || draft.polygon.length < 3 || save.isPending} onClick={() => save.mutate(draft)}>{save.isPending ? <Spinner /> : "Save zone"}</button>
                <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
                {draft.id && <button className="btn btn-danger" onClick={() => confirm("Delete this zone?") && remove.mutate(draft.id!)}><Trash2 size={13} /></button>}
              </div>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}
