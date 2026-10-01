from __future__ import annotations

import re
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from vigil.config import get_settings
from vigil.db import Camera, Zone, get_db
from vigil.frs_client import frs
from vigil.perception.engine import engine
from vigil.security import Principal, audit, current_user, require
from vigil.services import camera_dict, zone_dict

router = APIRouter(prefix="/api", tags=["cameras"])
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
VIDEO_EXT = {".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm", ".ts"}


class CameraIn(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    source_type: str = Field(pattern="^(frs|rtsp|http|file|browser)$")
    source_uri: str = Field(min_length=1)
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    enabled: bool = True
    loop: bool = False
    realtime: bool = True
    analysis_fps: float | None = Field(default=None, ge=1, le=30)
    config: dict = Field(default_factory=dict)


class CameraPatch(BaseModel):
    name: str | None = None
    source_uri: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    enabled: bool | None = None
    loop: bool | None = None
    realtime: bool | None = None
    analysis_fps: float | None = Field(default=None, ge=1, le=30)
    config: dict | None = None


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="monitored", pattern="^(restricted|monitored|entry)$")
    polygon: list[list[float]]
    rules: dict = Field(default_factory=dict)
    enabled: bool = True


def _validate_polygon(poly: list[list[float]]) -> None:
    if len(poly) < 3 or any(len(p) != 2 or not (0 <= p[0] <= 1 and 0 <= p[1] <= 1) for p in poly):
        raise HTTPException(400, "polygon needs >=3 points, normalised to 0..1")


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-")[:48] or "cam"


@router.get("/cameras")
async def list_cameras(demo: str = "include", _: Principal = Depends(current_user), db=Depends(get_db)):
    from vigil.db import demo_filter
    stats = engine.stats()
    stmt = demo_filter(select(Camera).order_by(Camera.created_at), Camera, demo)
    return [camera_dict(c, stats.get(c.id)) for c in (await db.execute(stmt)).scalars()]


