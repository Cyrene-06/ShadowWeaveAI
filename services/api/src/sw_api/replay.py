"""Run phase-one fixtures through real rules, never substitute prerecorded output."""

import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid5

from pydantic import ValidationError
from sw_contracts import EvidenceManifest, StoryNode, CaptureTask, CaptureVerification, Evidence, EDL, digest
from sw_contracts.validation import RuleError
from sw_ai.coverage import evaluate_coverage, submit_capture, verify_capture
from sw_media.policy import predict_impact, validate_edit, make_draft, confirm_contract

ROOT = Path(__file__).resolve().parents[4]


def run_replay(bundle):
    manifest = EvidenceManifest.model_validate(bundle["manifest"])
    nodes = [StoryNode.model_validate(n) for n in bundle["nodes"]]
    reports = {node.node_key: evaluate_coverage(node, manifest, True) for node in nodes}
    ending = next(node for node in nodes if node.node_key == "ending")
    uncertain = evaluate_coverage(ending, manifest, False)
    task = CaptureTask.model_validate(bundle["capture_task"])
    submitted = submit_capture(task)
    # Add a new human annotation to the previously unobserved ending source; this is not real analysis.
    segment = manifest.segments[3]
    fresh = Evidence(
        id=uuid5(manifest.project_id, "replay/farewell-evidence"),
        project_id=manifest.project_id,
        asset_id=segment.asset_id,
        segment_id=segment.id,
        analysis_run_id=segment.analysis_run_id,
        in_ms=0,
        out_ms=6000,
        method="human_annotation",
        semantic_support="supported",
        quality_usable=True,
        requirement_keys=["farewell"],
    )
    new_manifest = manifest.model_copy(deep=True)
    new_manifest.evidence.append(fresh)
    after = evaluate_coverage(ending, new_manifest, True)
    verification = CaptureVerification(
        task_id=task.id,
        task_revision=submitted.revision,
        source_storyboard_id=task.source_storyboard_id,
        source_storyboard_revision=task.source_storyboard_revision,
        result_storyboard_id=uuid5(manifest.project_id, "storyboard/after-farewell"),
        result_storyboard_revision=2,
        report_ref=uuid5(manifest.project_id, "report/farewell"),
        job_id=uuid5(manifest.project_id, "job/verify"),
        analysis_run_ids=[segment.analysis_run_id],
        report=after,
    )
    fulfilled = verify_capture(submitted, verification, new_manifest, ending, {segment.analysis_run_id})
    uncertain_manifest = new_manifest.model_copy(deep=True)
    for evidence in uncertain_manifest.evidence:
        if "farewell" in evidence.requirement_keys:
            evidence.semantic_support = "unknown"
    uncertain_report = evaluate_coverage(ending, uncertain_manifest, True)
    uncertain_verification = verification.model_copy(deep=True, update={"report": uncertain_report})
    try:
        verify_capture(submitted, uncertain_verification, uncertain_manifest, ending, {segment.analysis_run_id})
        uncertain_capture_blocked = False
    except RuleError:
        uncertain_capture_blocked = True
    base = EDL.model_validate(bundle["base_edl"])
    # Scope is established before inspecting or parsing any candidate.
    impact = predict_impact(
        base,
        ["opening"],
        approved=["opening"],
        scope_approval_ref=uuid5(manifest.project_id, "approved-opening-v1"),
    )
    edits = {}
    for name, raw in bundle["candidates"].items():
        try:
            candidate = EDL.model_validate(raw)
            report = validate_edit(base, candidate, impact, manifest)
            edits[name] = {"accepted": not report["hard_errors"], "validation": report}
        except (RuleError, ValidationError) as exc:
            edits[name] = {
                "accepted": False,
                "error_code": getattr(exc, "code", "INVALID_ARGUMENT"),
                "message": str(exc),
            }
    draft = make_draft(
        manifest.project_id,
        bundle["base_version_id"],
        bundle["base_revision"],
        base,
        EDL.model_validate(bundle["candidates"]["legal"]),
        impact,
        manifest,
    )
    confirmed = confirm_contract(draft, bundle["base_revision"], draft.payload_hash, [])
    expected = bundle["expected"]
    checks = {
        **{
            "coverage/" + key: report.coverage == expected["coverage"][key] for key, report in reports.items()
        },
        "incomplete_search": uncertain.coverage == expected["incomplete_ending"],
        "upload_is_not_fulfillment": submitted.state == expected["submitted"],
        "verification_gate": fulfilled.state == expected["verified"],
        **{"edit/" + key: report["accepted"] == expected["edits"][key] for key, report in edits.items()},
        "contract_only": confirmed["valid"] and not confirmed["version_published"],
        "coverage_explanation": all(
            row.requirement_key in report.checked_requirements
            for report in reports.values() for row in report.requirement_results
        ),
        "covered_nodes_have_sufficient_selection": all(
            report.selection_complete
            and report.usable_duration_ms >= report.minimum_duration_ms
            for report in reports.values() if report.coverage == "covered"
        ),
        "uncertainty_blocks_capture_fulfillment": (
            uncertain_report.coverage == "uncertain"
            and bool(uncertain_report.uncertainty_reasons)
            and uncertain_capture_blocked
        ),
        "impact_preflight_paths_and_risk": (
            impact.propagation_paths.get("opening-title") == ["opening", "opening-title"]
            and impact.risk_budget.affected_clip_count == len(impact.predicted_affected_keys)
        ),
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "unavailable", None
    source_files = [
        ROOT / "packages" / package / "src" / module / file
        for package, module, file in [
            ("contracts", "sw_contracts", "models.py"),
            ("contracts", "sw_contracts", "validation.py"),
            ("ai", "sw_ai", "coverage.py"),
            ("media", "sw_media", "policy.py"),
        ]
    ] + [Path(__file__)]
    return {
        "schema_version": "1.0",
        "mode": "fixed_input",
        "model_called": False,
        "dataset_version": bundle["dataset_version"],
        "input_hash": digest(bundle),
        "input": bundle,
        "code": {
            "commit": commit,
            "dirty": dirty,
            "source_hashes": {
                str(p.relative_to(ROOT)).replace("\\", "/"): __import__("hashlib")
                .sha256(p.read_bytes())
                .hexdigest()
                for p in source_files
            },
        },
        "rules": {"coverage": "coverage-2", "editing": "policy-2", "impact": "impact-2"},
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(checks.values()),
        "checks": checks,
        "coverage": [report.model_dump(mode="json") for report in reports.values()],
        "incomplete_search": uncertain.model_dump(mode="json"),
        "capture": {
            "initial": task.model_dump(mode="json"),
            "after_upload": submitted.model_dump(mode="json"),
            "after_verification": fulfilled.model_dump(mode="json"),
            "verification": verification.model_dump(mode="json"),
            "verification_manifest": new_manifest.model_dump(mode="json"),
            "uncertainty_report": uncertain_report.model_dump(mode="json"),
            "uncertainty_blocks_fulfillment": uncertain_capture_blocked,
        },
        "impact": impact.model_dump(mode="json"),
        "edits": edits,
        "draft": draft.model_dump(mode="json"),
        "confirmation": confirmed,
        "limitations": [
            "Human-annotated synthetic metadata; no actual media understanding or quality measurement.",
            "Evidence selection is deterministic greedy set-cover plus reverse pruning, not a globally minimum-cardinality solver.",
            "Impact risk is a static pre-candidate blast-radius heuristic, not a production risk or cost estimate.",
            "No production version publication or async workflow.",
        ],
    }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "examples/phase-1/campus.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/phase-one/replay.json")
    args = parser.parse_args()
    result = run_replay(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({"passed": result["passed"], "checks": len(result["checks"]), "output": str(args.output)})
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
