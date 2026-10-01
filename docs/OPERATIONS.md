# Operations

## Service

```bash
systemctl --user status vigil        # unit: ~/.config/systemd/user/vigil.service (copy of deploy/vigil.service)
systemctl --user restart vigil
tail -f data/logs/vigil.log          # structured JSON logs (rotating, 5 x 20 MB)
make status                          # readiness
```

Run exactly **one** process: tracks, identity gallery, live channels and the agent queue are process-local.
Do not also start `python -m vigil.main` by hand — the unit holds port 8090.

On restart the orchestrator recovers: interrupted agent runs are closed as failed, events pending VLM
verification in the last hour are re-verified, and incidents left mid-investigation are re-queued.

## Health endpoints

| Endpoint | Meaning |
| --- | --- |
| `GET /api/health` | liveness, no auth |
| `GET /api/ready` | 200 only when the DB answers and all four model workers initialised; 503 otherwise |
| `GET /api/system/status` | full status (auth): GPU, model workers, per-camera fps/latency/stage timings/idle, FRS link, LLM, counters |
| `GET /metrics` | Prometheus (loopback or admin): camera fps/tracks/latency/running, model queues/busy time, orchestrator and identity counters |

If `face.gpu` is `false` in `/api/system/status` the face models fell back to CPU (unified-memory
contention on the DGX Spark: something else claimed the GPU pool first). Recognition still works at
10–25x the latency; free GPU memory and restart.

## Configuration

`.env` in the project root (all keys in `vigil/config.py`, prefix `VIGIL_`). Most useful:

| Variable | Default | |
| --- | --- | --- |
| `VIGIL_ANALYSIS_FPS` | 12 | per-camera analysis rate while active (idle scenes: ~1/s) |
| `VIGIL_POSE_MODEL` | yolo11s-pose.pt | m-pose costs ~2x GPU for no measured gain on the violence eval |
| `VIGIL_FACE_MATCH_THRESHOLD` / `_MARGIN` | 0.40 / 0.06 | AdaFace cosine for re-identifying people among our own identities |
| `VIGIL_FRS_RELAY_WIDTH` | 1920 | width requested from the FRS MJPEG relay (face resolution vs FRS encode cost) |
| `VIGIL_AUTO_INVESTIGATE_MIN_SEVERITY` | high | incidents at/above this are investigated by the LLM agent automatically |
| `VIGIL_AGENTS_ENABLED` | true | false = no VLM verification / investigations (perception + rules only) |
| `VIGIL_NOTIFY_WEBHOOK_URL` | unset | POST target for the notify action |
| `VIGIL_DATABASE_URL` | SQLite in data/ | e.g. `postgresql+asyncpg://…` |

Detection rules (thresholds, severities, enable flags) are edited live in Settings → Rules
(`PUT /api/settings/rules`); per-zone overrides (`loiter_s`, `max_occupancy`, `schedule`) live on the zone.

## Demo / local camera (laptop webcam)

The physical cameras can be unavailable (the FRS-imported cameras `frs-BACK-GATE`, `frs-TSPARK-IT-CELL`
are currently **disabled in VIGIL only** — their config and history are kept; re-enabling one reconnects
it through the FRS relay; nothing on port 8000 was changed).

Live → **Connect laptop webcam** (or FRS → Console). The browser asks for camera permission, then streams
JPEG frames over `wss://…/ws/ingest/webcam-<user>`; the camera `webcam-<user>` (source type `browser`)
runs the same pipeline as any camera — detection, tracking, persistent face IDs, FRS watchlist search,
behaviour rules — and the overlays come back on the same socket.

- Needs a secure context: `https://<host>:8090` (accept the certificate) or `http://localhost` through an
  SSH tunnel (`ssh -N -L 8090:localhost:8090 …`, then use `https://localhost:8090`).
- On a slow Mac→DGX link frames arrive further apart; the client keeps ≤2 frames in flight and drops the
  rest, so overlays stay current rather than lagging.
- `make sim-webcam` drives the identical protocol from a video file (used for automated verification).

## Demo data

`make demo-data` / Settings → Demo data creates synthetic cameras (`demo-*`), identities (`D-xxxx`), tracks,
events and incidents for exercising dashboards. Every row has `is_demo = true`, every demo event/incident
title starts with `[DEMO]`, every image is generated and watermarked "SYNTHETIC DEMO DATA". Demo rows never
enter the face-matching gallery, are never searched against FRS, are invisible to every agent tool, cannot
be investigated or reviewed, and are removed completely by `make demo-clear`. List/analytics APIs take
`demo=include|exclude|only`; the UI's data-mode switch sets it and badges every demo item.

## FRS workspace

The FRS section (sidebar) is face-recognition operations over two sources:
VIGIL's identity service (persistent IDs, re-identification, enrolment into **VIGIL's** gallery) and the
port-8000 FRS backend (read-only: watchlist records, its own detections, its match log, its latency
metrics). Every watchlist search VIGIL sends is logged in `frs_searches` with the face crop, outcome and
round-trip latency (`GET /api/frs/searches`); FRS keeps its own copy (`GET /api/frs/history`, rows caused by
VIGIL flagged `by_vigil`).

## Adding cameras

- **From FRS** (preferred for cameras FRS already runs): Cameras → Import from FRS. Uses its MJPEG relay.
- **RTSP/HTTP**: add with the stream URL (credentials are redacted in every API response).
- **Video file**: Cameras → Upload video; plays as a camera (optionally looped/real-time) — useful for
  analysing recorded footage.

Draw zones on the camera snapshot: `restricted` (alerts on entry, optional schedule), `monitored`
(dwell/loitering, capacity), `entry` (counting).

## Data

| Path | |
| --- | --- |
| `data/vigil.db` | SQLite (WAL) |
| `data/media/evidence/<event>/` | keyframe, clip.mp4, f0..f5.jpg |
| `data/media/faces/`, `data/media/persons/` | identity portraits and per-track crops |
| `data/media/uploads/` | uploaded videos (never served over HTTP) |
| `data/heat/<camera>.npy` | per-camera occupancy model (heatmap + path anomaly) |
| `data/.jwt_secret` | session signing key (0600) |

Back up `data/vigil.db` with `sqlite3 data/vigil.db ".backup data/vigil-$(date +%F).db"` (safe while running).
