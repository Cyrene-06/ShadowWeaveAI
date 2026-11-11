"""Opt-in real PostgreSQL checks, isolated in a disposable random schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert, select, func
from sqlalchemy.exc import IntegrityError

from sw_api import db as tables
from sw_api.app import create_app


@pytest.fixture
def postgres():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for isolated real PostgreSQL checks")
    schema = "sw_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    config = Config("alembic.ini")
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    yield engine, config, schema
    engine.dispose()
    with admin.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    admin.dispose()


def test_migration_roundtrip_and_metadata(postgres):
    engine, config, _ = postgres
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        assert compare_metadata(MigrationContext.configure(conn), tables.metadata) == []
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(conn), tables.metadata) == []


def test_database_refuses_cross_project_source(postgres):
    engine, _, _ = postgres
    uid, p1, p2, oid = [str(uuid4()) for _ in range(4)]
    with engine.begin() as conn:
        conn.execute(
            insert(tables.users).values(
                id=uid, email=uid + "@example.test", password_hash="test", display_name="Test"
            )
        )
        for pid in (p1, p2):
            conn.execute(insert(tables.projects).values(id=pid, owner_id=uid, name="Test", scenario="campus"))
        conn.execute(
            insert(tables.objects).values(
                id=oid, project_id=p1, storage_key="synthetic", sha256="0" * 64, size_bytes=0
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(tables.assets).values(
                project_id=p2,
                original_object_id=oid,
                media_type="video",
                duration_ms=10,
                sha256="0" * 64,
                license_info={"kind": "synthetic"},
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(tables.objects).values(
                project_id=p1, storage_key="invalid", sha256="0" * 64, size_bytes=-1
            )
        )


def api_for(postgres, tmp_path, monkeypatch):
    engine, _, schema = postgres
    monkeypatch.setattr(tables, "get_engine", lambda url=None: engine)
    return create_app(artifact_dir=tmp_path, replay_enabled=True)


def identity(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": uuid4().hex + "@example.test",
            "password": "phase-one-test-password",
            "display_name": "Test",
            "client_kind": "mobile",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_concurrent_idempotency_and_seed(postgres, tmp_path, monkeypatch):
    app = api_for(postgres, tmp_path, monkeypatch)
    with TestClient(app) as client:
        headers = identity(client)

        def create(_):
            return client.post(
                "/api/v1/projects",
                headers={**headers, "Idempotency-Key": "same-concurrent-key"},
                json={"name": "Concurrent", "scenario": "campus"},
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(create, range(4)))
        assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
        ids = {r.json()["id"] for r in responses}
        assert len(ids) == 1
        prefix = "/api/v1/projects/" + ids.pop() + "/phase-one"
        with ThreadPoolExecutor(max_workers=4) as pool:
            seeded = list(pool.map(lambda _: client.post(prefix + "/seed", headers=headers), range(4)))
        assert all(r.status_code == 200 for r in seeded), [r.text for r in seeded]
        assert client.post(prefix + "/replay", headers=headers).json()["passed"]
    with postgres[0].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(tables.projects)) == 1
        assert conn.scalar(select(func.count()).select_from(tables.replay_datasets)) == 1


def test_failed_seed_rolls_back_all_references(postgres, tmp_path, monkeypatch):
    app = api_for(postgres, tmp_path, monkeypatch)
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = identity(client)
        project = client.post(
            "/api/v1/projects",
            headers={**headers, "Idempotency-Key": "rollback"},
            json={"name": "Rollback", "scenario": "campus"},
        ).json()
        prefix = "/api/v1/projects/" + project["id"] + "/phase-one"

        def fail(conn, cursor, statement, parameters, context, many):
            if statement.startswith("INSERT INTO assets"):
                raise RuntimeError("injected failure after dataset/object insert")

        event.listen(postgres[0], "before_cursor_execute", fail)
        try:
            assert client.post(prefix + "/seed", headers=headers).status_code == 500
        finally:
            event.remove(postgres[0], "before_cursor_execute", fail)
        with postgres[0].connect() as conn:
            assert conn.scalar(select(func.count()).select_from(tables.replay_datasets)) == 0
            assert conn.scalar(select(func.count()).select_from(tables.objects)) == 0
        assert client.post(prefix + "/seed", headers=headers).status_code == 200
