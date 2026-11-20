"""Reproduce Phase 2 on licensed NASA archival footage, with a disposable SQLite catalog."""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from sw_ai.coverage import evaluate_coverage
from sw_api.app import create_app
from sw_api.materials import keyword_rank
from sw_contracts import EvidenceManifest, StoryNode, digest
from sw_media.analysis import MAX_BYTES, ffmpeg, sha_file, tool_versions
from sw_worker.media_jobs import claim, clock, LEASE_MS, process_one, update_owned
from sw_api.db import session

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples/phase-2/nasa-demo.json"


def data_input(directory, registry, download):
    directory.mkdir(parents=True, exist_ok=True)
    for row in registry["assets"]:
        path = directory / row["name"]
        if not path.exists() and download:
            pending = path.with_suffix(".download")
            try:
                with httpx.stream("GET", row["url"], timeout=90, follow_redirects=True) as response:
                    response.raise_for_status()
                    with pending.open("wb") as handle:
                        for block in response.iter_bytes():
                            if handle.tell() + len(block) > MAX_BYTES:
                                raise ValueError("Source exceeds the evidence budget")
                            handle.write(block)
                if sha_file(pending) != row["sha256"]:
                    raise ValueError(f"Downloaded source SHA-256 does not match: {path.name}")
                pending.replace(path)
            finally:
                pending.unlink(missing_ok=True)
        if not path.is_file() or sha_file(path) != row["sha256"]:
            raise SystemExit(f"Missing or mismatched SHA-256: {path}")
        yield path


