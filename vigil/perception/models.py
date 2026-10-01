"""Model wrappers and the GPU worker threads that own them.

Each model group lives on one dedicated thread (CUDA contexts and ONNX
sessions are not shared across threads). Callers get Futures back:
- pose:     batched across cameras (YOLO11-pose, persons + 17 COCO keypoints)
- objects:  YOLO11 COCO subset (bags, knives, bats) at a reduced rate
- face:     SCRFD detect -> 5-point align -> AdaFace IR101 (the FRS's own ONNX files, read-only)
- aux:      VideoMAE violence classifier + CLIP appearance/text encoder
"""
from __future__ import annotations

import logging
import math
import os
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field

import cv2
import numpy as np

from vigil.config import get_settings

log = logging.getLogger("vigil.models")

# ─────────────────────────── worker threads ────────────────────────────


class Worker:
    """One thread, one queue, sequential execution. Owns its models."""

    def __init__(self, name: str, init_fn=None, maxsize: int = 256):
        self.name = name
        self.q: queue.Queue = queue.Queue(maxsize=maxsize)
        self.state: dict = {}
        self._init_fn = init_fn
        self.ready = threading.Event()
        self.error: str | None = None
        self.busy_s = 0.0
        self.calls = 0
        self.dropped = 0
        self._t = threading.Thread(target=self._run, name=f"gpu-{name}", daemon=True)
        self._t.start()

    def _run(self) -> None:
        try:
            if self._init_fn:
                self._init_fn(self.state)
        except Exception as e:  # noqa: BLE001
            self.error = f"init failed: {e}"
            log.exception("worker %s init failed", self.name)
        self.ready.set()
        while True:
            item = self.q.get()
            if item is None:
                return
            self._execute(item)

    def _execute(self, item) -> None:
        fn, args, fut = item
        if not fut.set_running_or_notify_cancel():
            return
        t = time.perf_counter()
        try:
            fut.set_result(fn(self.state, *args))
        except Exception as e:  # noqa: BLE001
            fut.set_exception(e)
        finally:
            self.busy_s += time.perf_counter() - t
            self.calls += 1

    def submit(self, fn, *args) -> Future:
        fut: Future = Future()
        if self.error:
            fut.set_exception(RuntimeError(self.error))
            return fut
        try:
            self.q.put_nowait((fn, args, fut))
        except queue.Full:
            self.dropped += 1
            fut.set_exception(RuntimeError(f"{self.name} queue full"))
        return fut


class BatchWorker(Worker):
    """Collects same-kind requests for a few ms and runs them as one batch."""

    def __init__(self, name: str, init_fn, batch_fn, max_batch: int = 4, max_wait_s: float = 0.004):
        self.batch_fn = batch_fn
        self.max_batch, self.max_wait_s = max_batch, max_wait_s
        super().__init__(name, init_fn)

    def _run(self) -> None:
        try:
            self._init_fn(self.state)
        except Exception as e:  # noqa: BLE001
            self.error = f"init failed: {e}"
            log.exception("worker %s init failed", self.name)
        self.ready.set()
        while True:
            first = self.q.get()
            if first is None:
                return
            batch = [first]
            deadline = time.perf_counter() + self.max_wait_s
            while len(batch) < self.max_batch:
                left = deadline - time.perf_counter()
                if left <= 0:
                    break
                try:
                    nxt = self.q.get(timeout=left)
                except queue.Empty:
                    break
                if nxt is None:
                    self.q.put(None)
                    break
                batch.append(nxt)
            futs = [f for _, f in batch if f.set_running_or_notify_cancel()]
            items = [x for x, f in batch if f in futs]
            if not items:
                continue
            t = time.perf_counter()
            try:
                outs = self.batch_fn(self.state, items)
                for f, o in zip(futs, outs):
                    f.set_result(o)
            except Exception as e:  # noqa: BLE001
                for f in futs:
                    f.set_exception(e)
            finally:
                self.busy_s += time.perf_counter() - t
                self.calls += 1

    def submit(self, item) -> Future:  # type: ignore[override]
        fut: Future = Future()
        if self.error:
            fut.set_exception(RuntimeError(self.error))
            return fut
        try:
            self.q.put_nowait((item, fut))
        except queue.Full:
            self.dropped += 1
            fut.set_exception(RuntimeError(f"{self.name} queue full"))
        return fut


