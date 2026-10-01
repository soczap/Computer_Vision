"""Evidence capture: pre-roll ring buffer -> annotated keyframe + H.264 clip + VLM frames."""
from __future__ import annotations

import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import av
import cv2
import numpy as np

from vigil.bus import bus
from vigil.config import get_settings

log = logging.getLogger("vigil.recorder")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clip-writer")
REC_W = 1280


def annotate(frame: np.ndarray, boxes: list, color=(40, 40, 235)) -> np.ndarray:
    img = frame.copy()
    th = max(2, img.shape[1] // 640)
    for b in boxes:
        x1, y1, x2, y2 = map(int, b[:4])
        label = str(b[4]) if len(b) > 4 else ""
        cv2.rectangle(img, (x1, y1), (x2, y2), color, th)
        if label:
            fs = 0.5 * th
            (tw, tht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
            cv2.rectangle(img, (x1, max(0, y1 - tht - 8)), (x1 + tw + 6, y1), color, -1)
            cv2.putText(img, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th)
    return img


def _resize(frame: np.ndarray, width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    return cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)


def write_clip(path: str, jpegs: list[bytes], fps: float) -> bool:
    if not jpegs:
        return False
    first = cv2.imdecode(np.frombuffer(jpegs[0], np.uint8), cv2.IMREAD_COLOR)
    h, w = first.shape[:2]
    h, w = h - h % 2, w - w % 2
    try:
        with av.open(path, "w", options={"movflags": "+faststart"}) as out:
            st = out.add_stream("libx264", rate=Fraction(int(round(fps * 1000)), 1000))
            st.width, st.height, st.pix_fmt = w, h, "yuv420p"
            st.options = {"crf": "26", "preset": "veryfast"}
            for jb in jpegs:
                img = cv2.imdecode(np.frombuffer(jb, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                if img.shape[:2] != (h, w):
                    img = cv2.resize(img, (w, h))
                fr = av.VideoFrame.from_ndarray(img, format="bgr24")
                for pkt in st.encode(fr):
                    out.mux(pkt)
            for pkt in st.encode():
                out.mux(pkt)
        return True
    except Exception:  # noqa: BLE001
        log.exception("clip write failed: %s", path)
        return False


class Recorder:
    def __init__(self, camera_id: str) -> None:
        s = get_settings()
        self.camera_id = camera_id
        self.fps = s.ring_fps
        self.pre, self.post = s.clip_pre_s, s.clip_post_s
        self.ring: deque = deque(maxlen=int((self.pre + self.post + 4) * self.fps))
        self.last_push = 0.0
        self.pending: list[dict] = []
        self.root = s.media_dir / "evidence"

    def push(self, ts: float, frame: np.ndarray) -> None:
        if ts - self.last_push < 1.0 / self.fps:
            return
        self.last_push = ts
        ok, jpg = cv2.imencode(".jpg", _resize(frame, REC_W), [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            self.ring.append((ts, jpg.tobytes()))

    def capture(self, event_id: str, ts: float, frame: np.ndarray, boxes: list) -> dict:
        d = self.root / event_id
        d.mkdir(parents=True, exist_ok=True)
        key = annotate(_resize(frame, REC_W), [[*(np.array(b[:4]) * min(1.0, REC_W / frame.shape[1])), *b[4:]]
                                               for b in boxes])
        cv2.imwrite(str(d / "key.jpg"), key, [cv2.IMWRITE_JPEG_QUALITY, 88])
        self.pending.append({"event_id": event_id, "ts": ts, "t_end": ts + self.post})
        return {"keyframe": f"evidence/{event_id}/key.jpg"}

    def tick(self, now: float, force: bool = False) -> None:
        keep = []
        for p in self.pending:
            if force or now >= p["t_end"]:
                frames = [(t, j) for t, j in self.ring if p["ts"] - self.pre <= t <= p["t_end"]]
                _pool.submit(self._finish, p["event_id"], p["ts"], frames)
            else:
                keep.append(p)
        self.pending = keep

    def _finish(self, event_id: str, ts: float, frames: list[tuple[float, bytes]]) -> None:
        d = self.root / event_id
        ev: dict = {"event_id": event_id, "camera_id": self.camera_id}
        if frames:
            if write_clip(str(d / "clip.mp4"), [j for _, j in frames], self.fps):
                ev["clip"] = f"evidence/{event_id}/clip.mp4"
            # six frames spanning [ts-2s, ts+2s] for visual verification
            window = [(t, j) for t, j in frames if ts - 2.5 <= t <= ts + 2.5] or frames
            idx = np.linspace(0, len(window) - 1, min(6, len(window))).astype(int)
            paths = []
            for n, i in enumerate(idx):
                (d / f"f{n}.jpg").write_bytes(window[i][1])
                paths.append(f"evidence/{event_id}/f{n}.jpg")
            ev["frames"] = paths
        bus.publish_threadsafe("evidence.ready", ev)
