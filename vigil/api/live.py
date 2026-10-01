"""WebSockets: live annotated video per camera, and the realtime event/agent stream."""
from __future__ import annotations

import asyncio
import dataclasses
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from vigil.bus import bus
from vigil.perception.engine import engine
from vigil.security import ws_user

log = logging.getLogger("vigil.ws")
router = APIRouter()
STREAM_TOPICS = ("event.created", "event.updated", "incident.created", "incident.updated", "agent.run", "agent.step",
                 "notification", "camera.status", "identity.created", "track.closed", "frs.search")


@router.websocket("/ws/live/{camera_id}")
async def live(ws: WebSocket, camera_id: str):
    try:
        await ws_user(ws)
    except Exception:  # noqa: BLE001
        await ws.close(code=4401)
        return
    await ws.accept()
    w = engine.worker(camera_id)
    if w is None:
        await ws.send_json({"error": "camera not running"})
        await ws.close()
        return
    w.live.viewers += 1
    sent = -1
    # Client acks each frame; we never queue more than one in flight, so slow links get fewer, fresh frames.
    inflight = False

    async def reader():
        nonlocal inflight
        while True:
            m = await ws.receive_text()
            if m == "ack":
                inflight = False

    rt = asyncio.create_task(reader())
    try:
        while True:
            cur = engine.worker(camera_id)
            if cur is not w:  # camera restarted (zones/rules changed): follow the new worker
                w.live.viewers -= 1
                if cur is None:
                    await ws.send_json({"error": "camera stopped"})
                    break
                w = cur
                w.live.viewers += 1
                sent = -1
            if rt.done():
                break
            if not inflight and w.live.seq != sent and w.live.payload is not None:
                with w.live.lock:
                    payload, sent = w.live.payload, w.live.seq
                await ws.send_bytes(payload)
                inflight = True
            await asyncio.sleep(0.02)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        w.live.viewers = max(0, w.live.viewers - 1)
        rt.cancel()


@router.websocket("/ws/ingest/{camera_id}")
async def ingest(ws: WebSocket, camera_id: str):
    """Browser webcam -> VIGIL. Client sends JPEG frames (binary); server replies:
    {"type":"ack"} per accepted frame (client keeps <=2 in flight), {"type":"overlay", ...header}
    whenever a newly analysed frame is ready, and {"type":"status", ...} once a second."""
    import cv2
    import numpy as np
    try:
        p = await ws_user(ws)
    except Exception:  # noqa: BLE001
        await ws.close(code=4401)
        return
    if not p.has("analyst"):
        await ws.close(code=4403)
        return
    await ws.accept()
    w = engine.worker(camera_id)
    if w is None or getattr(w, "source", None) is None or getattr(w.source, "kind", "") != "browser":
        await ws.send_json({"type": "error", "error": "not a running browser camera"})
        await ws.close()
        return
    src = w.source
    src.clients += 1
    sent_seq, last_status = -1, 0.0
    loop = asyncio.get_running_loop()

    async def pusher():
        nonlocal sent_seq, last_status
        while True:
            cur = engine.worker(camera_id)
            if cur is not None and cur.live.seq != sent_seq and cur.live.header is not None:
                with cur.live.lock:
                    hdr, sent_seq = cur.live.header, cur.live.seq
                await ws.send_text('{"type":"overlay",' + hdr.decode()[1:])
            if loop.time() - last_status > 1.0 and cur is not None:
                last_status = loop.time()
                st = cur.stats()
                await ws.send_json({"type": "status", **{k: st.get(k) for k in (
                    "status", "fps", "latency_ms", "active_tracks", "faces", "tracks_total", "idle")}})
            await asyncio.sleep(0.03)

    pt = asyncio.create_task(pusher())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if not data:
                continue
            if len(data) > 3_000_000:
                await ws.send_json({"type": "error", "error": "frame too large"})
                continue
            img = await asyncio.to_thread(cv2.imdecode, np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            cur = engine.worker(camera_id)
            if img is not None and cur is not None and getattr(cur.source, "kind", "") == "browser":
                cur.source.push(img)
            await ws.send_json({"type": "ack"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        pt.cancel()
        src.clients = max(0, src.clients - 1)


@router.websocket("/ws/stream")
async def stream(ws: WebSocket):
    try:
        await ws_user(ws)
    except Exception:  # noqa: BLE001
        await ws.close(code=4401)
        return
    await ws.accept()
    q = bus.subscribe(*STREAM_TOPICS, maxsize=1000)
    try:
        while True:
            msg = await q.get()
            data = msg["data"]
            if dataclasses.is_dataclass(data):
                data = dataclasses.asdict(data)
            await ws.send_json(jsonable_encoder({"topic": msg["topic"], "data": data},
                                                custom_encoder={bytes: lambda b: None}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)
