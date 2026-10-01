"""Tests run against an isolated data dir; nothing touches the live service's DB or media."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="vigil-test-")
os.environ["VIGIL_DATA_DIR"] = _TMP
os.environ["VIGIL_ADMIN_PASSWORD"] = "test-admin-pw"
os.environ["VIGIL_FRS_ENABLED"] = "false"
os.environ["VIGIL_AGENTS_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from vigil.perception.tracking import TrackState  # noqa: E402


def make_track(uid="t1", box=(100, 100, 160, 300), ts=0.0, kps=None, local_id=1):
    k = np.zeros((17, 3), np.float32) if kps is None else kps
    return TrackState(uid, local_id, "cam", ts, ts, np.array(box, np.float32), k, 0.9)


def upright_kps(box):
    """Plausible standing skeleton inside box (x1,y1,x2,y2)."""
    x1, y1, x2, y2 = box
    cx, h = (x1 + x2) / 2, y2 - y1
    k = np.zeros((17, 3), np.float32)
    pts = {0: (cx, y1 + .08 * h), 1: (cx - 5, y1 + .06 * h), 2: (cx + 5, y1 + .06 * h), 3: (cx - 9, y1 + .07 * h),
           4: (cx + 9, y1 + .07 * h), 5: (cx - 20, y1 + .2 * h), 6: (cx + 20, y1 + .2 * h), 7: (cx - 24, y1 + .35 * h),
           8: (cx + 24, y1 + .35 * h), 9: (cx - 26, y1 + .48 * h), 10: (cx + 26, y1 + .48 * h),
           11: (cx - 14, y1 + .52 * h), 12: (cx + 14, y1 + .52 * h), 13: (cx - 14, y1 + .75 * h),
           14: (cx + 14, y1 + .75 * h), 15: (cx - 14, y1 + .97 * h), 16: (cx + 14, y1 + .97 * h)}
    for i, (x, y) in pts.items():
        k[i] = (x, y, 0.95)
    return k


@pytest.fixture
def track_factory():
    return make_track
