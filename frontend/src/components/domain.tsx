import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertOctagon, Bot, Brain, CheckCircle2, ClipboardList, Eye, Film, Flag, Gavel, HelpCircle, ListChecks,
  Wrench, XCircle, Zap,
} from "lucide-react";
import type { AgentRun, AgentStep, Evidence, VEvent, Verification } from "../lib/api";
import { mediaUrl } from "../lib/api";
import { ago, conf, fmtDateTime, fmtTime, titleCase, typeLabel } from "../lib/format";
import { Badge, Collapsible, DemoBadge, Img, Markdown, SeverityBadge, StatusBadge, cx } from "./ui";
import { isDemo } from "../lib/datamode";

// ─────────────────────────── evidence ───────────────────────────

export function EvidenceView({ evidence, compact }: { evidence: Evidence; compact?: boolean }) {
  const [sel, setSel] = useState<string | null>(null);
  const [mode, setMode] = useState<"clip" | "key">(evidence.clip ? "clip" : "key");
  const main = sel ?? evidence.keyframe;
  return (
    <div className="flex flex-col gap-2">
      <div className="relative overflow-hidden rounded-lg border border-line bg-black">
        {mode === "clip" && evidence.clip && !sel ? (
          <video src={mediaUrl(evidence.clip)} controls muted autoPlay loop playsInline className="aspect-video w-full object-contain" />
        ) : (
          <Img src={mediaUrl(main)} alt="Evidence keyframe" className="aspect-video w-full object-contain" />
        )}
        <div className="absolute left-2 top-2 flex gap-1">
          {evidence.clip && (
            <button className={cx("btn btn-sm", mode === "clip" && !sel && "btn-primary")} onClick={() => { setMode("clip"); setSel(null); }}>
              <Film size={12} /> Clip
            </button>
          )}
          <button className={cx("btn btn-sm", mode === "key" && !sel && "btn-primary")} onClick={() => { setMode("key"); setSel(null); }}>
            Keyframe
          </button>
        </div>
      </div>
      {!compact && evidence.frames.length > 0 && (
        <div className="grid grid-cols-6 gap-1.5">
          {evidence.frames.map((f, i) => (
            <button key={f} onClick={() => setSel(sel === f ? null : f)}
              className={cx("overflow-hidden rounded border", sel === f ? "border-accent" : "border-line hover:border-line-strong")}
              title={`Verification frame ${i + 1}`}>
              <Img src={mediaUrl(f)} alt={`frame ${i + 1}`} className="aspect-video w-full object-cover" />
            </button>
          ))}
        </div>
      )}
      {!evidence.clip && !compact && <div className="text-[11px] text-muted">Clip is written after the post-roll completes.</div>}
    </div>
  );
}

// ─────────────────────────── explanation ───────────────────────────

function fmtVal(v: unknown): ReactNode {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ");
  if (typeof v === "object") return <code className="text-[11px]">{JSON.stringify(v)}</code>;
  return String(v);
}

const isThreshold = (k: string) => /threshold|^max_|^min_|trigger|^instant|^sustain|required/.test(k);

