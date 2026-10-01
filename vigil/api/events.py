from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from vigil.agents.orchestrator import AnalystAgent, InvestigationAgent, ReportingAgent, orchestrator
from vigil.agents.llm import llm
from vigil.analytics.signals import DEFAULT_RULES, EVENT_TYPES, merge_rules
from vigil.bus import bus
from vigil.db import AgentRun, Event, Incident, Setting, demo_filter, get_db, involves, utcnow
from vigil.perception.engine import engine
from vigil.security import Principal, audit, current_user, require
from vigil.services import event_dict, incident_dict, run_dict

router = APIRouter(prefix="/api", tags=["events"])


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


@router.get("/event-types")
async def event_types(_: Principal = Depends(current_user)):
    return EVENT_TYPES


@router.get("/events")
async def list_events(type: str | None = None, severity: str | None = None, camera_id: str | None = None,
                      status: str | None = None, identity_id: str | None = None, since: str | None = None,
                      until: str | None = None, q: str | None = None, incident_id: str | None = None,
                      limit: int = Query(50, le=500), offset: int = 0, demo: str = "include",
                      _: Principal = Depends(current_user), db=Depends(get_db)):
    stmt = demo_filter(select(Event), Event, demo)
    if type:
        stmt = stmt.where(Event.type.in_(type.split(",")))
    if severity:
        stmt = stmt.where(Event.severity.in_(severity.split(",")))
    if camera_id:
        stmt = stmt.where(Event.camera_id == camera_id)
    if status:
        stmt = stmt.where(Event.status.in_(status.split(",")))
    if incident_id:
        stmt = stmt.where(Event.incident_id == incident_id)
    if since:
        stmt = stmt.where(Event.ts >= _dt(since))
    if until:
        stmt = stmt.where(Event.ts <= _dt(until))
    if q:
        stmt = stmt.where(Event.title.ilike(f"%{q}%") | Event.description.ilike(f"%{q}%"))
    if identity_id:
        stmt = stmt.where(involves(identity_id))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(desc(Event.ts)).limit(limit).offset(offset))).scalars().all()
    return {"total": total, "items": [event_dict(e) for e in rows]}


@router.get("/events/{event_id}")
async def get_event(event_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    e = await db.get(Event, event_id)
    if e is None:
        raise HTTPException(404, "event not found")
    runs = (await db.execute(select(AgentRun).where(AgentRun.event_id == event_id).order_by(AgentRun.started_at))).scalars().all()
    d = event_dict(e)
    d["agent_runs"] = [run_dict(r) for r in runs]
    return d


class ReviewIn(BaseModel):
    verdict: str  # confirmed | dismissed
    note: str | None = None


@router.post("/events/{event_id}/review")
async def review_event(event_id: str, body: ReviewIn, p: Principal = Depends(require("analyst")), db=Depends(get_db)):
    if body.verdict not in ("confirmed", "dismissed"):
        raise HTTPException(400, "verdict must be confirmed or dismissed")
    e = await db.get(Event, event_id)
    if e is None:
        raise HTTPException(404, "event not found")
    if e.is_demo:
        raise HTTPException(400, "demo events cannot be reviewed or escalated")
    e.status = "verified" if body.verdict == "confirmed" else "dismissed"
    e.verification = {**(e.verification or {}), "human": {"verdict": body.verdict, "by": p.username,
                                                          "note": body.note, "at": utcnow().isoformat()}}
    await db.commit()
    await audit(p.username, "event.review", event_id, verdict=body.verdict, note=body.note)
    bus.publish("event.updated", event_dict(e))
    if body.verdict == "confirmed" and not e.incident_id:
        await orchestrator().escalate(event_id)
    return event_dict(e)


# ── incidents ──
@router.get("/incidents")
async def list_incidents(status: str | None = None, severity: str | None = None, limit: int = Query(50, le=200),
                         offset: int = 0, demo: str = "include", _: Principal = Depends(current_user),
                         db=Depends(get_db)):
    stmt = demo_filter(select(Incident), Incident, demo)
    if status:
        stmt = stmt.where(Incident.status.in_(status.split(",")))
    if severity:
        stmt = stmt.where(Incident.severity.in_(severity.split(",")))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(desc(Incident.updated_at)).limit(limit).offset(offset))).scalars().all()
    counts = {}
    for iid, n in (await db.execute(select(Event.incident_id, func.count()).where(
            Event.incident_id.in_([r.id for r in rows])).group_by(Event.incident_id))).all():
        counts[iid] = n
    items = []
    for r in rows:
        d = incident_dict(r)
        d.pop("report_md")
        d["event_count"] = counts.get(r.id, 0)
        items.append(d)
    return {"total": total, "items": items}


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    i = await db.get(Incident, incident_id)
    if i is None:
        raise HTTPException(404, "incident not found")
    evs = (await db.execute(select(Event).where(Event.incident_id == incident_id).order_by(Event.ts))).scalars().all()
    runs = (await db.execute(select(AgentRun).where(AgentRun.incident_id == incident_id).order_by(AgentRun.started_at))).scalars().all()
    ev_ids = [e.id for e in evs]
    vruns = (await db.execute(select(AgentRun).where(AgentRun.event_id.in_(ev_ids)))).scalars().all() if ev_ids else []
    d = incident_dict(i)
    d["events"] = [event_dict(e) for e in evs]
    d["agent_runs"] = [run_dict(r) for r in sorted([*runs, *vruns], key=lambda r: r.started_at)]
    return d


