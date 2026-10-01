import numpy as np

from conftest import make_track, upright_kps


def walk(tr, xs, y=0.8, dt=0.5, W=1000, H=1000, h=200):
    ts = tr.last_ts
    for x in xs:
        ts += dt
        box = np.array([x * W - 30, y * H - h, x * W + 30, y * H], np.float32)
        tr.update(ts, box, upright_kps(box), 0.9, W, H)


def test_jitter_does_not_count_as_reversal():
    tr = make_track()
    walk(tr, [0.5 + 0.01 * ((-1) ** i) for i in range(60)])
    assert tr.reversals == 0


def test_real_back_and_forth_counts():
    tr = make_track()
    xs = []
    for leg in range(6):
        seg = np.linspace(0.3, 0.6, 8) if leg % 2 == 0 else np.linspace(0.6, 0.3, 8)
        xs.extend(seg.tolist())
    walk(tr, xs)
    assert tr.reversals >= 4


def test_speed_in_body_heights():
    tr = make_track()
    walk(tr, np.linspace(0.1, 0.9, 20), dt=0.5, h=200)  # 800 px over 10 s = 80 px/s = 0.4 bh/s
    assert 0.25 < tr.mean_speed() < 0.6


def test_wrist_speed_ignores_whole_body_translation():
    tr = make_track()
    walk(tr, np.linspace(0.1, 0.5, 12), dt=1 / 12)  # fast glide, arms fixed relative to body
    assert tr.wrist_speed() < 0.3


def test_torso_angle_upright_vs_lying():
    tr = make_track()
    box = np.array([100, 100, 160, 300], np.float32)
    tr.kps = upright_kps(box)
    assert tr.torso_angle() < 15
    k = tr.kps.copy()
    k[[5, 6], :2] = [[100, 200], [100, 210]]
    k[[11, 12], :2] = [[180, 200], [180, 210]]
    tr.kps = k
    assert tr.torso_angle() > 70