function KVGrid({ obj, skip = [] }: { obj: Record<string, unknown>; skip?: string[] }) {
  const entries = Object.entries(obj).filter(([k, v]) => !skip.includes(k) && (typeof v !== "object" || v === null || Array.isArray(v)));
  if (!entries.length) return null;
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-x-4 gap-y-1.5">
      {entries.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <div className={cx("text-[11px]", isThreshold(k) ? "text-muted" : "text-ink-2")}>{titleCase(k)}</div>
          <div className={cx("tabular truncate font-mono text-[12px]", isThreshold(k) ? "text-muted" : "text-ink")} title={String(v)}>
            {fmtVal(v)}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Explanation({ event }: { event: VEvent }) {
  const x = event.explanation ?? {};
  const rule = x.rule as string | undefined;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {rule && <Badge color="#9085e9"><ListChecks size={11} /> rule: {rule}</Badge>}
        <span className="text-[12px] text-muted">confidence {conf(event.confidence)}</span>
      </div>
      {x.reasoning && <p className="leading-relaxed text-ink-2">{x.reasoning}</p>}
      {rule === "violence_cascade" ? (
        <ViolenceExplain x={x} />
      ) : rule === "frs_watchlist" ? (
        <WatchlistExplain x={x} />
      ) : rule === "behaviour_correlation" ? (
        <CorrelationExplain x={x} />
      ) : (
        <KVGrid obj={x} skip={["rule", "reasoning"]} />
      )}
    </div>
  );
}

function ViolenceExplain({ x }: { x: Record<string, any> }) {
  const s1 = x.stage1_pose ?? {};
  const s2 = x.stage2_videomae ?? {};
  const f = x.fusion ?? {};
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-2 md:grid-cols-3">
        <Stage n={1} title="Pose interaction" body={<KVGrid obj={s1} skip={["pair"]} />} />
        <Stage n={2} title="VideoMAE (RWF-2000)" body={<KVGrid obj={s2} />} />
        <Stage n={3} title="Fusion rule" body={<KVGrid obj={{ ...f, weights: f.weights ? `videomae ${f.weights.videomae} · pose ${f.weights.pose}` : undefined }} />} />
      </div>
      {Array.isArray(x.recent_evaluations) && x.recent_evaluations.length > 0 && (
        <div>
          <div className="label mb-1">Recent evaluations</div>
          <table className="tabular w-full text-[12px]">
            <thead className="text-muted">
              <tr>
                <th className="py-1 text-left font-normal">Time</th><th className="text-right font-normal">VideoMAE logit</th>
                <th className="text-right font-normal">VideoMAE</th><th className="text-right font-normal">Pose</th>
                <th className="text-right font-normal">Fused</th>
              </tr>
            </thead>
            <tbody>
              {x.recent_evaluations.map((e: any, i: number) => (
                <tr key={i} className="border-t border-line text-ink-2">
                  <td className="py-1">{fmtTime(e.ts)}</td><td className="text-right">{e.videomae_logit}</td>
                  <td className="text-right">{e.videomae_component}</td><td className="text-right">{e.pose_component}</td>
                  <td className="text-right font-medium text-ink">{e.fused}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stage({ n, title, body }: { n: number; title: string; body: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-3">
      <div className="mb-2 flex items-center gap-2 text-[12px] font-medium">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-surface-3 text-[11px]">{n}</span>
        {title}
      </div>
      {body}
    </div>
  );
}

function WatchlistExplain({ x }: { x: Record<string, any> }) {
  const rec = x.frs_record ?? {};
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg border border-[#e6676740] bg-[#e667670d] p-3 text-[12px] text-ink-2">
        FRS watchlist results are <b className="text-ink">candidates</b>. Verify the face against the record before acting.
      </div>
      <div className="grid gap-3 md:grid-cols-[120px_1fr]">
        {x.face && <Img src={mediaUrl(`/media/${x.face}`)} alt="Matched face" className="h-[140px] w-[120px] rounded-md object-cover" />}
        <div className="flex flex-col gap-2">
          <div className="text-[12px]"><span className="text-muted">FRS similarity </span><span className="font-mono text-ink">sim {Number(x.frs_similarity ?? 0).toFixed(2)}</span></div>
          {rec.name && <div className="text-[14px] font-semibold">{rec.name} <span className="text-[12px] font-normal text-muted">{[rec.group, rec.subgroup].filter(Boolean).join(" / ")}</span></div>}
          {rec.case && <KVGrid obj={rec.case} />}
          {Array.isArray(x.frs_top_k) && (
            <div className="text-[12px] text-muted">
              FRS top-k: {x.frs_top_k.map((t: any) => `${t.name} (sim ${Number(t.score).toFixed(2)})`).join(" · ")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CorrelationExplain({ x }: { x: Record<string, any> }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {(x.distinct_behaviours ?? []).map((b: string) => <Badge key={b}>{typeLabel(b)}</Badge>)}
      </div>
      <div className="flex flex-col gap-1 text-[12px]">
        {(x.constituent_events ?? []).map((e: any) => (
          <Link key={e.id} to={`/events?focus=${e.id}`} className="flex gap-3 text-ink-2 hover:text-ink">
            <span className="tabular text-muted">{fmtTime(e.ts)}</span>
            <span>{typeLabel(e.type)}</span>
            <span className="text-muted">{e.camera}</span>
            <span className="font-mono text-[11px] text-muted">{e.id}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────── verification ───────────────────────────

export function VerificationView({ v }: { v: Verification }) {
  if (!v || (!v.verdict && !v.human)) return <div className="text-[12px] text-muted">Not verified.</div>;
  const color = v.verdict === "confirmed" ? "#0ca30c" : v.verdict === "rejected" ? "#898781" : "#fab219";
  const I = v.verdict === "confirmed" ? CheckCircle2 : v.verdict === "rejected" ? XCircle : HelpCircle;
  return (
    <div className="flex flex-col gap-2">
      {v.verdict && (
        <div className="flex flex-wrap items-center gap-2">
          <Badge color={color}><I size={11} /> VLM: {v.verdict}</Badge>
          {v.confidence !== undefined && <span className="text-[12px] text-muted">confidence {conf(v.confidence)}</span>}
          {v.model && <span className="font-mono text-[11px] text-muted">{v.model}</span>}
        </div>
      )}
      {v.answer && <p className="leading-relaxed text-ink-2">{v.answer}</p>}
      {v.observations && v.observations.length > 0 && (
        <ul className="ml-4 list-disc text-[12px] leading-relaxed text-ink-2">
          {v.observations.map((o, i) => <li key={i}>{o}</li>)}
        </ul>
      )}
      {v.reasoning && <div className="text-[12px] text-muted">{v.reasoning}</div>}
      {v.human && (
        <div className="rounded-md border border-line bg-surface-2 px-3 py-2 text-[12px]">
          <span className="font-medium text-ink">Human review: {v.human.verdict}</span>
          <span className="text-muted"> · {v.human.by} · {fmtDateTime(v.human.at)}</span>
          {v.human.note && <div className="mt-1 text-ink-2">{v.human.note}</div>}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────── agent trace ───────────────────────────

const AGENT_LABEL: Record<string, string> = {
  investigator: "Investigation agent", threat: "Threat verification agent", identity: "Identity agent",
  behavior: "Behaviour agent", reporter: "Reporting agent", analyst: "Analyst agent",
};
export const agentLabel = (a: string) => AGENT_LABEL[a] ?? titleCase(a);

const STEP_STYLE: Record<string, { icon: typeof Bot; color: string; label: string }> = {
  task: { icon: ClipboardList, color: "#c3c2b7", label: "Task" },
  thought: { icon: Brain, color: "#9085e9", label: "Reasoning" },
  observation: { icon: Eye, color: "#6da7ec", label: "Observation" },
  tool_call: { icon: Wrench, color: "#3987e5", label: "Tool call" },
  tool_result: { icon: CheckCircle2, color: "#199e70", label: "Result" },
  decision: { icon: Gavel, color: "#fab219", label: "Decision" },
  final: { icon: Flag, color: "#0ca30c", label: "Conclusion" },
  error: { icon: AlertOctagon, color: "#d03b3b", label: "Error" },
};

function Json({ v }: { v: unknown }) {
  return (
    <pre className="max-h-[320px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-page p-2.5 font-mono text-[11px] leading-relaxed text-ink-2">
      {typeof v === "string" ? v : JSON.stringify(v, null, 2)}
    </pre>
  );
}

export function StepView({ s }: { s: AgentStep }) {
  const st = STEP_STYLE[s.kind] ?? { icon: Zap, color: "#898781", label: s.kind };
  const I = st.icon;
  const action = s.kind === "tool_call" && s.action;
  const color = action ? "#ec835a" : st.color;
  return (
    <li className="relative pb-3 pl-5">
      <span className="absolute -left-[10px] top-0 flex h-5 w-5 items-center justify-center rounded-full border border-line bg-surface-1" style={{ color }}>
        <I size={11} />
      </span>
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <span className="font-medium" style={{ color }}>{action ? "Action" : st.label}</span>
        {s.tool && <code className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-ink">{s.tool}</code>}
        {action && <Badge color="#ec835a">side effect · audited</Badge>}
        <span className="tabular ml-auto text-[11px] text-muted">+{s.t.toFixed(1)}s</span>
      </div>
      <div className="mt-1">
        {s.kind === "tool_call" && s.args && Object.keys(s.args).length > 0 && (
          <div className="font-mono text-[11.5px] text-ink-2">
            {Object.entries(s.args).map(([k, v]) => (
              <div key={k} className="break-words"><span className="text-muted">{k}=</span>{typeof v === "string" ? v : JSON.stringify(v)}</div>
            ))}
          </div>
        )}
        {s.kind === "tool_result" && (
          <Collapsible title={<span className="text-[11.5px] text-muted">show result</span>}>
            <Json v={s.result} />
          </Collapsible>
        )}
        {(s.kind === "thought" || s.kind === "observation" || s.kind === "decision" || s.kind === "error") && s.text && (
          <p className="whitespace-pre-wrap leading-relaxed text-ink-2">{s.text}</p>
        )}
        {s.kind === "task" && s.text && <p className="text-ink-2">{s.text}</p>}
        {s.kind === "task" && s.tools && (
          <div className="mt-1 text-[11px] text-muted">tools available: {s.tools.length}</div>
        )}
        {s.kind === "final" && <FinalOutput out={s.output} />}
      </div>
    </li>
  );
}

function FinalOutput({ out }: { out: any }) {
  if (!out) return null;
  if (typeof out.answer === "string") return <Markdown text={out.answer} />;
  if (typeof out.summary === "string") {
    return (
      <div className="flex flex-col gap-1">
        <p className="leading-relaxed text-ink-2">{out.summary}</p>
        <Collapsible title={<span className="text-[11.5px] text-muted">full output</span>}><Json v={out} /></Collapsible>
      </div>
    );
  }
  return <Collapsible title={<span className="text-[11.5px] text-muted">output</span>}><Json v={out} /></Collapsible>;
}

export function RunView({ run, defaultOpen }: { run: AgentRun; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const color = run.status === "done" ? "#0ca30c" : run.status === "failed" ? "#d03b3b" : "#6da7ec";
  return (
    <div className="rounded-lg border border-line bg-surface-2/40">
      <button className="flex w-full items-center gap-3 px-3 py-2.5 text-left" onClick={() => setOpen((o) => !o)}>
        <Bot size={15} className="text-accent" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{agentLabel(run.agent)}</span>
            <Badge color={color}>
              {run.status === "running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: color }} />}
              {run.status}
            </Badge>
            {run.model && <span className="font-mono text-[11px] text-muted">{run.model}</span>}
          </div>
          <div className="truncate text-[12px] text-muted">{run.trigger}</div>
        </div>
        <div className="text-right text-[11px] text-muted">
          <div>{fmtTime(run.started_at)}</div>
          <div>{run.steps?.length ?? run.step_count ?? 0} steps</div>
        </div>
      </button>
      {open && (
        <div className="border-t border-line px-3 pt-3">
          {run.error && <div className="mb-2 text-[12px] text-[#f0a0a0]">Error: {run.error}</div>}
          <ol className="ml-2.5 border-l border-line">
            {(run.steps ?? []).map((s) => <StepView key={s.i} s={s} />)}
          </ol>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────── event list item ───────────────────────────

export function EventLine({ e, onClick }: { e: VEvent; onClick?: () => void }) {
  return (
    <button onClick={onClick} className="flex w-full items-start gap-3 rounded-md px-2 py-2 text-left hover:bg-surface-2">
      <SeverityBadge severity={e.severity} compact />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5"><span className="truncate font-medium text-ink">{e.title}</span>{isDemo(e) && <DemoBadge compact />}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
          <span>{typeLabel(e.type)}</span>
          <span>·</span>
          <span>{e.camera_id}</span>
          <span>·</span>
          <span title={fmtDateTime(e.ts)}>{ago(e.ts)}</span>
        </div>
      </div>
      <StatusBadge status={e.status} />
    </button>
  );
}
