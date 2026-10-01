import { useEffect, useMemo, useState, type ReactNode } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import {
  AlertOctagon, AlertTriangle, ChevronDown, ChevronRight, CircleDot, Info, Loader2, ShieldAlert, X,
} from "lucide-react";
import { KIND_COLOR, KIND_LABEL, SEV_COLOR, statusLabel, titleCase } from "../lib/format";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

const SEV_ICON: Record<string, typeof Info> = {
  info: Info, low: CircleDot, medium: AlertTriangle, high: ShieldAlert, critical: AlertOctagon,
};

export function SeverityBadge({ severity, compact }: { severity: string; compact?: boolean }) {
  const c = SEV_COLOR[severity] ?? SEV_COLOR.info;
  const I = SEV_ICON[severity] ?? Info;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
      style={{ color: c, background: `${c}1f`, boxShadow: `inset 0 0 0 1px ${c}40` }}
      title={`Severity: ${severity}`}
    >
      <I size={11} />
      {!compact && severity}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  verified: "#0ca30c", confirmed: "#d03b3b", resolved: "#0ca30c", false_positive: "#898781", rejected: "#898781",
  dismissed: "#898781", needs_review: "#fab219", pending_verification: "#6da7ec", investigating: "#6da7ec",
  new: "#ec835a", open: "#c3c2b7",
};

export function StatusBadge({ status }: { status: string }) {
  const c = STATUS_TONE[status] ?? "#c3c2b7";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-line px-1.5 py-0.5 text-[11px] font-medium text-ink-2">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      {statusLabel(status)}
    </span>
  );
}

export function Badge({ children, color, title }: { children: ReactNode; color?: string; title?: string }) {
  const c = color ?? "#c3c2b7";
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium"
      style={{ color: c, background: `${c}1a`, boxShadow: `inset 0 0 0 1px ${c}33` }}
    >
      {children}
    </span>
  );
}

export function KindBadge({ kind }: { kind: string }) {
  return (
    <Badge color={KIND_COLOR[kind]}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: KIND_COLOR[kind] }} />
      {KIND_LABEL[kind] ?? titleCase(kind)}
    </Badge>
  );
}

export function WatchlistBadge({ name }: { name?: string | null }) {
  return (
    <Badge color={KIND_COLOR.watchlist} title="FRS watchlist match — a candidate for human verification, not a confirmed identity">
      <ShieldAlert size={11} /> {name ? `${name} · ` : ""}candidate — verify
    </Badge>
  );
}

export function Card({ title, actions, children, className, bodyClass }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={cx("card flex min-w-0 flex-col", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={cx("min-h-0 flex-1", bodyClass ?? "p-4")}>{children}</div>
    </section>
  );
}

export function Empty({ icon: I, title, hint }: { icon?: typeof Info; title: string; hint?: ReactNode }) {
  const Icon = I ?? Info;
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <Icon size={22} className="text-muted" />
      <div className="font-medium text-ink-2">{title}</div>
      {hint && <div className="max-w-sm text-[12px] text-muted">{hint}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className ?? "h-4 w-full")} />;
}

export function SkeletonRows({ n = 5, h = "h-9" }: { n?: number; h?: string }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: n }).map((_, i) => (
        <Skeleton key={i} className={cx(h, "w-full")} />
      ))}
    </div>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <Loader2 size={size} className="animate-spin text-muted" />;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="rounded-md border border-[#d03b3b55] bg-[#d03b3b14] px-3 py-2 text-[12px] text-[#f0a0a0]">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Modal({ open, onClose, title, children, width = 560, footer }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number; footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-6 pt-[8vh]" onMouseDown={onClose}>
      <div className="card w-full shadow-2xl" style={{ maxWidth: width }} onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="font-semibold">{title}</h2>
          <button className="text-muted hover:text-ink" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </header>
        <div className="p-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, children, width = 720 }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onMouseDown={onClose}>
      <aside
        className="flex h-full w-full flex-col border-l border-line bg-surface-1 shadow-2xl"
        style={{ maxWidth: width }}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <div className="min-w-0 flex-1 font-semibold">{title}</div>
          <button className="text-muted hover:text-ink" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

export function Collapsible({ title, children, defaultOpen = false, right }: {
  title: ReactNode; children: ReactNode; defaultOpen?: boolean; right?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button className="flex w-full items-center gap-1.5 text-left text-ink-2 hover:text-ink" onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="min-w-0 flex-1">{title}</span>
        {right}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text ?? "", { async: false }) as string), [text]);
  return <div className={cx("md", className)} dangerouslySetInnerHTML={{ __html: html }} />;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-muted">{hint}</span>}
    </label>
  );
}

export function Toggle({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2 disabled:opacity-40"
    >
      <span className={cx("relative h-[18px] w-8 rounded-full transition-colors", checked ? "bg-accent-strong" : "bg-surface-3")}>
        <span className={cx("absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white transition-all", checked ? "left-[16px]" : "left-[2px]")} />
      </span>
      {label && <span className="text-ink-2">{label}</span>}
    </button>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-1 border-b border-line" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx(
            "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium",
            value === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink-2",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[18px] font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <div className="mt-0.5 text-[12.5px] text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Img({ src, alt, className, fallback }: { src?: string | null; alt: string; className?: string; fallback?: ReactNode }) {
  const [err, setErr] = useState(false);
  useEffect(() => {
    setErr(false);
  }, [src]);
  if (!src || err) {
    return (
      <div className={cx("flex items-center justify-center bg-surface-2 text-muted", className)}>
        {fallback ?? <span className="text-[10px]">no image</span>}
      </div>
    );
  }
  return <img src={src} alt={alt} className={className} loading="lazy" onError={() => setErr(true)} />;
}

export function Meter({ value, max = 1, color, label }: { value: number; max?: number; color?: string; label?: string }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className="flex items-center gap-2" title={label}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color ?? "#3987e5" }} />
      </div>
    </div>
  );
}

export function KV({ k, v, mono }: { k: ReactNode; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-muted">{k}</span>
      <span className={cx("text-right text-ink-2", mono && "tabular font-mono text-[12px]")}>{v}</span>
    </div>
  );
}

/** Unmistakable marker for synthetic rows. Never render a demo item without it. */
export function DemoBadge({ compact, className }: { compact?: boolean; className?: string }) {
  return (
    <span
      title="Synthetic demo data — not a real event, person or camera"
      className={cx("inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider text-[#1a1a19]", className)}
      style={{ background: "repeating-linear-gradient(135deg,#fab219 0 6px,#e0a010 6px 12px)" }}
    >
      {compact ? "demo" : "DEMO · synthetic"}
    </span>
  );
}
