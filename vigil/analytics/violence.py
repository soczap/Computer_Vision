"""Violence detection cascade (stage 1+2; stage 3 is the threat agent's VLM check).

Stage 1  pose interaction (every frame, explainable): pairs of people in close
         proximity; wrist speed relative to the body; wrists landing inside the
         other person's box (contact).
Stage 2  VideoMAE fine-tuned on RWF-2000 (CCTV fights) over a 16-frame clip of
         the interacting region, run at most once per interval and only when
         >= 2 people are close. Measured on held-out RWF-2000 val clips here:
         AUC 0.954 but badly calibrated (half the non-fights score > 0.8), which
         is why it never alerts alone.
Fusion   weighted, smoothed, and it must stay hot for consecutive evaluations.
"""
from __future__ import annotations

import math
from collections import deque

import cv2
import numpy as np

from vigil.analytics.signals import Signal
from vigil.config import get_settings
from vigil.perception.models import violence_score


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class ViolenceMonitor:
    SMALL_W = 640

    def __init__(self, camera_id: str, rules: dict) -> None:
        self.camera_id = camera_id
        self.rules = rules
        s = get_settings()
        self.interval = s.violence_eval_interval_s
        self.logit_thr = s.violence_logit_threshold
        self.frames: deque = deque(maxlen=48)
        self.scale = 1.0
        self.pending = None
        self.pending_meta: dict | None = None
        self.last_eval = 0.0
        self.last_eval_ts = 0.0
        self.ema = 0.0
        self.hot = 0
        self.last_fire = float("-inf")
        self.contact_hist: dict[tuple[str, str], deque] = {}
        self.pose_hist: deque = deque(maxlen=48)  # (ts, score, pair)
        self.evals: deque = deque(maxlen=12)
        self.last: dict = {}

    def push_frame(self, ts: float, frame: np.ndarray) -> None:
        H, W = frame.shape[:2]
        self.scale = self.SMALL_W / W if W > self.SMALL_W else 1.0
        small = cv2.resize(frame, (int(W * self.scale), int(H * self.scale)), interpolation=cv2.INTER_AREA) \
            if self.scale < 1.0 else frame.copy()
        self.frames.append((ts, small))

    # ── stage 1 ──
    def _pairs(self, tracks, ts) -> tuple[float, tuple | None, dict]:
        best, best_pair, feats = 0.0, None, {}
        live = [t for t in tracks if t.height > 40]
        for i in range(len(live)):
            for j in range(i + 1, len(live)):
                a, b = live[i], live[j]
                mh = (a.height + b.height) / 2
                d = math.hypot(a.center[0] - b.center[0], a.center[1] - b.center[1]) / mh
                if d > 1.2:
                    continue
                key = tuple(sorted((a.uid, b.uid)))
                hist = self.contact_hist.setdefault(key, deque(maxlen=24))
                hist.append(1.0 if (_wrist_in(a, b) or _wrist_in(b, a)) else 0.0)
                ws = max(a.wrist_speed(), b.wrist_speed())
                contact = float(np.mean(hist))
                prox = float(np.clip(1.2 - d, 0, 1))
                score = 0.55 * _sig((ws - 2.0) / 0.5) + 0.3 * min(contact * 2.5, 1.0) + 0.15 * prox
                if score > best:
                    best, best_pair = score, (a, b)
                    feats = {"pair": [a.uid, b.uid], "distance_bh": round(d, 2), "wrist_speed_bh_s": round(ws, 2),
                             "contact_rate": round(contact, 2), "pose_score": round(score, 3)}
        return best, best_pair, feats

    def update(self, ts: float, tracks: list, labels: dict, aux_worker) -> list[Signal]:
        r = self.rules.get("violence", {})
        if not r.get("enabled", True):
            return []
        pose_score, pair, feats = self._pairs(tracks, ts)
        self.pose_hist.append((ts, pose_score, feats))
        out: list[Signal] = []

        # collect a finished stage-2 evaluation
        if self.pending is not None and self.pending.done():
            meta = self.pending_meta or {}
            try:
                res = self.pending.result()
            except Exception:  # noqa: BLE001
                res = None
            self.pending, self.pending_meta = None, None
            if res is not None:
                sig = self._fuse(ts, res, meta, r, labels)
                if sig:
                    out.append(sig)

        # schedule the next stage-2 evaluation
        close = len([t for t in tracks if t.height > 40]) >= 2 and pair is not None
        if self.pending is None and close and ts - self.last_eval >= self.interval and len(self.frames) >= 12:
            clip = self._clip(ts, pair, tracks)
            if clip is not None:
                self.last_eval = ts
                recent = [p for p in self.pose_hist if ts - p[0] <= 2.0]
                pmax = max(recent, key=lambda p: p[1]) if recent else (ts, 0.0, {})
                self.pending_meta = {"pose": pmax[1], "pose_feats": pmax[2], "pair": pair, "ts": ts}
                self.pending = aux_worker.submit(violence_score, clip)
        elif not close:
            self.ema *= 0.7
            self.hot = 0
        return out

    def _clip(self, ts, pair, tracks) -> list[np.ndarray] | None:
        frames = [(t, f) for t, f in self.frames if ts - t <= 2.2]
        if len(frames) < 8:
            return None
        idx = np.linspace(0, len(frames) - 1, 16).astype(int)
        sel = [frames[i][1] for i in idx]
        a, b = pair
        # region: the pair plus anyone overlapping it, padded; at least half the frame's short side
        x1 = min(a.box[0], b.box[0]); y1 = min(a.box[1], b.box[1])
        x2 = max(a.box[2], b.box[2]); y2 = max(a.box[3], b.box[3])
        s = self.scale
        x1, y1, x2, y2 = x1 * s, y1 * s, x2 * s, y2 * s
        h, w = sel[0].shape[:2]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        side = max(x2 - x1, y2 - y1) * 1.5
        side = max(side, min(h, w) * 0.5)
        side = min(side, max(h, w))
        X1 = int(max(0, min(w - side, cx - side / 2))) if side < w else 0
        Y1 = int(max(0, min(h - side, cy - side / 2))) if side < h else 0
        X2, Y2 = int(min(w, X1 + side)), int(min(h, Y1 + side))
        return [f[Y1:Y2, X1:X2] for f in sel]

    def _fuse(self, ts, res, meta, r, labels) -> Signal | None:
        """Fire on one very hot evaluation or two consecutive hot ones.

        Tuned on RWF-2000 val clips through this exact code path
        (scripts/eval_violence_cascade.py, yolo11s-pose): 0.55/0.45 weights,
        instant 0.85, sustained 0.78 x2. See docs/EVALUATION.md for the tuning
        set and the separate out-of-sample check.
        """
        vm = _sig((res["logit"] - self.logit_thr) / 1.0)
        pose = float(meta.get("pose", 0.0))
        fused = 0.55 * vm + 0.45 * pose
        self.ema = fused if ts - self.last_eval_ts > 3.0 else 0.5 * self.ema + 0.5 * fused
        self.last_eval_ts = ts
        instant = float(r.get("trigger", 0.85))
        sustain = float(r.get("sustain", 0.78))
        self.hot = self.hot + 1 if fused >= sustain else 0
        self.last = {"ts": ts, "videomae_logit": round(res["logit"], 2), "videomae_prob": round(res["prob"], 4),
                     "videomae_component": round(vm, 3), "pose_component": round(pose, 3), "fused": round(fused, 3),
                     "ema": round(self.ema, 3), "hot_evals": self.hot}
        self.evals.append(self.last)
        rule_hit = "instant" if fused >= instant else ("sustained" if self.hot >= 2 else None)
        if rule_hit and ts - self.last_fire > get_settings().event_cooldown_s:
            self.last_fire = ts
            self.hot = 0
            a, b = meta["pair"]
            who = [labels.get(t.identity_id, t.identity_id) if t.identity_id else f"track #{t.local_id}" for t in (a, b)]
            return Signal(
                type="violence", severity=r.get("severity", "high"), confidence=round(min(max(fused, self.ema), 0.99), 3),
                title=f"Possible fight: {who[0]} and {who[1]}",
                description=(f"Physical altercation suspected between {who[0]} and {who[1]}. VideoMAE(RWF-2000) "
                             f"logit {res['logit']:.1f}, pose interaction {pose:.2f}, fused {fused:.2f} ({rule_hit} rule)."),
                camera_id=self.camera_id, ts=ts, track_uids=[a.uid, b.uid],
                identity_ids=[t.identity_id for t in (a, b) if t.identity_id],
                explanation={"rule": "violence_cascade", "stage1_pose": meta.get("pose_feats", {}),
                             "stage2_videomae": {"logit": round(res["logit"], 2), "prob": round(res["prob"], 4),
                                                 "logit_threshold": self.logit_thr},
                             "fusion": {"weights": {"videomae": 0.55, "pose": 0.45}, "fused": round(fused, 3),
                                        "rule": rule_hit, "instant_threshold": instant,
                                        "sustained_threshold": sustain, "consecutive_required": 2},
                             "recent_evaluations": list(self.evals)[-5:],
                             "reasoning": "Close-range interaction with fast relative limb motion and a fight-like "
                                          "temporal pattern; requires VLM verification before escalation."},
                boxes=[[*map(float, a.box), f"#{a.local_id}"], [*map(float, b.box), f"#{b.local_id}"]],
                verify=True)
        return None


def _wrist_in(a, b) -> bool:
    x1, y1, x2, y2 = b.box
    mx, my = (x2 - x1) * 0.1, (y2 - y1) * 0.05
    for w in a.wrists():
        if x1 + mx <= w[0] <= x2 - mx and y1 + my <= w[1] <= y2 - my:
            return True
    return False
