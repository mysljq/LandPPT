"""Local filesystem artifact storage backend."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import AsyncIterator, Optional
from urllib.parse import quote

from .base import ArtifactStorage


class LocalArtifactStorage(ArtifactStorage):
    backend_name = "local"

    def __init__(self, root: str, public_base_url: Optional[str] = None):
        self.root = Path(root).resolve()
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root != candidate and self.root not in candidate.parents:
            raise ValueError("Storage key escapes local storage root")
        return candidate

    async def put_file(
        self,
        local_path: str,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        target = self._path_for_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, local_path, target)
        return key

    async def put_bytes(
        self,
        data: bytes,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        target = self._path_for_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)
        return key

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._path_for_key(key)
        with path.open("rb") as file_obj:
            while True:
                chunk = await asyncio.to_thread(file_obj.read, 1024 * 1024)
                if not chunk:
                    break
                yield chunk

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path_for_key(key).is_file)

    async def delete(self, key: str) -> None:
        path = self._path_for_key(key)
        if await asyncio.to_thread(path.exists):
            await asyncio.to_thread(path.unlink)

    async def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        if not self.public_base_url:
            raise ValueError("LOCAL_STORAGE_PUBLIC_BASE_URL is not configured")
        return f"{self.public_base_url}/{quote(key, safe='/')}"
