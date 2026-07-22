import pytest


@pytest.mark.asyncio
async def test_local_artifact_storage_roundtrip(tmp_path):
    from landppt.services.storage.local_storage import LocalArtifactStorage

    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    storage = LocalArtifactStorage(str(tmp_path / "artifacts"), public_base_url="http://assets.local")

    key = await storage.put_file(str(source), "users/1/exports/task/source.txt", content_type="text/plain")

    assert key == "users/1/exports/task/source.txt"
    assert await storage.exists(key) is True
    chunks = []
    async for chunk in storage.open_stream(key):
        chunks.append(chunk)
    assert b"".join(chunks) == b"hello"
    assert await storage.presigned_url(key) == "http://assets.local/users/1/exports/task/source.txt"

    await storage.delete(key)
    assert await storage.exists(key) is False


def test_artifact_service_builds_project_export_key():
    from landppt.services.storage.artifact_service import ArtifactService

    key = ArtifactService.build_key(
        user_id=7,
        project_id="project-1",
        task_id="task-1",
        artifact_type="pdf_export",
        filename="deck.pdf",
    )

    assert key == "users/7/projects/project-1/exports/task-1/deck.pdf"


def test_s3_storage_uses_path_style_for_minio(monkeypatch):
    from landppt.services.storage.s3_storage import S3ArtifactStorage

    created = {}

    def fake_client(service_name, **kwargs):
        created["service_name"] = service_name
        created.update(kwargs)
        return object()

    monkeypatch.setattr("landppt.services.storage.s3_storage.boto3.client", fake_client)

    storage = S3ArtifactStorage(
        endpoint_url="http://minio:9000",
        region="us-east-1",
        bucket="landppt",
        access_key_id="minio",
        secret_access_key="secret",
        force_path_style=True,
    )

    assert storage.bucket == "landppt"
    assert created["service_name"] == "s3"
    assert created["endpoint_url"] == "http://minio:9000"
    assert created["aws_access_key_id"] == "minio"
