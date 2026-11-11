"""Record actual tool/device availability without reading or echoing credentials."""

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, timeout=45):
    try:
        result = subprocess.run(
            args, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}


def main():
    flutter = os.environ.get("FLUTTER_PATH") or shutil.which("flutter")
    if not flutter:
        local = ROOT / ".cache/flutter/bin/flutter.bat"
        if local.exists():
            flutter = str(local)
    devices = (
        run([flutter, "devices", "--machine"])
        if flutter
        else {"status": "unavailable", "reason": "flutter_not_found"}
    )
    physical = []
    try:
        physical = [
            d
            for d in json.loads(devices.get("stdout", "[]"))
            if d.get("targetPlatform", "").startswith(("android", "ios")) and not d.get("emulator", True)
        ]
    except json.JSONDecodeError:
        pass
    model_ready = all(os.environ.get(name) for name in ("MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY"))
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "node": run([shutil.which("node") or "node", "--version"]),
        "flutter": run([flutter, "--version", "--machine"]) if flutter else {"status": "unavailable"},
        "devices": devices,
        "physical_capture": {
            "status": "not_run" if physical else "blocked",
            "physical_devices": physical,
            "reason": "Capture on an authorized physical device is still required"
            if physical
            else "No Android/iOS physical device discovered; Android SDK/adb unavailable on this host",
            "owner": "A",
            "review_date": "2026-11-19",
        },
        "model": {
            "status": "not_run" if model_ready else "not_configured",
            "model_called": False,
            "credentials_present": bool(os.environ.get("MODEL_API_KEY")),
            "reason": "Provider-specific connectivity, structured result and usage/cost probe still required"
            if model_ready
            else "MODEL_BASE_URL / MODEL_NAME / MODEL_API_KEY are not all configured",
            "usage": None,
            "cost": None,
            "owner": "C",
            "review_date": "2026-11-19",
        },
        "adb_available": bool(shutil.which("adb")),
        "notes": [
            "No secret values are included",
            "Flutter Web is not a physical capture result",
            "No creative quality or model accuracy claim is supported by this probe",
        ],
    }
    folder = ROOT / "artifacts/phase-one"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "environment.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)
    print(
        json.dumps(
            {"physical_capture": record["physical_capture"]["status"], "model": record["model"]["status"]}
        )
    )


if __name__ == "__main__":
    main()
