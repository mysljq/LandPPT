"""Artifact metadata and storage orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import delete, func, select

from ...core.config import app_config
from ...database.database import AsyncSessionLocal
from ...database.models import Artifact
from .base import ArtifactStorage
from .factory import get_artifact_storage


class ArtifactService:
    """Save files to storage and persist artifact metadata."""

    def __init__(self, storage: Optional[ArtifactStorage] = None):
        self.storage = storage or get_artifact_storage()

    async def save_file(
        self,
        *,
        local_path: str,
        user_id: int,
        artifact_type: str,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        expires_at: Optional[float] = None,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> Artifact:
        source = Path(local_path)
        if not await asyncio.to_thread(source.is_file):
            raise FileNotFoundError(local_path)

        artifact_id = str(uuid.uuid4())
        final_filename = filename or source.name
        detected_content_type = content_type or mimetypes.guess_type(final_filename)[0]
        storage_key = self.build_key(
            user_id=user_id,
            project_id=project_id,
            task_id=task_id or artifact_id,
            artifact_type=artifact_type,
            filename=final_filename,
        )
        size_bytes = await asyncio.to_thread(source.stat)
        checksum = await asyncio.to_thread(self._sha256_file, source)

        await self.storage.put_file(
            str(source),
            storage_key,
            content_type=detected_content_type,
            metadata={
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
            },
        )

        now = time.time()
        artifact = Artifact(
            id=artifact_id,
            user_id=user_id,
            project_id=project_id,
            task_id=task_id,
            artifact_type=artifact_type,
            storage_backend=self.storage.backend_name,
            storage_key=storage_key,
            filename=final_filename,
            content_type=detected_content_type,
            size_bytes=int(size_bytes.st_size),
            checksum_sha256=checksum,
            metadata_json=metadata_json,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        async with AsyncSessionLocal() as session:
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)
            return artifact

    async def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Artifact).where(Artifact.id == artifact_id))
            return result.scalar_one_or_none()

    async def get_task_artifact(
        self,
        task_id: str,
        artifact_type: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Optional[Artifact]:
        stmt = select(Artifact).where(Artifact.task_id == task_id).order_by(Artifact.created_at.desc())
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        if user_id is not None:
            stmt = stmt.where(Artifact.user_id == user_id)
        async with AsyncSessionLocal() as session:
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_task_artifacts(self, task_id: str, artifact_type: Optional[str] = None) -> list[Artifact]:
        stmt = select(Artifact).where(Artifact.task_id == task_id).order_by(Artifact.created_at.desc())
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        async with AsyncSessionLocal() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_artifacts(
        self,
        *,
        artifact_type: Optional[str] = None,
        user_id: Optional[int] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order_desc: bool = True,
    ) -> list[Artifact]:
        stmt = select(Artifact)
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        if user_id is not None:
            stmt = stmt.where(Artifact.user_id == user_id)
        stmt = stmt.order_by(Artifact.created_at.desc() if order_desc else Artifact.created_at.asc())
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        async with AsyncSessionLocal() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count_artifacts(self, *, artifact_type: Optional[str] = None, user_id: Optional[int] = None) -> int:
        stmt = select(func.count(Artifact.id))
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        if user_id is not None:
            stmt = stmt.where(Artifact.user_id == user_id)
        async with AsyncSessionLocal() as session:
            result = await session.execute(stmt)
            return int(result.scalar() or 0)

    async def update_artifact_metadata(
        self,
        artifact_id: str,
        *,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> Optional[Artifact]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Artifact).where(Artifact.id == artifact_id))
            artifact = result.scalar_one_or_none()
            if not artifact:
                return None
            artifact.metadata_json = metadata_json
            artifact.updated_at = time.time()
            await session.commit()
            await session.refresh(artifact)
            return artifact

    async def delete_artifact(self, artifact: Artifact) -> None:
        """Delete both the storage object and the metadata row."""
        await self.storage.delete(artifact.storage_key)
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Artifact).where(Artifact.id == artifact.id))
            await session.commit()

    async def delete_task_artifacts(
        self,
        task_id: str,
        *,
        artifact_type: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> int:
        artifacts = []
        stmt = select(Artifact).where(Artifact.task_id == task_id)
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        if user_id is not None:
            stmt = stmt.where(Artifact.user_id == user_id)
        async with AsyncSessionLocal() as session:
            result = await session.execute(stmt)
            artifacts = list(result.scalars().all())

        deleted_count = 0
        for artifact in artifacts:
            await self.delete_artifact(artifact)
            deleted_count += 1
        return deleted_count

    async def delete_artifacts(
        self,
        *,
        artifact_type: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> int:
        artifacts = await self.list_artifacts(artifact_type=artifact_type, user_id=user_id, limit=None)
        deleted_count = 0
        for artifact in artifacts:
            await self.delete_artifact(artifact)
            deleted_count += 1
        return deleted_count

    async def open_stream(self, artifact: Artifact):
        async for chunk in self.storage.open_stream(artifact.storage_key):
            yield chunk

    async def presigned_url(self, artifact: Artifact, expires_seconds: Optional[int] = None) -> str:
        return await self.storage.presigned_url(
            artifact.storage_key,
            expires_seconds or app_config.s3_presigned_url_expires_seconds,
        )

    @staticmethod
    def build_key(
        *,
        user_id: int,
        project_id: Optional[str],
        task_id: str,
        artifact_type: str,
        filename: str,
    ) -> str:
        safe_filename = os.path.basename(filename).replace("\\", "_").replace("/", "_")
        if project_id:
            return f"users/{user_id}/projects/{project_id}/exports/{task_id}/{safe_filename}"
        return f"users/{user_id}/artifacts/{artifact_type}/{task_id}/{safe_filename}"

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def get_artifact_service() -> ArtifactService:
    return ArtifactService()
