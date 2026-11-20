"""Prepare two local A/B timing sessions from a real Phase 2 replay, never score or sign G4."""

import argparse
import hashlib
import json
import secrets
import shutil
from pathlib import Path
from uuid import UUID

from sw_media.analysis import sha_file

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples/phase-2/nasa-demo.json"
TEMPLATE = Path(__file__).with_name("phase_two_timing.html")
LIMIT_MS = 60_000
PROTOCOL = "phase-two-nasa-timing-2"


def frozen_trials(report, registry):
    if report["dataset_version"] != registry["version"]:
        raise ValueError("Replay and source registry versions differ")
    source = {a["name"]: a["sha256"] for a in registry["assets"]}
    if sorted((a["name"], a["sha256"]) for a in report["asset_inputs"]) != sorted(source.items()):
        raise ValueError("Replay inputs do not match registered originals")
    runs = {}
    clips = {name: f"clip-{i}" for i, name in enumerate(source, start=1)}
    for row in report["actual_runs"]:
        name, latest = row["name"], row["latest"]
        if (name in runs or source.get(name) != row["sha256"] or latest["stage"] != "succeeded"
                or row["active_analysis_id"] != latest["analysis_run_id"]):
            raise ValueError("Replay must describe one successful active analysis per original")
        UUID(latest["analysis_run_id"])
        runs[name] = row
    if set(runs) != set(source):
        raise ValueError("Missing successful runs")
    records = {r["query_id"]: r for r in report["query_records"]}
    expected = {q["id"] for q in registry["queries"]}
    if len(report["query_records"]) != len(expected) or set(records) != expected:
        raise ValueError("Replay query set does not match the timing protocol")

    trials = []
    for query in registry["queries"]:
        row = records[query["id"]]
        a, b = row["a_assets"], row["b_candidates"]
        if len(a) > 5 or len(b) > 5 or len(a) != len(set(a)) or not set(a) <= set(source):
            raise ValueError("Unexpected file/segment ranking")
        if row["b_valid_refs"] != len(b) or len({r["id"] for r in b}) != len(b):
            raise ValueError("Segment ranking contains unverified or duplicate references")
        for ref in b:
            run = runs[ref["name"]]
            latest = run["latest"]
            if (ref["asset_id"] != run["asset_id"] or ref["source_sha256"] != run["sha256"]
                    or ref["analysis_run_id"] != latest["analysis_run_id"]
                    or ref["analysis_content_hash"] != latest["result"]["content_hash"]
                    or not 0 <= ref["in_ms"] < ref["out_ms"] <= latest["result"]["duration_ms"]):
                raise ValueError("Segment ranking is not bound to its original and frozen analysis")
        trials.append({"id": query["id"], "query": query["text"],
                       "A": [{"clip": clips[name]} for name in a],
                       "B": [{"clip": clips[r["name"]], "in_ms": r["in_ms"], "out_ms": r["out_ms"]} for r in b]})
    return trials, clips, runs


def packets(trials):
    if len(trials) != 4:
        raise ValueError("The fixed NASA protocol expects four trials")
    # Both queries sharing the step clip stay in the same arm for each participant.
    placements = ((0, 2, 1, 3), (1, 2, 3, 0))
    for i, order in enumerate(placements):
        rows = []
        for index in order:
            trial = trials[index]
            arm = "A" if (index < 2) == (i == 0) else "B"
            rows.append({"trial_id": f"T{index + 1}", "query": trial["query"], "arm": arm, "candidates": trial[arm]})
        yield {"participant": f"P{i + 1}", "limit_ms": LIMIT_MS, "trials": rows}


def validate_targets(targets, registry, runs):
    queries = {q["id"]: q for q in registry["queries"]}
    if not isinstance(targets, dict) or set(targets) != set(queries):
        raise ValueError("Freeze one target per registered query")
    for key, target in targets.items():
        if not queries[key]["asset"]:
            if target != {"kind": "no_answer"}:
                raise ValueError(f"Expected an explicit no-answer target for {key}")
            continue
        if not isinstance(target, dict) or set(target) != {"kind", "asset", "in_ms", "out_ms", "tolerance_ms"}:
            raise ValueError(f"Expected an independently marked interval for {key}")
        if target["kind"] != "interval" or target["asset"] not in runs:
            raise ValueError(f"Target must reference a registered source for {key}")
        start, end, tolerance = (target[k] for k in ("in_ms", "out_ms", "tolerance_ms"))
        if any(type(v) is not int for v in (start, end, tolerance)):
            raise ValueError(f"Use integer milliseconds for {key}")
        duration = runs[target["asset"]]["latest"]["result"]["duration_ms"]
        if not 0 <= start < end <= duration or not 0 <= tolerance <= 1000:
            raise ValueError(f"Invalid source interval or tolerance for {key}")


