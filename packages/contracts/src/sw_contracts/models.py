from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    waiting_user = "waiting_user"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class Project(Contract):
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    scenario: Literal["campus", "travel", "family_friends", "vlog", "organization"]
    revision: StrictInt = Field(default=1, ge=1)
    head_revision: StrictInt = Field(default=0, ge=0)


class Intent(Contract):
    id: UUID
    project_id: UUID
    revision: StrictInt = Field(ge=1)
    source_text: str = Field(min_length=1)
    target_duration_ms: StrictInt = Field(gt=0)
    state: Literal["draft", "confirmed"]
    constraints: dict[str, Any] = Field(default_factory=dict, json_schema_extra={"default": {}})


class Asset(Contract):
    id: UUID
    project_id: UUID
    media_type: Literal["video", "image", "audio"]
    duration_ms: StrictInt | None = Field(default=None, gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal["ready", "unavailable", "deleted"] = "ready"

    @model_validator(mode="after")
    def duration(self):
        if (self.media_type == "image") != (self.duration_ms is None):
            raise ValueError("image has no source time; video/audio require duration")
        return self


class Segment(Contract):
    id: UUID
    project_id: UUID
    asset_id: UUID
    analysis_run_id: UUID
    in_ms: StrictInt = Field(ge=0)
    out_ms: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def interval(self):
        if self.out_ms <= self.in_ms:
            raise ValueError("empty/reversed half-open interval")
        return self


class Evidence(Contract):
    id: UUID
    project_id: UUID
    asset_id: UUID
    segment_id: UUID
    analysis_run_id: UUID
    in_ms: StrictInt = Field(ge=0)
    out_ms: StrictInt = Field(gt=0)
    method: Literal["human_annotation", "tool_analysis", "model_observation"]
    semantic_support: Literal["supported", "unsupported", "unknown"]
    quality_usable: StrictBool
    requirement_keys: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def interval(self):
        if self.out_ms <= self.in_ms:
            raise ValueError("invalid evidence interval")
        return self


class EvidenceManifest(Contract):
    schema_version: Literal["1.0"] = "1.0"
    project_id: UUID
    dataset_version: str
    assets: list[Asset]
    segments: list[Segment]
    evidence: list[Evidence]


class StoryNode(Contract):
    project_id: UUID
    node_key: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1)
    requirements: list[str] = Field(min_length=1)
    minimum_duration_ms: StrictInt = Field(gt=0)
    required: StrictBool = True


class RequirementCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    requirement_key: str
    state: Literal["covered", "insufficient", "uncertain", "missing"]
    candidate_refs: list[UUID]
    qualified_refs: list[UUID]
    selected_refs: list[UUID]
    reason_codes: list[str]


class CoverageReport(Contract):
    project_id: UUID
    node_key: str
    coverage: Literal["covered", "insufficient", "uncertain", "missing"]
    evaluated_manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    checked_requirements: list[str]
    requirement_results: list[RequirementCoverage]
    candidate_refs: list[UUID]
    selected_evidence_refs: list[UUID]
    selection_complete: StrictBool
    uncertainty_reasons: list[str]
    reason_codes: list[str]
    search_complete: StrictBool
    usable_duration_ms: StrictInt = Field(ge=0)
    minimum_duration_ms: StrictInt = Field(gt=0)
    policy_version: Literal["coverage-2"] = "coverage-2"


class CaptureTask(Contract):
    id: UUID
    project_id: UUID
    kind: Literal["capture", "reshoot"] = "reshoot"
    node_key: str | None
    source_storyboard_id: UUID
    source_storyboard_revision: StrictInt = Field(ge=1)
    instruction: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    state: Literal["open", "in_progress", "submitted", "fulfilled", "unable", "cancelled"] = "open"
    revision: StrictInt = Field(default=1, ge=1)
    user_choice: dict[str, Any] = Field(default_factory=dict, json_schema_extra={"default": {}})

    @model_validator(mode="after")
    def reshoot_node(self):
        if self.kind == "reshoot" and not self.node_key:
            raise ValueError("reshoot requires original node_key")
        return self


class CaptureVerification(Contract):
    task_id: UUID
    task_revision: StrictInt = Field(ge=1)
    source_storyboard_id: UUID
    source_storyboard_revision: StrictInt = Field(ge=1)
    result_storyboard_id: UUID
    result_storyboard_revision: StrictInt = Field(ge=1)
    report_ref: UUID
    job_id: UUID
    analysis_run_ids: list[UUID] = Field(min_length=1)
    report: CoverageReport


class Output(Contract):
    width: Literal[1280, 1920] = 1920
    height: Literal[720, 1080] = 1080
    fps_num: Literal[25, 30] = 25
    fps_den: Literal[1] = 1

    @model_validator(mode="after")
    def preset(self):
        if (self.width, self.height) not in {(1280, 720), (1920, 1080)}:
            raise ValueError("unsupported output preset")
        return self


