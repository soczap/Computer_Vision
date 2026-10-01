// Live annotated video over WS /ws/live/{camera}: [u32 BE header len][JSON header][JPEG].
// One frame in flight: the client acks after drawing, so slow links get fewer, fresher frames.
import { useEffect, useRef, useState } from "react";
import { wsUrl } from "../lib/api";
import { KIND_COLOR } from "../lib/format";
import { Spinner } from "./ui";

export interface LiveTrack {
  id: number;
  uid: string;
  box: [number, number, number, number];
  identity: string | null;
  label: string;
  kind: string;
  score: number | null;
  speed: number;
  posture: string;
  dwell: number;
  trail: [number, number][];
  kps: [number, number, number][];
}
export interface LiveHeader {
  camera_id: string;
  ts: number;
  w: number;
  h: number;
  tracks: LiveTrack[];
  objects: { label: string; box: [number, number, number, number]; conf: number; weapon: boolean; bag: boolean }[];
  zones: { id: string; name: string; kind: string; polygon: [number, number][] }[];
  violence: Record<string, number>;
  fps: number;
}

const EDGES: [number, number][] = [
  [0, 1], [0, 2], [1, 3], [2, 4], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
];
const ZONE_COLOR: Record<string, string> = { restricted: "#d03b3b", monitored: "#fab219", entry: "#3987e5" };

export interface OverlayOpts {
  skeleton?: boolean;
  trails?: boolean;
  zones?: boolean;
  labels?: boolean;
}

function draw(ctx: CanvasRenderingContext2D, img: ImageBitmap, h: LiveHeader, W: number, H: number, o: OverlayOpts) {
  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(img, 0, 0, W, H);
  drawOverlay(ctx, h, W, H, o);
}

/** Zones, objects, tracks (boxes, trails, skeletons, label chips) in normalised coords, no background. */
export function drawOverlay(ctx: CanvasRenderingContext2D, h: Pick<LiveHeader, "zones" | "objects" | "tracks">, W: number, H: number, o: OverlayOpts) {
  const s = Math.max(1, W / 960);
  if (o.zones !== false) {
    for (const z of h.zones) {
      const c = ZONE_COLOR[z.kind] ?? "#c3c2b7";
      ctx.beginPath();
      z.polygon.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
      ctx.closePath();
      ctx.fillStyle = c + "22";
      ctx.fill();
      ctx.setLineDash([6 * s, 4 * s]);
      ctx.strokeStyle = c + "cc";
      ctx.lineWidth = 1.5 * s;
      ctx.stroke();
      ctx.setLineDash([]);
      const [x0, y0] = z.polygon[0];
      ctx.font = `600 ${11 * s}px Inter, sans-serif`;
      ctx.fillStyle = c;
      ctx.fillText(z.name, x0 * W + 4 * s, y0 * H + 13 * s);
    }
  }
  for (const ob of h.objects) {
    const [x1, y1, x2, y2] = ob.box;
    const c = ob.weapon ? "#d03b3b" : "#c98500";
    ctx.strokeStyle = c;
    ctx.lineWidth = (ob.weapon ? 3 : 1.5) * s;
    ctx.strokeRect(x1 * W, y1 * H, (x2 - x1) * W, (y2 - y1) * H);
    ctx.font = `600 ${10.5 * s}px Inter, sans-serif`;
    ctx.fillStyle = c;
    ctx.fillText(`${ob.weapon ? "⚠ " : ""}${ob.label} ${ob.conf.toFixed(2)}`, x1 * W, y2 * H + 12 * s);
  }
  for (const t of h.tracks) {
    const c = KIND_COLOR[t.kind] ?? "#898781";
    if (o.trails !== false && t.trail.length > 1) {
      ctx.lineWidth = 2 * s;
      for (let i = 1; i < t.trail.length; i++) {
        ctx.strokeStyle = c + Math.round(40 + (i / t.trail.length) * 200).toString(16).padStart(2, "0");
        ctx.beginPath();
        ctx.moveTo(t.trail[i - 1][0] * W, t.trail[i - 1][1] * H);
        ctx.lineTo(t.trail[i][0] * W, t.trail[i][1] * H);
        ctx.stroke();
      }
    }
    if (o.skeleton && t.kps?.length === 17) {
      ctx.strokeStyle = c + "cc";
      ctx.lineWidth = 1.5 * s;
      for (const [a, b] of EDGES) {
        const ka = t.kps[a], kb = t.kps[b];
        if (ka[2] > 0.35 && kb[2] > 0.35) {
          ctx.beginPath();
          ctx.moveTo(ka[0] * W, ka[1] * H);
          ctx.lineTo(kb[0] * W, kb[1] * H);
          ctx.stroke();
        }
      }
      ctx.fillStyle = "#ffffff";
      for (const k of t.kps) if (k[2] > 0.35) ctx.fillRect(k[0] * W - 1.5 * s, k[1] * H - 1.5 * s, 3 * s, 3 * s);
    }
    const [x1, y1, x2, y2] = t.box;
    ctx.strokeStyle = c;
    ctx.lineWidth = (t.kind === "watchlist" ? 3 : 2) * s;
    ctx.strokeRect(x1 * W, y1 * H, (x2 - x1) * W, (y2 - y1) * H);
    if (o.labels !== false) {
      const parts = [t.label];
      if (t.score !== null && t.identity) parts.push(`sim ${t.score.toFixed(2)}`);
      parts.push(`${Math.round(t.dwell)}s`);
      if (t.posture === "down") parts.push("DOWN");
      const text = parts.join(" · ");
      ctx.font = `600 ${11 * s}px Inter, sans-serif`;
      const tw = ctx.measureText(text).width + 8 * s;
      const th = 16 * s;
      const ly = y1 * H - th < 0 ? y1 * H : y1 * H - th;
      ctx.fillStyle = c;
      ctx.fillRect(x1 * W - 1, ly, tw, th);
      ctx.fillStyle = "#fff";
      ctx.fillText(text, x1 * W + 4 * s, ly + 12 * s);
    }
  }
}

