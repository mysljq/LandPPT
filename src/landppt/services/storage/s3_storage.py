"""S3/MinIO artifact storage backend."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .base import ArtifactStorage


class S3ArtifactStorage(ArtifactStorage):
    backend_name = "s3"

    def __init__(
        self,
        *,
        endpoint_url: Optional[str],
        region: str,
        bucket: str,
        access_key_id: Optional[str],
        secret_access_key: Optional[str],
        force_path_style: bool = True,
        public_base_url: Optional[str] = None,
    ):
        if not bucket:
            raise ValueError("S3_BUCKET is required")

        self.bucket = bucket
        self.public_base_url = (public_base_url or "").rstrip("/")
        s3_config = Config(s3={"addressing_style": "path" if force_path_style else "virtual"})
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=s3_config,
        )

    async def put_file(
        self,
        local_path: str,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        extra_args = self._extra_args(content_type, metadata)
        await asyncio.to_thread(self.client.upload_file, local_path, self.bucket, key, ExtraArgs=extra_args)
        return key

    async def put_bytes(
        self,
        data: bytes,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        kwargs = {"Bucket": self.bucket, "Key": key, "Body": data}
        kwargs.update(self._extra_args(content_type, metadata))
        await asyncio.to_thread(self.client.put_object, **kwargs)
        return key

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, 1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        if self.public_base_url:
            return f"{self.public_base_url}/{quote(key, safe='/')}"
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    @staticmethod
    def _extra_args(content_type: Optional[str], metadata: Optional[dict]) -> dict:
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
        return extra_args
