"""VIGIL Video Analytics — application entry point.

Run:  .venv/bin/python -m vigil.main          (reads .env / VIGIL_* env vars)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from vigil import runtime
from vigil.agents.llm import llm
from vigil.agents.orchestrator import orchestrator
from vigil.analytics.identity import identities
from vigil.api import analytics, auth, cameras, events, frs as frs_api, identities as identities_api, live, system
from vigil.bus import bus
from vigil.config import ROOT, get_settings
from vigil.db import init_db
from vigil.frs_client import frs
from vigil.logging_setup import setup_logging
from vigil.perception.engine import engine
from vigil.perception.models import hub
from vigil.security import bootstrap_admin

log = logging.getLogger("vigil")
DIST = ROOT / "frontend" / "dist"


async def _start_cameras_when_ready() -> None:
    status = await asyncio.to_thread(hub().wait_ready, 300)
    bad = {k: v["error"] for k, v in status.items() if v.get("error")}
    if bad:
        log.error("model workers failed: %s", bad)
    if status.get("face", {}).get("gpu") is False:
        log.warning("FACE MODELS ARE ON CPU — GPU context unavailable (unified-memory contention?). "
                    "Recognition will be 10-25x slower.")
    await engine.start_all()
    log.info("cameras started: %s", list(engine.workers))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    loop = asyncio.get_running_loop()
    bus.bind_loop(loop)
    runtime.bind(loop)
    await init_db()
    await bootstrap_admin()
    await identities().load()
    hub()  # model workers start loading in their own threads
    await orchestrator().start()
    starter = asyncio.create_task(_start_cameras_when_ready())
    log.info("VIGIL up on port %s", get_settings().port)
    yield
    starter.cancel()
    engine.stop_all()
    await orchestrator().stop()
    await frs().close()
    await llm().close()


def create_app() -> FastAPI:
    app = FastAPI(title="VIGIL Video Analytics", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    for r in (auth.router, cameras.router, events.router, identities_api.router, analytics.router, frs_api.router,
              system.router, live.router):
        app.include_router(r)

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith(("api/", "ws/", "media/")):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            f = (DIST / full_path).resolve()
            if full_path and f.is_file() and f.is_relative_to(DIST.resolve()):
                return FileResponse(f)
            return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
    return app


app = create_app()


def main() -> None:
    import uvicorn
    s = get_settings()
    uvicorn.run("vigil.main:app", host=s.host, port=s.port, workers=1, log_config=None,
                ssl_certfile=s.tls_cert, ssl_keyfile=s.tls_key, ws_max_size=8 * 1024 * 1024)


if __name__ == "__main__":
    main()
