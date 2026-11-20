"""Check frozen condition separation and local packet integrity, not human results."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.phase_two_score import score
from scripts.phase_two_timing import CATALOG, LIMIT_MS, frozen_trials, observer_plan, packets, write_packets


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


@pytest.fixture
def study(replay):
    raw = json.dumps(replay).encode()
    registry = json.loads(CATALOG.read_bytes())
    # Unit-test intervals derived from candidates, not independent annotation or trial data.
    targets = {}
    for row in replay["query_records"]:
        key = row["query_id"]
        if row["answer_asset"]:
            candidate = row["b_candidates"][0]
            targets[key] = {"kind": "interval", "asset": candidate["name"],
                            "in_ms": candidate["in_ms"], "out_ms": candidate["out_ms"], "tolerance_ms": 0}
        else:
            targets[key] = {"kind": "no_answer"}
    observer, _ = observer_plan(raw, registry, targets)
    downloads = []
    for session in observer["participants"]:
        trials = []
        for i, row in enumerate(session["trials"], start=1):
            target = targets[observer["query_keys"][row["trial_id"]]]
            attempts = []
            terminal, elapsed, errors = "abstained", 1234, 0
            if row["candidates"]:
                candidate = row["candidates"][0]["clip"]
                attempts.append({"clip": candidate, "point_ms": target["out_ms"], "elapsed_ms": 100})
                if row["arm"] == "B":
                    attempts.append({"clip": candidate, "point_ms": target["in_ms"], "elapsed_ms": 250})
                    terminal, elapsed = "submitted", 1234
                else:
                    terminal, elapsed = "timeout", LIMIT_MS
            trials.append({"trial_id": row["trial_id"], "arm": row["arm"], "order": i, "outcome": terminal,
                           "elapsed_ms": elapsed, "submissions": attempts, "playback_errors": errors})
        downloads.append({**{k: session[k] for k in ("participant", "study_commitment", "replay_sha256", "limit_ms")},
                          "trials": trials})
    return raw, observer, downloads, registry


def scored(study):
    raw, observer, downloads, registry = study
    return score(raw, observer, [json.dumps(row).encode() for row in downloads], registry)


def test_scores_first_matching_point_and_preserves_every_failure(study):
    receipt = scored(study)
    a, b = receipt["metrics"]["A"], receipt["metrics"]["B"]
    assert a["answerable_trials"] == b["answerable_trials"] == 3
    assert a["correct_locations"] == 0 and a["failed_locations"] == 3
    assert a["location_outcomes"] == {"timeout": 3} and a["median_correct_location_ms"] is None
    assert b["correct_locations"] == 3 and b["failed_locations"] == 0
    assert b["correct_location_times_ms"] == [250, 250, 250] and b["median_correct_location_ms"] == 250
    assert a["correct_abstentions"] == b["correct_abstentions"] == 1
    assert a["top5_material_hits"] == b["top5_material_hits"] == 3
    assert a["top5_interval_hits"] is None and b["top5_interval_hits"] == 3
    assert a["no_answer_false_returns"] == b["no_answer_false_returns"] == 0
    assert receipt["acceptance_verified"] is False


def test_scoring_uses_observer_intervals_not_development_anchors(study):
    raw, observer, downloads, registry = study
    observer["targets"]["first-step"].update(in_ms=1000, out_ms=2000)
    changed, _ = observer_plan(raw, registry, observer["targets"])
    for record in downloads:
        record["study_commitment"] = changed["study_commitment"]
    b = scored((raw, changed, downloads, registry))["metrics"]["B"]
    assert b["top5_material_hits"] == 3 and b["top5_interval_hits"] == 2
    assert b["correct_locations"] == 2 and b["failed_locations"] == 1


def test_session_and_targets_are_bound_to_frozen_plan(study):
    raw, observer, downloads, registry = study
    fresh, _ = observer_plan(raw, registry, observer["targets"])
    assert fresh["study_commitment"] != observer["study_commitment"]
    with pytest.raises(ValueError, match="same frozen timing packet"):
        scored((raw, fresh, downloads, registry))
    observer["targets"]["first-step"]["in_ms"] += 1
    with pytest.raises(ValueError, match="Observer plan"):
        scored(study)
    pilot, _ = observer_plan(raw, registry)
    with pytest.raises(ValueError, match="Pilot"):
        scored((raw, pilot, downloads, registry))


@pytest.mark.parametrize("fault, message", [
    ("drop-trial", "Incomplete session"), ("clip", "clip not offered"), ("elapsed", "unordered submission"),
    ("order", "Trial assignment mismatch"), ("participant", "distinct P1 and P2"), ("drop-session", "Both participant"),
])
def test_rejects_incomplete_or_inconsistent_records(study, fault, message):
    downloads = study[2]
    row = downloads[0]["trials"][0]
    if fault == "drop-trial":
        downloads[0]["trials"].pop()
    elif fault == "clip":
        row["submissions"][0]["clip"] = "clip-2"
    elif fault == "elapsed":
        row["submissions"][0]["elapsed_ms"] = LIMIT_MS + 1
    elif fault == "order":
        row["order"] = 2
    elif fault == "participant":
        downloads[1]["participant"] = "P1"
    else:
        downloads.pop()
    with pytest.raises(ValueError, match=message):
        scored(study)


def test_frozen_intervals_must_fit_original(study):
    raw, observer, _, registry = study
    targets = observer["targets"]
    targets["first-step"]["out_ms"] = 99_999
    with pytest.raises(ValueError, match="Invalid source interval"):
        observer_plan(raw, registry, targets)
    targets["first-step"] = None
    with pytest.raises(ValueError, match="marked interval"):
        observer_plan(raw, registry, targets)
