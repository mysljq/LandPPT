"""Local, best-effort tracing for every LLM invocation.

Each top-level provider call is written to its own JSON file so concurrent
requests cannot interleave.  Trace failures are deliberately non-fatal: a
logging problem must never break presentation generation.
"""

from __future__ import annotations

import contextvars
import inspect
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, Optional


logger = logging.getLogger(__name__)

_current_trace: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "landppt_llm_trace", default=None
)
# Avoid matching harmless usage fields such as ``prompt_tokens``.
_SECRET_KEY = re.compile(
    r"(?:^|_)(?:api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|secret|password|cookie)$",
    re.I,
)


def _jsonable(value: Any, *, key: str = "") -> Any:
    """Convert SDK/Pydantic objects to JSON-safe values and mask credentials."""
    if _SECRET_KEY.search(key):
        return "***REDACTED***"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except TypeError:
            return _jsonable(value.model_dump())
    if hasattr(value, "dict"):
        try:
            return _jsonable(value.dict())
        except Exception:
            pass
    return str(value)


def _trace_dir() -> Path:
    configured = os.getenv("LANDPPT_LLM_TRACE_DIR", "llm_traces")
    path = Path(configured).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def record_reasoning(value: Any) -> None:
    """Attach provider-exposed reasoning/thinking content to the active trace."""
    trace = _current_trace.get()
    if trace is None or value in (None, ""):
        return
    trace.setdefault("reasoning", []).append(_jsonable(value))


def _start_trace(provider: Any, method: str, args: tuple, kwargs: dict) -> tuple[Dict[str, Any], Any]:
    now = datetime.now(timezone.utc)
    trace: Dict[str, Any] = {
        "trace_id": uuid.uuid4().hex,
        "started_at": now.isoformat(),
        "provider": provider.__class__.__name__,
        "model": getattr(provider, "model", None),
        "method": method,
        "input": {
            "arguments": _jsonable(args),
            "options": _jsonable(kwargs),
            "provider_config": _jsonable(getattr(provider, "config", {})),
        },
        "_started_monotonic": time.monotonic(),
    }
    return trace, _current_trace.set(trace)


def _finish_trace(trace: Dict[str, Any], *, output: Any = None, error: BaseException | None = None) -> None:
    try:
        started = trace.pop("_started_monotonic", time.monotonic())
        trace["finished_at"] = datetime.now(timezone.utc).isoformat()
        trace["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        trace["status"] = "error" if error else "success"
        if output is not None:
            trace["output"] = _jsonable(output)
        if error is not None:
            trace["error"] = {
                "type": error.__class__.__name__,
                "message": str(error),
            }

        directory = _trace_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = trace["started_at"].replace(":", "-").replace("+", "_")
        target = directory / f"{stamp}_{trace['trace_id']}.json"
        target.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write local LLM trace")


def trace_provider_method(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an async provider method, suppressing nested provider calls."""
    if getattr(func, "_landppt_llm_traced", False):
        return func

    if inspect.isasyncgenfunction(func):
        @wraps(func)
        async def stream_wrapper(self: Any, *args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
            if _current_trace.get() is not None:
                async for item in func(self, *args, **kwargs):
                    yield item
                return

            trace, token = _start_trace(self, func.__name__, args, kwargs)
            chunks = []
            try:
                async for item in func(self, *args, **kwargs):
                    chunks.append(item)
                    yield item
            except BaseException as exc:
                _finish_trace(trace, output={"chunks": chunks, "content": "".join(map(str, chunks))}, error=exc)
                raise
            else:
                _finish_trace(trace, output={"chunks": chunks, "content": "".join(map(str, chunks))})
            finally:
                _current_trace.reset(token)

        stream_wrapper._landppt_llm_traced = True
        return stream_wrapper

    @wraps(func)
    async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if _current_trace.get() is not None:
            return await func(self, *args, **kwargs)

        trace, token = _start_trace(self, func.__name__, args, kwargs)
        try:
            result = await func(self, *args, **kwargs)
        except BaseException as exc:
            _finish_trace(trace, error=exc)
            raise
        else:
            _finish_trace(trace, output=result)
            return result
        finally:
            _current_trace.reset(token)

    async_wrapper._landppt_llm_traced = True
    return async_wrapper
