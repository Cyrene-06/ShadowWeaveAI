"""Validate preparation templates or ready offline records without making model calls."""

import argparse
import json
from pathlib import Path

from sw_contracts.evaluation import DatasetManifest, validate_record


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records", nargs="+")
    parser.add_argument("--manifest")
    parser.add_argument("--ready", action="store_true")
    args = parser.parse_args()
    try:
        manifest = validate_record(load(args.manifest), require_ready=True) if args.manifest else None
        if manifest is not None and not isinstance(manifest, DatasetManifest):
            raise ValueError("--manifest must be a dataset_manifest")
        for path in args.records:
            record = validate_record(load(path), manifest, args.ready)
            print(
                json.dumps(
                    {
                        "path": path,
                        "record_stage": record.record_stage,
                        "result": "valid_structure_and_consistency",
                        "execution_or_human_review_proved": False,
                    },
                    ensure_ascii=False,
                )
            )
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
