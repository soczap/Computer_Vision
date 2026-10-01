"""Frame sources.

- FRSRelaySource: the FRS backend's MJPEG relay of a camera it already decodes.
  Reusing it means the camera sees no second RTSP session and we inherit FRS's
  NVDEC decode.
- StreamSource: RTSP / HTTP / webcam device via OpenCV-FFmpeg (TCP transport).
- FileSource: a video file, paced to wall clock or as fast as analysis allows.

Live sources keep only the newest frame (a reader thread overwrites a single
slot), so a slow consumer sees fresh frames instead of an ever-growing lag.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

import cv2
import httpx
import numpy as np

from vigil.config import get_settings

log = logging.getLogger("vigil.source")
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")


@dataclass
class Frame:
    image: np.ndarray  # BGR
    ts: float  # wall-clock epoch seconds (virtual for non-realtime files)
    seq: int


class SourceEnded(Exception):
    """A finite source (non-looping file) has no more frames."""


class LatestSlot:
    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._frame: Frame | None = None
        self._taken_seq = -1

    def put(self, f: Frame) -> None:
        with self._cv:
            self._frame = f
            self._cv.notify_all()

    def get(self, timeout: float) -> Frame | None:
        with self._cv:
            end = time.time() + timeout
            while self._frame is None or self._frame.seq == self._taken_seq:
                left = end - time.time()
                if left <= 0:
                    return None
                self._cv.wait(left)
            self._taken_seq = self._frame.seq
            return self._frame


class LiveSource:
    """Base for live sources: a reader thread feeds a LatestSlot."""

    kind = "live"

    def __init__(self, name: str) -> None:
        self.name = name
        self.slot = LatestSlot()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_error: str | None = None
        self.reconnects = 0
        self.frames_in = 0
        self.resolution: tuple[int, int] | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_forever, name=f"src-{self.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def read(self, timeout: float = 2.0) -> Frame | None:
        return self.slot.get(timeout)

    def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._run_once()
                backoff = 1.0
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)[:300]
                log.warning("source %s error: %s", self.name, self.last_error)
            self.connected = False
            if self._stop.is_set():
                break
            self.reconnects += 1
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _emit(self, img: np.ndarray) -> None:
        self.frames_in += 1
        self.resolution = (img.shape[1], img.shape[0])
        self.slot.put(Frame(img, time.time(), self.frames_in))

    def _run_once(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class FRSRelaySource(LiveSource):
    def __init__(self, name: str, url: str) -> None:
        super().__init__(name)
        self.url = url

    def _run_once(self) -> None:
        s = get_settings()
        with httpx.Client(verify=s.frs_verify_tls, timeout=httpx.Timeout(10.0, read=15.0)) as client:
            with client.stream("GET", self.url) as r:
                r.raise_for_status()
                self.connected = True
                self.last_error = None
                buf = bytearray()
                for chunk in r.iter_bytes(65536):
                    if self._stop.is_set():
                        return
                    buf += chunk
                    # JPEG boundaries by marker: robust to header variations.
                    while True:
                        a = buf.find(b"\xff\xd8")
                        if a < 0:
                            buf.clear()
                            break
                        b = buf.find(b"\xff\xd9", a + 2)
                        if b < 0:
                            if a > 0:
                                del buf[:a]
                            break
                        jpg = bytes(buf[a:b + 2])
                        del buf[:b + 2]
                        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                        if img is not None:
                            self._emit(img)
                    if len(buf) > 20_000_000:
                        buf.clear()


class StreamSource(LiveSource):
    def __init__(self, name: str, uri: str) -> None:
        super().__init__(name)
        self.uri = uri

    def _run_once(self) -> None:
        target = int(self.uri) if self.uri.isdigit() else self.uri
        cap = cv2.VideoCapture(target, cv2.CAP_FFMPEG) if isinstance(target, str) else cv2.VideoCapture(target)
        try:
            if not cap.isOpened():
                raise RuntimeError("could not open stream")
            self.connected = True
            self.last_error = None
            misses = 0
            while not self._stop.is_set():
                ok, img = cap.read()
                if not ok or img is None:
                    misses += 1
                    if misses > 50:
                        raise RuntimeError("stream stalled")
                    time.sleep(0.02)
                    continue
                misses = 0
                self._emit(img)
        finally:
            cap.release()


class FileSource:
    """Sequential file reader. Samples frames to the analysis rate in *video* time."""

    kind = "file"

    def __init__(self, name: str, path: str, loop: bool, realtime: bool, target_fps: float) -> None:
        self.name, self.path, self.loop, self.realtime = name, path, loop, realtime
        self.target_fps = target_fps
        self.connected = False
        self.last_error: str | None = None
        self.reconnects = 0
        self.frames_in = 0
        self.resolution: tuple[int, int] | None = None
        self.finished = False
        self.progress = 0.0
        self._cap: cv2.VideoCapture | None = None
        self._base_wall = time.time()
        self._seq = 0
        self._stop = threading.Event()
        self._video_fps = 25.0
        self._n_frames = 0
        self._idx = 0
        self._next_t = 0.0

    def start(self) -> None:
        self._base_wall = time.time()
        self._open()

    def stop(self) -> None:
        self._stop.set()

    def _open(self) -> None:
        if not os.path.exists(self.path):
            self.last_error = "file not found"
            raise SourceEnded(self.path)
        self._cap = cv2.VideoCapture(self.path)
        self._video_fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        if not (1.0 <= self._video_fps <= 240.0):
            self._video_fps = 25.0
        self._n_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self._idx = 0
        self._next_t = 0.0
        self.connected = True

    def read(self, timeout: float = 2.0) -> Frame | None:
        if self._stop.is_set() or self.finished:
            raise SourceEnded(self.path)
        assert self._cap is not None
        step = 1.0 / max(self.target_fps, 1.0)
        while True:
            ok, img = self._cap.read()
            if not ok or img is None:
                if self.loop and self._idx > 0:
                    # Next pass continues the virtual clock where this one ended.
                    self._base_wall += self._idx / self._video_fps
                    self._cap.release()
                    self._open()
                    continue
                self.finished = True
                self.connected = False
                self.progress = 1.0
                raise SourceEnded(self.path)
            t_video = self._idx / self._video_fps
            self._idx += 1
            if t_video + 1e-6 < self._next_t:
                continue
            self._next_t = t_video + step
            if self.realtime:
                wait = (self._base_wall + t_video) - time.time()
                if wait > 0:
                    time.sleep(min(wait, 1.0))
            self.frames_in += 1
            self._seq += 1
            self.resolution = (img.shape[1], img.shape[0])
            if self._n_frames:
                self.progress = min(self._idx / self._n_frames, 1.0)
            return Frame(img, self._base_wall + t_video, self._seq)


class BrowserSource(LiveSource):
    """Frames pushed by a browser (getUserMedia webcam) over the /ws/ingest WebSocket.

    No reader thread: the WebSocket handler calls push(). Same LatestSlot semantics as
    other live sources, so a burst of frames never builds a backlog.
    """

    kind = "browser"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.clients = 0
        self.last_push = 0.0

    def start(self) -> None:  # nothing to connect to; the browser comes to us
        return

    def push(self, img: np.ndarray) -> None:
        if self._stop.is_set():
            return
        self.last_push = time.time()
        self.connected = True
        self._emit(img)

    def read(self, timeout: float = 2.0) -> Frame | None:
        f = self.slot.get(timeout)
        if f is None and time.time() - self.last_push > 3.0:
            self.connected = False  # no frames for 3 s: the tab closed or the camera stopped
        return f


def make_source(cam) -> LiveSource | FileSource:
    s = get_settings()
    fps = cam.analysis_fps or s.analysis_fps
    if cam.source_type == "frs":
        from vigil.frs_client import frs
        return FRSRelaySource(cam.id, frs().relay_url(cam.source_uri))
    if cam.source_type == "browser":
        return BrowserSource(cam.id)
    if cam.source_type == "file":
        return FileSource(cam.id, cam.source_uri, loop=cam.loop, realtime=cam.realtime, target_fps=fps)
    return StreamSource(cam.id, cam.source_uri)
