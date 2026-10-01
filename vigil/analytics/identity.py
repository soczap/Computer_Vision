"""Identity resolution: persistent person IDs from face evidence pooled over a track.

Rules, in the order they are applied:
- One frame is never an identity. A track's face observations are pooled
  (quality-weighted mean of its best embeddings) before any gallery search.
- A match needs cosine >= threshold AND a margin over the runner-up identity.
- A track locks onto an identity after two agreeing searches; a locked track
  is re-checked periodically and unlocked after repeated contradiction (tracker
  ID swaps happen; a wrong name must not outlive the evidence for it).
- An unmatched track with enough good observations becomes a new UNKNOWN
  identity (P-xxxxx) so the same person keeps the same ID when they return.
- Watchlist status comes from the FRS backend (its two-recogniser agreement
  and open-set gates), queried once per identity per interval at the best face.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import cv2
import numpy as np
from sqlalchemy import func, select, update

from vigil import runtime
from vigil.bus import bus
from vigil.config import get_settings
from vigil.db import FaceVector, Identity, Track, session

log = logging.getLogger("vigil.identity")


@dataclass
class IdentityMeta:
    id: str
    display_name: str | None
    kind: str
    category: str
    frs_criminal_id: str | None = None
    frs_name: str | None = None
    frs_checked_at: float = 0.0
    frs_checked_q: float = 0.0
    best_face_q: float = 0.0
    auto_vectors: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.frs_name:
            return f"{self.display_name or self.frs_name} ⚑"
        return self.display_name or self.id


class IdentityService:
    def __init__(self) -> None:
        self.s = get_settings()
        self._lock = threading.RLock()
        self.meta: dict[str, IdentityMeta] = {}
        self._vecs = np.zeros((0, 512), np.float32)
        self._owner: list[str] = []
        self._seq = 0
        self._frs_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="frs-match")
        self._frs_times: list[float] = []
        self.stats = {"matches": 0, "new_identities": 0, "frs_checks": 0, "frs_hits": 0, "unlocks": 0}

    # ── loading ──
    async def load(self) -> None:
        async with session() as db:
            # Demo identities are synthetic and have no vectors; keep them out of matching entirely.
            idents = (await db.execute(select(Identity).where(Identity.merged_into.is_(None),
                                                              Identity.is_demo.is_(False)))).scalars().all()
            vecs = (await db.execute(select(FaceVector))).scalars().all()
            max_seq = 0
            for i in idents:
                self.meta[i.id] = IdentityMeta(i.id, i.display_name, i.kind, i.category, i.frs_criminal_id,
                                               i.frs_name, i.frs_checked_at.timestamp() if i.frs_checked_at else 0.0,
                                               i.frs_checked_q or 0.0, i.best_face_quality)
                if i.id.startswith("P-"):
                    try:
                        max_seq = max(max_seq, int(i.id[2:]))
                    except ValueError:
                        pass
            self._seq = max_seq
            rows, owners = [], []
            for v in vecs:
                if v.identity_id in self.meta:
                    rows.append(np.frombuffer(v.vector, np.float32))
                    owners.append(v.identity_id)
                    if v.source == "auto":
                        self.meta[v.identity_id].auto_vectors += 1
            with self._lock:
                self._vecs = np.stack(rows) if rows else np.zeros((0, 512), np.float32)
                self._owner = owners
        log.info("identity gallery loaded: %d identities, %d vectors", len(self.meta), len(self._owner))

    def next_id(self) -> str:
        with self._lock:
            self._seq += 1
            return f"P-{self._seq:05d}"

    # ── search ──
    def search(self, emb: np.ndarray, exclude: set[str] | None = None) -> list[tuple[str, float]]:
        """Per-identity score = max cosine over its vectors. Sorted desc."""
        with self._lock:
            if len(self._owner) == 0:
                return []
            sims = self._vecs @ emb
            best: dict[str, float] = {}
            for o, sc in zip(self._owner, sims):
                if exclude and o in exclude:
                    continue
                if sc > best.get(o, -1.0):
                    best[o] = float(sc)
        return sorted(best.items(), key=lambda kv: -kv[1])

    def _add_vectors(self, identity_id: str, embs: list[np.ndarray]) -> None:
        with self._lock:
            self._vecs = np.concatenate([self._vecs, np.stack(embs).astype(np.float32)]) if len(self._owner) \
                else np.stack(embs).astype(np.float32)
            self._owner.extend([identity_id] * len(embs))

    def remove_identity(self, identity_id: str) -> None:
        with self._lock:
            keep = [i for i, o in enumerate(self._owner) if o != identity_id]
            self._vecs = self._vecs[keep] if keep else np.zeros((0, 512), np.float32)
            self._owner = [self._owner[i] for i in keep]
            self.meta.pop(identity_id, None)

    def reassign(self, src: str, dst: str) -> None:
        with self._lock:
            self._owner = [dst if o == src else o for o in self._owner]
            self.meta.pop(src, None)

    @staticmethod
    def pooled(face_buf: list[tuple[float, np.ndarray]], k: int = 5) -> np.ndarray | None:
        if not face_buf:
            return None
        top = sorted(face_buf, key=lambda qe: -qe[0])[:k]
        w = np.array([q for q, _ in top], np.float32)
        v = (np.stack([e for _, e in top]) * w[:, None]).sum(0)
        return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)

    # ── the per-track decision ──
    def observe(self, tr, obs, frame: np.ndarray) -> str | None:
        """Feed one face observation for a track. Returns a change marker or None.

        Called from the camera thread. Mutates the track state.
        """
        s = self.s
        if obs is None or obs.embedding is None:
            return None
        if tr.identity_locked:
            # Judge a locked track on THIS observation: the pooled buffer still holds the
            # original person's views and would mask a tracker ID swap.
            own = dict(self.search(obs.embedding)).get(tr.identity_id, 0.0)
            if own >= s.face_match_threshold:
                tr.contradictions = 0
                self._remember(tr, obs, frame)
                # Display the real similarity: smoothed per-observation cosine, never a ratchet.
                tr.identity_score = own if tr.identity_method == "new" else 0.7 * tr.identity_score + 0.3 * own
                tr.identity_method = "face"
                self._maybe_enrich(tr.identity_id, obs, own)
                return None
            if own < s.face_match_threshold - 0.1 and obs.quality >= 0.5:
                tr.contradictions += 1
            if tr.contradictions >= 3:
                log.info("track %s unlocked from %s (contradicted)", tr.uid, tr.identity_id)
                self.stats["unlocks"] += 1
                tr.identity_locked, tr.identity_id, tr.identity_votes, tr.contradictions = False, None, 0, 0
                tr.face_buf = [(obs.quality, obs.embedding)]
                return "unlocked"
            return None

        self._remember(tr, obs, frame)
        pooled = self.pooled(tr.face_buf)
        if pooled is None:
            return None
        ranked = self.search(pooled)
        best_id, best = ranked[0] if ranked else (None, 0.0)
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        confident = best_id is not None and best >= s.face_match_threshold and (best - second) >= s.face_match_margin

        if confident:
            if tr.identity_id == best_id:
                tr.identity_votes += 1
            else:
                tr.identity_id, tr.identity_votes = best_id, 1
            tr.identity_score, tr.identity_method = best, "face"
            if tr.identity_votes >= 2:
                tr.identity_locked = True
                self.stats["matches"] += 1
                self._maybe_enrich(best_id, obs, best)
                return "matched"
            return None

        good = [qe for qe in tr.face_buf if qe[0] >= 0.5]
        if len(good) >= s.face_obs_for_new_identity and best < s.face_new_identity_max_sim:
            new_id = self.next_id()
            embs = [e for _, e in sorted(good, key=lambda qe: -qe[0])[:3]]
            meta = IdentityMeta(new_id, None, "unknown", "none", best_face_q=tr.best_face_q)
            with self._lock:
                self.meta[new_id] = meta
            self._add_vectors(new_id, embs)
            # A new identity has no match score yet (its vectors come from this very track).
            tr.identity_id, tr.identity_score, tr.identity_method = new_id, 0.0, "new"
            tr.identity_locked, tr.identity_votes = True, 2
            self.stats["new_identities"] += 1
            runtime.submit(self._persist_new(new_id, embs, [q for q, _ in sorted(good, key=lambda qe: -qe[0])[:3]],
                                             tr.best_face_jpg, tr.camera_id))
            bus.publish_threadsafe("identity.created", {"id": new_id, "camera_id": tr.camera_id})
            return "created"
        return None

    def _remember(self, tr, obs, frame: np.ndarray) -> None:
        tr.face_buf.append((obs.quality, obs.embedding))
        if len(tr.face_buf) > 10:
            tr.face_buf.sort(key=lambda qe: -qe[0])
            tr.face_buf = tr.face_buf[:10]
        self._update_best_face(tr, obs, frame)

    def _maybe_enrich(self, identity_id: str, obs, score: float) -> None:
        """Add a diverse, high-quality view to an identity (pose coverage), bounded and conservative."""
        m = self.meta.get(identity_id)
        if m is None or obs.quality < 0.6 or score < self.s.face_match_threshold + 0.1:
            return
        if m.auto_vectors >= self.s.face_max_auto_vectors:
            return
        with self._lock:
            own = [i for i, o in enumerate(self._owner) if o == identity_id]
            redundant = bool(own) and float((self._vecs[own] @ obs.embedding).max()) > 0.85
        if redundant:
            return  # not a new view
        m.auto_vectors += 1
        self._add_vectors(identity_id, [obs.embedding])
        runtime.submit(self._persist_vectors(identity_id, [obs.embedding], [obs.quality], "auto"))

    def _update_best_face(self, tr, obs, frame: np.ndarray) -> None:
        if obs.quality <= tr.best_face_q:
            return
        tr.best_face_q = obs.quality
        tr.best_face_px = obs.size_px
        x1, y1, x2, y2 = obs.box
        w, h = x2 - x1, y2 - y1
        H, W = frame.shape[:2]
        # Portrait crop for display.
        px1, py1 = max(0, int(x1 - w * 0.35)), max(0, int(y1 - h * 0.45))
        px2, py2 = min(W, int(x2 + w * 0.35)), min(H, int(y2 + h * 0.3))
        ok, jpg = cv2.imencode(".jpg", frame[py1:py2, px1:px2], [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            tr.best_face_jpg = jpg.tobytes()
        # Wider crop for FRS: its own detector must find the face with context.
        fx1, fy1 = max(0, int(x1 - w)), max(0, int(y1 - h))
        fx2, fy2 = min(W, int(x2 + w)), min(H, int(y2 + h))
        ok, jpg2 = cv2.imencode(".jpg", frame[fy1:fy2, fx1:fx2], [cv2.IMWRITE_JPEG_QUALITY, 95])
        if ok:
            tr.best_face_frame_crop = jpg2.tobytes()

    # ── FRS watchlist ──
    def maybe_check_watchlist(self, tr) -> None:
        s = self.s
        if not s.frs_enabled or tr.identity_id is None or tr.best_face_frame_crop is None or tr.frs_submitted:
            return
        if tr.best_face_px < s.frs_watchlist_min_face_px or tr.best_face_q < 0.55:
            return
        m = self.meta.get(tr.identity_id)
        if m is None:
            return
        now = time.time()
        since = now - m.frs_checked_at
        if since < s.frs_watchlist_check_interval_s:
            return
        if m.frs_checked_at and tr.best_face_q < m.frs_checked_q + 0.1 and since < s.frs_watchlist_recheck_s:
            return  # nothing new to show FRS; every search is a row in its match log
        # Global budget: FRS stores every search, so never flood it.
        self._frs_times = [t for t in self._frs_times if now - t < 60]
        if len(self._frs_times) >= 20:
            return
        self._frs_times.append(now)
        m.frs_checked_at = now
        m.frs_checked_q = tr.best_face_q
        tr.frs_submitted = True
        self._frs_pool.submit(self._frs_check, tr.identity_id, tr.best_face_frame_crop, tr.camera_id, tr.uid)

    def _frs_check(self, identity_id: str, jpeg: bytes, camera_id: str, track_uid: str) -> None:
        from vigil.frs_client import frs
        self.stats["frs_checks"] += 1
        res = frs().match_face_sync(jpeg)
        m = self.meta.get(identity_id)
        from vigil.services import record_frs_search
        runtime.submit(record_frs_search(res, identity_id, camera_id, track_uid, jpeg, "auto"))
        if res is not None and res.get("outcome") == "error":
            if m is not None:
                m.frs_checked_at = 0.0  # FRS unreachable: allow a retry instead of waiting the interval
            return
        runtime.submit(self._persist_frs(identity_id, res, m.frs_checked_q if m else None))
        if res and res["matched"] and m is not None:
            self.stats["frs_hits"] += 1
            first_hit = m.frs_criminal_id != res["criminal_id"]
            m.frs_criminal_id, m.frs_name = res["criminal_id"], res["name"]
            if first_hit:
                bus.publish_threadsafe("identity.watchlist", {
                    "identity_id": identity_id, "camera_id": camera_id, "track_uid": track_uid,
                    "frs": res, "face_jpg": jpeg})

    # ── persistence (run on the loop) ──
    async def _persist_new(self, identity_id, embs, qualities, face_jpg, camera_id) -> None:
        path = None
        if face_jpg:
            p = self.s.media_dir / "faces" / f"{identity_id}.jpg"
            p.write_bytes(face_jpg)
            path = f"faces/{identity_id}.jpg"
        now = datetime.now(timezone.utc)
        async with session() as db:
            db.add(Identity(id=identity_id, kind="unknown", first_seen=now, last_seen=now, last_camera_id=camera_id,
                            best_face_path=path, best_face_quality=float(max(qualities))))
            await db.flush()
            for e, q in zip(embs, qualities):
                db.add(FaceVector(identity_id=identity_id, vector=e.astype(np.float32).tobytes(), quality=float(q),
                                  source="auto"))
            await db.commit()

    async def _persist_vectors(self, identity_id, embs, qualities, source) -> None:
        async with session() as db:
            if await db.get(Identity, identity_id) is None:
                return
            for e, q in zip(embs, qualities):
                db.add(FaceVector(identity_id=identity_id, vector=e.astype(np.float32).tobytes(), quality=float(q),
                                  source=source))
            await db.commit()

    async def _persist_frs(self, identity_id: str, res: dict | None, checked_q: float | None = None) -> None:
        async with session() as db:
            vals = {"frs_checked_at": datetime.now(timezone.utc), "frs_checked_q": checked_q}
            if res and res["matched"]:
                vals.update(frs_criminal_id=res["criminal_id"], frs_name=res["name"], frs_score=res["score"])
            await db.execute(update(Identity).where(Identity.id == identity_id).values(**vals))
            await db.commit()

    async def record_sighting(self, tr_summary: dict) -> None:
        """Called when a track closes or gets an identity: update identity last_seen/sightings/best face."""
        iid = tr_summary.get("identity_id")
        if not iid:
            return
        async with session() as db:
            ident = await db.get(Identity, iid)
            if ident is None:
                return
            ts = datetime.fromtimestamp(tr_summary["last_ts"], timezone.utc)
            if ident.last_seen is None or ts > ident.last_seen:
                ident.last_seen = ts
                ident.last_camera_id = tr_summary["camera_id"]
            if ident.first_seen is None:
                ident.first_seen = datetime.fromtimestamp(tr_summary["first_ts"], timezone.utc)
            ident.sightings = (await db.execute(select(func.count()).select_from(Track).where(
                Track.identity_id == iid))).scalar_one()
            fq = tr_summary.get("best_face_q") or 0.0
            if tr_summary.get("best_face_path") and fq > (ident.best_face_quality or 0.0):
                ident.best_face_quality = fq
                ident.best_face_path = tr_summary["best_face_path"]
            await db.commit()


_svc: IdentityService | None = None


def identities() -> IdentityService:
    global _svc
    if _svc is None:
        _svc = IdentityService()
    return _svc