# ─────────────────────────────── pose ──────────────────────────────────


@dataclass
class PoseResult:
    boxes: np.ndarray  # (N,4) xyxy
    conf: np.ndarray  # (N,)
    kps: np.ndarray  # (N,17,3) x,y,conf


class LeanYolo:
    """YOLO inference with GPU pre/post-processing.

    ultralytics' predict() letterboxes and converts each frame on the CPU; with
    1080p frames that dominated latency here (measured 29 ms at batch 1 for the
    *small* model, scaling with batch). This uploads uint8 frames, resizes and
    pads on the GPU, runs the fused network in fp16 and does NMS on the GPU.
    """

    def __init__(self, weights: str, imgsz: int, device: str) -> None:
        import torch
        from ultralytics import YOLO
        y = YOLO(weights)
        self.model = y.model.fuse().to(device).eval().half()
        head = self.model.model[-1]
        self.nc = int(head.nc)
        self.kpt_shape = getattr(head, "kpt_shape", None)
        self.imgsz, self.device, self.torch = imgsz, device, torch

    def __call__(self, frames: list[np.ndarray], conf: float, iou: float = 0.5, classes: list[int] | None = None):
        torch = self.torch
        import torch.nn.functional as F
        from ultralytics.utils.nms import non_max_suppression
        metas, tens = [], []
        for f in frames:
            h, w = f.shape[:2]
            r = self.imgsz / max(h, w)
            nh, nw = int(round(h * r)), int(round(w * r))
            t = torch.from_numpy(f).to(self.device, non_blocking=True).permute(2, 0, 1)[[2, 1, 0]]
            t = F.interpolate(t[None].half() / 255.0, size=(nh, nw), mode="bilinear", antialias=True,
                              align_corners=False)[0]
            tens.append(t)
            metas.append((r, nh, nw))
        H = int(math.ceil(max(m[1] for m in metas) / 32) * 32)
        W = int(math.ceil(max(m[2] for m in metas) / 32) * 32)
        batch = torch.full((len(frames), 3, H, W), 114 / 255.0, device=self.device, dtype=torch.half)
        pads = []
        for i, (t, (r, nh, nw)) in enumerate(zip(tens, metas)):
            py, px = (H - nh) // 2, (W - nw) // 2
            batch[i, :, py:py + nh, px:px + nw] = t
            pads.append((r, px, py))
        with torch.no_grad():
            pred = self.model(batch)
            pred = pred[0] if isinstance(pred, (list, tuple)) else pred
            dets = non_max_suppression(pred.float(), conf, iou, classes=classes, nc=self.nc, max_det=300)
        out = []
        for d, (r, px, py) in zip(dets, pads):
            d = d.cpu().numpy()
            boxes = d[:, :4].copy()
            boxes[:, [0, 2]] = (boxes[:, [0, 2]] - px) / r
            boxes[:, [1, 3]] = (boxes[:, [1, 3]] - py) / r
            kps = None
            if self.kpt_shape is not None:
                kps = d[:, 6:].reshape(len(d), *self.kpt_shape).copy()
                kps[..., 0] = (kps[..., 0] - px) / r
                kps[..., 1] = (kps[..., 1] - py) / r
            out.append((boxes.astype(np.float32), d[:, 4].astype(np.float32), d[:, 5].astype(np.int32), kps))
        return out


def _pose_init(state: dict) -> None:
    s = get_settings()
    m = LeanYolo(str(s.models_dir / s.pose_model), s.pose_imgsz, s.device)
    m([np.zeros((540, 960, 3), np.uint8)], 0.5)
    state["model"] = m


def _pose_batch(state: dict, frames: list[np.ndarray]) -> list[PoseResult]:
    s = get_settings()
    out = []
    for boxes, conf, _cls, kps in state["model"](frames, s.person_conf):
        out.append(PoseResult(boxes, conf, kps if kps is not None else np.zeros((len(boxes), 17, 3), np.float32)))
    return out


