import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Aperture, Camera as CamIcon, ImagePlus, Info, Power, UserPlus, X } from "lucide-react";
import { postForm, type Identity } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useToast } from "../../lib/toast";
import { titleCase } from "../../lib/format";
import { Card, Empty, ErrorBox, Field, Img, Spinner } from "../../components/ui";
import { CATEGORIES } from "../Identities";
import { FrsShell } from "./common";

interface EnrolResult {
  identity: Identity;
  photos_used: number;
  merged_existing_unknown: boolean;
  match_score: number | null;
  warnings: string[];
}

interface Photo { file: File; url: string; source: "upload" | "webcam" }

export default function FrsEnroll() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [category, setCategory] = useState("none");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [res, setRes] = useState<EnrolResult | null>(null);
  useEffect(() => () => photos.forEach((p) => URL.revokeObjectURL(p.url)), []); // eslint-disable-line react-hooks/exhaustive-deps

  const add = (files: File[], source: Photo["source"]) =>
    setPhotos((ps) => [...ps, ...files.map((file) => ({ file, url: URL.createObjectURL(file), source }))].slice(0, 10));

  const m = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.set("name", name.trim());
      fd.set("category", category);
      if (notes) fd.set("notes", notes);
      photos.forEach((p) => fd.append("files", p.file));
      return postForm<EnrolResult>("/api/identities/enroll", fd);
    },
    onSuccess: (r) => {
      setRes(r);
      qc.invalidateQueries({ queryKey: ["identities"] });
      toast({ kind: "success", title: `Enrolled ${r.identity.label}` });
    },
  });
  const warnings = res?.warnings ?? ((m.error as any)?.detail?.warnings as string[] | undefined) ?? [];
  const reset = () => { setName(""); setCategory("none"); setNotes(""); setPhotos([]); setRes(null); m.reset(); };

  return (
    <FrsShell title="Enrol a person" subtitle="Add a named person to VIGIL's recognition gallery from photos or the webcam">
      <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-[#3987e555] bg-[#3987e510] px-4 py-3 text-[12.5px] leading-relaxed text-ink-2">
        <Info size={15} className="mt-0.5 shrink-0 text-accent" />
        <div>Enrols into <b className="text-ink">VIGIL's recognition gallery</b>. The FRS (port 8000) watchlist is <b className="text-ink">read-only</b> and is not modified. If the photos match someone VIGIL has already seen as an unknown (P-number), that identity is upgraded in place and keeps its history.</div>
      </div>
      {!can("analyst") ? <Card><Empty title="Enrolment requires the analyst role" /></Card> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_480px]">
          <Card title="Details & photos">
            {res ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-4">
                  <Img src={res.identity.face_url} alt="" className="h-24 w-24 rounded-md object-cover" />
                  <div>
                    <div className="text-[16px] font-semibold">{res.identity.label}</div>
                    <div className="font-mono text-[12px] text-muted">{res.identity.id}</div>
                    <div className="text-[12px] text-ink-2">{res.photos_used} photo(s) used</div>
                  </div>
                </div>
                {res.merged_existing_unknown && (
                  <div className="rounded-md border border-[#3987e555] bg-[#3987e514] px-3 py-2 text-[12.5px]">
                    Matched existing unknown identity {res.identity.id} (sim {res.match_score?.toFixed(2)}) — upgraded in place; sighting history kept.
                  </div>
                )}
                {warnings.length > 0 && <ul className="ml-4 list-disc text-[12px] text-sev-medium">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
                <div className="flex gap-2">
                  <Link className="btn btn-primary" to={`/frs/identities/${res.identity.id}`}>Open profile</Link>
                  <button className="btn" onClick={reset}>Enrol another</button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <div className="grid gap-3 md:grid-cols-3">
                  <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
                  <Field label="Category">
                    <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
                      {CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
                    </select>
                  </Field>
                  <Field label="Notes"><input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
                </div>
                <Field label={`Photos (${photos.length}/10)`} hint="One person per photo; face ≥ 60 px. A frontal view plus ~30–60° turns works best.">
                  <div className="flex flex-wrap gap-2">
                    {photos.map((p, i) => (
                      <div key={p.url} className="relative">
                        <img src={p.url} alt="" className="h-20 w-20 rounded-md object-cover" />
                        <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1 text-[9.5px] text-ink-2">{p.source}</span>
                        <button className="absolute -right-1.5 -top-1.5 rounded-full bg-surface-3 p-0.5 text-ink hover:bg-[#d03b3b]" aria-label="Remove photo"
                          onClick={() => setPhotos((ps) => { URL.revokeObjectURL(ps[i].url); return ps.filter((_, j) => j !== i); })}><X size={11} /></button>
                      </div>
                    ))}
                    <label className="flex h-20 w-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-md border border-dashed border-line-strong text-[11px] text-muted hover:bg-surface-2">
                      <ImagePlus size={16} /> Upload
                      <input type="file" accept="image/*" multiple className="hidden" onChange={(e) => { add(Array.from(e.target.files ?? []), "upload"); e.target.value = ""; }} />
                    </label>
                  </div>
                </Field>
                <ErrorBox error={m.error} />
                {warnings.length > 0 && <ul className="ml-4 list-disc text-[12px] text-sev-medium">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
                <div className="flex justify-end">
                  <button className="btn btn-primary" disabled={!name.trim() || !photos.length || m.isPending} onClick={() => m.mutate()}>
                    {m.isPending ? <Spinner /> : <UserPlus size={14} />} Enrol into VIGIL gallery
                  </button>
                </div>
              </div>
            )}
          </Card>
          <CaptureCard onCapture={(files) => add(files, "webcam")} disabled={!!res} />
        </div>
      )}
    </FrsShell>
  );
}

