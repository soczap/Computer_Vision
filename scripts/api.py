"""Tiny authenticated client for scripts: `from api import c`."""
import httpx
creds = dict(l.split(": ", 1) for l in open("data/initial_admin_credentials.txt").read().strip().splitlines())
c = httpx.Client(base_url="https://127.0.0.1:8090", verify=False, timeout=120)
c.headers["Authorization"] = "Bearer " + c.post("/api/auth/login", json=creds).json()["token"]