export default function LiveCanvas({ cameraId, opts = {}, onHeader, className }: {
  cameraId: string; opts?: OverlayOpts; onHeader?: (h: LiveHeader) => void; className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"connecting" | "live" | "error" | "closed">("connecting");
  const [err, setErr] = useState<string | null>(null);
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const hdrCb = useRef(onHeader);
  hdrCb.current = onHeader;
  const last = useRef<{ img: ImageBitmap; h: LiveHeader } | null>(null);

  const redraw = () => {
    const cv = canvasRef.current;
    const box = boxRef.current;
    const l = last.current;
    if (!cv || !box || !l) return;
    const ratio = l.h.h / l.h.w;
    const bw = box.clientWidth;
    const W = Math.round(bw * devicePixelRatio);
    const H = Math.round(bw * ratio * devicePixelRatio);
    if (cv.width !== W || cv.height !== H) {
      cv.width = W;
      cv.height = H;
    }
    const ctx = cv.getContext("2d");
    if (ctx) draw(ctx, l.img, l.h, W, H, optsRef.current);
  };

  useEffect(() => {
    redraw();
  }, [opts.skeleton, opts.trails, opts.zones, opts.labels]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const ro = new ResizeObserver(() => redraw());
    if (boxRef.current) ro.observe(boxRef.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    let retry = 1000;
    const dec = new TextDecoder();
    const connect = () => {
      setState("connecting");
      ws = new WebSocket(wsUrl(`/ws/live/${encodeURIComponent(cameraId)}`));
      ws.binaryType = "arraybuffer";
      ws.onmessage = async (ev) => {
        if (typeof ev.data === "string") {
          try {
            const j = JSON.parse(ev.data);
            if (j.error) {
              setErr(j.error);
              setState("error");
            }
          } catch {
            /* ignore */
          }
          return;
        }
        const buf = ev.data as ArrayBuffer;
        const n = new DataView(buf).getUint32(0);
        const header = JSON.parse(dec.decode(new Uint8Array(buf, 4, n))) as LiveHeader;
        try {
          const img = await createImageBitmap(new Blob([new Uint8Array(buf, 4 + n)], { type: "image/jpeg" }));
          last.current?.img.close();
          last.current = { img, h: header };
          setState("live");
          setErr(null);
          retry = 1000;
          redraw();
          hdrCb.current?.(header);
        } finally {
          if (ws?.readyState === WebSocket.OPEN) ws.send("ack");
        }
      };
      ws.onclose = (e) => {
        if (stop) return;
        if (e.code === 4401) {
          setErr("not authorised");
          setState("error");
          return;
        }
        setState((s) => (s === "error" ? s : "closed"));
        setTimeout(() => !stop && connect(), retry);
        retry = Math.min(retry * 2, 10000);
      };
    };
    connect();
    return () => {
      stop = true;
      ws?.close();
      last.current?.img.close();
      last.current = null;
    };
  }, [cameraId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={boxRef} className={`relative w-full overflow-hidden bg-black ${className ?? ""}`}>
      <canvas ref={canvasRef} className="block w-full" style={{ aspectRatio: last.current ? `${last.current.h.w}/${last.current.h.h}` : "16/9" }} />
      {state !== "live" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-[12px] text-muted">
          {state === "error" ? <span>{err ?? "unavailable"}</span> : <><Spinner /> <span>{state === "closed" ? "reconnecting…" : "connecting…"}</span></>}
        </div>
      )}
    </div>
  );
}
