"""Storage backend factory."""

from __future__ import annotations

from functools import lru_cache

from ...core.config import app_config
from .base import ArtifactStorage
from .local_storage import LocalArtifactStorage
from .s3_storage import S3ArtifactStorage


@lru_cache(maxsize=1)
def get_artifact_storage() -> ArtifactStorage:
    backend = (app_config.storage_backend or "local").lower().strip()
    if backend == "local":
        return LocalArtifactStorage(
            root=app_config.local_storage_root,
            public_base_url=app_config.local_storage_public_base_url,
        )
    if backend in {"s3", "minio"}:
        return S3ArtifactStorage(
            endpoint_url=app_config.s3_endpoint_url,
            region=app_config.s3_region,
            bucket=app_config.s3_bucket,
            access_key_id=app_config.s3_access_key_id,
            secret_access_key=app_config.s3_secret_access_key,
            force_path_style=app_config.s3_force_path_style,
            public_base_url=app_config.s3_public_base_url,
        )
    raise ValueError(f"Unsupported STORAGE_BACKEND: {app_config.storage_backend}")
