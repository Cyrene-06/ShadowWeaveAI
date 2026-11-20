"""Prepare two local A/B timing sessions from a real Phase 2 replay, never score or sign G4."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from uuid import UUID

from sw_media.analysis import sha_file

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples/phase-2/nasa-demo.json"
TEMPLATE = Path(__file__).with_name("phase_two_timing.html")
LIMIT_MS = 60_000


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


def get_proxy(case, latest):
    run_id = str(UUID(latest["analysis_run_id"]))
    proxy_hash = latest["result"]["preview_sha256"]
    root = (case / "materials" / "derived").resolve(strict=True)
    matches = [p.resolve(strict=True) for p in root.glob(f"*/{run_id}/*/preview.mp4") if p.is_file()]
    if (len(matches) != 1 or not matches[0].is_relative_to(root) or sha_file(matches[0]) != proxy_hash):
        raise ValueError("Replay case is missing its exact, hash-matching proxy")
    return matches[0]


def write_packets(report_path, case, output):
    raw = report_path.read_bytes()
    report = json.loads(raw)
    registry = json.loads(CATALOG.read_text(encoding="utf-8"))
    trials, clips, runs = frozen_trials(report, registry)
    proxies = {clips[name]: get_proxy(case, runs[name]["latest"]) for name in clips}
    template = TEMPLATE.read_text(encoding="utf-8")
    packets_to_write = list(packets(trials))
    report_hash = hashlib.sha256(raw).hexdigest()
    for packet in packets_to_write:
        packet["replay_sha256"] = report_hash
    output.mkdir(parents=True, exist_ok=False)
    for packet in packets_to_write:
        folder = output / packet["participant"]
        folder.mkdir()
        data = json.dumps(packet, ensure_ascii=True).replace("<", "\\u003c")
        (folder / "index.html").write_text(template.replace("__PHASE_TWO_SESSION__", data), encoding="utf-8")
        used = {c["clip"] for row in packet["trials"] for c in row["candidates"]}
        for clip in sorted(used):
            shutil.copyfile(proxies[clip], folder / f"{clip}.mp4")
    query_keys = {f"T{i}": row["id"] for i, row in enumerate(trials, start=1)}
    observer = {"protocol": "phase-two-nasa-timing-1", "dataset_version": registry["version"],
                "replay_sha256": report_hash, "limit_ms": LIMIT_MS, "participants": packets_to_write,
                "query_keys": query_keys,
                "clip_sources": {clip: name for name, clip in clips.items()},
                "clip_sha256": {clips[name]: run["latest"]["result"]["preview_sha256"] for name, run in runs.items()},
                "targets": {row["id"]: None for row in trials},
                "targets_note": "Observer freezes independent source intervals/rejection rules before any trials."}
    (output / "observer.json").write_text(json.dumps(observer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Local verify_phase_two.py evidence JSON")
    parser.add_argument("--case", type=Path, required=True, help="Disposable replay case directory with its proxies")
    parser.add_argument("--output", type=Path, required=True, help="New directory under repository artifacts/")
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        artifacts = (ROOT / "artifacts").resolve()
        if output == artifacts or not output.is_relative_to(artifacts):
            raise ValueError("Keep video copies under the ignored artifacts directory")
        write_packets(args.report, args.case, output)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f"Timing preparation failed: {exc}\n")
    print(f"Prepared {output / 'P1'} and {output / 'P2'}; keep observer.json private until scoring")


if __name__ == "__main__":
    main()
