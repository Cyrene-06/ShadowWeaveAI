"""Generate offline schemas/templates; --check refuses stale preparation artifacts."""

import argparse
import json
from pathlib import Path

from sw_contracts.evaluation import REGISTRY, validate_record

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    folder = ROOT / "examples/evaluation"
    changed = []
    for name, cls in REGISTRY.items():
        for suffix, value in (("schema", cls.model_json_schema()), ("template", cls().model_dump())):
            if suffix == "template":
                validate_record(value)
            path = folder / f"{name}.{suffix}.json"
            content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != content:
                    changed.append(path.relative_to(ROOT).as_posix())
            else:
                folder.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    if changed:
        raise SystemExit("Stale evaluation preparation files: " + ", ".join(changed))
    print("Evaluation templates and schemas verified" if args.check else folder)


if __name__ == "__main__":
    main()
