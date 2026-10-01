import numpy as np

from conftest import make_track
from vigil.analytics.identity import IdentityService
from vigil.perception.models import FaceObs

rng = np.random.default_rng(0)


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


def person():
    return unit(rng.normal(size=512))


def view(base, noise=0.35):
    return unit(base + noise * unit(rng.normal(size=512)))


def obs(emb, q=0.8):
    return FaceObs((10, 10, 90, 90), np.zeros((5, 2), np.float32), 0.9, q, 80.0, 0.9, 0.8, embedding=emb)


FRAME = np.zeros((200, 200, 3), np.uint8)


def test_views_of_same_person_are_close_and_strangers_far():
    a, b = person(), person()
    assert float(view(a) @ view(a)) > 0.6
    assert abs(float(view(a) @ view(b))) < 0.2


def test_new_identity_then_reidentified_on_return():
    svc = IdentityService()
    a = person()
    t1 = make_track("t1")
    changes = [svc.observe(t1, obs(view(a)), FRAME) for _ in range(4)]
    assert "created" in changes
    pid = t1.identity_id
    assert pid.startswith("P-") and t1.identity_locked
    t2 = make_track("t2")  # same person comes back later
    changes = [svc.observe(t2, obs(view(a)), FRAME) for _ in range(3)]
    assert "matched" in changes and t2.identity_id == pid
    assert svc.stats["new_identities"] == 1


def test_two_people_get_two_ids():
    svc = IdentityService()
    ids = []
    for p in (person(), person()):
        t = make_track()
        for _ in range(4):
            svc.observe(t, obs(view(p)), FRAME)
        ids.append(t.identity_id)
    assert ids[0] != ids[1] and all(ids)


def test_low_quality_faces_never_create_identities():
    svc = IdentityService()
    t = make_track()
    for _ in range(10):
        svc.observe(t, obs(view(person()), q=0.3), FRAME)
    assert t.identity_id is None and svc.stats["new_identities"] == 0


def test_margin_rule_refuses_ambiguous_match():
    svc = IdentityService()
    a = person()
    twin = unit(a + 0.05 * person())  # near-duplicate gallery identity
    from vigil.analytics.identity import IdentityMeta
    svc.meta = {"P-1": IdentityMeta("P-1", None, "unknown", "none"), "P-2": IdentityMeta("P-2", None, "unknown", "none")}
    svc._add_vectors("P-1", [a])
    svc._add_vectors("P-2", [twin])
    t = make_track()
    for _ in range(3):
        svc.observe(t, obs(view(a, 0.2)), FRAME)
    assert not t.identity_locked or t.identity_id is None


def test_locked_track_unlocks_on_contradiction():
    svc = IdentityService()
    a, b = person(), person()
    t = make_track()
    for _ in range(4):
        svc.observe(t, obs(view(a)), FRAME)
    assert t.identity_locked
    results = [svc.observe(t, obs(view(b), q=0.9), FRAME) for _ in range(12)]
    assert "unlocked" in results


def test_ambiguous_face_does_not_mint_a_duplicate_identity():
    """A degraded view of a known person (sim ~0.34) must keep collecting, not create a second ID."""
    svc = IdentityService()
    a = person()
    t1 = make_track("t1")
    for _ in range(4):
        svc.observe(t1, obs(view(a)), FRAME)
    assert t1.identity_id
    known = svc.stats["new_identities"]
    degraded = [unit(a * 0.34 + np.sqrt(1 - 0.34 ** 2) * unit(person())) for _ in range(6)]
    t2 = make_track("t2")
    for e in degraded:
        svc.observe(t2, obs(e), FRAME)
    # never a second ID; pooling several degraded views may legitimately recover the right person
    assert svc.stats["new_identities"] == known and t2.identity_id in (None, t1.identity_id)
