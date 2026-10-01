"""Sample FRS's own analyzer metrics for N seconds (rolling-window p50s)."""
import json, sys, time, httpx
def snap():
    d = httpx.get("https://127.0.0.1:8000/api/metrics", verify=False, timeout=10).json()
    a = d["analysis"]; dt = d["detection_tracking"]
    return {"station_fps": a["station_analysed_fps"], **{f"{k}_fps": v["analysed_fps"] for k, v in a["cameras"].items()},
            "person_p50": dt["person_detect_ms"]["p50"], "face_p50": dt["face_detect_ms"]["p50"],
            "embed_p50": d["inference"]["embed_ms"]["p50"]}
out = []
for _ in range(int(sys.argv[1]) // 10):
    time.sleep(10); out.append(snap())
keys = out[0].keys()
print(json.dumps({k: round(sum(o[k] for o in out[1:]) / max(len(out) - 1, 1), 1) for k in keys}))
