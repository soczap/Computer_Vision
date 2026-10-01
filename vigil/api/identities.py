from __future__ import annotations

import asyncio
from datetime import timedelta

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select, update

from vigil.agents.tools import identity_timeline, search_people_by_description, find_similar_appearance
from vigil.analytics.identity import IdentityMeta, identities
from vigil.bus import bus
from vigil.config import get_settings
from vigil.db import Event, FaceVector, Identity, Track, demo_filter, get_db, involves, utcnow
from vigil.perception.models import face_embed_image, hub
from vigil.security import Principal, audit, current_user, require
from vigil.services import event_dict, identity_dict, track_dict

router = APIRouter(prefix="/api", tags=["identities"])
CATEGORIES = ("none", "staff", "vip", "watch", "banned")


@router.get("/identities")
async def list_identities(q: str | None = None, kind: str | None = None, category: str | None = None,
                          watchlist: bool | None = None, sort: str = "last_seen", limit: int = Query(60, le=500),
                          offset: int = 0, demo: str = "include", _: Principal = Depends(current_user),
                          db=Depends(get_db)):
    stmt = demo_filter(select(Identity).where(Identity.merged_into.is_(None)), Identity, demo)
    if q:
        stmt = stmt.where(Identity.id.ilike(f"%{q}%") | Identity.display_name.ilike(f"%{q}%") |
                          Identity.frs_name.ilike(f"%{q}%"))
    if kind:
        stmt = stmt.where(Identity.kind == kind)
    if category:
        stmt = stmt.where(Identity.category == category)
    if watchlist is not None:
        stmt = stmt.where(Identity.frs_criminal_id.is_not(None) if watchlist else Identity.frs_criminal_id.is_(None))
    order = {"last_seen": desc(Identity.last_seen), "sightings": desc(Identity.sightings),
             "created": desc(Identity.created_at)}.get(sort, desc(Identity.last_seen))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(order.nulls_last()).limit(limit).offset(offset))).scalars().all()
    return {"total": total, "items": [identity_dict(i) for i in rows]}


