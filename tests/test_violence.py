from vigil.analytics.signals import merge_rules
from vigil.analytics.violence import ViolenceMonitor
from conftest import make_track


def fuse(m, logit, pose, ts):
    a, b = make_track("a"), make_track("b", local_id=2)
    return m._fuse(ts, {"logit": logit, "prob": 0.9}, {"pose": pose, "pose_feats": {}, "pair": (a, b)},
                   merge_rules()["violence"], {})


def test_single_very_hot_eval_fires():
    m = ViolenceMonitor("cam", merge_rules())
    sig = fuse(m, logit=9.0, pose=0.95, ts=100.0)
    assert sig is not None and sig.verify and sig.explanation["fusion"]["rule"] == "instant"


def test_video_model_alone_does_not_fire():
    m = ViolenceMonitor("cam", merge_rules())
    assert fuse(m, logit=9.0, pose=0.0, ts=100.0) is None  # VideoMAE is badly calibrated: needs pose support
    assert fuse(m, logit=9.0, pose=0.0, ts=101.0) is None


def test_sustained_rule_needs_two_consecutive():
    m = ViolenceMonitor("cam", merge_rules())
    assert fuse(m, logit=5.5, pose=0.8, ts=100.0) is None
    sig = fuse(m, logit=5.5, pose=0.8, ts=101.0)
    assert sig is not None and sig.explanation["fusion"]["rule"] == "sustained"


def test_cooldown():
    m = ViolenceMonitor("cam", merge_rules())
    assert fuse(m, 9.0, 0.95, 100.0) is not None
    assert fuse(m, 9.0, 0.95, 105.0) is None
