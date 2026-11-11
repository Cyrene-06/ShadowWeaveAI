from uuid import uuid4

import pytest
from pydantic import ValidationError
from sw_contracts import EDL, digest
from sw_contracts.validation import RuleError
from sw_media.policy import (
    predict_impact,
    validate_edit,
    content_hash,
    make_draft,
    confirm_contract,
    dependency_graph,
)


def test_impact_report_exposes_propagation_path_and_static_risk_budget(base):
    report = predict_impact(base, ["opening"], approved=["opening"])

    assert report.propagation_paths["opening"] == ["opening"]
    assert report.propagation_paths["opening-title"] == ["opening", "opening-title"]
    assert report.risk_budget.affected_clip_count == 2
    assert report.risk_budget.affected_ratio == pytest.approx(2 / report.risk_budget.total_clip_count)
    assert report.risk_budget.severity == "high"
    assert report.risk_budget.unapproved_affected_keys == ("opening-title",)
    assert "predicted_impact_exceeds_approved_scope" in report.risk_budget.reasons


def test_locked_change_is_preflighted_as_blocked_risk(base):
    report = predict_impact(base, ["interview"], approved=["interview"])

    assert "interview" in report.risk_budget.unapproved_affected_keys or not report.risk_budget.unapproved_affected_keys
    assert report.risk_budget.locked_conflict_count == len(report.lock_conflicts)
    assert report.risk_budget.locked_conflict_count > 0
    assert report.risk_budget.severity == "blocked"
    assert "locked_content_in_predicted_impact" in report.risk_budget.reasons


def test_direction_and_frozen_approval(base):
    report = predict_impact(base, ["opening"], approved=["opening"])
    assert set(report.predicted_affected_keys) == {"opening", "opening-title"}
    assert "depends_on:opening" in report.causes["opening-title"]
    assert set(predict_impact(base, ["opening-title"]).predicted_affected_keys) == {"opening-title"}
    with pytest.raises(ValidationError):
        report.approved_affected_keys = ("opening", "ending")
    assert isinstance(report.approved_affected_keys, tuple)


@pytest.mark.parametrize(
    "name",
    [
        "legal",
        "locked_change",
        "locked_delete",
        "locked_rekey",
        "locked_move",
        "outside_update",
        "outside_add",
        "outside_delete",
        "dependency_change",
        "cycle",
    ],
)
def test_candidates_enforce_lock_scope_and_cycle(bundle, base, manifest, name):
    old = digest(base)
    impact = predict_impact(base, ["opening"], approved=["opening"])
    candidate = EDL.model_validate(bundle["candidates"][name])
    if name == "cycle":
        with pytest.raises(RuleError, match="cycle"):
            validate_edit(base, candidate, impact, manifest)
    else:
        report = validate_edit(base, candidate, impact, manifest)
        assert (not report["hard_errors"]) == bundle["expected"]["edits"][name]
        if name.startswith("locked"):
            assert "LOCKED_CONTENT_CHANGED" in report["hard_errors"]
        elif name != "legal":
            assert "SCOPE_APPROVAL_REQUIRED" in report["hard_errors"]
    assert digest(base) == old


def test_locked_dependency_and_track_metadata_are_changes(base, manifest):
    impact = predict_impact(base, ["interview"], approved=["interview"])
    candidate = base.model_copy(deep=True)
    candidate.tracks[0].clips[2].dependencies = ["process"]
    assert "LOCKED_CONTENT_CHANGED" in validate_edit(base, candidate, impact, manifest)["hard_errors"]
    candidate = base.model_copy(deep=True)
    candidate.tracks[0].position = 2
    assert "LOCKED_CONTENT_CHANGED" in validate_edit(base, candidate, impact, manifest)["hard_errors"]


def test_explicit_unlock_requires_new_reviewed_draft(bundle, base, manifest):
    candidate = EDL.model_validate(bundle["candidates"]["locked_change"])
    impact = predict_impact(base, ["opening", "interview"], approved=["opening", "interview"])
    with pytest.raises(RuleError):
        make_draft(manifest.project_id, uuid4(), 0, base, candidate, impact, manifest)
    draft = make_draft(manifest.project_id, uuid4(), 0, base, candidate, impact, manifest, ["interview"])
    with pytest.raises(RuleError, match="unlock"):
        confirm_contract(draft, 0, draft.payload_hash, [])
    assert confirm_contract(draft, 0, draft.payload_hash, ["interview"])["version_published"] is False


@pytest.mark.parametrize(
    "field",
    [
        "base_revision",
        "base_content_hash",
        "candidate_edl",
        "impact_report",
        "diff",
        "validation_report",
        "requested_unlock_clip_keys",
    ],
)
def test_hash_binds_entire_reviewed_payload(bundle, base, manifest, field):
    impact = predict_impact(base, ["opening"], approved=["opening"])
    draft = make_draft(
        manifest.project_id,
        uuid4(),
        0,
        base,
        EDL.model_validate(bundle["candidates"]["legal"]),
        impact,
        manifest,
    )
    bad = draft.model_copy(deep=True)
    if field == "base_revision":
        bad.base_revision = 1
    elif field == "base_content_hash":
        bad.base_content_hash = "f" * 64
    elif field == "candidate_edl":
        bad.candidate_edl.tracks[0].clips[0].config = {"x": 1}
    elif field == "impact_report":
        bad.impact_report = bad.impact_report.model_copy(update={"scope_approval_ref": uuid4()})
    elif field == "diff":
        bad.diff["added"] = ["unreviewed"]
    elif field == "validation_report":
        bad.validation_report["rules_version"] = "other"
    else:
        bad.requested_unlock_clip_keys = ["interview"]
    with pytest.raises(RuleError):
        confirm_contract(bad, bad.base_revision, draft.payload_hash, bad.requested_unlock_clip_keys)
    with pytest.raises(RuleError, match="head changed"):
        confirm_contract(draft, 1, draft.payload_hash, [])


def test_scope_cannot_expand_after_candidate_without_new_approval(bundle, base, manifest):
    first = predict_impact(base, ["opening"], approved=["opening"])
    candidate = EDL.model_validate(bundle["candidates"]["outside_update"])
    assert "SCOPE_APPROVAL_REQUIRED" in validate_edit(base, candidate, first, manifest)["hard_errors"]
    second = predict_impact(base, ["opening", "process"], approved=["opening", "process"])
    assert second.scope_approval_ref != first.scope_approval_ref
    assert not validate_edit(base, candidate, second, manifest)["hard_errors"]


def test_hash_normalizes_order_but_detects_track_and_dependency(base):
    other = base.model_copy(deep=True)
    other.tracks.reverse()
    other.tracks[-1].clips.reverse()
    assert content_hash(base) == content_hash(other)
    other.tracks[-1].position = 3
    assert content_hash(base) != content_hash(other)


def test_impact_budget_and_dangling_dependencies(base):
    with pytest.raises(RuleError, match="full_replan"):
        predict_impact(base, ["opening"], max_nodes=1)
    base.tracks[1].clips[0].dependencies = ["does-not-exist"]
    with pytest.raises(RuleError):
        dependency_graph(base)


def test_draft_cannot_bind_foreign_project(bundle, base, manifest):
    impact = predict_impact(base, ["opening"], approved=["opening"])
    with pytest.raises(RuleError, match="different projects"):
        make_draft(
            uuid4(), uuid4(), 0, base, EDL.model_validate(bundle["candidates"]["legal"]), impact, manifest
        )