def content(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def candidate_refs(rows):
    fields = ("asset_id", "id", "analysis_run_id", "name", "in_ms", "out_ms", "source_sha256", "analysis_content_hash")
    return [{k: r[k] for k in fields} for r in rows]


def compare(client, base, rows, registry, project_id):
    by_asset = {}
    for row in rows:
        document = by_asset.setdefault(row["name"], [])
        document.extend(line["text"] for line in row["speech"])
    records, matching_refs = [], {}
    for q in registry["queries"]:
        scored = [(keyword_rank(q["text"], text, [])[0], name) for name, text in by_asset.items()]
        a = [name for n, name in sorted(scored, key=lambda pair: (-pair[0], pair[1])) if n][:5]
        b = content(client.get(base + "/search", params={"q": q["text"], "limit": 5}))["candidates"]
        match = []
        valid = 0
        for r in b:
            found = content(client.get(base + "/segments/" + r["id"]))
            valid += (
                r["project_id"] == project_id
                and candidate_refs([found]) == candidate_refs([r])
                and 0 <= r["in_ms"] <= r["frame_ms"] < r["out_ms"]
                and r["source_sha256"] == next(x["sha256"] for x in registry["assets"] if x["name"] == r["name"])
            )
            if r["name"] == q["asset"] and r["in_ms"] <= q["anchor_ms"] < r["out_ms"]:
                match.append(r)
        if match:
            matching_refs[q["id"]] = match[0]
        records.append({"query_id": q["id"], "answer_asset": q["asset"], "source_anchor_ms": q["anchor_ms"],
                        "a_assets": a, "b_candidates": candidate_refs(b), "b_valid_refs": valid,
                        "b_interval_hit": bool(match) if q["asset"] else None})
    positives = [r for r in records if r["answer_asset"]]
    negatives = [r for r in records if not r["answer_asset"]]
    stats = {
        "a_material_hits": sum(r["answer_asset"] in r["a_assets"] for r in positives),
        "b_material_hits": sum(any(x["name"] == r["answer_asset"] for x in r["b_candidates"]) for r in positives),
        "b_interval_hits": sum(r["b_interval_hit"] for r in positives),
        "answered_queries": len(positives), "no_answer_queries": len(negatives),
        "a_false_returns": sum(bool(r["a_assets"]) for r in negatives),
        "b_false_returns": sum(bool(r["b_candidates"]) for r in negatives),
        "b_verified_refs": sum(r["b_valid_refs"] for r in records),
        "b_returned_refs": sum(len(r["b_candidates"]) for r in records),
        "a_human_correct_seek_time_ms": None, "b_human_correct_seek_time_ms": None,
        "human_timing_reason": "An independent participant has not run the paired timed task",
    }
    return records, stats, matching_refs


def reproduce_worker_restart(database_url, case, analysis_id, read_state):
    # The verifier starts from a drained, disposable catalog and queues only the silent fixture.
    child_env = {**os.environ, "DATABASE_URL": database_url, "ARTIFACT_DIR": str(case)}
    child_env.pop("SW_MEDIA_ASR_MODEL", None)
    lose_worker = """
import os
import sys
from sw_api.db import get_engine
from sw_worker.media_jobs import claim, clock, LEASE_MS

job = claim(get_engine(), at_ms=clock() - LEASE_MS - 1)
if not job or job.get("id") != sys.argv[1] or job.get("attempts") != 1:
    sys.exit(2)
os._exit(23)  # lease is committed; skip ordinary shutdown
"""
    child = subprocess.run([sys.executable, "-c", lose_worker, analysis_id],
                           cwd=ROOT, env=child_env, timeout=30)
    assert child.returncode == 23, "Worker did not commit the target lease and exit as expected"
    before, no_refs = read_state()
    assert before["analysis_run_id"] == analysis_id and before["stage"] == "probe" and before["attempts"] == 1
    assert not no_refs, "Unpublished analysis must not appear in search"
    worker = [sys.executable, "-m", "sw_worker.media_jobs", "--once"]
    subprocess.run(worker, cwd=ROOT, env=child_env, timeout=180, check=True)
    after, refs = read_state()
    assert after["analysis_run_id"] == analysis_id and after["stage"] == "succeeded" and after["attempts"] == 2
    assert refs and len(refs) == after["result"]["segment_count"]
    assert len({row["id"] for row in refs}) == len(refs)
    assert all(row["analysis_run_id"] == analysis_id for row in refs)
    subprocess.run(worker, cwd=ROOT, env=child_env, timeout=180, check=True)
    assert read_state() == (after, refs), "Second restart changed the published run or candidate references"
    return {"analysis_run_id": analysis_id, "injected_child_exit_code": child.returncode,
            "final_attempts": after["attempts"], "published_segments": len(refs),
            "second_restart_unchanged": True, "scope": "isolated no-audio fixture; expired lease fault injection"}


def run(args):
    registry = json.loads(CATALOG.read_text(encoding="utf-8"))
    files = list(data_input(args.inputs, registry, args.download))
    case = args.artifacts.resolve() / uuid4().hex
    case.mkdir(parents=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    database_url = "sqlite:///" + (case / "catalog.sqlite3").as_posix()
    app = create_app(database_url, case, False)
    env = app.state.engine, case
    with app.state.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    run_names = {f.name: f for f in files}
    silent = case / "no-audio.mp4"
    ffmpeg(run_names["one-small-step.m4v"], "-map", "0:v:0", "-an", "-c:v", "copy", "-t", "6", silent)
    with TestClient(app) as client:
        register = content(client.post("/api/v1/auth/register", json={
            "email": f"repro-{uuid4().hex}@example.test", "display_name": "Stage Two Reproduction",
            "password": "isolated-local-probe-password",
        }), 201)
        client.headers["Authorization"] = "Bearer " + register["access_token"]
        project = content(client.post("/api/v1/projects", headers={"Idempotency-Key": "phase-two-nasa"},
                                      json={"name": "Apollo 11 evidence replay", "scenario": "organization"}), 201)
        base = f"/api/v1/projects/{project['id']}/materials"

        uploads_ms = {}

        def upload(name, raw, source):
            start = perf_counter()
            result = content(client.post(base + "/assets", params={"name": name, "source": source, "rights_confirmed": True},
                             headers={"Content-Type": "application/octet-stream"}, content=raw), 201)
            uploads_ms[name] = round((perf_counter() - start) * 1000)
            return result

        def latest(name):
            return next(r for r in content(client.get(base + "/assets")) if r["name"] == name)

        def reanalyze(asset, key):
            url = base + f"/assets/{asset}/analyses"
            return content(client.post(url, headers={"Idempotency-Key": key}), 202)

        def export(bindings):
            return content(client.post(base + "/evidence", json={"bindings": bindings}))

        rights = "NASA SVS 10451 — informational and educational testing; no endorsement"
        for path in files:
            upload(path.name, path.read_bytes(), rights)
        assert upload("duplicate.mp4", files[0].read_bytes(), rights)["duplicate"]
        upload(silent.name, silent.read_bytes(), rights + "; derived without audio")
        upload("broken.mp4", b"deliberately invalid video test bytes", "synthetic robustness fixture")
        # Simulate process loss by consuming a lease without publication, then re-claim once expired.
        abandoned = claim(env[0], at_ms=clock() - LEASE_MS - 1)
        assert abandoned is not None
        while process_one(*env, str(args.model.resolve()), "en"):
            pass
        with session(env[0]) as db:
            assert not update_owned(db, abandoned, stage="publish")
        assert latest(files[0].name)["latest"]["attempts"] == 2
        spoken = [latest(p.name) for p in files]
        for row in spoken:
            assert row["latest"]["result"]["speech"]["utterance_count"] > 0, row
        silent_baseline = latest(silent.name)
        assert silent_baseline["latest"]["result"]["speech"]["status"] == "not_applicable"
        assert latest("broken.mp4")["latest"]["error_code"] == "INVALID_MEDIA"
        rows = content(client.get(base + "/search", params={"limit": 50}))["candidates"]
        records, metrics, matches = compare(client, base, rows, registry, project["id"])
        assert matches.get("first-step"), "Core query did not locate the source evidence"
        assert metrics["b_verified_refs"] == metrics["b_returned_refs"] > 0
        assert metrics["b_false_returns"] == 0
        # Simulate a review submission to test the wire contract; this is NOT a human annotation.
        bindings = [{"segment_id": r["id"], "analysis_run_id": r["analysis_run_id"], "in_ms": r["in_ms"],
                     "out_ms": r["out_ms"], "requirement_keys": [key], "semantic_support": "supported",
                     "quality_usable": True, "reviewed": True} for key, r in sorted(matches.items())]
        manifest_json = export(bindings)
        manifest = EvidenceManifest.model_validate(manifest_json)
        node = StoryNode(project_id=project["id"], node_key="archival-quotes", goal="Ground the sample speech facts",
                         requirements=[q["id"] for q in registry["queries"] if q["asset"]], minimum_duration_ms=4000)
        coverage = evaluate_coverage(node, manifest, search_complete=True)
        selected = matches["first-step"]
        assert client.get(base + f"/segments/{selected['id']}/frame").headers["content-type"] == "image/jpeg"
        preview_path = base + f"/analyses/{selected['analysis_run_id']}/preview"
        assert client.get(preview_path, headers={"Range": "bytes=0-255"}).status_code == 206
        bad = {**bindings[0], "out_ms": bindings[0]["out_ms"] + 30_000}
        assert client.post(base + "/evidence", json={"bindings": [bad]}).status_code == 422
        bad = {**bindings[0], "analysis_run_id": str(uuid4())}
        assert client.post(base + "/evidence", json={"bindings": [bad]}).status_code == 422
        other = content(client.post("/api/v1/projects", headers={"Idempotency-Key": "other-project"},
                                    json={"name": "Isolation check", "scenario": "organization"}), 201)
        assert client.get(preview_path.replace(project["id"], other["id"])).status_code == 404
        old = selected["analysis_run_id"]
        fail_id = reanalyze(selected["asset_id"], "no-local-model")["analysis_run_id"]
        assert process_one(*env)  # deliberately not configured
        failed = latest(selected["name"])
        assert failed["active_analysis_id"] == old and failed["latest"]["error_code"] == "TRANSCRIPTION_NOT_CONFIGURED"
        new = reanalyze(selected["asset_id"], "working-model")
        assert reanalyze(selected["asset_id"], "working-model") == new
        assert process_one(*env, str(args.model.resolve()), "en")
        active = latest(selected["name"])
        assert active["active_analysis_id"] == new["analysis_run_id"] != old
        current = content(client.get(base + "/search", params={"asset_id": selected["asset_id"],
                                                                 "limit": 50}))["candidates"]
        assert current and all(r["analysis_run_id"] == active["active_analysis_id"] for r in current)
        assert export(bindings) == manifest_json
        assert client.get(preview_path, headers={"Range": "bytes=0-255"}).status_code == 206
        assert not process_one(*env)
        silent_id = silent_baseline["asset_id"]
        replacement = reanalyze(silent_id, "process-restart-probe")["analysis_run_id"]

        def silent_restart_state():
            asset = latest(silent.name)
            state = asset["latest"]
            active_id = replacement if state["stage"] == "succeeded" else silent_baseline["active_analysis_id"]
            assert asset["active_analysis_id"] == active_id
            candidates = content(client.get(base + "/search", params={"asset_id": silent_id,
                                                                       "limit": 50}))["candidates"]
            assert candidates and all(r["analysis_run_id"] == active_id for r in candidates)
            return state, candidate_refs(candidates) if active_id == replacement else []

        restart = reproduce_worker_restart(database_url, case, replacement, silent_restart_state)
        coverage_counts = {"human_confirmed_reqs": None, "matched_dev_anchors": len(matches),
                           "required_facts": sum(bool(q["asset"]) for q in registry["queries"])}
        out = {"dataset_version": registry["version"], "environment": {"os": platform.platform(),
                                                                     "python": sys.version.split()[0],
                                                                     **tool_versions()},
               "asset_inputs": [{"name": f.name, "sha256": sha_file(f)} for f in files],
               "actual_runs": spoken, "upload_request_ms": uploads_ms,
               "silent_fixture": silent_baseline, "broken_fixture": latest("broken.mp4"), "worker_restart": restart,
               "query_records": records, "diagnostic_metrics": {**metrics, **coverage_counts},
               "partition": "development-only, one source event", "coverage_handoff": {
                   "review_provenance": "scripted API review submission using development anchors; not a human annotation",
                   "node": coverage.node_key, "state": coverage.coverage, "manifest_hash": digest(manifest_json),
                   "per_requirement": [r.model_dump(mode="json") for r in coverage.requirement_results],
               }, "checks": {"source_preview_range": True, "duplicate_upload_reuses_asset": True,
                            "cross_project_preview_rejected": True, "expired_lease_recovers_once": True,
                            "wrong_source_interval_and_version_rejected": True, "historical_manifest_unchanged": True},
               "reanalysis": {"failed_id": fail_id, "failed_run": failed["latest"], "old_active": old, "new_active": active},
               "independent_reproduction": "pending teammate run; not counted as passed"}
    app.state.engine.dispose()
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=ROOT / "artifacts/phase-two-input")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts/phase-two-repro")
    parser.add_argument("--model", type=Path, required=True, help="Pinned local tiny.en snapshot directory")
    parser.add_argument("--download", action="store_true", help="Fetch only the pinned NASA clips when absent")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    if args.output.exists():
        parser.error("--output must be a new file; choose another path to preserve the previous record")
    result = run(args)
    result["tested_source_base"] = git.stdout.strip()
    result["working_tree_had_changes"] = bool(dirty.stdout.strip())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")
    print(json.dumps(result["diagnostic_metrics"], ensure_ascii=False))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
