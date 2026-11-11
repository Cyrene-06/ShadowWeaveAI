from __future__ import annotations

import json
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import jwt
from fastapi import FastAPI, Depends, Request, Response, Header, UploadFile, File
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import Field
from sqlalchemy import select, insert, update, or_
from sqlalchemy.exc import IntegrityError

from sw_contracts import Contract, Project, EvidenceManifest, ErrorEnvelope, digest
from sw_contracts.validation import RuleError, resolve_manifest
from . import db as tables
from .auth import passwords, verify_password, issue_tokens, token_hash

ROOT = Path(__file__).resolve().parents[4]


class Login(Contract):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    client_kind: str = Field(default="web", pattern="^(web|mobile)$")


class Register(Login):
    display_name: str = Field(min_length=1, max_length=80)


class Refresh(Contract):
    refresh_token: str | None = None


class NewProject(Contract):
    name: str = Field(min_length=1, max_length=120)
    scenario: str = Field(pattern="^(campus|travel|family_friends|vlog|organization)$")


def create_app(database_url=None, artifact_dir=None, replay_enabled=None):
    artifact_dir = Path(artifact_dir or os.environ.get("ARTIFACT_DIR", ROOT / "artifacts"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    engine = tables.get_engine(database_url)
    enabled = (
        replay_enabled
        if replay_enabled is not None
        else os.environ.get("ENABLE_PHASE_ONE_REPLAY", "false") == "true"
    )
    if os.environ.get("APP_ENV") == "production" and enabled:
        raise RuntimeError("phase-one replay must not be enabled in production")
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        if os.environ.get("APP_ENV") == "production":
            raise RuntimeError("JWT_SECRET is required in production")
        secret_path = artifact_dir / "jwt-secret.txt"
        try:
            with secret_path.open("x", encoding="utf-8") as f:
                f.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
        secret = secret_path.read_text(encoding="utf-8")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters")
    origins = os.environ.get(
        "WEB_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    app = FastAPI(
        title="ShadowWeaveAI Phase One",
        version="0.1.0",
        responses={code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 413, 422, 429, 503)},
    )
    app.state.engine = engine
    app.state.artifact_dir = artifact_dir
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    attempts = defaultdict(deque)

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def error(request, status, code, message):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message, "retryable": status in {429, 503}, "details": []},
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RuleError)
    async def rule_error(request, exc):
        status = {
            "UNAUTHENTICATED": 401,
            "FORBIDDEN": 403,
            "NOT_FOUND": 404,
            "VERSION_CONFLICT": 409,
            "IDEMPOTENCY_CONFLICT": 409,
            "RATE_LIMITED": 429,
            "FILE_TOO_LARGE": 413,
            "DEPENDENCY_UNAVAILABLE": 503,
        }.get(exc.code, 422)
        return error(request, status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Do not echo the body: it may contain passwords or tokens.
        return error(request, 422, "INVALID_ARGUMENT", "Request does not match the published contract")

    def db_session():
        with tables.session(engine) as db:
            yield db

    def user(request: Request, db=Depends(db_session)):
        header = request.headers.get("Authorization", "")
        try:
            if not header.startswith("Bearer "):
                raise ValueError()
            claims = jwt.decode(
                header[7:], secret, algorithms=["HS256"], audience="shadowweave-api", issuer="shadowweave"
            )
            uid = str(UUID(claims["sub"]))
        except (jwt.PyJWTError, ValueError, KeyError):
            raise RuleError("UNAUTHENTICATED", "A valid access token is required")
        if not db.execute(select(tables.users.c.id).where(tables.users.c.id == uid)).first():
            raise RuleError("UNAUTHENTICATED", "User does not exist")
        return uid

    def project_access(db, project_id, uid, write=False):
        project_id = str(project_id)
        project = (
            db.execute(select(tables.projects).where(tables.projects.c.id == project_id)).mappings().first()
        )
        membership = db.execute(
            select(tables.members.c.role).where(
                tables.members.c.project_id == project_id, tables.members.c.user_id == uid
            )
        ).scalar()
        if not project or (project["owner_id"] != uid and not membership):
            raise RuleError("NOT_FOUND", "Project not found")
        if write and project["owner_id"] != uid and membership != "editor":
            raise RuleError("FORBIDDEN", "Project is read-only")
        return project

    def limit(request):
        key = request.client.host if request.client else "unknown"
        current = time.monotonic()
        queue = attempts[key]
        while queue and current - queue[0] > 60:
            queue.popleft()
        if len(queue) >= 20:
            raise RuleError("RATE_LIMITED", "Too many authentication attempts")
        queue.append(current)

    def tokens_response(db, row, kind, response, family=None):
        body, refresh = issue_tokens(db, row["id"], kind, secret, family)
        body["user"] = {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}
        if kind == "web":
            response.set_cookie(
                "sw_refresh",
                refresh,
                httponly=True,
                secure=os.environ.get("APP_ENV") == "production",
                samesite="strict",
                max_age=604800,
                path="/api/v1/auth",
            )
        else:
            body["refresh_token"] = refresh
        return body

    @app.get("/api/v1/health")
    def health(db=Depends(db_session)):
        db.execute(select(tables.users.c.id).limit(1))
        return {"status": "ok", "schema_version": "1.0", "mode": "phase_one", "replay_enabled": enabled}

    @app.post("/api/v1/auth/register", status_code=201)
    def register(body: Register, response: Response, request: Request, db=Depends(db_session)):
        limit(request)
        email = body.email.strip().lower()
        if "@" not in email:
            raise RuleError("INVALID_ARGUMENT", "Invalid email")
        if db.execute(select(tables.users.c.id).where(tables.users.c.email == email)).first():
            raise RuleError("IDEMPOTENCY_CONFLICT", "Email already registered")
        row = dict(
            id=str(uuid4()),
            email=email,
            password_hash=passwords.hash(body.password),
            display_name=body.display_name,
        )
        db.execute(insert(tables.users).values(**row))
        return tokens_response(db, row, body.client_kind, response)

    @app.post("/api/v1/auth/login")
    def login(body: Login, response: Response, request: Request, db=Depends(db_session)):
        limit(request)
        row = (
            db.execute(select(tables.users).where(tables.users.c.email == body.email.strip().lower()))
            .mappings()
            .first()
        )
        if not row or not verify_password(row["password_hash"], body.password):
            raise RuleError("UNAUTHENTICATED", "Invalid email or password")
        return tokens_response(db, row, body.client_kind, response)

    def refresh_session(request, body, db):
        raw = body.refresh_token or request.cookies.get("sw_refresh")
        if not raw:
            raise RuleError("UNAUTHENTICATED", "Refresh token required")
        if body.refresh_token is None and request.headers.get("Origin") not in origins:
            raise RuleError("FORBIDDEN", "Cookie refresh requires a trusted Origin")
        row = (
            db.execute(
                select(tables.sessions)
                .where(tables.sessions.c.token_hash == token_hash(raw))
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if not row:
            raise RuleError("UNAUTHENTICATED", "Invalid refresh token")
        return row

    @app.post("/api/v1/auth/refresh")
    def refresh(body: Refresh, response: Response, request: Request, db=Depends(db_session)):
        limit(request)
        row = refresh_session(request, body, db)
        current = tables.now()
        if row["revoked_at"] or row["expires_at"].replace(tzinfo=timezone.utc) <= current:
            db.execute(
                update(tables.sessions)
                .where(tables.sessions.c.family_id == row["family_id"])
                .values(revoked_at=current)
            )
            db.commit()  # Persist family revocation even though the request fails.
            raise RuleError("UNAUTHENTICATED", "Refresh expired or reused; session family revoked")
        db.execute(
            update(tables.sessions).where(tables.sessions.c.id == row["id"]).values(revoked_at=current)
        )
        owner = db.execute(select(tables.users).where(tables.users.c.id == row["user_id"])).mappings().one()
        return tokens_response(db, owner, row["client_kind"], response, row["family_id"])

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(body: Refresh, response: Response, request: Request, db=Depends(db_session)):
        row = refresh_session(request, body, db)
        db.execute(
            update(tables.sessions)
            .where(tables.sessions.c.family_id == row["family_id"])
            .values(revoked_at=tables.now())
        )
        response.delete_cookie("sw_refresh", path="/api/v1/auth")

    def project_view(row):
        return Project.model_validate({k: row[k] for k in Project.model_fields})

    @app.get("/api/v1/projects", response_model=list[Project])
    def list_projects(uid=Depends(user), db=Depends(db_session)):
        ids = select(tables.members.c.project_id).where(tables.members.c.user_id == uid)
        rows = (
            db.execute(
                select(tables.projects)
                .where(or_(tables.projects.c.owner_id == uid, tables.projects.c.id.in_(ids)))
                .order_by(tables.projects.c.created_at, tables.projects.c.id)
                .limit(100)
            )
            .mappings()
            .all()
        )
        return [project_view(row) for row in rows]

    @app.post("/api/v1/projects", response_model=Project, status_code=201)
    def new_project(
        body: NewProject,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        uid=Depends(user),
        db=Depends(db_session),
    ):
        where = (
            tables.idempotency.c.user_id == uid,
            tables.idempotency.c.operation == "create_project",
            tables.idempotency.c.key == key,
        )
        prior = db.execute(select(tables.idempotency).where(*where)).mappings().first()
        if prior:
            if prior["request_hash"] != digest(body):
                raise RuleError("IDEMPOTENCY_CONFLICT", "Key reused for a different request")
            return prior["response"]
        row = dict(id=str(uuid4()), owner_id=uid, **body.model_dump(), revision=1, head_revision=0)
        try:
            with db.begin_nested():
                db.execute(insert(tables.projects).values(**row))
                result = project_view(row).model_dump(mode="json")
                db.execute(
                    insert(tables.idempotency).values(
                        user_id=uid,
                        operation="create_project",
                        key=key,
                        request_hash=digest(body),
                        response=result,
                    )
                )
            return result
        except IntegrityError:
            prior = db.execute(select(tables.idempotency).where(*where)).mappings().one()
            if prior["request_hash"] != digest(body):
                raise RuleError("IDEMPOTENCY_CONFLICT", "Concurrent request differs")
            return prior["response"]

    @app.get("/api/v1/projects/{project_id}", response_model=Project)
    def read_project(project_id: UUID, uid=Depends(user), db=Depends(db_session)):
        return project_view(project_access(db, project_id, uid))

    if enabled:

        def stored_bundle(db, project_id):
            value = db.execute(
                select(tables.replay_datasets.c.bundle).where(
                    tables.replay_datasets.c.project_id == str(project_id)
                )
            ).scalar_one_or_none()
            if value is None:
                raise RuleError("NOT_FOUND", "Seed the phase-one dataset first")
            return value

        @app.post("/api/v1/projects/{project_id}/phase-one/seed")
        def seed(project_id: UUID, uid=Depends(user), db=Depends(db_session)):
            project_access(db, project_id, uid, True)
            prior = (
                db.execute(
                    select(tables.replay_datasets).where(
                        tables.replay_datasets.c.project_id == str(project_id)
                    )
                )
                .mappings()
                .first()
            )
            if prior:
                return {
                    "mode": "fixed_input",
                    "seeded": True,
                    "dataset_version": prior["bundle"]["dataset_version"],
                }
            raw = json.loads((ROOT / "examples/phase-1/campus.json").read_text(encoding="utf-8"))
            old = raw["manifest"]["project_id"]

            def remap(value):
                if isinstance(value, str):
                    if value == old:
                        return str(project_id)
                    try:
                        return str(uuid5(project_id, value)) if str(UUID(value)) == value else value
                    except ValueError:
                        return value
                if isinstance(value, list):
                    return [remap(v) for v in value]
                if isinstance(value, dict):
                    return {k: remap(v) for k, v in value.items()}
                return value

            bundle = remap(raw)
            manifest = EvidenceManifest.model_validate(bundle["manifest"])
            resolve_manifest(manifest)
            try:
                with db.begin_nested():
                    # Claim a unique project dataset before adding references, all in the same transaction.
                    db.execute(
                        insert(tables.replay_datasets).values(project_id=str(project_id), bundle=bundle)
                    )
                    for asset in manifest.assets:
                        obj = str(uuid4())
                        payload = asset.model_dump(mode="json")
                        db.execute(
                            insert(tables.objects).values(
                                id=obj,
                                project_id=str(project_id),
                                storage_key="fixture://human-annotation/" + str(asset.id),
                                sha256=digest(payload),
                                size_bytes=len(json.dumps(payload).encode("utf-8")),
                            )
                        )
                        db.execute(
                            insert(tables.assets).values(
                                id=str(asset.id),
                                project_id=str(project_id),
                                original_object_id=obj,
                                media_type=asset.media_type,
                                duration_ms=asset.duration_ms,
                                sha256=asset.sha256,
                                license_info=bundle["provenance"],
                            )
                        )
                    for aid in {segment.analysis_run_id for segment in manifest.segments}:
                        segment = next(
                            segment for segment in manifest.segments if segment.analysis_run_id == aid
                        )
                        job = str(uuid4())
                        db.execute(
                            insert(tables.jobs).values(id=job, project_id=str(project_id), state="succeeded")
                        )
                        db.execute(
                            insert(tables.analyses).values(
                                id=str(aid),
                                project_id=str(project_id),
                                asset_id=str(segment.asset_id),
                                root_job_id=job,
                                state="succeeded",
                                config_hash=digest({"method": "human_annotation"}),
                                config_snapshot={"method": "human_annotation", "mode": "fixed_input"},
                            )
                        )
                    for segment in manifest.segments:
                        db.execute(insert(tables.segments).values(**segment.model_dump(mode="json")))
            except IntegrityError:
                # Only a concurrent committed dataset can turn a collision into success.
                existing = db.execute(
                    select(tables.replay_datasets.c.bundle).where(
                        tables.replay_datasets.c.project_id == str(project_id)
                    )
                ).scalar_one_or_none()
                if existing is None:
                    raise
            return {"mode": "fixed_input", "seeded": True, "dataset_version": bundle["dataset_version"]}

        @app.get("/api/v1/projects/{project_id}/phase-one")
        def bundle(project_id: UUID, uid=Depends(user), db=Depends(db_session)):
            project_access(db, project_id, uid)
            return stored_bundle(db, project_id)

        @app.post("/api/v1/projects/{project_id}/phase-one/replay")
        def replay(project_id: UUID, uid=Depends(user), db=Depends(db_session)):
            project_access(db, project_id, uid, True)
            from .replay import run_replay

            result = run_replay(stored_bundle(db, project_id))
            folder = artifact_dir / "projects" / str(project_id)
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / (str(uuid4()) + "-run.json")
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return jsonable_encoder(result)

        @app.post("/api/v1/projects/{project_id}/phase-one/validate-evidence")
        def evidence(project_id: UUID, manifest: EvidenceManifest, uid=Depends(user), db=Depends(db_session)):
            project_access(db, project_id, uid, True)
            if str(manifest.project_id) != str(project_id):
                raise RuleError("FORBIDDEN", "Manifest belongs to another project")
            resolve_manifest(manifest)
            for segment in manifest.segments:
                row = (
                    db.execute(
                        select(tables.segments).where(
                            tables.segments.c.id == str(segment.id),
                            tables.segments.c.project_id == str(project_id),
                        )
                    )
                    .mappings()
                    .first()
                )
                if not row or any(str(row[k]) != str(v) for k, v in segment.model_dump().items()):
                    raise RuleError("INVALID_ARGUMENT", "Evidence references unregistered or altered source")
                state = db.execute(
                    select(tables.analyses.c.state).where(
                        tables.analyses.c.id == str(segment.analysis_run_id),
                        tables.analyses.c.project_id == str(project_id),
                        tables.analyses.c.asset_id == str(segment.asset_id),
                    )
                ).scalar_one_or_none()
                if state != "succeeded":
                    raise RuleError("INVALID_ARGUMENT", "Analysis has not succeeded")
            for asset in manifest.assets:
                row = (
                    db.execute(
                        select(tables.assets).where(
                            tables.assets.c.id == str(asset.id), tables.assets.c.project_id == str(project_id)
                        )
                    )
                    .mappings()
                    .first()
                )
                if (
                    not row
                    or row["duration_ms"] != asset.duration_ms
                    or row["sha256"] != asset.sha256
                    or row["media_type"] != asset.media_type
                ):
                    raise RuleError("INVALID_ARGUMENT", "Asset differs from registered source")
            return {"valid": True, "manifest_hash": digest(manifest)}

        @app.post("/api/v1/projects/{project_id}/phase-one/media-probe")
        async def media_probe(
            project_id: UUID, upload: UploadFile = File(), uid=Depends(user), db=Depends(db_session)
        ):
            project_access(db, project_id, uid, True)
            folder = artifact_dir / "media" / str(project_id)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (str(uuid4()) + ".upload")
            size = 0
            try:
                with path.open("wb") as f:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        if size > 16 * 1024 * 1024:
                            raise RuleError("FILE_TOO_LARGE", "Probe limit is 16 MiB")
                        f.write(chunk)
                from sw_media.tools import probe

                result = await run_in_threadpool(probe, path)
                return {
                    "mode": "real_media_probe",
                    "size_bytes": size,
                    "probe": result,
                    "capture_fulfilled": False,
                }
            finally:
                path.unlink(missing_ok=True)
                await upload.close()

    return app


app = create_app()
