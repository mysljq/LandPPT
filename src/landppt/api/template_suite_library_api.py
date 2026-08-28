"""
Global Template Suite Library API endpoints — shared, cross-project suite library.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import AsyncIterator, Dict, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth.middleware import get_current_user_required
from ..core.config import app_config
from ..database.database import AsyncSessionLocal
from ..services.credits_service import CreditsService
from ..services.template.global_template_suite_service import GlobalTemplateSuiteService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/template-suites", tags=["Global Template Suites"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # 禁止 Nginx 等反向代理缓存小块 SSE 数据，否则心跳无法及时到达客户端。
    "X-Accel-Buffering": "no",
}


async def _sse_events_with_heartbeat(
    events: AsyncIterator[dict], heartbeat_seconds: float = 10.0
):
    """把事件异步迭代器编码为 SSE，并在模型计算期间持续发送注释心跳。"""
    iterator = events.__aiter__()
    pending = asyncio.create_task(iterator.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if pending not in done:
                yield f": keepalive {int(time.time())}\n\n"
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            pending = asyncio.create_task(iterator.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        with contextlib.suppress(Exception):
            await iterator.aclose()


def _suite_service_for_user(user) -> GlobalTemplateSuiteService:
    """Suite library is global shared, but generation must resolve the user's
    configured model service (per-user LLM config), so pass user.id through."""
    return GlobalTemplateSuiteService(user_id=user.id)


class SuiteCreateRequest(BaseModel):
    suite_name: str
    description: Optional[str] = ""
    cover: str
    transition: str
    catalog: Optional[str] = ""
    ending: Optional[str] = ""
    header_footer: str
    design_tokens: Optional[str] = ""
    template_id: Optional[int] = None
    template_hash: Optional[str] = None
    template_name: Optional[str] = None
    tags: Optional[list] = None


class SuiteGenerateRequest(BaseModel):
    template_id: int
    creativity: int = 5
    stream: bool = False
    chapter_indicator: bool = False


class SuiteFromRequirementsRequest(BaseModel):
    requirement_text: str = ""
    web_html: str = ""
    creativity: int = 5
    stream: bool = True
    chapter_indicator: bool = False


class SuiteUpdateRequest(BaseModel):
    suite_name: Optional[str] = None
    description: Optional[str] = None
    cover: Optional[str] = None
    transition: Optional[str] = None
    catalog: Optional[str] = None
    ending: Optional[str] = None
    header_footer: Optional[str] = None
    design_tokens: Optional[str] = None
    tags: Optional[list] = None
    is_active: Optional[bool] = None


@router.get("")
async def list_suites(
    page: int = Query(1, ge=1),
    page_size: int = Query(6, ge=1, le=100),
    search: Optional[str] = None,
    template_id: Optional[int] = None,
    user=Depends(get_current_user_required),
):
    """List global template suites (paginated)."""
    try:
        svc = _suite_service_for_user(user)
        return await svc.list_suites(page=page, page_size=page_size, search=search, template_id=template_id)
    except Exception as exc:
        logger.error("Error listing template suites: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/all")
async def list_all_suites(user=Depends(get_current_user_required)):
    """List all global template suites (no pagination) — for pickers."""
    try:
        svc = _suite_service_for_user(user)
        return {"suites": await svc.list_all_suites()}
    except Exception as exc:
        logger.error("Error listing all template suites: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("")
async def create_suite(payload: SuiteCreateRequest, user=Depends(get_current_user_required)):
    """Create a global template suite."""
    try:
        svc = _suite_service_for_user(user)
        return await svc.create_suite(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Error creating template suite: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{suite_id}")
async def get_suite(suite_id: int, user=Depends(get_current_user_required)):
    """Get a global template suite by ID."""
    try:
        svc = _suite_service_for_user(user)
        suite = await svc.get_suite(suite_id)
        if not suite:
            raise HTTPException(status_code=404, detail="套件不存在")
        return {"suite": suite}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error getting template suite %s: %s", suite_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/{suite_id}")
async def update_suite(suite_id: int, payload: SuiteUpdateRequest, user=Depends(get_current_user_required)):
    """Update a global template suite."""
    try:
        svc = _suite_service_for_user(user)
        update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="无更新字段")
        ok = await svc.update_suite(suite_id, update_data)
        if not ok:
            raise HTTPException(status_code=404, detail="套件不存在")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error updating template suite %s: %s", suite_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{suite_id}")
async def delete_suite(suite_id: int, user=Depends(get_current_user_required)):
    """Delete a global template suite."""
    try:
        svc = _suite_service_for_user(user)
        ok = await svc.delete_suite(suite_id)
        if not ok:
            raise HTTPException(status_code=404, detail="套件不存在")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error deleting template suite %s: %s", suite_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


async def _generate_credits_error(user) -> Optional[dict]:
    """Return an error dict when credits are insufficient (landppt provider), else None."""
    if not app_config.enable_credits_system:
        return None
    provider_name = None
    try:
        from ..services.template.global_master_template_service import GlobalMasterTemplateService
        tsvc = GlobalMasterTemplateService(user_id=user.id)
        _, template_settings = await tsvc._get_template_role_provider_async()
        provider_name = template_settings.get("provider")
    except Exception as e:
        logger.warning(f"Failed to resolve template provider for credits check: {e}")
    if (provider_name or "").strip().lower() != "landppt":
        return None
    async with AsyncSessionLocal() as session:
        credits_service = CreditsService(session)
        required = credits_service.get_operation_cost("template_generation", 1)
        balance = await credits_service.get_balance(user.id)
        if balance < required:
            return {
                "success": False,
                "message": f"积分不足，套件生成需要{required}积分，当前余额{balance}积分",
                "required": required,
                "balance": balance,
            }
    return None


@router.post("/generate")
async def generate_suite_from_template(payload: SuiteGenerateRequest, user=Depends(get_current_user_required)):
    """Generate a suite from a master template (does not save; preview then save).

    When stream=true, returns a text/event-stream so the frontend can show live
    progress (status → complete / error) instead of a silent blocking request.
    """
    logger.info(
        "收到基于模板生成套件请求：template_id=%s, creativity=%s, stream=%s, user_id=%s",
        payload.template_id, payload.creativity, payload.stream, user.id,
    )
    try:
        svc = _suite_service_for_user(user)
        credits_error = await _generate_credits_error(user)
        if credits_error:
            if payload.stream:
                async def _credits_error_stream():
                    yield f"data: {json.dumps({'type': 'error', 'message': credits_error['message']}, ensure_ascii=False)}\n\n"
                return StreamingResponse(
                    _credits_error_stream(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                )
            return credits_error

        if payload.stream:
            async def event_stream():
                async for event in svc.stream_generate_suite_from_template(
                    payload.template_id, creativity=payload.creativity,
                    chapter_indicator=payload.chapter_indicator,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        suite = await svc.generate_suite_from_template(
            payload.template_id, creativity=payload.creativity,
            chapter_indicator=payload.chapter_indicator,
        )
        return {"success": True, "suite": suite}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Error generating template suite from template: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/generate-from-requirements")
async def generate_suite_from_requirements(
    payload: SuiteFromRequirementsRequest, user=Depends(get_current_user_required)
):
    """基于文字需求 + 可选网页 HTML 生成套件（流式）。

    requirement_text 与 web_html 至少填一项；都空时服务层返回 error 事件。
    web_html 提供时，套件配色/字体/版式/背景装饰与该网页保持一致。
    复用模板套件生成的积分检查（landppt provider 时）。
    """
    logger.info(
        "收到基于需求/网页生成套件请求：user_id=%s, creativity=%s, stream=%s, "
        "requirement_len=%s, web_html_len=%s",
        user.id, payload.creativity, payload.stream,
        len((payload.requirement_text or "")), len((payload.web_html or "")),
    )
    try:
        svc = _suite_service_for_user(user)
        credits_error = await _generate_credits_error(user)
        if credits_error:
            if payload.stream:
                async def _credits_error_stream():
                    yield f"data: {json.dumps({'type': 'error', 'message': credits_error['message']}, ensure_ascii=False)}\n\n"
                return StreamingResponse(
                    _credits_error_stream(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                )
            return credits_error

        if payload.stream:
            async def event_stream():
                async for event in svc.stream_generate_suite_from_requirements(
                    payload.requirement_text, payload.web_html, creativity=payload.creativity,
                    chapter_indicator=payload.chapter_indicator,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        # 非流式：收集事件，complete 取 suite，error 抛 400
        suite = None
        async for event in svc.stream_generate_suite_from_requirements(
            payload.requirement_text, payload.web_html, creativity=payload.creativity,
            chapter_indicator=payload.chapter_indicator,
        ):
            if event.get("type") == "error":
                raise HTTPException(status_code=400, detail=event.get("message", "生成失败"))
            if event.get("type") == "complete":
                suite = event.get("suite")
        if not suite:
            raise HTTPException(status_code=500, detail="生成未返回套件数据")
        return {"success": True, "suite": suite}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error generating template suite from requirements: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/generate-from-images")
async def generate_suite_from_images(
    creativity: int = Form(5),
    extract_images: bool = Form(True),
    cover: Optional[UploadFile] = File(default=None),
    transition: Optional[UploadFile] = File(default=None),
    catalog: Optional[UploadFile] = File(default=None),
    ending: Optional[UploadFile] = File(default=None),
    content: Optional[UploadFile] = File(default=None),
    user=Depends(get_current_user_required),
):
    """基于上传的页面截图生成套件（多模态读图）。返回 SSE 流。

    字段 cover/transition/catalog/ending/content 均为可选的页面截图（content=内容页）。
    未上传的类型由后端用大模型基于其它页面设计补全。
    extract_images=True 时，识别截图中的图片/图标区域并在生成结果中直接复用。
    """
    logger.info(
        "收到基于AI读图生成套件请求：user_id=%s, creativity=%s, extract_images=%s",
        user.id, creativity, extract_images,
    )

    async def _read_img(f: Optional[UploadFile]) -> Optional[bytes]:
        if f is None:
            return None
        try:
            data = await f.read()
        finally:
            await f.close()
        return data or None

    images: Dict[str, bytes] = {}
    for key, field in (
        ("cover", cover),
        ("transition", transition),
        ("catalog", catalog),
        ("ending", ending),
        ("header_footer", content),
    ):
        data = await _read_img(field)
        if data:
            images[key] = data

    if not images:
        raise HTTPException(status_code=400, detail="请至少上传一张页面截图")

    svc = _suite_service_for_user(user)

    async def event_stream():
        try:
            async for event in svc.stream_generate_suite_from_images(
                images, creativity=creativity, user_id=user.id, extract_images=extract_images
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.error("基于AI读图生成套件失败: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': f'生成失败：{exc}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/generate-from-reference-image")
async def generate_suite_from_reference_image(
    image: UploadFile = File(...),
    creativity: int = Form(5),
    requirement_text: str = Form(""),
    chapter_indicator: bool = Form(False),
    user=Depends(get_current_user_required),
):
    """读取一张任意参考图的画风、色板与视觉元素，并生成完整 PPT 套件。"""
    if creativity < 0 or creativity > 10:
        raise HTTPException(status_code=400, detail="创意度必须在 0-10 之间")
    content_type = (image.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        await image.close()
        raise HTTPException(status_code=400, detail="请上传图片文件")
    try:
        image_bytes = await image.read()
    finally:
        await image.close()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="参考图片为空")
    if len(image_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="参考图片不能超过 15MB")

    logger.info(
        "收到基于任意参考图片生成套件请求：user_id=%s, creativity=%s, image_size=%s, requirement_len=%s",
        user.id, creativity, len(image_bytes), len((requirement_text or "")),
    )
    credits_error = await _generate_credits_error(user)
    if credits_error:
        async def _credits_error_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': credits_error['message']}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            _credits_error_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    svc = _suite_service_for_user(user)

    async def event_stream():
        try:
            events = svc.stream_generate_suite_from_reference_image(
                image_bytes, creativity=creativity, user_id=user.id,
                requirement_text=requirement_text, chapter_indicator=chapter_indicator,
            )
            async for chunk in _sse_events_with_heartbeat(events):
                yield chunk
        except Exception as exc:
            logger.error("基于任意参考图片生成套件失败: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': f'生成失败：{exc}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/{suite_id}/duplicate")
async def duplicate_suite(suite_id: int, user=Depends(get_current_user_required)):
    """Duplicate a global template suite."""
    try:
        svc = _suite_service_for_user(user)
        suite = await svc.get_suite(suite_id)
        if not suite:
            raise HTTPException(status_code=404, detail="套件不存在")
        suite.pop("id", None)
        suite.pop("created_at", None)
        suite.pop("updated_at", None)
        suite["usage_count"] = 0
        suite["suite_name"] = suite.get("suite_name", "套件") + "（副本）"
        return await svc.create_suite(suite)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error duplicating template suite %s: %s", suite_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{suite_id}/preview")
async def preview_suite(suite_id: int, user=Depends(get_current_user_required)):
    """Preview pages (cover/transition/content) for a stored suite."""
    try:
        svc = _suite_service_for_user(user)
        preview = await svc.preview_suite(suite_id)
        return {"success": True, "preview": preview}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Error previewing template suite %s: %s", suite_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


class ProjectSuiteSelectRequest(BaseModel):
    project_id: str
    suite_id: Optional[int] = None  # None = clear selection


@router.post("/select-for-project")
async def select_suite_for_project(payload: ProjectSuiteSelectRequest, user=Depends(get_current_user_required)):
    """Select (or clear) a global-library suite as a project's suite source.

    suite_id provided -> project uses that library suite for generation.
    suite_id=None -> clear the selection (fall back to project-generated suite).
    """
    try:
        from ..services.enhanced_ppt_service import EnhancedPPTService
        service = EnhancedPPTService(user_id=user.id)
        if payload.suite_id:
            ok = await service.template_suite.select_global_suite(payload.project_id, payload.suite_id)
            if not ok:
                raise HTTPException(status_code=400, detail="套件不存在或项目无效")
            return {"success": True, "selected_global_suite_id": payload.suite_id}
        await service.template_suite.clear_selected_global_suite(payload.project_id)
        return {"success": True, "selected_global_suite_id": None}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error selecting global suite for project: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
