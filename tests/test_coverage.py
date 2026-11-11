from uuid import uuid4

import pytest
from pydantic import ValidationError
from sw_contracts import StoryNode, Segment, RoleEnvelope, CaptureTask, CaptureVerification, EvidenceManifest
from sw_contracts.validation import resolve_manifest, RuleError
from sw_ai.coverage import evaluate_coverage, submit_capture, verify_capture, validate_role
from sw_api.replay import run_replay


def test_four_states_and_incomplete_search(bundle, manifest):
    for raw in bundle["nodes"]:
        node = StoryNode.model_validate(raw)
        report = evaluate_coverage(node, manifest, True)
        assert report.coverage == bundle["expected"]["coverage"][node.node_key]
    node = StoryNode.model_validate(bundle["nodes"][-1])
    assert evaluate_coverage(node, manifest, False).coverage == "uncertain"
    manifest.evidence[0].requirement_keys = ["farewell"]
    manifest.evidence[0].semantic_support = "unknown"
    assert evaluate_coverage(node, manifest, True).coverage == "uncertain"


def test_overlap_is_not_extra_duration(bundle, manifest):
    node = StoryNode.model_validate(bundle["nodes"][1])
    node.minimum_duration_ms = 7000
    old = manifest.evidence[1]
    extra = old.model_copy(deep=True, update={"id": uuid4(), "in_ms": 2000, "out_ms": 6000})
    manifest.evidence.append(extra)
    report = evaluate_coverage(node, manifest, True)
    assert report.usable_duration_ms == 6000
    assert report.coverage == "insufficient"
    extra.out_ms = 8000
    assert evaluate_coverage(node, manifest, True).usable_duration_ms == 8000


@pytest.mark.parametrize("in_ms,out_ms", [(-1, 10), (0, 0), (20, 10), (True, 100), (0, 1.5)])
def test_invalid_segment_contract(manifest, in_ms, out_ms):
    raw = manifest.segments[0].model_dump(mode="json")
    raw.update(in_ms=in_ms, out_ms=out_ms)
    with pytest.raises(ValidationError):
        Segment.model_validate(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        "outside_project",
        "outside_source",
        "wrong_analysis",
        "wrong_asset",
        "missing_segment",
        "duplicate_evidence",
    ],
)
def test_resolver_refuses_forged_references(manifest, mutation):
    if mutation == "outside_project":
        manifest.evidence[0].project_id = uuid4()
    elif mutation == "outside_source":
        manifest.evidence[0].out_ms = 13000
    elif mutation == "wrong_analysis":
        manifest.evidence[0].analysis_run_id = uuid4()
    elif mutation == "wrong_asset":
        manifest.evidence[0].asset_id = manifest.assets[1].id
    elif mutation == "missing_segment":
        manifest.evidence[0].segment_id = uuid4()
    else:
        manifest.evidence.append(manifest.evidence[0])
    with pytest.raises(RuleError):
        resolve_manifest(manifest)


def test_source_boundary_is_half_open(manifest):
    manifest.evidence[0].out_ms = manifest.segments[0].out_ms
    resolve_manifest(manifest)
    manifest.segments[0].out_ms = manifest.assets[0].duration_ms + 1
    with pytest.raises(RuleError):
        resolve_manifest(manifest)


def test_upload_and_skip_do_not_fulfill_or_change_coverage(bundle, manifest):
    task = CaptureTask.model_validate(bundle["capture_task"])
    submitted = submit_capture(task)
    assert submitted.state == "submitted" and task.state == "open"
    assert submitted.revision == task.revision + 1
    task.user_choice = {"action": "skip"}
    node = StoryNode.model_validate(bundle["nodes"][-1])
    assert evaluate_coverage(node, manifest, True).coverage == "missing"
    with pytest.raises(RuleError):
        submit_capture(submitted)


@pytest.mark.parametrize(
    "mutation", ["task_revision", "storyboard", "no_successful_analysis", "missing_evidence", "fake_coverage"]
)
def test_capture_refuses_stale_unbound_or_forged_verification(bundle, mutation):
    result = run_replay(bundle)
    task = CaptureTask.model_validate(result["capture"]["after_upload"])
    verification = CaptureVerification.model_validate(result["capture"]["verification"])
    manifest = EvidenceManifest.model_validate(result["capture"]["verification_manifest"])
    node = StoryNode.model_validate(bundle["nodes"][-1])
    successful = set(verification.analysis_run_ids)
    if mutation == "task_revision":
        verification.task_revision -= 1
    elif mutation == "storyboard":
        verification.result_storyboard_id = verification.source_storyboard_id
    elif mutation == "no_successful_analysis":
        successful = set()
    elif mutation == "missing_evidence":
        manifest.evidence.pop()
    else:
        verification.report.usable_duration_ms += 1
    with pytest.raises(RuleError):
        verify_capture(task, verification, manifest, node, successful)


@pytest.mark.parametrize("role", ["director", "writer", "visual", "camera", "editor", "sound", "reviewer"])
def test_every_role_has_evidence_and_cannot_authorize_effects(manifest, role):
    envelope = RoleEnvelope(
        role=role,
        status="ok",
        result={"suggestion": "fixture"},
        evidence_refs=[manifest.evidence[0].id],
        uncertainties=[],
        decision_summary="test",
        issues=[],
        next_action="validate",
    )
    assert validate_role(envelope, manifest) == envelope
    for forbidden in ["unlock_clip_keys", "requested_unlock_clip_keys", "submit_version", "shell", "command"]:
        envelope.result = {"nested": [{forbidden: True}]}
        with pytest.raises(RuleError, match="side effects"):
            validate_role(envelope, manifest)
    envelope.result = {}
    envelope.evidence_refs = [uuid4()]
    with pytest.raises(RuleError):
        validate_role(envelope, manifest)
