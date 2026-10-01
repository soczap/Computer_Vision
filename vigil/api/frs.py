"""FRS workspace: face recognition operations, backed by VIGIL's identity service and the port-8000 FRS
backend (read-only). Everything here is real data; demo rows are flagged `is_demo` and filterable."""
from __future__ import annotations

import base64
import time
from datetime import timedelta

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select

from vigil.analytics.identity import identities
from vigil.db import Event, FRSSearch, Identity, Track, get_db, utcnow
from vigil.frs_client import frs
from vigil.perception.engine import engine
from vigil.perception.models import hub
from vigil.security import Principal, current_user
from vigil.services import event_dict, frs_search_dict, identity_dict

router = APIRouter(prefix="/api/frs", tags=["frs"])


def _pct(d: dict | None) -> dict | None:
    if not d:
        return None
    return {k: d.get(k) for k in ("p50", "p95", "p99", "count")}


@router.get("/overview")
async def overview(_: Principal = Depends(current_user), db=Depends(get_db)):
    since = utcnow() - timedelta(hours=24)
    # VIGIL side
    n_ids = (await db.execute(select(func.count()).select_from(Identity).where(
        Identity.merged_into.is_(None), Identity.is_demo.is_(False)))).scalar_one()
    n_enrolled = (await db.execute(select(func.count()).select_from(Identity).where(
        Identity.kind == "enrolled", Identity.is_demo.is_(False)))).scalar_one()
    n_watch = (await db.execute(select(func.count()).select_from(Identity).where(
        Identity.frs_criminal_id.is_not(None), Identity.is_demo.is_(False)))).scalar_one()
    rows = (await db.execute(select(FRSSearch.outcome, FRSSearch.latency_ms).where(FRSSearch.ts >= since))).all()
    lat = [r[1] for r in rows if r[1] is not None and r[0] != "error"]
    by_outcome: dict[str, int] = {}
    for o, _l in rows:
        by_outcome[o] = by_outcome.get(o, 0) + 1
    appear = (await db.execute(select(func.count()).select_from(Track).where(
        Track.started_at >= since, Track.identity_id.is_not(None), Track.is_demo.is_(False)))).scalar_one()
    face_w = hub().status().get("face", {})
    svc = identities()
    vigil = {
        "identities": n_ids, "enrolled": n_enrolled, "unknown": n_ids - n_enrolled, "watchlist_candidates": n_watch,
        "gallery_vectors": len(svc._owner), "identified_appearances_24h": appear, "counters": svc.stats,
        "face_pipeline_ms": round(face_w["busy_s"] / face_w["calls"] * 1000, 1) if face_w.get("calls") else None,
        "face_on_gpu": face_w.get("gpu"),
        "frs_searches_24h": len(rows), "frs_searches_by_outcome": by_outcome,
        "frs_search_latency_ms": {"p50": round(float(np.percentile(lat, 50)), 1),
                                  "p95": round(float(np.percentile(lat, 95)), 1)} if lat else None,
        "thresholds": {"match": svc.s.face_match_threshold, "margin": svc.s.face_match_margin,
                       "min_face_px": svc.s.face_min_px, "min_quality": svc.s.face_min_quality},
    }
    # FRS backend side (read-only)
    backend: dict = {"url": frs().base, "reachable": False}
    try:
        h = await frs()._get("/api/health")
        st = await frs().stats()
        m = await frs().metrics()
        backend.update({
            "reachable": True, "status": h.get("status"), "gpu": h.get("settings", {}).get("gpu"),
            "gallery": {"subjects": st.get("criminals"), "embeddings": st.get("embeddings"),
                        "faiss_vectors": h.get("faiss_vectors"), "match_events": st.get("match_events"),
                        "detections_today": st.get("detections_today")},
            "recognition": h.get("recognition", {}),
            "thresholds": {k: h.get("settings", {}).get(k) for k in ("threshold", "open_set_z_min", "top_k")},
            "latency_ms": {"person_detect": _pct(m.get("detection_tracking", {}).get("person_detect_ms")),
                           "face_detect": _pct(m.get("detection_tracking", {}).get("face_detect_ms")),
                           "embed": _pct(m.get("inference", {}).get("embed_ms")),
                           "vector_search": _pct(m.get("vector_search", {}).get("query_ms"))},
            "analysed_fps": m.get("analysis", {}).get("station_analysed_fps"),
        })
    except Exception as e:  # noqa: BLE001
        backend["error"] = str(e)
    return {"vigil": vigil, "frs_backend": backend, "read_only": True}


