// Realtime event/agent stream over WS /ws/stream, shared app-wide.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getDemoMode, wsUrl } from "./api";
import { useToast } from "./toast";
import { typeLabel } from "./format";

export interface StreamMsg {
  topic: string;
  data: any;
  at: number;
}
type Listener = (m: StreamMsg) => void;

interface StreamCtx {
  connected: boolean;
  recent: StreamMsg[];
  subscribe: (fn: Listener) => () => void;
}

const Ctx = createContext<StreamCtx>({ connected: false, recent: [], subscribe: () => () => undefined });

export function StreamProvider({ children, enabled }: { children: ReactNode; enabled: boolean }) {
  const [connected, setConnected] = useState(false);
  const [recent, setRecent] = useState<StreamMsg[]>([]);
  const listeners = useRef(new Set<Listener>());
  const qc = useQueryClient();
  const toast = useToast();
  const invalidateTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let ws: WebSocket | null = null;
    let stop = false;
    let retry = 1000;
    const pending = new Set<string>();
    const flush = () => {
      invalidateTimer.current = null;
      pending.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      pending.clear();
    };
    const invalidate = (...keys: string[]) => {
      keys.forEach((k) => pending.add(k));
      if (invalidateTimer.current === null) invalidateTimer.current = window.setTimeout(flush, 800);
    };
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/stream"));
      ws.onopen = () => {
        setConnected(true);
        retry = 1000;
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stop) setTimeout(connect, retry);
        retry = Math.min(retry * 2, 15000);
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (ev) => {
        let m: StreamMsg;
        try {
          const raw = JSON.parse(ev.data);
          m = { topic: raw.topic, data: raw.data, at: Date.now() };
        } catch {
          return;
        }
        listeners.current.forEach((fn) => fn(m));
        if (m.topic !== "agent.step") setRecent((xs) => [m, ...xs].slice(0, 200));
        const d = m.data ?? {};
        if (m.topic.startsWith("event.")) invalidate("events", "overview", "event");
        if (m.topic.startsWith("incident.")) invalidate("incidents", "incident", "overview");
        if (m.topic === "agent.run") invalidate("runs", "incident", "event");
        if (m.topic === "identity.created") invalidate("identities");
        if (m.topic === "track.closed") invalidate("tracks", "identity");
        if (m.topic === "frs.search") invalidate("frs-feed", "frs-searches", "frs-overview", "identity");
        const demo = !!d.is_demo || String(d.camera_id ?? "").startsWith("demo-");
        if (m.topic === "event.created" && (d.severity === "critical" || d.severity === "high") && !(demo && getDemoMode() === "exclude") && !(!demo && getDemoMode() === "only")) {
          toast({
            kind: d.severity === "critical" ? "critical" : "high",
            title: `${demo ? "DEMO · synthetic — " : ""}${typeLabel(d.type)} · ${d.camera_id ?? ""}`,
            body: d.title,
            href: d.incident_id ? `/incidents/${d.incident_id}` : `/events?focus=${d.id}`,
          });
        }
        if (m.topic === "notification") {
          toast({
            kind: d.severity === "critical" ? "critical" : d.severity === "high" ? "high" : "info",
            title: `Agent notification${d.by ? ` · ${d.by}` : ""}`,
            body: d.message,
            href: d.incident_id ? `/incidents/${d.incident_id}` : undefined,
          });
        }
      };
    };
    connect();
    return () => {
      stop = true;
      ws?.close();
      if (invalidateTimer.current) clearTimeout(invalidateTimer.current);
    };
  }, [enabled, qc, toast]);

  const subscribe = useCallback((fn: Listener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return <Ctx.Provider value={{ connected, recent, subscribe }}>{children}</Ctx.Provider>;
}

export const useStream = () => useContext(Ctx);

export function useStreamListener(fn: Listener, deps: unknown[] = []) {
  const { subscribe } = useStream();
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => subscribe((m) => ref.current(m)), [subscribe, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
}
