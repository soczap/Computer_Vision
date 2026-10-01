"""Synthetic demo data for exercising dashboards when no real camera activity exists.

Guarantees (so demo can never be mistaken for, or leak into, real operations):
- every row has is_demo=True; ids are prefixed (cameras `demo-`, identities `D-`)
- every image is generated (no real faces) and watermarked "SYNTHETIC DEMO DATA"
- demo cameras have source_type "demo" and never run; demo identities have no face vectors, so they are
  never loaded into the matching gallery; the orchestrator and agents never see demo rows
- one call removes all of it (`clear`)
"""
from __future__ import annotations


import random
import shutil
from datetime import timedelta

import cv2
import numpy as np
from sqlalchemy import delete, select

from vigil.config import get_settings
from vigil.db import Camera, Event, Identity, Incident, Track, Zone, new_id, session, utcnow

WATERMARK = "SYNTHETIC DEMO DATA"
CAMERAS = [
    ("demo-main-gate", "DEMO · Main Gate", "Demo site / perimeter"),
    ("demo-lobby", "DEMO · Reception Lobby", "Demo site / ground floor"),
    ("demo-parking", "DEMO · Parking Bay", "Demo site / basement"),
    ("demo-corridor", "DEMO · 2F Corridor", "Demo site / second floor"),
]
NAMED = [("Demo Officer A", "staff"), ("Demo Officer B", "staff"), ("Demo Clerk C", "staff"),
         ("Demo Visitor D", "vip"), ("Demo Contractor E", "none")]
PALETTE = [(94, 129, 244), (72, 187, 120), (237, 137, 54), (159, 122, 234), (56, 178, 172), (236, 72, 153),
           (234, 179, 8), (99, 102, 241)]


