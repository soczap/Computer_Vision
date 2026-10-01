"""Simulate the browser webcam: stream a video's frames to /ws/ingest exactly as the UI does
(JPEG binary frames, <=2 in flight, overlays and status coming back on the same socket)."""
import asyncio, json, ssl, sys, time
import cv2
sys.path.insert(0, "scripts")
from api import c
import websockets

VIDEO = sys.argv[1]
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 40
cam = c.post("/api/demo/webcam").json()
cid = cam["id"]
tok = c.headers["Authorization"].split()[1]

async def main():
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    async with websockets.connect(f"wss://127.0.0.1:8090/ws/ingest/{cid}?token={tok}", ssl=ctx, max_size=4_000_000) as ws:
        inflight, sent, overlays, statuses, labels = 0, 0, 0, None, {}
        t0 = time.time(); next_t = t0
        async def reader():
            nonlocal inflight, overlays, statuses
            async for m in ws:
                d = json.loads(m)
                if d["type"] == "ack": inflight -= 1
                elif d["type"] == "overlay":
                    overlays += 1
                    for tr in d["tracks"]:
                        labels[(tr["label"], tr["kind"])] = labels.get((tr["label"], tr["kind"]), 0) + 1
                elif d["type"] == "status": statuses = d
                elif d["type"] == "error": print("ERROR", d)
        rt = asyncio.create_task(reader())
        while time.time() - t0 < SECONDS:
            ok, f = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
            next_t += 1 / fps
            await asyncio.sleep(max(0, next_t - time.time()))
            if inflight >= 2:
                continue  # browser drops frames under backpressure
            await ws.send(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes())
            inflight += 1; sent += 1
        await asyncio.sleep(1.5); rt.cancel()
    print(json.dumps({"camera": cid, "sent": sent, "overlays": overlays, "status": statuses,
                      "labels_seen": {f"{k[0]} ({k[1]})": v for k, v in sorted(labels.items(), key=lambda kv: -kv[1])}}, indent=1))

asyncio.run(main())
