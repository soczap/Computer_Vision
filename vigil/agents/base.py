"""Agent runtime: a traced ReAct loop over native tool calling.

The model decides which tools to call and in what order; nothing here encodes
an investigation sequence. Every thought, tool call, result and final answer
is persisted on an AgentRun row and streamed on the bus, so the UI can show
the reasoning chain behind each conclusion.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from vigil.agents.llm import LLMError, llm, parse_json
from vigil.agents.tools import REGISTRY, call_tool, compact
from vigil.bus import bus
from vigil.config import get_settings
from vigil.db import AgentRun, session, utcnow

log = logging.getLogger("vigil.agents")


class Trace:
    def __init__(self, agent: str, trigger: str, incident_id: str | None = None, event_id: str | None = None,
                 model: str | None = None) -> None:
        self.agent, self.trigger = agent, trigger
        self.incident_id, self.event_id, self.model = incident_id, event_id, model
        self.steps: list[dict] = []
        self.run_id: str | None = None
        self.t0 = time.time()

    async def open(self) -> "Trace":
        async with session() as db:
            r = AgentRun(agent=self.agent, trigger=self.trigger, incident_id=self.incident_id,
                         event_id=self.event_id, model=self.model)
            db.add(r)
            await db.commit()
            self.run_id = r.id
        bus.publish("agent.run", {"run_id": self.run_id, "agent": self.agent, "status": "running",
                                  "trigger": self.trigger, "incident_id": self.incident_id, "event_id": self.event_id})
        return self

    async def step(self, kind: str, **data: Any) -> None:
        st = {"i": len(self.steps), "t": round(time.time() - self.t0, 2), "kind": kind, **data}
        self.steps.append(st)
        async with session() as db:
            r = await db.get(AgentRun, self.run_id)
            if r:
                r.steps = list(self.steps)
                await db.commit()
        bus.publish("agent.step", {"run_id": self.run_id, "agent": self.agent, "incident_id": self.incident_id,
                                   "step": st})

    async def close(self, output: dict | None = None, error: str | None = None) -> None:
        async with session() as db:
            r = await db.get(AgentRun, self.run_id)
            if r:
                r.status = "failed" if error else "done"
                r.output = output or {}
                r.error = error
                r.finished_at = utcnow()
                r.steps = list(self.steps)
                await db.commit()
        bus.publish("agent.run", {"run_id": self.run_id, "agent": self.agent,
                                  "status": "failed" if error else "done", "incident_id": self.incident_id,
                                  "event_id": self.event_id, "output": output or {}, "error": error})


async def react(trace: Trace, system: str, task: str, tools: list[str], final_schema: dict | None = None,
                actor: str | None = None, max_steps: int | None = None, history: list[dict] | None = None) -> dict:
    """Run a tool-using loop until the model answers without calling tools.

    The final answer is requested as JSON matching `final_schema` (enforced with
    Ollama structured output on the closing turn).
    """
    s = get_settings()
    max_steps = max_steps or s.agent_max_steps
    actor = actor or f"agent:{trace.agent}"
    schemas = [REGISTRY[t].schema() for t in tools if t in REGISTRY]
    msgs: list[dict] = [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": task}]
    await trace.step("task", text=task[:2000], tools=tools)
    calls_made = 0
    for _ in range(max_steps):
        try:
            msg = await llm().chat(msgs, tools=schemas)
        except LLMError as e:
            await trace.step("error", text=str(e))
            raise
        content = (msg.get("content") or "").strip()
        tcs = msg.get("tool_calls") or []
        if content and tcs:
            await trace.step("thought", text=content[:2000])
        if not tcs:
            break
        msgs.append({"role": "assistant", "content": content, "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function", {})
            name, args = fn.get("name"), fn.get("arguments") or {}
            if isinstance(args, str):
                args = parse_json(args)
            await trace.step("tool_call", tool=name, args=args, action=bool(REGISTRY.get(name) and REGISTRY[name].action))
            result = await call_tool(name, args, actor, tools)
            calls_made += 1
            await trace.step("tool_result", tool=name, result=_preview(result))
            msgs.append({"role": "tool", "content": compact(result), "tool_name": name})
    # Closing turn: structured answer grounded in what was gathered.
    closing = ("Now give your final answer as JSON only, grounded strictly in the tool results above. "
               "Cite event/track/identity IDs you relied on.")
    msgs.append({"role": "user", "content": closing})
    try:
        msg = await llm().chat(msgs, fmt=final_schema or "json")
    except LLMError as e:
        await trace.step("error", text=str(e))
        raise
    out = parse_json(msg.get("content", ""))
    out["_tool_calls"] = calls_made
    await trace.step("final", output=out)
    return out


def _preview(result: Any) -> Any:
    s = json.dumps(result, default=str)
    if len(s) <= 1500:
        return result
    return {"preview": s[:1500] + "…", "size": len(s)}
