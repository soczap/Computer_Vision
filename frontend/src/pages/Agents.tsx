import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Cpu, Send, User } from "lucide-react";
import { get, post, type AgentRun, type AgentStep } from "../lib/api";
import { useStreamListener } from "../lib/stream";
import { useToast } from "../lib/toast";
import { ago, fmtTime } from "../lib/format";
import { Badge, Card, Collapsible, Empty, KV, Markdown, PageHeader, SkeletonRows, Spinner, Tabs } from "../components/ui";
import { RunView, StepView, agentLabel } from "../components/domain";

interface Msg {
  role: "user" | "assistant";
  content: string;
  run_id?: string;
  steps?: AgentStep[];
  status?: "running" | "done" | "failed";
}

const SUGGEST = [
  "What happened in the last hour?",
  "Who is on the FRS watchlist and where were they seen today?",
  "Summarise the open incidents and what the agents concluded.",
  "Which people appeared more than once today?",
  "Were there any fights or falls today? Were they verified?",
];

export default function Agents() {
  const [tab, setTab] = useState<"chat" | "activity">("chat");
  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader title="Agents" subtitle="Local LLM agents (Ollama) that reason over tools: perception data, identities, evidence, FRS records" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="card flex min-w-0 flex-col">
          <div className="px-4 pt-2">
            <Tabs value={tab} onChange={setTab} tabs={[{ id: "chat", label: "Ask the analyst" }, { id: "activity", label: "Agent activity" }]} />
          </div>
          {tab === "chat" ? <Chat /> : <Activity />}
        </div>
        <AgentStatus />
      </div>
    </div>
  );
}