# ───────────────────────────── objects ─────────────────────────────────

#: COCO ids we care about -> our label
OBJECT_CLASSES = {24: "backpack", 26: "handbag", 28: "suitcase", 43: "knife", 34: "baseball bat", 76: "scissors"}
WEAPON_LABELS = {"knife", "baseball bat", "scissors"}
BAG_LABELS = {"backpack", "handbag", "suitcase"}


@dataclass
class ObjectDet:
    label: str
    box: tuple[float, float, float, float]
    conf: float


def _obj_init(state: dict) -> None:
    s = get_settings()
    m = LeanYolo(str(s.models_dir / s.object_model), s.object_imgsz, s.device)
    m([np.zeros((540, 960, 3), np.uint8)], 0.5)
    state["model"] = m


def _obj_batch(state: dict, frames: list[np.ndarray]) -> list[list[ObjectDet]]:
    out = []
    for boxes, conf, cls, _ in state["model"](frames, 0.35, classes=list(OBJECT_CLASSES)):
        dets = []
        for b, c, k in zip(boxes, conf, cls):
            label = OBJECT_CLASSES.get(int(k))
            # Weapons need more confidence: a false knife is a false alarm.
            if label and (label not in WEAPON_LABELS or c >= 0.5):
                dets.append(ObjectDet(label, tuple(float(v) for v in b), float(c)))
        out.append(dets)
    return out


# ─────────────────────────────── face ──────────────────────────────────

ARCFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                             [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


@dataclass
class FaceObs:
    box: tuple[float, float, float, float]  # in full-frame coords
    landmarks: np.ndarray  # (5,2) full-frame
    det_score: float
    quality: float
    size_px: float
    frontal: float
    sharpness: float
    embedding: np.ndarray | None = None  # (512,) L2-normalised
    chip: np.ndarray | None = None  # 112x112 BGR
    extras: dict = field(default_factory=dict)


def _ort_session(path: str):
    import onnxruntime as ort
    ort.preload_dlls()
    so = ort.SessionOptions()
    so.log_severity_level = 3
    return ort.InferenceSession(path, so, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])


def _face_init(state: dict) -> None:
    s = get_settings()
    for p in (s.face_det_model, s.face_rec_model):
        if not os.path.exists(p):
            raise FileNotFoundError(p)
    state["det"] = _ort_session(str(s.face_det_model))
    state["rec"] = _ort_session(str(s.face_rec_model))
    state["det_input"] = state["det"].get_inputs()[0].name
    state["rec_input"] = state["rec"].get_inputs()[0].name
    state["providers"] = state["rec"].get_providers()
    state["anchor_cache"] = {}
    _scrfd(state, np.zeros((320, 320, 3), np.uint8), 0.5)
    state["rec"].run(None, {state["rec_input"]: np.zeros((2, 3, 112, 112), np.float32)})


def _scrfd(state: dict, img: np.ndarray, thresh: float, size: int = 320):
    """SCRFD-10GF (insightface det_10g). Returns boxes (N,5) and kps (N,5,2) in img coords."""
    h, w = img.shape[:2]
    scale = size / max(h, w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    canvas = np.zeros((size, size, 3), np.uint8)
    canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
    blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128, (size, size), (127.5, 127.5, 127.5), swapRB=True)
    outs = state["det"].run(None, {state["det_input"]: blob})
    boxes, kpss, scores = [], [], []
    for i, stride in enumerate((8, 16, 32)):
        sc, bb, kp = outs[i][:, 0], outs[i + 3] * stride, outs[i + 6] * stride
        fh, fw = size // stride, size // stride
        key = (fh, fw, stride)
        centers = state["anchor_cache"].get(key)
        if centers is None:
            c = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).astype(np.float32).reshape(-1, 2) * stride
            centers = np.repeat(c, 2, axis=0)
            state["anchor_cache"][key] = centers
        keep = np.where(sc >= thresh)[0]
        if keep.size == 0:
            continue
        c = centers[keep]
        b = bb[keep]
        boxes.append(np.stack([c[:, 0] - b[:, 0], c[:, 1] - b[:, 1], c[:, 0] + b[:, 2], c[:, 1] + b[:, 3]], -1))
        k = kp[keep].reshape(-1, 5, 2) + c[:, None, :]
        kpss.append(k)
        scores.append(sc[keep])
    if not boxes:
        return np.zeros((0, 5), np.float32), np.zeros((0, 5, 2), np.float32)
    boxes = np.concatenate(boxes) / scale
    kpss = np.concatenate(kpss) / scale
    scores = np.concatenate(scores)
    idx = cv2.dnn.NMSBoxes([[float(x1), float(y1), float(x2 - x1), float(y2 - y1)] for x1, y1, x2, y2 in boxes],
                           scores.tolist(), thresh, 0.4)
    idx = np.array(idx).reshape(-1)
    return np.concatenate([boxes[idx], scores[idx, None]], 1), kpss[idx]