def _thumb(jpg: bytes | None, size: int = 112) -> str | None:
    if not jpg:
        return None
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    s = size / max(h, w)
    img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    ok, b = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(b.tobytes()).decode() if ok else None


@router.get("/live")
async def live(_: Principal = Depends(current_user)):
    """People currently in view on every running camera, with their face-identity state."""
    svc = identities()
    now = time.time()
    out = []
    for cid, w in list(engine.workers.items()):
        for tr in list(w.tracks.values()):
            if (w.last_frame_ts or now) - tr.last_ts > 2.0:
                continue
            m = svc.meta.get(tr.identity_id) if tr.identity_id else None
            state = ("watchlist_candidate" if m and m.frs_criminal_id else "known" if m and m.kind == "enrolled"
                     else "new_identity" if tr.identity_method == "new" else "reidentified" if m else
                     "collecting" if tr.face_buf else "no_face")
            out.append({
                "camera_id": cid, "track_uid": tr.uid, "local_id": tr.local_id, "identity_id": tr.identity_id,
                "label": m.label if m else None, "display_name": m.display_name if m else None,
                "state": state, "locked": tr.identity_locked,
                "similarity": round(float(tr.identity_score), 3) if tr.identity_method == "face" else None,
                "face_observations": len(tr.face_buf), "best_face_quality": round(tr.best_face_q, 2),
                "best_face_px": round(tr.best_face_px),
                # searched against FRS: by this track, or earlier for the same identity (rate-limited per identity)
                "frs_searched": bool(tr.frs_submitted or (m and m.frs_checked_at)),
                "frs_checked_at": m.frs_checked_at if m and m.frs_checked_at else None,
                "watchlist": {"criminal_id": m.frs_criminal_id, "name": m.frs_name} if m and m.frs_criminal_id else None,
                "in_view_s": round(tr.duration, 1), "face": _thumb(tr.best_face_jpg),
            })
    return {"tracks": out, "cameras": {cid: w.stats()["status"] for cid, w in engine.workers.items()}}


@router.get("/searches")
async def searches(identity_id: str | None = None, outcome: str | None = None, limit: int = Query(50, le=500),
                   offset: int = 0, _: Principal = Depends(current_user), db=Depends(get_db)):
    stmt = select(FRSSearch)
    if identity_id:
        stmt = stmt.where(FRSSearch.identity_id == identity_id)
    if outcome:
        stmt = stmt.where(FRSSearch.outcome.in_(outcome.split(",")))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(desc(FRSSearch.ts)).limit(limit).offset(offset))).scalars().all()
    return {"total": total, "items": [frs_search_dict(r) for r in rows]}


@router.get("/history")
async def backend_history(limit: int = Query(50, le=200), _: Principal = Depends(current_user)):
    """The FRS backend's own match log (read-only). Rows VIGIL caused are flagged `by_vigil`."""
    try:
        rows = await frs().history(limit)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"FRS unreachable: {e}")
    out = []
    for r in rows:
        qp = r.get("query_image_path") or ""
        out.append({"id": r.get("id"), "created_at": r.get("created_at"), "outcome": r.get("outcome"),
                    "score": r.get("score"), "matched_criminal_id": r.get("matched_criminal_id"),
                    "by_vigil": "vigil_face_" in qp,
                    "query_url": ("/api/frs/media/" + qp.split("storage/", 1)[1]) if qp.startswith("storage/uploads/queries/") else None,
                    "top_k": [{"name": t.get("name"), "criminal_id": t.get("criminal_id"), "score": t.get("score"),
                               "image_url": ("/api/frs" + t["image_url"]) if t.get("image_url") else None}
                              for t in (r.get("top_k") or [])[:3]]})
    return out