def commitment(replay_hash, targets, nonce):
    value = json.dumps([PROTOCOL, replay_hash, targets, nonce], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def observer_plan(raw, registry, targets=None, nonce=None):
    trials, clips, runs = frozen_trials(json.loads(raw), registry)
    report_hash = hashlib.sha256(raw).hexdigest()
    if targets is not None:
        validate_targets(targets, registry, runs)
        if nonce is None:
            nonce = secrets.token_hex(16)
    else:
        targets = {row["id"]: None for row in trials}
    seal = commitment(report_hash, targets, nonce) if nonce is not None else None
    assigned = list(packets(trials))
    for packet in assigned:
        packet.update(replay_sha256=report_hash, study_commitment=seal)
    plan = {"protocol": PROTOCOL, "dataset_version": registry["version"],
            "replay_sha256": report_hash, "study_commitment": seal, "observer_nonce": nonce,
            "limit_ms": LIMIT_MS, "participants": assigned,
            "query_keys": {f"T{i}": row["id"] for i, row in enumerate(trials, start=1)},
            "clip_sources": {clip: name for name, clip in clips.items()},
            "clip_sha256": {clips[name]: run["latest"]["result"]["preview_sha256"] for name, run in runs.items()},
            "targets": targets}
    return plan, runs


def get_proxy(case, latest):
    run_id = str(UUID(latest["analysis_run_id"]))
    proxy_hash = latest["result"]["preview_sha256"]
    root = (case / "materials" / "derived").resolve(strict=True)
    matches = [p.resolve(strict=True) for p in root.glob(f"*/{run_id}/*/preview.mp4") if p.is_file()]
    if (len(matches) != 1 or not matches[0].is_relative_to(root) or sha_file(matches[0]) != proxy_hash):
        raise ValueError("Replay case is missing its exact, hash-matching proxy")
    return matches[0]


def write_packets(report_path, case, output, targets=None):
    raw = report_path.read_bytes()
    registry = json.loads(CATALOG.read_text(encoding="utf-8"))
    observer, runs = observer_plan(raw, registry, targets)
    proxies = {clip: get_proxy(case, runs[name]["latest"]) for clip, name in observer["clip_sources"].items()}
    template = TEMPLATE.read_text(encoding="utf-8")
    output.mkdir(parents=True, exist_ok=False)
    for packet in observer["participants"]:
        folder = output / packet["participant"]
        folder.mkdir()
        data = json.dumps(packet, ensure_ascii=True).replace("<", "\\u003c")
        (folder / "index.html").write_text(template.replace("__PHASE_TWO_SESSION__", data), encoding="utf-8")
        used = {c["clip"] for row in packet["trials"] for c in row["candidates"]}
        for clip in sorted(used):
            shutil.copyfile(proxies[clip], folder / f"{clip}.mp4")
    (output / "observer.json").write_text(json.dumps(observer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Local verify_phase_two.py evidence JSON")
    parser.add_argument("--case", type=Path, required=True, help="Disposable replay case directory with its proxies")
    parser.add_argument("--output", type=Path, required=True, help="New directory under repository artifacts/")
    parser.add_argument("--targets", type=Path, help="Independently frozen targets; omit only for an unscorable pilot")
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        artifacts = (ROOT / "artifacts").resolve()
        if output == artifacts or not output.is_relative_to(artifacts):
            raise ValueError("Keep video copies under the ignored artifacts directory")
        targets = json.loads(args.targets.read_bytes()) if args.targets else None
        if args.targets and not isinstance(targets, dict):
            raise ValueError("Targets file must be a JSON object")
        write_packets(args.report, args.case, output, targets)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f"Timing preparation failed: {exc}\n")
    if not args.targets:
        print("Pilot only: no frozen targets; records cannot be scored.")
    print(f"Prepared {output / 'P1'} and {output / 'P2'}; keep observer.json private until scoring")


if __name__ == "__main__":
    main()
