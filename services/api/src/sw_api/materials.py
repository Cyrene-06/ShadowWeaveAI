"""Authorized phase-two video ingestion, review and evidence export."""

import hashlib
import re
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from sw_contracts import Asset, Contract, Evidence, EvidenceManifest, Segment, digest
from sw_contracts.models import MaterialCandidate, MaterialEvidenceRequest, MaterialSearch
from sw_contracts.validation import RuleError, resolve_manifest
from sw_media.analysis import ALLOWED_SUFFIXES, MAX_BYTES
from sw_worker.media_jobs import enqueue, object_path

from . import db as t

MAX_ASSETS = 50
PENDING = {"queued", "probe", "media", "speech", "publish"}
MEDIA_NAMESPACE = UUID("1695583f-fe02-47d3-8ea4-13daaca27287")


class MediaRunView(Contract):
    analysis_run_id: UUID
    job_id: UUID
    generation: int = Field(ge=1)
    stage: Literal["queued", "probe", "media", "speech", "publish", "succeeded", "failed"]
    attempts: int = Field(ge=0)
    error_code: str | None
    queue_ms: int | None = Field(ge=0)
    wall_ms: int | None = Field(ge=0)
    result: dict[str, object]


class MediaAssetView(Contract):
    asset_id: UUID
    name: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    active_analysis_id: UUID | None
    latest: MediaRunView
    duplicate: bool


class MediaEnqueued(Contract):
    analysis_run_id: UUID
    generation: int = Field(ge=1)


class HumanTag(Contract):
    label: str = Field(min_length=1, max_length=80)


def tokens(text):
    return list(dict.fromkeys(re.findall(r"\w+", text.casefold())))


def keyword_rank(query, transcript, labels):
    # Phrase/token substring baseline; no embeddings or fabricated results.
    words = tokens(query)
    channels = {"transcript": " ".join(transcript).casefold(), "human_tag": " ".join(labels).casefold()}
    if not words or not all(any(word in text for text in channels.values()) for word in words):
        return 0, []
    counts = {key: sum(word in text for word in words) for key, text in channels.items()}
    return sum(counts.values()), [key for key, count in counts.items() if count]


