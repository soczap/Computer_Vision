import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, KeyRound, RotateCcw, Save, Trash2, UserPlus } from "lucide-react";
import { del } from "../lib/api";
import { DemoBadge, Modal } from "../components/ui";
import { useDataMode } from "../lib/datamode";
import { get, patch, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { fmtDateTime, SEVERITIES, titleCase, typeLabel } from "../lib/format";
import { Badge, Card, ErrorBox, Field, PageHeader, SkeletonRows, Spinner, Tabs, Toggle } from "../components/ui";

type Rules = Record<string, Record<string, any>>;

export default function Settings() {
  const [tab, setTab] = useState<"rules" | "users" | "account" | "audit" | "demo">("rules");
  return (
    <div className="mx-auto max-w-[1300px]">
      <PageHeader title="Settings" subtitle="Detection rules, users and audit trail" />
      <div className="mb-4">
        <Tabs value={tab} onChange={setTab} tabs={[
          { id: "rules", label: "Detection rules" }, { id: "users", label: "Users" }, { id: "account", label: "My account" }, { id: "audit", label: "Audit log" }, { id: "demo", label: "Demo data" },
        ]} />
      </div>
      {tab === "rules" && <RulesEditor />}
      {tab === "users" && <UsersAdmin />}
      {tab === "account" && <Account />}
      {tab === "audit" && <Audit />}
      {tab === "demo" && <DemoData />}
    </div>
  );
}

const HINTS: Record<string, string> = {
  dwell_s: "seconds", max_radius: "frame-normalised radius", speed_bh_s: "body-heights / s", min_duration_s: "seconds",
  torso_deg: "degrees from vertical", min_down_s: "seconds", min_people: "people", radius_bh: "body-heights",
  unattended_s: "seconds", owner_radius_bh: "body-heights", min_hits: "detections in 3 s", reversals: "direction changes",
  window_s: "seconds", min_samples: "foot-point samples", percentile: "% of traffic", min_visits: "sightings",
  window_min: "minutes", trigger: "instant fused score", sustain: "fused score, 2 consecutive", open: "HH:MM", close: "HH:MM",
};

function RulesEditor() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["rules"], queryFn: () => get<{ defaults: Rules; overrides: Rules; effective: Rules }>("/api/settings/rules") });
  const [eff, setEff] = useState<Rules | null>(null);
  useEffect(() => { if (q.data) setEff(structuredClone(q.data.effective)); }, [q.data]);
  const save = useMutation({
    mutationFn: (overrides: Rules) => put("/api/settings/rules", overrides),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); toast({ kind: "success", title: "Rules saved", body: "Cameras restarted with the new rules." }); },
    onError: (e) => toast({ kind: "error", title: "Save failed", body: (e as Error).message }),
  });
  if (!q.data || !eff) return <SkeletonRows n={8} h="h-16" />;
  const defs = q.data.defaults;
  const diff = (): Rules => {
    const out: Rules = {};
    for (const [rule, vals] of Object.entries(eff)) {
      for (const [k, v] of Object.entries(vals)) {
        if (JSON.stringify(defs[rule]?.[k]) !== JSON.stringify(v)) (out[rule] ??= {})[k] = v;
      }
    }
    return out;
  };
  const changed = JSON.stringify(diff()) !== JSON.stringify(q.data.overrides);
  return (
    <div>
      <div className="sticky top-0 z-10 mb-3 flex items-center justify-between gap-3 bg-page py-2">
        <div className="text-[12px] text-muted">Values differing from the built-in default are marked. Saving restarts camera analysis (tracks restart; identities persist).</div>
        <div className="flex gap-2">
          <button className="btn" onClick={() => setEff(structuredClone(q.data!.effective))} disabled={!changed}>Discard</button>
          <button className="btn btn-primary" disabled={!changed || save.isPending} onClick={() => save.mutate(diff())}>{save.isPending ? <Spinner /> : <Save size={14} />} Save rules</button>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {Object.entries(eff).map(([rule, vals]) => (
          <Card key={rule} title={
            <span className="flex items-center gap-2">
              {typeLabel(rule === "watchlist" ? "watchlist_match" : rule === "weapon" ? "weapon" : rule)}
            </span>}
            actions={"enabled" in vals && <Toggle checked={!!vals.enabled} onChange={(v) => setEff({ ...eff, [rule]: { ...vals, enabled: v } })} />}>
            <div className="flex flex-col gap-2.5">
              {Object.entries(vals).filter(([k]) => k !== "enabled").map(([k, v]) => {
                const isDefault = JSON.stringify(defs[rule]?.[k]) === JSON.stringify(v);
                const setV = (nv: any) => setEff({ ...eff, [rule]: { ...vals, [k]: nv } });
                return (
                  <div key={k} className="grid grid-cols-[1fr_130px_22px] items-center gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-[12.5px] text-ink-2">{titleCase(k.replace(/_(bh_s|bh|s|min|deg)$/, ""))}</div>
                      {HINTS[k] && <div className="text-[10.5px] text-muted">{HINTS[k]}</div>}
                    </div>
                    {k === "severity" ? (
                      <select className="input" value={v} onChange={(e) => setV(e.target.value)}>{SEVERITIES.map((s) => <option key={s}>{s}</option>)}</select>
                    ) : typeof v === "number" ? (
                      <input className="input tabular" type="number" step="any" value={v} onChange={(e) => setV(e.target.value === "" ? 0 : Number(e.target.value))} />
                    ) : typeof v === "boolean" ? (
                      <Toggle checked={v} onChange={setV} />
                    ) : (
                      <input className="input" value={String(v)} onChange={(e) => setV(e.target.value)} />
                    )}
                    {isDefault ? <span /> : (
                      <button className="text-sev-medium" title={`Reset to default (${defs[rule]?.[k]})`} onClick={() => setV(defs[rule]?.[k])}><RotateCcw size={13} /></button>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

interface U { id: string; username: string; role: string; disabled: boolean; created_at: string; last_login: string | null }

function UsersAdmin() {
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["users"], queryFn: () => get<U[]>("/api/users") });
  const [f, setF] = useState({ username: "", password: "", role: "viewer" });
  const create = useMutation({
    mutationFn: () => post("/api/users", f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); setF({ username: "", password: "", role: "viewer" }); toast({ kind: "success", title: "User created" }); },
  });
  const upd = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => patch(`/api/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => toast({ kind: "error", title: "Update failed", body: (e as Error).message }),
  });
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Card bodyClass="p-0">
        {q.isLoading ? <div className="p-4"><SkeletonRows /></div> : (
          <table className="w-full text-left">
            <thead className="border-b border-line text-[11.5px] text-muted"><tr><th className="px-4 py-2 font-medium">User</th><th className="px-2 py-2 font-medium">Role</th><th className="px-2 py-2 font-medium">Last login</th><th className="px-4 py-2 text-right font-medium">Active</th></tr></thead>
            <tbody>
              {(q.data ?? []).map((u) => (
                <tr key={u.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 font-medium">{u.username}{u.id === me?.id && <span className="ml-2 text-[11px] text-muted">(you)</span>}</td>
                  <td className="px-2 py-2.5">
                    <select className="input" value={u.role} disabled={u.id === me?.id} onChange={(e) => upd.mutate({ id: u.id, body: { role: e.target.value } })}>
                      <option value="viewer">viewer</option><option value="analyst">analyst</option><option value="admin">admin</option>
                    </select>
                  </td>
                  <td className="px-2 py-2.5 text-[12px] text-muted">{u.last_login ? fmtDateTime(u.last_login) : "never"}</td>
                  <td className="px-4 py-2.5 text-right"><Toggle checked={!u.disabled} disabled={u.id === me?.id} onChange={(v) => upd.mutate({ id: u.id, body: { disabled: !v } })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Add user">
        <div className="flex flex-col gap-3">
          <Field label="Username"><input className="input" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" /></Field>
          <Field label="Password" hint="At least 8 characters"><input className="input" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></Field>
          <Field label="Role">
            <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="viewer">viewer — read & watch</option><option value="analyst">analyst — + review, investigate, enrol</option><option value="admin">admin — + cameras, rules, users</option>
            </select>
          </Field>
          <ErrorBox error={create.error} />
          <button className="btn btn-primary justify-center" disabled={f.username.length < 2 || f.password.length < 8 || create.isPending} onClick={() => create.mutate()}><UserPlus size={14} /> Create</button>
        </div>
      </Card>
    </div>
  );
}

function Account() {
  const toast = useToast();
  const { me } = useAuth();
  const [f, setF] = useState({ current: "", new: "", confirm: "" });
  const m = useMutation({
    mutationFn: () => post("/api/auth/password", { current: f.current, new: f.new }),
    onSuccess: () => { setF({ current: "", new: "", confirm: "" }); toast({ kind: "success", title: "Password changed" }); },
  });
  return (
    <Card title="Change password" className="max-w-[420px]">
      <div className="flex flex-col gap-3">
        <div className="text-[12px] text-muted">Signed in as <b className="text-ink">{me?.username}</b> <Badge>{me?.role}</Badge></div>
        <Field label="Current password"><input className="input" type="password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} autoComplete="current-password" /></Field>
        <Field label="New password"><input className="input" type="password" value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} autoComplete="new-password" /></Field>
        <Field label="Confirm new password"><input className="input" type="password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} autoComplete="new-password" /></Field>
        {f.confirm && f.confirm !== f.new && <div className="text-[12px] text-sev-high">Passwords do not match</div>}
        <ErrorBox error={m.error} />
        <button className="btn btn-primary justify-center" disabled={!f.current || f.new.length < 8 || f.new !== f.confirm || m.isPending} onClick={() => m.mutate()}><KeyRound size={14} /> Change password</button>
      </div>
    </Card>
  );
}

function Audit() {
  const q = useQuery({ queryKey: ["audit"], queryFn: () => get<{ ts: string; actor: string; action: string; target: string | null; details: Record<string, unknown> }[]>("/api/audit?limit=300"), refetchInterval: 20000 });
  return (
    <Card bodyClass="p-0">
      {q.isLoading ? <div className="p-4"><SkeletonRows n={8} /></div> : (
        <table className="w-full text-left text-[12px]">
          <thead className="border-b border-line text-[11.5px] text-muted"><tr><th className="px-4 py-2 font-medium">Time</th><th className="px-2 py-2 font-medium">Actor</th><th className="px-2 py-2 font-medium">Action</th><th className="px-2 py-2 font-medium">Target</th><th className="px-4 py-2 font-medium">Details</th></tr></thead>
          <tbody>
            {(q.data ?? []).map((a, i) => (
              <tr key={i} className="border-b border-line last:border-0 align-top">
                <td className="tabular whitespace-nowrap px-4 py-1.5 text-ink-2">{fmtDateTime(a.ts)}</td>
                <td className="px-2 py-1.5">{a.actor.startsWith("agent") ? <Badge color="#3987e5">{a.actor}</Badge> : a.actor}</td>
                <td className="px-2 py-1.5 font-mono">{a.action}</td>
                <td className="px-2 py-1.5 font-mono text-muted">{a.target}</td>
                <td className="max-w-[480px] truncate px-4 py-1.5 font-mono text-[11px] text-muted" title={JSON.stringify(a.details)}>{JSON.stringify(a.details)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function DemoData() {
  const qc = useQueryClient();
  const toast = useToast();
  const { mode, setMode } = useDataMode();
  const [hours, setHours] = useState(24);
  const [confirm, setConfirm] = useState<"gen" | "clear" | null>(null);
  const q = useQuery({ queryKey: ["demo-data"], queryFn: () => get<Record<string, number | boolean>>("/api/demo/data") });
  const done = (title: string) => { qc.resetQueries(); setConfirm(null); toast({ kind: "success", title }); };
  const gen = useMutation({ mutationFn: () => post(`/api/demo/data?hours=${hours}`), onSuccess: () => done("Demo data regenerated") });
  const clear = useMutation({ mutationFn: () => del("/api/demo/data"), onSuccess: () => done("Demo data removed") });
  const d = q.data;
  return (
    <div className="grid max-w-[980px] gap-4 md:grid-cols-2">
      <Card title={<span className="flex items-center gap-2"><FlaskConical size={14} /> Synthetic demo data <DemoBadge compact /></span>}>
        <p className="mb-3 text-[12.5px] leading-relaxed text-ink-2">Demo cameras, identities (D-xxxx), tracks, events and incidents exist so dashboards can be shown without live footage. Every demo row is flagged, watermarked and badged; it never streams and agents are not run on it.</p>
        {!d ? <SkeletonRows n={5} h="h-5" /> : (
          <div className="grid grid-cols-5 gap-2 text-center">
            {["cameras", "identities", "tracks", "events", "incidents"].map((k) => (
              <div key={k} className="rounded-md border border-line bg-surface-2 py-2">
                <div className="tabular text-[18px] font-semibold">{String(d[k] ?? 0)}</div>
                <div className="text-[11px] text-muted">{k}</div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-4 flex items-center gap-2 text-[12px] text-muted">
          Showing now: <b className="text-ink">{mode === "exclude" ? "Real only" : mode === "only" ? "Demo only" : "Real + Demo"}</b>
          {mode !== "exclude" && <button className="btn btn-sm ml-auto" onClick={() => setMode("exclude")}>Hide demo data</button>}
        </div>
      </Card>
      <Card title="Manage">
        <div className="flex flex-col gap-4">
          <div>
            <div className="mb-1.5 font-medium">Generate</div>
            <div className="mb-2 text-[12px] text-muted">Replaces all existing demo rows with a fresh synthetic history.</div>
            <div className="flex items-center gap-2">
              <select className="input" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                {[6, 12, 24, 48, 72, 168].map((h) => <option key={h} value={h}>last {h} h</option>)}
              </select>
              <button className="btn btn-primary" onClick={() => setConfirm("gen")}><FlaskConical size={14} /> Generate</button>
            </div>
          </div>
          <div className="border-t border-line pt-4">
            <div className="mb-1.5 font-medium">Clear</div>
            <div className="mb-2 text-[12px] text-muted">Deletes every demo camera, identity, track, event, incident and demo image. Real data is untouched.</div>
            <button className="btn btn-danger" disabled={!d?.present} onClick={() => setConfirm("clear")}><Trash2 size={14} /> Clear demo data</button>
          </div>
        </div>
      </Card>
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm === "gen" ? "Regenerate demo data?" : "Remove all demo data?"}
        footer={<>
          <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
          <button className={confirm === "gen" ? "btn btn-primary" : "btn btn-danger"} disabled={gen.isPending || clear.isPending}
            onClick={() => (confirm === "gen" ? gen.mutate() : clear.mutate())}>{gen.isPending || clear.isPending ? <Spinner /> : confirm === "gen" ? "Regenerate" : "Remove"}</button>
        </>}>
        <p className="text-[12.5px] leading-relaxed text-ink-2">{confirm === "gen" ? `Existing demo rows are replaced with ${hours} h of synthetic history. Real cameras, identities and events are not affected.` : "All synthetic rows and demo images are deleted. Real data is not affected."}</p>
        <ErrorBox error={gen.error ?? clear.error} />
      </Modal>
    </div>
  );
}
