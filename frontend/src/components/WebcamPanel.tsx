// Browser webcam → VIGIL: POST /api/demo/webcam, then stream JPEGs over WS /ws/ingest/{camera}.
// The local <video> plays at full frame rate; analysis overlays (boxes/IDs) are drawn on a canvas
// on top and update at the analysis rate. ≤2 frames in flight; send rate adapts to ack latency.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { AlertTriangle, Camera as CamIcon, Power, Video } from "lucide-react";
import { post, wsUrl, type Camera } from "../lib/api";
import { drawOverlay, type LiveHeader, type LiveTrack } from "./LiveCanvas";
import { Badge, Spinner, Toggle, cx } from "./ui";

export interface IngestStatus {
  status?: string;
  fps?: number;
  latency_ms?: number | null;
  active_tracks?: number;
  faces?: number;
  tracks_total?: number;
  idle?: boolean;
}

export interface WebcamHandle {
  /** JPEG snapshots of the local video (full resolution), for enrolment. */
  snapshot: () => Promise<Blob | null>;
  running: boolean;
}

type Phase = "idle" | "starting" | "live" | "error";

function mediaError(e: unknown): string {
  const n = (e as DOMException)?.name;
  if (n === "NotAllowedError" || n === "SecurityError")
    return "Camera permission was denied. Allow camera access for this site in the browser's address bar (camera icon), then try again.";
  if (n === "NotFoundError" || n === "OverconstrainedError") return "No camera was found on this computer. Plug in a webcam or use a laptop with a built-in camera.";
  if (n === "NotReadableError") return "The camera is in use by another application (Zoom/Teams/another tab). Close it and try again.";
  return `Could not open the camera: ${(e as Error)?.message ?? String(e)}`;
}