def material_routes(root, db_session, user, access):
    router = APIRouter(prefix="/api/v1/projects/{project_id}/materials", tags=["materials"])

    def catalog(db, pid, aid):
        c = t.media_catalog.c
        row = db.execute(select(t.media_catalog).where(c.project_id == pid, c.asset_id == aid)).mappings().first()
        if not row:
            raise RuleError("NOT_FOUND", "Material not found")
        return row

    def run_view(row):
        payload = dict(row["result"] or {})
        payload.pop("preview_key", None)
        started = row["started_ms"]
        return {"analysis_run_id": row["id"], "job_id": row["job_id"], "generation": row["generation"],
                "stage": row["stage"], "attempts": row["attempts"], "error_code": row["error_code"],
                "queue_ms": max(0, started - row["enqueued_ms"]) if started is not None else None,
                "wall_ms": max(0, row["finished_ms"] - row["enqueued_ms"]) if row["finished_ms"] is not None else None,
                "result": payload}

    def asset_view(db, row, duplicate=False):
        r = t.media_runs.c
        latest = db.execute(select(t.media_runs).where(r.asset_id == row["asset_id"],
                           r.generation == row["latest_generation"])).mappings().one()
        return {"asset_id": row["asset_id"], "name": row["name"], "sha256": row["sha256"],
                "active_analysis_id": row["active_analysis_id"], "latest": run_view(latest), "duplicate": duplicate}

    @router.post("/assets", status_code=201, response_model=MediaAssetView, openapi_extra={"requestBody": {"required": True, "content": {
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    }}})
    async def upload(project_id: UUID, request: Request, name: str = Query(min_length=1, max_length=250),
                     source: str = Query(min_length=1, max_length=300),
                     rights_confirmed: bool = Query(), uid=Depends(user), db=Depends(db_session)):
        pid = str(project_id)
        access(db, project_id, uid, write=True)
        name, source = name.strip(), source.strip()
        if (not rights_confirmed or not source or not name or re.search(r"[\x00-\x1f/\\]", name)
                or Path(name).suffix.lower() not in ALLOWED_SUFFIXES):
            raise RuleError("INVALID_ARGUMENT", "Confirm usage rights and choose an MP4/M4V/MOV/WebM/MKV video")
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/octet-stream":
            raise RuleError("INVALID_ARGUMENT", "Send raw binary video data as application/octet-stream")
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BYTES:
            raise RuleError("FILE_TOO_LARGE", "Video limit is 64 MiB")
        aid, oid = str(uuid4()), str(uuid4())
        key = f"original/{pid}/{oid}{Path(name).suffix.lower()}"
        file = object_path(root, key)
        file.parent.mkdir(parents=True, exist_ok=True)
        total, sha, keep = 0, hashlib.sha256(), False
        try:
            with file.open("xb") as dest:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise RuleError("FILE_TOO_LARGE", "Video limit is 64 MiB")
                    sha.update(chunk)
                    dest.write(chunk)
            if not total:
                raise RuleError("INVALID_ARGUMENT", "Empty upload")
            checksum = sha.hexdigest()
            c = t.media_catalog.c
            # Serialize project ingest to make the small-project catalog bound deterministic.
            db.execute(update(t.projects).where(t.projects.c.id == pid).values(revision=t.projects.c.revision))
            existing = db.execute(select(t.media_catalog).where(c.project_id == pid, c.sha256 == checksum)).mappings().first()
            if existing:
                return asset_view(db, existing, True)
            if db.execute(select(func.count()).select_from(t.media_catalog).where(c.project_id == pid)).scalar_one() >= MAX_ASSETS:
                raise RuleError("INVALID_ARGUMENT", "This phase-two catalog supports up to 50 videos per project")
            db.execute(insert(t.objects).values(id=oid, project_id=pid, storage_key=key, sha256=checksum, size_bytes=total))
            db.execute(insert(t.assets).values(id=aid, project_id=pid, media_type="video", sha256=checksum,
                       original_object_id=oid, license_info={"source_and_rights": source, "confirmed_by": uid}))
            db.execute(insert(t.media_catalog).values(asset_id=aid, project_id=pid, sha256=checksum,
                                                       name=name, latest_generation=1))
            enqueue(db, pid, aid, 1)
            response = asset_view(db, catalog(db, pid, aid))
            # Do not keep a raw object if the database transaction fails.
            db.commit()
            keep = True
            return response
        finally:
            if not keep:
                file.unlink(missing_ok=True)

    @router.get("/assets", response_model=list[MediaAssetView])
    def assets(project_id: UUID, uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid)
        c = t.media_catalog.c
        rows = db.execute(select(t.media_catalog).where(c.project_id == str(project_id)).order_by(c.name, c.asset_id))
        return [asset_view(db, row) for row in rows.mappings()]

    @router.get("/assets/{asset_id}/analyses", response_model=list[MediaRunView])
    def analyses(project_id: UUID, asset_id: UUID, uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid)
        catalog(db, str(project_id), str(asset_id))
        r = t.media_runs.c
        rows = db.execute(select(t.media_runs).where(r.asset_id == str(asset_id)).order_by(r.generation.desc()).limit(50))
        return [run_view(row) for row in rows.mappings()]

    @router.post("/assets/{asset_id}/analyses", status_code=202, response_model=MediaEnqueued)
    def retry(project_id: UUID, asset_id: UUID, idempotency_key: str = Header(min_length=1, max_length=128),
              uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid, write=True)
        pid, aid = str(project_id), str(asset_id)
        c, i = t.media_catalog.c, t.idempotency.c
        row = catalog(db, pid, aid)
        db.execute(update(t.media_catalog).where(c.asset_id == aid).values(latest_generation=c.latest_generation))
        row = catalog(db, pid, aid)
        operation = f"material-analysis:{aid}"
        previous = db.execute(select(i.response).where(i.user_id == uid, i.key == idempotency_key,
                              i.operation == operation)).scalar()
        if previous is not None:
            return previous
        result = asset_view(db, row)
        if result["latest"]["stage"] in PENDING:
            raise RuleError("VERSION_CONFLICT", "This material already has an analysis in progress")
        gen = row["latest_generation"] + 1
        run_id = enqueue(db, pid, aid, gen)
        db.execute(update(t.media_catalog).where(c.asset_id == aid).values(latest_generation=gen))
        response = {"analysis_run_id": run_id, "generation": gen}
        db.execute(insert(t.idempotency).values(user_id=uid, operation=operation, key=idempotency_key,
                                                request_hash=digest({"asset_id": aid}), response=response))
        return response

    def rows_for(pid):
        s, a, o, r, c, obj = [table.c for table in (t.segments, t.assets, t.media_observations,
                                                  t.media_runs, t.media_catalog, t.objects)]
        return select(t.segments, t.media_observations, a.sha256, a.duration_ms, a.license_info, r.result,
                      c.name, c.active_analysis_id, obj.storage_key).select_from(t.segments.join(t.media_observations,
                      and_(o.segment_id == s.id, o.project_id == s.project_id)).join(t.assets,
                      and_(a.id == s.asset_id, a.project_id == s.project_id)).join(t.media_runs,
                      and_(r.id == s.analysis_run_id, r.asset_id == s.asset_id, r.project_id == s.project_id)).join(
                      t.media_catalog, and_(c.asset_id == s.asset_id, c.project_id == s.project_id)).join(t.objects,
                      and_(obj.id == a.original_object_id, obj.project_id == a.project_id))).where(
                      s.project_id == pid, r.stage == "succeeded")

    def tags_for(db, pid, ids):
        tags = {}
        tgs = t.media_tags.c
        for offset in range(0, len(ids), 500):
            rows = db.execute(select(tgs.segment_id, tgs.label).where(tgs.project_id == pid,
                              tgs.segment_id.in_(ids[offset:offset + 500])).order_by(tgs.label))
            for segment_id, label in rows:
                tags.setdefault(segment_id, []).append(label)
        return tags

    def candidate(row, labels, score=0, fields=()):
        return MaterialCandidate(id=row["id"], project_id=row["project_id"], name=row["name"],
            source_and_rights=row["license_info"]["source_and_rights"],
            asset_id=row["asset_id"], analysis_run_id=row["analysis_run_id"], in_ms=row["in_ms"],
            out_ms=row["out_ms"], source_sha256=row["sha256"], analysis_content_hash=row["result"]["content_hash"],
            frame_ms=row["frame_ms"], speech=row["transcript"], signals=row["signals"], human_tags=labels,
            matched_fields=list(fields), score=score)

    @router.get("/search", response_model=MaterialSearch)
    def search(project_id: UUID, q: str = Query(default="", max_length=120), asset_id: UUID | None = None,
               from_ms: int | None = Query(default=None, ge=0), to_ms: int | None = Query(default=None, gt=0),
               limit: int = Query(default=20, ge=1, le=50), uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid)
        pid, s = str(project_id), t.segments.c
        if from_ms is not None and to_ms is not None and from_ms >= to_ms:
            raise RuleError("INVALID_ARGUMENT", "Search interval is empty or reversed")
        stmt = rows_for(pid).where(s.analysis_run_id == t.media_catalog.c.active_analysis_id)
        if asset_id:
            catalog(db, pid, str(asset_id))
            stmt = stmt.where(s.asset_id == str(asset_id))
        if from_ms is not None:
            stmt = stmt.where(s.out_ms > from_ms)
        if to_ms is not None:
            stmt = stmt.where(s.in_ms < to_ms)
        rows = db.execute(stmt).mappings().all()
        available = {key: object_path(root, key).is_file() for key in {row["storage_key"] for row in rows}}
        rows = [row for row in rows if available[row["storage_key"]]]
        labels = tags_for(db, pid, [row["id"] for row in rows])
        matches = []
        for row in rows:
            human = labels.get(row["id"], [])
            score, fields = keyword_rank(q, [utterance["text"] for utterance in row["transcript"]], human)
            if not q.strip() or score:
                matches.append((row, human, score, fields))
        matches.sort(key=lambda x: (-x[2], x[0]["name"], x[0]["asset_id"], x[0]["in_ms"], x[0]["id"]))
        return MaterialSearch(candidates=[candidate(*match) for match in matches[:limit]])

    def get_segment(db, pid, sid):
        row = db.execute(rows_for(pid).where(t.segments.c.id == sid)).mappings().first()
        if not row:
            raise RuleError("NOT_FOUND", "Published segment not found")
        return row

    @router.get("/segments/{segment_id}", response_model=MaterialCandidate)
    def segment(project_id: UUID, segment_id: UUID, uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid)
        pid, sid = str(project_id), str(segment_id)
        return candidate(get_segment(db, pid, sid), tags_for(db, pid, [sid]).get(sid, []))

    @router.post("/segments/{segment_id}/tags", response_model=MaterialCandidate)
    def tag(project_id: UUID, segment_id: UUID, body: HumanTag, uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid, write=True)
        pid, sid, label = str(project_id), str(segment_id), body.label.strip()
        row = get_segment(db, pid, sid)
        if not label or row["analysis_run_id"] != row["active_analysis_id"]:
            raise RuleError("INVALID_ARGUMENT", "Provide a tag for an active segment")
        c = t.media_catalog.c
        db.execute(update(t.media_catalog).where(c.asset_id == row["asset_id"]).values(latest_generation=c.latest_generation))
        if get_segment(db, pid, sid)["active_analysis_id"] != row["analysis_run_id"]:
            raise RuleError("VERSION_CONFLICT", "Material was reanalyzed")
        labels = tags_for(db, pid, [sid]).get(sid, [])
        if label not in labels:
            if len(labels) >= 20:
                raise RuleError("INVALID_ARGUMENT", "A segment supports up to 20 human tags")
            try:
                with db.begin_nested():
                    db.execute(insert(t.media_tags).values(id=str(uuid4()), project_id=pid, segment_id=sid, label=label))
            except IntegrityError:
                if label not in tags_for(db, pid, [sid]).get(sid, []):
                    raise
            labels = sorted([*labels, label])
        return candidate(row, labels)

    def file_response(key, mime):
        path = object_path(root, key)
        if not path.is_file():
            raise RuleError("NOT_FOUND", "Media object is unavailable")
        return FileResponse(path, media_type=mime, headers={"X-Content-Type-Options": "nosniff"})

    @router.get("/segments/{segment_id}/frame", response_class=FileResponse, responses={
        200: {"content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}},
    })
    def frame(project_id: UUID, segment_id: UUID, uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid)
        return file_response(get_segment(db, str(project_id), str(segment_id))["frame_key"], "image/jpeg")

    @router.get("/analyses/{analysis_run_id}/preview", response_class=FileResponse, responses={
        200: {"content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}}},
        206: {"description": "Partial Content", "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}}},
    })
    def preview(project_id: UUID, analysis_run_id: UUID, uid=Depends(user), db=Depends(db_session)):
        access(db, project_id, uid)
        r = t.media_runs.c
        row = db.execute(select(r.result).where(r.project_id == str(project_id), r.id == str(analysis_run_id),
                         r.stage == "succeeded")).scalar()
        if not row:
            raise RuleError("NOT_FOUND", "Published media preview not found")
        return file_response(row["preview_key"], "video/mp4")

    @router.post("/evidence", response_model=EvidenceManifest)
    def evidence(project_id: UUID, body: MaterialEvidenceRequest, uid=Depends(user), db=Depends(db_session)):
        pid = str(project_id)
        access(db, project_id, uid, write=True)
        assets, segments, evidence, versions = {}, {}, {}, {}
        for binding in body.bindings:
            row = get_segment(db, pid, str(binding.segment_id))
            aid = row["asset_id"]
            version = (str(binding.analysis_run_id), row["result"]["content_hash"])
            if (row["analysis_run_id"] != version[0] or versions.get(aid, version) != version
                    or not row["in_ms"] <= binding.in_ms < binding.out_ms <= row["out_ms"]):
                raise RuleError("INVALID_ARGUMENT", "Evidence interval or analysis revision is inconsistent")
            obj = db.execute(select(t.objects.c.storage_key).join(t.assets, t.assets.c.original_object_id ==
                             t.objects.c.id).where(t.assets.c.id == aid, t.assets.c.project_id == pid)).scalar_one()
            if not object_path(root, obj).is_file():
                raise RuleError("NOT_FOUND", "Original media is unavailable")
            versions[aid] = version
            assets[aid] = Asset(id=aid, project_id=pid, media_type="video", sha256=row["sha256"],
                                duration_ms=row["duration_ms"])
            segments[row["id"]] = Segment(**{k: row[k] for k in ("id", "project_id", "asset_id", "analysis_run_id", "in_ms", "out_ms")})
            fields = binding.model_dump(mode="json", exclude={"reviewed"})
            fields["requirement_keys"] = sorted(fields["requirement_keys"])
            eid = str(uuid5(MEDIA_NAMESPACE, digest(fields)))
            evidence[eid] = Evidence(id=eid, project_id=pid, asset_id=aid, method="human_annotation", **fields)
        manifest = EvidenceManifest(project_id=pid, dataset_version="media-v1-" + digest(versions),
                                    assets=[assets[k] for k in sorted(assets)], segments=[segments[k] for k in sorted(segments)],
                                    evidence=[evidence[k] for k in sorted(evidence)])
        resolve_manifest(manifest)
        return manifest

    return router
