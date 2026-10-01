"""Per-camera multi-object tracking (ByteTrack) and the live state of each track."""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

from vigil.perception.models import PoseResult

# COCO-17 keypoint indices
NOSE, LEYE, REYE, LEAR, REAR, LSHO, RSHO, LELB, RELB, LWRI, RWRI, LHIP, RHIP, LKNE, RKNE, LANK, RANK = range(17)
KP_CONF = 0.35


class _Dets:
    """Results-like object for ultralytics BYTETracker (conf, xywh, cls, mask indexing)."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray):
        self.conf = conf.astype(np.float32)
        xywh = np.zeros_like(xyxy, dtype=np.float32)
        if len(xyxy):
            xywh[:, 0] = (xyxy[:, 0] + xyxy[:, 2]) / 2
            xywh[:, 1] = (xyxy[:, 1] + xyxy[:, 3]) / 2
            xywh[:, 2] = xyxy[:, 2] - xyxy[:, 0]
            xywh[:, 3] = xyxy[:, 3] - xyxy[:, 1]
        self.xywh = xywh
        self.cls = np.zeros(len(conf), np.float32)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, m):
        out = _Dets.__new__(_Dets)
        out.conf, out.xywh, out.cls = self.conf[m], self.xywh[m], self.cls[m]
        return out


class PersonTracker:
    def __init__(self, fps: float):
        from ultralytics.trackers.byte_tracker import BYTETracker
        args = SimpleNamespace(track_high_thresh=0.45, track_low_thresh=0.15, new_track_thresh=0.5,
                               track_buffer=int(max(fps, 5) * 2.5), match_thresh=0.8, fuse_score=True)
        self.t = BYTETracker(args)

    def update(self, pose: PoseResult) -> list[tuple[int, np.ndarray, float, np.ndarray]]:
        out = self.t.update(_Dets(pose.boxes, pose.conf))
        res = []
        for row in out:
            x1, y1, x2, y2, tid, score, _cls, idx = row[:8]
            idx = int(idx)
            kps = pose.kps[idx] if 0 <= idx < len(pose.kps) else np.zeros((17, 3), np.float32)
            res.append((int(tid), np.array([x1, y1, x2, y2], np.float32), float(score), kps))
        return res


@dataclass
class KinSample:
    ts: float
    box: np.ndarray
    kps: np.ndarray


@dataclass
class TrackState:
    uid: str
    local_id: int
    camera_id: str
    first_ts: float
    last_ts: float
    box: np.ndarray
    kps: np.ndarray
    conf: float = 0.0
    frames: int = 0
    kin: deque = field(default_factory=lambda: deque(maxlen=48))  # ~4 s at 12 fps
    path: list = field(default_factory=list)  # [(ts, xn, yn)] sampled 0.5 s
    speed_ema: float = 0.0
    max_speed: float = 0.0
    speed_sum: float = 0.0
    speed_n: int = 0
    zones_now: set = field(default_factory=set)
    zone_enter: dict = field(default_factory=dict)
    zone_dwell: dict = field(default_factory=dict)
    # identity
    identity_id: str | None = None
    identity_score: float = 0.0
    identity_method: str | None = None
    identity_locked: bool = False
    identity_votes: int = 0
    contradictions: int = 0
    face_buf: list = field(default_factory=list)  # [(quality, emb)]
    face_attempts: int = 0
    last_face_try: float = 0.0
    face_pending: object = None  # Future
    best_face_q: float = 0.0
    best_face_jpg: bytes | None = None
    best_face_frame_crop: bytes | None = None  # padded crop for FRS
    best_face_px: float = 0.0
    best_person_score: float = 0.0
    best_person_jpg: bytes | None = None
    best_person_crop: np.ndarray | None = None
    appearance: np.ndarray | None = None
    appearance_pending: object = None
    appearance_ts: float = 0.0
    frs_submitted: bool = False
    # behaviour flags
    fired: dict = field(default_factory=dict)  # event type -> last ts
    posture: str = "upright"
    down_since: float | None = None
    upright_last: float = 0.0
    reversals: int = 0
    last_dir: float | None = None
    leg_ext: float | None = None
    leg_origin: float = 0.0
    anomaly: float = 0.0
    carried: set = field(default_factory=set)
    dirty: bool = True

    @property
    def height(self) -> float:
        return float(max(self.box[3] - self.box[1], 1.0))

    @property
    def foot(self) -> tuple[float, float]:
        return float((self.box[0] + self.box[2]) / 2), float(self.box[3])

    @property
    def center(self) -> tuple[float, float]:
        return float((self.box[0] + self.box[2]) / 2), float((self.box[1] + self.box[3]) / 2)

    @property
    def duration(self) -> float:
        return self.last_ts - self.first_ts

    def update(self, ts: float, box: np.ndarray, kps: np.ndarray, conf: float, W: int, H: int) -> None:
        prev_foot, prev_ts = self.foot, self.last_ts
        self.box, self.kps, self.conf, self.last_ts = box, kps, conf, ts
        self.frames += 1
        self.kin.append(KinSample(ts, box.copy(), kps.copy()))
        dt = ts - prev_ts
        if 0 < dt < 2.0 and self.frames > 1:
            fx, fy = self.foot
            v = math.hypot(fx - prev_foot[0], fy - prev_foot[1]) / dt / self.height  # body-heights / s
            self.speed_ema = 0.7 * self.speed_ema + 0.3 * v
            self.max_speed = max(self.max_speed, self.speed_ema)
            self.speed_sum += self.speed_ema
            self.speed_n += 1
        if not self.path or ts - self.path[-1][0] >= 0.5:
            fx, fy = self.foot
            xn, yn = fx / W, fy / H
            self._leg(xn)
            self.path.append((ts, round(xn, 4), round(yn, 4)))
            self.dirty = True

    LEG_MIN = 0.06  # a direction change counts only after travelling 6% of the frame width

    def _leg(self, xn: float) -> None:
        """Hysteresis reversal counter: jitter and short shuffles are not pacing."""
        if self.leg_ext is None:
            self.leg_ext, self.leg_origin = xn, xn
            return
        if self.last_dir is None:
            if abs(xn - self.leg_origin) >= self.LEG_MIN:
                self.last_dir = math.copysign(1.0, xn - self.leg_origin)
                self.leg_ext = xn
            return
        if (xn - self.leg_ext) * self.last_dir > 0:
            self.leg_ext = xn  # still moving the same way
        elif abs(xn - self.leg_ext) >= self.LEG_MIN:
            self.reversals += 1
            self.last_dir = -self.last_dir
            self.leg_ext = xn

    # ── pose kinematics ──
    def head_region(self) -> tuple[float, float, float, float] | None:
        k = self.kps
        pts = [k[i, :2] for i in (NOSE, LEYE, REYE, LEAR, REAR) if k[i, 2] > KP_CONF]
        x1, y1, x2, y2 = self.box
        bw, bh = x2 - x1, y2 - y1
        if len(pts) >= 2:
            p = np.array(pts)
            cx, cy = p[:, 0].mean(), p[:, 1].mean()
            span = max(np.ptp(p[:, 0]), np.ptp(p[:, 1]), bw * 0.25)
            r = span * 1.6
            return (cx - r, cy - r * 1.1, cx + r, cy + r)
        if bh < 60:
            return None
        return (x1, y1, x2, y1 + min(bh * 0.35, bw * 1.2))

    def facing_camera(self) -> bool:
        k = self.kps
        return k[NOSE, 2] > KP_CONF and (k[LEYE, 2] > KP_CONF or k[REYE, 2] > KP_CONF)

    def wrist_speed(self, window_s: float = 0.6) -> float:
        """p90 wrist speed over the window in body-heights/s (0 if unobserved)."""
        samples = [s for s in self.kin if self.last_ts - s.ts <= window_s]
        if len(samples) < 3:
            return 0.0
        speeds = []
        for a, b in zip(samples, samples[1:]):
            dt = b.ts - a.ts
            if dt <= 0:
                continue
            h = max(b.box[3] - b.box[1], 1.0)
            for w in (LWRI, RWRI):
                if a.kps[w, 2] > KP_CONF and b.kps[w, 2] > KP_CONF:
                    # Wrist motion relative to the body centre, so walking does not count as striking.
                    ca = (a.box[:2] + a.box[2:]) / 2
                    cb = (b.box[:2] + b.box[2:]) / 2
                    d = (b.kps[w, :2] - cb) - (a.kps[w, :2] - ca)
                    speeds.append(float(np.hypot(*d)) / dt / h)
        return float(np.percentile(speeds, 90)) if speeds else 0.0

    def torso_angle(self) -> float | None:
        """Degrees from vertical of the shoulder-mid -> hip-mid vector."""
        k = self.kps
        if min(k[LSHO, 2], k[RSHO, 2], k[LHIP, 2], k[RHIP, 2]) < KP_CONF:
            return None
        sh = (k[LSHO, :2] + k[RSHO, :2]) / 2
        hp = (k[LHIP, :2] + k[RHIP, :2]) / 2
        v = hp - sh
        return float(abs(math.degrees(math.atan2(v[0], v[1] + 1e-6))))

    def wrists(self) -> list[np.ndarray]:
        return [self.kps[w, :2] for w in (LWRI, RWRI) if self.kps[w, 2] > KP_CONF]

    def radius_of_gyration(self, since_s: float) -> float:
        pts = np.array([(x, y) for t, x, y in self.path if self.last_ts - t <= since_s])
        if len(pts) < 2:
            return 0.0
        return float(np.sqrt(((pts - pts.mean(0)) ** 2).sum(1).mean()))

    def mean_speed(self) -> float:
        return self.speed_sum / self.speed_n if self.speed_n else 0.0


def now() -> float:
    return time.time()
