import numpy as np

from conftest import make_track, upright_kps
from vigil.analytics.behavior import BehaviorEngine, ZoneDef
from vigil.analytics.signals import merge_rules
from vigil.perception.models import ObjectDet

W = H = 1000


def engine(zones=(), **rule_overrides):
    return BehaviorEngine("cam", merge_rules(rule_overrides), list(zones), "Asia/Kolkata")


def step(eng, tracks, ts, objects=None):
    return eng.update(ts, tracks, objects, W, H, {})


def place(tr, ts, x, y, h=200):
    box = np.array([x - 30, y - h, x + 30, y], np.float32)
    tr.update(ts, box, upright_kps(box), 0.9, W, H)


def test_restricted_zone_intrusion_fires_once():
    z = ZoneDef("z1", "Armoury", "restricted", [[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 1]])
    eng = engine([z])
    tr = make_track()
    out = []
    for i, x in enumerate(range(300, 800, 50)):
        place(tr, i * 0.5, x, 800)
        out += step(eng, [tr], i * 0.5)
    hits = [s for s in out if s.type == "zone_intrusion"]
    assert len(hits) == 1 and hits[0].explanation["zone"] == "Armoury"


def test_loitering_requires_dwell_and_small_radius():
    eng = engine(loitering={"dwell_s": 30})
    still, walker = make_track("a"), make_track("b", local_id=2)
    out = []
    for i in range(80):
        ts = i * 0.5
        place(still, ts, 500 + (i % 3), 600)
        place(walker, ts, 100 + i * 10, 800)
        out += step(eng, [still, walker], ts)
    types = [(s.type, s.track_uids[0]) for s in out]
    assert ("loitering", "a") in types
    assert ("loitering", "b") not in types


def test_fall_detected_after_upright():
    eng = engine(fall={"min_down_s": 1.0})
    tr = make_track()
    out = []
    for i in range(10):
        place(tr, i * 0.1, 500, 700)
        out += step(eng, [tr], i * 0.1)
    for i in range(10, 40):
        ts = i * 0.1
        box = np.array([400, 640, 640, 700], np.float32)  # wide, low box
        k = upright_kps(box)
        k[[5, 6], :2] = [[420, 660], [420, 680]]
        k[[11, 12], :2] = [[560, 660], [560, 680]]
        tr.update(ts, box, k, 0.9, W, H)
        out += step(eng, [tr], ts)
    falls = [s for s in out if s.type == "fall"]
    assert len(falls) == 1 and falls[0].explanation["upright_before"] is True and falls[0].verify


def test_crowd_needs_duration():
    eng = engine(crowd={"min_people": 4, "min_duration_s": 5})
    trs = [make_track(f"t{i}", local_id=i) for i in range(5)]
    out = []
    for n in range(20):
        ts = n * 0.5
        for i, tr in enumerate(trs):
            place(tr, ts, 400 + i * 40, 700)
        out += step(eng, trs, ts)
        if n < 9:
            assert not [s for s in out if s.type == "crowd"]
    assert len([s for s in out if s.type == "crowd"]) == 1


def test_abandoned_object_after_owner_leaves():
    eng = engine(abandoned_object={"unattended_s": 10})
    owner = make_track("owner")
    bag = ObjectDet("suitcase", (480, 650, 540, 700), 0.8)
    out = []
    for i in range(60):
        ts = i * 0.5
        place(owner, ts, 500 if i < 10 else 500 + (i - 10) * 40, 700)
        tracks = [owner] if i < 30 else []
        out += step(eng, tracks, ts, [bag])
    ab = [s for s in out if s.type == "abandoned_object"]
    assert len(ab) == 1 and ab[0].verify and ab[0].explanation["object"] == "suitcase"


def test_moving_bag_is_not_abandoned():
    eng = engine(abandoned_object={"unattended_s": 5})
    out = []
    for i in range(60):
        ts = i * 0.5
        out += step(eng, [], ts, [ObjectDet("backpack", (100 + i * 20, 600, 160 + i * 20, 660), 0.8)])
    assert not [s for s in out if s.type == "abandoned_object"]


def test_weapon_needs_repeated_hits_on_a_person():
    eng = engine()
    tr = make_track()
    place(tr, 0, 500, 700)
    knife = ObjectDet("knife", (500, 560, 520, 600), 0.7)
    out = step(eng, [tr], 0.0, [knife]) + step(eng, [tr], 0.5, [knife])
    assert not [s for s in out if s.type == "weapon"]
    out = step(eng, [tr], 1.0, [knife])
    assert [s for s in out if s.type == "weapon"]
    floating = ObjectDet("knife", (10, 10, 30, 40), 0.9)  # not on anybody
    eng2 = engine()
    out2 = sum((step(eng2, [tr], t, [floating]) for t in (0, .5, 1, 1.5)), [])
    assert not [s for s in out2 if s.type == "weapon"]


def test_explanations_carry_thresholds():
    eng = engine(running={"speed_bh_s": 1.0, "min_duration_s": 0.5})
    tr = make_track()
    out = []
    for i in range(30):
        ts = i * 0.1
        place(tr, ts, 100 + i * 40, 700)
        out += step(eng, [tr], ts)
    run = [s for s in out if s.type == "running"]
    assert run and run[0].explanation["threshold_bh_per_s"] == 1.0
    assert run[0].explanation["speed_bh_per_s"] > 1.0