def align_face(img: np.ndarray, lm: np.ndarray) -> np.ndarray:
    m, _ = cv2.estimateAffinePartial2D(lm.astype(np.float32), ARCFACE_TEMPLATE, method=cv2.LMEDS)
    return cv2.warpAffine(img, m, (112, 112), borderValue=0.0)


def frontal_score(lm: np.ndarray) -> float:
    """1.0 = looking at the camera. Nose position between the eyes / mouth corners."""
    le, re, nose, lm_, rm = lm
    eye_w = np.linalg.norm(re - le) + 1e-6
    mid_eye = (le + re) / 2
    yaw = abs(nose[0] - mid_eye[0]) / eye_w  # 0 frontal, ~0.5 profile
    mouth_mid = (lm_ + rm) / 2
    face_h = np.linalg.norm(mouth_mid - mid_eye) + 1e-6
    pitch = abs((nose[1] - mid_eye[1]) / face_h - 0.55)
    return float(np.clip(1.0 - 1.8 * yaw - 1.2 * pitch, 0.0, 1.0))


def _embed(state: dict, chips: list[np.ndarray]) -> np.ndarray:
    """AdaFace IR101: RGB, (x-127.5)/127.5, flip-TTA averaged, L2-normalised."""
    batch = []
    for c in chips:
        rgb = cv2.cvtColor(c, cv2.COLOR_BGR2RGB).astype(np.float32)
        x = ((rgb - 127.5) / 127.5).transpose(2, 0, 1)
        batch.append(x)
        batch.append(x[:, :, ::-1].copy())
    out = state["rec"].run(None, {state["rec_input"]: np.stack(batch).astype(np.float32)})[0]
    out = out.reshape(len(chips), 2, -1).mean(1)
    norms = np.linalg.norm(out, axis=1, keepdims=True) + 1e-9
    return (out / norms).astype(np.float32)


def face_analyze(state: dict, image: np.ndarray, regions: list[tuple[float, float, float, float]],
                 embed: bool = True) -> list[FaceObs | None]:
    """For each head region (full-frame coords), find the best face and embed it."""
    s = get_settings()
    H, W = image.shape[:2]
    results: list[FaceObs | None] = []
    to_embed: list[tuple[int, FaceObs]] = []
    for ri, (x1, y1, x2, y2) in enumerate(regions):
        x1i, y1i = max(0, int(x1)), max(0, int(y1))
        x2i, y2i = min(W, int(x2)), min(H, int(y2))
        if x2i - x1i < 16 or y2i - y1i < 16:
            results.append(None)
            continue
        crop = image[y1i:y2i, x1i:x2i]
        dets, kps = _scrfd(state, crop, 0.5)
        if len(dets) == 0:
            results.append(None)
            continue
        j = int(np.argmax((dets[:, 2] - dets[:, 0]) * dets[:, 4]))
        bx = dets[j, :4] + np.array([x1i, y1i, x1i, y1i], np.float32)
        lm = kps[j] + np.array([x1i, y1i], np.float32)
        size = float(min(bx[2] - bx[0], bx[3] - bx[1]))
        chip = align_face(image, lm)
        gray = cv2.cvtColor(chip, cv2.COLOR_BGR2GRAY)
        sharp = float(min(cv2.Laplacian(gray, cv2.CV_64F).var() / 400.0, 1.0))
        front = frontal_score(lm)
        size_q = float(np.clip((size - s.face_min_px * 0.6) / 80.0, 0.0, 1.0))
        q = float(np.clip(0.35 * size_q + 0.25 * sharp + 0.25 * front + 0.15 * float(dets[j, 4]), 0, 1))
        obs = FaceObs(tuple(float(v) for v in bx), lm, float(dets[j, 4]), q, size, front, sharp, chip=chip)
        results.append(obs)
        if embed and size >= s.face_min_px and q >= s.face_min_quality:
            to_embed.append((ri, obs))
    if to_embed:
        embs = _embed(state, [o.chip for _, o in to_embed])
        for (ri, o), e in zip(to_embed, embs):
            o.embedding = e
    return results


