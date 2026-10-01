import { useQuery } from "@tanstack/react-query";
import { Cpu, Database, HardDrive, Link2, Server } from "lucide-react";
import { get } from "../lib/api";
import { dur } from "../lib/format";
import { Badge, Card, KV, Meter, PageHeader, SkeletonRows } from "../components/ui";

export default function System() {
  const q = useQuery({ queryKey: ["system"], queryFn: () => get<any>("/api/system/status"), refetchInterval: 5000 });
  const frs = useQuery({ queryKey: ["frs-status"], queryFn: () => get<any>("/api/frs/status"), refetchInterval: 15000 });
  const ready = useQuery({ queryKey: ["ready"], queryFn: () => fetch("/api/ready").then((r) => r.json()), refetchInterval: 10000 });
  const d = q.data;
  if (!d) return <div className="mx-auto max-w-[1400px]"><PageHeader title="System" /><SkeletonRows n={8} h="h-16" /></div>;
  const gpu = d.gpu ?? {};
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="System" subtitle={`Uptime ${dur(d.uptime_s)} · refreshes every 5 s`}
        actions={<Badge color={ready.data?.ready ? "#0ca30c" : "#fab219"}>{ready.data?.ready ? "ready" : "not ready"}</Badge>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={<span className="flex items-center gap-2"><Cpu size={14} /> GPU</span>}>
          {gpu.available ? (
            <div className="flex flex-col">
              <KV k="Device" v={gpu.name} />
              <KV k="Unified memory free" v={`${gpu.free_gb} / ${gpu.total_gb} GB`} mono />
              <div className="py-1"><Meter value={gpu.total_gb - gpu.free_gb} max={gpu.total_gb} color={gpu.free_gb < 10 ? "#d03b3b" : "#3987e5"} /></div>
              <KV k="VIGIL torch allocated" v={`${gpu.torch_allocated_gb} GB`} mono />
              <KV k="Face models on GPU" v={d.face_gpu ? <Badge color="#0ca30c">CUDA</Badge> : <Badge color="#d03b3b">CPU fallback</Badge>} />
            </div>
          ) : <div className="text-sev-critical">GPU unavailable: {gpu.error}</div>}
        </Card>
        <Card title={<span className="flex items-center gap-2"><Link2 size={14} /> FRS backend (:8000, read-only)</span>}>
          <div className="flex flex-col">
            <KV k="Reachable" v={d.frs.reachable ? <Badge color="#0ca30c">yes</Badge> : <Badge color="#d03b3b">no</Badge>} />
            <KV k="Status" v={d.frs.status ?? d.frs.error ?? "—"} />
            <KV k="FRS gallery vectors" v={d.frs.faiss_vectors ?? "—"} mono />
            <KV k="Watchlist searches made" v={d.frs_match_calls} mono />
            <KV k="URL" v={<span className="font-mono text-[11px]">{frs.data?.url ?? "—"}</span>} />
          </div>
        </Card>
        <Card title={<span className="flex items-center gap-2"><Server size={14} /> Agents & LLM</span>}>
          <div className="flex flex-col">
            <KV k="Ollama" v={d.llm.reachable ? <Badge color="#0ca30c">reachable</Badge> : <Badge color="#d03b3b">down</Badge>} />
            <KV k="Reasoning" v={<span className="font-mono text-[11px]">{d.llm.text_model}</span>} />
            <KV k="Vision" v={<span className="font-mono text-[11px]">{d.llm.vision_model}</span>} />
            <KV k="Calls" v={`${d.llm_stats.text_calls} text · ${d.llm_stats.vision_calls} vision · ${d.llm_stats.errors} errors`} mono />
            <KV k="Bus messages dropped" v={d.bus_dropped} mono />
          </div>
        </Card>
      </div>

      <Card title="Model workers" className="mt-4" bodyClass="p-0">
        <table className="w-full text-left text-[12.5px]">
          <thead className="border-b border-line text-[11.5px] text-muted"><tr><th className="px-4 py-2 font-medium">Worker</th><th className="px-2 py-2 font-medium">State</th><th className="px-2 py-2 text-right font-medium">Calls</th><th className="px-2 py-2 text-right font-medium">Avg ms</th><th className="px-2 py-2 text-right font-medium">Queue</th><th className="px-2 py-2 text-right font-medium">Dropped</th><th className="px-4 py-2 font-medium">Providers</th></tr></thead>
          <tbody>
            {Object.entries(d.models as Record<string, any>).map(([k, v]) => (
              <tr key={k} className="border-b border-line last:border-0">
                <td className="px-4 py-2 font-medium">{k}</td>
                <td className="px-2 py-2">{v.ready ? <Badge color="#0ca30c">ready</Badge> : v.error ? <Badge color="#d03b3b" title={v.error}>error</Badge> : <Badge color="#fab219">loading</Badge>}</td>
                <td className="tabular px-2 py-2 text-right">{v.calls}</td>
                <td className="tabular px-2 py-2 text-right">{v.calls ? ((v.busy_s / v.calls) * 1000).toFixed(1) : "—"}</td>
                <td className="tabular px-2 py-2 text-right">{v.queue}</td>
                <td className="tabular px-2 py-2 text-right">{v.dropped}</td>
                <td className="px-4 py-2 font-mono text-[11px] text-muted">{(v.providers ?? []).join(", ") || "torch"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Camera pipelines" className="mt-4" bodyClass="p-0">
        <table className="w-full text-left text-[12.5px]">
          <thead className="border-b border-line text-[11.5px] text-muted">
            <tr><th className="px-4 py-2 font-medium">Camera</th><th className="px-2 py-2 font-medium">Status</th><th className="px-2 py-2 text-right font-medium">FPS</th><th className="px-2 py-2 text-right font-medium">Latency</th><th className="px-2 py-2 font-medium">Stage ms</th><th className="px-2 py-2 text-right font-medium">Frames / skipped</th><th className="px-4 py-2 text-right font-medium">Reconnects</th></tr>
          </thead>
          <tbody>
            {Object.entries(d.cameras as Record<string, any>).map(([k, s]) => (
              <tr key={k} className="border-b border-line last:border-0 align-top">
                <td className="px-4 py-2 font-medium">{k}{s.source_error && <div className="max-w-[260px] truncate text-[11px] text-sev-high" title={s.source_error}>{s.source_error}</div>}</td>
                <td className="px-2 py-2"><Badge color={s.status === "running" ? (s.idle ? "#6da7ec" : "#0ca30c") : "#fab219"}>{s.status}{s.idle ? " · idle" : ""}</Badge></td>
                <td className="tabular px-2 py-2 text-right">{s.fps}</td>
                <td className="tabular px-2 py-2 text-right">{s.latency_ms ?? "—"}</td>
                <td className="px-2 py-2 font-mono text-[11px] text-muted">{Object.entries(s.stage_ms ?? {}).map(([a, b]) => `${a} ${b}`).join(" · ")}</td>
                <td className="tabular px-2 py-2 text-right">{s.frames} / {s.skipped_frames ?? 0}</td>
                <td className="tabular px-4 py-2 text-right">{s.reconnects}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title={<span className="flex items-center gap-2"><Database size={14} /> Identity gallery</span>}>
          <KV k="Identities" v={d.gallery.identities} mono />
          <KV k="Face vectors" v={d.gallery.vectors} mono />
          {Object.entries(d.identity as Record<string, number>).map(([k, v]) => <KV key={k} k={k.replace(/_/g, " ")} v={v} mono />)}
        </Card>
        <Card title={<span className="flex items-center gap-2"><HardDrive size={14} /> Orchestrator</span>}>
          {Object.entries(d.orchestrator as Record<string, number>).map(([k, v]) => <KV key={k} k={k} v={v} mono />)}
        </Card>
        <Card title="Health endpoints">
          <div className="flex flex-col gap-1 font-mono text-[12px] text-ink-2">
            <span>GET /api/health — liveness</span>
            <span>GET /api/ready — {ready.data ? JSON.stringify(ready.data.checks) : "…"}</span>
            <span>GET /metrics — Prometheus (loopback or admin)</span>
          </div>
        </Card>
      </div>
    </div>
  );
}
