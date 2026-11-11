"""Package whitelisted phase-one evidence; never include tokens, traces or media."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "artifacts/phase-one"
DEST = ROOT / "docs/reports/evidence"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    path = DEST / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()


def main():
    # Missing inputs stop packaging; a missing/failed check is not converted to PASS.
    verification = load(RAW / "verification.json")
    replay = load(RAW / "replay.json")
    browser = load(RAW / "browser/results.json")
    environment = load(RAW / "environment.json")
    media = load(RAW / "media/report.json")
    suites = ET.parse(RAW / "python-tests.xml").getroot()
    test_counts = {
        key: sum(int(s.get(key, "0")) for s in suites.iter("testsuite"))
        for key in ("tests", "failures", "errors", "skipped")
    }
    for relative, expected in replay["code"]["source_hashes"].items():
        if sha(ROOT / relative) != expected:
            raise SystemExit(f"Replay is stale for {relative}; run it again before packaging")
    DEST.mkdir(parents=True, exist_ok=True)
    write("replay.json", replay)
    write("media.json", media)
    # Explicit whitelist: environment probe never serializes secret values.
    write("environment.json", {
        key: environment[key]
        for key in ("recorded_at", "platform", "python", "node", "flutter", "devices",
                    "physical_capture", "model", "adb_available", "notes")
    })
    write("verification-summary.json", {
        "recorded_at": verification["recorded_at"],
        "passed": verification["passed"],
        "postgres_configured": verification["postgres_configured"],
        "flutter_included": verification["flutter_included"],
        "python_junit_counts": test_counts,
        "steps": [
            {k: step[k] for k in ("name", "command", "exit_code", "duration_seconds")}
            for step in verification["steps"]
        ],
        "browser": browser["stats"],
        "limitations": [
            "This is a summary of actual local command results, not a remote CI run.",
            "Full stdout/stderr, JUnit and browser results remain in ignored artifacts/phase-one.",
            "No independent human reproduction, physical capture or model evaluation has passed.",
        ],
    })
    optional_probe = RAW / "model-probe.json"
    if optional_probe.exists():
        probe = load(optional_probe)
        if probe.get("code", {}).get("script_sha256") != sha(ROOT / "scripts/model_probe.py"):
            raise SystemExit("Model probe record is stale; run scripts/model_probe.py again")
        write("model-probe.json", probe)
    # All implementation inputs, not a self-referential hash of reports/outputs.
    candidates = git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    source_hashes = {
        f: sha(ROOT / f) for f in sorted(set(candidates))
        if (ROOT / f).is_file() and (
            f.startswith(("services/", "packages/", "apps/", "scripts/", "tests/", "examples/phase-1/", "examples/evaluation/"))
            or f in ("pyproject.toml", "requirements.lock.txt", "alembic.ini", "infra/compose.yaml")
        ) and not f.endswith((".md", ".gitkeep"))
    }
    raw_paths = [
        "verification.json", "python-tests.xml", "replay.json", "environment.json",
        "media/report.json", "browser/results.json",
    ]
    if optional_probe.exists():
        raw_paths.append("model-probe.json")
    packaged_names = ["replay.json", "media.json", "environment.json", "verification-summary.json"]
    if optional_probe.exists():
        packaged_names.append("model-probe.json")
    # There are no browser traces or credentials in this whitelist.
    write("index.json", {
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "kind": "local_advance_engineering_verification",
        "assembly_code": {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))},
        "assembly_source_hashes": source_hashes,
        "assembly_note": "Source hashes identify files at packaging time; command-time provenance remains in replay.json.",
        "raw_artifacts": [
            {"path": "artifacts/phase-one/" + name, "sha256": sha(RAW / name)} for name in raw_paths
        ],
        "packaged_files": [
            {"path": name, "sha256": sha(DEST / name)}
            for name in packaged_names
        ],
        "requirements_sha256": sha(ROOT / "docs/requirements.md"),
        "formal_phase_acceptance": "pending_independent_reproduction",
        "model_called": probe.get("model_called") if optional_probe.exists() else False,
    })
    print(DEST)


if __name__ == "__main__":
    main()