@router.get("/identities/{identity_id}")
async def get_identity(identity_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    i = await db.get(Identity, identity_id)
    if i is None:
        raise HTTPException(404, "identity not found")
    tracks = (await db.execute(select(Track).where(Track.identity_id == identity_id)
                               .order_by(desc(Track.started_at)).limit(100))).scalars().all()
    nvec = (await db.execute(select(func.count()).select_from(FaceVector).where(FaceVector.identity_id == identity_id))).scalar_one()
    evs = (await db.execute(select(Event).where(involves(identity_id)).order_by(desc(Event.ts)).limit(50))).scalars().all()
    d = identity_dict(i)
    d["face_vectors"] = nvec
    d["tracks"] = [track_dict(t, with_path=True) for t in tracks]
    d["events"] = [event_dict(e) for e in evs]
    cams: dict[str, dict] = {}
    for t in tracks:
        c = cams.setdefault(t.camera_id, {"camera_id": t.camera_id, "sightings": 0, "dwell_s": 0.0})
        c["sightings"] += 1
        c["dwell_s"] += t.duration_s
    d["cameras"] = sorted(cams.values(), key=lambda c: -c["sightings"])
    from vigil.db import FRSSearch
    from vigil.services import frs_search_dict
    d["frs_searches"] = [frs_search_dict(r) for r in (await db.execute(
        select(FRSSearch).where(FRSSearch.identity_id == identity_id).order_by(desc(FRSSearch.ts)).limit(30))).scalars()]
    d["appearances"] = len(tracks)
    return d


class IdentityPatch(BaseModel):
    display_name: str | None = None
    category: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


@router.patch("/identities/{identity_id}")
async def patch_identity(identity_id: str, body: IdentityPatch, p: Principal = Depends(require("analyst")),
                         db=Depends(get_db)):
    i = await db.get(Identity, identity_id)
    if i is None:
        raise HTTPException(404, "identity not found")
    if body.category is not None and body.category not in CATEGORIES:
        raise HTTPException(400, f"category must be one of {CATEGORIES}")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    if body.display_name:
        i.kind = "enrolled"
    await db.commit()
    m = identities().meta.get(identity_id)
    if m:
        m.display_name, m.category, m.kind = i.display_name, i.category, i.kind
    await audit(p.username, "identity.update", identity_id, **body.model_dump(exclude_unset=True))
    return identity_dict(i)


@router.post("/identities/enroll")
async def enroll(name: str = Form(...), category: str = Form("none"), notes: str | None = Form(None),
                 files: list[UploadFile] = File(...), p: Principal = Depends(require("analyst")), db=Depends(get_db)):
    """Enrol a named person from photos. If they were already seen as an unknown P-xxxxx, that identity is
    upgraded in place (keeps their history) instead of creating a duplicate."""
    if category not in CATEGORIES:
        raise HTTPException(400, f"category must be one of {CATEGORIES}")
    svc = identities()
    faces, warnings = [], []
    for f in files[:10]:
        img = cv2.imdecode(np.frombuffer(await f.read(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            warnings.append(f"{f.filename}: not an image")
            continue
        found = await asyncio.wrap_future(hub().face.submit(face_embed_image, img))
        if not found:
            warnings.append(f"{f.filename}: no face found")
            continue
        if len(found) > 1:
            warnings.append(f"{f.filename}: {len(found)} faces; used the largest")
        fo = found[0]
        if fo.size_px < 60 or fo.quality < 0.35:
            warnings.append(f"{f.filename}: face too small or low quality ({fo.size_px:.0f}px, q={fo.quality:.2f})")
            continue
        faces.append((fo, f.filename))
    if not faces:
        raise HTTPException(400, {"message": "no usable face in the uploaded photos", "warnings": warnings})
    # consistency: all photos must be the same person
    embs = [fo.embedding for fo, _ in faces]
    for a in range(len(embs)):
        for b in range(a + 1, len(embs)):
            if float(embs[a] @ embs[b]) < 0.25:
                raise HTTPException(400, {"message": f"photos {faces[a][1]} and {faces[b][1]} look like different "
                                                     f"people (cosine {float(embs[a] @ embs[b]):.2f})",
                                          "warnings": warnings})
    pooled = identities().pooled([(fo.quality, fo.embedding) for fo, _ in faces])
    ranked = svc.search(pooled)
    s = get_settings()
    target = None
    if ranked and ranked[0][1] >= s.face_match_threshold:
        existing = await db.get(Identity, ranked[0][0])
        if existing is not None and existing.kind == "enrolled" and existing.display_name != name:
            raise HTTPException(409, {"message": f"these photos match already-enrolled {existing.display_name} "
                                                 f"({existing.id}, cosine {ranked[0][1]:.2f})", "warnings": warnings})
        target = existing
    merged = target is not None
    if target is None:
        target = Identity(id=svc.next_id(), kind="enrolled", created_at=utcnow())
        db.add(target)
    target.display_name, target.kind, target.category = name, "enrolled", category
    if notes:
        target.notes = notes
    best = max(faces, key=lambda x: x[0].quality)[0]
    face_rel = f"faces/{target.id}_enrol.jpg"
    cv2.imwrite(str(s.media_dir / face_rel), best.chip if best.chip is not None else np.zeros((112, 112, 3), np.uint8))
    enrol_dir = s.media_dir / "enroll" / target.id
    enrol_dir.mkdir(parents=True, exist_ok=True)
    if not target.best_face_path or best.quality >= (target.best_face_quality or 0):
        target.best_face_path, target.best_face_quality = face_rel, best.quality
    await db.flush()
    for fo, fname in faces:
        db.add(FaceVector(identity_id=target.id, vector=fo.embedding.astype(np.float32).tobytes(),
                          quality=fo.quality, source="enrollment", image_path=fname))
    await db.commit()
    meta = svc.meta.get(target.id) or IdentityMeta(target.id, name, "enrolled", category)
    meta.display_name, meta.kind, meta.category = name, "enrolled", category
    svc.meta[target.id] = meta
    svc._add_vectors(target.id, embs)
    await audit(p.username, "identity.enroll", target.id, name=name, photos=len(faces), merged_existing=merged)
    bus.publish("identity.created", {"id": target.id, "enrolled": True})
    return {"identity": identity_dict(target), "photos_used": len(faces), "merged_existing_unknown": merged,
            "match_score": round(ranked[0][1], 3) if merged else None, "warnings": warnings}


class MergeIn(BaseModel):
    into: str


@router.post("/identities/{identity_id}/merge")
async def merge(identity_id: str, body: MergeIn, p: Principal = Depends(require("analyst")), db=Depends(get_db)):
    """Operator says two IDs are the same person: move history + vectors into `into`."""
    if identity_id == body.into:
        raise HTTPException(400, "cannot merge into itself")
    src, dst = await db.get(Identity, identity_id), await db.get(Identity, body.into)
    if src is None or dst is None:
        raise HTTPException(404, "identity not found")
    if src.is_demo != dst.is_demo:
        raise HTTPException(400, "cannot merge demo and real identities")
    await db.execute(update(FaceVector).where(FaceVector.identity_id == src.id).values(identity_id=dst.id))
    await db.execute(update(Track).where(Track.identity_id == src.id).values(identity_id=dst.id))
    src.merged_into = dst.id
    dst.sightings = (dst.sightings or 0) + (src.sightings or 0)
    if src.first_seen and (dst.first_seen is None or src.first_seen < dst.first_seen):
        dst.first_seen = src.first_seen
    if src.last_seen and (dst.last_seen is None or src.last_seen > dst.last_seen):
        dst.last_seen, dst.last_camera_id = src.last_seen, src.last_camera_id
    await db.commit()
    identities().reassign(src.id, dst.id)
    await audit(p.username, "identity.merge", src.id, into=dst.id)
    return identity_dict(dst)


@router.delete("/identities/{identity_id}")
async def delete_identity(identity_id: str, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    i = await db.get(Identity, identity_id)
    if i is None:
        raise HTTPException(404, "identity not found")
    await db.execute(delete(FaceVector).where(FaceVector.identity_id == identity_id))
    await db.execute(update(Track).where(Track.identity_id == identity_id).values(identity_id=None))
    await db.delete(i)
    await db.commit()
    identities().remove_identity(identity_id)
    await audit(p.username, "identity.delete", identity_id)
    return {"ok": True}


@router.get("/identities/{identity_id}/timeline")
async def timeline(identity_id: str, hours: float = 24, _: Principal = Depends(current_user)):
    return await identity_timeline(identity_id, hours)


@router.post("/identities/{identity_id}/check-watchlist")
async def check_watchlist(identity_id: str, p: Principal = Depends(require("analyst")), db=Depends(get_db)):
    """Force one FRS search with this identity's best face (FRS records every search)."""
    from vigil.frs_client import frs
    i = await db.get(Identity, identity_id)
    if i is None or not i.best_face_path:
        raise HTTPException(404, "identity has no face image")
    if i.is_demo:
        raise HTTPException(400, "demo identities are never searched against FRS")
    path = get_settings().media_dir / i.best_face_path
    jpeg = path.read_bytes()
    res = await asyncio.to_thread(frs().match_face_sync, jpeg)
    from vigil.services import record_frs_search
    await record_frs_search(res, identity_id, i.last_camera_id, None, jpeg, "manual")
    i.frs_checked_at = utcnow()
    if res and res["matched"]:
        i.frs_criminal_id, i.frs_name, i.frs_score = res["criminal_id"], res["name"], res["score"]
        m = identities().meta.get(identity_id)
        if m:
            m.frs_criminal_id, m.frs_name = res["criminal_id"], res["name"]
    await db.commit()
    await audit(p.username, "identity.check_watchlist", identity_id, matched=bool(res and res["matched"]))
    return {"result": res, "identity": identity_dict(i)}


# ── tracks & search ──
@router.get("/tracks")
async def list_tracks(camera_id: str | None = None, identity_id: str | None = None, hours: float = 24,
                      limit: int = Query(100, le=1000), demo: str = "include", _: Principal = Depends(current_user),
                      db=Depends(get_db)):
    stmt = demo_filter(select(Track).where(Track.started_at >= utcnow() - timedelta(hours=hours)), Track, demo)
    if camera_id:
        stmt = stmt.where(Track.camera_id == camera_id)
    if identity_id:
        stmt = stmt.where(Track.identity_id == identity_id)
    rows = (await db.execute(stmt.order_by(desc(Track.started_at)).limit(limit))).scalars().all()
    return [track_dict(t) for t in rows]


@router.get("/tracks/{track_id}")
async def get_track(track_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    t = await db.get(Track, track_id)
    if t is None:
        raise HTTPException(404, "track not found")
    return track_dict(t, with_path=True)


class SearchIn(BaseModel):
    text: str | None = None
    track_id: str | None = None
    hours: float = 24
    camera_id: str | None = None
    limit: int = 24


@router.post("/search/appearance")
async def search_appearance(body: SearchIn, _: Principal = Depends(current_user)):
    if body.text:
        return await search_people_by_description(body.text, body.hours, body.camera_id, body.limit)
    if body.track_id:
        return await find_similar_appearance(body.track_id, body.hours, body.limit)
    raise HTTPException(400, "text or track_id required")
