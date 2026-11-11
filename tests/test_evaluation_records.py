"""Protect evaluation preparation from leakage and invented completed results."""

import copy
import json
from pathlib import Path

import pytest
from sw_contracts.evaluation import DatasetManifest, validate_record

ROOT = Path(__file__).resolve().parents[1]


def manifest_payload():
    return {
        "record_type": "dataset_manifest",
        "record_stage": "ready",
        "dataset_version": "unit-1",
        "assets": [
            {
                "asset_id": "asset-one",
                "source_uri": "controlled/one.mp4",
                "sha256": "a" * 64,
                "media_type": "video",
                "duration_ms": 1000,
                "source_kind": "real_capture",
                "event_id": "event-one",
                "duplicate_group": "group-one",
                "rights": {
                    "status": "approved",
                    "permission_ref": "unit-fixture-permission",
                    "allowed_uses": ["development", "evaluation"],
                },
            }
        ],
        "tasks": [
            {
                "task_id": "task-one",
                "scenario": "campus",
                "split": "development",
                "event_id": "event-one",
                "asset_ids": ["asset-one"],
                "intent_ref": "unit-intent",
            }
        ],
    }


def annotation_payload():
    return {
        "record_type": "annotation",
        "record_stage": "ready",
        "dataset_version": "unit-1",
        "task_id": "task-one",
        "annotator_id": "unit-annotator",
        "nodes": [
            {
                "node_key": "opening",
                "requirement_keys": ["place"],
                "coverage": "covered",
                "search_complete": True,
                "gap_types": [],
                "rationale": "Unit fixture only",
                "evidence": [
                    {
                        "asset_id": "asset-one",
                        "in_ms": 0,
                        "out_ms": 1000,
                        "requirement_keys": ["place"],
                        "semantic_support": "supported",
                        "quality_usable": True,
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize("kind", ["dataset_manifest", "annotation", "evaluation_run"])
def test_templates_are_unexecuted_and_cannot_pass_ready_gate(kind):
    payload = json.loads((ROOT / f"examples/evaluation/{kind}.template.json").read_text(encoding="utf-8"))
    assert validate_record(payload).record_stage == "template"
    with pytest.raises(ValueError, match="unfilled template"):
        validate_record(payload, require_ready=True)


@pytest.mark.parametrize("collision", ["sha", "event", "duplicate", "lineage"])
def test_cross_split_leakage_is_rejected(collision):
    payload = manifest_payload()
    other = copy.deepcopy(payload["assets"][0])
    other.update(asset_id="asset-two", sha256="b" * 64, event_id="event-two", duplicate_group="group-two")
    if collision == "sha":
        other["sha256"] = "a" * 64
    elif collision == "event":
        other["event_id"] = "event-one"
    elif collision == "duplicate":
        other["duplicate_group"] = "group-one"
    else:
        other["parent_asset_id"] = "asset-one"
    payload["assets"].append(other)
    payload["tasks"].append(
        {
            "task_id": "task-two",
            "scenario": "travel",
            "split": "frozen_test",
            "event_id": other["event_id"],
            "asset_ids": ["asset-two"],
            "intent_ref": "intent-two",
        }
    )
    with pytest.raises(ValueError, match="cross-split leakage"):
        validate_record(payload, require_ready=True)


@pytest.mark.parametrize("mutation", ["permission", "generated", "unknown_asset", "lineage_cycle"])
def test_unlicensed_generated_or_unbound_frozen_inputs_are_rejected(mutation):
    payload = manifest_payload()
    payload["tasks"][0]["split"] = "frozen_test"
    if mutation == "permission":
        payload["assets"][0]["rights"]["permission_ref"] = None
    elif mutation == "generated":
        payload["assets"][0]["source_kind"] = "generated_probe"
    elif mutation == "unknown_asset":
        payload["tasks"][0]["asset_ids"] = ["unknown"]
    else:
        payload["assets"][0]["parent_asset_id"] = "asset-one"
    with pytest.raises(ValueError):
        validate_record(payload, require_ready=True)


@pytest.mark.parametrize(
    "mutation", ["outside", "unknown_asset", "unfinished_missing", "false_covered", "single_review"]
)
def test_annotation_requires_source_bounds_and_consistent_human_labels(mutation):
    payload = annotation_payload()
    node = payload["nodes"][0]
    if mutation == "outside":
        node["evidence"][0]["out_ms"] = 1001
    elif mutation == "unknown_asset":
        node["evidence"][0]["asset_id"] = "unknown"
    elif mutation == "unfinished_missing":
        node.update(coverage="missing", search_complete=False, evidence=[])
    elif mutation == "false_covered":
        node["evidence"][0]["quality_usable"] = False
    else:
        payload.update(
            annotation_stage="adjudicated", adjudicator_id="judge", independent_source_refs=["one"]
        )
    with pytest.raises(ValueError):
        validate_record(payload, validate_record(manifest_payload()), True)


def run_payload():
    return {
        "record_type": "evaluation_run",
        "record_stage": "ready",
        "dataset_version": "unit-1",
        "task_id": "task-one",
        "scenario": "campus",
        "condition": "A",
        "code_commit": "a" * 40,
        "graph_version": "not_applicable",
        "prompt_version": "not_applicable",
        "hardware": {"fixture": True},
        "budget": {"wall_seconds": 60},
        "model_called": False,
        "timing_boundaries": {"received_at": "2026-11-11T00:00:00Z", "finished_at": "2026-11-11T00:00:02Z"},
        "timings_seconds": {"user_wait": 2.0},
        "input_manifest_hash": "b" * 64,
        "status": "failed",
        "failure_code": "UNIT_FAILURE",
        "raw_artifact_refs": ["unit-error.json"],
    }


def test_failed_runs_remain_valid_records_for_denominators():
    manifest = validate_record(manifest_payload())
    assert isinstance(manifest, DatasetManifest)
    assert validate_record(annotation_payload(), manifest, True).nodes[0].coverage == "covered"
    run = validate_record(run_payload(), manifest, True)
    assert run.status == "failed" and run.failure_code == "UNIT_FAILURE"


@pytest.mark.parametrize(
    "mutation", ["no_failure", "invented_usage", "negative_time", "backwards", "naive_time", "not_run"]
)
def test_run_cannot_invent_usage_hide_failure_or_rewrite_timing(mutation):
    payload = run_payload()
    if mutation == "no_failure":
        payload["failure_code"] = None
    elif mutation == "invented_usage":
        payload["usage"] = {"tokens": 100}
    elif mutation == "negative_time":
        payload["timings_seconds"]["user_wait"] = -1.0
    elif mutation == "backwards":
        payload["timing_boundaries"]["finished_at"] = "2026-11-10T00:00:00Z"
    elif mutation == "naive_time":
        payload["timing_boundaries"]["received_at"] = "2026-11-11T00:00:00"
    else:
        payload["status"] = "not_run"
    with pytest.raises(ValueError):
        validate_record(payload, validate_record(manifest_payload()), True)
