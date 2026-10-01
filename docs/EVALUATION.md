# Evaluation

Every number here was measured on this machine (DGX Spark GB10, shared with the FRS backend and Ollama)
through the production code path unless stated otherwise. Scripts are in `scripts/`; rerun them with
`make eval-violence`, `make eval-vlm`, `make frs-impact`.

## Violence detection

### Model selection (`scripts/eval_violence_models.py`)

25 fight + 25 non-fight clips sampled from the RWF-2000 validation split (CCTV fights; mirror
`valiantlynxz/godseye-violence-detection-dataset`), clip-level scoring:

| Candidate | AUC | Best accuracy | Accuracy @0.5 |
| --- | --- | --- | --- |
| **VideoMAE-base, Kinetics → RWF-2000** (`lmazzon70/…rwf2000mp4-epochs8-batch8-kb`) | **0.954** | **0.94** | 0.72 |
| CLIP ViT-B/32 zero-shot (prompt ensemble) | 0.752 | 0.72 | 0.68 |
| VideoMAE, UCF-Crime → bus violence (`HappyGook/…`) | 0.621 | 0.68 | 0.62 |
| `DanJoshua/videomae_v1_rwf-2000` | — | — | rejected: classifier head has 1,743 outputs (trained on file names) |

Two loading traps found and fixed: the chosen checkpoint stores attention biases as legacy
`q_bias/v_bias`, which transformers 5 silently re-initialises at random (fixed by remapping in
`perception/models.py::_load_videomae`); a ViT candidate was a timm checkpoint that loads as random weights.

The chosen model is **badly calibrated**: 24/25 fights score > 0.9, but so do 13/25 non-fights. It is
therefore used as a sensitive stage, never alone.

### Cascade (`scripts/eval_violence_cascade.py`)

Real `CameraWorker` over each clip (pose → ByteTrack → proximity gate → VideoMAE on the interacting region
→ fusion rule). Fusion: `0.55·sigmoid(logit−4) + 0.45·pose_interaction`; fire on one evaluation ≥ 0.85 or
two consecutive ≥ 0.78.

| Set | Fights detected | Non-fights flagged | Notes |
| --- | --- | --- | --- |
| Tuning set (50 clips above; thresholds chosen here) | 18/25 | 0/25 | in-sample, optimistic |
| **Held-out set** (50 different RWF-2000 val clips) | **14/25** | **1/25** | out-of-sample; 4 missed fights never had two people close enough to evaluate |

Clip-level on 5-second clips: a real incident on a live camera lasts longer and gets more evaluations.
Pose model: yolo11s-pose (yolo11m-pose measured 18/0 on the tuning set at 2x the GPU cost).

### VLM verification stage (`scripts/eval_vlm_verifier.py`)

`qwen3-vl:8b` with the ThreatAgent's exact question over six frames, held-out set, 10 fights and the 10
*hardest* non-fights (clips where two or more people were close enough for the cascade to evaluate):

| | confirmed | rejected |
| --- | --- | --- |
| Fights the cascade flagged (6) | 5 | 1 |
| Fights the cascade missed (4) | 0 | 4 |
| Hard non-fights (10) | **0** | 10 |

The VLM's self-reported confidence was 0.98 on every answer: it carries no information and is not used
for ranking. Policy that follows: **confirmed** (0 false confirmations) escalates violence to critical;
**rejected** (misses real fights) lowers severity one step, never below medium, and keeps the event for a
human. Nothing is dismissed by a model.

## Identity

- **Embedding space** (FRS enrolment photos, `face_embed_image`): genuine pairs 0.555–0.735 including
  frontal-vs-profile (6 pairs, 2 people with multiple photos); impostor pairs max 0.307, mean 0.06
  (27 people). Threshold 0.40 + margin 0.06 sits between them. Small sample — recalibrate on real footage.
- **Persistent re-identification** (`netra/data/test/walkthrough.mp4` from the FRS test corpus, 3 real
  faces composited into a synthetic scene, looped): 3 people → exactly 3 identities; every later pass and a
  service restart re-used the same IDs (0 new identities, 0 unlocks across ~20 sightings each).
  The clip's own caveat applies: it proves integration, not field accuracy.
- **FRS watchlist**: 2 of the 3 subjects are enrolled in FRS; both were reported as candidates
  (FRS similarity 0.84 and 0.77), the third correctly unmatched, using 3 FRS searches in total.

## Performance and impact on FRS (`scripts/frs_impact.py`)

FRS's own `/api/metrics`, averaged over 90 s windows, its two live cameras running throughout:

| Condition | FRS station fps | person-detect p50 | face-detect p50 |
| --- | --- | --- | --- |
| VIGIL stopped | 22.7 | 6.8 ms | 16.4 ms |
| VIGIL first build (m-pose, no motion gate) | 14.9 | 25.6 ms | 39.8 ms |
| **VIGIL now** (s-pose, GPU pre/post, motion gate) | **22.5** | **7.1 ms** | **16.5 ms** |
| During an LLM investigation (27B model decoding) | ~16 | ~22 ms | ~35 ms |

VIGIL per-camera analysis while people are in view: 7–10 fps with latency ~70 ms under concurrent LLM
load; idle scenes ~1 analysed frame/s. YOLO11s-pose at 960: 8 ms (batch 1) / 21 ms (batch 3) on an
otherwise FRS-only GPU.

## Not yet measured

- Accuracy on this site's own cameras (no labelled incidents exist yet; the live cameras were empty at
  night during this build).
- Fall, weapon, unattended-object and loitering rules have unit tests on synthetic tracks, not a labelled
  field set.
- Demographic performance of the face models (the FRS audit flagged the same gap).
