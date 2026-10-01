"""Tools the agents can call. Read tools are side-effect free; action tools are audited.

Each tool: an async function taking keyword args and returning JSON-able data,
plus an OpenAI-style function schema so the LLM can choose it.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx
import numpy as np
from sqlalchemy import desc, or_, select

from vigil.agents.llm import llm
from vigil.bus import bus
from vigil.config import get_settings
from vigil.db import Camera, Event, Identity, Incident, Track, Zone, involves, session, utcnow
from vigil.frs_client import frs
from vigil.security import audit
from vigil.services import event_dict, identity_dict, incident_dict, track_dict

log = logging.getLogger("vigil.tools")


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    fn: Callable[..., Awaitable[Any]]
    action: bool = False

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": {"type": "object", **self.params}}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None,
         action: bool = False):
    def deco(fn):
        REGISTRY[name] = Tool(name, description, {"properties": properties or {}, "required": required or []}, fn,
                              action)
        return fn
    return deco


def _since(minutes: float | None, default: float = 24 * 60) -> datetime:
    return utcnow() - timedelta(minutes=float(minutes or default))


def _local(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(get_settings().timezone)).strftime("%Y-%m-%d %H:%M:%S")


def _brief_event(e: Event) -> dict:
    return {"id": e.id, "time": _local(e.ts), "camera": e.camera_id, "type": e.type, "severity": e.severity,
            "confidence": e.confidence, "title": e.title, "status": e.status,
            "verification": (e.verification or {}).get("verdict"), "identities": e.identity_ids,
            "incident_id": e.incident_id}


def _brief_track(t: Track) -> dict:
    return {"track_id": t.id, "camera": t.camera_id, "start": _local(t.started_at), "end": _local(t.ended_at),
            "duration_s": round(t.duration_s, 1), "identity": t.identity_id, "max_speed_bh_s": t.max_speed,
            "zones_dwell_s": t.zones, "posture": (t.attributes or {}).get("posture")}


# ─────────────────────────────── read tools ────────────────────────────


@tool("get_event", "Full details of one event: explanation (measured values vs thresholds), evidence, verification.",
      {"event_id": {"type": "string"}}, ["event_id"])
async def get_event(event_id: str) -> dict:
    async with session() as db:
        e = await db.get(Event, event_id)
        if e is None:
            return {"error": "event not found"}
        d = event_dict(e)
        d["time_local"] = _local(e.ts)
        return d


@tool("get_incident", "An incident with all its events (brief) and any prior conclusion.",
      {"incident_id": {"type": "string"}}, ["incident_id"])
async def get_incident(incident_id: str) -> dict:
    async with session() as db:
        i = await db.get(Incident, incident_id)
        if i is None:
            return {"error": "incident not found"}
        evs = (await db.execute(select(Event).where(Event.incident_id == incident_id).order_by(Event.ts))).scalars().all()
        d = incident_dict(i)
        d.pop("report_md", None)
        d["created_local"] = _local(i.created_at)
        d["events"] = [_brief_event(e) for e in evs]
        return d


@tool("search_events", "Search events by camera, type, severity, identity and time window (minutes back).",
      {"camera_id": {"type": "string"}, "type": {"type": "string", "description": "e.g. violence, loitering, fall, "
                                                "zone_intrusion, watchlist_match, weapon, running, crowd"},
       "min_severity": {"type": "string", "enum": ["info", "low", "medium", "high", "critical"]},
       "identity_id": {"type": "string"}, "since_minutes": {"type": "number"}, "limit": {"type": "integer"}})
async def search_events(camera_id: str | None = None, type: str | None = None, min_severity: str | None = None,
                        identity_id: str | None = None, since_minutes: float | None = None, limit: int = 25) -> dict:
    from vigil.config import SEVERITY_ORDER
    async with session() as db:
        q = select(Event).where(Event.ts >= _since(since_minutes), Event.is_demo.is_(False)).order_by(desc(Event.ts)).limit(min(int(limit or 25), 100) * 3)
        if camera_id:
            q = q.where(Event.camera_id == camera_id)
        if type:
            q = q.where(Event.type == type)
        if identity_id:
            q = q.where(involves(identity_id))
        rows = (await db.execute(q)).scalars().all()
    if min_severity:
        rows = [e for e in rows if SEVERITY_ORDER.get(e.severity, 0) >= SEVERITY_ORDER[min_severity]]
    rows = rows[: min(int(limit or 25), 100)]
    return {"count": len(rows), "events": [_brief_event(e) for e in rows]}


@tool("get_identity", "Profile of a person identity (P-xxxxx): name, category, watchlist status, first/last seen, "
      "sightings count, and the most recent sightings.", {"identity_id": {"type": "string"}}, ["identity_id"])
async def get_identity(identity_id: str) -> dict:
    async with session() as db:
        i = await db.get(Identity, identity_id)
        if i is None:
            return {"error": "identity not found"}
        tracks = (await db.execute(select(Track).where(Track.identity_id == identity_id)
                                   .order_by(desc(Track.started_at)).limit(10))).scalars().all()
        d = identity_dict(i)
        d["first_seen"], d["last_seen"] = _local(i.first_seen), _local(i.last_seen)
        d["recent_sightings"] = [_brief_track(t) for t in tracks]
        return d


@tool("identity_timeline", "Chronological movement of one identity across all cameras over the last N hours "
      "(sightings with camera, time, dwell, zones) plus events involving them.",
      {"identity_id": {"type": "string"}, "hours": {"type": "number"}}, ["identity_id"])
async def identity_timeline(identity_id: str, hours: float = 24) -> dict:
    since = utcnow() - timedelta(hours=float(hours or 24))
    async with session() as db:
        tracks = (await db.execute(select(Track).where(Track.identity_id == identity_id, Track.started_at >= since)
                                   .order_by(Track.started_at))).scalars().all()
        evs = (await db.execute(select(Event).where(Event.ts >= since, involves(identity_id))
                                .order_by(Event.ts))).scalars().all()
    cams = sorted({t.camera_id for t in tracks})
    return {"identity_id": identity_id, "window_hours": hours, "sightings": len(tracks), "cameras": cams,
            "total_dwell_s": round(sum(t.duration_s for t in tracks), 1),
            "timeline": [_brief_track(t) for t in tracks][-60:], "events": [_brief_event(e) for e in evs][-40:]}


@tool("get_track", "One sighting (track): camera, times, identity, speeds, zone dwell, path start/end.",
      {"track_id": {"type": "string"}}, ["track_id"])
async def get_track(track_id: str) -> dict:
    async with session() as db:
        t = await db.get(Track, track_id)
        if t is None:
            return {"error": "track not found"}
    d = _brief_track(t)
    p = t.path or []
    if p:
        d["path_start_norm"], d["path_end_norm"] = p[0][1:], p[-1][1:]
        d["path_points"] = len(p)
        d["net_displacement_norm"] = round(float(np.hypot(p[-1][1] - p[0][1], p[-1][2] - p[0][2])), 3)
    d["anomaly_score"] = t.anomaly_score
    return d


@tool("correlate_events", "Find other events related to an event: same camera within a window, or involving the "
      "same identities anywhere. Use to build a sequence of activity.",
      {"event_id": {"type": "string"}, "window_minutes": {"type": "number"}}, ["event_id"])
async def correlate_events(event_id: str, window_minutes: float = 30) -> dict:
    async with session() as db:
        e = await db.get(Event, event_id)
        if e is None:
            return {"error": "event not found"}
        w = timedelta(minutes=float(window_minutes or 30))
        rows = (await db.execute(select(Event).where(Event.ts >= e.ts - w, Event.ts <= e.ts + w, Event.id != e.id,
                                                     Event.is_demo.is_(False))
                                 .order_by(Event.ts))).scalars().all()
    ids = set(e.identity_ids or [])
    same_cam = [_brief_event(x) for x in rows if x.camera_id == e.camera_id]
    same_people = [_brief_event(x) for x in rows if ids & set(x.identity_ids or [])]
    return {"anchor": _brief_event(e), "same_camera": same_cam[:30], "same_identities": same_people[:30]}


@tool("co_occurrence", "People seen together with an identity (same camera, overlapping in time) in the last N hours.",
      {"identity_id": {"type": "string"}, "hours": {"type": "number"}}, ["identity_id"])
async def co_occurrence(identity_id: str, hours: float = 24) -> dict:
    since = utcnow() - timedelta(hours=float(hours or 24))
    async with session() as db:
        mine = (await db.execute(select(Track).where(Track.identity_id == identity_id, Track.started_at >= since))).scalars().all()
        together: dict[str, dict] = {}
        for t in mine:
            end = t.ended_at or t.started_at
            others = (await db.execute(select(Track).where(
                Track.camera_id == t.camera_id, Track.identity_id.is_not(None), Track.identity_id != identity_id,
                Track.started_at <= end + timedelta(seconds=30),
                or_(Track.ended_at.is_(None), Track.ended_at >= t.started_at - timedelta(seconds=30))))).scalars().all()
            for o in others:
                d = together.setdefault(o.identity_id, {"identity_id": o.identity_id, "times_together": 0, "cameras": set()})
                d["times_together"] += 1
                d["cameras"].add(o.camera_id)
    out = sorted(together.values(), key=lambda d: -d["times_together"])
    for d in out:
        d["cameras"] = sorted(d["cameras"])
    return {"identity_id": identity_id, "associates": out[:20]}


async def _clip_text(q: str) -> np.ndarray:
    from vigil.perception.models import clip_text, hub
    return (await asyncio.wrap_future(hub().aux.submit(clip_text, [q])))[0].astype(np.float32)


async def _appearance_rank(qv: np.ndarray, hours: float, camera_id: str | None, limit: int,
                           exclude: str | None = None) -> list[dict]:
    since = utcnow() - timedelta(hours=float(hours or 24))
    async with session() as db:
        q = select(Track).where(Track.started_at >= since, Track.appearance.is_not(None), Track.is_demo.is_(False))
        if camera_id:
            q = q.where(Track.camera_id == camera_id)
        rows = (await db.execute(q.order_by(desc(Track.started_at)).limit(5000))).scalars().all()
    rows = [r for r in rows if r.id != exclude]
    if not rows:
        return []
    m = np.stack([np.frombuffer(r.appearance, np.float16).astype(np.float32) for r in rows])
    sims = m @ qv
    order = np.argsort(-sims)[:limit]
    return [{**_brief_track(rows[i]), "similarity": round(float(sims[i]), 3),
             "person_url": f"/media/{rows[i].best_person_path}" if rows[i].best_person_path else None} for i in order]


@tool("search_people_by_description", "Natural-language appearance search over recent sightings, e.g. "
      "'man in a red shirt with a backpack'. Returns best-matching tracks (CLIP similarity; a hint, not an identity).",
      {"description": {"type": "string"}, "hours": {"type": "number"}, "camera_id": {"type": "string"},
       "limit": {"type": "integer"}}, ["description"])
async def search_people_by_description(description: str, hours: float = 24, camera_id: str | None = None,
                                       limit: int = 8) -> dict:
    qv = await _clip_text(f"a CCTV photo of {description}")
    return {"query": description, "results": await _appearance_rank(qv, hours, camera_id, min(int(limit or 8), 30))}


@tool("find_similar_appearance", "Find sightings on any camera whose clothing/appearance resembles a given track "
      "(cross-camera hint when no face is visible). Similarity >0.9 is strong, <0.8 weak.",
      {"track_id": {"type": "string"}, "hours": {"type": "number"}, "limit": {"type": "integer"}}, ["track_id"])
async def find_similar_appearance(track_id: str, hours: float = 24, limit: int = 8) -> dict:
    async with session() as db:
        t = await db.get(Track, track_id)
    if t is None or t.appearance is None:
        return {"error": "track has no appearance descriptor"}
    qv = np.frombuffer(t.appearance, np.float16).astype(np.float32)
    return {"track_id": track_id, "results": await _appearance_rank(qv, hours, None, min(int(limit or 8), 30), exclude=track_id)}


@tool("camera_context", "Camera name/location, configured zones, live status (people in view), and event counts "
      "in the last hour.", {"camera_id": {"type": "string"}}, ["camera_id"])
async def camera_context(camera_id: str) -> dict:
    from vigil.perception.engine import engine
    async with session() as db:
        c = await db.get(Camera, camera_id)
        if c is None:
            return {"error": "camera not found"}
        zones = (await db.execute(select(Zone).where(Zone.camera_id == camera_id))).scalars().all()
        evs = (await db.execute(select(Event).where(Event.camera_id == camera_id, Event.ts >= _since(60)))).scalars().all()
    counts: dict[str, int] = {}
    for e in evs:
        counts[e.type] = counts.get(e.type, 0) + 1
    w = engine.worker(camera_id)
    live = w.stats() if w else {"status": "not running"}
    return {"camera_id": camera_id, "name": c.name, "location": c.location, "source": c.source_type,
            "zones": [{"name": z.name, "kind": z.kind, "rules": z.rules} for z in zones],
            "live": {k: live.get(k) for k in ("status", "fps", "active_tracks")}, "events_last_hour": counts}


VISION_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"}, "verdict": {"type": "string", "enum": ["confirmed", "rejected", "uncertain"]},
    "confidence": {"type": "number"}, "observations": {"type": "array", "items": {"type": "string"}},
    "people_count": {"type": "integer"}}, "required": ["answer", "verdict", "confidence", "observations"]}
VISION_SYSTEM = ("You are a careful CCTV analyst. Describe only what is clearly visible. Frames are in time order. "
                 "Do not guess identities, ethnicity or intent beyond visible behaviour. If unclear, say uncertain.")


async def _evidence_images(event_id: str) -> list[bytes]:
    root = get_settings().media_dir / "evidence" / event_id
    frames = sorted(root.glob("f*.jpg"))
    imgs = [p.read_bytes() for p in frames[:6]]
    if not imgs and (root / "key.jpg").exists():
        imgs = [(root / "key.jpg").read_bytes()]
    return imgs


@tool("inspect_evidence", "Ask the vision model a question about an event's evidence frames (time-ordered "
      "stills from the clip). Returns answer, verdict (confirmed/rejected/uncertain for yes/no questions), "
      "confidence and observations.", {"event_id": {"type": "string"}, "question": {"type": "string"}},
      ["event_id", "question"])
async def inspect_evidence(event_id: str, question: str) -> dict:
    imgs = await _evidence_images(event_id)
    if not imgs:
        return {"error": "no evidence frames yet"}
    return await llm().vision(question, imgs, VISION_SCHEMA, VISION_SYSTEM)


@tool("look_at_camera_now", "Ask the vision model a question about the current live view of a camera.",
      {"camera_id": {"type": "string"}, "question": {"type": "string"}}, ["camera_id", "question"])
async def look_at_camera_now(camera_id: str, question: str) -> dict:
    from vigil.perception.engine import engine
    w = engine.worker(camera_id)
    if w is None or not w.recorder.ring:
        return {"error": "camera not running"}
    frames = list(w.recorder.ring)
    imgs = [frames[i][1] for i in sorted({len(frames) - 1, max(0, len(frames) - 5), max(0, len(frames) - 9)})]
    return await llm().vision(question, imgs, VISION_SCHEMA, VISION_SYSTEM)


@tool("frs_watchlist_record", "Look up a person on the FRS criminal watchlist (port-8000 system): name, group, case "
      "metadata, and where FRS cameras last detected them.", {"criminal_id": {"type": "string"}}, ["criminal_id"])
async def frs_watchlist_record(criminal_id: str) -> dict:
    try:
        rec = await frs().criminal(criminal_id)
        det = await frs().criminal_detections(criminal_id, limit=10)
    except httpx.HTTPError as e:
        return {"error": f"FRS unavailable: {e}"}
    md = rec.get("metadata", {})
    return {"criminal_id": criminal_id, "name": rec.get("name"), "group": rec.get("group"),
            "subgroup": rec.get("subgroup"),
            "case": {k: md.get(k) for k in ("crime_number", "fir_number", "case_type", "police_station", "district",
                                            "charges", "blacklisted") if k in md},
            "frs_detections": [{"camera": d.get("camera_id"), "time": d.get("created_at"),
                                "similarity": d.get("similarity"), "state": d.get("identity_state"),
                                "review": d.get("review_state")} for d in det.get("detections", [])][:10],
            "note": "FRS matches are CANDIDATES requiring human verification."}


@tool("frs_recent_detections", "Recent detections from the FRS system's own cameras (watchlist and known people).",
      {"limit": {"type": "integer"}, "camera_id": {"type": "string"}})
async def frs_recent_detections(limit: int = 20, camera_id: str | None = None) -> dict:
    try:
        d = await frs().detections(limit=min(int(limit or 20), 100), camera_id=camera_id)
    except httpx.HTTPError as e:
        return {"error": f"FRS unavailable: {e}"}
    return {"detections": [{"name": x.get("name"), "kind": x.get("kind"), "camera": x.get("camera_id"),
                            "time": x.get("created_at"), "similarity": x.get("similarity"),
                            "state": x.get("identity_state")} for x in d.get("detections", [])]}


@tool("list_active_incidents", "Open incidents (new/investigating) across the site.", {"limit": {"type": "integer"}})
async def list_active_incidents(limit: int = 20) -> dict:
    async with session() as db:
        rows = (await db.execute(select(Incident).where(Incident.status.in_(["new", "investigating", "confirmed"]),
                                                        Incident.is_demo.is_(False))
                                 .order_by(desc(Incident.created_at)).limit(min(int(limit or 20), 50)))).scalars().all()
    return {"incidents": [{"id": i.id, "title": i.title, "type": i.type, "severity": i.severity, "status": i.status,
                           "created": _local(i.created_at), "camera": i.camera_id} for i in rows]}


@tool("site_summary", "Counts of sightings, distinct identities and events by type over the last N hours.",
      {"hours": {"type": "number"}})
async def site_summary(hours: float = 24) -> dict:
    since = utcnow() - timedelta(hours=float(hours or 24))
    async with session() as db:
        tracks = (await db.execute(select(Track.camera_id, Track.identity_id).where(
            Track.started_at >= since, Track.is_demo.is_(False)))).all()
        evs = (await db.execute(select(Event.type, Event.severity).where(Event.ts >= since, Event.is_demo.is_(False)))).all()
    by_type: dict[str, int] = {}
    for t, _ in evs:
        by_type[t] = by_type.get(t, 0) + 1
    by_cam: dict[str, int] = {}
    for c, _ in tracks:
        by_cam[c] = by_cam.get(c, 0) + 1
    return {"hours": hours, "sightings": len(tracks), "distinct_identities": len({i for _, i in tracks if i}),
            "sightings_by_camera": by_cam, "events_by_type": by_type}


# ─────────────────────────────── action tools ──────────────────────────


@tool("update_incident", "Change an incident's status and/or severity and/or summary. Status: investigating, "
      "confirmed, false_positive, resolved.", {"incident_id": {"type": "string"},
      "status": {"type": "string", "enum": ["investigating", "confirmed", "false_positive", "resolved"]},
      "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]}, "summary": {"type": "string"},
      "reason": {"type": "string"}}, ["incident_id", "reason"], action=True)
async def update_incident(incident_id: str, reason: str, status: str | None = None, severity: str | None = None,
                          summary: str | None = None, _actor: str = "agent") -> dict:
    async with session() as db:
        i = await db.get(Incident, incident_id)
        if i is None:
            return {"error": "incident not found"}
        changes = {}
        if status and status != i.status:
            changes["status"] = [i.status, status]
            i.status = status
        if severity and severity != i.severity:
            changes["severity"] = [i.severity, severity]
            i.severity = severity
        if summary:
            i.summary = summary
            changes["summary"] = True
        i.notes = (i.notes or []) + [{"ts": utcnow().isoformat(), "by": _actor, "text": f"Updated: {reason}",
                                       "changes": changes}]
        i.updated_at = utcnow()
        await db.commit()
        d = incident_dict(i)
    await audit(_actor, "incident.update", incident_id, reason=reason, changes=changes)
    bus.publish("incident.updated", d)
    return {"ok": True, "changes": changes}


@tool("add_incident_note", "Append an investigative note to an incident.",
      {"incident_id": {"type": "string"}, "note": {"type": "string"}}, ["incident_id", "note"], action=True)
async def add_incident_note(incident_id: str, note: str, _actor: str = "agent") -> dict:
    async with session() as db:
        i = await db.get(Incident, incident_id)
        if i is None:
            return {"error": "incident not found"}
        i.notes = (i.notes or []) + [{"ts": utcnow().isoformat(), "by": _actor, "text": note}]
        i.updated_at = utcnow()
        await db.commit()
        d = incident_dict(i)
    bus.publish("incident.updated", d)
    return {"ok": True}


@tool("flag_identity", "Set an identity's category (watch = keep an eye on; banned = alert on sight; none = clear). "
      "Requires a reason grounded in evidence.", {"identity_id": {"type": "string"},
      "category": {"type": "string", "enum": ["none", "watch", "banned"]}, "reason": {"type": "string"}},
      ["identity_id", "category", "reason"], action=True)
async def flag_identity(identity_id: str, category: str, reason: str, _actor: str = "agent") -> dict:
    from vigil.analytics.identity import identities
    async with session() as db:
        i = await db.get(Identity, identity_id)
        if i is None:
            return {"error": "identity not found"}
        old = i.category
        i.category = category
        i.notes = ((i.notes or "") + f"\n[{_local(utcnow())}] {_actor}: category {old}->{category}: {reason}").strip()
        await db.commit()
    m = identities().meta.get(identity_id)
    if m:
        m.category = category
    await audit(_actor, "identity.flag", identity_id, category=category, reason=reason)
    return {"ok": True, "old": old, "new": category}


@tool("notify", "Send an operator notification (in-app, plus webhook if configured). Use for high-confidence, "
      "actionable situations only.", {"message": {"type": "string"},
      "severity": {"type": "string", "enum": ["info", "low", "medium", "high", "critical"]},
      "incident_id": {"type": "string"}}, ["message", "severity"], action=True)
async def notify(message: str, severity: str, incident_id: str | None = None, _actor: str = "agent") -> dict:
    payload = {"ts": utcnow().isoformat(), "message": message, "severity": severity, "incident_id": incident_id,
               "by": _actor}
    bus.publish("notification", payload)
    await audit(_actor, "notify", incident_id, message=message, severity=severity)
    url = get_settings().notify_webhook_url
    delivered = False
    if url:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                delivered = (await c.post(url, json=payload)).is_success
        except httpx.HTTPError:
            delivered = False
    return {"ok": True, "webhook_delivered": delivered}


READ_TOOLS = [n for n, t in REGISTRY.items() if not t.action]
ACTION_TOOLS = [n for n, t in REGISTRY.items() if t.action]


async def call_tool(name: str, args: dict, actor: str, allowed: list[str]) -> Any:
    if name not in allowed or name not in REGISTRY:
        return {"error": f"tool '{name}' not available to this agent"}
    t = REGISTRY[name]
    import inspect
    sig = inspect.signature(t.fn)
    clean = {k: v for k, v in (args or {}).items() if k in sig.parameters and not k.startswith("_")}
    if "_actor" in sig.parameters:
        clean["_actor"] = actor
    try:
        return await asyncio.wait_for(t.fn(**clean), timeout=get_settings().llm_timeout_s)
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except asyncio.TimeoutError:
        return {"error": "tool timed out"}
    except Exception as e:  # noqa: BLE001
        log.exception("tool %s failed", name)
        return {"error": f"{type(e).__name__}: {e}"}


def compact(obj: Any, limit: int = 6000) -> str:
    s = json.dumps(obj, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "…(truncated)"


