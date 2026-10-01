import asyncio

import pytest
from fastapi.testclient import TestClient

from vigil.db import init_db
from vigil.main import create_app
from vigil.security import bootstrap_admin


@pytest.fixture(scope="module")
def client():
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_setup())
    app = create_app()
    with TestClient(app, base_url="https://testserver") as c:  # no lifespan: models/cameras stay off
        yield c


async def _setup():
    await init_db()
    await bootstrap_admin()


def login(c, user="admin", pw="test-admin-pw"):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_health_is_public(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_protected_routes_require_auth(client):
    for path in ("/api/events", "/api/incidents", "/api/identities", "/api/cameras", "/api/system/status"):
        assert client.get(path).status_code == 401, path


def test_bad_login_rejected(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401


def test_roles_enforced(client):
    admin = login(client)
    r = client.post("/api/users", json={"username": "viewer1", "password": "viewer-pass-1", "role": "viewer"},
                    headers=admin)
    assert r.status_code == 200
    viewer = login(client, "viewer1", "viewer-pass-1")
    assert client.get("/api/events", headers=viewer).status_code == 200
    assert client.post("/api/cameras", json={"name": "x", "source_type": "rtsp", "source_uri": "rtsp://h/x"},
                       headers=viewer).status_code == 403
    assert client.put("/api/settings/rules", json={}, headers=viewer).status_code == 403
    assert client.post("/api/users", json={"username": "evil", "password": "12345678", "role": "admin"},
                       headers=viewer).status_code == 403


def test_disabled_user_is_locked_out_immediately(client):
    admin = login(client)
    client.post("/api/users", json={"username": "temp1", "password": "temp-pass-1", "role": "analyst"}, headers=admin)
    tok = login(client, "temp1", "temp-pass-1")
    uid = next(u["id"] for u in client.get("/api/users", headers=admin).json() if u["username"] == "temp1")
    client.patch(f"/api/users/{uid}", json={"disabled": True}, headers=admin)
    assert client.get("/api/events", headers=tok).status_code == 401


def test_media_path_traversal_blocked(client):
    """No path may return a file outside the media root / built UI (DB, secrets, source)."""
    admin = login(client)
    for p in ("/media/../vigil.db", "/media/..%2Fvigil.db", "/media/%2e%2e/.jwt_secret", "/../data/vigil.db",
              "/assets/../../vigil/config.py", "/media/uploads/x.mp4"):
        r = client.get(p, headers=admin)
        body = r.content
        assert b"SQLite format" not in body and b"BaseSettings" not in body, p
        assert r.status_code in (403, 404) or body.lstrip().lower().startswith(b"<!doctype html"), p


def test_file_camera_outside_uploads_refused(client):
    admin = login(client)
    r = client.post("/api/cameras", json={"name": "x", "source_type": "file", "source_uri": "/etc/passwd"},
                    headers=admin)
    assert r.status_code == 400


def test_rules_roundtrip(client):
    admin = login(client)
    r = client.put("/api/settings/rules", json={"loitering": {"dwell_s": 42}, "bogus": {"x": 1}}, headers=admin)
    assert r.status_code == 200
    eff = client.get("/api/settings/rules", headers=admin).json()["effective"]
    assert eff["loitering"]["dwell_s"] == 42 and "bogus" not in eff


def test_retention_sweep_keeps_incident_evidence(client):
    from datetime import timedelta
    from vigil.agents.orchestrator import Orchestrator
    from vigil.config import get_settings
    from vigil.db import Event, session, utcnow

    media = get_settings().media_dir / "evidence"
    old = utcnow() - timedelta(days=get_settings().retention_days + 1)

    async def run():
        async with session() as db:
            db.add(Event(id="evt_old_unlinked", ts=old, type="running", severity="low", title="x", evidence={}))
            db.add(Event(id="evt_old_incident", ts=old, type="violence", severity="high", title="y", evidence={},
                         incident_id="inc_keep"))
            await db.commit()
        for eid in ("evt_old_unlinked", "evt_old_incident"):
            (media / eid).mkdir(parents=True, exist_ok=True)
            (media / eid / "key.jpg").write_bytes(b"x")
        return await Orchestrator().sweep()

    out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(run())
    assert out["evidence_dirs"] == 1
    assert not (media / "evt_old_unlinked").exists()
    assert (media / "evt_old_incident" / "key.jpg").exists()


def test_identity_event_filter_is_exact(client):
    from vigil.db import Event, session, utcnow
    admin = login(client)

    async def seed():
        async with session() as db:
            db.add(Event(id="evt_f1", ts=utcnow(), type="loitering", severity="medium", title="a",
                         identity_ids=["P-00011"]))
            db.add(Event(id="evt_f2", ts=utcnow(), type="loitering", severity="medium", title="b",
                         identity_ids=["P-000111"]))
            await db.commit()
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(seed())
    ids = [e["id"] for e in client.get("/api/events?identity_id=P-00011", headers=admin).json()["items"]]
    assert ids == ["evt_f1"]  # no prefix false-match with P-000111


def test_demo_data_is_isolated_and_removable(client):
    admin = login(client)
    r = client.post("/api/demo/data?hours=12", headers=admin)
    assert r.status_code == 200, r.text
    gen = r.json()["generated"]
    assert gen["events"] > 20 and gen["identities"] == 16 and gen["cameras"] == 4
    demo_evs = client.get("/api/events?demo=only&limit=500", headers=admin).json()["items"]
    assert demo_evs and all(e["is_demo"] and e["description"].startswith("[DEMO]") for e in demo_evs)
    real_evs = client.get("/api/events?demo=exclude&limit=500", headers=admin).json()["items"]
    assert not any(e["is_demo"] for e in real_evs)
    ids = client.get("/api/identities?demo=only", headers=admin).json()["items"]
    assert all(i["id"].startswith("D-") for i in ids)
    for i in ids:  # every demo image must really exist (imwrite fails silently without its folder)
        assert client.get(i["face_url"], headers=admin).status_code == 200, i["face_url"]
    assert client.get(demo_evs[0]["evidence"]["keyframe"], headers=admin).status_code == 200
    # demo rows never touch real systems
    d = next(i for i in ids)
    assert client.post(f"/api/identities/{d['id']}/check-watchlist", headers=admin).status_code == 400
    inc = client.get("/api/incidents?demo=only", headers=admin).json()["items"][0]
    assert client.post(f"/api/incidents/{inc['id']}/investigate", headers=admin).status_code == 400
    assert client.patch("/api/cameras/demo-main-gate", json={"enabled": True}, headers=admin).status_code == 400
    # demo identities never enter the face-matching gallery
    import asyncio as _a
    from vigil.analytics.identity import IdentityService
    svc = IdentityService()
    _a.get_event_loop_policy().new_event_loop().run_until_complete(svc.load())
    assert not any(k.startswith("D-") for k in svc.meta)
    r = client.delete("/api/demo/data", headers=admin)
    assert r.status_code == 200
    assert client.get("/api/demo/data", headers=admin).json()["present"] is False


def test_webcam_camera_creation(client):
    admin = login(client)
    r = client.post("/api/demo/webcam", headers=admin)
    assert r.status_code == 200 and r.json()["source_type"] == "browser" and r.json()["id"] == "webcam-admin"
    viewer = login(client, "viewer1", "viewer-pass-1")
    assert client.post("/api/demo/webcam", headers=viewer).status_code == 403


def test_migration_backfills_defaults(tmp_path):
    """A column added to an existing table must get its default on old rows (is_demo NULL hid real data)."""
    import sqlite3
    from sqlalchemy import create_engine
    from vigil.db import _add_missing_columns
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE identities (id VARCHAR(40) PRIMARY KEY, kind VARCHAR(20))")
    con.execute("INSERT INTO identities (id, kind) VALUES ('P-1', 'unknown')")
    con.commit(); con.close()
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as conn:
        added = _add_missing_columns(conn)
    assert "identities.is_demo" in added
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT is_demo FROM identities").scalar_one() in (0, False)
