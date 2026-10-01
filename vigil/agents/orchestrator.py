"""Orchestrator and specialised agents.

perception/analytics --signal--> Orchestrator
   ├─ persist event (dedupe) ── verify? ──> ThreatAgent (VLM on evidence) ──┐
   │                                                                        ▼
   ├─ watchlist hit ──> IdentityAgent (FRS record, evidence) ──> escalate(event)
   ├─ track closed ──> BehaviorAgent (repeat visits, cross-event correlation)  │
   │                                                                        ▼
   └─ escalate: attach to / open an incident ──> InvestigationAgent (LLM, tools, actions)
                                                  └─> ReportingAgent (on demand / critical)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from sqlalchemy import desc, select

from vigil.agents.base import Trace, react
from vigil.agents.llm import LLMError, llm
from vigil.agents.tools import ACTION_TOOLS, READ_TOOLS, call_tool
from vigil.analytics.identity import identities
from vigil.analytics.signals import EVENT_TYPES, Signal, merge_rules
from vigil.bus import bus
from vigil.config import SEVERITY_ORDER, get_settings
from vigil.db import Event, Incident, Setting, Track, new_id, session, utcnow
from vigil.services import event_dict, incident_dict

log = logging.getLogger("vigil.orchestrator")
EVENT_TYPES.setdefault("suspicious_pattern", "Correlated suspicious behaviour")

VERIFY_QUESTIONS = {
    "violence": ("These time-ordered CCTV frames were flagged as a possible physical fight. Is anyone hitting, "
                 "kicking, pushing, grappling or assaulting another person? verdict=confirmed only if physical "
                 "aggression is visible; rejected if the interaction is clearly non-violent (talking, hugging, "
                 "walking, playing)."),
    "fall": ("These frames were flagged because a person appears to be down. Is a person lying or sitting on the "
             "ground? Did they fall, or are they resting deliberately? verdict=confirmed if someone is down/fallen."),
    "weapon": ("These frames were flagged for a possible weapon. Is any person holding a knife, blade, bat, stick, "
               "gun or other weapon? verdict=confirmed only if a weapon is clearly visible in a hand."),
    "abandoned_object": ("These frames were flagged for an unattended object. Is there a bag, suitcase or package "
                         "left on the ground with nobody attending it? verdict=confirmed if it is unattended."),
}


def sev_ge(a: str, b: str) -> bool:
    return SEVERITY_ORDER.get(a, 0) >= SEVERITY_ORDER.get(b, 0)


class Orchestrator:
    def __init__(self) -> None:
        self.s = get_settings()
        self.evidence_waiters: dict[str, asyncio.Future] = {}
        self.investigations: asyncio.Queue[str] = asyncio.Queue()
        self._queued: set[str] = set()
        self._recent: dict[tuple, float] = {}
        self._repeat_fired: dict[str, float] = {}
        self._pattern_fired: dict[str, float] = {}
        self._tasks: list[asyncio.Task] = []
        self.stats = {"signals": 0, "events": 0, "deduped": 0, "incidents": 0, "verifications": 0,
                      "investigations": 0, "reports": 0}

    async def recover(self) -> dict:
        """After a restart: close interrupted runs, re-verify recent pending events, resume investigations."""
        from vigil.db import AgentRun
        out = {"runs_closed": 0, "reverify": 0, "reinvestigate": 0}
        async with session() as db:
            for r in (await db.execute(select(AgentRun).where(AgentRun.status == "running"))).scalars():
                r.status, r.error, r.finished_at = "failed", "interrupted by service restart", utcnow()
                out["runs_closed"] += 1
            pend = (await db.execute(select(Event).where(Event.status == "pending_verification"))).scalars().all()
            recent = [e.id for e in pend if e.ts >= utcnow() - timedelta(hours=1)]
            for e in pend:
                if e.id not in recent:
                    e.status = "needs_review"
            incs = (await db.execute(select(Incident).where(Incident.status == "investigating",
                                                            Incident.is_demo.is_(False)))).scalars().all()
            resume = [i.id for i in incs if not (i.conclusion or {}).get("summary")]
            await db.commit()
        for eid in recent:
            asyncio.create_task(ThreatAgent(self).verify(eid))
        for iid in resume:
            self.enqueue_investigation(iid)
        out["reverify"], out["reinvestigate"] = len(recent), len(resume)
        log.info("orchestrator recovery: %s", out)
        return out

    async def start(self) -> None:
        await self.recover()
        q = bus.subscribe("signal", "evidence.ready", "identity.watchlist", "track.closed", maxsize=5000)
        self._tasks.append(asyncio.create_task(self._pump(q), name="orchestrator"))
        self._tasks.append(asyncio.create_task(self._investigator(), name="investigator"))
        self._tasks.append(asyncio.create_task(self._maintenance(), name="maintenance"))

    async def _maintenance(self) -> None:
        while True:
            try:
                await self.sweep()
            except Exception:  # noqa: BLE001
                log.exception("retention sweep failed")
            await asyncio.sleep(3600)

    async def sweep(self) -> dict:
        """Retention: drop evidence files of old, unlinked, low-value events and old track crops."""
        import shutil
        media = self.s.media_dir
        cutoff = utcnow() - timedelta(days=self.s.retention_days)
        out = {"evidence_dirs": 0, "track_crops": 0}
        async with session() as db:
            evs = (await db.execute(select(Event).where(Event.ts < cutoff, Event.incident_id.is_(None)))).scalars().all()
            for e in evs:
                if e.status in ("rejected", "dismissed") or e.severity in ("info", "low") or e.status == "open":
                    d = media / "evidence" / e.id
                    if d.exists():
                        shutil.rmtree(d, ignore_errors=True)
                        out["evidence_dirs"] += 1
                    e.evidence = {"expired": True}
            trs = (await db.execute(select(Track).where(Track.started_at < cutoff))).scalars().all()
            for t in trs:
                for rel in (t.best_person_path, t.best_face_path):
                    if rel and rel.startswith(("persons/", "faces/tracks/")) and (media / rel).exists():
                        (media / rel).unlink()
                        out["track_crops"] += 1
                t.best_person_path = t.best_face_path = None
            await db.commit()
        if any(out.values()):
            log.info("retention sweep: %s", out)
        return out

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    async def _pump(self, q: asyncio.Queue) -> None:
        while True:
            msg = await q.get()
            try:
                topic, data = msg["topic"], msg["data"]
                if topic == "signal":
                    await self.on_signal(data)
                elif topic == "evidence.ready":
                    await self.on_evidence(data)
                elif topic == "identity.watchlist":
                    asyncio.create_task(IdentityAgent(self).handle(data))
                elif topic == "track.closed":
                    asyncio.create_task(BehaviorAgent(self).on_track_closed(data))
            except Exception:  # noqa: BLE001
                log.exception("orchestrator failed on %s", msg.get("topic"))

    # ── signals -> events ──
    async def on_signal(self, sig: Signal) -> Event | None:
        self.stats["signals"] += 1
        key = (sig.type, sig.camera_id, tuple(sorted(sig.identity_ids or sig.track_uids)))
        now = time.time()
        if now - self._recent.get(key, 0) < self.s.event_cooldown_s and sig.type not in ("watchlist_match",):
            self.stats["deduped"] += 1
            return None
        self._recent[key] = now
        from datetime import datetime, timezone
        async with session() as db:
            ev = Event(id=sig.event_id or new_id("evt"), ts=datetime.fromtimestamp(sig.ts, timezone.utc),
                       camera_id=sig.camera_id, type=sig.type, severity=sig.severity, confidence=sig.confidence,
                       title=sig.title, description=sig.description, track_ids=sig.track_uids,
                       identity_ids=sig.identity_ids, explanation=sig.explanation, evidence=sig.evidence,
                       status="pending_verification" if sig.verify and self.s.agents_enabled else "open")
            db.add(ev)
            await db.commit()
        self.stats["events"] += 1
        bus.publish("event.created", event_dict(ev))
        if sig.verify and self.s.agents_enabled:
            asyncio.create_task(ThreatAgent(self).verify(ev.id))
        else:
            await self.escalate(ev.id)
        return ev

    async def on_evidence(self, data: dict) -> None:
        eid = data["event_id"]
        async with session() as db:
            ev = await db.get(Event, eid)
            if ev is not None:
                evd = dict(ev.evidence or {})
                if data.get("clip"):
                    evd["clip"] = data["clip"]
                if data.get("frames"):
                    evd["frames"] = data["frames"]
                ev.evidence = evd
                await db.commit()
                bus.publish("event.updated", event_dict(ev))
        w = self.evidence_waiters.pop(eid, None)
        if w and not w.done():
            w.set_result(data)

    async def wait_evidence(self, event_id: str, timeout: float = 25.0) -> None:
        async with session() as db:
            ev = await db.get(Event, event_id)
            if ev is not None and (ev.evidence or {}).get("frames"):
                return
        fut = asyncio.get_running_loop().create_future()
        self.evidence_waiters[event_id] = fut
        try:
            await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.evidence_waiters.pop(event_id, None)

    # ── events -> incidents ──
    async def escalate(self, event_id: str) -> str | None:
        async with session() as db:
            ev = await db.get(Event, event_id)
            if ev is None or ev.status in ("rejected", "dismissed") or not sev_ge(ev.severity, "medium"):
                return None
            window = utcnow() - timedelta(minutes=10)
            opens = (await db.execute(select(Incident).where(
                Incident.status.in_(["new", "investigating", "confirmed"]), Incident.updated_at >= window,
                Incident.is_demo.is_(False))
                .order_by(desc(Incident.updated_at)))).scalars().all()
            ids = set(ev.identity_ids or [])
            inc = next((i for i in opens if (ids and ids & set(i.identity_ids or [])) or
                        (i.camera_id == ev.camera_id and i.type == ev.type)), None)
            created = inc is None
            if created:
                inc = Incident(title=ev.title, type=ev.type, severity=ev.severity, camera_id=ev.camera_id,
                               identity_ids=list(ids), summary=ev.description, confidence=ev.confidence,
                               notes=[{"ts": utcnow().isoformat(), "by": "orchestrator",
                                       "text": f"Opened from {ev.type} event {ev.id}."}])
                db.add(inc)
                await db.flush()
                self.stats["incidents"] += 1
            else:
                if SEVERITY_ORDER[ev.severity] > SEVERITY_ORDER[inc.severity]:
                    inc.severity = ev.severity
                inc.identity_ids = sorted(set(inc.identity_ids or []) | ids)
                inc.notes = (inc.notes or []) + [{"ts": utcnow().isoformat(), "by": "orchestrator",
                                                  "text": f"Correlated {ev.type} event {ev.id} into this incident."}]
            inc.updated_at = utcnow()
            ev.incident_id = inc.id
            await db.commit()
            d = incident_dict(inc)
            sev = inc.severity
        bus.publish("incident.created" if created else "incident.updated", d)
        bus.publish("event.updated", {"id": event_id, "incident_id": d["id"]})
        if self.s.agents_enabled and sev_ge(sev, self.s.auto_investigate_min_severity):
            self.enqueue_investigation(d["id"])
        return d["id"]

    def enqueue_investigation(self, incident_id: str) -> bool:
        if incident_id in self._queued:
            return False
        self._queued.add(incident_id)
        self.investigations.put_nowait(incident_id)
        return True

    async def _investigator(self) -> None:
        while True:
            iid = await self.investigations.get()
            # Let correlated events settle into the incident before reasoning about it.
            await asyncio.sleep(3)
            self._queued.discard(iid)
            try:
                await InvestigationAgent(self).run(iid)
                self.stats["investigations"] += 1
            except Exception:  # noqa: BLE001
                log.exception("investigation of %s failed", iid)


# ─────────────────────────────── agents ────────────────────────────────


class ThreatAgent:
    """Verifies flagged events visually before they escalate. Never deletes: it re-grades."""

    def __init__(self, orch: Orchestrator) -> None:
        self.o = orch

    async def verify(self, event_id: str) -> None:
        async with session() as db:
            ev = await db.get(Event, event_id)
        if ev is None:
            return
        tr = await Trace("threat", f"verify {ev.type} event", event_id=event_id, model=get_settings().vlm_model).open()
        try:
            await tr.step("thought", text=f"'{ev.title}' needs visual confirmation before escalation. Waiting for "
                                          f"the evidence clip, then asking the vision model a type-specific question.")
            await self.o.wait_evidence(event_id)
            q = VERIFY_QUESTIONS.get(ev.type, "Describe what is happening. Is this a genuine security concern?")
            await tr.step("tool_call", tool="inspect_evidence", args={"event_id": event_id, "question": q})
            res = await call_tool("inspect_evidence", {"event_id": event_id, "question": q}, "agent:threat",
                                  ["inspect_evidence"])
            await tr.step("tool_result", tool="inspect_evidence", result=res)
            verdict = res.get("verdict", "uncertain") if isinstance(res, dict) else "uncertain"
            conf = float(res.get("confidence", 0.5) or 0.5) if isinstance(res, dict) else 0.0
            if "error" in (res or {}):
                verdict, conf = "uncertain", 0.0
            # Policy from measurement (docs/EVALUATION.md): on cascade-flagged fights the VLM confirmed 5/6
            # and confirmed 0/10 hard negatives -> "confirmed" is trustworthy and escalates. Its "rejected"
            # is NOT (it missed 1 in 6 real fights), so a rejection lowers severity one step, never below
            # medium, and leaves the event for a human instead of burying it.
            new_sev, status = ev.severity, "needs_review"
            order = ["info", "low", "medium", "high", "critical"]
            if verdict == "confirmed" and conf >= 0.6:
                status = "verified"
                if ev.type == "violence":
                    new_sev = "critical"
            elif verdict == "rejected" and conf >= 0.6:
                status = "vlm_rejected"
                new_sev = order[max(order.index("medium"), order.index(ev.severity) - 1)] \
                    if order.index(ev.severity) > order.index("medium") else ev.severity
            reasoning = (f"Vision model verdict '{verdict}' (confidence {conf:.2f}). "
                         + ("Escalating." if status == "verified" else
                            "Not visually confirmed: severity lowered one step (floor medium) and held for human "
                            "review — the VLM misses some real events, so a rejection never dismisses one."
                            if status == "vlm_rejected" else "Kept at original severity for human review."))
            await tr.step("decision", text=reasoning, status=status, severity=new_sev)
            async with session() as db:
                ev = await db.get(Event, event_id)
                ev.status = status
                ev.severity = new_sev
                ev.verification = {"verdict": verdict, "confidence": conf, "answer": res.get("answer"),
                                   "observations": res.get("observations", []), "model": get_settings().vlm_model,
                                   "reasoning": reasoning, "run_id": tr.run_id}
                await db.commit()
                bus.publish("event.updated", event_dict(ev))
            self.o.stats["verifications"] += 1
            await tr.close({"verdict": verdict, "confidence": conf, "status": status, "severity": new_sev})
        except Exception as e:  # noqa: BLE001
            log.exception("verification failed")
            async with session() as db:
                ev = await db.get(Event, event_id)
                ev.status = "needs_review"
                ev.verification = {"verdict": "unavailable", "reasoning": f"Verification failed: {e}"}
                await db.commit()
            await tr.close(error=str(e))
        await self.o.escalate(event_id)


class IdentityAgent:
    """FRS watchlist hit -> evidence from the live frame -> enriched critical event."""

    def __init__(self, orch: Orchestrator) -> None:
        self.o = orch

    async def handle(self, data: dict) -> None:
        from vigil.perception.engine import engine
        frs_res = data["frs"]
        iid = data["identity_id"]
        tr = await Trace("identity", f"watchlist hit {frs_res.get('name')}").open()
        await tr.step("observation", text=f"FRS matched identity {iid} to watchlist subject '{frs_res.get('name')}' "
                                          f"(sim {frs_res.get('score', 0):.2f}; FRS applies two-recogniser agreement "
                                          f"and open-set gates).")
        await tr.step("tool_call", tool="frs_watchlist_record", args={"criminal_id": frs_res["criminal_id"]})
        rec = await call_tool("frs_watchlist_record", {"criminal_id": frs_res["criminal_id"]}, "agent:identity",
                              ["frs_watchlist_record"])
        await tr.step("tool_result", tool="frs_watchlist_record", result=rec)
        case = rec.get("case", {}) if isinstance(rec, dict) else {}
        # Keep a copy of the face that FRS matched.
        face_path = get_settings().media_dir / "faces" / f"{iid}_frs.jpg"
        face_path.write_bytes(data["face_jpg"])
        sig = Signal(
            type="watchlist_match", severity="critical", confidence=round(float(frs_res.get("score", 0)), 3),
            title=f"Watchlist candidate: {frs_res.get('name')} ({iid})",
            description=(f"Person {iid} matched FRS watchlist subject '{frs_res.get('name')}'"
                         + (f" — {', '.join(str(case[k]) for k in ('case_type', 'charges') if case.get(k))}"
                            if any(case.get(k) for k in ('case_type', 'charges')) else "")
                         + ". FRS matches are candidates: verify the face before acting."),
            camera_id=data["camera_id"], ts=time.time(), track_uids=[data["track_uid"]], identity_ids=[iid],
            explanation={"rule": "frs_watchlist", "frs_similarity": frs_res.get("score"),
                         "frs_top_k": frs_res.get("top_k"), "frs_record": rec, "face": f"faces/{iid}_frs.jpg",
                         "reasoning": "Identity's best face was searched against the FRS gallery; FRS reported a "
                                      "match under its calibrated gates."})
        sig.event_id = new_id("evt")
        w = engine.worker(data["camera_id"])
        if w is not None:
            w.inject(sig, data["track_uid"])  # evidence from the live frame; flows back as a signal
        else:
            await self.o.on_signal(sig)
        await tr.step("decision", text="Raised a critical watchlist event with live evidence; an incident and an "
                                       "investigation follow automatically.", event_id=sig.event_id)
        await tr.close({"event_id": sig.event_id, "criminal": frs_res.get("name")})


async def _fired_recently(etype: str, identity_id: str, minutes: float) -> bool:
    """Durable once-per-window guard (survives restarts, unlike in-memory state)."""
    async with session() as db:
        from vigil.db import involves
        row = (await db.execute(select(Event.id).where(
            Event.type == etype, Event.ts >= utcnow() - timedelta(minutes=minutes), involves(identity_id)).limit(1))).first()
    return row is not None


class BehaviorAgent:
    """Temporal reasoning across sightings and events: repeat visits and correlated suspicious patterns."""

    PATTERN_TYPES = {"loitering", "pacing", "after_hours", "anomalous_path", "zone_intrusion",
                     "repeated_appearance", "running"}

    def __init__(self, orch: Orchestrator) -> None:
        self.o = orch

    async def _rules(self) -> dict:
        async with session() as db:
            g = await db.get(Setting, "rules")
        return merge_rules(g.value if g else {})

    async def on_track_closed(self, s: dict) -> None:
        iid = s.get("identity_id")
        if not iid:
            return
        rules = await self._rules()
        r = rules["repeated_appearance"]
        m = identities().meta.get(iid)
        if m is not None and m.category in ("staff", "vip"):
            return
        now = time.time()
        async with session() as db:
            since = utcnow() - timedelta(minutes=r["window_min"])
            rows = (await db.execute(select(Track).where(Track.identity_id == iid, Track.started_at >= since)
                                     .order_by(Track.started_at))).scalars().all()
        visits = len(rows)
        if r.get("enabled") and visits >= r["min_visits"] and now - self.o._repeat_fired.get(iid, 0) > r["window_min"] * 60 \
                and not await _fired_recently("repeated_appearance", iid, r["window_min"]):
            self.o._repeat_fired[iid] = now
            cams = sorted({t.camera_id for t in rows})
            sig = Signal(
                type="repeated_appearance", severity=r["severity"], confidence=min(0.5 + 0.08 * visits, 0.9),
                title=f"{m.label if m else iid} seen {visits} times in {r['window_min']} min",
                description=f"{iid} appeared in {visits} separate sightings across {len(cams)} camera(s) "
                            f"({', '.join(cams)}) within {r['window_min']} minutes.",
                camera_id=s["camera_id"], ts=now, track_uids=[t.id for t in rows][-10:], identity_ids=[iid],
                explanation={"rule": "repeated_appearance", "visits": visits, "threshold": r["min_visits"],
                             "window_min": r["window_min"], "cameras": cams,
                             "sightings": [{"track": t.id, "camera": t.camera_id, "start": t.started_at.isoformat(),
                                            "duration_s": t.duration_s} for t in rows][-10:],
                             "reasoning": "Returning repeatedly without being a known staff member can indicate "
                                          "surveillance of the premises."},
                evidence={"keyframe": s.get("best_person_path") or s.get("best_face_path")})
            sig.event_id = new_id("evt")
            await self.o.on_signal(sig)
        await self.correlate(iid, s["camera_id"])

    async def correlate(self, iid: str, camera_id: str) -> None:
        """Several individually-minor behaviours by the same person -> one explained, escalated finding."""
        now = time.time()
        if now - self.o._pattern_fired.get(iid, 0) < 1800 or await _fired_recently("suspicious_pattern", iid, 30):
            return
        async with session() as db:
            evs = (await db.execute(select(Event).where(Event.ts >= utcnow() - timedelta(minutes=30))
                                    .order_by(Event.ts))).scalars().all()
        mine = [e for e in evs if iid in (e.identity_ids or []) and e.type in self.PATTERN_TYPES
                and e.status not in ("rejected", "dismissed")]
        types = sorted({e.type for e in mine})
        if len(types) < 2:
            return
        self.o._pattern_fired[iid] = now
        tr = await Trace("behavior", f"correlate behaviour of {iid}").open()
        await tr.step("observation", text=f"{iid} triggered {len(mine)} minor events of {len(types)} kinds in 30 min: "
                                          f"{', '.join(types)}.")
        sev = "high" if ("zone_intrusion" in types or len(types) >= 3) else "medium"
        await tr.step("decision", text=f"Individually minor, together a pattern -> raising a '{sev}' suspicious-pattern "
                                       f"finding that references each constituent event.")
        last = mine[-1]
        sig = Signal(
            type="suspicious_pattern", severity=sev, confidence=min(0.55 + 0.1 * len(types), 0.9),
            title=f"Suspicious pattern: {iid} ({', '.join(types)})",
            description=f"{iid} showed {len(types)} distinct suspicious behaviours within 30 minutes: "
                        + "; ".join(f"{e.type} at {e.camera_id}" for e in mine[-6:]) + ".",
            camera_id=last.camera_id or camera_id, ts=now, identity_ids=[iid],
            track_uids=sorted({t for e in mine for t in (e.track_ids or [])})[-10:],
            explanation={"rule": "behaviour_correlation", "window_min": 30, "distinct_behaviours": types,
                         "constituent_events": [{"id": e.id, "type": e.type, "ts": e.ts.isoformat(),
                                                 "camera": e.camera_id} for e in mine],
                         "reasoning": "Correlation across events: combinations of loitering, pacing, unusual paths, "
                                      "repeat visits or intrusion are characteristic of casing."},
            evidence=dict(last.evidence or {}))
        sig.event_id = new_id("evt")
        await self.o.on_signal(sig)
        await tr.close({"event_id": sig.event_id, "behaviours": types})


INVESTIGATOR_SYSTEM = """You are the investigation agent of a video-analytics security system at a police facility.
You receive an incident raised by automated perception. Your job: establish what happened, who is involved,
how it relates to other activity, and whether it is a genuine threat — then act proportionately.