class IncidentPatch(BaseModel):
    status: str | None = None
    severity: str | None = None
    assigned_to: str | None = None
    note: str | None = None


@router.patch("/incidents/{incident_id}")
async def patch_incident(incident_id: str, body: IncidentPatch, p: Principal = Depends(require("analyst")),
                         db=Depends(get_db)):
    i = await db.get(Incident, incident_id)
    if i is None:
        raise HTTPException(404, "incident not found")
    changes = {}
    if body.status and body.status in ("new", "investigating", "confirmed", "false_positive", "resolved"):
        changes["status"] = [i.status, body.status]
        i.status = body.status
    if body.severity and body.severity in ("low", "medium", "high", "critical"):
        changes["severity"] = [i.severity, body.severity]
        i.severity = body.severity
    if body.assigned_to is not None:
        i.assigned_to = body.assigned_to or None
        changes["assigned_to"] = i.assigned_to
    notes = list(i.notes or [])
    if body.note or changes:
        notes.append({"ts": utcnow().isoformat(), "by": p.username, "text": body.note or "Updated", "changes": changes})
    i.notes = notes
    i.updated_at = utcnow()
    await db.commit()
    await audit(p.username, "incident.update", incident_id, changes=changes, note=body.note)
    d = incident_dict(i)
    bus.publish("incident.updated", d)
    return d


@router.post("/incidents/{incident_id}/investigate")
async def investigate(incident_id: str, p: Principal = Depends(require("analyst")), db=Depends(get_db)):
    i = await db.get(Incident, incident_id)
    if i is None or i.is_demo:
        raise HTTPException(400, "demo incidents are not investigated (no agent reasons about synthetic data)")
    asyncio.create_task(InvestigationAgent(orchestrator()).run(incident_id, requested_by=p.username))
    await audit(p.username, "incident.investigate", incident_id)
    return {"ok": True, "queued": True}


@router.post("/incidents/{incident_id}/report")
async def make_report(incident_id: str, p: Principal = Depends(require("analyst"))):
    asyncio.create_task(ReportingAgent().generate(incident_id))
    await audit(p.username, "incident.report", incident_id)
    return {"ok": True, "queued": True}


@router.get("/incidents/{incident_id}/report.md", response_class=PlainTextResponse)
async def download_report(incident_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    i = await db.get(Incident, incident_id)
    if i is None or not i.report_md:
        raise HTTPException(404, "no report yet")
    return PlainTextResponse(i.report_md, headers={"Content-Disposition": f'attachment; filename="{incident_id}.md"'})


# ── agents ──
@router.get("/agents/runs")
async def list_runs(agent: str | None = None, limit: int = Query(50, le=200), _: Principal = Depends(current_user),
                    db=Depends(get_db)):
    stmt = select(AgentRun).order_by(desc(AgentRun.started_at)).limit(limit)
    if agent:
        stmt = stmt.where(AgentRun.agent == agent)
    out = []
    for r in (await db.execute(stmt)).scalars():
        d = run_dict(r)
        d["step_count"] = len(d.pop("steps"))
        out.append(d)
    return out


@router.get("/agents/runs/{run_id}")
async def get_run(run_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    r = await db.get(AgentRun, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return run_dict(r)


class AskIn(BaseModel):
    question: str
    history: list[dict] = []


@router.post("/agents/ask")
async def ask(body: AskIn, p: Principal = Depends(current_user)):
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    history = [{"role": m.get("role"), "content": str(m.get("content", ""))[:4000]} for m in body.history[-8:]
               if m.get("role") in ("user", "assistant")]
    agent = AnalystAgent()
    tr = await agent.start(body.question, p.username)
    asyncio.create_task(agent.run(tr, body.question, p.username, history))
    return {"run_id": tr.run_id}


@router.get("/agents/status")
async def agents_status(_: Principal = Depends(current_user)):
    o = orchestrator()
    return {"llm": await llm().health(), "llm_stats": llm().stats, "orchestrator": o.stats,
            "investigation_queue": o.investigations.qsize()}


# ── rules ──
@router.get("/settings/rules")
async def get_rules(_: Principal = Depends(current_user), db=Depends(get_db)):
    row = await db.get(Setting, "rules")
    return {"defaults": DEFAULT_RULES, "overrides": row.value if row else {},
            "effective": merge_rules(row.value if row else {})}


@router.put("/settings/rules")
async def put_rules(body: dict, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    clean = {k: v for k, v in body.items() if k in DEFAULT_RULES and isinstance(v, dict)}
    row = await db.get(Setting, "rules")
    if row is None:
        db.add(Setting(key="rules", value=clean))
    else:
        row.value = clean
    await db.commit()
    await audit(p.username, "rules.update", None, rules=list(clean))
    await engine.reload_all()
    return {"effective": merge_rules(clean)}
