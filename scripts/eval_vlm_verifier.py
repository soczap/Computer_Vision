"""Measure the ThreatAgent's VLM verification stage on labelled clips (hard negatives only)."""
import asyncio, glob, json, sys
sys.path.insert(0, ".")
import cv2, numpy as np
from vigil.agents.llm import llm
from vigil.agents.orchestrator import VERIFY_QUESTIONS
from vigil.agents.tools import VISION_SCHEMA, VISION_SYSTEM

ROOT = sys.argv[1] if len(sys.argv) > 1 else "data/testclips2"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
rows = json.load(open(f"{ROOT}/cascade.json"))
fights = [r for r in rows if r["label"] == 1 and r["evals"] > 0][:N]
hard_neg = [r for r in rows if r["label"] == 0 and r["evals"] > 0][:N]  # people close together: the hard case

def frames(name, label):
    p = glob.glob(f"{ROOT}/{'Fight' if label else 'NonFight'}/{name}")[0]
    cap = cv2.VideoCapture(p); fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    idx = np.linspace(0, len(fr) - 1, 6).astype(int)
    return [cv2.imencode(".jpg", fr[i])[1].tobytes() for i in idx]

async def main():
    out = []
    for r in fights + hard_neg:
        res = await llm().vision(VERIFY_QUESTIONS["violence"], frames(r["clip"], r["label"]), VISION_SCHEMA, VISION_SYSTEM)
        out.append({"clip": r["clip"], "label": r["label"], "cascade_fired": r["fired"], "verdict": res.get("verdict"),
                    "conf": res.get("confidence")})
        print(json.dumps(out[-1]), flush=True)
    for lab in (1, 0):
        rs = [o for o in out if o["label"] == lab]
        cnt = {v: sum(o["verdict"] == v for o in rs) for v in ("confirmed", "uncertain", "rejected")}
        print("FIGHT" if lab else "HARD-NONFIGHT", len(rs), cnt)
    await llm().close()
asyncio.run(main())
