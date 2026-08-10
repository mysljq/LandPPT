"""
Global Template Suite Library API endpoints — shared, cross-project suite library.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional
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
                    payload.template_id, creativity=payload.creativity
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        suite = await svc.generate_suite_from_template(payload.template_id, creativity=payload.creativity)
        return {"success": True, "suite": suite}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Error generating template suite from template: %s", exc)
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