@router.get("/cameras/{camera_id}")
async def get_camera(camera_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    c = await db.get(Camera, camera_id)
    if c is None:
        raise HTTPException(404, "camera not found")
    zones = (await db.execute(select(Zone).where(Zone.camera_id == camera_id))).scalars().all()
    d = camera_dict(c, engine.stats().get(camera_id))
    d["zones"] = [zone_dict(z) for z in zones]
    return d


@router.post("/cameras")
async def create_camera(body: CameraIn, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    cid = body.id or _slug(body.name)
    if not _ID.match(cid):
        raise HTTPException(400, "camera id may contain letters, digits, _ . - only")
    if await db.get(Camera, cid):
        raise HTTPException(409, "camera id exists")
    if body.source_type == "file":
        from pathlib import Path
        root = (get_settings().media_dir / "uploads").resolve()
        if not Path(body.source_uri).resolve().is_relative_to(root):
            raise HTTPException(400, "file sources must be uploaded via /api/cameras/upload")
    c = Camera(id=cid, **body.model_dump(exclude={"id"}))
    db.add(c)
    await db.commit()
    await audit(p.username, "camera.create", cid, source_type=body.source_type)
    if c.enabled:
        await engine.start(cid)
    return camera_dict(c)


@router.patch("/cameras/{camera_id}")
async def patch_camera(camera_id: str, body: CameraPatch, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    c = await db.get(Camera, camera_id)
    if c is None:
        raise HTTPException(404, "camera not found")
    if c.is_demo and body.enabled:
        raise HTTPException(400, "demo cameras are synthetic and have no stream")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    await db.commit()
    await audit(p.username, "camera.update", camera_id, fields=list(body.model_dump(exclude_unset=True)))
    if c.enabled:
        await engine.start(camera_id)
    else:
        await engine.stop(camera_id)
    return camera_dict(c)


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    c = await db.get(Camera, camera_id)
    if c is None:
        raise HTTPException(404, "camera not found")
    await engine.stop(camera_id)
    await db.delete(c)
    await db.commit()
    await audit(p.username, "camera.delete", camera_id)
    return {"ok": True}


@router.post("/cameras/{camera_id}/start")
async def start_camera(camera_id: str, p: Principal = Depends(require("analyst"))):
    if not await engine.start(camera_id):
        raise HTTPException(400, "camera missing or disabled")
    await audit(p.username, "camera.start", camera_id)
    return {"ok": True}


@router.post("/cameras/{camera_id}/stop")
async def stop_camera(camera_id: str, p: Principal = Depends(require("analyst"))):
    await engine.stop(camera_id)
    await audit(p.username, "camera.stop", camera_id)
    return {"ok": True}


@router.get("/cameras/{camera_id}/snapshot")
async def snapshot(camera_id: str, _: Principal = Depends(current_user)):
    w = engine.worker(camera_id)
    if w is None or not w.recorder.ring:
        raise HTTPException(404, "no frame yet")
    return Response(w.recorder.ring[-1][1], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/cameras/upload")
async def upload_video(file: UploadFile = File(...), name: str = Form(...), realtime: bool = Form(False),
                       loop: bool = Form(False), location: str | None = Form(None),
                       p: Principal = Depends(require("analyst")), db=Depends(get_db)):
    import os
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, f"unsupported video type {ext}")
    dest = get_settings().media_dir / "uploads" / f"{uuid.uuid4().hex}{ext}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh, length=1 << 20)
    cid = f"upload-{_slug(name)}-{uuid.uuid4().hex[:4]}"
    c = Camera(id=cid, name=name, source_type="file", source_uri=str(dest), location=location or "Uploaded video",
               loop=loop, realtime=realtime, config={"uploaded_filename": file.filename})
    db.add(c)
    await db.commit()
    await audit(p.username, "video.upload", cid, filename=file.filename)
    await engine.start(cid)
    return camera_dict(c)


@router.post("/demo/webcam")
async def demo_webcam(p: Principal = Depends(require("analyst")), db=Depends(get_db)):
    """Create (or restart) this operator's browser-webcam camera. Frames come from the browser via
    /ws/ingest/{id}; the camera runs the same pipeline as any other source."""
    cid = f"webcam-{_slug(p.username)}"
    c = await db.get(Camera, cid)
    if c is None:
        c = Camera(id=cid, name=f"Laptop webcam ({p.username})", source_type="browser", source_uri="browser",
                   location="Operator browser (demo / local camera)", analysis_fps=10.0,
                   config={"demo_camera": True})
        db.add(c)
        await audit(p.username, "camera.webcam_create", cid)
    c.enabled = True
    await db.commit()
    w = engine.worker(cid)
    if w is None or not w.is_alive():
        await engine.start(cid)
    return camera_dict(c, engine.stats().get(cid))


@router.get("/demo/data")
async def demo_status(_: Principal = Depends(current_user)):
    from vigil import demo
    return await demo.status()


@router.post("/demo/data")
async def demo_generate(hours: int = 24, p: Principal = Depends(require("admin"))):
    """Create clearly-labelled synthetic data (replaces any previous demo data; never touches real rows)."""
    from vigil import demo
    out = await demo.generate(hours=max(1, min(hours, 168)))
    await audit(p.username, "demo.generate", None, **out["generated"])
    return out


@router.delete("/demo/data")
async def demo_clear(p: Principal = Depends(require("admin"))):
    from vigil import demo
    out = await demo.clear()
    await audit(p.username, "demo.clear", None, **out["removed"])
    return out


# ── zones ──
@router.get("/cameras/{camera_id}/zones")
async def list_zones(camera_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    return [zone_dict(z) for z in (await db.execute(select(Zone).where(Zone.camera_id == camera_id))).scalars()]


@router.post("/cameras/{camera_id}/zones")
async def create_zone(camera_id: str, body: ZoneIn, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    if await db.get(Camera, camera_id) is None:
        raise HTTPException(404, "camera not found")
    _validate_polygon(body.polygon)
    z = Zone(camera_id=camera_id, **body.model_dump())
    db.add(z)
    await db.commit()
    await audit(p.username, "zone.create", z.id, camera=camera_id, kind=body.kind)
    await engine.reload(camera_id)
    return zone_dict(z)


@router.patch("/zones/{zone_id}")
async def patch_zone(zone_id: str, body: dict, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    z = await db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(404, "zone not found")
    for k in ("name", "kind", "polygon", "rules", "enabled"):
        if k in body:
            if k == "polygon":
                _validate_polygon(body[k])
            setattr(z, k, body[k])
    await db.commit()
    await audit(p.username, "zone.update", zone_id)
    await engine.reload(z.camera_id)
    return zone_dict(z)


@router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: str, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    z = await db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(404, "zone not found")
    cam = z.camera_id
    await db.delete(z)
    await db.commit()
    await audit(p.username, "zone.delete", zone_id)
    await engine.reload(cam)
    return {"ok": True}


# ── FRS camera import (read-only use of port 8000) ──
@router.get("/frs/cameras")
async def frs_cameras(_: Principal = Depends(current_user)):
    try:
        cams = await frs().cameras()
        stats = await frs().camera_stats()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"FRS unreachable: {e}")
    live = {c["camera_id"]: c for c in stats.get("cameras", [])}
    for c in cams:
        s = live.get(c["id"], {})
        c["running_in_frs"] = bool(s.get("connected"))
        c["frs_fps"] = s.get("fps")
        c["native_resolution"] = s.get("resolution")
    return cams


@router.post("/frs/cameras/{frs_camera_id}/import")
async def import_frs_camera(frs_camera_id: str, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    cams = {c["id"]: c for c in await frs().cameras()}
    fc = cams.get(frs_camera_id)
    if fc is None:
        raise HTTPException(404, "FRS camera not found")
    cid = f"frs-{_slug(frs_camera_id)}"
    if await db.get(Camera, cid):
        raise HTTPException(409, "already imported")
    c = Camera(id=cid, name=fc.get("name") or frs_camera_id, source_type="frs", source_uri=frs_camera_id,
               location=fc.get("location"), latitude=fc.get("latitude"), longitude=fc.get("longitude"))
    db.add(c)
    await db.commit()
    await audit(p.username, "camera.import_frs", cid, frs_camera=frs_camera_id)
    await engine.start(cid)
    return camera_dict(c)
