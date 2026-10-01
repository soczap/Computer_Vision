"""Async persistence helpers and serializers shared by the API and the agents."""
from __future__ import annotations

from datetime import datetime, timezone

from vigil.analytics.identity import identities
from vigil.bus import bus
from vigil.db import AgentRun, Camera, Event, FRSSearch, Identity, Incident, Track, Zone, new_id, session


def _ts(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def media_url(path: str | None) -> str | None:
    return f"/media/{path}" if path else None


async def persist_track(s: dict) -> None:
    started = datetime.fromtimestamp(s["first_ts"], timezone.utc)
    ended = datetime.fromtimestamp(s["last_ts"], timezone.utc)
    async with session() as db:
        row = await db.get(Track, s["uid"])
        if row is None:
            row = Track(id=s["uid"], camera_id=s["camera_id"], local_id=s["local_id"], started_at=started)
            db.add(row)
        row.identity_id = s["identity_id"]
        row.identity_score = s["identity_score"]
        row.identity_method = s["identity_method"]
        row.ended_at = ended
        row.duration_s = s["duration"]
        row.path = s["path"]
        row.max_speed = s["max_speed"]
        row.mean_speed = s["mean_speed"]
        row.zones = s["zones"]
        row.best_face_path = s["best_face_path"] or row.best_face_path
        row.best_person_path = s["best_person_path"] or row.best_person_path
        if s["appearance"] is not None:
            row.appearance = s["appearance"]
        row.attributes = s["attributes"]
        row.anomaly_score = s["anomaly"]
        row.closed = s["closed"]
        await db.commit()
    if s["identity_id"]:
        await identities().record_sighting(s)
    bus.publish("track.closed" if s["closed"] else "track.updated",
                {k: v for k, v in s.items() if k not in ("appearance", "path")})


async def record_frs_search(res: dict | None, identity_id: str | None, camera_id: str | None,
                            track_id: str | None, jpeg: bytes | None, trigger: str = "auto") -> dict | None:
    """Log one FRS watchlist search (our side of the audit trail) and broadcast it."""
    if res is None:
        return None
    from vigil.config import get_settings
    sid = new_id("frs")
    face_rel = None
    if jpeg:
        d = get_settings().media_dir / "frs_queries"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.jpg").write_bytes(jpeg)
        face_rel = f"frs_queries/{sid}.jpg"
    row = FRSSearch(id=sid, identity_id=identity_id, camera_id=camera_id, track_id=track_id, trigger=trigger,
                    outcome=res.get("outcome", "error"), criminal_id=res.get("criminal_id"), name=res.get("name"),
                    score=res.get("score"), top_k=res.get("top_k") or [], latency_ms=res.get("latency_ms"),
                    face_path=face_rel, error=res.get("error"))
    async with session() as db:
        db.add(row)
        await db.commit()
    d = frs_search_dict(row)
    bus.publish("frs.search", d)
    return d


def frs_search_dict(r: FRSSearch) -> dict:
    return {"id": r.id, "ts": _ts(r.ts), "identity_id": r.identity_id, "camera_id": r.camera_id,
            "track_id": r.track_id, "trigger": r.trigger, "outcome": r.outcome, "criminal_id": r.criminal_id,
            "name": r.name, "score": r.score, "top_k": r.top_k or [], "latency_ms": r.latency_ms,
            "face_url": media_url(r.face_path), "error": r.error}


def camera_dict(c: Camera, stats: dict | None = None) -> dict:
    uri = c.source_uri
    if c.source_type in ("rtsp", "http"):
        from vigil.frs_client import redact
        uri = redact(uri)
    return {"id": c.id, "name": c.name, "source_type": c.source_type, "source_uri": uri, "location": c.location,
            "latitude": c.latitude, "longitude": c.longitude, "enabled": c.enabled, "loop": c.loop,
            "realtime": c.realtime, "analysis_fps": c.analysis_fps, "config": c.config or {},
            "created_at": _ts(c.created_at), "stats": stats, "is_demo": bool(c.is_demo)}


def zone_dict(z: Zone) -> dict:
    return {"id": z.id, "camera_id": z.camera_id, "name": z.name, "kind": z.kind, "polygon": z.polygon,
            "rules": z.rules or {}, "enabled": z.enabled}


def identity_dict(i: Identity) -> dict:
    return {"id": i.id, "display_name": i.display_name, "label": i.display_name or i.frs_name or i.id,
            "kind": i.kind, "category": i.category, "notes": i.notes, "tags": i.tags or [],
            "watchlist": bool(i.frs_criminal_id), "frs_criminal_id": i.frs_criminal_id, "frs_name": i.frs_name,
            "frs_score": i.frs_score, "frs_checked_at": _ts(i.frs_checked_at),
            "first_seen": _ts(i.first_seen), "last_seen": _ts(i.last_seen), "last_camera_id": i.last_camera_id,
            "sightings": i.sightings, "face_url": media_url(i.best_face_path), "created_at": _ts(i.created_at),
            "is_demo": bool(i.is_demo)}


def track_dict(t: Track, with_path: bool = False) -> dict:
    d = {"id": t.id, "camera_id": t.camera_id, "local_id": t.local_id, "identity_id": t.identity_id,
         "identity_score": t.identity_score, "identity_method": t.identity_method,
         "started_at": _ts(t.started_at), "ended_at": _ts(t.ended_at), "duration_s": t.duration_s,
         "max_speed": t.max_speed, "mean_speed": t.mean_speed, "zones": t.zones or {},
         "face_url": media_url(t.best_face_path), "person_url": media_url(t.best_person_path),
         "attributes": t.attributes or {}, "anomaly_score": t.anomaly_score, "closed": t.closed,
         "is_demo": bool(t.is_demo)}
    if with_path:
        d["path"] = t.path or []
    return d


def event_dict(e: Event) -> dict:
    ev = e.evidence or {}
    return {"id": e.id, "ts": _ts(e.ts), "camera_id": e.camera_id, "type": e.type, "severity": e.severity,
            "confidence": e.confidence, "title": e.title, "description": e.description,
            "track_ids": e.track_ids or [], "identity_ids": e.identity_ids or [], "explanation": e.explanation or {},
            "evidence": {"keyframe": media_url(ev.get("keyframe")), "clip": media_url(ev.get("clip")),
                         "frames": [media_url(f) for f in ev.get("frames", [])]},
            "status": e.status, "verification": e.verification or {}, "incident_id": e.incident_id,
            "is_demo": bool(e.is_demo)}


def incident_dict(i: Incident) -> dict:
    return {"id": i.id, "created_at": _ts(i.created_at), "updated_at": _ts(i.updated_at), "title": i.title,
            "type": i.type, "severity": i.severity, "status": i.status, "camera_id": i.camera_id,
            "summary": i.summary, "conclusion": i.conclusion or {}, "confidence": i.confidence,
            "identity_ids": i.identity_ids or [], "report_md": i.report_md, "notes": i.notes or [],
            "assigned_to": i.assigned_to, "is_demo": bool(i.is_demo)}


def run_dict(r: AgentRun) -> dict:
    return {"id": r.id, "agent": r.agent, "trigger": r.trigger, "incident_id": r.incident_id, "event_id": r.event_id,
            "status": r.status, "model": r.model, "started_at": _ts(r.started_at), "finished_at": _ts(r.finished_at),
            "steps": r.steps or [], "output": r.output or {}, "error": r.error}
