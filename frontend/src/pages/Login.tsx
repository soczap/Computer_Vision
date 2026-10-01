import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Lock } from "lucide-react";
import { useAuth } from "../lib/auth";
import { ErrorBox, Spinner } from "../components/ui";

export default function Login() {
  const { me, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const from = (loc.state as { from?: string } | null)?.from ?? "/";
  if (me) return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(u, p);
      nav(from, { replace: true });
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-page p-6">
      <form onSubmit={submit} className="card w-full max-w-[360px] p-7">
        <div className="mb-6 flex items-center gap-3">
          <svg width="36" height="36" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="7" fill="#222220" />
            <path d="M4 16c3.5-6 7.5-9 12-9s8.5 3 12 9c-3.5 6-7.5 9-12 9S7.5 22 4 16z" fill="none" stroke="#3987e5" strokeWidth="2.2" />
            <circle cx="16" cy="16" r="4.2" fill="#3987e5" />
          </svg>
          <div>
            <div className="text-[18px] font-bold tracking-[0.12em]">VIGIL</div>
            <div className="text-[12px] text-muted">Agentic video intelligence</div>
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="label">Username</span>
            <input className="input" autoFocus autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">Password</span>
            <input className="input" type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} />
          </label>
          <ErrorBox error={err} />
          <button className="btn btn-primary mt-2 justify-center py-2" disabled={busy || !u || !p}>
            {busy ? <Spinner /> : <Lock size={14} />} Sign in
          </button>
        </div>
        <p className="mt-5 text-[11px] leading-relaxed text-muted">
          Authorised personnel only. All actions are audited.
        </p>
      </form>
    </div>
  );
}
