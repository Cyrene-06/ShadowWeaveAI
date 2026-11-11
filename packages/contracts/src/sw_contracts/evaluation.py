"""Offline evaluation preparation records; separate from the 21 product contracts."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scenario = Literal["campus", "travel", "family_friends", "vlog", "organization"]


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Record(Shape):
    schema_version: Literal["1.0"] = "1.0"
    record_stage: Literal["template", "ready"] = "template"


class Rights(Shape):
    status: Literal["pending", "approved"]
    permission_ref: str | None
    allowed_uses: list[Literal["development", "evaluation", "publication"]]


class DatasetAsset(Shape):
    asset_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: Literal["video", "audio", "image", "metadata"]
    duration_ms: int | None = Field(default=None, gt=0)
    source_kind: Literal["real_capture", "generated_probe", "synthetic_metadata"]
    event_id: str = Field(min_length=1)
    duplicate_group: str = Field(min_length=1)
    parent_asset_id: str | None = None
    rights: Rights


class DatasetTask(Shape):
    task_id: str = Field(min_length=1)
    scenario: Scenario
    split: Literal["development", "frozen_test"]
    event_id: str = Field(min_length=1)
    asset_ids: list[str] = Field(min_length=1)
    intent_ref: str = Field(min_length=1)


class DatasetManifest(Record):
    record_type: Literal["dataset_manifest"] = "dataset_manifest"
    dataset_version: str | None = None
    assets: list[DatasetAsset] = Field(default_factory=list)
    tasks: list[DatasetTask] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EvidenceLabel(Shape):
    asset_id: str
    in_ms: int | None = Field(default=None, ge=0)
    out_ms: int | None = Field(default=None, gt=0)
    requirement_keys: list[str] = Field(min_length=1)
    semantic_support: Literal["supported", "unsupported", "unknown"]
    quality_usable: bool | None


class NodeLabel(Shape):
    node_key: str = Field(min_length=1)
    requirement_keys: list[str] = Field(min_length=1)
    coverage: Literal["covered", "insufficient", "uncertain", "missing"]
    search_complete: bool
    gap_types: list[str]
    evidence: list[EvidenceLabel]
    rationale: str = Field(min_length=1)


class EditLabel(Shape):
    request_id: str = Field(min_length=1)
    target_clip_keys: list[str] = Field(min_length=1)
    acceptable_impact_keys: list[str] = Field(min_length=1)
    locked_clip_keys: list[str]
    rationale: str = Field(min_length=1)


class AnnotationRecord(Record):
    record_type: Literal["annotation"] = "annotation"
    dataset_version: str | None = None
    task_id: str | None = None
    annotator_id: str | None = None
    annotation_revision: int = Field(default=1, ge=1)
    annotation_stage: Literal["independent", "adjudicated"] = "independent"
    independent_source_refs: list[str] = Field(default_factory=list)
    adjudicator_id: str | None = None
    disagreements: list[str] = Field(default_factory=list)
    nodes: list[NodeLabel] = Field(default_factory=list)
    edits: list[EditLabel] = Field(default_factory=list)


class RunRecord(Record):
    record_type: Literal["evaluation_run"] = "evaluation_run"
    dataset_version: str | None = None
    task_id: str | None = None
    scenario: Scenario | None = None
    condition: Literal["A", "B", "C", "D1", "D1b", "D2", "D3"] | None = None
    code_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    graph_version: str | None = None
    prompt_version: str | None = None
    model_profile: dict | None = None
    model_called: bool = False
    random_seed: int | None = None
    hardware: dict | None = None
    budget: dict | None = None
    timing_boundaries: dict[str, str | None] = Field(default_factory=dict)
    timings_seconds: dict[str, float] = Field(default_factory=dict)
    input_manifest_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    approved_impact_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    status: Literal[
        "not_run", "succeeded", "failed", "timed_out", "cancelled", "waiting_user", "budget_exceeded"
    ] = "not_run"
    failure_code: str | None = None
    raw_artifact_refs: list[str] = Field(default_factory=list)
    usage: dict | None = None
    cost: str | None = None
    notes: list[str] = Field(default_factory=list)


REGISTRY = {
    cls.model_fields["record_type"].default: cls for cls in (DatasetManifest, AnnotationRecord, RunRecord)
}


def required(value, *names):
    for name in names:
        if getattr(value, name) in (None, "", [], {}):
            raise ValueError(f"ready record requires {name}")


def unique(values, name):
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name}")


def validate_manifest(manifest):
    required(manifest, "dataset_version", "assets", "tasks")
    unique([a.asset_id for a in manifest.assets], "asset_id")
    unique([t.task_id for t in manifest.tasks], "task_id")
    assets = {a.asset_id: a for a in manifest.assets}
    allocations = {}
    for task in manifest.tasks:
        unique(task.asset_ids, "task asset_id")
        for aid in task.asset_ids:
            if aid not in assets:
                raise ValueError("task refers to unknown asset")
            asset = assets[aid]
            if asset.event_id != task.event_id:
                raise ValueError("task and asset event_id differ")
            use = "evaluation" if task.split == "frozen_test" else "development"
            if (
                asset.rights.status != "approved"
                or not asset.rights.permission_ref
                or use not in asset.rights.allowed_uses
            ):
                raise ValueError("missing source permission for requested use")
            if task.split == "frozen_test" and asset.source_kind != "real_capture":
                raise ValueError("generated probes and synthetic metadata cannot enter frozen_test")
            if asset.media_type in ("video", "audio") and asset.duration_ms is None:
                raise ValueError("timed media requires measured duration_ms")
            lineage = []
            ancestor = asset
            while ancestor.parent_asset_id:
                if ancestor.parent_asset_id not in assets or ancestor.asset_id in lineage:
                    raise ValueError("invalid or cyclic asset lineage")
                lineage.append(ancestor.asset_id)
                ancestor = assets[ancestor.parent_asset_id]
            # Original/crop families, exact bytes, events and near-duplicate groups stay together.
            keys = [
                ("sha", asset.sha256),
                ("event", task.event_id),
                ("duplicate", asset.duplicate_group),
                ("lineage", ancestor.asset_id),
            ]
            for key in keys:
                if key in allocations and allocations[key] != task.split:
                    raise ValueError(f"cross-split leakage: {key[0]}")
                allocations[key] = task.split
    return manifest


def validate_record(payload, manifest=None, require_ready=False):
    if not isinstance(payload, dict):
        raise ValueError("evaluation record must be a JSON object")
    kind = payload.get("record_type")
    if kind not in REGISTRY:
        raise ValueError("unknown evaluation record_type")
    record = REGISTRY[kind].model_validate(payload)
    if require_ready and record.record_stage != "ready":
        raise ValueError("unfilled template cannot be treated as an executed/ready record")
    if record.record_stage == "template":
        return record
    if isinstance(record, DatasetManifest):
        return validate_manifest(record)
    required(record, "dataset_version", "task_id")
    if manifest is None or manifest.record_stage != "ready":
        raise ValueError("ready annotation/run requires a validated ready manifest")
    validate_manifest(manifest)
    tasks = {t.task_id: t for t in manifest.tasks}
    if record.dataset_version != manifest.dataset_version or record.task_id not in tasks:
        raise ValueError("unknown dataset/task reference")
    task = tasks[record.task_id]
    if isinstance(record, AnnotationRecord):
        required(record, "annotator_id", "nodes")
        unique([n.node_key for n in record.nodes], "node_key")
        unique([e.request_id for e in record.edits], "request_id")
        if record.annotation_stage == "adjudicated":
            required(record, "adjudicator_id", "independent_source_refs")
            if len(set(record.independent_source_refs)) < 2:
                raise ValueError("adjudication needs two distinct independent source references")
        assets = {a.asset_id: a for a in manifest.assets}
        for node in record.nodes:
            if not node.search_complete and node.coverage == "missing":
                raise ValueError("unfinished search cannot be labelled missing")
            if node.coverage in ("covered", "insufficient") and not node.evidence:
                raise ValueError("supported coverage label requires evidence")
            supported = [e for e in node.evidence if e.semantic_support == "supported"]
            if node.coverage == "missing" and any(e.semantic_support != "unsupported" for e in node.evidence):
                raise ValueError("missing label contradicts supporting/unknown evidence")
            if node.coverage == "insufficient" and not supported:
                raise ValueError("insufficient label requires known semantic support")
            if node.coverage == "covered":
                usable = {k for e in supported if e.quality_usable for k in e.requirement_keys}
                if not set(node.requirement_keys) <= usable:
                    raise ValueError("covered label lacks usable support for every requirement")
            for ev in node.evidence:
                if ev.asset_id not in task.asset_ids:
                    raise ValueError("annotation evidence must belong to task")
                asset = assets[ev.asset_id]
                if asset.media_type in ("audio", "video"):
                    if (
                        ev.in_ms is None
                        or ev.out_ms is None
                        or not 0 <= ev.in_ms < ev.out_ms <= asset.duration_ms
                    ):
                        raise ValueError("annotation interval outside source")
                elif ev.in_ms is not None or ev.out_ms is not None:
                    raise ValueError("untimed media cannot have a source time interval")
        return record
    required(
        record,
        "scenario",
        "condition",
        "code_commit",
        "graph_version",
        "prompt_version",
        "hardware",
        "budget",
        "timing_boundaries",
        "input_manifest_hash",
        "raw_artifact_refs",
    )
    if record.scenario != task.scenario or record.status == "not_run":
        raise ValueError("run scenario mismatch or unexecuted run")
    if record.status in ("failed", "timed_out", "cancelled", "budget_exceeded"):
        required(record, "failure_code")
    elif record.failure_code:
        raise ValueError("nonfailure state cannot claim a failure_code")
    if record.model_called:
        required(record, "model_profile")
    elif record.model_profile is not None or record.usage is not None or record.cost is not None:
        raise ValueError("no model call: model_profile, usage and cost must stay null")
    if any(not 0 <= seconds < float("inf") for seconds in record.timings_seconds.values()):
        raise ValueError("timings must be finite and nonnegative")
    stamps = {}
    for name in ("received_at", "finished_at"):
        raw = record.timing_boundaries.get(name)
        if name == "finished_at" and record.status == "waiting_user" and raw is None:
            continue
        if raw is None:
            raise ValueError(f"missing timing boundary {name}")
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError("timing boundaries must use UTC offsets")
        stamps[name] = stamp
    if stamps.get("finished_at", stamps["received_at"]) < stamps["received_at"]:
        raise ValueError("run finishes before it starts")
    return record
