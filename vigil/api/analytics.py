from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from vigil.config import get_settings
from vigil.db import Camera, Event, Identity, Incident, Track, Zone, get_db, utcnow
from vigil.security import Principal, current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _bucket(dt, tz, hours: float) -> str:
    local = dt.astimezone(tz)
    if hours <= 48:
        return local.strftime("%Y-%m-%dT%H:00")
    return local.strftime("%Y-%m-%d")


@router.get("/overview")
async def overview(hours: float = 24, camera_id: str | None = None, demo: str = "include",
                   _: Principal = Depends(current_user), db=Depends(get_db)):
    from vigil.db import demo_filter
    tz = ZoneInfo(get_settings().timezone)
    since = utcnow() - timedelta(hours=hours)
    tq = select(Track.started_at, Track.identity_id, Track.camera_id, Track.duration_s).where(Track.started_at >= since)
    eq = select(Event.ts, Event.type, Event.severity, Event.status).where(Event.ts >= since)
    if camera_id:
        tq = tq.where(Track.camera_id == camera_id)
        eq = eq.where(Event.camera_id == camera_id)
    tq, eq = demo_filter(tq, Track, demo), demo_filter(eq, Event, demo)
    tracks = (await db.execute(tq)).all()
    events = (await db.execute(eq)).all()
    open_inc = (await db.execute(demo_filter(select(func.count()).select_from(Incident).where(
        Incident.status.in_(["new", "investigating", "confirmed"])), Incident, demo))).scalar_one()
    n_ident = (await db.execute(demo_filter(select(func.count()).select_from(Identity).where(
        Identity.merged_into.is_(None)), Identity, demo))).scalar_one()
    watch = (await db.execute(demo_filter(select(func.count()).select_from(Identity).where(
        Identity.frs_criminal_id.is_not(None)), Identity, demo))).scalar_one()
    series: dict[str, dict] = {}
    for st, _, _, _ in tracks:
        b = series.setdefault(_bucket(st, tz, hours), {"sightings": 0, "events": 0})
        b["sightings"] += 1
    by_type: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for ts, typ, sev, stt in events:
        series.setdefault(_bucket(ts, tz, hours), {"sightings": 0, "events": 0})["events"] += 1
        by_type[typ] = by_type.get(typ, 0) + 1
        by_sev[sev] = by_sev.get(sev, 0) + 1
        by_status[stt] = by_status.get(stt, 0) + 1
    by_cam: dict[str, int] = {}
    for _, _, c, _ in tracks:
        by_cam[c] = by_cam.get(c, 0) + 1
    dwell = [d for *_, d in tracks if d > 0]
    return {
        "hours": hours, "sightings": len(tracks), "unique_identities": len({i for _, i, _, _ in tracks if i}),
        "identified_share": round(sum(1 for _, i, _, _ in tracks if i) / len(tracks), 3) if tracks else 0.0,
        "events": len(events), "open_incidents": open_inc, "identities_total": n_ident, "watchlist_identities": watch,
        "events_by_type": by_type, "events_by_severity": by_sev, "events_by_status": by_status,
        "sightings_by_camera": by_cam,
        "series": [{"bucket": k, **v} for k, v in sorted(series.items())],
        "dwell": {"median_s": round(float(np.median(dwell)), 1) if dwell else 0,
                  "p90_s": round(float(np.percentile(dwell, 90)), 1) if dwell else 0,
                  "histogram": _hist(dwell)},
    }


def _hist(values: list[float]) -> list[dict]:
    edges = [0, 5, 15, 30, 60, 120, 300, 600, 1800, float("inf")]
    labels = ["<5s", "5-15s", "15-30s", "30-60s", "1-2m", "2-5m", "5-10m", "10-30m", ">30m"]
    out = [{"bin": l, "count": 0} for l in labels]
    for v in values:
        for i in range(len(labels)):
            if edges[i] <= v < edges[i + 1]:
                out[i]["count"] += 1
                break
    return out


@router.get("/heatmap/{camera_id}")
async def heatmap(camera_id: str, _: Principal = Depends(current_user)):
    p = get_settings().data_dir / "heat" / f"{camera_id}.npy"
    if not p.exists():
        return {"camera_id": camera_id, "grid": None, "samples": 0}
    g = np.load(p)
    total = float(g.sum())
    mx = float(g.max()) or 1.0
    return {"camera_id": camera_id, "rows": g.shape[0], "cols": g.shape[1], "samples": int(total),
            "grid": np.round(np.sqrt(g / mx), 3).tolist()}


@router.get("/zones/{camera_id}")
async def zone_stats(camera_id: str, hours: float = 24, _: Principal = Depends(current_user), db=Depends(get_db)):
    zones = (await db.execute(select(Zone).where(Zone.camera_id == camera_id))).scalars().all()
    tracks = (await db.execute(select(Track.zones).where(Track.camera_id == camera_id,
                                                         Track.started_at >= utcnow() - timedelta(hours=hours)))).all()
    out = []
    for z in zones:
        d = [row[0].get(z.id) for row in tracks if row[0] and z.id in row[0]]
        out.append({"zone_id": z.id, "name": z.name, "kind": z.kind, "visits": len(d),
                    "total_dwell_s": round(sum(d), 1), "mean_dwell_s": round(float(np.mean(d)), 1) if d else 0,
                    "max_dwell_s": round(max(d), 1) if d else 0})
    return out


@router.get("/cameras")
async def camera_stats(hours: float = 24, demo: str = "include", _: Principal = Depends(current_user),
                       db=Depends(get_db)):
    from vigil.db import demo_filter
    since = utcnow() - timedelta(hours=hours)
    cams = (await db.execute(demo_filter(select(Camera), Camera, demo))).scalars().all()
    out = []
    for c in cams:
        n_tr = (await db.execute(select(func.count()).select_from(Track).where(Track.camera_id == c.id, Track.started_at >= since))).scalar_one()
        n_ev = (await db.execute(select(func.count()).select_from(Event).where(Event.camera_id == c.id, Event.ts >= since))).scalar_one()
        out.append({"camera_id": c.id, "name": c.name, "sightings": n_tr, "events": n_ev})
    return out


@router.get("/track-paths/{camera_id}")
async def track_paths(camera_id: str, hours: float = 1, limit: int = 200, _: Principal = Depends(current_user),
                      db=Depends(get_db)):
    if limit > 1000:
        raise HTTPException(400, "limit too high")
    rows = (await db.execute(select(Track.id, Track.identity_id, Track.path, Track.anomaly_score).where(
        Track.camera_id == camera_id, Track.started_at >= utcnow() - timedelta(hours=hours))
        .order_by(Track.started_at.desc()).limit(limit))).all()
    return [{"id": r[0], "identity_id": r[1], "path": [p[1:] for p in (r[2] or [])], "anomaly": r[3]} for r in rows]
