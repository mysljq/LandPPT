"""Valkey-backed task queue primitives."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from ..core.config import app_config
from ..services.cache_service import get_cache_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueMessage:
    task_id: str
    task_type: str


class TaskQueueUnavailable(RuntimeError):
    """Raised when queue mode is requested but Valkey is unavailable."""


def queue_key(queue_name: Optional[str] = None) -> str:
    return f"landppt:task_queue:{queue_name or app_config.task_queue_name or 'default'}"


async def _connected_client():
    cache = await get_cache_service()
    if not cache or not cache.is_connected or not getattr(cache, "_client", None):
        raise TaskQueueUnavailable("Valkey queue is unavailable; set CACHE_BACKEND=valkey and VALKEY_URL")
    return cache._client


async def enqueue_task(task_id: str, task_type: str, queue_name: Optional[str] = None) -> None:
    client = await _connected_client()
    payload = json.dumps({"task_id": task_id, "task_type": task_type})
    await client.lpush(queue_key(queue_name), payload)
    logger.info("Queued task %s (%s)", task_id, task_type)


async def dequeue_task(queue_name: Optional[str] = None, timeout_seconds: Optional[int] = None) -> Optional[QueueMessage]:
    client = await _connected_client()
    timeout = timeout_seconds if timeout_seconds is not None else app_config.task_worker_poll_timeout_seconds
    try:
        item = await client.brpop(queue_key(queue_name), timeout=timeout)
    except ValkeyTimeoutError:
        logger.debug("Timed out waiting for task queue %s", queue_key(queue_name))
        return None
    if not item:
        return None
    _, payload = item
    data = json.loads(payload)
    return QueueMessage(task_id=str(data["task_id"]), task_type=str(data["task_type"]))