const WebcamPanel = forwardRef<WebcamHandle, {
  onOverlay?: (h: LiveHeader) => void;
  onStatus?: (s: IngestStatus) => void;
  compact?: boolean;
  className?: string;
}>(function WebcamPanel({ onOverlay, onStatus, compact, className }, ref) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const overlayRef = useRef<LiveHeader | null>(null);
  const timerRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [err, setErr] = useState<string | null>(null);
  const [cam, setCam] = useState<Camera | null>(null);
  const [status, setStatus] = useState<IngestStatus>({});
  const [sendFps, setSendFps] = useState(0);
  const [skeleton, setSkeleton] = useState(false);
  const skelRef = useRef(false);
  skelRef.current = skeleton;
  const cbs = useRef({ onOverlay, onStatus });
  cbs.current = { onOverlay, onStatus };

  const secure = typeof window !== "undefined" && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

  const stop = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    timerRef.current = rafRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    overlayRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setPhase("idle");
    setSendFps(0);
  }, []);

  useEffect(() => stop, [stop]);

  useImperativeHandle(ref, () => ({
    running: phase === "live",
    snapshot: async () => {
      const v = videoRef.current;
      if (!v || !v.videoWidth) return null;
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext("2d")!.drawImage(v, 0, 0);
      return await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.92));
    },
  }), [phase]);

  const start = async () => {
    setErr(null);
    if (!secure) {
      setErr("insecure");
      setPhase("error");
      return;
    }
    setPhase("starting");
    try {
      const media = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false });
      streamRef.current = media;
      const v = videoRef.current!;
      v.srcObject = media;
      await v.play();
      const c = await post<Camera>("/api/demo/webcam");
      setCam(c);
      openSocket(c.id);
      drawLoop();
    } catch (e) {
      stop();
      setErr((e as DOMException)?.name ? mediaError(e) : `Could not start the webcam camera: ${(e as Error).message}`);
      setPhase("error");
    }
  };

  const openSocket = (cameraId: string) => {
    const ws = new WebSocket(wsUrl(`/ws/ingest/${encodeURIComponent(cameraId)}`));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    let inflight = 0;
    let interval = 100; // ~10 fps target
    const rtts: number[] = [];
    const sentAt: number[] = [];
    let sentCount = 0;
    let lastRate = performance.now();
    const work = document.createElement("canvas");

    const sendOne = () => {
      timerRef.current = window.setTimeout(sendOne, interval);
      const v = videoRef.current;
      if (!v || ws.readyState !== WebSocket.OPEN || inflight >= 2 || !v.videoWidth) return;
      const w = Math.min(960, v.videoWidth);
      const h = Math.round((v.videoHeight / v.videoWidth) * w);
      if (work.width !== w) {
        work.width = w;
        work.height = h;
      }
      work.getContext("2d")!.drawImage(v, 0, 0, w, h);
      inflight++;
      sentAt.push(performance.now());
      work.toBlob(async (b) => {
        if (!b || ws.readyState !== WebSocket.OPEN) {
          inflight--;
          return;
        }
        ws.send(await b.arrayBuffer());
        sentCount++;
        const now = performance.now();
        if (now - lastRate > 1000) {
          setSendFps(Math.round((sentCount * 1000) / (now - lastRate)));
          sentCount = 0;
          lastRate = now;
        }
      }, "image/jpeg", 0.75);
    };

    ws.onopen = () => {
      setPhase("live");
      sendOne();
    };
    ws.onmessage = (ev) => {
      let m: any;
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (m.type === "ack") {
        inflight = Math.max(0, inflight - 1);
        const t0 = sentAt.shift();
        if (t0) {
          rtts.push(performance.now() - t0);
          if (rtts.length > 10) rtts.shift();
          const avg = rtts.reduce((a, b) => a + b, 0) / rtts.length;
          // Adapt: slow acks → send less often (min ~3 fps); fast acks → back towards 10 fps.
          interval = avg > 350 ? Math.min(330, interval * 1.25) : avg < 150 ? Math.max(100, interval * 0.9) : interval;
        }
      } else if (m.type === "overlay") {
        overlayRef.current = m as LiveHeader;
        cbs.current.onOverlay?.(m as LiveHeader);
      } else if (m.type === "status") {
        setStatus(m);
        cbs.current.onStatus?.(m);
      } else if (m.type === "error") {
        setErr(m.error);
      }
    };
    ws.onclose = (e) => {
      if (wsRef.current !== ws) return;
      if (e.code === 4401 || e.code === 4403) {
        setErr(e.code === 4403 ? "Your role cannot stream a camera (analyst or admin required)." : "Session expired — sign in again.");
        stop();
        setPhase("error");
        return;
      }
      // transient drop: reconnect while the local stream is still running
      if (streamRef.current) setTimeout(() => streamRef.current && openSocket(cameraId), 1500);
    };
  };

  const drawLoop = () => {
    const step = () => {
      rafRef.current = requestAnimationFrame(step);
      const v = videoRef.current;
      const cv = canvasRef.current;
      if (!v || !cv || !v.videoWidth) return;
      const W = Math.round(cv.clientWidth * devicePixelRatio);
      const H = Math.round(cv.clientHeight * devicePixelRatio);
      if (cv.width !== W || cv.height !== H) {
        cv.width = W;
        cv.height = H;
      }
      const ctx = cv.getContext("2d")!;
      ctx.clearRect(0, 0, W, H);
      const o = overlayRef.current;
      if (o) drawOverlay(ctx, o, W, H, { skeleton: skelRef.current, trails: true, zones: true, labels: true });
    };
    step();
  };

  return (
    <div className={cx("flex flex-col gap-2", className)}>
      <div className="relative w-full overflow-hidden rounded-lg border border-line bg-black" style={{ aspectRatio: "16/9" }}>
        <video ref={videoRef} muted playsInline className={cx("absolute inset-0 h-full w-full object-contain", phase === "idle" && "hidden")} />
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />
        {phase !== "live" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            {phase === "starting" ? (
              <><Spinner size={18} /><span className="text-[12px] text-muted">Opening camera…</span></>
            ) : phase === "error" ? (
              <div className="max-w-[520px] rounded-lg border border-[#d03b3b55] bg-[#1a1a19] p-4 text-left text-[12.5px] leading-relaxed">
                <div className="mb-1.5 flex items-center gap-2 font-semibold text-ink"><AlertTriangle size={14} className="text-sev-critical" /> Webcam unavailable</div>
                {err === "insecure" ? (
                  <>
                    <p className="text-ink-2">Browsers only allow camera access on a secure page (HTTPS or <code>http://localhost</code>). This page is served from <code>{location.origin}</code>.</p>
                    <p className="mt-2 text-muted">Fix: open VIGIL via <b className="text-ink">https://&lt;host&gt;:8090</b>, or tunnel it — <code>ssh -N -L 8090:localhost:8090 user@dgx</code> — and browse to <b className="text-ink">https://localhost:8090</b>.</p>
                  </>
                ) : <p className="text-ink-2">{err}</p>}
                <button className="btn btn-sm mt-3" onClick={() => { setPhase("idle"); setErr(null); }}>Dismiss</button>
              </div>
            ) : (
              <>
                <Video size={28} className="text-muted" />
                <div className="text-[13px] text-ink-2">Stream this computer's webcam into VIGIL for live face recognition and analytics.</div>
                <div className="text-[11.5px] text-muted">Video is analysed on the server; the camera appears as <span className="font-mono">webcam-&lt;you&gt;</span> for other viewers.</div>
                <button className="btn btn-primary mt-1" onClick={start}><CamIcon size={14} /> Connect laptop webcam</button>
              </>
            )}
          </div>
        )}
        {phase === "live" && (
          <div className="absolute left-2 top-2 flex gap-1.5">
            <Badge color="#d03b3b"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#d03b3b]" /> LIVE</Badge>
            {status.idle && <Badge color="#6da7ec">idle</Badge>}
          </div>
        )}
      </div>
      {phase === "live" && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
          <span className="font-mono text-ink-2">{cam?.id}</span>
          <span>sending {sendFps} fps</span>
          <span>analysis {status.fps?.toFixed?.(1) ?? "—"} fps</span>
          <span>latency {status.latency_ms ?? "—"} ms</span>
          <span>{status.active_tracks ?? 0} in view</span>
          {!compact && <span>{status.faces ?? 0} face observations</span>}
          <span className="ml-auto flex items-center gap-3">
            <Toggle checked={skeleton} onChange={setSkeleton} label="Skeleton" />
            <button className="btn btn-sm btn-danger" onClick={stop}><Power size={12} /> Disconnect</button>
          </span>
        </div>
      )}
    </div>
  );
});

export default WebcamPanel;
export type { LiveTrack };