def face_embed_image(state: dict, image: np.ndarray) -> list[FaceObs]:
    """Enrolment: every face in a photograph, largest first, embedded."""
    dets, kps = _scrfd(state, image, 0.5, size=640)
    out = []
    for j in np.argsort(-(dets[:, 2] - dets[:, 0]) * (dets[:, 3] - dets[:, 1])) if len(dets) else []:
        lm = kps[j]
        bx = dets[j, :4]
        chip = align_face(image, lm)
        size = float(min(bx[2] - bx[0], bx[3] - bx[1]))
        gray = cv2.cvtColor(chip, cv2.COLOR_BGR2GRAY)
        sharp = float(min(cv2.Laplacian(gray, cv2.CV_64F).var() / 400.0, 1.0))
        front = frontal_score(lm)
        q = float(np.clip(0.35 * min(size / 120, 1) + 0.25 * sharp + 0.25 * front + 0.15 * float(dets[j, 4]), 0, 1))
        out.append(FaceObs(tuple(float(v) for v in bx), lm, float(dets[j, 4]), q, size, front, sharp, chip=chip))
    if out:
        for o, e in zip(out, _embed(state, [o.chip for o in out])):
            o.embedding = e
    return out


# ───────────────────────────── aux: violence + CLIP ────────────────────


def _load_videomae(path: str):
    """VideoMAE with the legacy q_bias/v_bias checkpoint layout remapped.

    transformers>=5 expects query/key/value biases; loading the legacy file
    directly silently re-initialises them at random (measured: AUC collapses).
    """
    import torch
    from transformers import VideoMAEConfig, VideoMAEForVideoClassification
    cfg = VideoMAEConfig.from_pretrained(path)
    m = VideoMAEForVideoClassification(cfg)
    sd_path = os.path.join(path, "pytorch_model.bin")
    sd = torch.load(sd_path, map_location="cpu")
    fixed = {}
    for k, v in sd.items():
        if k.endswith("attention.attention.q_bias"):
            base = k[: -len("q_bias")]
            fixed[base + "query.bias"] = v
            fixed[base + "key.bias"] = torch.zeros_like(v)
        elif k.endswith("attention.attention.v_bias"):
            fixed[k[: -len("v_bias")] + "value.bias"] = v
        else:
            fixed[k] = v
    missing, unexpected = m.load_state_dict(fixed, strict=False)
    if missing or unexpected:
        raise RuntimeError(f"VideoMAE weight mismatch: missing={missing[:3]} unexpected={unexpected[:3]}")
    return m, cfg


def _aux_init(state: dict) -> None:
    import open_clip
    import torch
    s = get_settings()
    m, cfg = _load_videomae(str(s.violence_model_dir))
    state["vmae"] = m.to(s.device).eval().half()
    state["vmae_fight_idx"] = int({v: k for k, v in cfg.id2label.items()}.get("Fight", 0))
    state["vmae_mean"] = torch.tensor([0.485, 0.456, 0.406], device=s.device).view(1, 3, 1, 1)
    state["vmae_std"] = torch.tensor([0.229, 0.224, 0.225], device=s.device).view(1, 3, 1, 1)
    cm, _, pre = open_clip.create_model_and_transforms(s.clip_model, pretrained=s.clip_pretrained)
    state["clip"] = cm.to(s.device).eval().half()
    state["clip_tok"] = open_clip.get_tokenizer(s.clip_model)
    state["clip_mean"] = torch.tensor([0.48145466, 0.4578275, 0.40821073], device=s.device).view(1, 3, 1, 1)
    state["clip_std"] = torch.tensor([0.26862954, 0.26130258, 0.27577711], device=s.device).view(1, 3, 1, 1)
    state["torch"] = torch


