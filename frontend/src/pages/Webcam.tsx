import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PersonStanding } from "lucide-react";
import WebcamPanel from "../components/WebcamPanel";
import type { LiveHeader } from "../components/LiveCanvas";
import { dur, KIND_COLOR, KIND_LABEL } from "../lib/format";
import { Card, Empty, PageHeader } from "../components/ui";
import { useAuth } from "../lib/auth";

export function InViewList({ hdr }: { hdr: LiveHeader | null }) {
  const nav = useNavigate();
  if (!hdr || hdr.tracks.length === 0) return <Empty icon={PersonStanding} title="Nobody in view" hint="Step in front of the camera; faces are identified after a few good views." />;
  return (
    <div className="flex flex-col">
      {hdr.tracks.map((t) => (
        <button key={t.uid} disabled={!t.identity} onClick={() => t.identity && nav(`/identities/${t.identity}`)}
          className="grid grid-cols-[10px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-surface-2 disabled:hover:bg-transparent">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND_COLOR[t.kind] }} />
          <div className="min-w-0">
            <div className="truncate font-medium">{t.label}</div>
            <div className="truncate text-[11px] text-muted">{KIND_LABEL[t.kind]}{t.score !== null && t.identity ? ` · sim ${t.score.toFixed(2)}` : ""}</div>
          </div>
          <span className="tabular text-[11.5px] text-ink-2">{dur(t.dwell)}</span>
        </button>
      ))}
    </div>
  );
}

export default function Webcam() {
  const [hdr, setHdr] = useState<LiveHeader | null>(null);
  const { can } = useAuth();
  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader title="Demo / Local camera" subtitle="Your browser's webcam as a live VIGIL camera — same pipeline as CCTV: tracking, face re-identification, FRS watchlist search, behaviour rules" />
      {!can("analyst") ? (
        <Card><Empty title="Streaming a camera requires the analyst role" hint="Viewers can watch the webcam camera from the Live wall once someone is streaming." /></Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="card p-3"><WebcamPanel onOverlay={setHdr} /></div>
          <Card title={`In view (${hdr?.tracks.length ?? 0})`} bodyClass="p-2"><InViewList hdr={hdr} /></Card>
        </div>
      )}
    </div>
  );
}
