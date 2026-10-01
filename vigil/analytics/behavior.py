"""Behaviour engine: rule-based, explainable detectors over tracks, zones and objects.

Every signal carries the measured values and the thresholds they crossed, so
an operator (or the investigating agent) can see *why* it fired.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from vigil.analytics.signals import Signal
from vigil.config import get_settings
from vigil.perception.models import BAG_LABELS, WEAPON_LABELS, ObjectDet

log = logging.getLogger("vigil.behavior")
GRID_W, GRID_H = 48, 27


@dataclass
class ZoneDef:
    id: str
    name: str
    kind: str  # restricted | monitored | entry
    polygon: list  # normalised
    rules: dict = field(default_factory=dict)
    _px: np.ndarray | None = None
    _wh: tuple[int, int] | None = None

    def contains(self, x: float, y: float, W: int, H: int) -> bool:
        if self._wh != (W, H):
            self._px = (np.array(self.polygon, np.float32) * np.array([W, H], np.float32)).reshape(-1, 1, 2)
            self._wh = (W, H)
        return cv2.pointPolygonTest(self._px, (float(x), float(y)), False) >= 0


@dataclass
class TrackedObject:
    label: str
    box: tuple
    first_ts: float
    last_ts: float
    hits: int = 1
    owner_uid: str | None = None
    unattended_since: float | None = None
    anchor: tuple | None = None
    fired: bool = False


class OccupancyModel:
    """Online foot-point occupancy histogram per camera, used for path anomaly and heatmaps."""

    def __init__(self, camera_id: str) -> None:
        self.path = get_settings().data_dir / "heat" / f"{camera_id}.npy"
        self.path.parent.mkdir(exist_ok=True)
        self.grid = np.load(self.path) if self.path.exists() else np.zeros((GRID_H, GRID_W), np.float64)
        self.dirty = 0

    @property
    def samples(self) -> float:
        return float(self.grid.sum())

    def cell(self, xn: float, yn: float) -> tuple[int, int]:
        return min(GRID_H - 1, max(0, int(yn * GRID_H))), min(GRID_W - 1, max(0, int(xn * GRID_W)))

    def add(self, xn: float, yn: float) -> None:
        r, c = self.cell(xn, yn)
        self.grid[r, c] += 1
        self.dirty += 1
        if self.dirty >= 500:
            self.save()

    def save(self) -> None:
        # Slow decay so the model tracks layout changes over weeks.
        self.grid *= 0.999
        tmp = Path(str(self.path) + ".tmp.npy")
        np.save(tmp, self.grid)
        tmp.replace(self.path)
        self.dirty = 0

    def rarity_percentile(self, xn: float, yn: float) -> float:
        """Share (%) of historical traffic that falls in cells at most as busy as this one."""
        r, c = self.cell(xn, yn)
        v = self.grid[r, c]
        tot = self.grid.sum()
        if tot <= 0:
            return 100.0
        return float(self.grid[self.grid <= v].sum() / tot * 100.0)


class BehaviorEngine:
    def __init__(self, camera_id: str, rules: dict, zones: list[ZoneDef], tz: str) -> None:
        self.camera_id = camera_id
        self.rules = rules
        self.zones = zones
        self.tz = ZoneInfo(tz)
        self.objects: list[TrackedObject] = []
        self.weapon_hits: list[tuple[float, ObjectDet]] = []
        self.crowd_since: float | None = None
        self.crowd_fired_ts = float("-inf")
        self.zone_over_since: dict[str, float] = {}
        self.occupancy = OccupancyModel(camera_id)
        self.cooldown_s = get_settings().event_cooldown_s
        self._last_after_hours: float = 0.0

    # helpers
    def _r(self, name: str) -> dict:
        return self.rules.get(name, {})

    def _cool(self, tr, etype: str, ts: float, cooldown: float | None = None) -> bool:
        last = tr.fired.get(etype)
        if last is not None and ts - last < (cooldown or self.cooldown_s * 4):
            return False
        tr.fired[etype] = ts
        return True

    def _sig(self, etype, sev, conf, title, desc, ts, tracks, expl, boxes=None, verify=False) -> Signal:
        return Signal(type=etype, severity=sev, confidence=round(float(conf), 3), title=title, description=desc,
                      camera_id=self.camera_id, ts=ts, track_uids=[t.uid for t in tracks],
                      identity_ids=[t.identity_id for t in tracks if t.identity_id],
                      explanation=expl, boxes=boxes or [[*map(float, t.box), f"#{t.local_id}"] for t in tracks],
                      verify=verify)

    def _who(self, tr, labels: dict) -> str:
        return labels.get(tr.identity_id, tr.identity_id) if tr.identity_id else f"track #{tr.local_id}"

    # ── main entry ──
    def update(self, ts: float, tracks: list, objects: list[ObjectDet] | None, W: int, H: int,
               labels: dict) -> list[Signal]:
        out: list[Signal] = []
        for tr in tracks:
            fx, fy = tr.foot
            if tr.frames % 3 == 0:
                self.occupancy.add(fx / W, fy / H)
            self._zones(tr, ts, W, H, labels, out)
            self._running(tr, ts, labels, out)
            self._fall(tr, ts, labels, out)
            self._loiter(tr, ts, labels, out)
            self._pacing(tr, ts, labels, out)
            self._anomalous_path(tr, ts, W, H, labels, out)
        self._crowd(tracks, ts, out)
        self._occupancy(tracks, ts, W, H, out)
        self._after_hours(tracks, ts, labels, out)
        if objects is not None:
            self._objects(objects, tracks, ts, out)
        return out

    # ── rules ──
    def _zones(self, tr, ts, W, H, labels, out) -> None:
        fx, fy = tr.foot
        now_in = {z.id for z in self.zones if z.contains(fx, fy, W, H)}
        for zid in now_in - tr.zones_now:
            tr.zone_enter[zid] = ts
            z = next(z for z in self.zones if z.id == zid)
            r = self._r("zone_intrusion")
            if z.kind == "restricted" and r.get("enabled") and self._in_schedule(z) and \
                    self._cool(tr, f"zone_intrusion:{zid}", ts):
                who = self._who(tr, labels)
                out.append(self._sig(
                    "zone_intrusion", z.rules.get("severity", r["severity"]), 0.9,
                    f"{who} entered restricted zone '{z.name}'",
                    f"Foot point of {who} crossed into the restricted polygon '{z.name}'.",
                    ts, [tr], {"rule": "zone_intrusion", "zone": z.name, "zone_id": zid,
                               "foot_point_norm": [round(fx / W, 3), round(fy / H, 3)],
                               "reasoning": "Restricted zones alert on any entry while their schedule is active."}))
        for zid in tr.zones_now - now_in:
            enter = tr.zone_enter.pop(zid, None)
            if enter is not None:
                tr.zone_dwell[zid] = tr.zone_dwell.get(zid, 0.0) + (ts - enter)
        tr.zones_now = now_in

    def _in_schedule(self, z: ZoneDef) -> bool:
        sch = z.rules.get("schedule")  # {"start":"20:00","end":"06:00"}
        if not sch:
            return True
        now = datetime.now(self.tz).strftime("%H:%M")
        a, b = sch.get("start", "00:00"), sch.get("end", "23:59")
        return a <= now <= b if a <= b else (now >= a or now <= b)

    def _running(self, tr, ts, labels, out) -> None:
        r = self._r("running")
        if not r.get("enabled") or tr.duration < 1.5:
            return
        if tr.speed_ema >= r["speed_bh_s"] and tr.height > 60:
            tr.fired.setdefault("_run_start", ts)
            dur = ts - tr.fired["_run_start"]
            if dur >= r["min_duration_s"] and self._cool(tr, "running", ts):
                who = self._who(tr, labels)
                out.append(self._sig(
                    "running", r["severity"], min(0.5 + (tr.speed_ema - r["speed_bh_s"]) / 4, 0.95),
                    f"{who} running", f"{who} moved at {tr.speed_ema:.1f} body-heights/s for {dur:.1f}s.",
                    ts, [tr], {"rule": "running", "speed_bh_per_s": round(tr.speed_ema, 2),
                               "threshold_bh_per_s": r["speed_bh_s"], "sustained_s": round(dur, 1),
                               "reasoning": "Walking is ~0.6-1.3 body-heights/s; sustained >2.2 is running."}))
        else:
            tr.fired.pop("_run_start", None)

    def _fall(self, tr, ts, labels, out) -> None:
        r = self._r("fall")
        if not r.get("enabled"):
            return
        ang = tr.torso_angle()
        x1, y1, x2, y2 = tr.box
        aspect = (x2 - x1) / max(y2 - y1, 1)
        lying = (ang is not None and ang >= r["torso_deg"] and aspect > 0.9) or (ang is None and aspect > 1.6)
        if not lying:
            tr.down_since = None
            tr.upright_last = ts
            tr.posture = "upright"
            return
        if tr.down_since is None:
            tr.down_since = ts
        tr.posture = "down"
        down = ts - tr.down_since
        # A fall = was upright recently, now down and staying down.
        was_upright = tr.upright_last > 0 and (tr.down_since - tr.upright_last) < 3.0
        if down >= r["min_down_s"] and self._cool(tr, "fall", ts, cooldown=300):
            who = self._who(tr, labels)
            conf = 0.75 if was_upright else 0.6
            out.append(self._sig(
                "fall", r["severity"], conf, f"{who} down" + (" after a fall" if was_upright else ""),
                f"{who} has been horizontal for {down:.1f}s (torso {ang if ang is not None else 'n/a'}°, "
                f"box aspect {aspect:.2f}).", ts, [tr],
                {"rule": "fall", "torso_angle_deg": None if ang is None else round(ang, 1),
                 "box_aspect_w_over_h": round(aspect, 2), "down_for_s": round(down, 1),
                 "upright_before": was_upright, "threshold_deg": r["torso_deg"],
                 "reasoning": "Torso axis near horizontal with a wide box, sustained; preceded by upright posture."},
                verify=True))

    def _loiter(self, tr, ts, labels, out) -> None:
        r = self._r("loitering")
        if not r.get("enabled"):
            return
        # Per-zone loiter thresholds override the scene default.
        zone_thr = [(z, z.rules.get("loiter_s")) for z in self.zones if z.id in tr.zones_now and z.rules.get("loiter_s")]
        dwell_s = min([t for _, t in zone_thr], default=r["dwell_s"])
        if tr.duration < dwell_s:
            return
        rg = tr.radius_of_gyration(dwell_s)
        if rg <= r["max_radius"] and self._cool(tr, "loitering", ts, cooldown=max(dwell_s * 2, 300)):
            who = self._who(tr, labels)
            where = f" in '{zone_thr[0][0].name}'" if zone_thr else ""
            out.append(self._sig(
                "loitering", r["severity"], min(0.55 + (tr.duration - dwell_s) / (4 * dwell_s), 0.9),
                f"{who} loitering{where}", f"{who} stayed{where} for {tr.duration:.0f}s within a radius of "
                f"{rg:.2f} (frame-normalised).", ts, [tr],
                {"rule": "loitering", "dwell_s": round(tr.duration, 1), "threshold_s": dwell_s,
                 "radius_of_gyration": round(rg, 3), "max_radius": r["max_radius"],
                 "reasoning": "Long presence with little net displacement."}))

    def _pacing(self, tr, ts, labels, out) -> None:
        r = self._r("pacing")
        if not r.get("enabled") or tr.duration > r["window_s"] * 3:
            return
        if tr.reversals >= r["reversals"] and tr.duration >= r.get("min_duration_s", 30) and \
                self._cool(tr, "pacing", ts, 600):
            who = self._who(tr, labels)
            out.append(self._sig(
                "pacing", r["severity"], 0.55, f"{who} pacing back and forth",
                f"{who} reversed horizontal direction {tr.reversals} times in {tr.duration:.0f}s.", ts, [tr],
                {"rule": "pacing", "direction_reversals": tr.reversals, "threshold": r["reversals"],
                 "duration_s": round(tr.duration, 1),
                 "reasoning": "Repeated back-and-forth movement can indicate casing or agitation."}))

    def _anomalous_path(self, tr, ts, W, H, labels, out) -> None:
        r = self._r("anomalous_path")
        if not r.get("enabled") or self.occupancy.samples < r["min_samples"] or len(tr.path) < 6:
            return
        if tr.frames % 12:
            return
        pts = tr.path[-12:]
        pct = [self.occupancy.rarity_percentile(x, y) for _, x, y in pts]
        rare = sum(p <= r["percentile"] for p in pct)
        tr.anomaly = rare / len(pct)
        if rare >= max(4, len(pct) // 2) and self._cool(tr, "anomalous_path", ts, 600):
            who = self._who(tr, labels)
            out.append(self._sig(
                "anomalous_path", r["severity"], 0.5 + 0.4 * tr.anomaly, f"{who} on an unusual path",
                f"{rare} of the last {len(pct)} positions of {who} lie in areas carrying under "
                f"{r['percentile']}% of this camera's historical foot traffic.", ts, [tr],
                {"rule": "anomalous_path", "rare_points": rare, "window_points": len(pct),
                 "traffic_percentile_threshold": r["percentile"], "model_samples": int(self.occupancy.samples),
                 "reasoning": "Unsupervised occupancy model learned from this camera's own history."}))

    def _crowd(self, tracks, ts, out) -> None:
        r = self._r("crowd")
        if not r.get("enabled") or len(tracks) < r["min_people"]:
            self.crowd_since = None
            return
        med_h = float(np.median([t.height for t in tracks]))
        centers = np.array([t.foot for t in tracks])
        d = np.linalg.norm(centers[:, None] - centers[None], axis=-1)
        neigh = (d <= r["radius_bh"] * med_h).sum(1)
        k = int(neigh.max())
        if k < r["min_people"]:
            self.crowd_since = None
            return
        self.crowd_since = self.crowd_since or ts
        dur = ts - self.crowd_since
        if dur >= r["min_duration_s"] and ts - self.crowd_fired_ts > self.cooldown_s * 6:
            self.crowd_fired_ts = ts
            members = [tracks[i] for i in np.where(d[int(neigh.argmax())] <= r["radius_bh"] * med_h)[0]]
            out.append(self._sig(
                "crowd", r["severity"], min(0.5 + (k - r["min_people"]) * 0.08, 0.9),
                f"Crowd of {k} gathering", f"{k} people within {r['radius_bh']} body-heights of each other "
                f"for {dur:.0f}s.", ts, members,
                {"rule": "crowd", "cluster_size": k, "min_people": r["min_people"], "sustained_s": round(dur, 1),
                 "reasoning": "Dense cluster persisting beyond the configured duration."}))

    def _occupancy(self, tracks, ts, W, H, out) -> None:
        r = self._r("occupancy")
        if not r.get("enabled"):
            return
        for z in self.zones:
            cap = z.rules.get("max_occupancy")
            if not cap:
                continue
            inside = [t for t in tracks if z.id in t.zones_now]
            if len(inside) > cap:
                since = self.zone_over_since.setdefault(z.id, ts)
                if ts - since >= 5 and ts - self.zone_over_since.get(f"{z.id}:fired", float("-inf")) > self.cooldown_s * 4:
                    self.zone_over_since[f"{z.id}:fired"] = ts
                    out.append(self._sig(
                        "occupancy", r["severity"], 0.8, f"'{z.name}' over capacity ({len(inside)}/{cap})",
                        f"{len(inside)} people in '{z.name}', limit {cap}.", ts, inside,
                        {"rule": "occupancy", "zone": z.name, "count": len(inside), "max_occupancy": cap}))
            else:
                self.zone_over_since.pop(z.id, None)

    def _after_hours(self, tracks, ts, labels, out) -> None:
        r = self._r("after_hours")
        if not r.get("enabled") or not tracks:
            return
        now = datetime.fromtimestamp(ts, self.tz).strftime("%H:%M")
        if r["open"] <= now < r["close"]:
            return
        for tr in tracks:
            if tr.duration >= 3 and self._cool(tr, "after_hours", ts, 1800):
                who = self._who(tr, labels)
                out.append(self._sig(
                    "after_hours", r["severity"], 0.7, f"{who} present after hours",
                    f"{who} observed at {now}, outside operating hours {r['open']}-{r['close']}.", ts, [tr],
                    {"rule": "after_hours", "local_time": now, "open": r["open"], "close": r["close"]}))

    def _objects(self, objects: list[ObjectDet], tracks, ts, out) -> None:
        # weapons: sustained, overlapping a person
        rw = self._r("weapon")
        self.weapon_hits = [(t, o) for t, o in self.weapon_hits if ts - t < 3.0]
        for o in objects:
            if o.label in WEAPON_LABELS:
                holder = self._overlapping_person(o.box, tracks)
                if holder is not None:
                    self.weapon_hits.append((ts, o))
        if rw.get("enabled") and len(self.weapon_hits) >= rw["min_hits"]:
            o = max(self.weapon_hits, key=lambda h: h[1].conf)[1]
            holder = self._overlapping_person(o.box, tracks)
            if holder is not None and self._cool(holder, "weapon", ts, 120):
                out.append(self._sig(
                    "weapon", rw["severity"], min(o.conf + 0.1, 0.95), f"Possible {o.label} held by track #{holder.local_id}",
                    f"A {o.label} was detected overlapping a person in {len(self.weapon_hits)} object passes "
                    f"within 3s (max conf {o.conf:.2f}).", ts, [holder],
                    {"rule": "weapon", "object": o.label, "detections_3s": len(self.weapon_hits),
                     "max_conf": round(o.conf, 3), "reasoning": "Repeated detection on a person, pending visual verification."},
                    boxes=[[*o.box, o.label], [*map(float, holder.box), f"#{holder.local_id}"]], verify=True))
                self.weapon_hits.clear()
        # bags: persistence + ownership
        ra = self._r("abandoned_object")
        bags = [o for o in objects if o.label in BAG_LABELS]
        for b in bags:
            m = max(self.objects, key=lambda t: _iou(t.box, b.box), default=None)
            if m is not None and _iou(m.box, b.box) > 0.3:
                m.box, m.last_ts, m.hits = b.box, ts, m.hits + 1
            else:
                owner = self._nearest_person(b.box, tracks)
                self.objects.append(TrackedObject(b.label, b.box, ts, ts, owner_uid=owner.uid if owner else None,
                                                  anchor=_center(b.box)))
        self.objects = [o for o in self.objects if ts - o.last_ts < 20]
        if not ra.get("enabled"):
            return
        for o in self.objects:
            if o.fired or o.hits < 5:
                continue
            cx, cy = _center(o.box)
            if o.anchor and math.hypot(cx - o.anchor[0], cy - o.anchor[1]) > (o.box[3] - o.box[1]) * 0.5:
                o.anchor, o.unattended_since = (cx, cy), None  # it moved: carried, not abandoned
                continue
            near = self._nearest_person(o.box, tracks)
            attended = near is not None and math.hypot(near.center[0] - cx, near.center[1] - cy) <= \
                ra["owner_radius_bh"] * near.height
            if attended:
                o.unattended_since = None
                continue
            o.unattended_since = o.unattended_since or ts
            if ts - o.unattended_since >= ra["unattended_s"]:
                o.fired = True
                owner = next((t for t in tracks if t.uid == o.owner_uid), None)
                sig = self._sig(
                    "abandoned_object", ra["severity"], 0.7, f"Unattended {o.label}",
                    f"A {o.label} has been stationary with nobody within {ra['owner_radius_bh']} body-heights "
                    f"for {ts - o.unattended_since:.0f}s (seen {ts - o.first_ts:.0f}s total).", ts,
                    [owner] if owner else [],
                    {"rule": "abandoned_object", "object": o.label, "unattended_s": round(ts - o.unattended_since, 1),
                     "threshold_s": ra["unattended_s"], "first_seen_s_ago": round(ts - o.first_ts, 1),
                     "owner_track": o.owner_uid,
                     "reasoning": "Object persisted in place after the nearest person moved away."},
                    boxes=[[*o.box, o.label]], verify=True)
                out.append(sig)

    @staticmethod
    def _overlapping_person(box, tracks):
        best, bi = None, 0.0
        for t in tracks:
            inter = _inter(box, t.box)
            a = (box[2] - box[0]) * (box[3] - box[1]) + 1e-6
            if inter / a > bi:
                best, bi = t, inter / a
        return best if bi > 0.3 else None

    @staticmethod
    def _nearest_person(box, tracks):
        cx, cy = _center(box)
        return min(tracks, key=lambda t: math.hypot(t.center[0] - cx, t.center[1] - cy), default=None)


def _center(b) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _inter(a, b) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return w * h


def _iou(a, b) -> float:
    i = _inter(a, b)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0