/** Local-only preview (nothing is streamed); grabs 3 frames ~0.7 s apart for enrolment. */
function CaptureCard({ onCapture, disabled }: { onCapture: (f: File[]) => void; disabled?: boolean }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const stop = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setOn(false);
  };
  useEffect(() => stop, []); // eslint-disable-line react-hooks/exhaustive-deps
  const start = async () => {
    setErr(null);
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setErr("Camera access needs a secure page (https or http://localhost).");
      return;
    }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } } });
      stream.current = s;
      video.current!.srcObject = s;
      await video.current!.play();
      setOn(true);
    } catch (e) {
      const n = (e as DOMException).name;
      setErr(n === "NotAllowedError" ? "Camera permission denied — allow it in the address bar and retry." : n === "NotFoundError" ? "No camera found on this computer." : String((e as Error).message));
    }
  };
  const capture = async () => {
    const v = video.current;
    if (!v?.videoWidth) return;
    setBusy(true);
    const files: File[] = [];
    for (let i = 0; i < 3; i++) {
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext("2d")!.drawImage(v, 0, 0);
      const b = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.92));
      if (b) files.push(new File([b], `webcam-${Date.now()}-${i + 1}.jpg`, { type: "image/jpeg" }));
      if (i < 2) await new Promise((r) => setTimeout(r, 700));
    }
    setBusy(false);
    onCapture(files);
  };
  return (
    <Card title={<span className="flex items-center gap-2"><CamIcon size={14} /> Capture from webcam</span>}>
      <div className="relative aspect-video overflow-hidden rounded-lg border border-line bg-black">
        <video ref={video} muted playsInline className={on ? "h-full w-full object-contain" : "hidden"} />
        {!on && <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center text-[12px] text-muted">
          {err ? <span className="text-sev-high">{err}</span> : "Local preview only — frames stay in this browser until you enrol."}
          <button className="btn btn-sm" onClick={start} disabled={disabled}><CamIcon size={12} /> Start camera</button>
        </div>}
      </div>
      {on && (
        <div className="mt-3 flex items-center gap-2">
          <button className="btn btn-primary" disabled={busy || disabled} onClick={capture}>{busy ? <Spinner /> : <Aperture size={14} />} Capture 3 frames</button>
          <span className="text-[11.5px] text-muted">Turn your head slightly between shots.</span>
          <button className="btn btn-sm ml-auto" onClick={stop}><Power size={12} /> Stop</button>
        </div>
      )}
    </Card>
  );
}
