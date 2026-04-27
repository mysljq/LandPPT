"""Storage backend interface for generated artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class ArtifactStorage(ABC):
    """Abstract artifact storage backend."""

    backend_name: str

    @abstractmethod
    async def put_file(
        self,
        local_path: str,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Store a local file at key and return the storage key."""

    @abstractmethod
    async def put_bytes(
        self,
        data: bytes,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Store bytes at key and return the storage key."""

    @abstractmethod
    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """Open an async byte stream for key."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return whether key exists."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete key if it exists."""

    @abstractmethod
    async def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        """Return a short-lived download URL for key."""
