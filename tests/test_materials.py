from io import StringIO
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import select

from sw_ai.coverage import evaluate_coverage
from sw_api import db as t
from sw_api.app import create_app
from sw_api.materials import keyword_rank
from sw_contracts import EvidenceManifest, StoryNode
from sw_media.analysis import ffmpeg, slice_intervals
from sw_worker import media_jobs as worker
from test_api import project, register


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "artifacts"
    app = create_app("sqlite:///" + (tmp_path / "media.sqlite3").as_posix(), root, False)
    cfg = Config("alembic.ini")
    with app.state.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        assert compare_metadata(MigrationContext.configure(conn), t.metadata) == []
    with TestClient(app) as client:
        _, headers = register(client)
        pid = project(client, headers)["id"]
        yield client, headers, pid, app
    app.state.engine.dispose()


def upload(client, headers, pid, content, name="clip.mp4", rights=True):
    return client.post(f"/api/v1/projects/{pid}/materials/assets", content=content,
                       params={"name": name, "source": "locally generated test fixture", "rights_confirmed": rights},
                       headers={**headers, "Content-Type": "application/octet-stream"})


def video_fixture(tmp_path, with_audio=False):
    path = tmp_path / ("sound.mp4" if with_audio else "silent.mp4")
    from sw_media.tools import binary, run

    args = [binary("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i", "color=s=320x180:d=1.5:c=blue"]
    if with_audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1.5", "-c:a", "aac"]
    run([*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    return path.read_bytes()


@pytest.mark.parametrize("dialect", ["sqlite:///artifacts/offline.db", "postgresql+psycopg://localhost/offline"])
def test_phase_two_offline_ddl(dialect):
    output = StringIO()
    cfg = Config("alembic.ini", output_buffer=output)
    cfg.set_main_option("sqlalchemy.url", dialect)
    command.upgrade(cfg, "head", sql=True)
    sql = output.getvalue()
    assert all(f"CREATE TABLE {table}" in sql for table in (
        "media_catalog", "media_runs", "media_observations", "media_tags",
    ))
    assert sql.index("CREATE TABLE assets") < sql.index("CREATE TABLE media_catalog")


def test_partition_and_keyword_baseline():
    intervals, mode = slice_intervals(22_000, [20_000, 0, 2, 22_000])
    assert intervals == [(0, 8000), (8000, 20_000), (20_000, 22_000)]
    assert mode == "scene_and_fixed"
    assert keyword_rank("词语", ["本地转写词语"], ["另一个标签"]) == (1, ["transcript"])
    assert keyword_rank("missing", ["spoken phrase"], []) == (0, [])
    assert worker.utterances_for([{"words": [{"in_ms": 900, "out_ms": 1100, "text": " here"}]}], 0, 1000) == []
    assert worker.utterances_for([{"words": [{"in_ms": 900, "out_ms": 1100, "text": " here"}]}], 1000, 2000) == [
        {"in_ms": 1000, "out_ms": 1100, "text": "here"},
    ]


def test_upload_analysis_search_preview_evidence_and_versions(sandbox, tmp_path):
    client, headers, pid, app = sandbox
    root = f"/api/v1/projects/{pid}/materials"
    bytes_ = video_fixture(tmp_path)
    env = (app.state.engine, app.state.artifact_dir)
    assert upload(client, headers, pid, bytes_, rights=False).status_code == 422
    assert upload(client, headers, pid, bytes_, name="../file.mp4").status_code == 422
    row = upload(client, headers, pid, bytes_).json()
    assert row["latest"]["stage"] == "queued"
    assert upload(client, headers, pid, bytes_, name="duplicate.mp4").json()["duplicate"]
    assert client.get(root + "/search", headers=headers).json()["candidates"] == []
    assert worker.process_one(*env)
    existing = client.get(root + "/assets", headers=headers).json()[0]
    assert existing["latest"]["result"]["speech"]["status"] == "not_applicable", existing
    old_run = existing["active_analysis_id"]
    old = client.get(root + "/search", headers=headers).json()["candidates"][0]
    route = root + "/segments/" + old["id"]
    assert old["semantic_support"] == "unknown"
    assert client.get(route + "/frame", headers=headers).headers["content-type"] == "image/jpeg"
    assert client.get(root + "/analyses/" + old_run + "/preview", headers={**headers, "Range": "bytes=0-9"}).status_code == 206
    _, stranger = register(client, "stranger@example.test")
    assert client.get(route + "/frame", headers=stranger).status_code == 404
    other_project = project(client, headers, key="other-project")["id"]
    other_root = f"/api/v1/projects/{other_project}/materials"
    assert client.get(other_root + "/segments/" + old["id"], headers=headers).status_code == 404
    assert client.post(route + "/tags", headers=headers, json={"label": "blue scene"}).status_code == 200
    q = client.get(root + "/search?q=blue", headers=headers).json()["candidates"]
    assert [x["matched_fields"] for x in q] == [["human_tag"]]
    assert client.get(root + "/search?q=zzzzz", headers=headers).json()["candidates"] == []
    assert client.get(root + "/search?from_ms=9999", headers=headers).json()["candidates"] == []
    binding = {"segment_id": old["id"], "analysis_run_id": old_run, "in_ms": old["in_ms"], "out_ms": old["out_ms"],
               "requirement_keys": ["blue"], "semantic_support": "supported", "quality_usable": True, "reviewed": True}

    def export(*bindings):
        return client.post(root + "/evidence", headers=headers, json={"bindings": bindings})

    snapshot = export(binding)
    assert snapshot.status_code == 200, snapshot.text
    manifest = EvidenceManifest.model_validate(snapshot.json())
    node = StoryNode(project_id=pid, node_key="blue", goal="Find a blue frame", requirements=["blue"], minimum_duration_ms=500)
    assert evaluate_coverage(node, manifest, True).coverage == "covered"
    assert export({**binding, "out_ms": old["out_ms"] + 1}).status_code == 422
    assert export({**binding, "analysis_run_id": str(uuid4())}).status_code == 422
    assert export({**binding, "reviewed": False}).status_code == 422
    retrigger = root + "/assets/" + old["asset_id"] + "/analyses"
    key = {**headers, "Idempotency-Key": "second"}
    second = client.post(retrigger, headers=key).json()
    assert client.post(retrigger, headers=key).json() == second
    assert client.post(retrigger, headers={**headers, "Idempotency-Key": "third"}).status_code == 409
    assert client.get(root + "/search?q=blue", headers=headers).json()["candidates"][0]["id"] == old["id"]
    assert worker.process_one(*env)
    fresh = client.get(root + "/search", headers=headers).json()["candidates"][0]
    assert fresh["analysis_run_id"] == second["analysis_run_id"] != old_run
    assert fresh["id"] != old["id"]
    assert client.get(root + "/search?q=blue", headers=headers).json()["candidates"] == []
    assert client.get(route, headers=headers).status_code == 200
    assert export(binding).json() == snapshot.json()
    assert export(binding, {**binding, "segment_id": fresh["id"], "analysis_run_id": fresh["analysis_run_id"]}).status_code == 422
    assert not worker.process_one(*env)


def test_failures_and_fenced_worker_recovery(sandbox, tmp_path, monkeypatch):
    client, headers, pid, app = sandbox
    root = f"/api/v1/projects/{pid}/materials"
    env = (app.state.engine, app.state.artifact_dir)
    bad = upload(client, headers, pid, b"not-a-video", "broken.mp4").json()
    assert worker.process_one(*env)
    assert client.get(root + "/assets", headers=headers).json()[0]["latest"]["error_code"] == "INVALID_MEDIA"
    sound = upload(client, headers, pid, video_fixture(tmp_path, with_audio=True), "sound.mp4").json()
    with t.session(app.state.engine) as db:
        assert db.execute(select(t.jobs.c.state).where(t.jobs.c.id == bad["latest"]["job_id"])).scalar_one() == "failed"
    abandoned = worker.claim(app.state.engine)
    assert abandoned["id"] == sound["latest"]["analysis_run_id"]
    assert worker.claim(app.state.engine) is None
    recovered = worker.claim(app.state.engine, at_ms=worker.clock() + worker.LEASE_MS + 10)
    assert recovered["id"] == abandoned["id"] and recovered["lease_token"] != abandoned["lease_token"]
    with t.session(app.state.engine) as db:
        assert not worker.update_owned(db, abandoned, stage="publish")
    worker.fail(app.state.engine, recovered, "WORKER_INTERRUPTED", {})
    retry = root + "/assets/" + sound["asset_id"] + "/analyses"
    assert client.post(retry, headers={**headers, "Idempotency-Key": "recover-sound"}).status_code == 202
    assert worker.process_one(*env)
    row = next(a for a in client.get(root + "/assets", headers=headers).json() if a["asset_id"] == sound["asset_id"])
    assert row["latest"]["error_code"] == "TRANSCRIPTION_NOT_CONFIGURED", row
    assert row["active_analysis_id"] is None


def test_delayed_audio_cannot_precede_its_track(tmp_path):
    """Validate timestamp-preserving WAV conversion on a delayed audio stream."""
    import wave
    from sw_media.tools import binary, run

    source, wav = tmp_path / "delay.mp4", tmp_path / "delay.wav"
    run([binary("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i", "color=s=160x120:d=3", "-itsoffset", "1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac", str(source)])
    ffmpeg(source, "-map", "0:a:0", "-vn", "-af", "aresample=async=1:first_pts=0", "-ac", "1", "-ar", "16000", wav,
           before=("-copyts", "-start_at_zero"))
    with wave.open(str(wav), "rb") as data:
        assert data.readframes(10_000) == b"\0" * 20_000
        assert data.readframes(20_000) != b"\0" * 40_000
