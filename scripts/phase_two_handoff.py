"""Feed actual Web review exports into the Phase 1 coverage engine without changing judgments."""

import argparse
import json
import re
from pathlib import Path

from pydantic import ValidationError

from sw_ai.coverage import evaluate_coverage
from sw_contracts import EvidenceManifest, StoryNode, digest
from sw_contracts.validation import resolve_manifest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples/phase-2/nasa-demo.json"


def handoff(manifests, registry, *, search_complete=False):
    if not manifests:
        raise ValueError("Provide at least one Web review export")
    pid = manifests[0].project_id
    requirements = [q["id"] for q in registry["queries"] if q["asset"]]
    requirement_keys = set(requirements)
    source_hashes = {a["sha256"] for a in registry["assets"]}
    assets, segments, evidence = {}, {}, {}
    versions, source_assets, judgments, inputs = {}, {}, {}, set()

    def remember(target, row):
        if target.setdefault(row.id, row) != row:
            raise ValueError("Conflicting definitions for the same evidence, asset or segment ID")

    for manifest in manifests:
        if manifest.project_id != pid:
            raise ValueError("All review exports must belong to the same project")
        resolve_manifest(manifest)
        if not re.fullmatch(r"media-v1-[a-f0-9]{64}", manifest.dataset_version) or not manifest.evidence:
            raise ValueError("Expected a non-empty phase-two media review export")
        inputs.add(digest(manifest.model_dump(mode="json")))
        for asset in manifest.assets:
            if asset.media_type != "video" or asset.sha256 not in source_hashes:
                raise ValueError("Source SHA-256 not registered for the NASA Phase 2 exercise")
            if source_assets.setdefault(asset.sha256, asset.id) != asset.id:
                raise ValueError("Multiple asset IDs for the same registered source SHA-256")
            remember(assets, asset)
        for segment in manifest.segments:
            if versions.setdefault(segment.asset_id, segment.analysis_run_id) != segment.analysis_run_id:
                raise ValueError("Export again from a single analysis version per source asset")
            remember(segments, segment)
        for row in manifest.evidence:
            if row.method != "human_annotation" or not set(row.requirement_keys) <= requirement_keys:
                raise ValueError("Expected manual review of the registered story requirements")
            for key in row.requirement_keys:
                binding = (row.segment_id, row.in_ms, row.out_ms, key)
                judgment = (row.semantic_support, row.quality_usable)
                if judgments.setdefault(binding, judgment) != judgment:
                    raise ValueError("Conflicting judgments for the same fact and source interval")
            remember(evidence, row)

    inputs = sorted(inputs)
    merged = EvidenceManifest(
        project_id=pid,
        dataset_version="p2-review-" + digest(inputs),
        assets=[assets[k] for k in sorted(assets)],
        segments=[segments[k] for k in sorted(segments)],
        evidence=[evidence[k] for k in sorted(evidence)],
    )
    node = StoryNode(
        project_id=pid,
        node_key="archival-quotes",
        goal="Ground the sample speech facts",
        requirements=requirements,
        minimum_duration_ms=4000,
    )
    report = evaluate_coverage(node, merged, search_complete=search_complete)
    return {
        "dataset_version": registry["version"],
        "input_manifest_hashes": inputs,
        "source_sha256": sorted({a.sha256 for a in assets.values()}),
        "coverage_result": report.model_dump(mode="json"),
        "review_provenance": "Provided by the operator; this tool does not verify reviewer identity or independence",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="+", type=Path, help="JSON exported by the material workspace")
    parser.add_argument("--output", required=True, type=Path, help="New file for the coverage receipt")
    parser.add_argument("--search-complete", action="store_true", help="Observer confirms the full candidate review")
    args = parser.parse_args()
    try:
        registry = json.loads(CATALOG.read_text(encoding="utf-8"))
        manifests = [EvidenceManifest.model_validate_json(p.read_bytes()) for p in args.manifest]
        report = handoff(manifests, registry, search_complete=args.search_complete)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    except ValidationError:
        # Do not print manifest contents.
        parser.exit(1, "Invalid EvidenceManifest schema\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Handoff failed: {exc}\n")
    print(f"Coverage: {report['coverage_result']['coverage']}; receipt: {args.output}")


if __name__ == "__main__":
    main()
