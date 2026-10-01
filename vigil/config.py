"""Single settings object. Every knob is an env var (prefix VIGIL_) or .env entry."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIGIL_", env_file=str(ROOT / ".env"), extra="ignore")

    # ── service ──────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8090
    tls_cert: str | None = None
    tls_key: str | None = None
    data_dir: Path = ROOT / "data"
    database_url: str | None = None  # default: sqlite+aiosqlite in data_dir
    log_level: str = "INFO"
    timezone: str = "Asia/Kolkata"

    # ── auth ─────────────────────────────────────────────────────────────
    jwt_secret: str | None = None  # generated + persisted in data_dir when unset
    jwt_ttl_hours: int = 12
    admin_username: str = "admin"
    admin_password: str | None = None  # generated + written to data_dir when unset
    cookie_secure: bool = False  # set true when served over TLS

    # ── existing FRS backend (port 8000) — READ-ONLY integration ─────────
    frs_url: str = "https://127.0.0.1:8000"
    frs_verify_tls: bool = False  # FRS uses a self-signed LAN cert
    frs_enabled: bool = True
    #: Each FRS /api/match call persists a match_event + the upload on the FRS
    #: side, so we query it once per identity at its best face, rate-limited.
    frs_watchlist_check_interval_s: float = 600.0
    #: Without a clearly better face (+0.1 quality) an identity is re-searched only this often,
    #: which still catches people enrolled in FRS after our first check.
    frs_watchlist_recheck_s: float = 6 * 3600.0
    frs_watchlist_min_face_px: int = 56
    frs_relay_width: int = 1280
    frs_relay_fps: int = 15

    # ── models ───────────────────────────────────────────────────────────
    models_dir: Path = ROOT / "models"
    pose_model: str = "yolo11s-pose.pt"  # m-pose is ~2x the GPU cost; measured equal on the violence eval
    object_model: str = "yolo11s.pt"
    pose_imgsz: int = 960
    object_imgsz: int = 768
    object_every_n: int = 6
    person_conf: float = 0.35
    face_det_model: Path = Path("/home/vajra/umeshdr/frs_final/models/retinaface/det_10g.onnx")
    face_rec_model: Path = Path("/home/vajra/umeshdr/frs_final/models/adaface/adaface_ir101_webface12m.onnx")
    violence_model_dir: Path = ROOT / "models" / "violence" / "videomae_rwf2000"
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"
    device: str = "cuda"

    # ── identity ─────────────────────────────────────────────────────────
    #: AdaFace IR101 cosine for matching a track to a gallery identity. The FRS
    #: calibrates 0.26 + z>=5 for 1:N watchlist search; we re-identify people
    #: among ourselves on pooled track embeddings, so we run stricter and add a
    #: margin test against the runner-up identity.
    face_match_threshold: float = 0.40
    face_match_margin: float = 0.06
    face_min_px: int = 40
    face_min_quality: float = 0.35
    face_obs_for_new_identity: int = 3
    #: A new identity is created only if the pooled face is clearly nobody we know (best < this).
    #: Between this and face_match_threshold the track keeps collecting views: an occluded or backlit
    #: face of a known person lands there (measured on a real webcam: 0.339 split one person in two).
    face_new_identity_max_sim: float = 0.30
    face_max_auto_vectors: int = 12
    identity_recheck_s: float = 4.0

    # ── analytics ────────────────────────────────────────────────────────
    analysis_fps: float = 12.0
    live_jpeg_quality: int = 70
    live_width: int = 960
    clip_pre_s: float = 6.0
    clip_post_s: float = 4.0
    ring_fps: float = 8.0
    violence_logit_threshold: float = 4.0
    violence_eval_interval_s: float = 1.0
    violence_trigger_score: float = 0.62
    event_cooldown_s: float = 45.0
    #: Evidence of events not linked to an incident, and per-track crops, expire after this many days.
    #: Incident evidence and identity portraits are kept.
    retention_days: int = 30

    # ── agents / LLM ─────────────────────────────────────────────────────
    ollama_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3.8:latest"
    vlm_model: str = "qwen3-vl:8b-instruct"
    llm_timeout_s: float = 180.0
    agent_max_steps: int = 8
    agents_enabled: bool = True
    auto_investigate_min_severity: str = "high"
    notify_webhook_url: str | None = None

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{self.data_dir / 'vigil.db'}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("evidence", "faces", "persons", "uploads", "reports", "enroll"):
        (s.media_dir / sub).mkdir(parents=True, exist_ok=True)
    return s


SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