def _square_resize(img: np.ndarray, size: int) -> np.ndarray:
    """Short-side resize + centre crop (VideoMAE/CLIP eval transform)."""
    h, w = img.shape[:2]
    sc = size / min(h, w)
    r = cv2.resize(img, (max(size, int(round(w * sc))), max(size, int(round(h * sc)))), interpolation=cv2.INTER_AREA)
    y = (r.shape[0] - size) // 2
    x = (r.shape[1] - size) // 2
    return r[y:y + size, x:x + size]


def violence_score(state: dict, frames_bgr: list[np.ndarray]) -> dict:
    """16 BGR frames -> {'logit': fight-minus-nonfight logit, 'prob': P(fight)}."""
    torch = state["torch"]
    s = get_settings()
    if len(frames_bgr) != 16:
        idx = np.linspace(0, len(frames_bgr) - 1, 16).astype(int)
        frames_bgr = [frames_bgr[i] for i in idx]
    arr = np.stack([cv2.cvtColor(_square_resize(f, 224), cv2.COLOR_BGR2RGB) for f in frames_bgr])
    x = torch.from_numpy(arr).to(s.device).permute(0, 3, 1, 2).float() / 255.0
    x = ((x - state["vmae_mean"]) / state["vmae_std"]).half().unsqueeze(0)
    with torch.no_grad():
        logits = state["vmae"](pixel_values=x).logits.float()[0]
    fi = state["vmae_fight_idx"]
    other = 1 - fi
    return {"logit": float(logits[fi] - logits[other]), "prob": float(torch.softmax(logits, -1)[fi])}


def clip_images(state: dict, crops_bgr: list[np.ndarray]) -> np.ndarray:
    torch = state["torch"]
    s = get_settings()
    arr = np.stack([cv2.cvtColor(_square_resize(c, 224), cv2.COLOR_BGR2RGB) for c in crops_bgr])
    x = torch.from_numpy(arr).to(s.device).permute(0, 3, 1, 2).float() / 255.0
    x = ((x - state["clip_mean"]) / state["clip_std"]).half()
    with torch.no_grad():
        f = state["clip"].encode_image(x).float()
    f = f / f.norm(dim=-1, keepdim=True)
    return f.cpu().numpy().astype(np.float16)


def clip_text(state: dict, texts: list[str]) -> np.ndarray:
    torch = state["torch"]
    s = get_settings()
    with torch.no_grad():
        f = state["clip"].encode_text(state["clip_tok"](texts).to(s.device)).float()
    f = f / f.norm(dim=-1, keepdim=True)
    return f.cpu().numpy().astype(np.float16)


# ───────────────────────────── registry ────────────────────────────────


class ModelHub:
    def __init__(self) -> None:
        self.pose = BatchWorker("pose", _pose_init, _pose_batch, max_batch=4)
        self.objects = BatchWorker("objects", _obj_init, _obj_batch, max_batch=4)
        self.face = Worker("face", _face_init)
        self.aux = Worker("aux", _aux_init)

    def wait_ready(self, timeout: float = 180.0) -> dict:
        t = time.time()
        for w in (self.pose, self.objects, self.face, self.aux):
            w.ready.wait(max(0.1, timeout - (time.time() - t)))
        return self.status()

    def status(self) -> dict:
        out = {}
        for w in (self.pose, self.objects, self.face, self.aux):
            out[w.name] = {"ready": w.ready.is_set() and not w.error, "error": w.error, "calls": w.calls,
                           "busy_s": round(w.busy_s, 2), "queue": w.q.qsize(), "dropped": w.dropped}
        prov = self.face.state.get("providers")
        if prov:
            out["face"]["providers"] = prov
            out["face"]["gpu"] = prov[0] == "CUDAExecutionProvider"
        return out


_hub: ModelHub | None = None


def hub() -> ModelHub:
    global _hub
    if _hub is None:
        _hub = ModelHub()
    return _hub
