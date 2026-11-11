from collections import defaultdict
from uuid import UUID

from sw_contracts.validation import RuleError, resolve_manifest
from sw_contracts import CoverageReport, EvidenceManifest, StoryNode, CaptureTask, CaptureVerification, digest
from sw_contracts.models import RequirementCoverage


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

    evidence_by_id = {e.id: e for e in manifest.evidence}
    relevant_by_requirement = {
        requirement: sorted(
            (e for e in manifest.evidence if requirement in e.requirement_keys),
            key=lambda e: (str(e.asset_id), e.in_ms, e.out_ms, str(e.id)),
        )
        for requirement in node.requirements
    }
    qualified_by_requirement = {
        requirement: [
            e for e in rows if e.semantic_support == "supported" and e.quality_usable
        ]
        for requirement, rows in relevant_by_requirement.items()
    }
    qualified_ids = {
        e.id for rows in qualified_by_requirement.values() for e in rows
    }

    def duration_for(ids):
        by_asset = defaultdict(list)
        for evidence_id in ids:
            evidence = evidence_by_id[evidence_id]
            by_asset[evidence.asset_id].append((evidence.in_ms, evidence.out_ms))
        return sum(union_duration(intervals) for intervals in by_asset.values())

    # Deterministic greedy set cover: first satisfy the most unresolved requirements,
    # then maximize new source duration. A reverse pass removes every redundant item.
    selected = set()
    while True:
        covered = {
            requirement for requirement, rows in qualified_by_requirement.items()
            if any(e.id in selected for e in rows)
        }
        current_duration = duration_for(selected)
        if len(covered) == len(node.requirements) and current_duration >= node.minimum_duration_ms:
            break
        options = []
        for evidence_id in qualified_ids - selected:
            evidence = evidence_by_id[evidence_id]
            new_requirements = sum(
                requirement not in covered and requirement in evidence.requirement_keys
                for requirement in node.requirements
            )
            added_duration = duration_for(selected | {evidence_id}) - current_duration
            if new_requirements or added_duration:
                options.append((new_requirements, added_duration, str(evidence_id), evidence_id))
        if not options:
            break
        chosen = min(options, key=lambda row: (-row[0], -row[1], row[2]))
        selected.add(chosen[3])

    for evidence_id in sorted(selected, key=str, reverse=True):
        trial = selected - {evidence_id}
        all_requirements = all(
            any(e.id in trial for e in qualified_by_requirement[requirement])
            for requirement in node.requirements
        )
        if all_requirements and duration_for(trial) >= node.minimum_duration_ms:
            selected = trial

    duration = duration_for(selected)
    requirement_results = []
    uncertainty_reasons = []
    unresolved = []
    for requirement in node.requirements:
        candidates = relevant_by_requirement[requirement]
        qualified = qualified_by_requirement[requirement]
        chosen = [e for e in qualified if e.id in selected]
        if qualified:
            state, reasons = "covered", ["qualified_evidence"]
        elif any(e.semantic_support == "unknown" for e in candidates) or not search_complete:
            state, reasons = "uncertain", [
                "semantic_unknown" if any(e.semantic_support == "unknown" for e in candidates)
                else "search_incomplete"
            ]
            uncertainty_reasons.append(f"{requirement}:{reasons[0]}")
            unresolved.append(state)
        elif any(e.semantic_support == "supported" for e in candidates):
            state, reasons = "insufficient", ["quality_unusable"]
            unresolved.append(state)
        else:
            state, reasons = "missing", ["no_supporting_evidence"]
            unresolved.append(state)
        requirement_results.append(RequirementCoverage(
            requirement_key=requirement,
            state=state,
            candidate_refs=[e.id for e in candidates],
            qualified_refs=[e.id for e in qualified],
            selected_refs=[e.id for e in chosen],
            reason_codes=reasons,
        ))

    requirements_met = all(not rows for rows in unresolved) and all(
        row.state == "covered" for row in requirement_results
    )
    if requirements_met and duration >= node.minimum_duration_ms and search_complete:
        state = "covered"
        reasons = ["minimum_sufficient_evidence_selected"]
    elif "uncertain" in unresolved or not search_complete:
        state = "uncertain"
        reasons = ["required_evidence_uncertain" if "uncertain" in unresolved else "search_incomplete"]
        if not search_complete and "search_incomplete" not in uncertainty_reasons:
            uncertainty_reasons.append("node:search_incomplete")
    elif "insufficient" in unresolved or (requirements_met and duration < node.minimum_duration_ms):
        state = "insufficient"
        reasons = ["quality_or_duration_shortfall"]
    else:
        state = "missing"
        reasons = ["no_supporting_evidence"]
    if requirements_met and duration < node.minimum_duration_ms:
        reasons.append("duration_below_minimum")

    return CoverageReport(
        project_id=node.project_id,
        node_key=node.node_key,
        coverage=state,
        evaluated_manifest_hash=digest(manifest),
        checked_requirements=node.requirements,
        requirement_results=requirement_results,
        candidate_refs=sorted({e.id for rows in relevant_by_requirement.values() for e in rows}, key=str),
        selected_evidence_refs=sorted(selected, key=str),
        selection_complete=state == "covered",
        uncertainty_reasons=uncertainty_reasons,
        reason_codes=reasons,
        search_complete=search_complete,
        usable_duration_ms=duration,
        minimum_duration_ms=node.minimum_duration_ms,
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
    if recomputed.coverage != "covered" or recomputed.uncertainty_reasons or not recomputed.selection_complete:
        raise RuleError("INVALID_ARGUMENT", "submitted material is not certainly covered")
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
