"""Exercise the acceptance adapter with synthetic reviews, never human sign-offs."""

import json
from uuid import uuid4

import pytest

from scripts.phase_two_handoff import CATALOG, handoff
from sw_contracts import Asset, Evidence, EvidenceManifest, Segment


@pytest.fixture
def review_set():
    registry = json.loads(CATALOG.read_text(encoding="utf-8"))
    project = uuid4()
    assets = {
        item["name"]: Asset(id=uuid4(), project_id=project, media_type="video", duration_ms=60_000,
                            sha256=item["sha256"])
        for item in registry["assets"]
    }
    versions = {a.id: uuid4() for a in assets.values()}
    manifests = []
    for query in registry["queries"]:
        if not query["asset"]:
            continue
        a = assets[query["asset"]]
        start = query["anchor_ms"] - 3000
        s = Segment(id=uuid4(), project_id=project, asset_id=a.id, analysis_run_id=versions[a.id],
                    in_ms=start, out_ms=start + 5000)
        e = Evidence(id=uuid4(), project_id=project, asset_id=a.id, segment_id=s.id,
                     analysis_run_id=s.analysis_run_id, in_ms=s.in_ms, out_ms=s.out_ms,
                     method="human_annotation", semantic_support="supported", quality_usable=True,
                     requirement_keys=[query["id"]])
        manifests.append(EvidenceManifest(project_id=project, dataset_version="media-v1-" + "a" * 64,
                                          assets=[a], segments=[s], evidence=[e]))
    return registry, manifests


def test_multiple_exports_and_input_hashes_are_order_stable(review_set):
    registry, exports = review_set
    receipt = handoff(exports, registry, search_complete=True)
    assert receipt == handoff([*reversed(exports), exports[0]], registry, search_complete=True)
    assert receipt["coverage_result"]["coverage"] == "covered"
    assert len(receipt["input_manifest_hashes"]) == 3
    assert len(receipt["source_sha256"]) == 2
    assert handoff(exports, registry)["coverage_result"]["coverage"] == "uncertain"


def test_missing_unknown_and_unusable_are_not_promoted(review_set):
    registry, exports = review_set
    exports[0].evidence[0].semantic_support = "unknown"
    exports[1].evidence[0].quality_usable = False
    receipt = handoff(exports[:2], registry, search_complete=True)
    states = {row["requirement_key"]: row["state"] for row in receipt["coverage_result"]["requirement_results"]}
    assert states == {"first-step": "uncertain", "ladder": "insufficient", "buzz-view": "missing"}


@pytest.mark.parametrize("change, message", [
    ("project", "same project"),
    ("hash", "not registered"),
    ("version", "single analysis version"),
    ("method", "manual review"),
    ("query", "registered story requirements"),
    ("judgment", "Conflicting judgments"),
])
def test_reject_unsafe_merge(review_set, change, message):
    registry, exports = review_set
    review = exports[0].model_copy(deep=True)
    e, s, a = review.evidence[0], review.segments[0], review.assets[0]
    if change == "project":
        review.project_id = e.project_id = s.project_id = a.project_id = uuid4()
    if change == "hash":
        a.sha256 = "b" * 64
    if change == "version":
        s.analysis_run_id = e.analysis_run_id = uuid4()
    if change == "method":
        e.method = "tool_analysis"
    if change == "query":
        e.requirement_keys = ["no-answer"]
    if change == "judgment":
        e.id = uuid4()
        e.semantic_support = "unsupported"
    with pytest.raises(ValueError, match=message):
        handoff([*exports, review], registry)
