"""Run the real CameraWorker over labelled clips and report the violence cascade per clip.

Measures stage 1 (pose), stage 2 (VideoMAE) and the fused trigger on held-out
RWF-2000 val clips, using the production code path (file source, non-realtime).
"""
import glob, json, sys, time
sys.path.insert(0, ".")
import numpy as np
from vigil.bus import bus
from vigil.perception.models import hub
from vigil.perception.worker import CameraWorker
from vigil.analytics.signals import merge_rules

ROOT = sys.argv[1] if len(sys.argv) > 1 else "data/testclips"
fired = []
bus.publish_threadsafe = lambda topic, payload: fired.append((topic, payload)) if topic == "signal" else None
hub().wait_ready()
rows = []
clips = [(p, 1) for p in sorted(glob.glob(f"{ROOT}/Fight/*.avi")) if "_processed" not in p] + \
        [(p, 0) for p in sorted(glob.glob(f"{ROOT}/NonFight/*.avi")) if "_processed" not in p]
for p, label in clips:
    fired.clear()
    cam = {"id": "eval", "name": "eval", "source_type": "file", "source_uri": p, "loop": False, "realtime": False,
           "analysis_fps": 12.0, "enabled": True}
    w = CameraWorker(cam, [], merge_rules())
    w.start(); w.join(timeout=120)
    ev = list(w.violence.evals)
    v = [s for t, s in fired if s.type == "violence"]
    rows.append({"clip": p.split("/")[-1], "label": label, "evals": len(ev),
                 "max_vm": max([e["videomae_component"] for e in ev], default=0),
                 "max_pose": max([e["pose_component"] for e in ev], default=0),
                 "max_fused": max([e["fused"] for e in ev], default=0),
                 "max_ema": max([e["ema"] for e in ev], default=0), "fired": len(v) > 0,
                 "other": sorted({s.type for t, s in fired if s.type != "violence"}), "seq": ev})
    print(json.dumps({k: v for k, v in rows[-1].items() if k != "seq"}))
json.dump(rows, open(f"{ROOT}/cascade.json", "w"))
for lab in (1, 0):
    r = [x for x in rows if x["label"] == lab]
    print("FIGHT" if lab else "NONFIGHT", "n", len(r), "fired", sum(x["fired"] for x in r),
          "no-evals", sum(x["evals"] == 0 for x in r))
