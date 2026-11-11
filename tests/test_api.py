from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, func, update
from sw_api.app import create_app
from sw_api import db as tables


@pytest.fixture
def api(tmp_path):
    app = create_app("sqlite:///" + (tmp_path / "db.sqlite3").as_posix(), tmp_path / "artifacts", True)
    tables.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        yield client, app
    app.state.engine.dispose()


def register(client, email="one@example.test", kind="mobile"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "phase-one-test-password",
            "display_name": "Test",
            "client_kind": kind,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body, {"Authorization": "Bearer " + body["access_token"]}


def project(client, headers, key="create-1"):
    response = client.post(
        "/api/v1/projects",
        headers={**headers, "Idempotency-Key": key},
        json={"name": "Campus", "scenario": "campus"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_persistent_projects_idempotency_and_scope(api):
    client, app = api
    user, headers = register(client)
    created = project(client, headers)
    assert project(client, headers) == created
    other = client.post(
        "/api/v1/projects",
        headers={**headers, "Idempotency-Key": "create-1"},
        json={"name": "Other", "scenario": "campus"},
    )
    assert other.status_code == 409
    assert client.get("/api/v1/projects", headers=headers).json() == [created]
    assert client.get("/api/v1/projects/" + created["id"], headers=headers).json() == created
    restarted = create_app(str(app.state.engine.url), app.state.artifact_dir, True)
    with TestClient(restarted) as reader:
        assert reader.get("/api/v1/projects", headers=headers).json() == [created]
    restarted.state.engine.dispose()
    _, foreign = register(client, "two@example.test")
    assert client.get("/api/v1/projects/" + created["id"], headers=foreign).status_code == 404
    assert client.get("/api/v1/projects", headers=foreign).json() == []
    assert client.get("/api/v1/projects").status_code == 401


def test_seed_and_replay_are_real_rule_runs_and_transactional(api):
    client, app = api
    _, headers = register(client)
    created = project(client, headers)
    prefix = "/api/v1/projects/" + created["id"] + "/phase-one"
    assert client.get(prefix, headers=headers).status_code == 404
    assert client.post(prefix + "/seed", headers=headers).status_code == 200
    with tables.session(app.state.engine) as db:
        count = db.scalar(select(func.count()).select_from(tables.assets))
    assert client.post(prefix + "/seed", headers=headers).status_code == 200
    with tables.session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(tables.assets)) == count == 5
    bundle = client.get(prefix, headers=headers).json()
    assert bundle["manifest"]["project_id"] == created["id"]
    run = client.post(prefix + "/replay", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["passed"] and not run.json()["model_called"]
    assert list((app.state.artifact_dir / "projects" / created["id"]).glob("*-run.json"))
    assert (
        client.post(prefix + "/validate-evidence", headers=headers, json=bundle["manifest"]).status_code
        == 200
    )
    bundle["manifest"]["segments"][0]["analysis_run_id"] = str(uuid4())
    assert (
        client.post(prefix + "/validate-evidence", headers=headers, json=bundle["manifest"]).status_code
        == 422
    )
    _, foreign = register(client, "two@example.test")
    other = project(client, foreign)
    target = "/api/v1/projects/" + other["id"] + "/phase-one/validate-evidence"
    assert client.post(target, headers=foreign, json=bundle["manifest"]).status_code == 403


def test_membership_viewer_and_editor(api):
    client, app = api
    _, owner = register(client)
    created = project(client, owner)
    viewer, headers = register(client, "viewer@example.test")
    with tables.session(app.state.engine) as db:
        db.execute(
            insert(tables.members).values(
                project_id=created["id"], user_id=viewer["user"]["id"], role="viewer"
            )
        )
    prefix = "/api/v1/projects/" + created["id"]
    assert client.get(prefix, headers=headers).status_code == 200
    assert client.post(prefix + "/phase-one/seed", headers=headers).status_code == 403


def test_refresh_rotation_reuse_revokes_entire_family(api):
    client, _ = api
    body, headers = register(client)
    old = body["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != old
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old}).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
        ).status_code
        == 401
    )


def test_web_cookie_requires_origin_and_secrets_not_echoed(api):
    client, _ = api
    body, _ = register(client, kind="web")
    assert "refresh_token" not in body
    assert "HttpOnly" in str(client.cookies) or client.cookies.get("sw_refresh")
    assert client.post("/api/v1/auth/refresh", json={}).status_code == 403
    assert (
        client.post("/api/v1/auth/refresh", json={}, headers={"Origin": "http://localhost:5173"}).status_code
        == 200
    )
    secret = "SHOULD_NOT_APPEAR"
    invalid = client.post("/api/v1/auth/login", json={"email": "a", "password": secret, "extra": secret})
    assert invalid.status_code == 422
    assert secret not in invalid.text
    assert invalid.json()["request_id"] == invalid.headers["X-Request-ID"]
    assert invalid.headers["Cache-Control"] == "no-store"


def test_replay_is_disabled_by_default_and_forbidden_in_production(tmp_path, monkeypatch):
    monkeypatch.delenv("ENABLE_PHASE_ONE_REPLAY", raising=False)
    app = create_app("sqlite:///" + (tmp_path / "db.sqlite3").as_posix(), tmp_path / "artifacts")
    assert not any("phase-one" in route.path for route in app.routes)
    app.state.engine.dispose()
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="must not"):
        create_app("sqlite://", tmp_path / "prod", True)


def test_failed_registered_analysis_cannot_support_evidence(api):
    client, app = api
    _, headers = register(client)
    created = project(client, headers)
    prefix = "/api/v1/projects/" + created["id"] + "/phase-one"
    assert client.post(prefix + "/seed", headers=headers).status_code == 200
    bundle = client.get(prefix, headers=headers).json()
    with tables.session(app.state.engine) as db:
        db.execute(
            update(tables.analyses)
            .where(tables.analyses.c.project_id == created["id"])
            .values(state="failed")
        )
    response = client.post(prefix + "/validate-evidence", headers=headers, json=bundle["manifest"])
    assert response.status_code == 422
    assert "Analysis has not succeeded" in response.text
