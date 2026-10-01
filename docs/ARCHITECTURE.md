# Architecture

## Process model

One Python process (uvicorn, one worker). Threads do perception; the asyncio loop does I/O, persistence
and agents.

```
┌──────────────────────────────── vigil (uvicorn, 1 worker) ─────────────────────────────────┐
│                                                                                           │
│  source threads (1/camera)     camera threads (1/camera)          GPU worker threads      │
│  FRS MJPEG relay / RTSP /  ──► CameraWorker._process  ──submit──► pose   (batched YOLO11) │
│  file  → LatestSlot            motion gate → track → faces        objects(batched YOLO11) │
│                                → identity → rules → violence       face   (SCRFD+AdaFace) │
│                                → recorder → live channel           aux    (VideoMAE+CLIP) │
│                                        │                                                  │
│                         bus.publish_threadsafe / runtime.submit                           │
│                                        ▼                                                  │
│  asyncio loop:  Orchestrator ─ Threat/Identity/Behavior/Investigation/Reporting agents    │
│                 persistence (SQLAlchemy async) · REST routers · WebSockets                │
└───────────────────────────────────────────────────────────────────────────────────────────┘
        │ read-only HTTP                     │ HTTP (local)
        ▼                                    ▼
  FRS backend :8000                    Ollama :11434 (qwen3.8, qwen3-vl:8b)
```

- Each model group has exactly one owning thread (CUDA contexts and ONNX sessions are not shared).
  Callers get `Future`s. Pose and object detection batch requests from all cameras for up to 4 ms.
- YOLO runs through `LeanYolo`: uint8 frames are uploaded, letterboxed and normalised on the GPU; NMS
  on the GPU. Parity with ultralytics' predictor verified (boxes ±0.2 px, keypoints ±1 px).
- Face work is asynchronous: a camera submits at most one face job at a time and collects it on a later
  frame, so recognition never stalls tracking.
- The **motion gate** analyses idle scenes (no active tracks, <0.25% changed pixels on a 160x90
  thumbnail for 3 s) once a second; the ring buffer keeps recording for evidence pre-roll.
- Threads never touch the DB or the loop directly: `runtime.submit(coro)` schedules persistence on the
  loop; `bus.publish_threadsafe` delivers signals. Subscribers have bounded queues (a slow WebSocket
  drops its own messages, it never back-pressures perception).

## Identity decision

```
face obs (quality ≥ 0.35, face ≥ 40 px) ─► track face buffer (best 10)
unlocked track: pooled embedding (quality-weighted mean of best 5)
   ├─ best ≥ 0.40 and best − second ≥ 0.06  → vote; 2 votes → LOCK to that identity
   └─ no match and ≥3 views with q ≥ 0.5 and best < 0.35 → NEW identity P-xxxxx (3 best vectors)
locked track: each new observation checked on its own
   ├─ ≥ threshold → confirm (+ add a diverse high-quality view to the gallery, ≤12 auto vectors)
   └─ 3 good contradicting views → UNLOCK (tracker ID swap)
identity with a good face (≥56 px, q ≥ 0.55) → FRS watchlist search (rate-limited) → candidate
```

Thresholds rest on measurement: AdaFace IR101 on this deployment's enrolment photos gives genuine pairs
0.555–0.735 (frontal vs profile included) and impostor pairs max 0.307 (mean 0.06) across 27 subjects.

## Event → incident flow

1. A rule or the violence cascade emits a `Signal` (type, severity, confidence, explanation, boxes).
2. The camera worker captures evidence (keyframe now; clip + frames after post-roll).
3. The orchestrator deduplicates (type × camera × people within the cooldown), stores an `Event`.
4. `verify` signals (violence, fall, weapon, unattended object) go to the ThreatAgent first.
5. Medium+ events escalate: attached to an open incident updated in the last 10 min that shares a person,
   or same camera and type; otherwise a new incident.
6. Incidents at/above `auto_investigate_min_severity` are queued for the InvestigationAgent (one at a time).
7. Critical incidents get an automatic report after investigation.

Behaviour correlation: when a person's track closes, the BehaviorAgent counts their visits in the window
(repeat-appearance) and looks for ≥2 distinct minor behaviours by the same person in 30 min
(loitering, pacing, unusual path, after-hours, intrusion, running, repeat visits) → one explained
`suspicious_pattern` event referencing each constituent.

## Data model (SQLite WAL / Postgres)

| Table | |
| --- | --- |
| `users`, `audit_log` | accounts, roles; every mutation and agent action |
| `cameras`, `zones` | sources and normalised polygons with per-zone rules |
| `identities`, `face_vectors` | persistent people; AdaFace vectors (enrolment + bounded auto views) |
| `tracks` | one sighting = one person on one camera: path, speeds, zone dwell, crops, CLIP appearance |
| `events` | explainable detections with evidence and verification |
| `incidents` | correlated events, investigation conclusion, report, notes |
| `agent_runs` | every agent execution with its full step trace |
| `settings` | rule overrides |

Schema changes are additive migrations applied at startup (`db._add_missing_columns`).

## Deliberate non-features

- **No automatic identity assignment from clothing/appearance.** At a police station many people wear the
  same uniform; CLIP appearance similarity would merge different officers into one ID. Appearance is used
  for natural-language search and as a cross-camera *hint* the investigation agent can weigh
  (`find_similar_appearance`), never to assign an identity. Only face evidence assigns identities.
- **The machine never confirms an identity.** FRS watchlist hits are candidates; the UI and every agent
  prompt say so.
- **VideoMAE never alerts alone.** It is sensitive but badly calibrated on this footage (see EVALUATION.md);
  it must be corroborated by pose interaction and then by the VLM.