class Clip(Contract):
    clip_key: str = Field(min_length=1)
    kind: Literal["video", "image", "audio", "subtitle"]
    asset_id: UUID | None = None
    segment_id: UUID | None = None
    src_in_ms: StrictInt | None = Field(default=None, ge=0)
    src_out_ms: StrictInt | None = Field(default=None, gt=0)
    dst_in_ms: StrictInt = Field(ge=0)
    dst_out_ms: StrictInt = Field(gt=0)
    speed_num: StrictInt = Field(default=1, gt=0)
    speed_den: StrictInt = Field(default=1, gt=0)
    locked: StrictBool = False
    config: dict[str, Any] = Field(default_factory=dict, json_schema_extra={"default": {}})
    dependencies: list[str] = Field(default_factory=list, json_schema_extra={"default": []})

    @model_validator(mode="after")
    def ranges(self):
        if self.dst_out_ms <= self.dst_in_ms:
            raise ValueError("invalid target interval")
        if self.kind in {"video", "audio"}:
            if (
                self.asset_id is None
                or self.segment_id is None
                or self.src_in_ms is None
                or self.src_out_ms is None
            ):
                raise ValueError("time-based media requires source and segment")
            if self.src_out_ms <= self.src_in_ms:
                raise ValueError("invalid source interval")
            if (self.src_out_ms - self.src_in_ms) * self.speed_den != (
                self.dst_out_ms - self.dst_in_ms
            ) * self.speed_num:
                raise ValueError("source/target duration mismatch")
        else:
            if self.src_in_ms is not None or self.src_out_ms is not None:
                raise ValueError("image/subtitle source interval must be null")
            if self.speed_num != 1 or self.speed_den != 1:
                raise ValueError("speed only applies to video/audio")
            if self.kind == "subtitle" and (self.asset_id is not None or self.segment_id is not None):
                raise ValueError("subtitle cannot reference media")
            if self.kind == "image" and self.asset_id is None:
                raise ValueError("image requires asset")
        return self


class Track(Contract):
    track_key: str = Field(min_length=1)
    kind: Literal["video", "subtitle", "voiceover", "music", "ambience"]
    position: StrictInt = Field(ge=0)
    clips: list[Clip]


class EDL(Contract):
    schema_version: Literal["1.0"] = "1.0"
    duration_ms: StrictInt = Field(gt=0)
    output: Output = Field(default_factory=Output)
    tracks: list[Track] = Field(min_length=1)


class EditRiskBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    total_clip_count: StrictInt = Field(ge=0)
    affected_clip_count: StrictInt = Field(ge=0)
    affected_ratio: float = Field(ge=0, le=1)
    locked_conflict_count: StrictInt = Field(ge=0)
    unapproved_affected_keys: tuple[str, ...]
    severity: Literal["low", "medium", "high", "blocked"]
    reasons: tuple[str, ...]


class ImpactReport(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_target_keys: tuple[str, ...] = Field(min_length=1)
    predicted_affected_keys: tuple[str, ...]
    approved_affected_keys: tuple[str, ...]
    causes: dict[str, list[str]]
    propagation_paths: dict[str, list[str]]
    risk_budget: EditRiskBudget
    scope_approval_ref: UUID
    lock_conflicts: list[str] = Field(default_factory=list, json_schema_extra={"default": []})
    policy_version: Literal["impact-2"] = "impact-2"


class EditDraft(Contract):
    project_id: UUID
    base_version_id: UUID
    base_revision: StrictInt = Field(ge=0)
    base_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_edl: EDL
    impact_report: ImpactReport
    diff: dict[str, Any]
    validation_report: dict[str, Any]
    requested_unlock_clip_keys: list[str] = Field(default_factory=list, json_schema_extra={"default": []})
    state: Literal["ready"] = "ready"
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Version(Contract):
    id: UUID
    project_id: UUID
    parent_version_id: UUID | None
    revision: StrictInt = Field(ge=1)
    edl: EDL
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Job(Contract):
    id: UUID
    project_id: UUID
    state: JobState
    mode: Literal["synchronous_replay", "async"]
    error_code: str | None = None


class RoleEnvelope(Contract):
    schema_version: Literal["1.0"] = "1.0"
    role: Literal["director", "writer", "visual", "camera", "editor", "sound", "reviewer"]
    status: Literal["ok", "needs_confirmation", "blocked", "failed"]
    result: dict[str, Any]
    evidence_refs: list[UUID]
    uncertainties: list[str]
    decision_summary: str
    issues: list[str]
    next_action: Literal["validate", "request_gap_resolution", "request_edit_scope", "stop"]


def canonical(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class ErrorBody(Contract):
    code: str
    message: str
    retryable: StrictBool
    details: list[dict[str, Any]] = Field(default_factory=list, json_schema_extra={"default": []})


class ErrorEnvelope(Contract):
    error: ErrorBody
    request_id: UUID