function Chat() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const endRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const runRef = useRef<string | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs]);

  const finish = (run: AgentRun) => {
    setMsgs((xs) => xs.map((m) => (m.run_id === run.id ? {
      ...m, status: run.status === "failed" ? "failed" : "done", steps: run.steps,
      content: run.output?.answer ?? (run.error ? `The agent failed: ${run.error}` : "(no answer)"),
    } : m)));
    runRef.current = null;
    setBusy(false);
  };

  useStreamListener((m) => {
    const d = m.data ?? {};
    if (!runRef.current || d.run_id !== runRef.current) return;
    if (m.topic === "agent.step") {
      setMsgs((xs) => xs.map((x) => (x.run_id === d.run_id ? { ...x, steps: [...(x.steps ?? []), d.step] } : x)));
    }
    if (m.topic === "agent.run" && d.status !== "running") {
      get<AgentRun>(`/api/agents/runs/${d.run_id}`).then(finish);
    }
  });

  // Fallback poll in case the stream drops mid-run.
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(async () => {
      const id = runRef.current;
      if (!id) return;
      const r = await get<AgentRun>(`/api/agents/runs/${id}`).catch(() => null);
      if (r && r.status !== "running") finish(r);
      else if (r) setMsgs((xs) => xs.map((x) => (x.run_id === id && (x.steps?.length ?? 0) < r.steps.length ? { ...x, steps: r.steps } : x)));
    }, 5000);
    return () => clearInterval(t);
  }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps

  const ask = async (e?: FormEvent, q?: string) => {
    e?.preventDefault();
    const question = (q ?? text).trim();
    if (!question || busy) return;
    const history = msgs.filter((m) => m.status !== "running").map((m) => ({ role: m.role, content: m.content }));
    setText("");
    setBusy(true);
    setMsgs((xs) => [...xs, { role: "user", content: question }]);
    try {
      const r = await post<{ run_id: string }>("/api/agents/ask", { question, history });
      runRef.current = r.run_id;
      setMsgs((xs) => [...xs, { role: "assistant", content: "", run_id: r.run_id, steps: [], status: "running" }]);
    } catch (x) {
      setBusy(false);
      toast({ kind: "error", title: "Could not ask the agent", body: (x as Error).message });
    }
  };

  return (
    <div className="flex min-h-[640px] flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4" style={{ maxHeight: "calc(100vh - 260px)" }}>
        {msgs.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-10">
            <Empty icon={Bot} title="Ask about people, cameras, events or incidents" hint="The analyst agent chooses its own tools (event search, identity timelines, appearance search, FRS records, evidence inspection) and shows its reasoning." />
            <div className="flex max-w-[640px] flex-wrap justify-center gap-1.5">
              {SUGGEST.map((s) => <button key={s} className="btn btn-sm" onClick={() => ask(undefined, s)}>{s}</button>)}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {msgs.map((m, i) => (
              <div key={i} className="flex gap-3">
                <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${m.role === "user" ? "bg-surface-3" : "bg-[#3987e522] text-accent"}`}>
                  {m.role === "user" ? <User size={14} /> : <Bot size={14} />}
                </div>
                <div className="min-w-0 flex-1">
                  {m.role === "user" ? <div className="pt-1 text-[13.5px]">{m.content}</div> : (
                    <div className="flex flex-col gap-2">
                      {(m.steps?.length ?? 0) > 0 && (
                        <div className="rounded-lg border border-line bg-surface-2/50 px-3 py-2">
                          <Collapsible defaultOpen={m.status === "running"}
                            title={<span className="text-[12px] text-muted">{m.status === "running" ? "Working" : "Reasoning"} · {m.steps!.filter((s) => s.kind === "tool_call").length} tool calls</span>}
                            right={m.status === "running" ? <Spinner size={12} /> : undefined}>
                            <ol className="ml-2.5 mt-1 border-l border-line">
                              {m.steps!.filter((s) => s.kind !== "final").map((s) => <StepView key={s.i} s={s} />)}
                            </ol>
                          </Collapsible>
                        </div>
                      )}
                      {m.status === "running" ? (
                        (m.steps?.length ?? 0) === 0 && <div className="flex items-center gap-2 text-[12px] text-muted"><Spinner /> thinking…</div>
                      ) : <Markdown text={m.content} />}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>
      <form onSubmit={ask} className="flex gap-2 border-t border-line p-3">
        <input className="input flex-1" placeholder={busy ? "The agent is working…" : "Ask a question… (local LLM, answers cite IDs)"} value={text}
          onChange={(e) => setText(e.target.value)} disabled={busy} />
        <button className="btn btn-primary" disabled={busy || !text.trim()}>{busy ? <Spinner /> : <Send size={14} />} Ask</button>
      </form>
    </div>
  );
}

function Activity() {
  const qc = useQueryClient();
  const [agent, setAgent] = useState("");
  const q = useQuery({ queryKey: ["runs", agent], queryFn: () => get<AgentRun[]>(`/api/agents/runs?limit=60${agent ? `&agent=${agent}` : ""}`), refetchInterval: 15000 });
  const [open, setOpen] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["run", open], queryFn: () => get<AgentRun>(`/api/agents/runs/${open}`), enabled: !!open, refetchInterval: 4000 });
  useStreamListener((m) => {
    if (m.topic === "agent.run") qc.invalidateQueries({ queryKey: ["runs"] });
  });
  return (
    <div className="p-4">
      <div className="mb-3 flex gap-1">
        {["", "investigator", "threat", "identity", "behavior", "reporter", "analyst"].map((a) => (
          <button key={a} className={`btn btn-sm ${agent === a ? "btn-primary" : ""}`} onClick={() => setAgent(a)}>{a ? agentLabel(a).replace(" agent", "") : "All"}</button>
        ))}
      </div>
      {q.isLoading ? <SkeletonRows n={6} /> : (q.data ?? []).length === 0 ? <Empty icon={Bot} title="No agent runs yet" /> : (
        <div className="flex flex-col gap-1.5">
          {q.data!.map((r) => (
            open === r.id && detail.data ? (
              <div key={r.id} onDoubleClick={() => setOpen(null)}><RunView run={detail.data} defaultOpen /></div>
            ) : (
              <button key={r.id} onClick={() => setOpen(r.id)} className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)_auto_auto] items-center gap-3 rounded-md border border-line px-3 py-2 text-left hover:bg-surface-2">
                <span className="truncate font-medium">{agentLabel(r.agent)}</span>
                <span className="truncate text-[12px] text-muted">{r.trigger}</span>
                <Badge color={r.status === "done" ? "#0ca30c" : r.status === "failed" ? "#d03b3b" : "#6da7ec"}>{r.status}</Badge>
                <span className="w-[74px] text-right text-[11.5px] text-muted">{ago(r.started_at)}</span>
              </button>
            )
          ))}
        </div>
      )}
    </div>
  );
}

function AgentStatus() {
  const q = useQuery({ queryKey: ["agent-status"], queryFn: () => get<any>("/api/agents/status"), refetchInterval: 10000 });
  const d = q.data;
  return (
    <div className="flex flex-col gap-4">
      <Card title={<span className="flex items-center gap-2"><Cpu size={14} /> Models</span>}>
        {!d ? <SkeletonRows n={4} h="h-5" /> : (
          <div className="flex flex-col">
            <KV k="Ollama" v={<Badge color={d.llm.reachable ? "#0ca30c" : "#d03b3b"}>{d.llm.reachable ? "reachable" : "down"}</Badge>} />
            <KV k="Reasoning model" v={<span className="font-mono text-[11.5px]">{d.llm.text_model} {d.llm.text_available ? "✓" : "✗"}</span>} />
            <KV k="Vision model" v={<span className="font-mono text-[11.5px]">{d.llm.vision_model} {d.llm.vision_available ? "✓" : "✗"}</span>} />
            <KV k="LLM calls" v={`${d.llm_stats.text_calls} text · ${d.llm_stats.vision_calls} vision`} mono />
            <KV k="Avg latency" v={`${(d.llm_stats.text_s / Math.max(1, d.llm_stats.text_calls)).toFixed(1)}s text · ${(d.llm_stats.vision_s / Math.max(1, d.llm_stats.vision_calls)).toFixed(1)}s vision`} mono />
            <KV k="Errors" v={d.llm_stats.errors} mono />
            <KV k="Investigation queue" v={d.investigation_queue} mono />
          </div>
        )}
      </Card>
      <Card title="Orchestrator">
        {!d ? <SkeletonRows n={5} h="h-5" /> : (
          <div className="flex flex-col">
            {Object.entries(d.orchestrator as Record<string, number>).map(([k, v]) => <KV key={k} k={k} v={v} mono />)}
          </div>
        )}
      </Card>
      <Card title="How the agents work">
        <ul className="flex flex-col gap-2 text-[12px] leading-relaxed text-ink-2">
          <li><b className="text-ink">Threat agent</b> — waits for the evidence clip and asks the vision model a type-specific question; confirms, rejects (downgrades, never deletes) or flags for review.</li>
          <li><b className="text-ink">Identity agent</b> — on an FRS watchlist hit, pulls the case record and raises a critical candidate event with live evidence.</li>
          <li><b className="text-ink">Behaviour agent</b> — correlates minor events per person (loitering, pacing, repeat visits…) into an explained suspicious-pattern finding.</li>
          <li><b className="text-ink">Investigation agent</b> — autonomous tool-using loop on high/critical incidents; records notes, may notify or flag, every action audited.</li>
          <li><b className="text-ink">Reporting agent</b> — writes a supervisor-ready incident report.</li>
        </ul>
        <div className="mt-3 text-[11px] text-muted">Updated {fmtTime(Date.now())}</div>
      </Card>
    </div>
  );
}
