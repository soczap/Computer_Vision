import { Component, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, BarChart3, Bot, Camera, Cctv, FileWarning, LayoutDashboard, ListFilter, LogOut, Search, Server,
  Settings, Users, ScanSearch, ScanFace, UserPlus, ShieldAlert, History, Gauge, Webcam, FlaskConical,
} from "lucide-react";
import { useDataMode } from "../lib/datamode";
import type { DemoMode } from "../lib/api";
import { get, type Paged, type Incident } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useStream } from "../lib/stream";
import { cx, DemoBadge as DemoBadgeInline } from "./ui";

const NAV = [
  { to: "/", label: "Command Center", icon: LayoutDashboard, end: true },
  { to: "/live", label: "Live", icon: Cctv },
  { to: "/incidents", label: "Incidents", icon: FileWarning, badge: "incidents" as const },
  { to: "/events", label: "Events", icon: ListFilter },
  { to: "/identities", label: "Identities", icon: Users },
  { to: "/search", label: "Search", icon: ScanSearch },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/webcam", label: "Local camera", icon: Webcam },
];
const FRS_NAV = [
  { to: "/frs", label: "Console", icon: ScanFace, end: true },
  { to: "/frs/identities", label: "Identities", icon: Users },
  { to: "/frs/enroll", label: "Enrol", icon: UserPlus },
  { to: "/frs/watchlist", label: "Watchlist", icon: ShieldAlert },
  { to: "/frs/searches", label: "Searches", icon: History },
  { to: "/frs/stats", label: "Stats", icon: Gauge },
];
const ADMIN_NAV = [
  { to: "/cameras", label: "Cameras", icon: Camera, role: "analyst" as const },
  { to: "/settings", label: "Settings", icon: Settings, role: "admin" as const },
  { to: "/system", label: "System", icon: Server, role: "viewer" as const },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-4 py-4">
      <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#222220" />
        <path d="M4 16c3.5-6 7.5-9 12-9s8.5 3 12 9c-3.5 6-7.5 9-12 9S7.5 22 4 16z" fill="none" stroke="#3987e5" strokeWidth="2.2" />
        <circle cx="16" cy="16" r="4.2" fill="#3987e5" />
      </svg>
      <div className="leading-tight">
        <div className="text-[14px] font-bold tracking-[0.12em] text-ink">VIGIL</div>
        <div className="text-[10.5px] text-muted">Video Analytics</div>
      </div>
    </div>
  );
}

function GlobalSearch() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement)?.tagName)) {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = q.trim();
    if (!v) return;
    if (/^P-\d+$/i.test(v)) nav(`/identities/${v.toUpperCase()}`);
    else if (v.startsWith("inc_")) nav(`/incidents/${v}`);
    else if (v.startsWith("evt_")) nav(`/events?focus=${v}`);
    else nav(`/identities?q=${encodeURIComponent(v)}`);
    setQ("");
  };
  return (
    <form onSubmit={submit} className="relative w-[340px] max-w-[40vw]">
      <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
      <input
        ref={ref}
        className="input w-full pl-8"
        placeholder="Identity (P-00012), name, inc_…, evt_…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Global search"
      />
      <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-line px-1 text-[10px] text-muted">/</kbd>
    </form>
  );
}

