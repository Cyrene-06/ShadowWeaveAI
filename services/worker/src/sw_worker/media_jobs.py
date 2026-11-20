"""Durable phase-two queue and transactional publication of a media analysis."""

import argparse
import logging
import os
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, insert, or_, select, update

from sw_api import db as t
from sw_contracts import digest
from sw_contracts.validation import RuleError
from sw_media import analysis as media

LEASE_MS = 900_000
MAX_ATTEMPTS = 2


def clock():
    return time.time_ns() // 1_000_000


def object_path(root, key):
    base = (Path(root) / "materials").resolve()
    path = (base / key).resolve()
    if not path.is_relative_to(base) or path == base:
        raise RuleError("NOT_FOUND", "Media object is unavailable")
    return path


def enqueue(db, project_id, asset_id, generation):
    job_id, run_id = str(uuid4()), str(uuid4())
    config = {"policy": media.TOOL_POLICY, "ffmpeg_threads": 2, "scene_threshold": 0.35,
              "max_duration_ms": media.MAX_DURATION_MS, "speech_word_timestamps": True}
    db.execute(insert(t.jobs).values(id=job_id, project_id=project_id, state="queued"))
    db.execute(insert(t.analyses).values(id=run_id, project_id=project_id, asset_id=asset_id, root_job_id=job_id,
                                        state="queued", config_hash=digest(config), config_snapshot=config))
    db.execute(insert(t.media_runs).values(id=run_id, project_id=project_id, asset_id=asset_id,
                                           job_id=job_id, generation=generation, stage="queued", attempts=0,
                                           enqueued_ms=clock()))
    return str(run_id)


def claim(engine, at_ms=None):
    now = clock() if at_ms is None else at_ms
    r = t.media_runs.c
    eligible = or_(r.stage == "queued", and_(r.lease_until_ms <= now, r.stage.not_in(("succeeded", "failed"))))
    with t.session(engine) as db:
        row = db.execute(select(t.media_runs).where(eligible).order_by(r.enqueued_ms, r.id).limit(1)).mappings().first()
        if not row:
            return None
        token = str(uuid4())
        exhausted = row["attempts"] >= MAX_ATTEMPTS
        # Compare the attempt as well as eligibility in case the selected lease was superseded.
        claimed = db.execute(update(t.media_runs).where(
            r.id == row["id"], r.attempts == row["attempts"], eligible,
        ).values(
            stage="failed" if exhausted else "probe", attempts=row["attempts"] + (not exhausted),
            started_ms=row["started_ms"] if row["started_ms"] is not None else now,
            lease_token=None if exhausted else token, lease_until_ms=None if exhausted else now + LEASE_MS,
            error_code="WORKER_INTERRUPTED" if exhausted else None, finished_ms=now if exhausted else None,
        ).returning(t.media_runs)).mappings().first()
        if not claimed:
            return None
        if exhausted:
            set_states(db, claimed, "failed")
            return {"exhausted": True, "id": claimed["id"]}
        set_states(db, claimed, "running")
        return dict(claimed)


def set_states(db, job, state):
    db.execute(update(t.jobs).where(t.jobs.c.id == job["job_id"]).values(state=state))
    db.execute(update(t.analyses).where(t.analyses.c.id == job["id"]).values(state=state))


def update_owned(db, job, **values):
    r = t.media_runs.c
    return db.execute(update(t.media_runs).where(
        r.id == job["id"], r.lease_token == job["lease_token"], r.lease_until_ms > clock(),
    ).values(**values)).rowcount == 1


def checkpoint(engine, job, stage):
    with t.session(engine) as db:
        if not update_owned(db, job, stage=stage, lease_until_ms=clock() + LEASE_MS):
            raise RuleError("LEASE_LOST", "Media job was claimed by another worker")


