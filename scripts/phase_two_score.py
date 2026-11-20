"""Score submitted locations against frozen targets; never attest human review or sign G4."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median

from scripts.phase_two_timing import CATALOG, LIMIT_MS, observer_plan


def bounded_integer(value, limit):
    return type(value) is int and 0 <= value <= limit


def target_window(target, duration):
    tolerance = target["tolerance_ms"]
    return max(0, target["in_ms"] - tolerance), min(duration, target["out_ms"] + tolerance)


def retrieval_for(assignment, target, clip_sources, runs):
    candidates = assignment["candidates"]
    if target["kind"] == "no_answer":
        return {"candidate_count": len(candidates), "material_hit": None, "interval_hit": None}
    asset = target["asset"]
    matched = [row for row in candidates if clip_sources[row["clip"]] == asset]
    interval_hit = None
    if assignment["arm"] == "B":
        lower, upper = target_window(target, runs[asset]["latest"]["result"]["duration_ms"])
        interval_hit = any(max(lower, row["in_ms"]) < min(upper, row["out_ms"]) for row in matched)
    return {"candidate_count": len(candidates), "material_hit": bool(matched), "interval_hit": interval_hit}


def score_trial(record, assignment, order, plan, runs):
    key = assignment["trial_id"]
    if (record["trial_id"] != key or record["arm"] != assignment["arm"]
            or type(record["order"]) is not int or record["order"] != order):
        raise ValueError(f"Trial assignment mismatch for {key}")
    elapsed, terminal = record["elapsed_ms"], record["outcome"]
    errors = record["playback_errors"]
    if (not bounded_integer(elapsed, LIMIT_MS) or type(errors) is not int or errors < 0
            or terminal not in {"submitted", "timeout", "abstained"} or (terminal == "timeout" and elapsed != LIMIT_MS)):
        raise ValueError(f"Invalid timing or terminal outcome for {key}")
    submissions = record["submissions"]
    if not isinstance(submissions, list) or (terminal == "submitted" and not submissions):
        raise ValueError(f"Invalid submissions for {key}")
    query = plan["query_keys"][key]
    target = plan["targets"][query]
    no_answer = target["kind"] == "no_answer"
    candidates = {row["clip"] for row in assignment["candidates"]}
    first = None
    previous = 0
    for item in submissions:
        clip, point, submitted_at = item["clip"], item["point_ms"], item["elapsed_ms"]
        if clip not in candidates:
            raise ValueError(f"Submission references a clip not offered for {key}")
        asset = plan["clip_sources"][clip]
        duration = runs[asset]["latest"]["result"]["duration_ms"]
        if not bounded_integer(point, duration) or not bounded_integer(submitted_at, elapsed) or submitted_at < previous:
            raise ValueError(f"Invalid or unordered submission for {key}")
        previous = submitted_at
        if not no_answer and first is None and asset == target["asset"]:
            lower, upper = target_window(target, duration)
            if lower <= point < upper:
                first = {"asset": asset, "point_ms": point, "elapsed_ms": submitted_at}
    if no_answer:
        result = "correct_abstention" if terminal == "abstained" and not submissions else "not_confirmed_abstention"
    elif first is not None:
        result = "correct_location"
    elif not candidates:
        result = "no_candidates"
    elif errors and not submissions:
        result = "playback_error"
    elif terminal == "timeout":
        result = "timeout"
    elif terminal == "abstained":
        result = "abstained"
    else:
        result = "incorrect_location"
    return {"query_id": query, "arm": assignment["arm"], "order": order, "expected_no_answer": no_answer,
            "terminal_outcome": terminal, "elapsed_ms": elapsed, "playback_errors": errors,
            "submission_count": len(submissions), "result": result, "first_matching_submission": first,
            "retrieval": retrieval_for(assignment, target, plan["clip_sources"], runs)}


def score(raw, observer, record_bytes, registry):
    nonce = observer.get("observer_nonce")
    if not isinstance(nonce, str) or not re.fullmatch("[a-f0-9]{32}", nonce):
        raise ValueError("Pilot or invalid observer plan; generate a new packet with --targets before conducting trials")
    plan, runs = observer_plan(raw, registry, observer["targets"], nonce)
    if observer != plan:
        raise ValueError("Observer plan does not match the replay, frozen targets or assignment")
    assigned = {row["participant"]: row for row in plan["participants"]}
    sessions = {}
    for blob in record_bytes:
        record = json.loads(blob)
        participant = record["participant"]
        if participant not in assigned or participant in sessions:
            raise ValueError("Expected distinct P1 and P2 downloads")
        if (record["study_commitment"] != plan["study_commitment"] or record["replay_sha256"] != plan["replay_sha256"]
                or record["limit_ms"] != LIMIT_MS):
            raise ValueError("Download is not from the same frozen timing packet")
        trials = assigned[participant]["trials"]
        if not isinstance(record["trials"], list) or len(record["trials"]) != len(trials):
            raise ValueError("Incomplete session; preserve every trial including failures")
        sessions[participant] = {
            "download_sha256": hashlib.sha256(blob).hexdigest(),
            "trials": [score_trial(result, trial, i, plan, runs)
                       for i, (result, trial) in enumerate(zip(record["trials"], trials, strict=True), start=1)],
        }
    if set(sessions) != set(assigned):
        raise ValueError("Both participant downloads are required")
    metrics = {}
    for arm in ("A", "B"):
        rows = [row for session in sessions.values() for row in session["trials"] if row["arm"] == arm]
        positives = [row for row in rows if not row["expected_no_answer"]]
        negatives = [row for row in rows if row["expected_no_answer"]]
        times = sorted(row["first_matching_submission"]["elapsed_ms"] for row in positives
                       if row["first_matching_submission"] is not None)
        metrics[arm] = {"answerable_trials": len(positives), "correct_locations": len(times),
                        "failed_locations": len(positives) - len(times),
                        "location_outcomes": dict(Counter(row["result"] for row in positives)),
                        "terminal_outcomes": dict(Counter(row["terminal_outcome"] for row in rows)),
                        "correct_location_times_ms": times, "median_correct_location_ms": median(times) if times else None,
                        "no_answer_trials": len(negatives),
                        "correct_abstentions": sum(row["result"] == "correct_abstention" for row in negatives),
                        "top5_material_hits": sum(row["retrieval"]["material_hit"] for row in positives),
                        "top5_interval_hits": sum(row["retrieval"]["interval_hit"] for row in positives) if arm == "B" else None,
                        "no_answer_false_returns": sum(row["retrieval"]["candidate_count"] > 0 for row in negatives)}
    return {"protocol": plan["protocol"], "dataset_version": plan["dataset_version"],
            "replay_sha256": plan["replay_sha256"], "study_commitment": plan["study_commitment"],
            "metrics": metrics, "sessions": dict(sorted(sessions.items())), "acceptance_verified": False,
            "scope": "Structural scoring only. Observer must attest real playback, timing and independence separately."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("observer", type=Path)
    parser.add_argument("downloads", nargs=2, type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New file for the comparison receipt")
    args = parser.parse_args()
    try:
        result = score(args.replay.read_bytes(), json.loads(args.observer.read_bytes()),
                       [p.read_bytes() for p in args.downloads], json.loads(CATALOG.read_bytes()))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f"Could not score timing records: {exc}\n")
    print(f"Wrote {args.output}; human acceptance still requires an observer sign-off")


if __name__ == "__main__":
    main()
