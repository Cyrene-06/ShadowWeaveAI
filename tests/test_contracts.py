import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError
from sw_contracts import models

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "packages/contracts/examples/cases.json").read_text(encoding="utf-8"))["cases"]
SCHEMAS = json.loads((ROOT / "packages/contracts/schema/catalog.json").read_text(encoding="utf-8"))["models"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_shared_contract_cases(case):
    cls = getattr(models, case["model"])
    if case["valid"]:
        parsed = cls.model_validate(case["input"])
        assert parsed.model_dump(mode="json") == case["normalized"]
        jsonschema.Draft202012Validator(
            SCHEMAS[case["model"]], format_checker=jsonschema.FormatChecker()
        ).validate(case["input"])
    else:
        with pytest.raises(ValidationError):
            cls.model_validate(case["input"])
