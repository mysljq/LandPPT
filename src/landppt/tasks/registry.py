"""Task handler registry for worker processes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

TaskHandler = Callable[[Any], Awaitable[dict]]

_HANDLERS: dict[str, TaskHandler] = {}


def task_handler(task_type: str):
    def decorator(func: TaskHandler) -> TaskHandler:
        _HANDLERS[task_type] = func
        return func

    return decorator


def get_handler(task_type: str) -> TaskHandler:
    if not _HANDLERS:
        import landppt.tasks.handlers.export_tasks  # noqa: F401
    try:
        return _HANDLERS[task_type]
    except KeyError as exc:
        raise KeyError(f"No worker handler registered for task type: {task_type}") from exc

