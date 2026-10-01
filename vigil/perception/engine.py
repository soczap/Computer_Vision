"""EngineManager: owns camera workers; (re)configures them from the database."""
from __future__ import annotations

import logging

from sqlalchemy import select

from vigil.analytics.signals import merge_rules
from vigil.db import Camera, Setting, Zone, session
from vigil.perception.models import hub
from vigil.perception.worker import CameraWorker

log = logging.getLogger("vigil.engine")


async def global_rules() -> dict:
    async with session() as db:
        row = await db.get(Setting, "rules")
        return row.value if row else {}


class EngineManager:
    def __init__(self) -> None:
        self.workers: dict[str, CameraWorker] = {}

    async def _config(self, camera_id: str) -> tuple[dict, list[dict], dict] | None:
        async with session() as db:
            cam = await db.get(Camera, camera_id)
            if cam is None:
                return None
            zones = (await db.execute(select(Zone).where(Zone.camera_id == camera_id, Zone.enabled.is_(True)))).scalars().all()
            g = await db.get(Setting, "rules")
            rules = merge_rules(g.value if g else {}, (cam.config or {}).get("rules"))
            camd = {"id": cam.id, "name": cam.name, "source_type": cam.source_type, "source_uri": cam.source_uri,
                    "loop": cam.loop, "realtime": cam.realtime, "analysis_fps": cam.analysis_fps,
                    "enabled": cam.enabled}
            return camd, [{"id": z.id, "name": z.name, "kind": z.kind, "polygon": z.polygon, "rules": z.rules}
                          for z in zones], rules

    async def start_all(self) -> None:
        async with session() as db:
            ids = [c.id for c in (await db.execute(select(Camera).where(Camera.enabled.is_(True)))).scalars()]
        for cid in ids:
            await self.start(cid)

    async def start(self, camera_id: str) -> bool:
        await self.stop(camera_id)
        cfg = await self._config(camera_id)
        if cfg is None:
            return False
        camd, zones, rules = cfg
        if not camd["enabled"] or camd["source_type"] == "demo":
            return False
        hub()  # make sure models are loading
        w = CameraWorker(camd, zones, rules)
        self.workers[camera_id] = w
        w.start()
        log.info("camera %s started (%s)", camera_id, camd["source_type"])
        return True

    async def stop(self, camera_id: str) -> None:
        w = self.workers.pop(camera_id, None)
        if w is not None:
            w.stop()

    async def reload(self, camera_id: str) -> None:
        """Apply new zones/rules: restart the worker (tracks restart; identities persist)."""
        if camera_id in self.workers:
            await self.start(camera_id)

    async def reload_all(self) -> None:
        for cid in list(self.workers):
            await self.start(cid)

    def stop_all(self) -> None:
        for w in self.workers.values():
            w.stop()

    def worker(self, camera_id: str) -> CameraWorker | None:
        return self.workers.get(camera_id)

    def stats(self) -> dict:
        return {cid: w.stats() for cid, w in self.workers.items()}


engine = EngineManager()
