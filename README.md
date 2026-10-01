# VIGIL — Agentic Video Analytics

Real-time video intelligence for the station's cameras: face identity with persistent IDs, violence
detection, explainable suspicious-activity rules, behavioural tracking — and a layer of agents that verify,
correlate, investigate and act on what perception finds.

VIGIL runs **beside** the existing FRS backend on port 8000 and treats it as read-only (see
[Integration with FRS](#integration-with-the-frs-backend-port-8000)).

```
https://<host>:8090          console (self-signed cert; accept once)
make status | logs | test    see Makefile
```

First login: `admin`, password in `data/initial_admin_credentials.txt` (mode 0600). Change it under
Settings → Account, then delete the file.

---

## What it does

| Capability | How |
| --- | --- |
| **Persistent identity** | SCRFD face detection inside each person's head region → 5-point alignment → AdaFace IR101 embedding (FRS's own ONNX weights, read-only). Embeddings are **pooled per track** (never one frame), matched with a threshold **and** a margin over the runner-up. Unmatched people with ≥3 good views become `P-xxxxx` and keep that ID when they return, across cameras and restarts. |
| **Enrolment** | Photos → face check (size, quality, same-person consistency) → if the person was already seen as an unknown, that `P-xxxxx` is upgraded in place so their history is kept. |
| **Watchlist** | An identity's best face is searched once against FRS (`/api/match/video`), which applies its two-recogniser agreement and open-set gates. A hit is a *candidate* for human verification, never a confirmed identity. |
| **Violence** | Cascade: pose interaction (proximity, relative wrist speed, cross-body contact) → VideoMAE fine-tuned on RWF-2000 CCTV fights → fusion rule → **VLM verification by the threat agent**. |
| **Suspicious activity** | Explainable rules: restricted-zone intrusion (with schedules), loitering, running, falls/person down, crowding, zone over-capacity, unattended objects, weapons, after-hours presence, pacing, anomalous paths (unsupervised occupancy model per camera), repeat visits, and cross-event correlation into "suspicious pattern" findings. Every event carries the measured values and the thresholds they crossed. |
| **Behavioural tracking** | ByteTrack per camera; per-track trajectory, speed (body-heights/s), zone dwell, posture; identity timelines across cameras; co-occurrence (who was seen with whom); CLIP appearance embeddings for natural-language search ("man in a red shirt with a backpack") and cross-camera hints. |
| **Real-time** | Live WebSocket per camera: JPEG + overlay metadata (boxes, IDs, labels, trails, skeletons, zones, objects, violence meter), with client acks for backpressure. Realtime event/incident/agent stream. |
| **Laptop webcam** | Browser `getUserMedia` → WebSocket ingest → the same pipeline as any camera; overlays return on the socket. For demos while the physical cameras are unavailable. |
| **FRS workspace** | Dedicated console: people in view with identity state, re-identification, FRS watchlist candidates, enrolment, gallery and profiles, VIGIL's and FRS's match logs, recognition latency and gallery statistics. |
| **Demo data** | Clearly-labelled synthetic data (`is_demo`, `[DEMO]`, watermarked images) for dashboards when nothing real is happening; isolated from matching, FRS and agents; one-click removal. |
| **Evidence** | Pre-roll ring buffer → annotated keyframe immediately, H.264 clip (6 s pre / 4 s post) and six verification frames when the post-roll completes. |

## The agents

Perception is deterministic and fast; reasoning is agentic. The orchestrator routes signals; the LLM
agents choose their own tools.

```
camera threads ─signal─► Orchestrator ─┬─ persist event (dedupe/cooldown)
                                       ├─ verify? ─► ThreatAgent ── VLM on evidence frames ──► re-grade
                                       ├─ FRS hit ─► IdentityAgent ── FRS record + live evidence
                                       ├─ track closed ─► BehaviorAgent ── repeat visits, correlation
                                       └─ escalate ─► Incident ─► InvestigationAgent (LLM + tools + actions)
                                                                   └─► ReportingAgent
operator ─► AnalystAgent (chat; read-only tools)
```

- **ThreatAgent** asks the vision model a type-specific question over the clip frames. `confirmed` escalates
  (violence → critical); `rejected` downgrades and keeps the event for audit; `uncertain` holds for review.
- **InvestigationAgent** runs a ReAct loop over ~20 tools (incident/event/track/identity queries, timelines,
  co-occurrence, appearance search, VLM evidence inspection, live camera look, FRS watchlist records,
  event correlation) and **action tools** (notes, incident status/severity, identity flags, notifications).
  Its conclusion is structured (assessment, threat level, confidence, cited evidence, recommended actions).
- Every thought, tool call, result and decision is stored on an `AgentRun` and streamed to the UI.

LLM: `qwen3.8` (already resident for the FRS AI operator) via local Ollama; VLM: `qwen3-vl:8b`.
Nothing leaves the machine.

## Integration with the FRS backend (port 8000)

**Read-only by contract.** VIGIL never calls FRS enrolment, deletion, settings, re-index, alert
acknowledgement or visitor-clear routes, and does not touch its files except reading its ONNX model weights.

| Used | For |
| --- | --- |
| `GET /api/cctv/cameras/{id}/stream` | MJPEG relay of cameras FRS already decodes — no second RTSP session to the camera. |
| `POST /api/match/video` | Watchlist search. FRS stores every search, so VIGIL searches once per identity, again only with a clearly better face or after 6 h, max 20/min. |
| `GET /api/criminals`, `/api/criminal/{id}`, `/detections`, `/api/detections`, `/api/alerts` | Watchlist records and FRS's own sightings, as agent tools. |
| `GET /api/cctv/cameras`, `/api/cctv/stats`, `/api/health` | Camera import and link status. RTSP credentials are redacted before they reach our API, DB or logs. |
| `/media/uploads/criminals/…`, `/media/alerts/…` | Proxied (authenticated) for display only. |

**Measured impact on FRS** (its own `/api/metrics`, 90 s windows): VIGIL stopped 22.7 station fps /
person-detect p50 6.8 ms; VIGIL running with both live cameras 22.5 fps / 7.1 ms. Idle scenes are
motion-gated to ~1 analysed frame/s. During an LLM investigation (1–4 min, only for high/critical incidents)
FRS drops to ~8 fps per camera because the 27B model shares the GPU; set
`VIGIL_AUTO_INVESTIGATE_MIN_SEVERITY=critical` or `VIGIL_AGENTS_ENABLED=false` to trade that off.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
.venv/bin/pip install --extra-index-url https://pypi.jetson-ai-lab.io/sbsa/cu130 -r requirements.txt
.venv/bin/python scripts/fetch_models.py          # YOLO11, VideoMAE (RWF-2000), CLIP
cp .env.example .env                              # then edit
mkdir -p certs && openssl req -x509 -newkey rsa:2048 -nodes -keyout certs/server.key \
  -out certs/server.crt -days 825 -subj "/CN=vigil"
(cd frontend && npm ci && npm run build)
cp deploy/vigil.service ~/.config/systemd/user/ && systemctl --user enable --now vigil
```

Face recognition uses the FRS backend's own ONNX weights (read-only); set `VIGIL_FACE_DET_MODEL` /
`VIGIL_FACE_REC_MODEL` if they live elsewhere. Ollama must serve the LLM/VLM models named in `.env`.

## Security

- JWT sessions (HttpOnly, SameSite=Strict, Secure cookie or Bearer header), scrypt password hashing,
  login throttling, roles `viewer < analyst < admin` enforced server-side, disabled users locked out
  immediately. WebSockets and media require a session.
- Every mutation and every agent action is written to the audit log.
- Raw uploaded videos are never served; media paths are confined to the media root.
- `/metrics` answers loopback only (or an admin session).

## Layout

```
vigil/
  config.py            every knob (env VIGIL_*)
  db.py                SQLAlchemy models, WAL SQLite (Postgres via VIGIL_DATABASE_URL), additive migrations
  security.py          auth, roles, audit
  frs_client.py        the only code that talks to port 8000
  perception/          sources, GPU model workers, tracking, recorder, camera worker, engine
  analytics/           identity service, behaviour rules, violence cascade, signals
  agents/              LLM client, tools, ReAct runtime, orchestrator + agents
  api/                 REST + WebSocket routers
frontend/              React console (built into frontend/dist, served by the backend)
scripts/               evaluation, smoke tests, FRS impact measurement
tests/                 pytest suite (isolated temp data dir)
docs/                  ARCHITECTURE.md, EVALUATION.md, OPERATIONS.md
deploy/vigil.service   systemd user unit
```

See [docs/EVALUATION.md](docs/EVALUATION.md) for every accuracy and performance number and how it was measured.
