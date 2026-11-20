from sqlalchemy import (
    JSON, BigInteger, CheckConstraint, Column, ForeignKeyConstraint, Index, Integer,
    String, Table, Text, UniqueConstraint,
)


def phase_two_schema(metadata):
    # This schema is copied into an immutable migration snapshot on release.
    assets = Table(
        "media_catalog", metadata,
        Column("asset_id", String(36), primary_key=True),
        Column("project_id", String(36), nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("name", String(250), nullable=False),
        Column("latest_generation", Integer, nullable=False),
        Column("active_analysis_id", String(36)),
        UniqueConstraint("project_id", "sha256"),
        ForeignKeyConstraint(["project_id", "asset_id"], ["assets.project_id", "assets.id"]),
        ForeignKeyConstraint(
            ["project_id", "active_analysis_id", "asset_id"],
            ["analysis_runs.project_id", "analysis_runs.id", "analysis_runs.asset_id"],
        ),
        CheckConstraint("latest_generation > 0"),
    )
    runs = Table(
        "media_runs", metadata,
        Column("id", String(36), primary_key=True),
        Column("project_id", String(36), nullable=False),
        Column("asset_id", String(36), nullable=False),
        Column("job_id", String(36), nullable=False, unique=True),
        Column("generation", Integer, nullable=False),
        Column("enqueued_ms", BigInteger, nullable=False),
        Column("stage", String(24), nullable=False),
        Column("attempts", Integer, nullable=False),
        Column("lease_token", String(36)),
        Column("lease_until_ms", BigInteger),
        Column("started_ms", BigInteger),
        Column("finished_ms", BigInteger),
        Column("error_code", String(48)),
        Column("result", JSON),
        UniqueConstraint("asset_id", "generation"),
        ForeignKeyConstraint(
            ["project_id", "id", "asset_id"],
            ["analysis_runs.project_id", "analysis_runs.id", "analysis_runs.asset_id"],
        ),
        ForeignKeyConstraint(["project_id", "job_id"], ["jobs.project_id", "jobs.id"]),
        CheckConstraint("generation > 0 AND attempts >= 0"),
        CheckConstraint("stage IN ('queued','probe','media','speech','publish','succeeded','failed')"),
        CheckConstraint("(lease_token IS NULL) = (lease_until_ms IS NULL)"),
        Index("ix_media_runs_queue", "stage", "enqueued_ms"),
    )
    observations = Table(
        "media_observations", metadata,
        Column("segment_id", String(36), primary_key=True),
        Column("project_id", String(36), nullable=False),
        Column("frame_ms", BigInteger, nullable=False),
        Column("frame_key", Text, nullable=False),
        Column("transcript", JSON, nullable=False),
        Column("signals", JSON, nullable=False),
        ForeignKeyConstraint(["project_id", "segment_id"], ["segments.project_id", "segments.id"]),
        CheckConstraint("frame_ms >= 0"),
    )
    tags = Table(
        "media_tags", metadata,
        Column("id", String(36), primary_key=True),
        Column("project_id", String(36), nullable=False),
        Column("segment_id", String(36), nullable=False),
        Column("label", String(80), nullable=False),
        ForeignKeyConstraint(["project_id", "segment_id"], ["segments.project_id", "segments.id"]),
        UniqueConstraint("segment_id", "label"),
    )
    return assets, runs, observations, tags
