"""
Template-selection routes extracted from the legacy web router.
"""

from __future__ import annotations

import time
from datetime import datetime
import json
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...auth.middleware import get_current_user_required
from ...database.models import User
from .support import (
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
    logger,
    ppt_service,
)

router = APIRouter()


@router.get("/api/projects/{project_id}/selected-global-template")
async def get_selected_global_template(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Return the selected project template or the current default template."""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        selected_template = await user_ppt_service.get_selected_global_template(project_id, user_id=user.id)
        if selected_template:
            logger.info(
                "Project %s has selected template: %s",
                project_id,
                selected_template.get("template_name", "Unknown"),
            )
            return {"status": "success", "template": selected_template, "is_user_selected": True}

        default_template = await user_ppt_service.global_template_service.get_default_template()
        if default_template:
            logger.info(
                "Project %s using default template: %s",
                project_id,
                default_template.get("template_name", "Unknown"),
            )
            return {"status": "success", "template": default_template, "is_user_selected": False}

        logger.warning("No template available for project %s", project_id)
        return {"status": "success", "template": None, "is_user_selected": False}
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting selected global template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/free-template")
async def get_project_free_template(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Return the free-template status and current generated template."""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        is_free_mode = metadata.get("template_mode") == "free"
        html = metadata.get("free_template_html")
        template = None
        if isinstance(html, str) and html.strip():
            template = {
                "template_name": metadata.get("free_template_name") or "自由模板",
                "description": "AI 生成的项目专属自由模板",
                "html_template": html,
                "tags": ["自由模板", "AI生成"],
                "created_by": "ai_free",
                "template_mode": "free",
                "is_project_free_template": True,
            }

        return {
            "success": True,
            "enabled": is_free_mode,
            "active_mode": is_free_mode,
            "available": template is not None,
            "message": (
                "项目当前正在使用自由模板"
                if is_free_mode
                else ("项目存在可复用的历史自由模板" if template is not None else "项目当前未使用自由模板")
            ),
            "status": metadata.get("free_template_status"),
            "confirmed": bool(metadata.get("free_template_confirmed")),
            "saved_template_id": metadata.get("saved_global_template_id"),
            "template": template,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/free-template/generate")
async def generate_project_free_template(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Generate or regenerate a project's free template."""
    try:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        force = bool(payload.get("force", False))
        accept = (request.headers.get("accept") or "").lower()
        stream_flag = payload.get("stream")
        want_stream = True if stream_flag is None else bool(stream_flag)
        if "application/json" in accept and "text/event-stream" not in accept and stream_flag is None:
            want_stream = False

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        if metadata.get("template_mode") != "free":
            raise HTTPException(status_code=400, detail="Project is not using free template mode")

        existing_free_html = metadata.get("free_template_html")
        will_generate = force or not (isinstance(existing_free_html, str) and existing_free_html.strip())

        template_provider_name = None
        if will_generate:
            _, template_settings = await user_ppt_service.global_template_service._get_template_role_provider_async()
            template_provider_name = template_settings.get("provider")
            has_credits, required, balance = await check_credits_for_operation(
                user.id,
                "template_generation",
                1,
                provider_name=template_provider_name,
            )
            if not has_credits:
                message = f"Insufficient credits, need {required}, current {balance}"
                if want_stream:
                    async def _credit_error_stream():
                        yield f"data: {json.dumps({'type': 'error', 'message': message, 'required': required, 'balance': balance}, ensure_ascii=False)}\n\n"

                    return StreamingResponse(
                        _credit_error_stream(),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                    )
                return {"success": False, "error": message}

        if want_stream:
            async def event_stream():
                credits_consumed = False
                try:
                    async for event in user_ppt_service.stream_free_template_generation(
                        project_id,
                        user_id=user.id,
                        force=force,
                    ):
                        if (
                            will_generate
                            and not credits_consumed
                            and (event or {}).get("type") == "complete"
                        ):
                            await consume_credits_for_operation(
                                user.id,
                                "template_generation",
                                1,
                                description="Free template generation",
                                reference_id=project_id,
                                provider_name=template_provider_name,
                            )
                            credits_consumed = True

                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except HTTPException as exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': exc.detail}, ensure_ascii=False)}\n\n"
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error generating free template for project %s: %s", project_id, exc)
                    yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        template = None
        async for event in user_ppt_service.stream_free_template_generation(
            project_id,
            user_id=user.id,
            force=force,
        ):
            if (event or {}).get("type") == "complete":
                template = (event or {}).get("template")
                break
            if (event or {}).get("type") == "error":
                raise HTTPException(status_code=500, detail=(event or {}).get("message") or "Failed to generate free template")

        if not template:
            raise HTTPException(status_code=500, detail="Failed to generate free template")

        if will_generate:
            await consume_credits_for_operation(
                user.id,
                "template_generation",
                1,
                description="Free template generation",
                reference_id=project_id,
                provider_name=template_provider_name,
            )

        return {"success": True, "template": template}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error generating free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/free-template/confirm")
async def confirm_project_free_template(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Confirm the current free template and optionally save it to the library."""
    try:
        data = await request.json()
        save_to_library = bool(data.get("save_to_library", False))
        requested_name = (data.get("template_name") or "").strip()
        requested_description = (data.get("description") or "").strip()
        requested_tags = data.get("tags") or []
        submitted_html = data.get("html_template")

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        if metadata.get("template_mode") != "free":
            raise HTTPException(status_code=400, detail="Project is not using free template mode")

        html = metadata.get("free_template_html")
        if isinstance(submitted_html, str) and submitted_html.strip():
            html = submitted_html
            metadata["free_template_html"] = submitted_html
        if requested_name:
            metadata["free_template_name"] = requested_name
        if not (isinstance(html, str) and html.strip()):
            raise HTTPException(status_code=400, detail="Free template is not generated yet")

        metadata["free_template_confirmed"] = True
        metadata["free_template_confirmed_at"] = time.time()
        metadata["free_template_status"] = "ready"

        saved_template = None
        if save_to_library:
            base_name = requested_name or f"Free-template-{(project.topic or 'PPT')[:20]}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            description = requested_description or "Template confirmed from free-template mode"
            tags: List[str] = []
            if isinstance(requested_tags, list):
                tags = [str(tag).strip() for tag in requested_tags if str(tag).strip()]
            tags = tags or ["free-template", "ai-generated"]

            final_name = base_name
            for attempt in range(1, 6):
                try:
                    saved_template = await user_ppt_service.global_template_service.create_template(
                        {
                            "template_name": final_name,
                            "description": description,
                            "html_template": html,
                            "tags": tags,
                            "is_default": False,
                            "is_active": True,
                            "created_by": f"free_template:{project_id}",
                        }
                    )
                    break
                except ValueError:
                    final_name = f"{base_name}-{attempt}"

            if not saved_template:
                raise HTTPException(status_code=409, detail="Failed to save template to library")

            metadata["saved_global_template_id"] = saved_template.get("id")
            metadata["saved_global_template_name"] = saved_template.get("template_name")

        await user_ppt_service.project_manager.update_project_metadata(project_id, metadata)
        user_ppt_service.clear_cached_style_genes(project_id)
        return {"success": True, "saved_template": saved_template}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error confirming free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/free-template/adjust")
async def adjust_project_free_template(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Adjust the generated free template based on user feedback."""
    try:
        data = await request.json()
        adjustment_request = (data.get("adjustment_request") or "").strip()
        if not adjustment_request:
            raise HTTPException(status_code=400, detail="Adjustment request is required")

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        if metadata.get("template_mode") != "free":
            raise HTTPException(status_code=400, detail="Project is not using free template mode")

        current_html = metadata.get("free_template_html")
        if not (isinstance(current_html, str) and current_html.strip()):
            raise HTTPException(status_code=400, detail="Free template is not generated yet")

        template_name = metadata.get("free_template_name") or "Free template"
        _, template_settings = await user_ppt_service.global_template_service._get_template_role_provider_async()
        template_provider_name = template_settings.get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id,
            "template_generation",
            1,
            provider_name=template_provider_name,
        )
        if not has_credits:
            return {"success": False, "error": f"Insufficient credits, need {required}, current {balance}"}

        adjusted_html = None
        async for chunk in user_ppt_service.global_template_service.adjust_template_with_ai_stream(
            current_html=current_html,
            adjustment_request=adjustment_request,
            template_name=template_name,
        ):
            if chunk.get("type") == "complete":
                adjusted_html = chunk.get("html_template")
                break
            if chunk.get("type") == "error":
                raise HTTPException(status_code=500, detail=chunk.get("message", "Template adjustment failed"))

        if not adjusted_html:
            raise HTTPException(status_code=500, detail="Failed to adjust template")

        metadata["free_template_html"] = adjusted_html
        metadata["free_template_adjusted_at"] = time.time()
        metadata["free_template_adjustment_request"] = adjustment_request
        metadata["free_template_confirmed"] = False
        await user_ppt_service.project_manager.update_project_metadata(project_id, metadata)
        user_ppt_service.clear_cached_style_genes(project_id)

        await consume_credits_for_operation(
            user.id,
            "template_generation",
            1,
            description="Free template adjustment",
            reference_id=project_id,
            provider_name=template_provider_name,
        )

        return {
            "success": True,
            "template": {
                "template_name": template_name,
                "html_template": adjusted_html,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error adjusting free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/template-suite")
async def get_project_template_suite(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Return the template-suite status for the project's currently selected template."""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        status = await user_ppt_service.template_suite.get_suite_status(project_id)
        return {"success": True, **status}
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting template suite for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/template-suite/preview")
async def get_project_template_suite_preview(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Return rendered preview HTML for the project's template suite.

    Produces three standalone 1280x720 documents: cover, transition, and a
    content page (header/footer composed with sample body) so the user can see
    the actual suite effect before generating the PPT.
    """
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        suite = await user_ppt_service.template_suite.get_effective_suite(project_id)
        if not suite:
            raise HTTPException(status_code=404, detail="模板套件尚未生成，请先点击「生成一致性套件」")

        preview = user_ppt_service.template_suite.build_preview_html(suite)
        return {
            "success": True,
            "template_name": suite.get("template_name"),
            "preview": preview,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting template suite preview for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/template-suite/generate")
async def generate_project_template_suite(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Generate (or regenerate) the template suite for the project's selected template.

    Streams SSE events; persists the suite on success and consumes one
    template-generation credit (only billable for the LandPPT provider).
    """
    try:
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        force = bool(payload.get("force", False))
        # free=True：大纲智能套件——无需母版模板，直接根据项目大纲/主题设计套件。
        free = bool(payload.get("free", False))
        # requirements：用户自定义要求（如主题色/风格），注入套件生成 prompt。
        requirements = str(payload.get("requirements", "") or "").strip()
        # creativity：0-10 刻度，0=严格遵循母版，10=最具创意；默认 5（平衡）。
        try:
            creativity = int(payload.get("creativity", 5))
        except (TypeError, ValueError):
            creativity = 5
        creativity = max(0, min(10, creativity))
        # chapter_indicator：True = 内容页 header_footer 生成 {{chapter_indicator}} 章节提示槽位。
        # 缺省（None）时在下方从现有套件自推断（如编辑器"重新生成套件"入口，避免静默丢失章节提示）。
        chapter_indicator = payload.get("chapter_indicator")
        want_stream = True if payload.get("stream") is None else bool(payload.get("stream"))
        accept = (request.headers.get("accept") or "").lower()
        if "application/json" in accept and "text/event-stream" not in accept and payload.get("stream") is None:
            want_stream = False

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # chapter_indicator 缺省时，从现有套件推断（保留已有章节提示状态，避免编辑器
        # "重新生成套件"入口静默丢失用户已勾选的章节提示）。
        if chapter_indicator is None:
            try:
                existing = await user_ppt_service.template_suite.get_suite(project_id)
                chapter_indicator = bool(
                    existing and "{{chapter_indicator}}" in str(existing.get("header_footer") or "")
                )
            except Exception:
                chapter_indicator = False
        else:
            chapter_indicator = bool(chapter_indicator)

        will_generate = True
        if not force:
            suite = await user_ppt_service.template_suite.get_suite(project_id)
            will_generate = suite is None

        template_provider_name = None
        if will_generate:
            _, template_settings = await user_ppt_service.global_template_service._get_template_role_provider_async()
            template_provider_name = template_settings.get("provider")
            has_credits, required, balance = await check_credits_for_operation(
                user.id,
                "template_generation",
                1,
                provider_name=template_provider_name,
            )
            if not has_credits:
                message = f"Insufficient credits, need {required}, current {balance}"
                if want_stream:
                    async def _credit_error_stream():
                        yield f"data: {json.dumps({'type': 'error', 'message': message, 'required': required, 'balance': balance}, ensure_ascii=False)}\n\n"

                    return StreamingResponse(
                        _credit_error_stream(),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                    )
                return {"success": False, "error": message}

        if want_stream:
            async def event_stream():
                credits_consumed = False
                try:
                    async for event in user_ppt_service.template_suite.stream_suite_generation(
                        project_id,
                        user_id=user.id,
                        force=force,
                        creativity=creativity,
                        free=free,
                        custom_requirements=requirements,
                        chapter_indicator=chapter_indicator,
                    ):
                        if (
                            will_generate
                            and not credits_consumed
                            and (event or {}).get("type") == "complete"
                        ):
                            await consume_credits_for_operation(
                                user.id,
                                "template_generation",
                                1,
                                description="Template suite generation",
                                reference_id=project_id,
                                provider_name=template_provider_name,
                            )
                            credits_consumed = True
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except HTTPException as exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': exc.detail}, ensure_ascii=False)}\n\n"
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error generating template suite for project %s: %s", project_id, exc)
                    yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        suite = None
        async for event in user_ppt_service.template_suite.stream_suite_generation(
            project_id,
            user_id=user.id,
            force=force,
            creativity=creativity,
            free=free,
            custom_requirements=requirements,
            chapter_indicator=chapter_indicator,
        ):
            if (event or {}).get("type") == "complete":
                suite = (event or {}).get("suite")
                break
            if (event or {}).get("type") == "error":
                raise HTTPException(status_code=500, detail=(event or {}).get("message") or "Failed to generate template suite")

        if not suite:
            raise HTTPException(status_code=500, detail="Failed to generate template suite")

        if will_generate:
            await consume_credits_for_operation(
                user.id,
                "template_generation",
                1,
                description="Template suite generation",
                reference_id=project_id,
                provider_name=template_provider_name,
            )

        return {"success": True, "suite": suite}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error generating template suite for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/template-suite/regenerate-part")
async def regenerate_project_template_suite_part(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Regenerate a single part of the template suite (cover/transition/header_footer).

    Streams SSE events; only the chosen part is regenerated while every other part
    and design_tokens stay intact. Consumes one template-generation credit.
    """
    try:
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        part = (payload.get("part") or "").strip()
        user_feedback = (payload.get("feedback") or "").strip()
        # creativity：0-10 刻度，0=严格遵循母版，10=最具创意；默认 5（平衡）。
        try:
            creativity = int(payload.get("creativity", 5))
        except (TypeError, ValueError):
            creativity = 5
        creativity = max(0, min(10, creativity))
        # chapter_indicator：True = 内容页 header_footer 保留 {{chapter_indicator}} 章节提示槽位；
        # 缺省（None）由服务层从现有 header_footer 自推断。
        chapter_indicator = payload.get("chapter_indicator")
        if chapter_indicator is not None:
            chapter_indicator = bool(chapter_indicator)
        if part not in ("cover", "transition", "header_footer"):
            raise HTTPException(status_code=400, detail="part 必须是 cover / transition / header_footer")

        want_stream = True if payload.get("stream") is None else bool(payload.get("stream"))
        accept = (request.headers.get("accept") or "").lower()
        if "application/json" in accept and "text/event-stream" not in accept and payload.get("stream") is None:
            want_stream = False

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        suite = await user_ppt_service.template_suite.get_suite(project_id)
        if not suite:
            raise HTTPException(status_code=400, detail="项目暂无已生成的套件，请先生成套件")

        _, template_settings = await user_ppt_service.global_template_service._get_template_role_provider_async()
        template_provider_name = template_settings.get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id,
            "template_generation",
            1,
            provider_name=template_provider_name,
        )
        if not has_credits:
            message = f"Insufficient credits, need {required}, current {balance}"
            if want_stream:
                async def _credit_error_stream():
                    yield f"data: {json.dumps({'type': 'error', 'message': message, 'required': required, 'balance': balance}, ensure_ascii=False)}\n\n"
                return StreamingResponse(
                    _credit_error_stream(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                )
            return {"success": False, "error": message}

        if want_stream:
            async def event_stream():
                credits_consumed = False
                try:
                    async for event in user_ppt_service.template_suite.stream_suite_part_regeneration(
                        project_id,
                        part,
                        user_feedback=user_feedback,
                        user_id=user.id,
                        creativity=creativity,
                        chapter_indicator=chapter_indicator,
                    ):
                        if not credits_consumed and (event or {}).get("type") == "complete":
                            await consume_credits_for_operation(
                                user.id,
                                "template_generation",
                                1,
                                description=f"Template suite {part} regeneration",
                                reference_id=project_id,
                                provider_name=template_provider_name,
                            )
                            credits_consumed = True
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except HTTPException as exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': exc.detail}, ensure_ascii=False)}\n\n"
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error regenerating suite part for project %s: %s", project_id, exc)
                    yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        updated = None
        async for event in user_ppt_service.template_suite.stream_suite_part_regeneration(
            project_id,
            part,
            user_feedback=user_feedback,
            user_id=user.id,
            creativity=creativity,
            chapter_indicator=chapter_indicator,
        ):
            if (event or {}).get("type") == "complete":
                updated = (event or {}).get("suite")
                break
            if (event or {}).get("type") == "error":
                raise HTTPException(status_code=500, detail=(event or {}).get("message") or "Failed to regenerate suite part")

        if not updated:
            raise HTTPException(status_code=500, detail="Failed to regenerate suite part")

        await consume_credits_for_operation(
            user.id,
            "template_generation",
            1,
            description=f"Template suite {part} regeneration",
            reference_id=project_id,
            provider_name=template_provider_name,
        )

        return {"success": True, "part": part, "suite": updated}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error regenerating suite part for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
