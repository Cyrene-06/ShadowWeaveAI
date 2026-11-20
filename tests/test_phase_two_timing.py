"""Check frozen condition separation and local packet integrity, not human results."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.phase_two_timing import CATALOG, frozen_trials, packets, write_packets


@pytest.fixture
def replay():
    path = Path(__file__).resolve().parents[1] / "docs/reports/evidence/phase-2-real-media.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_query_has_opposite_conditions_without_leaking_targets(replay):
    registry = json.loads(CATALOG.read_text(encoding="utf-8"))
    trials, clips, _ = frozen_trials(replay, registry)
    first, second = packets(trials)
    orders = [{r["trial_id"]: r for r in p["trials"]} for p in (first, second)]
    for key in orders[0]:
        assert {r[key]["arm"] for r in orders} == {"A", "B"}
        for r in orders:
            card = r[key]
            assert set(card) == {"trial_id", "arm", "query", "candidates"}
            expected = {"clip"} if card["arm"] == "A" else {"clip", "in_ms", "out_ms"}
            assert all(set(c) == expected for c in card["candidates"])
            assert all(c["clip"] in clips.values() for c in card["candidates"])
    assert all(not r["T4"]["candidates"] for r in orders)


@pytest.mark.parametrize("field, value", [("in_ms", -1), ("out_ms", 100_000), ("analysis_run_id", "other")])
def test_wrong_candidate_interval_or_version_cannot_be_frozen(replay, field, value):
    replay["query_records"][0]["b_candidates"][0][field] = value
    with pytest.raises(ValueError, match="frozen analysis"):
        frozen_trials(replay, json.loads(CATALOG.read_text(encoding="utf-8")))


def test_copies_exact_proxy_and_keeps_observer_file_separate(replay, tmp_path):
    case = tmp_path / "case"
    for i, run in enumerate(replay["actual_runs"]):
        latest = run["latest"]
        proxy = case / "materials/derived/project" / latest["analysis_run_id"] / "lease/preview.mp4"
        proxy.parent.mkdir(parents=True)
        data = f"proxy bytes {i}".encode()
        proxy.write_bytes(data)
        latest["result"]["preview_sha256"] = hashlib.sha256(data).hexdigest()
    source = tmp_path / "evidence.json"
    source.write_text(json.dumps(replay), encoding="utf-8")
    session = tmp_path / "session"
    write_packets(source, case, session)
    key = json.loads((session / "observer.json").read_text(encoding="utf-8"))
    assert all(x is None for x in key["targets"].values())
    assert key["query_keys"]["T4"] == "no-answer"
    assert key["replay_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    for packet in ("P1", "P2"):
        page = (session / packet / "index.html").read_text(encoding="utf-8")
        assert all(value not in page for value in ("observer.json", "one-small-step.m4v", "no-answer"))
        for clip, sha in key["clip_sha256"].items():
            assert hashlib.sha256((session / packet / f"{clip}.mp4").read_bytes()).hexdigest() == sha
    with pytest.raises(FileExistsError):
        write_packets(source, case, session)
    proxy.write_bytes(b"mismatch")
    with pytest.raises(ValueError, match="hash-matching proxy"):
        write_packets(source, case, tmp_path / "another-session")
    assert not (tmp_path / "another-session").exists()
