"""Utilities for keeping image payloads out of LLM prompt text."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


DATA_IMAGE_BASE64_RE = re.compile(
    r"data:(?P<mime>image/[A-Za-z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/=_-]+)",
    re.IGNORECASE,
)

UploadDataUrlFunc = Callable[[bytes, str, int], Awaitable[Optional[str]]]


def strip_base64_image_payloads_for_prompt(value: str) -> str:
    """Remove base64 image payloads from text that may be sent to an LLM."""
    if not value or "base64," not in value or "data:image" not in value:
        return value or ""

    def _replace(match: re.Match[str]) -> str:
        mime_type = match.group("mime")
        payload_len = len(match.group("payload") or "")
        return f"[image data omitted from prompt: {mime_type}, {payload_len} chars]"

    return DATA_IMAGE_BASE64_RE.sub(_replace, value)


async def materialize_base64_image_data_urls_for_prompt(
    value: str,
    *,
    user_id: Optional[int] = None,
    upload_func: Optional[UploadDataUrlFunc] = None,
    max_upload_bytes: int = 50 * 1024 * 1024,
) -> str:
    """Replace base64 image data URLs with hosted image URLs before prompt use.

    If hosting fails, the payload is still stripped so the prompt cannot balloon.
    """
    if not value or "base64," not in value or "data:image" not in value:
        return value or ""

    chunks: list[str] = []
    last_end = 0
    replacements: dict[str, str] = {}
    uploaded_count = 0
    omitted_count = 0

    for index, match in enumerate(DATA_IMAGE_BASE64_RE.finditer(value), start=1):
        chunks.append(value[last_end:match.start()])

        data_url = match.group(0)
        replacement = replacements.get(data_url)
        if replacement is None:
            mime_type = match.group("mime").lower()
            payload = match.group("payload") or ""
            image_bytes = _decode_base64_payload(payload)

            if not image_bytes:
                replacement = _omitted_marker(mime_type, len(payload), "invalid base64")
                omitted_count += 1
            elif len(image_bytes) > max_upload_bytes:
                replacement = _omitted_marker(mime_type, len(payload), "image too large")
                omitted_count += 1
            else:
                uploader = upload_func or (
                    lambda data, mime, idx: _upload_data_url_image_to_hosting(
                        data,
                        mime,
                        idx,
                        user_id=user_id,
                    )
                )
                try:
                    hosted_url = await uploader(image_bytes, mime_type, index)
                except Exception as exc:
                    logger.warning("Failed to host prompt image data URL: %s", exc)
                    hosted_url = None

                if hosted_url:
                    replacement = hosted_url
                    uploaded_count += 1
                else:
                    replacement = _omitted_marker(mime_type, len(payload), "upload failed")
                    omitted_count += 1

            replacements[data_url] = replacement

        chunks.append(replacement)
        last_end = match.end()

    chunks.append(value[last_end:])

    if uploaded_count or omitted_count:
        logger.info(
            "Prompt image data URLs processed: hosted=%s omitted=%s",
            uploaded_count,
            omitted_count,
        )

    return "".join(chunks)


async def upload_image_bytes_for_prompt(
    image_bytes: bytes,
    mime_type: str,
    *,
    user_id: Optional[int] = None,
    max_upload_bytes: int = 50 * 1024 * 1024,
) -> Optional[str]:
    """Upload image bytes to hosting and return a prompt-safe URL."""
    if not image_bytes:
        return None
    if len(image_bytes) > max_upload_bytes:
        logger.warning(
            "Prompt image omitted because it exceeds max upload size: %s > %s",
            len(image_bytes),
            max_upload_bytes,
        )
        return None

    try:
        return await _upload_data_url_image_to_hosting(
            image_bytes,
            (mime_type or "image/png").lower(),
            1,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning("Failed to host prompt image bytes: %s", exc)
        return None


def _decode_base64_payload(payload: str) -> Optional[bytes]:
    compact = re.sub(r"\s+", "", payload or "")
    if not compact:
        return None
    compact += "=" * (-len(compact) % 4)
    try:
        if "-" in compact or "_" in compact:
            return base64.urlsafe_b64decode(compact)
        return base64.b64decode(compact, validate=False)
    except Exception:
        return None


def _omitted_marker(mime_type: str, payload_len: int, reason: str) -> str:
    return f"[image data omitted from prompt: {mime_type}, {payload_len} chars, {reason}]"


def _extension_for_mime_type(mime_type: str) -> str:
    mime_type = (mime_type or "").lower()
    if mime_type in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if mime_type == "image/png":
        return "png"
    if mime_type == "image/webp":
        return "webp"
    if mime_type == "image/gif":
        return "gif"
    if mime_type == "image/bmp":
        return "bmp"
    if mime_type == "image/svg+xml":
        return "svg"
    return "png"


async def _upload_data_url_image_to_hosting(
    image_bytes: bytes,
    mime_type: str,
    index: int,
    *,
    user_id: Optional[int] = None,
) -> Optional[str]:
    from ..auth.request_context import current_user_id
    from .image.image_service import get_image_service
    from .image.models import ImageSourceType, ImageUploadRequest
    from .url_service import build_image_url

    token = None
    if user_id is not None and current_user_id.get() != user_id:
        token = current_user_id.set(user_id)

    try:
        image_service = get_image_service()
        if not image_service.initialized:
            await image_service.initialize()

        digest = hashlib.sha256(image_bytes).hexdigest()[:16]
        ext = _extension_for_mime_type(mime_type)
        upload_request = ImageUploadRequest(
            filename=f"prompt_asset_{digest}_{index}.{ext}",
            content_type=mime_type,
            file_size=len(image_bytes),
            title=f"Prompt asset {digest}",
            description="Image data URL materialized for LLM prompt use",
            tags=["prompt_asset", "template_resource"],
            category="local_storage",
            source_type=ImageSourceType.LOCAL_STORAGE,
        )

        result = await image_service.upload_image(upload_request, image_bytes)
        if not result.success or not result.image_info:
            logger.warning(
                "Image hosting upload failed for prompt asset: %s",
                getattr(result, "message", "unknown"),
            )
            return None

        metadata = result.image_info.metadata
        try:
            return build_image_url(
                result.image_info.image_id,
                width=getattr(metadata, "width", None),
                height=getattr(metadata, "height", None),
            )
        except Exception as exc:
            logger.warning("Failed to build absolute prompt asset URL: %s", exc)
            return f"/api/image/view/{result.image_info.image_id}"
    finally:
        if token is not None:
            current_user_id.reset(token)
