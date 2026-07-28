"""单页幻灯片生成进度回调（跨层共享，ContextVar 传递）。

用于生成 PPT 时把"当前页/总页、本轮第几次重试/最多几次、当前在哪道闸"
实时透出到数据库 stage 与前端进度，以及在控制台打印重试次数。

为什么用 ContextVar：单页生成链路经 slide_authoring→slide_html_service→
slide_media→validation→recovery 多层 facade，逐层透传参数成本高且会破坏
既有方法签名。ContextVar 在同一协程调用栈里下传，重试器按需读取，
不传则无副作用。
"""

from __future__ import annotations

import logging
import contextvars
from typing import Optional

logger = logging.getLogger(__name__)

# 当前重试进度回调。每轮重试前/关键节点调用一次。
# 回调签名：async def cb(*, page_number: int, total_pages: int,
#                        attempt: int, max_retries: int,
#                        stage: str, detail: str = "") -> None
_retry_progress_cb: contextvars.ContextVar = contextvars.ContextVar(
    "landppt_retry_progress_cb", default=None
)


def set_retry_progress_cb(cb) -> None:
    """在 PPT 生成开始处设置当前页重试进度回调。"""
    _retry_progress_cb.set(cb)


def get_retry_progress_cb():
    return _retry_progress_cb.get()


async def notify_retry_progress(
    *,
    page_number: int,
    total_pages: int,
    attempt: int,
    max_retries: int,
    stage: str,
    detail: str = "",
) -> None:
    """通知一次重试进度。回调缺失或异常都不阻塞生成主流程。"""
    cb = get_retry_progress_cb()
    if cb is None:
        return
    try:
        await cb(
            page_number=page_number,
            total_pages=total_pages,
            attempt=attempt,
            max_retries=max_retries,
            stage=stage,
            detail=detail,
        )
    except Exception as exc:
        logger.debug("retry progress callback error (ignored): %s", exc)