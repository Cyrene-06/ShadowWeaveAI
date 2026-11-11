import os
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    MetaData,
    Table,
    Column,
    String,
    Integer,
    BigInteger,
    Text,
    DateTime,
    JSON,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    CheckConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import Session

metadata = MetaData()


def now():
    return datetime.now(timezone.utc)


def common():
    return [
        Column("id", String(36), primary_key=True, default=lambda: str(uuid4())),
        Column("created_at", DateTime(timezone=True), nullable=False, default=now),
    ]


users = Table(
    "users",
    metadata,
    *common(),
    Column("email", String(254), unique=True, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("display_name", String(80), nullable=False),
)
sessions = Table(
    "auth_sessions",
    metadata,
    *common(),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("token_hash", String(64), unique=True, nullable=False),
    Column("family_id", String(36), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("client_kind", String(10), nullable=False),
)
projects = Table(
    "projects",
    metadata,
    *common(),
    Column("owner_id", ForeignKey("users.id"), nullable=False),
    Column("name", String(120), nullable=False),
    Column("scenario", String(30), nullable=False),
    Column("revision", Integer, nullable=False, default=1),
    Column("head_revision", Integer, nullable=False, default=0),
    CheckConstraint("revision >= 1 AND head_revision >= 0"),
)
members = Table(
    "project_members",
    metadata,
    *common(),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("role", String(10), nullable=False),
    UniqueConstraint("project_id", "user_id"),
    CheckConstraint("role IN ('editor','viewer')"),
)
objects = Table(
    "stored_objects",
    metadata,
    *common(),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    UniqueConstraint("project_id", "id"),
    CheckConstraint("size_bytes >= 0"),
)
assets = Table(
    "assets",
    metadata,
    *common(),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("original_object_id", String(36), nullable=False),
    Column("media_type", String(10), nullable=False),
    Column("duration_ms", BigInteger),
    Column("sha256", String(64), nullable=False),
    Column("license_info", JSON, nullable=False),
    UniqueConstraint("project_id", "id"),
    ForeignKeyConstraint(
        ["project_id", "original_object_id"], ["stored_objects.project_id", "stored_objects.id"]
    ),
    CheckConstraint("duration_ms IS NULL OR duration_ms > 0"),
)
jobs = Table(
    "jobs",
    metadata,
    *common(),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("state", String(20), nullable=False),
    UniqueConstraint("project_id", "id"),
    CheckConstraint("state IN ('queued','running','waiting_user','succeeded','failed','cancelled')"),
)
analyses = Table(
    "analysis_runs",
    metadata,
    *common(),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("asset_id", String(36), nullable=False),
    Column("root_job_id", String(36), nullable=False),
    Column("config_hash", String(64), nullable=False),
    Column("config_snapshot", JSON, nullable=False),
    Column("state", String(20), nullable=False),
    UniqueConstraint("project_id", "id", "asset_id"),
    ForeignKeyConstraint(["project_id", "asset_id"], ["assets.project_id", "assets.id"]),
    ForeignKeyConstraint(["project_id", "root_job_id"], ["jobs.project_id", "jobs.id"]),
)
segments = Table(
    "segments",
    metadata,
    *common(),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("asset_id", String(36), nullable=False),
    Column("analysis_run_id", String(36), nullable=False),
    Column("in_ms", BigInteger, nullable=False),
    Column("out_ms", BigInteger, nullable=False),
    UniqueConstraint("project_id", "id"),
    ForeignKeyConstraint(
        ["project_id", "analysis_run_id", "asset_id"],
        ["analysis_runs.project_id", "analysis_runs.id", "analysis_runs.asset_id"],
    ),
    CheckConstraint("in_ms >= 0 AND out_ms > in_ms"),
)
idempotency = Table(
    "api_idempotency",
    metadata,
    *common(),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("operation", String(100), nullable=False),
    Column("key", String(128), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("response", JSON, nullable=False),
    UniqueConstraint("user_id", "operation", "key"),
)


# Development-only fixture state; never used to publish actual media versions.
replay_datasets = Table(
    "phase_one_datasets",
    metadata,
    Column("project_id", ForeignKey("projects.id"), primary_key=True),
    Column("bundle", JSON, nullable=False),
)


def get_engine(url=None):
    url = url or os.environ.get("DATABASE_URL", "sqlite:///artifacts/phase-one.sqlite3")
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def foreign_keys(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    return engine


@contextmanager
def session(engine):
    with Session(engine) as db:
        with db.begin():
            yield db