def utterances_for(rows, start, end):
    # Keep only words owned by this half-open interval; a word straddling a cut has one owner.
    output = []
    for row in rows:
        words = [w for w in row["words"] if start <= (w["in_ms"] + w["out_ms"]) // 2 < end]
        if words:
            output.append({"in_ms": max(start, words[0]["in_ms"]), "out_ms": min(end, words[-1]["out_ms"]),
                           "text": "".join(w["text"] for w in words).strip()})
        elif not row["words"] and start <= row["in_ms"] < row["out_ms"] <= end:
            output.append({k: row[k] for k in ("in_ms", "out_ms", "text")})
    return output


def publish(engine, job, rows, result, config, duration, prefix):
    with t.session(engine) as db:
        c = t.media_catalog.c
        db.execute(update(t.media_catalog).where(c.asset_id == job["asset_id"]).values(latest_generation=c.latest_generation))
        if not update_owned(db, job, stage="succeeded", lease_token=None, lease_until_ms=None,
                            finished_ms=clock(), result=result):
            raise RuleError("LEASE_LOST", "Media job was claimed by another worker")
        for row in rows:
            segment_id = str(uuid4())
            start, end = row["in_ms"], row["out_ms"]
            if not (0 <= start <= row["frame_ms"] < end <= duration):
                raise RuleError("INVALID_MEDIA", "Produced source interval is invalid")
            db.execute(insert(t.segments).values(id=segment_id, project_id=job["project_id"],
                       asset_id=job["asset_id"], analysis_run_id=job["id"], in_ms=start, out_ms=end))
            db.execute(insert(t.media_observations).values(segment_id=segment_id, project_id=job["project_id"],
                       frame_ms=row["frame_ms"], frame_key=f"{prefix}/{row['frame']}",
                       transcript=row["transcript"], signals=row["signals"]))
        db.execute(update(t.assets).where(t.assets.c.id == job["asset_id"]).values(duration_ms=duration))
        db.execute(update(t.analyses).where(t.analyses.c.id == job["id"]).values(
            config_hash=digest(config), config_snapshot=config,
        ))
        set_states(db, job, "succeeded")
        db.execute(update(t.media_catalog).where(t.media_catalog.c.asset_id == job["asset_id"],
                   t.media_catalog.c.latest_generation == job["generation"]).values(active_analysis_id=job["id"]))


def fail(engine, job, code, telemetry):
    with t.session(engine) as db:
        if update_owned(db, job, stage="failed", finished_ms=clock(), error_code=code,
                        lease_token=None, lease_until_ms=None, result={"timing_ms": telemetry}):
            set_states(db, job, "failed")


def process_one(engine, root, model=None, language="auto"):
    job = claim(engine)
    if not job or job.get("exhausted"):
        return job is not None
    telemetry, stage_start = {}, clock()
    prefix = f"derived/{job['project_id']}/{job['id']}/{job['lease_token']}"
    work = object_path(root, prefix)
    try:
        with t.session(engine) as db:
            source = db.execute(select(t.objects, t.analyses.c.config_snapshot).join(
                t.assets, and_(t.assets.c.project_id == t.objects.c.project_id,
                               t.assets.c.original_object_id == t.objects.c.id),
            ).join(t.analyses, t.analyses.c.asset_id == t.assets.c.id).where(
                t.assets.c.id == job["asset_id"], t.analyses.c.id == job["id"],
            )).mappings().one()
        path = object_path(root, source["storage_key"])
        if not path.is_file() or media.sha_file(path) != source["sha256"]:
            raise RuleError("SOURCE_UNAVAILABLE", "Original media is no longer available or changed")
        info = media.inspect(path)
        versions = media.tool_versions()
        telemetry["probe"] = clock() - stage_start
        checkpoint(engine, job, "media")
        stage_start = clock()
        work.mkdir(parents=True, exist_ok=False)
        preview, rows, split = media.prepare_media(path, work, info)
        telemetry["media"] = clock() - stage_start
        checkpoint(engine, job, "speech")
        stage_start = clock()
        if info["has_audio"]:
            transcript, transcription = media.speech(path, work, model, language, info["duration_ms"])
        else:
            transcript, transcription = [], {"status": "not_applicable", "reason": "no_audio_stream"}
        telemetry["speech"] = clock() - stage_start
        checkpoint(engine, job, "publish")
        for row in rows:
            row["transcript"] = utterances_for(transcript, row["in_ms"], row["out_ms"])
            row["frame_sha256"] = media.sha_file(work / row["frame"])
        config = {**source["config_snapshot"], "tools": versions, "speech": {
            k: transcription[k] for k in ("provider", "version", "snapshot", "model_files_sha256", "language")
            if k in transcription
        }}
        content = {"source_sha256": source["sha256"], "config_hash": digest(config), "segments": rows,
                   "preview_sha256": media.sha_file(preview)}
        result = {"preview_key": f"{prefix}/{preview.name}", "preview_sha256": content["preview_sha256"],
                  "content_hash": digest(content), "tools": versions, "timing_ms": telemetry, "split": split,
                  "speech": transcription, "segment_count": len(rows), "duration_ms": info["duration_ms"]}
        publish(engine, job, rows, result, config, info["duration_ms"], prefix)
    except Exception as exc:
        code = exc.code if isinstance(exc, RuleError) else "ANALYSIS_FAILED"
        logging.warning("media run %s failed: %s (%s)", job["id"], code, type(exc).__name__)
        telemetry["last_stage_before_failure"] = clock() - stage_start
        fail(engine, job, code, telemetry)
        if work.is_dir():
            for output in work.iterdir():
                if output.is_file():
                    output.unlink(missing_ok=True)
            work.rmdir()
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--once", action="store_true", help="Drain available work, then exit")
    args = p.parse_args()
    from sw_api.app import ROOT

    engine = t.get_engine()
    root = Path(os.environ.get("ARTIFACT_DIR", ROOT / "artifacts"))
    model = os.environ.get("SW_MEDIA_ASR_MODEL")
    language = os.environ.get("SW_MEDIA_ASR_LANGUAGE", "auto")
    try:
        while True:
            if not process_one(engine, root, model, language):
                if args.once:
                    return
                time.sleep(1)
    except KeyboardInterrupt:
        return
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
