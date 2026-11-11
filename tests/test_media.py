import pytest
from fastapi.testclient import TestClient
from sw_api.app import create_app
from sw_api.db import metadata
from sw_media.tools import generate_probe_media, probe, decode_and_render
from sw_contracts.validation import RuleError


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp("media")
    source = folder / "own-video.mp4"
    generated = generate_probe_media(source)
    assert generated["duration_ms"] == 1000
    return source


def test_real_decode_and_render(media, tmp_path):
    report = decode_and_render(media, tmp_path / "render.mp4")
    assert 400 <= report["duration_ms"] <= 600
    assert any(
        s["codec_type"] == "video" and s["width"] == 1280 and s["height"] == 720 for s in report["streams"]
    )
    assert not report["model_called"]


def test_malformed_media_is_controlled_and_does_not_leak_paths(tmp_path):
    source = tmp_path / "private-name.mp4"
    source.write_bytes(b"not a video")
    with pytest.raises(RuleError, match="rejected") as failure:
        probe(source)
    assert str(tmp_path) not in str(failure.value)


def test_real_upload_probe_is_project_scoped_and_cannot_fulfill(media, tmp_path):
    app = create_app("sqlite:///" + (tmp_path / "db.sqlite3").as_posix(), tmp_path / "artifacts", True)
    metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        user = client.post(
            "/api/v1/auth/register",
            json={
                "email": "media@example.test",
                "password": "test-media-password",
                "display_name": "Media",
                "client_kind": "mobile",
            },
        ).json()
        headers = {"Authorization": "Bearer " + user["access_token"]}
        project = client.post(
            "/api/v1/projects",
            headers={**headers, "Idempotency-Key": "media"},
            json={"name": "Media", "scenario": "campus"},
        ).json()
        path = "/api/v1/projects/" + project["id"] + "/phase-one/media-probe"
        with media.open("rb") as content:
            response = client.post(
                path, headers=headers, files={"upload": ("../untrusted.mp4", content, "video/mp4")}
            )
        assert response.status_code == 200, response.text
        assert response.json()["probe"]["duration_ms"] == 1000
        assert not response.json()["capture_fulfilled"]
        assert not list((tmp_path / "artifacts/media").rglob("*.upload"))
        assert client.post(path, files={"upload": ("a.mp4", b"bad", "video/mp4")}).status_code == 401
        assert (
            client.post(path, headers=headers, files={"upload": ("a.mp4", b"bad", "video/mp4")}).status_code
            == 422
        )
        assert (
            client.post(
                path, headers=headers, files={"upload": ("a.mp4", b"x" * (16 * 1024 * 1024 + 1), "video/mp4")}
            ).status_code
            == 413
        )
    app.state.engine.dispose()
