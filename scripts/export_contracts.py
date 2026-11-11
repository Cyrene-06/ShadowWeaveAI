"""Generate shared schemas and expected client mappings from Pydantic. --check never writes."""

import argparse
import copy
import inspect
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

from pydantic import ValidationError
from sw_contracts import models
from sw_api.app import create_app
from sw_api.replay import run_replay

ROOT = Path(__file__).resolve().parents[1]


def artifacts():
    registry = {
        name: cls
        for name, cls in vars(models).items()
        if inspect.isclass(cls) and issubclass(cls, models.Contract) and cls is not models.Contract
    }
    schemas = {name: cls.model_json_schema() for name, cls in registry.items()}
    bundle = json.loads((ROOT / "examples/phase-1/campus.json").read_text(encoding="utf-8"))
    result = run_replay(bundle)
    pid = bundle["manifest"]["project_id"]

    def uid(s):
        return str(uuid5(NAMESPACE_URL, "contract/" + s))

    valid = {
        "Project": {"id": pid, "name": "Campus", "scenario": "campus"},
        "Intent": {
            "id": uid("intent"),
            "project_id": pid,
            "revision": 1,
            "source_text": "校园活动",
            "target_duration_ms": 24000,
            "state": "confirmed",
        },
        "Asset": bundle["manifest"]["assets"][0],
        "Segment": bundle["manifest"]["segments"][0],
        "Evidence": bundle["manifest"]["evidence"][0],
        "EvidenceManifest": bundle["manifest"],
        "StoryNode": bundle["nodes"][0],
        "CoverageReport": result["coverage"][0],
        "CaptureTask": bundle["capture_task"],
        "CaptureVerification": result["capture"]["verification"],
        "Output": {},
        "Clip": bundle["base_edl"]["tracks"][0]["clips"][0],
        "Track": bundle["base_edl"]["tracks"][0],
        "EDL": bundle["base_edl"],
        "ImpactReport": result["impact"],
        "EditDraft": result["draft"],
        "Version": {
            "id": uid("version"),
            "project_id": pid,
            "parent_version_id": None,
            "revision": 1,
            "edl": bundle["base_edl"],
            "content_hash": result["impact"]["base_content_hash"],
        },
        "Job": {"id": uid("job"), "project_id": pid, "state": "queued", "mode": "synchronous_replay"},
        "RoleEnvelope": {
            "role": "director",
            "status": "ok",
            "result": {},
            "evidence_refs": [],
            "uncertainties": [],
            "decision_summary": "fixture only",
            "issues": [],
            "next_action": "validate",
        },
        "ErrorBody": {"code": "INVALID_ARGUMENT", "message": "Invalid input", "retryable": False},
        "ErrorEnvelope": {
            "error": {"code": "INVALID_ARGUMENT", "message": "Invalid input", "retryable": False},
            "request_id": uid("request"),
        },
    }
    cases = []

    def add(name, model, value):
        try:
            normalized = registry[model].model_validate(value).model_dump(mode="json")
            cases.append(
                {"id": name, "model": model, "input": value, "valid": True, "normalized": normalized}
            )
        except ValidationError:
            cases.append({"id": name, "model": model, "input": value, "valid": False})

    for model, value in valid.items():
        add(model + "/valid", model, copy.deepcopy(value))
    changes = [
        ("Project", "bad-uuid", {"id": "not-a-uuid"}),
        ("Project", "missing-name", {"name": None}),
        ("Project", "unknown-scenario", {"scenario": "other"}),
        ("Project", "bool-revision", {"revision": True}),
        ("Segment", "negative", {"in_ms": -1}),
        ("Segment", "zero", {"in_ms": 0, "out_ms": 0}),
        ("Segment", "reversed", {"in_ms": 12, "out_ms": 10}),
        ("Segment", "fraction", {"out_ms": 1.5}),
        ("Segment", "string-ms", {"out_ms": "12000"}),
        ("Segment", "extra-field", {"surprise": True}),
        ("Asset", "video-no-duration", {"duration_ms": None}),
        ("Asset", "image-with-duration", {"media_type": "image"}),
        ("Asset", "image-valid", {"media_type": "image", "duration_ms": None}),
        ("CaptureTask", "missing-reshoot-node", {"node_key": None}),
        ("Output", "mismatched-preset", {"width": 1280, "height": 1080}),
        ("Clip", "invalid-speed-duration", {"speed_num": 2}),
        ("Clip", "invalid-target", {"dst_out_ms": 0}),
        ("StoryNode", "required-not-bool", {"required": 1}),
        ("Job", "unknown-state", {"state": "done"}),
    ]
    for model, name, patch in changes:
        value = copy.deepcopy(valid[model])
        value.update(patch)
        add(model + "/" + name, model, value)
    # Explicit absent vs nullable cases are separate, so clients cannot collapse the distinction.
    value = copy.deepcopy(valid["CaptureTask"])
    del value["node_key"]
    add("CaptureTask/node-absent", "CaptureTask", value)
    value = copy.deepcopy(valid["Version"])
    del value["parent_version_id"]
    add("Version/parent-absent", "Version", value)
    catalog = {
        "schema_version": "1.0",
        "source": "packages/contracts/src/sw_contracts/models.py",
        "validation_layers": [
            "JSON Schema structural validation",
            "documented semantic invariants",
            "project reference and policy validation",
        ],
        "models": schemas,
    }

    def encode(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    app = create_app(replay_enabled=True)
    openapi = app.openapi()
    app.state.engine.dispose()
    return {
        "packages/contracts/schema/catalog.json": encode(catalog),
        "packages/contracts/examples/cases.json": encode({"schema_version": "1.0", "cases": cases}),
        "apps/mobile/assets/contracts.json": encode(catalog),
        "docs/api/openapi.json": encode(openapi),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    for name, content in artifacts().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                mismatches.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if mismatches:
        raise SystemExit("Regenerate contracts: " + ", ".join(mismatches))
    print("Contract artifacts " + ("verified" if args.check else "generated"))


if __name__ == "__main__":
    main()
