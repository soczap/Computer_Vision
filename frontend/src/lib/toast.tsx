import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { SEV_COLOR } from "./format";

export type ToastKind = "info" | "success" | "error" | "high" | "critical";
interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  body?: string;
  href?: string;
}

const Ctx = createContext<(t: Omit<Toast, "id">) => void>(() => undefined);

export function ToastProvider({ children, onNavigate }: { children: ReactNode; onNavigate?: (href: string) => void }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = ++seq.current;
    setToasts((xs) => [...xs.slice(-4), { ...t, id }]);
    const ttl = t.kind === "critical" ? 12000 : t.kind === "error" ? 8000 : 5000;
    setTimeout(() => setToasts((xs) => xs.filter((x) => x.id !== id)), ttl);
  }, []);
  const color = (k: ToastKind) =>
    k === "critical" ? SEV_COLOR.critical : k === "high" ? SEV_COLOR.high : k === "error" ? SEV_COLOR.critical : k === "success" ? "#0ca30c" : "#3987e5";
  const Icon = (k: ToastKind) =>
    k === "critical" || k === "high" ? AlertTriangle : k === "error" ? XCircle : k === "success" ? CheckCircle2 : Info;
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex w-[360px] flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => {
          const I = Icon(t.kind);
          return (
            <div
              key={t.id}
              className={`card flex gap-3 p-3 shadow-2xl shadow-black/60 ${t.href ? "cursor-pointer hover:bg-surface-2" : ""}`}
              style={{ borderLeft: `3px solid ${color(t.kind)}` }}
              onClick={() => t.href && onNavigate?.(t.href)}
            >
              <I size={18} style={{ color: color(t.kind) }} className="mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="font-medium text-ink">{t.title}</div>
                {t.body && <div className="mt-0.5 line-clamp-3 text-ink-2">{t.body}</div>}
              </div>
              <button
                className="self-start text-muted hover:text-ink"
                aria-label="Dismiss"
                onClick={(e) => {
                  e.stopPropagation();
                  setToasts((xs) => xs.filter((x) => x.id !== t.id));
                }}
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
