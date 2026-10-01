"""Signal: what perception/analytics hand to the agent layer. Always explainable."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

DEFAULT_RULES: dict[str, dict] = {
    "loitering": {"enabled": True, "dwell_s": 90, "max_radius": 0.12, "severity": "medium"},
    "zone_intrusion": {"enabled": True, "severity": "high"},
    "running": {"enabled": True, "speed_bh_s": 2.2, "min_duration_s": 1.0, "severity": "low"},
    "fall": {"enabled": True, "torso_deg": 60, "min_down_s": 1.5, "severity": "high"},
    "crowd": {"enabled": True, "min_people": 5, "radius_bh": 2.5, "min_duration_s": 8, "severity": "medium"},
    "abandoned_object": {"enabled": True, "unattended_s": 45, "owner_radius_bh": 2.0, "severity": "high"},
    "weapon": {"enabled": True, "min_hits": 3, "severity": "critical"},
    "after_hours": {"enabled": False, "open": "07:00", "close": "21:00", "severity": "medium"},
    "pacing": {"enabled": True, "reversals": 6, "window_s": 120, "severity": "low"},
    "anomalous_path": {"enabled": True, "min_samples": 3000, "percentile": 1.5, "severity": "low"},
    "repeated_appearance": {"enabled": True, "min_visits": 4, "window_min": 60, "severity": "medium"},
    "occupancy": {"enabled": True, "severity": "medium"},
    "violence": {"enabled": True, "severity": "high", "trigger": 0.85, "sustain": 0.78},
    "watchlist": {"enabled": True, "severity": "critical"},
}

EVENT_TYPES = {
    "violence": "Physical violence",
    "watchlist_match": "Watchlist match (FRS)",
    "weapon": "Weapon visible",
    "fall": "Person down / fall",
    "zone_intrusion": "Restricted zone intrusion",
    "loitering": "Loitering",
    "abandoned_object": "Unattended object",
    "crowd": "Crowd gathering",
    "running": "Running",
    "after_hours": "After-hours presence",
    "pacing": "Pacing / casing behaviour",
    "anomalous_path": "Anomalous trajectory",
    "repeated_appearance": "Repeated appearance",
    "occupancy": "Zone over capacity",
}


def merge_rules(*layers: dict | None) -> dict:
    out = copy.deepcopy(DEFAULT_RULES)
    for layer in layers:
        for k, v in (layer or {}).items():
            if k in out and isinstance(v, dict):
                out[k].update(v)
    return out


@dataclass
class Signal:
    type: str
    severity: str
    confidence: float
    title: str
    description: str
    camera_id: str
    ts: float
    track_uids: list[str] = field(default_factory=list)
    identity_ids: list[str] = field(default_factory=list)
    explanation: dict = field(default_factory=dict)
    boxes: list = field(default_factory=list)  # [[x1,y1,x2,y2,label], ...] full-frame coords
    verify: bool = False  # ask the threat agent to verify with the VLM
    event_id: str | None = None
    evidence: dict = field(default_factory=dict)