How to work:
- Choose tools yourself. Typical moves: read the incident and its events; read event explanations (measured
  values vs thresholds) and verification; look at evidence with the vision model when visual facts matter;
  pull the involved identities' timelines, associates and watchlist records; correlate nearby events;
  check the camera context.
- Ground every claim in tool output and cite IDs. Say "unknown" rather than guess.
- Face matches (including FRS watchlist hits) are CANDIDATES for human verification, never confirmed identities.
- Automated detectors produce false positives (e.g. sports, hugging, people lying down deliberately).
  Weigh verification results and context.
- Actions: add_incident_note to record findings. update_incident to set severity/status when evidence clearly
  supports it (use false_positive only with clear contrary evidence). notify only for high-confidence, actionable
  threats. flag_identity 'watch' only with concrete behavioural evidence. Every action needs a reason.
- Be efficient: at most ~6 tool calls. Do not describe ethnicity or make assumptions from appearance."""

INVESTIGATION_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "timeline": {"type": "array", "items": {"type": "string"}},
    "persons": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "role": {"type": "string"}, "notes": {"type": "string"}}}},
    "assessment": {"type": "string", "enum": ["real_threat", "likely_benign", "inconclusive"]},
    "threat_level": {"type": "string", "enum": ["none", "low", "medium", "high", "critical"]},
    "confidence": {"type": "number"},
    "key_evidence": {"type": "array", "items": {"type": "string"}},
    "recommended_actions": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "assessment", "threat_level", "confidence", "key_evidence", "recommended_actions"]}


class InvestigationAgent:
    def __init__(self, orch: Orchestrator | None = None) -> None:
        self.o = orch

    async def run(self, incident_id: str, requested_by: str | None = None) -> dict:
        async with session() as db:
            inc = await db.get(Incident, incident_id)
            if inc is None:
                return {"error": "incident not found"}
            inc.status = "investigating" if inc.status == "new" else inc.status
            await db.commit()
            title, sev = inc.title, inc.severity
        bus.publish("incident.updated", {"id": incident_id, "status": "investigating"})
        tr = await Trace("investigator", f"investigate: {title}" + (f" (by {requested_by})" if requested_by else ""),
                         incident_id=incident_id, model=get_settings().llm_model).open()
        task = (f"Investigate incident {incident_id} ('{title}', severity {sev}). Start with get_incident. "
                f"Local timezone: {get_settings().timezone}.")
        try:
            out = await react(tr, INVESTIGATOR_SYSTEM, task, READ_TOOLS + ACTION_TOOLS, INVESTIGATION_SCHEMA,
                              actor="agent:investigator")
        except (LLMError, Exception) as e:  # noqa: BLE001
            await tr.close(error=str(e))
            raise
        async with session() as db:
            inc = await db.get(Incident, incident_id)
            inc.conclusion = {**out, "run_id": tr.run_id, "at": utcnow().isoformat()}
            inc.summary = out.get("summary") or inc.summary
            try:
                inc.confidence = float(out.get("confidence", inc.confidence))
            except (TypeError, ValueError):
                pass
            inc.updated_at = utcnow()
            await db.commit()
            d = incident_dict(inc)
        bus.publish("incident.updated", d)
        await tr.close(out)
        if sev_ge(d["severity"], "critical") and not d.get("report_md"):
            try:
                await ReportingAgent().generate(incident_id)
            except Exception:  # noqa: BLE001
                log.exception("auto report failed")
        return out


REPORT_SYSTEM = """You write concise, factual incident reports for police supervisors from structured data.
Use Markdown with these sections: Summary, Timeline (local time), Persons involved, Evidence, Automated analysis
(what each detector measured and how verification went), Assessment, Recommended actions.
Only state what the data supports. Face matches are candidates pending human verification. Cite event IDs."""


class ReportingAgent:
    async def generate(self, incident_id: str) -> str:
        from vigil.agents.tools import get_incident, get_event
        tr = await Trace("reporter", f"report for {incident_id}", incident_id=incident_id,
                         model=get_settings().llm_model).open()
        inc = await get_incident(incident_id)
        await tr.step("tool_result", tool="get_incident", result={"events": len(inc.get("events", []))})
        details = []
        for e in inc.get("events", [])[:12]:
            d = await get_event(e["id"])
            details.append({k: d.get(k) for k in ("id", "time_local", "camera_id", "type", "severity", "confidence",
                                                   "title", "description", "explanation", "verification", "status")})
        payload = {"incident": {k: v for k, v in inc.items() if k != "events"}, "events": details}
        import json
        try:
            msg = await llm().chat([{"role": "system", "content": REPORT_SYSTEM},
                                    {"role": "user", "content": "Write the report for:\n" +
                                     json.dumps(payload, default=str)[:24000]}], temperature=0.2)
        except LLMError as e:
            await tr.close(error=str(e))
            raise
        md = msg.get("content", "").strip()
        async with session() as db:
            i = await db.get(Incident, incident_id)
            i.report_md = md
            i.updated_at = utcnow()
            await db.commit()
            d = incident_dict(i)
        bus.publish("incident.updated", d)
        await tr.step("final", output={"chars": len(md)})
        await tr.close({"chars": len(md)})
        return md


ANALYST_SYSTEM = """You are the analyst assistant of a video-analytics security system. Operators ask questions about
people, cameras, events and incidents. Use the tools to look things up; never invent data. Answer in concise
Markdown, cite IDs (events evt_..., identities P-..., tracks), and give local times. If the data does not answer
the question, say so and suggest what to check. Face matches are candidates, not confirmed identities."""

ANALYST_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"},
                                                    "referenced_ids": {"type": "array", "items": {"type": "string"}}},
                  "required": ["answer"]}


class AnalystAgent:
    async def start(self, question: str, user: str) -> Trace:
        return await Trace("analyst", f"chat ({user}): {question[:120]}", model=get_settings().llm_model).open()

    async def run(self, tr: Trace, question: str, user: str, history: list[dict] | None = None) -> dict:
        try:
            out = await react(tr, ANALYST_SYSTEM + f"\nLocal timezone: {get_settings().timezone}.", question,
                              READ_TOOLS, ANALYST_SCHEMA, actor=f"analyst:{user}", history=history)
        except Exception as e:  # noqa: BLE001
            await tr.close(error=str(e))
            return {"answer": f"The analyst agent failed: {e}"}
        await tr.close(out)
        return out


_orch: Orchestrator | None = None


def orchestrator() -> Orchestrator:
    global _orch
    if _orch is None:
        _orch = Orchestrator()
    return _orch

