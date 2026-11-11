import json
from pathlib import Path

import pytest
from sw_contracts import EvidenceManifest, EDL

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle():
    return json.loads((ROOT / "examples/phase-1/campus.json").read_text(encoding="utf-8"))


@pytest.fixture
def manifest(bundle):
    return EvidenceManifest.model_validate(bundle["manifest"])


@pytest.fixture
def base(bundle):
    return EDL.model_validate(bundle["base_edl"])