export default function Layout() {
  const { me, logout, can } = useAuth();
  const { connected } = useStream();
  const nav = useNavigate();
  const open = useQuery({
    queryKey: ["incidents", "open-count"],
    queryFn: () => get<Paged<Incident>>("/api/incidents?status=new,investigating,confirmed&limit=1"),
    refetchInterval: 30000,
  });
  const openCount = open.data?.total ?? 0;

  return (
    <div className="flex h-full">
      <aside className="flex w-[212px] shrink-0 flex-col border-r border-line bg-surface">
        <Logo />
        <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-2">
          {NAV.map((n) => (
            <NavItem key={n.to} {...n} count={n.badge ? openCount : 0} />
          ))}
          <div className="label mx-2 mb-1 mt-4 flex items-center gap-1.5"><ScanFace size={11} /> FRS · Face recognition</div>
          {FRS_NAV.map((n) => (
            <NavItem key={n.to} {...n} />
          ))}
          <div className="label mx-2 mb-1 mt-4">Administration</div>
          {ADMIN_NAV.filter((n) => can(n.role)).map((n) => (
            <NavItem key={n.to} {...n} />
          ))}
        </nav>
        <div className="border-t border-line p-3 text-[11px] text-muted">
          Integrates read-only with FRS :8000
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-5">
          <GlobalSearch />
          <div className="flex items-center gap-4">
            <DataModeSwitch />
            <span
              className="flex items-center gap-1.5 text-[12px] text-ink-2"
              title={connected ? "Realtime stream connected" : "Realtime stream disconnected — retrying"}
            >
              <Activity size={14} className={connected ? "text-good" : "text-sev-critical"} />
              {connected ? "Live" : "Reconnecting…"}
            </span>
            <div className="flex items-center gap-2 border-l border-line pl-4">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-3 text-[12px] font-semibold uppercase">
                {me?.username?.[0]}
              </div>
              <div className="leading-tight">
                <div className="text-[12.5px] font-medium">{me?.username}</div>
                <div className="text-[10.5px] uppercase tracking-wide text-muted">{me?.role}</div>
              </div>
              <button
                className="btn btn-ghost btn-sm ml-1"
                title="Sign out"
                onClick={async () => {
                  await logout();
                  nav("/login");
                }}
              >
                <LogOut size={14} />
              </button>
            </div>
          </div>
        </header>
        <DemoBanner />
        <main className="min-h-0 flex-1 overflow-y-auto p-5">
          <PageBoundary><Outlet /></PageBoundary>
        </main>
      </div>
    </div>
  );
}

function NavItem({ to, label, icon: I, end, count }: { to: string; label: string; icon: typeof Activity; end?: boolean; count?: number }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cx(
          "flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px]",
          isActive ? "bg-surface-3 font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
        )
      }
    >
      <I size={15} />
      <span className="flex-1">{label}</span>
      {!!count && (
        <span className="tabular rounded-full bg-sev-critical px-1.5 text-[10.5px] font-semibold text-white">{count}</span>
      )}
    </NavLink>
  );
}

class Boundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card mx-auto mt-10 max-w-[560px] p-6">
        <div className="mb-2 font-semibold">This page hit an error</div>
        <pre className="whitespace-pre-wrap font-mono text-[12px] text-muted">{this.state.error.message}</pre>
        <button className="btn mt-4" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}

function PageBoundary({ children }: { children: ReactNode }) {
  const loc = useLocation();
  return <Boundary resetKey={loc.pathname}>{children}</Boundary>;
}

const MODES: { id: DemoMode; label: string }[] = [
  { id: "exclude", label: "Real" },
  { id: "include", label: "Real + Demo" },
  { id: "only", label: "Demo only" },
];

function DataModeSwitch() {
  const { mode, setMode } = useDataMode();
  return (
    <div className="flex items-center gap-1 rounded-lg border border-line bg-surface-2 p-0.5" role="radiogroup" aria-label="Data shown">
      {MODES.map((m) => (
        <button
          key={m.id}
          role="radio"
          aria-checked={mode === m.id}
          onClick={() => setMode(m.id)}
          className={cx(
            "rounded-md px-2.5 py-1 text-[12px] font-medium",
            mode === m.id ? (m.id === "exclude" ? "bg-surface-3 text-ink" : "bg-[#fab21926] text-[#fab219]") : "text-muted hover:text-ink",
          )}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

function DemoBanner() {
  const { mode } = useDataMode();
  if (mode === "exclude") return null;
  return (
    <div className="flex items-center gap-2 border-b border-[#fab21944] px-5 py-1 text-[12px] font-medium text-[#fab219]"
      style={{ background: "repeating-linear-gradient(135deg, rgba(250,178,25,0.10) 0 10px, rgba(250,178,25,0.04) 10px 20px)" }}>
      <FlaskConical size={13} />
      {mode === "only" ? "Showing synthetic demo data only — not real events" : "Showing synthetic demo data — not real events"}
      <span className="text-muted">· items are marked</span>
      <span className="ml-1"><DemoBadgeInline /></span>
    </div>
  );
}