def _media():
    d = get_settings().media_dir / "demo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, h - 30), (w, h), (20, 20, 160), -1)
    cv2.putText(img, WATERMARK, (10, h - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return img


def _avatar(ident: str, label: str, color) -> str:
    img = np.full((160, 160, 3), 32, np.uint8)
    cv2.circle(img, (80, 66), 46, color, -1)
    initials = "".join(p[0] for p in label.replace("Demo", "").split()[:2]).upper() or ident[-2:]
    (tw, th), _ = cv2.getTextSize(initials, cv2.FONT_HERSHEY_SIMPLEX, 1.3, 3)
    cv2.putText(img, initials, (80 - tw // 2, 66 + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 3)
    cv2.putText(img, "DEMO", (52, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 220), 2)
    rel = f"demo/{ident}.jpg"
    if not cv2.imwrite(str(_media() / f"{ident}.jpg"), img):  # imwrite fails silently without the folder
        raise RuntimeError(f"could not write demo avatar {rel}")
    return rel


def _scene(event_id: str, title: str, boxes: list[tuple], seed: int) -> str:
    rng = np.random.default_rng(seed)
    h, w = 540, 960
    img = np.zeros((h, w, 3), np.uint8)
    top = np.array([70, 60, 55]) + rng.integers(0, 30, 3)
    for y in range(h):
        img[y] = (top * (1 - y / h) + np.array([130, 125, 120]) * (y / h)).astype(np.uint8)
    cv2.line(img, (0, int(h * .55)), (w, int(h * .5)), (90, 90, 90), 2)
    for (x1, y1, x2, y2, lbl) in boxes:
        cv2.rectangle(img, (x1 + 8, y1 + 8), (x2 - 8, y2), (150, 150, 160), -1)
        cv2.circle(img, ((x1 + x2) // 2, y1 + 4), max(8, (x2 - x1) // 5), (170, 170, 180), -1)
        cv2.rectangle(img, (x1, y1 - 20), (x2, y2), (40, 40, 235), 2)
        cv2.putText(img, lbl, (x1, y1 - 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(img, title[:70], (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    _stamp(img)
    d = _media() / "evidence" / event_id
    d.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(d / "key.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85]):
        raise RuntimeError(f"could not write demo keyframe for {event_id}")
    return f"demo/evidence/{event_id}/key.jpg"


def _path(rng: random.Random, n: int) -> list:
    x, y = rng.uniform(0.1, 0.9), rng.uniform(0.55, 0.95)
    vx, vy = rng.uniform(-0.02, 0.02), rng.uniform(-0.01, 0.01)
    out = []
    for i in range(n):
        vx = 0.85 * vx + rng.gauss(0, 0.006)
        vy = 0.85 * vy + rng.gauss(0, 0.003)
        x = min(0.98, max(0.02, x + vx))
        y = min(0.98, max(0.45, y + vy))
        out.append([round(i * 0.5, 1), round(x, 4), round(y, 4)])
    return out


EVENT_SPECS = {
    "loitering": ("medium", 0.72, "{who} loitering near {cam}",
                  lambda r: {"rule": "loitering", "dwell_s": round(r.uniform(95, 400), 1), "threshold_s": 90,
                             "radius_of_gyration": round(r.uniform(0.02, 0.1), 3), "max_radius": 0.12}),
    "zone_intrusion": ("high", 0.9, "{who} entered restricted zone 'Server Room'",
                       lambda r: {"rule": "zone_intrusion", "zone": "Server Room",
                                  "foot_point_norm": [round(r.uniform(.5, .9), 3), round(r.uniform(.6, .9), 3)]}),
    "running": ("low", 0.66, "{who} running",
                lambda r: {"rule": "running", "speed_bh_per_s": round(r.uniform(2.3, 3.8), 2),
                           "threshold_bh_per_s": 2.2, "sustained_s": round(r.uniform(1, 3), 1)}),
    "fall": ("high", 0.75, "{who} down after a fall",
             lambda r: {"rule": "fall", "torso_angle_deg": round(r.uniform(65, 88), 1), "box_aspect_w_over_h": 1.3,
                        "down_for_s": round(r.uniform(2, 9), 1), "upright_before": True, "threshold_deg": 60}),
    "crowd": ("medium", 0.7, "Crowd of {n} gathering",
              lambda r: {"rule": "crowd", "cluster_size": r.randint(5, 11), "min_people": 5,
                         "sustained_s": round(r.uniform(8, 60), 1)}),
    "abandoned_object": ("high", 0.7, "Unattended backpack",
                         lambda r: {"rule": "abandoned_object", "object": "backpack",
                                    "unattended_s": round(r.uniform(46, 200), 1), "threshold_s": 45}),
    "after_hours": ("medium", 0.7, "{who} present after hours",
                    lambda r: {"rule": "after_hours", "local_time": f"{r.randint(0, 5):02d}:{r.randint(0, 59):02d}",
                               "open": "07:00", "close": "21:00"}),
    "pacing": ("low", 0.55, "{who} pacing back and forth",
               lambda r: {"rule": "pacing", "direction_reversals": r.randint(6, 12), "threshold": 6,
                          "duration_s": round(r.uniform(40, 150), 1)}),
    "violence": ("critical", 0.88, "Possible fight: {who} and another person",
                 lambda r: {"rule": "violence_cascade",
                            "stage2_videomae": {"logit": round(r.uniform(6, 10), 2), "logit_threshold": 4.0},
                            "stage1_pose": {"wrist_speed_bh_s": round(r.uniform(2.5, 5), 2),
                                            "contact_rate": round(r.uniform(.3, .8), 2)},
                            "fusion": {"fused": round(r.uniform(.86, .98), 3), "rule": "instant"}}),
    "repeated_appearance": ("medium", 0.66, "{who} seen {n} times in 60 min",
                            lambda r: {"rule": "repeated_appearance", "visits": r.randint(4, 7), "threshold": 4,
                                       "window_min": 60}),
    "watchlist_match": ("critical", 0.61, "Watchlist candidate: DEMO Subject X ({who})",
                        lambda r: {"rule": "frs_watchlist", "frs_similarity": round(r.uniform(.45, .7), 3),
                                   "note": "synthetic: no FRS search was made"}),
}
TYPE_WEIGHTS = {"loitering": 10, "running": 8, "pacing": 6, "zone_intrusion": 4, "after_hours": 4, "crowd": 3,
                "fall": 2, "abandoned_object": 2, "repeated_appearance": 3, "violence": 1, "watchlist_match": 1}


async def status() -> dict:
    from sqlalchemy import func
    out = {}
    async with session() as db:
        for name, model in (("cameras", Camera), ("identities", Identity), ("tracks", Track), ("events", Event),
                            ("incidents", Incident)):
            out[name] = (await db.execute(select(func.count()).select_from(model).where(model.is_demo.is_(True)))).scalar_one()
    out["present"] = any(v for v in out.values())
    return out


async def clear() -> dict:
    counts = await status()
    async with session() as db:
        cams = [c.id for c in (await db.execute(select(Camera).where(Camera.is_demo.is_(True)))).scalars()]
        if cams:
            await db.execute(delete(Zone).where(Zone.camera_id.in_(cams)))
        for model in (Event, Incident, Track, Identity, Camera):
            await db.execute(delete(model).where(model.is_demo.is_(True)))
        await db.commit()
    shutil.rmtree(get_settings().media_dir / "demo", ignore_errors=True)
    for cid, *_ in CAMERAS:
        (get_settings().data_dir / "heat" / f"{cid}.npy").unlink(missing_ok=True)
    counts.pop("present", None)
    return {"removed": counts}


async def generate(hours: int = 24, seed: int = 7) -> dict:
    await clear()
    rng = random.Random(seed)
    now = utcnow()
    heat_dir = get_settings().data_dir / "heat"
    heat_dir.mkdir(exist_ok=True)
    async with session() as db:
        for cid, name, loc in CAMERAS:
            db.add(Camera(id=cid, name=name, source_type="demo", source_uri="synthetic", location=loc,
                          enabled=False, is_demo=True, config={"demo": True}))
            g = np.zeros((27, 48))
            for _ in range(4):
                cy, cx = rng.uniform(14, 25), rng.uniform(5, 43)
                yy, xx = np.mgrid[:27, :48]
                g += rng.uniform(200, 900) * np.exp(-((yy - cy) ** 2 / 18 + (xx - cx) ** 2 / 60))
            np.save(heat_dir / f"{cid}.npy", g)
        await db.flush()
        db.add(Zone(camera_id="demo-corridor", name="Server Room", kind="restricted",
                    polygon=[[0.62, 0.55], [0.95, 0.55], [0.95, 0.98], [0.62, 0.98]], rules={"schedule": None}))
        db.add(Zone(camera_id="demo-lobby", name="Reception queue", kind="monitored",
                    polygon=[[0.1, 0.6], [0.5, 0.6], [0.5, 0.95], [0.1, 0.95]], rules={"loiter_s": 120, "max_occupancy": 6}))

        idents = []
        for i in range(16):
            iid = f"D-{i + 1:04d}"
            if i < len(NAMED):
                label, cat = NAMED[i]
                kind = "enrolled"
            else:
                label, cat, kind = iid, ("watch" if i in (9, 12) else "none"), "unknown"
            first = now - timedelta(hours=rng.uniform(2, hours))
            ident = Identity(id=iid, display_name=label if kind == "enrolled" else None, kind=kind, category=cat,
                             is_demo=True, first_seen=first, created_at=first,
                             best_face_path=_avatar(iid, label, PALETTE[i % len(PALETTE)]), best_face_quality=0.8,
                             notes="Synthetic demo identity." if kind == "unknown" else "Synthetic demo person.",
                             tags=["demo"])
            if i == 14:
                ident.frs_criminal_id, ident.frs_name, ident.frs_score = "DEMO-CRIM-001", "DEMO Subject X", 0.58
            db.add(ident)
            idents.append(ident)
        await db.flush()

        tracks = []
        for k in range(260):
            hrs_ago = hours * (1 - rng.betavariate(2.2, 1.6))
            start = now - timedelta(hours=hrs_ago)
            local = start.hour + 5.5
            if (local % 24) < 6 and rng.random() < 0.7:
                continue  # quieter nights
            cid = rng.choice(CAMERAS)[0]
            ident = rng.choice(idents) if rng.random() < 0.72 else None
            dur = min(900.0, rng.lognormvariate(3.2, 0.9))
            path = _path(rng, max(3, min(200, int(dur / 0.5))))
            t = Track(id=f"demo-{cid}-{k}", camera_id=cid, local_id=k, identity_id=ident.id if ident else None,
                      identity_score=round(rng.uniform(0.45, 0.8), 3) if ident else None,
                      identity_method="face" if ident else None, started_at=start,
                      ended_at=start + timedelta(seconds=dur), duration_s=round(dur, 1), path=path,
                      max_speed=round(rng.uniform(0.6, 3.2), 2), mean_speed=round(rng.uniform(0.3, 1.3), 2),
                      zones={}, closed=True, is_demo=True, attributes={"posture": "upright", "demo": True},
                      best_person_path=ident.best_face_path if ident else None)
            db.add(t)
            tracks.append(t)
            if ident:
                ident.sightings = (ident.sightings or 0) + 1
                if ident.last_seen is None or t.ended_at > ident.last_seen:
                    ident.last_seen, ident.last_camera_id = t.ended_at, cid
        await db.flush()

        events = []
        types = list(TYPE_WEIGHTS)
        for k in range(70):
            etype = rng.choices(types, weights=[TYPE_WEIGHTS[t] for t in types])[0]
            sev, conf, title_t, expl_f = EVENT_SPECS[etype]
            tr = rng.choice(tracks)
            ident = next((i for i in idents if i.id == tr.identity_id), None)
            if etype == "watchlist_match":
                ident = idents[14]
            who = (ident.display_name or ident.id) if ident else f"track #{tr.local_id}"
            title = title_t.format(who=who, cam=tr.camera_id, n=rng.randint(4, 9))
            expl = {**expl_f(rng), "demo": True, "reasoning": "Synthetic event for dashboard testing."}
            eid = new_id("evt")
            ev_status = rng.choices(["open", "verified", "needs_review", "vlm_rejected", "dismissed"],
                                 weights=[5, 3, 2, 1, 1])[0]
            ver = {}
            if etype in ("violence", "fall", "abandoned_object"):
                ver = {"verdict": {"verified": "confirmed", "vlm_rejected": "rejected"}.get(ev_status, "uncertain"),
                       "confidence": 0.9, "model": "demo", "observations": ["Synthetic observation (demo)."],
                       "reasoning": "Demo verification — no model was run."}
            boxes = [(rng.randint(80, 700), rng.randint(180, 280), 0, 0, f"#{tr.local_id}")]
            boxes = [(x, y, x + rng.randint(60, 110), y + rng.randint(160, 240), l) for x, y, _, _, l in boxes]
            ts = tr.started_at + timedelta(seconds=min(tr.duration_s, rng.uniform(1, 60)))
            ev = Event(id=eid, ts=ts, camera_id=tr.camera_id, type=etype, severity=sev,
                       confidence=round(conf + rng.uniform(-0.08, 0.08), 3), title=title,
                       description=f"[DEMO] {title}. Synthetic event generated for dashboard testing.",
                       track_ids=[tr.id], identity_ids=[ident.id] if ident else [], explanation=expl,
                       evidence={"keyframe": _scene(eid, f"[DEMO] {title}", boxes, k)}, status=ev_status,
                       verification=ver, is_demo=True)
            db.add(ev)
            events.append(ev)
        await db.flush()

        incidents = 0
        for etype in ("violence", "watchlist_match", "zone_intrusion", "fall", "abandoned_object"):
            evs = [e for e in events if e.type == etype][:3]
            if not evs:
                continue
            e0 = evs[0]
            assess = "real_threat" if etype in ("violence", "zone_intrusion") else "inconclusive"
            inc = Incident(title=f"[DEMO] {e0.title}", type=etype, severity=e0.severity, camera_id=e0.camera_id,
                           status=rng.choice(["new", "investigating", "confirmed", "resolved"]),
                           summary=f"Synthetic incident for dashboard testing ({etype}).",
                           confidence=0.8, identity_ids=e0.identity_ids, is_demo=True, created_at=e0.ts,
                           updated_at=e0.ts + timedelta(minutes=5),
                           conclusion={"summary": "DEMO conclusion — no agent was run. This incident is synthetic.",
                                       "assessment": assess, "threat_level": e0.severity, "confidence": 0.8,
                                       "key_evidence": [f"{e.id}: {e.title}" for e in evs],
                                       "recommended_actions": ["None — demo data"], "demo": True},
                           notes=[{"ts": now.isoformat(), "by": "demo-generator", "text": "Synthetic incident."}])
            db.add(inc)
            await db.flush()
            for e in evs:
                e.incident_id = inc.id
            incidents += 1
        await db.commit()
    s = await status()
    return {"generated": {k: v for k, v in s.items() if k != "present"}, "watermark": WATERMARK}


