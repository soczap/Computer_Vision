// Global "Real | Real + Demo | Demo only" data mode. Persisted per browser; applied to every list call.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { get, setDemoModeForApi, type DemoMode } from "./api";

const KEY = "vigil.dataMode";

interface Ctx {
  mode: DemoMode;
  setMode: (m: DemoMode) => void;
  includesDemo: boolean;
  demoPresent: boolean;
}
const C = createContext<Ctx>({ mode: "include", setMode: () => undefined, includesDemo: true, demoPresent: false });

function stored(): DemoMode | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "exclude" || v === "include" || v === "only" ? v : null;
  } catch {
    return null;
  }
}

export function DataModeProvider({ children, enabled }: { children: ReactNode; enabled: boolean }) {
  const qc = useQueryClient();
  const [mode, setModeState] = useState<DemoMode>(() => {
    const m = stored() ?? "include";
    setDemoModeForApi(m);
    return m;
  });
  const [demoPresent, setPresent] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    get<{ present: boolean }>("/api/demo/data")
      .then((d) => {
        setPresent(d.present);
        if (!stored()) {
          const m: DemoMode = d.present ? "include" : "exclude";
          setDemoModeForApi(m);
          setModeState(m);
        }
      })
      .catch(() => undefined);
  }, [enabled]);

  const setMode = useCallback((m: DemoMode) => {
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* per-browser convenience only */
    }
    setDemoModeForApi(m);
    setModeState(m);
    qc.resetQueries();
  }, [qc]);

  return <C.Provider value={{ mode, setMode, includesDemo: mode !== "exclude", demoPresent }}>{children}</C.Provider>;
}

export const useDataMode = () => useContext(C);

/** Demo rows carry is_demo; ids/prefixes are a fallback for payloads that omit it (e.g. agent tool output). */
export function isDemo(x: { is_demo?: boolean; id?: string; camera_id?: string | null; camera?: string } | null | undefined): boolean {
  if (!x) return false;
  if (x.is_demo) return true;
  const id = x.id ?? "";
  const cam = x.camera_id ?? x.camera ?? "";
  return /^D-\d+$/.test(id) || id.startsWith("demo-") || (typeof cam === "string" && cam.startsWith("demo-"));
}
