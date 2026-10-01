"""CameraWorker: one thread per camera running the full perception loop.

frame -> pose (batched GPU) [+ objects every N] -> ByteTrack -> track states
      -> face jobs (async) -> identity resolution -> watchlist check (FRS, rate-limited)
      -> behaviour rules + violence cascade -> signals (+ evidence capture)
      -> live overlay stream (only while someone watches)
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from collections import deque
from types import SimpleNamespace

import cv2
import numpy as np

from vigil import runtime
from vigil.analytics.behavior import BehaviorEngine, ZoneDef
from vigil.analytics.identity import identities
from vigil.analytics.signals import Signal
from vigil.analytics.violence import ViolenceMonitor
from vigil.bus import bus
from vigil.config import get_settings
from vigil.db import new_id
from vigil.perception.models import BAG_LABELS, WEAPON_LABELS, clip_images, face_analyze, hub
from vigil.perception.recorder import Recorder
from vigil.perception.sources import SourceEnded, make_source
from vigil.perception.tracking import PersonTracker, TrackState

log = logging.getLogger("vigil.worker")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _jsonable(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o).__name__)


class LiveChannel:
    """Latest encoded overlay frame for WebSocket viewers (polled, never blocks the worker)."""

    def __init__(self) -> None:
        self.viewers = 0
        self.seq = 0
        self.payload: bytes | None = None
        self.header: bytes | None = None
        self.lock = threading.Lock()

    def set(self, payload: bytes, header: bytes | None = None) -> None:
        with self.lock:
            self.payload = payload
            self.header = header
            self.seq += 1


class CameraWorker(threading.Thread):
    def __init__(self, cam: dict, zones: list[dict], rules: dict) -> None:
        super().__init__(name=f"cam-{cam['id']}", daemon=True)
        s = get_settings()
        self.s = s
        self.cam = cam
        self.camera_id = cam["id"]
        self.fps = cam.get("analysis_fps") or s.analysis_fps
        self.zones = [ZoneDef(z["id"], z["name"], z["kind"], z["polygon"], z.get("rules") or {}) for z in zones]
        self.rules = rules
        self.behavior = BehaviorEngine(self.camera_id, rules, self.zones, s.timezone)
        self.violence = ViolenceMonitor(self.camera_id, rules)
        self.recorder = Recorder(self.camera_id)
        self.live = LiveChannel()
        self.tracks: dict[int, TrackState] = {}
        self.inject_q: queue.Queue = queue.Queue()
        self.is_browser = cam["source_type"] == "browser"
        self._halt = threading.Event()
        self.source = None
        self.status = "starting"
        self.frames = 0
        self.proc_times: deque = deque(maxlen=60)
        self.frame_ts: deque = deque(maxlen=60)
        self.last_frame_ts = 0.0
        self.counts = {"tracks_total": 0, "signals": 0, "faces": 0}
        self.face_job = None
        self.obj_last: list = []
        self.last_persist = 0.0
        self.resolution: tuple[int, int] | None = None
        self.finished = False
        self.last_objects: list = []
        self.stage_ms: dict[str, float] = {}
        # motion gate (GPU is shared with the FRS backend: idle scenes must cost ~nothing)
        self.motion_ref: np.ndarray | None = None
        self.motion_ref_ts = 0.0
        self.last_motion_ts = 0.0
        self.motion = 0.0
        self.idle = False
        self.last_idle_probe = 0.0
        self.skipped = 0
        self.last_live_ts = 0.0

    def _mark(self, name: str, t0: float) -> float:
        t = time.perf_counter()
        self.stage_ms[name] = round(0.9 * self.stage_ms.get(name, (t - t0) * 1000) + 0.1 * (t - t0) * 1000, 1)
        return t

    # ── control ──
    def stop(self) -> None:
        self._halt.set()
        if self.source:
            self.source.stop()

    def inject(self, sig: Signal, track_uid: str | None = None) -> None:
        """Signals produced outside the loop (e.g. FRS watchlist) get evidence from the next frame."""
        self.inject_q.put((sig, track_uid))

    def stats(self) -> dict:
        pt = list(self.proc_times)
        ft = list(self.frame_ts)
        fps = (len(ft) - 1) / (ft[-1] - ft[0]) if len(ft) > 2 and ft[-1] > ft[0] else 0.0
        src = self.source
        return {
            "camera_id": self.camera_id, "status": self.status, "fps": round(fps, 1),
            "latency_ms": round(float(np.mean(pt)) * 1000, 1) if pt else None,
            "active_tracks": len(self.tracks), "frames": self.frames, "resolution": self.resolution,
            "viewers": self.live.viewers, "source_connected": getattr(src, "connected", False),
            "source_error": getattr(src, "last_error", None), "reconnects": getattr(src, "reconnects", 0),
            "progress": getattr(src, "progress", None), "violence": self.violence.last, "stage_ms": self.stage_ms,
            "idle": self.idle, "motion": round(self.motion, 4), "skipped_frames": self.skipped,
            **self.counts,
        }

    # ── main loop ──
    def run(self) -> None:
        try:
            self.source = make_source(SimpleNamespace(**self.cam))
            self.source.start()
        except Exception as e:  # noqa: BLE001
            self.status = f"error: {e}"
            log.exception("camera %s failed to start", self.camera_id)
            return
        self.tracker = PersonTracker(self.fps)
        live_src = self.cam["source_type"] != "file"
        self.is_browser = self.cam["source_type"] == "browser"
        min_gap = 1.0 / self.fps * 0.92
        last = 0.0
        self.status = "connecting"
        while not self._halt.is_set():
            try:
                f = self.source.read(timeout=2.0)
            except SourceEnded:
                self.status = "finished"
                self.finished = True
                break
            except Exception as e:  # noqa: BLE001
                self.status = f"error: {e}"
                log.exception("camera %s read failed", self.camera_id)
                time.sleep(1)
                continue
            if f is None:
                if self.is_browser:
                    self.status = "waiting for browser webcam"
                else:
                    self.status = "waiting for video" if not getattr(self.source, "connected", False) else "stalled"
                self._expire_tracks(time.time(), force_after=5.0)
                continue
            if live_src and f.ts - last < min_gap:
                continue
            last = f.ts
            self.status = "running"
            if not self._motion_gate(f.image, f.ts):
                self.skipped += 1
                self.recorder.push(f.ts, f.image)  # keep pre-roll for evidence
                self.recorder.tick(f.ts)
                self.last_frame_ts = f.ts
                if (self.live.viewers > 0 or self.is_browser) and f.ts - self.last_live_ts >= 0.12:
                    self._publish_live(f.image, f.ts, [], {})  # video keeps flowing; nothing to annotate
                continue
            t0 = time.perf_counter()
            try:
                self._process(f.image, f.ts)
            except Exception:  # noqa: BLE001
                log.exception("camera %s frame processing failed", self.camera_id)
            self.proc_times.append(time.perf_counter() - t0)
            self.frame_ts.append(time.time())
        # drain
        for tr in list(self.tracks.values()):
            self._close_track(tr)
        self.tracks.clear()
        self.recorder.tick(self.last_frame_ts, force=True)
        self.behavior.occupancy.save()
        if self.status == "running":
            self.status = "stopped"
        bus.publish_threadsafe("camera.status", {"camera_id": self.camera_id, "status": self.status})

    MOTION_THRESHOLD = 0.0025  # fraction of changed thumbnail pixels
    IDLE_AFTER_S = 3.0
    IDLE_PROBE_S = 1.0

    def _motion_gate(self, img: np.ndarray, ts: float) -> bool:
        """True = analyse this frame. Idle scenes (no tracks, no motion) are probed once a second."""
        small = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA),
                                              cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if self.motion_ref is None:
            self.motion_ref, self.motion_ref_ts = small, ts
            return True
        diff = cv2.absdiff(small, self.motion_ref)
        self.motion = float((diff > 14).mean())
        if ts - self.motion_ref_ts >= 0.4:  # compare across ~0.4 s so slow walkers register
            self.motion_ref, self.motion_ref_ts = small, ts
        if self.motion >= self.MOTION_THRESHOLD:
            self.last_motion_ts = ts
        active = any(ts - t.last_ts < 2.0 for t in self.tracks.values())
        self.idle = not active and ts - self.last_motion_ts > self.IDLE_AFTER_S
        if not self.idle:
            return True
        if ts - self.last_idle_probe >= self.IDLE_PROBE_S:
            self.last_idle_probe = ts
            return True
        return False

    def _process(self, img: np.ndarray, ts: float) -> None:
        H, W = img.shape[:2]
        self.resolution = (W, H)
        self.frames += 1
        self.last_frame_ts = ts
        h = hub()
        t = time.perf_counter()
        pose_f = h.pose.submit(img)
        obj_f = h.objects.submit(img) if self.frames % self.s.object_every_n == 0 else None
        pose = pose_f.result(timeout=10)
        t = self._mark("pose", t)
        objects = None
        if obj_f is not None:
            try:
                objects = obj_f.result(timeout=10)
                self.last_objects = objects
            except Exception:  # noqa: BLE001
                objects = None

        # tracking
        seen = set()
        for tid, box, conf, kps in self.tracker.update(pose):
            seen.add(tid)
            tr = self.tracks.get(tid)
            if tr is None:
                uid = f"{_SAFE.sub('_', self.camera_id)}-{int(ts)}-{tid}"
                tr = TrackState(uid, tid, self.camera_id, ts, ts, box, kps, conf)
                self.tracks[tid] = tr
                self.counts["tracks_total"] += 1
            tr.update(ts, box, kps, conf, W, H)
            self._best_person(tr, img)
        self._expire_tracks(ts)
        active = [tr for tr in self.tracks.values() if ts - tr.last_ts < 0.5]
        t = self._mark("track", t)

        # faces + identity
        self._collect_faces(img)
        self._schedule_faces(img, ts, active)
        self._collect_appearance()
        t = self._mark("faces", t)

        idsvc = identities()
        labels = {iid: m.label for iid, m in idsvc.meta.items()}
        signals = self.behavior.update(ts, active, objects, W, H, labels)
        t = self._mark("behavior", t)
        self.violence.push_frame(ts, img)
        signals += self.violence.update(ts, active, labels, h.aux)
        t = self._mark("violence", t)
        while not self.inject_q.empty():
            sig, tuid = self.inject_q.get_nowait()
            tr = next((x for x in self.tracks.values() if x.uid == tuid), None)
            if tr is not None:
                sig.boxes = [[*map(float, tr.box), sig.title[:40]]]
            sig.ts = ts
            signals.append(sig)
        for sig in signals:
            self._emit(sig, img, ts)

        self.recorder.push(ts, img)
        self.recorder.tick(ts)
        t = self._mark("record", t)
        if ts - self.last_persist > 5.0:
            self.last_persist = ts
            for tr in active:
                if tr.dirty and (tr.identity_id or tr.duration > 3):
                    self._persist_track(tr, closed=False)
        if self.live.viewers > 0 or self.is_browser:  # the webcam's own page needs overlays even unwatched
            try:
                self._publish_live(img, ts, active, labels)
            except Exception:  # noqa: BLE001 - a display problem must never cost analysis
                log.exception("live overlay failed on %s", self.camera_id)
            t = self._mark("live", t)

    # ── faces ──
    def _schedule_faces(self, img, ts, active) -> None:
        if self.face_job is not None:
            return
        cand = []
        for tr in active:
            if tr.height < 70:
                continue
            gap = self.s.identity_recheck_s if tr.identity_locked else 0.25
            if ts - tr.last_face_try < gap:
                continue
            reg = tr.head_region()
            if reg is None:
                continue
            prio = (0 if not tr.identity_locked else 1, -tr.height)
            cand.append((prio, tr, reg))
        if not cand:
            return
        cand.sort(key=lambda c: c[0])
        cand = cand[:4]
        for _, tr, _ in cand:
            tr.last_face_try = ts
            tr.face_attempts += 1
        fut = hub().face.submit(face_analyze, img, [c[2] for c in cand])
        self.face_job = (fut, [c[1].local_id for c in cand], img)

    def _collect_faces(self, _img) -> None:
        if self.face_job is None or not self.face_job[0].done():
            return
        fut, tids, frame = self.face_job
        self.face_job = None
        try:
            results = fut.result()
        except Exception:  # noqa: BLE001
            return
        idsvc = identities()
        for tid, obs in zip(tids, results):
            tr = self.tracks.get(tid)
            if tr is None or obs is None:
                continue
            self.counts["faces"] += 1
            change = idsvc.observe(tr, obs, frame)
            if change in ("matched", "created"):
                tr.dirty = True
                self._persist_track(tr, closed=False)
            if tr.identity_id:
                idsvc.maybe_check_watchlist(tr)

    # ── appearance (CLIP) for NL search & cross-camera hints ──
    def _best_person(self, tr: TrackState, img) -> None:
        vis = float((tr.kps[:, 2] > 0.35).sum()) / 17.0
        x1, y1, x2, y2 = tr.box
        H, W = img.shape[:2]
        edge = x1 <= 2 or y1 <= 2 or x2 >= W - 2 or y2 >= H - 2
        score = tr.conf * min(tr.height / 300.0, 1.0) * (0.4 + 0.6 * vis) * (0.6 if edge else 1.0)
        if score > tr.best_person_score * 1.15 and tr.height > 50:
            tr.best_person_score = score
            crop = img[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]
            if crop.size:
                hh = crop.shape[0]
                small = cv2.resize(crop, (max(1, int(crop.shape[1] * 256 / hh)), 256)) if hh > 256 else crop
                tr.best_person_crop = small
                ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    tr.best_person_jpg = jpg.tobytes()
                if tr.appearance_pending is None and tr.last_ts - tr.appearance_ts > 3.0:
                    tr.appearance_ts = tr.last_ts
                    tr.appearance_pending = hub().aux.submit(clip_images, [small])

    def _collect_appearance(self) -> None:
        for tr in self.tracks.values():
            f = tr.appearance_pending
            if f is not None and f.done():
                tr.appearance_pending = None
                try:
                    tr.appearance = f.result()[0]
                except Exception:  # noqa: BLE001
                    pass

    # ── lifecycle ──
    def _expire_tracks(self, ts: float, force_after: float | None = None) -> None:
        horizon = force_after or max(3.0, 2.5 * 1.2)
        for tid in [tid for tid, t in self.tracks.items() if ts - t.last_ts > horizon]:
            self._close_track(self.tracks.pop(tid))

    def _close_track(self, tr: TrackState) -> None:
        for zid, enter in tr.zone_enter.items():
            tr.zone_dwell[zid] = tr.zone_dwell.get(zid, 0.0) + (tr.last_ts - enter)
        tr.zone_enter.clear()
        if tr.duration < 1.0 and not tr.identity_id:
            return  # detector flicker, not a sighting
        self._persist_track(tr, closed=True)

    def _persist_track(self, tr: TrackState, closed: bool) -> None:
        tr.dirty = False
        media = self.s.media_dir
        face_path = person_path = None
        if tr.best_face_jpg:
            (media / "faces" / "tracks").mkdir(parents=True, exist_ok=True)
            (media / "faces" / "tracks" / f"{tr.uid}.jpg").write_bytes(tr.best_face_jpg)
            face_path = f"faces/tracks/{tr.uid}.jpg"
        if tr.best_person_jpg:
            (media / "persons" / f"{tr.uid}.jpg").write_bytes(tr.best_person_jpg)
            person_path = f"persons/{tr.uid}.jpg"
        summary = {
            "uid": tr.uid, "camera_id": tr.camera_id, "local_id": tr.local_id, "identity_id": tr.identity_id,
            "identity_score": round(tr.identity_score, 3) if tr.identity_id else None,
            "identity_method": tr.identity_method, "first_ts": tr.first_ts, "last_ts": tr.last_ts,
            "duration": round(tr.duration, 2), "path": [[round(t - tr.first_ts, 1), x, y] for t, x, y in tr.path][-400:],
            "max_speed": round(tr.max_speed, 2), "mean_speed": round(tr.mean_speed(), 2),
            "zones": {k: round(v, 1) for k, v in tr.zone_dwell.items()},
            "best_face_path": face_path, "best_face_q": round(tr.best_face_q, 3), "best_person_path": person_path,
            "appearance": tr.appearance.tobytes() if tr.appearance is not None else None,
            "attributes": {"posture": tr.posture, "reversals": tr.reversals, "face_attempts": tr.face_attempts,
                           "face_obs": len(tr.face_buf)},
            "anomaly": round(tr.anomaly, 3), "closed": closed,
        }
        from vigil.services import persist_track
        runtime.submit(persist_track(summary))

    # ── signals ──
    def _emit(self, sig: Signal, img, ts) -> None:
        sig.event_id = sig.event_id or new_id("evt")
        try:
            sig.evidence = self.recorder.capture(sig.event_id, ts, img, sig.boxes)
        except Exception:  # noqa: BLE001
            log.exception("evidence capture failed")
        self.counts["signals"] += 1
        bus.publish_threadsafe("signal", sig)

    # ── live ──
    def _publish_live(self, img, ts, active, labels) -> None:
        self.last_live_ts = ts
        s = self.s
        H, W = img.shape[:2]
        lw = s.live_width
        small = cv2.resize(img, (lw, int(H * lw / W)), interpolation=cv2.INTER_AREA) if W > lw else img
        ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, s.live_jpeg_quality])
        if not ok:
            return
        idsvc = identities()
        tracks = []
        for tr in active:
            m = idsvc.meta.get(tr.identity_id) if tr.identity_id else None
            if m is not None and m.frs_criminal_id:
                kind = "watchlist"
            elif m is not None and m.category in ("banned", "watch"):
                kind = "watch"
            elif m is not None and m.kind == "enrolled":
                kind = "known"
            elif m is not None:
                kind = "reidentified"
            else:
                kind = "unresolved"
            x1, y1, x2, y2 = (float(v) for v in tr.box)  # numpy float32 is not JSON-serialisable
            kp = tr.kps.astype(np.float64)
            kp[:, 0] /= W
            kp[:, 1] /= H
            tracks.append({
                "id": tr.local_id, "uid": tr.uid, "box": [round(x1 / W, 4), round(y1 / H, 4), round(x2 / W, 4), round(y2 / H, 4)],
                "identity": tr.identity_id, "label": m.label if m else f"#{tr.local_id}", "kind": kind,
                "score": round(float(tr.identity_score), 2) if tr.identity_id and tr.identity_method == "face" else None,
                "speed": round(float(tr.speed_ema), 2), "posture": tr.posture, "dwell": round(float(tr.duration), 1),
                "trail": [[float(x), float(y)] for _, x, y in tr.path[-24:]],
                "kps": np.round(kp, 3).tolist(),
            })
        objs = [{"label": o.label, "box": [round(float(o.box[0]) / W, 4), round(float(o.box[1]) / H, 4),
                                           round(float(o.box[2]) / W, 4), round(float(o.box[3]) / H, 4)],
                 "conf": round(float(o.conf), 2),
                 "weapon": o.label in WEAPON_LABELS, "bag": o.label in BAG_LABELS} for o in self.last_objects]
        header = {"camera_id": self.camera_id, "ts": ts, "w": W, "h": H, "tracks": tracks, "objects": objs,
                  "zones": [{"id": z.id, "name": z.name, "kind": z.kind, "polygon": z.polygon} for z in self.zones],
                  "violence": self.violence.last, "fps": self.stats()["fps"]}
        hb = json.dumps(header, separators=(",", ":"), default=_jsonable).encode()
        self.live.set(len(hb).to_bytes(4, "big") + hb + jpg.tobytes(), hb)
