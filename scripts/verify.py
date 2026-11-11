"""Run real checks and persist exit codes/output; a missing check is never a pass."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flutter", action="store_true")
    args = parser.parse_args()
    py = sys.executable
    npm = shutil.which("npm") or "npm"
    steps = [
        ("ruff", [py, "-m", "ruff", "check", "."], ROOT),
        ("contracts", [py, "scripts/export_contracts.py", "--check"], ROOT),
        ("evaluation_templates", [py, "scripts/prepare_evaluation.py", "--check"], ROOT),
        ("python", [py, "-m", "pytest", "-q", "--junitxml=artifacts/phase-one/python-tests.xml"], ROOT),
        ("replay", [py, "-m", "sw_api.replay"], ROOT),
        ("media", [py, "scripts/media_probe.py"], ROOT),
        ("web_tests", [npm, "test"], ROOT / "apps/web"),
        ("web_build", [npm, "run", "build"], ROOT / "apps/web"),
    ]
    if args.flutter:
        flutter = os.environ.get("FLUTTER_PATH") or shutil.which("flutter") or "flutter"
        mobile = Path(os.environ.get("FLUTTER_WORKDIR", ROOT / "apps/mobile"))
        steps.extend(
            [
                ("flutter_analyze", [flutter, "analyze"], mobile),
                ("flutter_tests", [flutter, "test", "--reporter", "expanded"], mobile),
                (
                    "flutter_build",
                    [
                        flutter,
                        "build",
                        "web",
                        "--release",
                        "--dart-define=API_BASE_URL=http://127.0.0.1:8000/api/v1",
                    ],
                    mobile,
                ),
            ]
        )
    results = []
    for name, command, cwd in steps:
        start = time.monotonic()
        print("RUN", name, flush=True)
        try:
            run = subprocess.run(
                command,
                cwd=cwd,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            result = {
                "name": name,
                "command": command,
                "cwd": str(cwd),
                "exit_code": run.returncode,
                "stdout": run.stdout,
                "stderr": run.stderr,
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"name": name, "command": command, "exit_code": -1, "error": str(exc)}
        result["duration_seconds"] = round(time.monotonic() - start, 3)
        results.append(result)
        print(name, "PASS" if result["exit_code"] == 0 else "FAIL", flush=True)
        if result["exit_code"]:
            print(result.get("stdout", ""), result.get("stderr", result.get("error", "")), flush=True)
    output = ROOT / "artifacts/phase-one/verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(r["exit_code"] == 0 for r in results),
        "postgres_configured": bool(os.environ.get("TEST_DATABASE_URL")),
        "flutter_included": args.flutter,
        "steps": results,
    }
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    raise SystemExit(0 if record["passed"] else 1)


if __name__ == "__main__":
    main()
