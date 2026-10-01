from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from sqlalchemy import desc, select, text

from vigil.agents.llm import llm
from vigil.agents.orchestrator import orchestrator
from vigil.analytics.identity import identities
from vigil.bus import bus
from vigil.config import get_settings
from vigil.db import AuditLog, get_db, session
from vigil.frs_client import frs
from vigil.perception.engine import engine
from vigil.perception.models import hub
from vigil.security import Principal, current_user, media_user, require

router = APIRouter(tags=["system"])
STARTED = time.time()


def _gpu() -> dict:
    try:
        import torch
        free, total = torch.cuda.mem_get_info()
        return {"available": True, "name": torch.cuda.get_device_name(0), "free_gb": round(free / 1e9, 1),
                "total_gb": round(total / 1e9, 1), "torch_allocated_gb": round(torch.cuda.memory_allocated() / 1e9, 2)}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)}


@router.get("/api/health")
async def health():
    """Liveness: the process answers. No auth, no dependencies."""
    return {"status": "ok", "uptime_s": round(time.time() - STARTED)}


@router.get("/api/ready")
async def ready():
    """Readiness: DB answers and every model worker initialised."""
    checks = {}
    try:
        async with session() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {e}"
    ms = hub().status()
    checks["models"] = "ok" if all(v.get("ready") for v in ms.values()) else "loading"
    ok = checks["database"] == "ok" and checks["models"] == "ok"
    return Response(content=__import__("json").dumps({"ready": ok, "checks": checks}), media_type="application/json",
                    status_code=200 if ok else 503)


@router.get("/api/system/status")
async def status(_: Principal = Depends(current_user)):
    ms = hub().status()
    return {
        "uptime_s": round(time.time() - STARTED), "gpu": _gpu(), "models": ms,
        "face_gpu": ms.get("face", {}).get("gpu"), "cameras": engine.stats(),
        "frs": await frs().health(), "frs_match_calls": frs().match_calls, "llm": await llm().health(),
        "llm_stats": llm().stats, "orchestrator": orchestrator().stats, "identity": identities().stats,
        "gallery": {"identities": len(identities().meta), "vectors": len(identities()._owner)},
        "bus_dropped": bus.dropped,
    }


class _Collector:
    def collect(self):
        g = GaugeMetricFamily("vigil_camera_fps", "Analysis FPS per camera", labels=["camera"])
        a = GaugeMetricFamily("vigil_camera_active_tracks", "Active tracks per camera", labels=["camera"])
        lat = GaugeMetricFamily("vigil_camera_latency_ms", "Per-frame processing latency", labels=["camera"])
        up = GaugeMetricFamily("vigil_camera_running", "1 if the camera loop is running", labels=["camera"])
        for cid, s in engine.stats().items():
            g.add_metric([cid], s.get("fps") or 0)
            a.add_metric([cid], s.get("active_tracks") or 0)
            lat.add_metric([cid], s.get("latency_ms") or 0)
            up.add_metric([cid], 1 if s.get("status") == "running" else 0)
        yield from (g, a, lat, up)
        w = GaugeMetricFamily("vigil_model_queue", "Model worker queue depth", labels=["worker"])
        b = GaugeMetricFamily("vigil_model_busy_seconds", "Cumulative busy time", labels=["worker"])
        for name, s in hub().status().items():
            w.add_metric([name], s.get("queue", 0))
            b.add_metric([name], s.get("busy_s", 0))
        yield from (w, b)
        o = GaugeMetricFamily("vigil_orchestrator_total", "Orchestrator counters", labels=["counter"])
        for k, v in orchestrator().stats.items():
            o.add_metric([k], v)
        yield o
        i = GaugeMetricFamily("vigil_identity_total", "Identity service counters", labels=["counter"])
        for k, v in identities().stats.items():
            i.add_metric([k], v)
        yield i


REGISTRY.register(_Collector())


@router.get("/metrics")
async def metrics(request: Request):
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1"):
        await require("admin")(await current_user(request))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/audit")
async def audit_log(limit: int = 200, _: Principal = Depends(require("admin")), db=Depends(get_db)):
    rows = (await db.execute(select(AuditLog).order_by(desc(AuditLog.ts)).limit(min(limit, 1000)))).scalars().all()
    return [{"ts": r.ts.isoformat(), "actor": r.actor, "action": r.action, "target": r.target, "details": r.details}
            for r in rows]


@router.get("/api/frs/status")
async def frs_status(_: Principal = Depends(current_user)):
    return {**(await frs().health()), "url": frs().base, "match_calls_made": frs().match_calls}


@router.get("/api/frs/criminals")
async def frs_criminals(_: Principal = Depends(current_user)):
    try:
        return await frs().criminals()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"FRS unreachable: {e}")


@router.get("/api/frs/media/{path:path}")
async def frs_media(path: str, _: Principal = Depends(media_user)):
    import httpx
    try:
        body, ctype = await frs().media("/media/" + path)
    except ValueError:
        raise HTTPException(403, "not proxyable")
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        raise HTTPException(404 if code == 404 else 502, "not found on FRS" if code == 404 else f"FRS error {code}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"FRS unreachable: {e}")
    return Response(body, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/media/{path:path}")
async def media(path: str, _: Principal = Depends(media_user)):
    root = get_settings().media_dir.resolve()
    p = (root / path).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise HTTPException(404, "not found")
    if p.is_relative_to(root / "uploads"):
        raise HTTPException(403, "raw uploads are not served")
    return FileResponse(p, headers={"Cache-Control": "private, max-age=86400"})


