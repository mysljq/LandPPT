"""
项目生命周期相关页面路由。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from ...api.models import PPTGenerationRequest
from ...auth.middleware import get_current_user_required
from ...database.models import User
from ...services.outline.document_structure_service import (
    DOCUMENT_STRUCTURE_MODE,
    MAX_DOCUMENT_UPLOAD_BYTES,
    read_document_source,
    generate_document_outline,
)
from ...utils.thread_pool import run_blocking_io
from .support import (get_ppt_service_for_user, ppt_service, templates,
                      check_credits_for_operation, consume_credits_for_operation)

router = APIRouter()


@router.get("/scenarios", response_class=HTMLResponse)
async def web_scenarios(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """场景选择页面。"""
    scenarios = [
        {"id": "general", "name": "通用", "description": "适用于各类通用场景的 PPT 模板", "icon": "📚"},
        {"id": "tourism", "name": "旅游观光", "description": "旅游线路、景点介绍等旅游相关 PPT", "icon": "🗺️"},
        {"id": "education", "name": "儿童科普", "description": "适合儿童的科普教育类 PPT", "icon": "🎓"},
        {"id": "analysis", "name": "深入分析", "description": "数据分析、研究报告等深度分析 PPT", "icon": "📊"},
        {"id": "history", "name": "历史文化", "description": "历史事件、文化介绍等人文类 PPT", "icon": "🏛️"},
        {"id": "technology", "name": "科技技术", "description": "技术介绍、产品发布等科技类 PPT", "icon": "💻"},
        {"id": "business", "name": "方案汇报", "description": "商业计划、项目汇报等商务 PPT", "icon": "💼"},
    ]
    return templates.TemplateResponse(
        "pages/project/scenarios.html",
        {"request": request, "scenarios": scenarios},
    )


@router.get("/research", response_class=HTMLResponse)
async def web_research_status(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Deep Research 状态页。"""
    return templates.TemplateResponse("pages/project/research_status.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def web_dashboard(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """项目仪表盘。"""
    try:
        projects_response = await ppt_service.project_manager.list_projects(
            page=1,
            page_size=100,
            user_id=user.id,
        )
        projects = projects_response.projects

        total_projects = len(projects)
        completed_projects = len([project for project in projects if project.status == "completed"])
        in_progress_projects = len([project for project in projects if project.status == "in_progress"])
        draft_projects = len([project for project in projects if project.status == "draft"])
        recent_projects = sorted(projects, key=lambda project: project.updated_at, reverse=True)[:5]

        active_todo_boards = []
        for project in projects:
            if project.status == "in_progress" and project.todo_board:
                todo_board = await ppt_service.get_project_todo_board(project.project_id)
                if todo_board:
                    active_todo_boards.append(todo_board)

        return templates.TemplateResponse(
            "pages/project/project_dashboard.html",
            {
                "request": request,
                "total_projects": total_projects,
                "completed_projects": completed_projects,
                "in_progress_projects": in_progress_projects,
                "draft_projects": draft_projects,
                "recent_projects": recent_projects,
                "active_todo_boards": active_todo_boards[:3],
            },
        )
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.get("/projects", response_class=HTMLResponse)
async def web_projects_list(
    request: Request,
    page: int = 1,
    status: str | None = None,
    user: User = Depends(get_current_user_required),
):
    """项目列表页。"""
    try:
        projects_response = await ppt_service.project_manager.list_projects(
            page=page,
            page_size=10,
            status=status,
            user_id=user.id,
        )
        return templates.TemplateResponse(
            "pages/project/projects_list.html",
            {
                "request": request,
                "projects": projects_response.projects,
                "total": projects_response.total,
                "page": projects_response.page,
                "page_size": projects_response.page_size,
                "status_filter": status,
            },
        )
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.post("/projects/create", response_class=HTMLResponse)
async def web_create_project(
    request: Request,
    scenario: str = Form(...),
    topic: str = Form(""),
    requirements: str | None = Form(None),
    notes: str | None = Form(None),
    language: str = Form("zh"),
    network_mode: bool = Form(False),
    creation_mode: str = Form("standard"),
    source_document: UploadFile | None = File(None),
    user: User = Depends(get_current_user_required),
):
    """创建项目。"""
    try:
        if creation_mode not in ("standard", DOCUMENT_STRUCTURE_MODE):
            raise ValueError("不支持的创建模式。")
        document_outline = None
        if creation_mode == DOCUMENT_STRUCTURE_MODE:
            if source_document is None or not source_document.filename:
                raise ValueError("请上传 Word（.docx）或 Markdown 文件。")
            try:
                content = await source_document.read(MAX_DOCUMENT_UPLOAD_BYTES + 1)
                filename, source = await run_blocking_io(
                    read_document_source, content, source_document.filename
                )
            finally:
                await source_document.close()
            service = get_ppt_service_for_user(user.id)
            _, settings = await service.get_role_provider_async("outline")
            provider_name = settings.get("provider")
            has_credits, required, balance = await check_credits_for_operation(
                user.id, "outline_generation", 3, provider_name=provider_name,
            )
            if not has_credits:
                raise ValueError(f"积分不足，文档解析最多需要 {required} 积分，当前余额 {balance} 积分")
            document_outline = await generate_document_outline(source, filename, topic, service)
            topic = document_outline["title"]
            network_mode = False
        elif not topic.strip():
            raise ValueError("请输入 PPT 主题。")

        project_request = PPTGenerationRequest(
            scenario=scenario,
            topic=topic,
            requirements=requirements,
            notes=notes,
            network_mode=network_mode,
            language=language,
            user_id=user.id,
        )
        project = await ppt_service.project_manager.create_project(project_request)
        await ppt_service.project_manager.update_project_status(project.project_id, "in_progress")
        if document_outline is not None:
            confirmed = {
                "creation_mode": DOCUMENT_STRUCTURE_MODE,
                "topic": topic,
                "scenario": scenario,
                "requirements": requirements,
                "target_audience": "普通大众",
                "ppt_style": "general",
                "content_source": "file",
                "filename": document_outline["metadata"]["source_filename"],
                "page_count_settings": {"mode": "document_structure"},
                "include_transition_pages": False,
                "force_file_outline_regeneration": False,
                "file_generated_outline": document_outline,
                "document_source_outline": document_outline,
            }
            manager = ppt_service.project_manager
            if not await manager.update_todo_board_with_confirmed_requirements(
                project.project_id, confirmed, user_id=user.id
            ):
                raise RuntimeError("文档已解析，但保存任务失败，请重试。")
            from landppt.services.slide.parallel_page_service import ParallelPageService
            await ParallelPageService.prepare(
                service, project.project_id, document_outline,
                document_outline.get("slides", []), persist=False,
            )
            if not await manager.save_project_outline(project.project_id, document_outline):
                raise RuntimeError("保存文档大纲失败，请重试。")
            if not await manager.update_stage_status(
                project.project_id, "outline_generation", "completed", 100.0,
                {"outline_data": document_outline}, user_id=user.id,
            ):
                raise RuntimeError("更新大纲阶段失败，请重试。")
            billed, message = await consume_credits_for_operation(
                user.id, "outline_generation", document_outline["metadata"]["llm_call_count"],
                description=f"文档结构解析: {topic}", reference_id=project.project_id,
                provider_name=provider_name,
            )
            if not billed:
                raise RuntimeError(message or "文档解析积分扣费失败")
        return RedirectResponse(url=f"/projects/{project.project_id}/todo", status_code=302)
    except ValueError as exc:
        return templates.TemplateResponse(
            "error.html", {"request": request, "error": str(exc)}, status_code=400
        )
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.post("/projects/{project_id}/start-workflow")
async def start_project_workflow(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """启动项目工作流。"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if not project.confirmed_requirements:
            return {"status": "waiting", "message": "Waiting for requirements confirmation"}

        network_mode = False
        if project.project_metadata and isinstance(project.project_metadata, dict):
            network_mode = project.project_metadata.get("network_mode", False)

        language = "zh"
        if project.project_metadata and isinstance(project.project_metadata, dict):
            language = project.project_metadata.get("language", "zh")

        confirmed_requirements = project.confirmed_requirements or {}
        project_request = PPTGenerationRequest(
            scenario=project.scenario,
            topic=project.topic,
            requirements=project.requirements,
            language=language,
            network_mode=network_mode,
            target_audience=confirmed_requirements.get("target_audience", "普通大众"),
            ppt_style=confirmed_requirements.get("ppt_style", "general"),
            custom_style_prompt=confirmed_requirements.get("custom_style_prompt"),
            description=confirmed_requirements.get("description"),
            user_id=user.id,
        )

        user_ppt_service = get_ppt_service_for_user(user.id)
        asyncio.create_task(
            user_ppt_service._execute_project_workflow(
                project_id,
                project_request,
                user_id=user.id,
            )
        )
        return {"status": "success", "message": "Workflow started"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
