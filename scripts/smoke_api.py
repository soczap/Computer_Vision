"""End-to-end smoke test against a running VIGIL server."""
import sys, time, json, glob
import httpx

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "https://127.0.0.1:8090")
creds = dict(l.split(": ", 1) for l in open("data/initial_admin_credentials.txt").read().strip().splitlines())
c = httpx.Client(base_url=BASE, verify=False, timeout=60)
r = c.post("/api/auth/login", json={"username": creds["username"], "password": creds["password"]})
r.raise_for_status()
c.headers["Authorization"] = "Bearer " + r.json()["token"]
print("login ok", r.json()["user"]["role"])
assert httpx.get(BASE + "/api/events", verify=False).status_code == 401, "unauthenticated access must fail"
print("unauthenticated -> 401 ok")
print("frs cameras:", [(x["id"], x["running_in_frs"]) for x in c.get("/api/frs/cameras").json()])
existing = {x["id"] for x in c.get("/api/cameras").json()}
for fid in ("BACK-GATE", "TSPARK-IT-CELL"):
    if f"frs-{fid}" not in existing:
        print("import", fid, c.post(f"/api/frs/cameras/{fid}/import").status_code)
if "--upload" in sys.argv:
    clip = sorted(glob.glob("data/testclips/Fight/39BFeYnbuI_4.avi"))[0]
    with open(clip, "rb") as fh:
        r = c.post("/api/cameras/upload", data={"name": "fight-test", "realtime": "true", "loop": "true"},
                   files={"file": ("fight.avi", fh, "video/x-msvideo")})
    print("upload", r.status_code, r.json().get("id"))
time.sleep(float(sys.argv[-1]) if sys.argv[-1].replace(".", "").isdigit() else 20)
for cam in c.get("/api/cameras").json():
    print("CAM", cam["id"], json.dumps({k: cam["stats"].get(k) for k in ("status", "fps", "latency_ms", "active_tracks",
          "tracks_total", "faces", "signals", "resolution")} if cam["stats"] else None))
ev = c.get("/api/events?limit=20").json()
print("events total", ev["total"])
for e in ev["items"][:10]:
    print("  ", e["ts"][11:19], e["camera_id"], e["type"], e["severity"], e["status"], e["title"][:70])
inc = c.get("/api/incidents").json()
print("incidents", inc["total"], [(i["title"][:50], i["status"], i["severity"]) for i in inc["items"][:5]])
print("runs", [(r["agent"], r["status"], r["step_count"]) for r in c.get("/api/agents/runs?limit=10").json()])
st = c.get("/api/system/status").json()
print("gpu", st["gpu"], "face_gpu", st["face_gpu"], "identity", st["identity"], "gallery", st["gallery"])
print("frs", st["frs"], "llm", st["llm"])
