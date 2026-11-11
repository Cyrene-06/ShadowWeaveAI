from collections import defaultdict
from uuid import UUID

from sw_contracts.validation import RuleError, resolve_manifest
from sw_contracts import CoverageReport, EvidenceManifest, StoryNode, CaptureTask, CaptureVerification, digest


def union_duration(intervals):
    total = 0
    end = -1
    for start, stop in sorted(intervals):
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def evaluate_coverage(node: StoryNode, manifest: EvidenceManifest, search_complete: bool) -> CoverageReport:
    resolve_manifest(manifest)
    if node.project_id != manifest.project_id:
        raise RuleError("INVALID_ARGUMENT", "node project mismatch")
    relevant = [e for e in manifest.evidence if set(node.requirements) & set(e.requirement_keys)]
    qualified = [e for e in relevant if e.semantic_support == "supported" and e.quality_usable]
    supported = {r for e in qualified for r in e.requirement_keys}
    per_source = defaultdict(list)
    for e in qualified:
        per_source[e.asset_id].append((e.in_ms, e.out_ms))
    duration = sum(union_duration(x) for x in per_source.values())
    if set(node.requirements) <= supported and duration >= node.minimum_duration_ms:
        state, reason = "covered", "qualified_evidence"
    elif not search_complete or any(e.semantic_support == "unknown" for e in relevant):
        state, reason = "uncertain", "search_incomplete_or_semantics_unknown"
    elif any(e.semantic_support == "supported" for e in relevant):
        state, reason = "insufficient", "quality_duration_or_requirement_shortfall"
    else:
        state, reason = "missing", "no_supporting_evidence"
    return CoverageReport(
        project_id=node.project_id,
        node_key=node.node_key,
        coverage=state,
        evaluated_manifest_hash=digest(manifest),
        checked_requirements=node.requirements,
        candidate_refs=[e.id for e in relevant],
        reason_codes=[reason],
        search_complete=search_complete,
        usable_duration_ms=duration,
    )


def submit_capture(task: CaptureTask) -> CaptureTask:
    if task.state not in {"open", "in_progress"}:
        raise RuleError("INVALID_ARGUMENT", "capture is not open")
    return task.model_copy(update={"state": "submitted", "revision": task.revision + 1})


def verify_capture(
    task: CaptureTask,
    verification: CaptureVerification,
    manifest: EvidenceManifest,
    node: StoryNode,
    succeeded_analysis_ids: set[UUID],
) -> CaptureTask:
    if (
        task.state != "submitted"
        or verification.task_id != task.id
        or verification.task_revision != task.revision
    ):
        raise RuleError("VERSION_CONFLICT", "stale task result")
    if (
        verification.source_storyboard_id != task.source_storyboard_id
        or verification.source_storyboard_revision != task.source_storyboard_revision
        or verification.result_storyboard_id == task.source_storyboard_id
        or verification.result_storyboard_revision <= task.source_storyboard_revision
    ):
        raise RuleError("VERSION_CONFLICT", "stale/unchanged storyboard")
    if task.project_id != manifest.project_id or node.node_key != task.node_key:
        raise RuleError("INVALID_ARGUMENT", "capture scope mismatch")
    if not set(verification.analysis_run_ids) <= succeeded_analysis_ids:
        raise RuleError("INVALID_ARGUMENT", "analysis has not succeeded")
    relevant = {e.id: e for e in manifest.evidence}
    if not verification.report.candidate_refs or any(
        ref not in relevant or relevant[ref].analysis_run_id not in verification.analysis_run_ids
        for ref in verification.report.candidate_refs
    ):
        raise RuleError("INVALID_ARGUMENT", "verification lacks bound analysis evidence")
    recomputed = evaluate_coverage(node, manifest, verification.report.search_complete)
    if digest(recomputed) != digest(verification.report):
        raise RuleError("INVALID_ARGUMENT", "verification does not match evidence")
    if recomputed.coverage != "covered":
        raise RuleError("INVALID_ARGUMENT", "submitted material still does not cover node")
    return task.model_copy(update={"state": "fulfilled", "revision": task.revision + 1})


def validate_role(envelope, manifest):
    resolve_manifest(manifest)
    if not set(envelope.evidence_refs) <= {e.id for e in manifest.evidence}:
        raise RuleError("INVALID_ARGUMENT", "unregistered role evidence")
    forbidden = {"unlock_clip_keys", "requested_unlock_clip_keys", "submit_version", "command", "shell"}

    def walk(value):
        if isinstance(value, dict):
            if forbidden & value.keys():
                raise RuleError("FORBIDDEN", "role output cannot authorize side effects")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(envelope.result)
    return envelope
