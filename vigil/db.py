"""Database: SQLAlchemy 2 async. SQLite (WAL) by default, Postgres via VIGIL_DATABASE_URL."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
                        event)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from vigil.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class UTC(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("usr"))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin | analyst | viewer
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTC, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(UTC, nullable=True)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(16))  # frs | rtsp | http | file
    source_uri: Mapped[str] = mapped_column(Text)  # FRS camera id for frs; url/path otherwise
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    loop: Mapped[bool] = mapped_column(Boolean, default=False)  # file sources
    realtime: Mapped[bool] = mapped_column(Boolean, default=True)  # file sources: pace to wall clock
    analysis_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # rule overrides, business hours, lines
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # synthetic demo data
    created_at: Mapped[datetime] = mapped_column(UTC, default=utcnow)


class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("zn"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="monitored")  # restricted | monitored | entry
    polygon: Mapped[list] = mapped_column(JSON)  # [[x,y],...] normalised 0..1
    rules: Mapped[dict] = mapped_column(JSON, default=dict)  # loiter_s, max_occupancy, schedule
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Identity(Base):
    __tablename__ = "identities"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # P-000123
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="unknown")  # enrolled | unknown
    category: Mapped[str] = mapped_column(String(20), default="none")  # none | staff | vip | watch | banned
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    frs_criminal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    frs_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    frs_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    frs_checked_at: Mapped[datetime | None] = mapped_column(UTC, nullable=True)
    frs_checked_q: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(UTC, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(UTC, nullable=True, index=True)
    last_camera_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sightings: Mapped[int] = mapped_column(Integer, default=0)
    best_face_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_face_quality: Mapped[float] = mapped_column(Float, default=0.0)
    merged_into: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # synthetic demo data
    created_at: Mapped[datetime] = mapped_column(UTC, default=utcnow)


class FaceVector(Base):
    __tablename__ = "face_vectors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey("identities.id", ondelete="CASCADE"), index=True)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32[512], L2-normalised
    quality: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20))  # enrollment | auto
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTC, default=utcnow)


class Track(Base):
    """One continuous observation of one person on one camera (a sighting)."""
    __tablename__ = "tracks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    local_id: Mapped[int] = mapped_column(Integer)
    identity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    identity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    identity_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTC, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTC, nullable=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    path: Mapped[list] = mapped_column(JSON, default=list)  # [[t_rel, x, y], ...] normalised
    max_speed: Mapped[float] = mapped_column(Float, default=0.0)  # body-heights / s
    mean_speed: Mapped[float] = mapped_column(Float, default=0.0)
    zones: Mapped[dict] = mapped_column(JSON, default=dict)  # zone_id -> dwell seconds
    best_person_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_face_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # CLIP float16[512]
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    anomaly_score: Mapped[float] = mapped_column(Float, default=0.0)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # synthetic demo data


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evt"))
    ts: Mapped[datetime] = mapped_column(UTC, index=True)
    camera_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_ids: Mapped[list] = mapped_column(JSON, default=list)
    identity_ids: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # {keyframes:[...], clip: path}
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|verified|rejected|dismissed
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    incident_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("inc"))
    created_at: Mapped[datetime] = mapped_column(UTC, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTC, default=utcnow)
    title: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="new")  # new|investigating|confirmed|false_positive|resolved
    camera_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    conclusion: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    identity_ids: Mapped[list] = mapped_column(JSON, default=list)
    report_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    assigned_to: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # synthetic demo data


class FRSSearch(Base):
    """Every watchlist search VIGIL sent to the FRS backend (FRS logs them too; this is our side)."""
    __tablename__ = "frs_searches"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("frs"))
    ts: Mapped[datetime] = mapped_column(UTC, default=utcnow, index=True)
    identity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    camera_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    track_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="auto")  # auto | manual
    outcome: Mapped[str] = mapped_column(String(20))  # match | no_match | no_face | error
    criminal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_k: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    agent: Mapped[str] = mapped_column(String(40), index=True)
    trigger: Mapped[str] = mapped_column(String(200))
    incident_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|done|failed
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTC, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTC, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTC, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


def demo_filter(stmt, model, demo: str | None):
    """demo = include (default) | exclude | only. Synthetic rows are flagged is_demo."""
    if demo == "exclude":
        return stmt.where(model.is_demo.is_(False))
    if demo == "only":
        return stmt.where(model.is_demo.is_(True))
    return stmt


def involves(identity_id: str):
    """SQL filter: event lists this identity. JSON array as text, portable to SQLite and Postgres."""
    from sqlalchemy import String, cast
    safe = identity_id.replace("%", "").replace("_", "\\_").replace('"', "")
    return cast(Event.identity_ids, String).like(f'%"{safe}"%', escape="\\")


Index("ix_tracks_cam_start", Track.camera_id, Track.started_at)
Index("ix_events_type_ts", Event.type, Event.ts)

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine():
    global _engine, _sessionmaker
    if _engine is None:
        url = get_settings().db_url
        kw = {}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"timeout": 30}
        _engine = create_async_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(_engine.sync_engine, "connect")
            def _pragmas(dbapi_conn, _):  # pragma: no cover - sqlite hook
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session() -> AsyncSession:
    engine()
    assert _sessionmaker is not None
    return _sessionmaker()


async def get_db():
    async with session() as s:
        yield s


def _add_missing_columns(sync_conn) -> list[str]:
    """Additive migration: create columns that exist in the models but not in the DB.

    Only ever ADDs nullable columns (portable across SQLite/Postgres); renames and
    drops are deliberately not automatic.
    """
    from sqlalchemy import inspect
    insp = inspect(sync_conn)
    added = []
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have:
                ddl = col.type.compile(dialect=sync_conn.dialect)
                sync_conn.exec_driver_sql(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}')
                added.append(f"{table.name}.{col.name}")
            # Backfill scalar defaults: existing rows must not be NULL where code filters on the value
            # (e.g. is_demo = false would silently hide every pre-existing real row).
            dflt = col.default.arg if col.default is not None and col.default.is_scalar else None
            if dflt is not None:
                sync_conn.exec_driver_sql(f'UPDATE {table.name} SET "{col.name}" = ? WHERE "{col.name}" IS NULL'
                                          if sync_conn.dialect.name == "sqlite" else
                                          f'UPDATE {table.name} SET "{col.name}" = %s WHERE "{col.name}" IS NULL',
                                          (dflt,))
    return added


async def init_db() -> None:
    import logging
    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        added = await conn.run_sync(_add_missing_columns)
    if added:
        logging.getLogger("vigil.db").info("schema migration added columns: %s", added)
