"""Client for the existing FRS backend on port 8000.

Contract with that system:
- It is READ-ONLY to us. We never call its enrol/delete/settings/reindex/
  acknowledge/visitor-clear routes. The one POST we make is /api/match/video,
  a search; FRS records each search as a match_event and keeps the upload, so
  callers must rate-limit (see IdentityService).
- Its camera RTSP URLs carry plaintext credentials; we redact them before they
  reach our API, DB or logs.
- It has no auth and a self-signed cert; we talk to it over loopback only.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from vigil.config import get_settings

log = logging.getLogger("vigil.frs")
_CRED = re.compile(r"(://)([^:/@]+):([^@]+)@")

# FRS routes we are allowed to proxy media from (display of watchlist photos/evidence).
MEDIA_PREFIXES = ("/media/uploads/criminals/", "/media/alerts/", "/media/uploads/queries/")


def redact(url: str | None) -> str | None:
    return _CRED.sub(r"\1\2:<redacted>@", url) if url else url


class FRSClient:
    def __init__(self) -> None:
        s = get_settings()
        self.base = s.frs_url.rstrip("/")
        self.enabled = s.frs_enabled
        self._client = httpx.AsyncClient(base_url=self.base, verify=s.frs_verify_tls, timeout=15.0)
        self._sync = httpx.Client(base_url=self.base, verify=s.frs_verify_tls, timeout=15.0)
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self.match_calls = 0

    async def close(self) -> None:
        await self._client.aclose()
        self._sync.close()

    async def _get(self, path: str, **params) -> Any:
        r = await self._client.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        self.last_ok = time.time()
        return r.json()

    async def health(self) -> dict:
        try:
            h = await self._get("/api/health")
            self.last_error = None
            return {"reachable": True, "status": h.get("status"), "gpu": h.get("gpu"),
                    "gpu_degraded": h.get("gpu_degraded"), "faiss_vectors": h.get("faiss_vectors")}
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            return {"reachable": False, "error": str(e)}

    async def cameras(self) -> list[dict]:
        cams = await self._get("/api/cctv/cameras")
        out = []
        for c in cams:
            out.append({"id": c["id"], "name": c.get("name"), "location": c.get("location"),
                        "latitude": c.get("latitude"), "longitude": c.get("longitude"),
                        "is_active": c.get("is_active"), "resolution": c.get("resolution"),
                        "fps": c.get("fps"), "url": redact(c.get("rtsp_url"))})
        return out

    async def camera_stats(self) -> dict:
        st = await self._get("/api/cctv/stats")
        for c in st.get("cameras", []):
            c["url"] = redact(c.get("url"))
        return st

    async def criminals(self) -> list[dict]:
        rows = await self._get("/api/criminals")
        return [{"id": r["id"], "name": r["name"], "group": r.get("group"), "subgroup": r.get("subgroup"),
                 "metadata": r.get("metadata", {}), "image_count": r.get("image_count"),
                 "photo_url": (r.get("images") or [{}])[0].get("url")} for r in rows]

    async def criminal(self, criminal_id: str) -> dict:
        return await self._get(f"/api/criminal/{criminal_id}")

    async def criminal_detections(self, criminal_id: str, limit: int = 50) -> dict:
        return await self._get(f"/api/criminal/{criminal_id}/detections", limit=limit)

    async def detections(self, limit: int = 50, camera_id: str | None = None) -> dict:
        return await self._get("/api/detections", limit=limit, camera_id=camera_id)

    async def alerts(self, limit: int = 50) -> list:
        return await self._get("/api/alerts", limit=limit)

    async def stats(self) -> dict:
        return await self._get("/api/stats")

    async def metrics(self) -> dict:
        return await self._get("/api/metrics")

    async def history(self, limit: int = 50) -> list:
        """FRS's own match log (every search anyone ran, VIGIL's included)."""
        return await self._get("/api/history", limit=limit)

    async def media(self, path: str) -> tuple[bytes, str]:
        if not path.startswith(MEDIA_PREFIXES) or ".." in path:
            raise ValueError("path not proxyable")
        r = await self._client.get(path)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "application/octet-stream")

    def relay_url(self, frs_camera_id: str) -> str:
        s = get_settings()
        return f"{self.base}/api/cctv/cameras/{frs_camera_id}/stream?fps={s.frs_relay_fps}&width={s.frs_relay_width}"

    def match_face_sync(self, jpeg: bytes) -> dict | None:
        """1:N watchlist search for one face image. Called from a worker thread.

        Returns {outcome, matched, criminal_id, name, score, top_k, latency_ms} where outcome is
        match | no_match | no_face | error, or None when FRS integration is disabled.
        FRS applies its own two-recogniser agreement and open-set gates; `matched` is its verdict.
        """
        if not self.enabled:
            return None
        t = time.perf_counter()
        base = {"matched": False, "criminal_id": None, "name": None, "score": None, "top_k": []}
        try:
            self.match_calls += 1
            r = self._sync.post("/api/match/video", files={"frame": ("vigil_face.jpg", jpeg, "image/jpeg")},
                                data={"top_k": "3"})
            ms = round((time.perf_counter() - t) * 1000, 1)
            if r.status_code in (400, 422):  # FRS: no usable face in the crop
                return {**base, "outcome": "no_face", "latency_ms": ms}
            r.raise_for_status()
            self.last_ok = time.time()
            matches = r.json().get("matches") or []
            if not matches:
                return {**base, "outcome": "no_face", "latency_ms": ms}
            best = max(matches, key=lambda m: m.get("confidence", 0.0))
            matched = bool(best.get("matched"))
            return {"outcome": "match" if matched else "no_match", "matched": matched,
                    "criminal_id": best.get("criminal_id") if matched else None,
                    "name": best.get("identity") if matched else None, "score": float(best.get("confidence", 0.0)),
                    "top_k": [{"name": t_["name"], "criminal_id": t_["criminal_id"], "score": t_["score"]}
                              for t_ in best.get("top_k", [])[:3]], "latency_ms": ms}
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            log.warning("FRS match failed: %s", e)
            return {**base, "outcome": "error", "error": str(e)[:300],
                    "latency_ms": round((time.perf_counter() - t) * 1000, 1)}


_frs: FRSClient | None = None


def frs() -> FRSClient:
    global _frs
    if _frs is None:
        _frs = FRSClient()
    return _frs