@router.get("/criminals/{criminal_id}")
async def criminal(criminal_id: str, _: Principal = Depends(current_user), db=Depends(get_db)):
    try:
        rec = await frs().criminal(criminal_id)
        det = await frs().criminal_detections(criminal_id, limit=50)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"FRS unreachable: {e}")
    linked = (await db.execute(select(Identity).where(Identity.frs_criminal_id == criminal_id))).scalars().all()
    ours = (await db.execute(select(FRSSearch).where(FRSSearch.criminal_id == criminal_id)
                             .order_by(desc(FRSSearch.ts)).limit(20))).scalars().all()
    return {
        "id": rec.get("id"), "name": rec.get("name"), "group": rec.get("group"), "subgroup": rec.get("subgroup"),
        "metadata": rec.get("metadata", {}), "created_at": rec.get("created_at"),
        "images": [{"url": "/api/frs" + i["url"], "quality": i.get("quality_score")} for i in rec.get("images", [])
                   if i.get("url")],
        "frs_detections": [{"id": d.get("id"), "camera_id": d.get("camera_id"), "time": d.get("created_at"),
                            "similarity": d.get("similarity"), "state": d.get("identity_state"),
                            "review": d.get("review_state"),
                            "thumb_url": ("/api/frs" + d["thumbnail_url"]) if d.get("thumbnail_url") else None}
                           for d in det.get("detections", [])],
        "vigil_identities": [identity_dict(i) for i in linked],
        "vigil_matches": [frs_search_dict(r) for r in ours],
        "read_only": True,
    }


@router.get("/feed")
async def feed(limit: int = Query(40, le=200), demo: str = "exclude", _: Principal = Depends(current_user),
               db=Depends(get_db)):
    """One timeline of face-recognition activity: identities created, FRS searches, watchlist events,
    and the FRS backend's own detections."""
    items: list[dict] = []
    ids = select(Identity).where(Identity.merged_into.is_(None))
    evq = select(Event).where(Event.type == "watchlist_match")
    if demo == "exclude":
        ids = ids.where(Identity.is_demo.is_(False))
        evq = evq.where(Event.is_demo.is_(False))
    elif demo == "only":
        ids = ids.where(Identity.is_demo.is_(True))
        evq = evq.where(Event.is_demo.is_(True))
    for i in (await db.execute(ids.order_by(desc(Identity.created_at)).limit(limit))).scalars():
        items.append({"kind": "identity_created" if i.kind == "unknown" else "identity_enrolled",
                      "ts": i.created_at.isoformat(), "identity_id": i.id, "label": i.display_name or i.id,
                      "face_url": f"/media/{i.best_face_path}" if i.best_face_path else None, "is_demo": i.is_demo})
    if demo != "only":
        for r in (await db.execute(select(FRSSearch).order_by(desc(FRSSearch.ts)).limit(limit))).scalars():
            items.append({"kind": "frs_search", **frs_search_dict(r), "is_demo": False})
    for e in (await db.execute(evq.order_by(desc(Event.ts)).limit(limit))).scalars():
        items.append({"kind": "watchlist_event", **event_dict(e)})
    if demo != "only":
        try:
            d = await frs().detections(limit=min(limit, 50))
            for x in d.get("detections", []):
                items.append({"kind": "frs_backend_detection", "ts": x.get("created_at"), "name": x.get("name"),
                              "criminal_id": x.get("criminal_id"), "detection_kind": x.get("kind"),
                              "camera_id": x.get("camera_id"), "similarity": x.get("similarity"),
                              "state": x.get("identity_state"), "review": x.get("review_state"),
                              "thumb_url": ("/api/frs" + x["thumbnail_url"]) if x.get("thumbnail_url") else None,
                              "is_demo": False})
        except Exception:  # noqa: BLE001
            pass

    def key(it):
        t = it.get("ts") or ""
        return t if "+" in t or t.endswith("Z") else t + "+00:00"
    items.sort(key=key, reverse=True)
    return items[:limit]
