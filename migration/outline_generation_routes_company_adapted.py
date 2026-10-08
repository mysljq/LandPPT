"""
大纲接口
"""
import asyncio
import json
import tempfile
import time
import uuid
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from za38 import get_logger

from .models import (
    PPTGenerationRequest,
    GenerateOutlineRequest,
    GenerateOutlineResponse,
    ConfirmSearchRequest,
    CancelGenerationRequest,
    CancelGenerationResponse,
    UpdateOutlineRequest,
    UpdateOutlineResponse,
    RegenerateOutlineRequest,
    RegenerateOutlineResponse,
    CancelRegenerateOutlineRequest,
    CancelRegenerateOutlineResponse,
    FileUploadItem,
    OriginalRequirementDetail,
    OriginalRequirementFileItem,
)
from ..auth.middleware import get_current_user_required
from ..database.models import User
from ..services.file_processor import FileProcessor
from ..services.service_instances import get_ppt_service_for_user
from ..services.clawpartner_manage_service import clawpartner_agent_service
from ..tracking import (
    tracker,
    OutlineGenerateRequestEvent,
    OutlineGenerateResultEvent,
    OutlineEditEvent,
    UsageScenarioGenerateResultEvent,
)


router = APIRouter()
logger = get_logger(__name__)
file_processor = FileProcessor()


async def _generate_usage_scenario_async(
        user_ppt_service,
        project_id: str,
        user_id: str,
        title: str,
        content: str,
        language: str = "zh",
):
    """并行生成使用场景，完成后更新confirmed_requirements

    当用户未传usage_scenario时，后台并行调用AI总结一个使用场景，
    并将结果更新到数据库中的confirmed_requirements，供大纲生成使用。

    Args:
        user_ppt_service: PPT服务实例
        project_id: 项目ID
        user_id: 用户ID
        title: PPT标题
        content: 用户输入的内容
        language: 语言
    """
    start_time = time.time()
    try:
        # 构建AI提示词
        if language == "en":
            prompt = f"""Based on the following PPT topic and content, summarize a concise usage scenario (e.g., promotional material, defense report, training courseware, product research, etc.).

Topic: {title or 'Untitled'}

Content:
{content[:2000]}

Please return ONLY the usage scenario name (2-10 words), without any explanation or prefix. If you cannot determine a scenario, return "General Presentation"."""
        else:
            prompt = f"""根据以下PPT主题和内容，总结一个简洁的使用场景（如：宣传材料、答辩汇报、培训课件、产品调研、方案汇报等，可以按类似的语义来总结场景）。

主题：{title or '未命名'}

内容：
{content[:2000]}

请只返回使用场景名称（2-10个字），不要有任何解释或前缀。
"""

        # 调用AI生成使用场景
        response = await user_ppt_service._text_completion_for_role(
            "outline",
            prompt=prompt,
            temperature=0.3,
        )

        usage_scenario = response.content.strip()
        if not usage_scenario:
            logger.warning(f"AI生成使用场景为空，项目={project_id}")
            return

        # 清理AI返回的多余内容（只保留第一行）
        usage_scenario = usage_scenario.split('\n')[0].strip()
        # 去掉可能的引号
        usage_scenario = usage_scenario.strip('"\'“”‘’')

        logger.info(f"AI生成使用场景成功: {usage_scenario}, 项目={project_id}")

        # 使用场景生成结果埋点（成功）
        duration_ms = int((time.time() - start_time) * 1000)
        try:
            usage = response.usage or {}
        except Exception:
            usage = {}
        tracker.track(
            UsageScenarioGenerateResultEvent,
            user_id=user_id,
            project_id=project_id,
            usage_scenario=usage_scenario,
            success=True,
            model=getattr(response, "model", None),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            duration_ms=duration_ms,
        )

        # 更新数据库中的confirmed_requirements
        from ..services.db_project_manager import DatabaseProjectManager
        db_manager = DatabaseProjectManager()
        project = await db_manager.get_project(project_id, user_id=user_id)
        if not project:
            logger.warning(f"项目不存在，无法更新使用场景: {project_id}")
            return

        confirmed_requirements = project.confirmed_requirements or {}
        confirmed_requirements["usage_scenario"] = usage_scenario
        # 移除标记字段，保持数据整洁
        confirmed_requirements.pop("_needs_usage_scenario", None)
        await db_manager.save_confirmed_requirements(project_id, confirmed_requirements)
        logger.info(f"已更新项目 {project_id} 的confirmed_requirements中的usage_scenario: {usage_scenario}")

    except Exception as e:
        logger.warning(f"AI生成使用场景失败: {e}, 项目={project_id}")
        # 使用场景生成结果埋点（失败）
        duration_ms = int((time.time() - start_time) * 1000)
        tracker.track(
            UsageScenarioGenerateResultEvent,
            user_id=user_id,
            project_id=project_id,
            usage_scenario="",
            success=False,
            duration_ms=duration_ms,
            error_msg=str(e),
        )


# 生成大纲
@router.post("/outline/generate-with-progress", response_model=GenerateOutlineResponse)
async def generate_outline_with_progress(
        request: GenerateOutlineRequest,
        http_request: Request,
        user: User = Depends(get_current_user_required)
):
    """
    生成大纲接口 - 创建项目并开始生成大纲（或复用已有项目重试）

    点击【生成大纲】按钮后调用此接口：
    1. 如果提供了project_id，则复用已有项目进行大纲生成（重试场景）
    2. 如果未提供project_id，则创建一个新项目
    3. 自动完成需求确认阶段
    4. 启动大纲生成流程（后台异步执行）
    5. 返回项目ID供前端跳转到进度查看页面

    创建模式（source_type）：
    - "intelligent_creation": 智能创作PPT模式
        - content: 必填，文本要求
        - text_requirement: 可选 "ai_expand"(AI扩写) 或 "ai_summarize"(AI归纳)
        - page_count_mode: 必填，页数模式
        - file_paths: 可选，最多5个文件，作为背景资料
        - 支持文档类型：word、pdf、ppt、markdown、txt

    - "document_to_ppt": 文稿一键转PPT模式
        - content: 非必填
        - file_paths: 必填，仅支持1个文件，单个文件不超过50M
        - text_requirement: 默认为 "keep_original"(接近原文)，在最大程度保留原文的基础上进行校对和PPT结构优化
        - page_count_mode: 必填，页数模式
        - 支持文档类型：word、pdf、ppt、markdown、txt

    参数说明：
    - title: PPT标题（必填）
    - text_requirement: 文本要求，可选值：
        - "keep_original": 保留原文
        - "ai_expand": AI扩写
        - "ai_summarize": AI归纳
      默认值: "keep_original"
    - page_count_mode: 页数模式，可选值：
        - "ai": AI生成
        - "range": 范围（需配合min_pages和max_pages使用）
        - "fixed": 固定（需配合fixed_pages使用）
      默认值: "ai"
    - text_style: 文本风格（可选）
    - usage_scenario: 使用场景（可选）
    """
    try:
        # 确保用户ID已设置
        request.user_id = user.user_id

        # 获取用户特定的PPT服务实例
        user_ppt_service = get_ppt_service_for_user(user.user_id)

        # 支持的文档类型
        SUPPORTED_DOC_TYPES = {'.doc', '.docx', '.pdf', '.ppt', '.pptx', '.md', '.txt', '.markdown'}
        MAX_FILE_SIZE_DOCUMENT_TO_PPT = 50 * 1024 * 1024  # 50MB

        # 大纲生成请求埋点
        tracker.track(
            OutlineGenerateRequestEvent,
            user_id=user.user_id,
            project_id=request.project_id,
            source_type=request.source_type,
            text_requirement=request.text_requirement,
            page_count_mode=request.page_count_mode,
            min_pages=request.min_pages,
            max_pages=request.max_pages,
            fixed_pages=request.fixed_pages,
            usage_scenario=request.usage_scenario,
            is_regenerate=request.project_id is not None,
        )

        # 根据创建模式验证和处理内容
        if request.source_type == "intelligent_creation":
            # 智能创作PPT模式
            # 1. 验证content必填
            if not request.content:
                raise HTTPException(status_code=400, detail="智能创作PPT模式下content参数必填")

            # 2. 验证text_requirement只能是ai_expand或ai_summarize
            if request.text_requirement not in ["ai_expand", "ai_summarize"]:
                raise HTTPException(
                    status_code=400,
                    detail="智能创作PPT模式下text_requirement只能是ai_expand(AI扩写)或ai_summarize(AI归纳)"
                )

            # 3. 如果没有提供title，使用默认标题（后续由AI生成）
            if not request.title:
                request.title = "智能创作PPT"  # 临时标题，后续由大纲生成时AI会生成正式标题

            # 3. 处理可选的背景资料文档（最多5个）
            processed_content = request.content
            if request.file_paths:
                if len(request.file_paths) > 5:
                    raise HTTPException(status_code=400, detail="智能创作PPT模式最多上传5个文档作为背景资料")

                # 验证文档类型
                for file_obj in request.file_paths:
                    file_ext = _get_file_extension(file_obj.name)
                    if file_ext not in SUPPORTED_DOC_TYPES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"不支持的文档类型: {file_obj.name}，支持的类型: word、pdf、ppt、markdown、txt"
                        )

                # 处理背景资料文档
                background_content = await _process_uploaded_files(request.file_paths, None)
                processed_content = f"{request.content}\n\n【背景资料】\n{background_content}"

            source_type = "intelligent_creation"

        elif request.source_type == "document_to_ppt":
            # 文稿一键转PPT模式
            # 1. 验证必须上传文档，且仅支持1个
            if not request.file_paths or len(request.file_paths) == 0:
                raise HTTPException(status_code=400, detail="文稿一键转PPT模式下file_paths参数必填")

            if len(request.file_paths) > 1:
                raise HTTPException(status_code=400, detail="文稿一键转PPT模式仅支持上传1个文档")

            # 2. 验证文档类型
            file_obj = request.file_paths[0]
            file_ext = _get_file_extension(file_obj.name)
            if file_ext not in SUPPORTED_DOC_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的文档类型: {file_obj.name}，支持的类型: word、pdf、ppt、markdown、txt"
                )

            # 3. 验证文件大小（通过URL下载后检查，或信任前端已验证）
            # 注意：此处假设前端已验证文件大小，如需后端验证可下载后检查

            # 4. 强制设置text_requirement为keep_original（对应"接近原文"模式）
            request.text_requirement = "keep_original"

            # 5. 如果没有提供title，使用文件名（去掉扩展名）作为临时标题
            if not request.title:
                # 从文件名提取标题（去掉扩展名）
                import os
                request.title = os.path.splitext(file_obj.name)[0] or "文稿转PPT"

            # 6. 处理文档内容
            processed_content = await _process_uploaded_files(request.file_paths, None)
            source_type = "document_to_ppt"

        else:
            raise HTTPException(status_code=400, detail=f"不支持的创建模式: {request.source_type}")

        # 构建confirmed_requirements（需求确认信息）
        confirmed_requirements = {
            "topic": request.title,
            "type": request.scenario,
            "description": processed_content,
            "source_type": source_type,
            "text_requirement": request.text_requirement,
            "page_count_mode": request.page_count_mode,
            "min_pages": request.min_pages,
            "max_pages": request.max_pages,
            "fixed_pages": request.fixed_pages,
            "language": request.language,
            "user_id": request.user_id,
            "enable_mcp_search": request.enable_mcp_search,
        }

        # 只在智能创作PPT模式下包含text_style和usage_scenario
        if source_type == "intelligent_creation":
            if request.text_style:
                confirmed_requirements["text_style"] = request.text_style
            if request.usage_scenario:
                confirmed_requirements["usage_scenario"] = request.usage_scenario
            else:
                # 用户未传usage_scenario，标记为需要AI总结使用场景
                confirmed_requirements["_needs_usage_scenario"] = True

        # 保存file_paths到confirmed_requirements，用于后续重新生成
        if request.file_paths:
            # 将FileUploadItem列表转换为可序列化的字典列表
            uploaded_files = []
            for file_obj in request.file_paths:
                if isinstance(file_obj, FileUploadItem):
                    uploaded_files.append({
                        "name": file_obj.name,
                        "key": file_obj.key
                    })
                elif isinstance(file_obj, dict):
                    uploaded_files.append(file_obj)
            confirmed_requirements["uploaded_files"] = uploaded_files

        # 构建页数设置
        page_count_settings = {
            "mode": request.page_count_mode,
            "min_pages": request.min_pages,
            "max_pages": request.max_pages,
            "fixed_pages": request.fixed_pages,
        }

        # 将GenerateOutlineRequest转换为PPTGenerationRequest
        ppt_request = PPTGenerationRequest(
            scenario=request.scenario,
            topic=request.title,
            requirements=_build_requirements_from_outline_request(request),
            language=request.language,
            user_id=user.user_id,
            description=processed_content,
            uploaded_content=processed_content,
        )

        # 判断是复用已有项目还是创建新项目
        if request.project_id:
            # 重试场景：复用已有项目
            project = await user_ppt_service.project_manager.get_project(request.project_id, user_id=user.user_id)
            if not project:
                raise HTTPException(status_code=404, detail=f"项目 {request.project_id} 不存在")

            # 验证项目所有权
            if project.user_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权访问此项目")

            project_id = request.project_id
            logger.info(f"Reusing existing project {project_id} for outline regeneration by user {user.user_id}")
        else:
            # 新建项目
            # 如果前端提供了task_id，则使用task_id作为project_id
            custom_project_id = request.task_id if request.task_id else None
            project = await user_ppt_service.project_manager.create_project(ppt_request, project_id=custom_project_id)
            project_id = project.project_id
            logger.info(f"Created new project {project_id} for user {user.user_id}, task_id={request.task_id}")

        # 自动完成需求确认阶段（更新confirmed_requirements）
        success = await user_ppt_service.confirm_requirements_and_update_workflow(
            project_id,
            confirmed_requirements
        )

        if not success:
            raise Exception("需求确认失败")

        # 复用已有项目重试时，需要主动重置outline_generation阶段状态为running，
        # 否则前端在接口返回后立即查询详情时，看到的还是之前completed的状态。
        # 调度器异步执行TaskRunner._execute_outline_task时才会更新为running，
        # 但存在竞态窗口期，接口返回和调度器执行之间前端可能已发起查询。
        if request.project_id:
            await user_ppt_service.update_project_stage(
                project_id,
                "outline_generation",
                "running",
                progress=0.0,
                user_id=user.user_id
            )
            logger.info(f"Reset outline_generation stage to running for reused project {project_id}")

        # 从请求头中获取自定义的 x-agent-id，保存到 project_metadata 中，
        # 以便在查询项目详情时可以获取到。
        # 注意：HTTP header 名称大小写不敏感，FastAPI/Starlette 的 request.headers
        # 内部统一转为小写存储，因此无论客户端发送 X-Agent-Id、X-AGENT-ID 还是 x-agent-id
        # 都能通过 get("x-agent-id") 正确获取。
        x_agent_id = http_request.headers.get("x-agent-id")
        if x_agent_id:
            x_agent_id = x_agent_id.strip()

        # 创建大纲生成的取消上下文（用于支持取消操作）
        project_metadata = project.project_metadata or {}
        project_metadata["_regenerate_outline_context"] = {
            "previous_outline": None,  # 首次生成没有之前的大纲
            "previous_stage_status": None,
            "user_id": user.user_id,
            "cancelled": False
        }
        # 保存用户原始输入的content到project_metadata，用于后续原始需求详情展示
        # 注意：confirmed_requirements["description"] 会包含文件解析后的背景资料内容，
        # 而原始需求详情只需要用户在界面上输入的纯文本内容。
        project_metadata["_original_request_content"] = request.content
        # 保存 x-agent-id 到 project_metadata，供查询项目详情时获取
        if x_agent_id:
            project_metadata["x_agent_id"] = x_agent_id
        await user_ppt_service.project_manager.update_project_metadata(
            project_id,
            project_metadata,
            user_id=user.user_id
        )

        # 通过调度模块创建大纲生成任务
        from ..schedule.task_service import task_service as schedule_task_service
        from ..schedule.models import TaskType, ExecMode
        await schedule_task_service.create_task(
            project_id=project_id,
            user_id=str(user.user_id),
            task_type=TaskType.OUTLINE,
            exec_mode=ExecMode.DAY,
            payload={
                "confirmed_requirements": confirmed_requirements,
                "page_count_settings": page_count_settings,
                "regenerate": request.project_id is not None,
            },
            prev_phase="pending",
        )
        logger.info(f"Outline task created via scheduler for project {project_id}")

        # 如果用户未传usage_scenario，启动并行AI任务总结使用场景
        # 不阻塞接口返回，由后台任务完成后更新数据库中的confirmed_requirements
        # TaskRunner._execute_outline_task执行时会从数据库获取最新的confirmed_requirements
        if source_type == "intelligent_creation" and not request.usage_scenario:
            asyncio.create_task(
                _generate_usage_scenario_async(
                    user_ppt_service,
                    project_id,
                    user.user_id,
                    request.title,
                    processed_content,
                    request.language,
                )
            )
            logger.info(f"Started parallel usage_scenario generation for project {project_id}")

        # 获取看板
        todo_board = await user_ppt_service.get_project_todo_board(project_id, user_id=user.user_id)

        action_msg = "复用项目重试" if request.project_id else "项目创建成功"
        logger.info(f"{action_msg}, project {project_id}, outline generation started for user {user.user_id}")

        return GenerateOutlineResponse(
            success=True,
            project_id=project_id,
            message=f"{action_msg}，大纲生成已启动",
            todo_board=todo_board,
        )

    except HTTPException as http_ex:
        # 将HTTPException转换为统一错误格式返回
        logger.error(f"HTTP error generating outline: {http_ex.detail}")
        return JSONResponse(
            status_code=200,
            content={
                "returnCode": "ERR001",
                "errorMsg": http_ex.detail,
                "body": None
            }
        )
    except Exception as e:
        logger.error(f"Error generating outline: {str(e)}")
        return JSONResponse(
            status_code=200,
            content={
                "returnCode": "ERR001",
                "errorMsg": f"生成大纲失败: {str(e)}",
                "body": None
            }
        )


# 确认搜索敏感信息后继续大纲生成
@router.post("/outline/confirm-search")
async def confirm_search_and_generate_outline(
        request: ConfirmSearchRequest,
        user: User = Depends(get_current_user_required)
):
    """
    确认搜索关键词敏感信息后继续大纲生成接口

    用户在前端轮询发现 outline_generation 阶段状态为 search_confirmation 后，
    确认搜索关键词是否有敏感信息，然后调用此接口继续大纲生成：
    1. mcp_search_decision="search"：无敏感信息，执行联网搜索后生成大纲
    2. mcp_search_decision="skip"：有敏感信息，跳过搜索直接生成大纲

    项目已在 generate-with-progress 时创建，此接口只需传 project_id 和确认结果。
    """
    try:
        # 获取用户特定的PPT服务实例
        user_ppt_service = get_ppt_service_for_user(user.user_id)

        # 获取已有项目
        project = await user_ppt_service.project_manager.get_project(request.project_id, user_id=user.user_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"项目 {request.project_id} 不存在")

        if project.user_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权访问此项目")

        project_id = request.project_id

        # 获取已有的confirmed_requirements
        confirmed_requirements = project.confirmed_requirements or {}
        # 更新搜索决策
        confirmed_requirements["mcp_search_decision"] = request.mcp_search_decision
        confirmed_requirements["mcp_search_keywords"] = request.search_keywords or []

        # 如果用户未传usage_scenario且数据库中没有，标记需要AI总结使用场景
        # 注意：_convert_db_project_to_api会过滤掉_needs_usage_scenario标记，
        # 所以这里需要从数据库原始数据中检查
        if not confirmed_requirements.get("usage_scenario"):
            confirmed_requirements["_needs_usage_scenario"] = True

        # 更新confirmed_requirements
        success = await user_ppt_service.confirm_requirements_and_update_workflow(
            project_id,
            confirmed_requirements
        )
        if not success:
            raise Exception("更新需求确认信息失败")

        # ============ 记录用户承诺到数据库 ============
        try:
            import json as _json
            from ..database.database import AsyncSessionLocal
            from ..database.models import UserCommitmentRecord

            original_info = _json.dumps({
                "title": confirmed_requirements.get("topic", ""),
                "content": confirmed_requirements.get("description", ""),
                "search_keywords": request.search_keywords or [],
                "enable_mcp_search": confirmed_requirements.get("enable_mcp_search", False),
            }, ensure_ascii=False)

            choice_description = "无敏感信息，执行联网搜索" if request.mcp_search_decision == "search" else "有敏感信息，跳过联网搜索"

            extra_data = _json.dumps({
                "source_type": confirmed_requirements.get("source_type", ""),
                "text_requirement": confirmed_requirements.get("text_requirement", ""),
                "page_count_mode": confirmed_requirements.get("page_count_mode", ""),
            }, ensure_ascii=False)

            async with AsyncSessionLocal() as db_session:
                commitment_record = UserCommitmentRecord(
                    user_id=str(user.user_id),
                    project_id=project_id,
                    scenario="mcp_search_sensitive_check",
                    original_info=original_info,
                    user_choice=request.mcp_search_decision,
                    choice_description=choice_description,
                    extra_data=extra_data,
                )
                db_session.add(commitment_record)
                await db_session.commit()
                logger.info(f"用户承诺记录已入库：user={user.user_id}, project={project_id}, choice={request.mcp_search_decision}")
        except Exception as commit_error:
            logger.warning(f"记录用户承诺失败，不影响大纲生成: {commit_error}")

        # 构建页数设置
        page_count_settings = {
            "mode": confirmed_requirements.get("page_count_mode", "ai"),
            "min_pages": confirmed_requirements.get("min_pages", 8),
            "max_pages": confirmed_requirements.get("max_pages", 15),
            "fixed_pages": confirmed_requirements.get("fixed_pages", 10),
        }

        # 更新outline_generation阶段状态为running（从search_confirmation恢复）
        await user_ppt_service.project_manager.update_stage_status(
            project_id,
            "outline_generation",
            "running",
            progress=0.0,
            user_id=user.user_id
        )

        # 通过调度模块创建新的大纲生成任务
        from ..schedule.task_service import task_service as schedule_task_service
        from ..schedule.models import TaskType, ExecMode
        await schedule_task_service.create_task(
            project_id=project_id,
            user_id=str(user.user_id),
            task_type=TaskType.OUTLINE,
            exec_mode=ExecMode.DAY,
            payload={
                "confirmed_requirements": confirmed_requirements,
                "page_count_settings": page_count_settings,
                "regenerate": True,
            },
            prev_phase="pending",
        )
        logger.info(f"Outline task created via scheduler for project {project_id} (confirm-search)")

        # 如果用户未传usage_scenario，启动并行AI任务总结使用场景
        # 注意：generate-with-progress时可能已启动，这里检查确认后是否需要补充
        if not confirmed_requirements.get("usage_scenario"):
            from ..services.db_project_manager import DatabaseProjectManager
            _db_manager = DatabaseProjectManager()
            _project = await _db_manager.get_project(project_id, user_id=user.user_id)
            _db_confirmed = (_project.confirmed_requirements or {}) if _project else {}
            if not _db_confirmed.get("usage_scenario"):
                asyncio.create_task(
                    _generate_usage_scenario_async(
                        user_ppt_service,
                        project_id,
                        user.user_id,
                        confirmed_requirements.get("topic", ""),
                        confirmed_requirements.get("description", ""),
                        confirmed_requirements.get("language", "zh"),
                    )
                )
                logger.info(f"Started parallel usage_scenario generation for project {project_id} (confirm-search)")

        decision_msg = "执行联网搜索" if request.mcp_search_decision == "search" else "跳过联网搜索"
        logger.info(f"confirm-search: project {project_id}, {decision_msg}, outline generation resumed for user {user.user_id}")

        return {
            "success": True,
            "project_id": project_id,
            "message": f"{decision_msg}，大纲生成已继续",
        }

    except HTTPException as http_ex:
        logger.error(f"HTTP error in confirm-search: {http_ex.detail}")
        return JSONResponse(
            status_code=200,
            content={
                "returnCode": "ERR001",
                "errorMsg": http_ex.detail,
                "body": None
            }
        )
    except Exception as e:
        logger.error(f"Error in confirm-search: {str(e)}")
        return JSONResponse(
            status_code=200,
            content={
                "returnCode": "ERR001",
                "errorMsg": f"确认搜索后继续生成大纲失败: {str(e)}",
                "body": None
            }
        )


# 获取原始需求详情
@router.get("/projects/{project_id}/original-requirements")
async def get_original_requirements(
        project_id: str,
        user: User = Depends(get_current_user_required)
):
    """
    获取项目的原始需求详情 - 用于前端弹窗展示

    从项目的 confirmed_requirements 字段中提取原始需求信息，包括：
    - 创建模式（智能生成PPT / 文稿一键转PPT）
    - 输入内容（用户输入的文本）
    - 附件文件列表
    - 文本要求（保留原文 / AI扩写 / AI归纳）
    - 生成页数模式
    - 文本风格（仅智能生成PPT模式）
    - 使用场景（仅智能生成PPT模式）

    返回统一响应格式：
    - returnCode: "SUC0000" 表示成功
    - body: OriginalRequirementDetail 对象
    """
    try:
        # 获取用户特定的PPT服务实例
        user_ppt_service = get_ppt_service_for_user(user.user_id)

        # 验证项目存在且属于当前用户
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.user_id)
        if not project:
            return JSONResponse(
                status_code=200,
                content={
                    "returnCode": "ERR001",
                    "errorMsg": f"项目 {project_id} 不存在或无权访问",
                    "body": None
                }
            )

        # 从 confirmed_requirements 提取原始需求
        confirmed_requirements = project.confirmed_requirements or {}
        project_metadata = project.project_metadata or {}

        # 创建模式映射
        source_type_map = {
            "intelligent_creation": "智能生成PPT",
            "document_to_ppt": "文稿一键转PPT"
        }
        source_type = confirmed_requirements.get("source_type", "intelligent_creation")
        source_type_display = source_type_map.get(source_type, source_type)

        # 文本要求映射
        text_requirement_map = {
            "keep_original": "保留原文",
            "ai_expand": "AI扩写",
            "ai_summarize": "AI归纳"
        }
        text_requirement = confirmed_requirements.get("text_requirement")
        text_requirement_display = text_requirement_map.get(text_requirement, text_requirement) if text_requirement else None

        # 页数模式映射
        page_count_mode = confirmed_requirements.get("page_count_mode")
        page_count_display = None
        if page_count_mode == "ai":
            page_count_display = "AI生成页数"
        elif page_count_mode == "range":
            min_pages = confirmed_requirements.get("min_pages")
            max_pages = confirmed_requirements.get("max_pages")
            page_count_display = f"{min_pages}-{max_pages}页"
        elif page_count_mode == "fixed":
            fixed_pages = confirmed_requirements.get("fixed_pages")
            page_count_display = f"固定{fixed_pages}页"

        # 处理附件文件列表
        uploaded_files_data = confirmed_requirements.get("uploaded_files", [])
        uploaded_files = []
        for file_obj in uploaded_files_data:
            if isinstance(file_obj, dict):
                uploaded_files.append(OriginalRequirementFileItem(
                    name=file_obj.get("name", ""),
                    key=file_obj.get("key", ""),
                    size=file_obj.get("size")
                ))
            elif isinstance(file_obj, FileUploadItem):
                uploaded_files.append(OriginalRequirementFileItem(
                    name=file_obj.name,
                    key=file_obj.key,
                    size=None
                ))

        # 提取用户原始输入的content
        # 优先从 project_metadata 中获取保存的原始 content（generate_outline_with_progress 接口保存），
        # 这样可以确保返回的是用户在界面上输入的纯文本，而非包含文件解析后的背景资料内容。
        original_content = project_metadata.get("_original_request_content")
        # 如果元数据中没有（可能是旧项目），回退使用 confirmed_requirements 中的 description
        if original_content is None:
            original_content = confirmed_requirements.get("description")

        # 构建响应体
        detail = OriginalRequirementDetail(
            project_id=project_id,
            source_type=source_type,
            source_type_display=source_type_display,
            content=original_content,
            uploaded_files=uploaded_files,
            text_requirement=text_requirement,
            text_requirement_display=text_requirement_display,
            page_count_mode=page_count_mode,
            page_count_display=page_count_display,
            text_style=confirmed_requirements.get("text_style"),
            usage_scenario=confirmed_requirements.get("usage_scenario"),
        )

        return {
            "returnCode": "SUC0000",
            "errorMsg": None,
            "body": detail.dict()
        }

    except Exception as e:
        logger.error(f"Error getting original requirements for project {project_id}: {str(e)}")
        return JSONResponse(
            status_code=200,
            content={
                "returnCode": "ERR001",
                "errorMsg": f"获取原始需求详情失败: {str(e)}",
                "body": None
            }
        )


# 取消生成大纲
@router.post("/outline/cancel-generation", response_model=CancelGenerationResponse)
async def cancel_generation(
        request: CancelGenerationRequest,
        user: User = Depends(get_current_user_required)
):
    """
    取消生成接口 - 取消大纲生成但保留项目

    点击【取消生成】按钮后调用此接口：
    1. 取消正在进行的AI生成任务
    2. 保留项目，不删除
    3. 将项目状态保持为进行中
    4. 将需求确认阶段重置为pending状态，允许用户重新生成

    注意：此操作允许用户重新调整需求并重新生成大纲
    """
    try:
        # 获取用户特定的PPT服务实例
        user_ppt_service = get_ppt_service_for_user(user.user_id)

        # 验证项目存在且属于当前用户
        project = await user_ppt_service.project_manager.get_project(request.project_id, user_id=user.user_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在或无权访问")

        # 检查大纲是否已经生成
        if project.outline and project.outline.get("slides"):
            raise HTTPException(
                status_code=400,
                detail="大纲已生成，无法取消。如需重新生成，请使用重新生成功能。"
            )

        # 1. 设置取消标志，让后台任务能够检测到并停止执行
        cancel_flag_set = await _set_regenerate_cancelled_flag(user_ppt_service, request.project_id, user.user_id)
        if cancel_flag_set:
            logger.info(f"Set cancelled flag for project {request.project_id}")

        # 2. 取消正在进行的AI生成任务
        try:
            # 通过新调度模块取消幻灯片生成任务
            from ..schedule.task_service import TaskService
            from ..schedule.models import TaskType
            task_service = TaskService()
            await task_service.cancel_task(request.project_id, TaskType.FULL)
            logger.info(f"Cancelled slides generation for project {request.project_id}")
        except Exception as cancel_error:
            logger.warning(f"Error cancelling slides generation: {cancel_error}")
            # 继续执行，即使取消失败

        # 3. 将大纲生成阶段重置为pending状态
        await user_ppt_service.update_project_stage(
            request.project_id,
            "outline_generation",
            "pending",
            progress=0.0,
            user_id=user.user_id
        )

        # 4. 将需求确认阶段重置为pending状态
        await user_ppt_service.update_project_stage(
            request.project_id,
            "requirements_confirmation",
            "pending",
            user_id=user.user_id
        )

        # 5. 将PPT生成阶段重置为pending状态
        await user_ppt_service.update_project_stage(
            request.project_id,
            "ppt_creation",
            "pending",
            progress=0.0,
            user_id=user.user_id
        )

        # 6. 清除已确认的需求，以便状态协调逻辑能正确识别为pending状态
        await user_ppt_service.project_manager.update_project(
            request.project_id,
            {"confirmed_requirements": None},
            user_id=user.user_id
        )

        # 7. 确保项目状态为进行中
        await user_ppt_service.project_manager.update_project_status(
            request.project_id,
            "in_progress",
            user_id=user.user_id
        )

        logger.info(f"Successfully cancelled outline generation for project {request.project_id}, project kept in in_progress status")

        return CancelGenerationResponse(
            success=True,
            message="已取消大纲生成，项目已保留，可重新调整需求"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling generation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消生成失败: {str(e)}")


# 重新生成大纲
@router.post("/outline/regenerate", response_model=RegenerateOutlineResponse)
async def regenerate_outline(
        request: RegenerateOutlineRequest,
        user: User = Depends(get_current_user_required)
):
    """
    重新生成大纲接口

    使用原有参数重新生成大纲：
    1. 验证项目存在且属于当前用户
    2. 备份当前大纲（用于取消时恢复）
    3. 重置大纲生成阶段状态为running
    4. 启动后台异步生成任务
    5. 返回项目ID供前端轮询进度

    注意：
    - 如果是导入文档模式，会从confirmed_requirements.uploaded_files获取文件key
    - 文件key永不过期，可通过key从OSS重新下载文件
    """
    try:
        # 获取用户特定的PPT服务实例
        user_ppt_service = get_ppt_service_for_user(user.user_id)

        # 验证项目存在且属于当前用户
        project = await user_ppt_service.project_manager.get_project(request.project_id, user_id=user.user_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在或无权访问")

        # 检查项目是否有确认的需求
        if not project.confirmed_requirements:
            raise HTTPException(status_code=400, detail="项目需求尚未确认，无法重新生成大纲")

        confirmed_requirements = project.confirmed_requirements

        # 大纲生成请求埋点（重新生成）
        tracker.track(
            OutlineGenerateRequestEvent,
            user_id=user.user_id,
            project_id=request.project_id,
            source_type=confirmed_requirements.get("source_type", "intelligent_creation"),
            text_requirement=confirmed_requirements.get("text_requirement", "keep_original"),
            page_count_mode=confirmed_requirements.get("page_count_mode", "ai"),
            min_pages=confirmed_requirements.get("min_pages"),
            max_pages=confirmed_requirements.get("max_pages"),
            fixed_pages=confirmed_requirements.get("fixed_pages"),
            usage_scenario=confirmed_requirements.get("usage_scenario"),
            is_regenerate=True,
        )

        # 备份当前大纲和阶段状态（用于取消时恢复）
        previous_outline = project.outline
        todo_board = await user_ppt_service.get_project_todo_board(request.project_id, user_id=user.user_id)
        previous_stage_status = None
        if todo_board:
            for stage in todo_board.stages:
                if stage.id == "outline_generation":
                    previous_stage_status = {
                        "status": stage.status,
                        "progress": stage.progress,
                        "result": stage.result
                    }
                    break

        # 保存备份上下文到项目元数据（支持多实例部署）
        project_metadata = project.project_metadata or {}
        project_metadata["_regenerate_outline_context"] = {
            "previous_outline": previous_outline,
            "previous_stage_status": previous_stage_status,
            "user_id": user.user_id,
            "cancelled": False
        }
        await user_ppt_service.project_manager.update_project_metadata(
            request.project_id,
            project_metadata,
            user_id=user.user_id
        )

        # 重置大纲生成阶段状态为running
        logger.info(f"Setting outline_generation stage to running for project {request.project_id}")
        update_success = await user_ppt_service.update_project_stage(
            request.project_id,
            "outline_generation",
            "running",
            progress=0.0,
            user_id=user.user_id
        )
        logger.info(f"Update stage status result: {update_success}")

        # 将项目状态置为进行中（从failed状态恢复）
        await user_ppt_service.project_manager.update_project_status(
            request.project_id,
            "in_progress",
            user_id=user.user_id
        )

        # 获取页数设置
        page_count_settings = {
            "mode": confirmed_requirements.get("page_count_mode", "ai"),
            "min_pages": confirmed_requirements.get("min_pages", 8),
            "max_pages": confirmed_requirements.get("max_pages", 15),
            "fixed_pages": confirmed_requirements.get("fixed_pages", 10),
        }

        # 启动后台异步生成任务
        asyncio.create_task(
            _start_regenerate_outline_background(
                user_ppt_service,
                request.project_id,
                confirmed_requirements,
                page_count_settings,
                user.user_id
            )
        )

        # 获取更新后的看板
        todo_board = await user_ppt_service.get_project_todo_board(request.project_id, user_id=user.user_id)

        logger.info(f"User {user.user_id} started outline regeneration for project {request.project_id}")

        return RegenerateOutlineResponse(
            success=True,
            project_id=request.project_id,
            message="大纲重新生成已启动",
            todo_board=todo_board
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating outline: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重新生成大纲失败: {str(e)}")


# 取消重新生成大纲
@router.post("/outline/cancel-regenerate", response_model=CancelRegenerateOutlineResponse)
async def cancel_regenerate_outline(
        request: CancelRegenerateOutlineRequest,
        user: User = Depends(get_current_user_required)
):
    """
    取消重新生成大纲接口

    将状态恢复到重新生成之前：
    1. 验证项目存在且属于当前用户
    2. 设置取消标志（阻止后台任务写入数据库）
    3. 恢复之前备份的大纲
    4. 恢复之前的大纲生成阶段状态
    5. 不会删除项目

    注意：此接口仅用于取消重新生成操作，不会删除项目
    """
    try:
        # 获取用户特定的PPT服务实例
        user_ppt_service = get_ppt_service_for_user(user.user_id)

        # 验证项目存在且属于当前用户
        project = await user_ppt_service.project_manager.get_project(request.project_id, user_id=user.user_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在或无权访问")

        # 从数据库获取备份的上下文
        project_metadata = project.project_metadata or {}
        backup_context = project_metadata.get("_regenerate_outline_context")

        if not backup_context:
            # 没有备份上下文，可能是首次生成时的取消，提示用户使用cancel_generation
            raise HTTPException(
                status_code=400,
                detail="未找到重新生成的备份信息。如果是首次生成大纲，请使用 /outline/cancel-generation 接口"
            )

        # 验证备份上下文的用户ID
        if backup_context.get("user_id") != user.user_id:
            raise HTTPException(status_code=403, detail="无权操作此项目")

        # 首先设置取消标志，阻止后台任务继续写入数据库
        await _set_regenerate_cancelled_flag(user_ppt_service, request.project_id, user.user_id)

        # 恢复之前的大纲
        previous_outline = backup_context.get("previous_outline")
        if previous_outline is not None:
            await user_ppt_service.project_manager.save_project_outline(request.project_id, previous_outline)
        else:
            # 如果之前没有大纲，清空当前大纲
            await user_ppt_service.project_manager.save_project_outline(request.project_id, None)

        # 恢复之前的阶段状态
        previous_stage_status = backup_context.get("previous_stage_status")
        if previous_stage_status:
            await user_ppt_service.update_project_stage(
                request.project_id,
                "outline_generation",
                previous_stage_status.get("status", "completed"),
                progress=previous_stage_status.get("progress", 100.0),
                result=previous_stage_status.get("result"),
                user_id=user.user_id
            )
        else:
            # 如果没有之前的阶段状态，默认设置为completed
            await user_ppt_service.update_project_stage(
                request.project_id,
                "outline_generation",
                "completed",
                progress=100.0,
                user_id=user.user_id
            )

        # 注意：不在这里清理备份上下文，保留 cancelled=True 标志
        # 让后台任务在检测到取消后自己清理，避免竞态条件

        logger.info(f"User {user.user_id} cancelled outline regeneration for project {request.project_id}")

        return CancelRegenerateOutlineResponse(
            success=True,
            message="已取消重新生成，大纲已恢复到之前的状态",
            project_id=request.project_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling outline regeneration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消重新生成失败: {str(e)}")


# 更新大纲
@router.put("/projects/{project_id}/update-outline", response_model=UpdateOutlineResponse)
async def update_project_outline(
        project_id: str,
        request: UpdateOutlineRequest,
        user: User = Depends(get_current_user_required)
):
    """
    更新项目大纲接口

    当用户在前端编辑大纲内容后，调用此接口保存更新：
    1. 验证项目存在且属于当前用户
    2. 解析并验证大纲内容（支持JSON字符串或直接传递JSON对象）
    3. 更新项目的大纲数据
    4. 保存到数据库

    支持两种请求格式：
    格式1（直接传递JSON对象，推荐）：
    {
        "title": "大纲标题",
        "slides": [...],
        "metadata": {...}
    }

    格式2（传递JSON字符串）：
    {
        "outline_content": "{\"title\": \"...\", \"slides\": [...]}"
    }

    注意：
    - 此接口只是更新大纲内容，不会改变大纲的确认状态
    - 更新后大纲仍处于未确认状态，需要调用confirm-outline接口确认
    """
    try:
        # 获取用户特定的PPT服务实例
        user_ppt_service = get_ppt_service_for_user(user.user_id)

        # 验证项目存在且属于当前用户
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.user_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在或无权访问")

        # 检查大纲生成阶段是否已完成
        todo_board = await user_ppt_service.get_project_todo_board(project_id, user_id=user.user_id)
        if not todo_board:
            raise HTTPException(status_code=404, detail="TODO看板不存在")

        outline_stage = None
        for stage in todo_board.stages:
            if stage.id == "outline_generation":
                outline_stage = stage
                break

        if not outline_stage or outline_stage.status != "completed":
            raise HTTPException(status_code=400, detail="大纲生成尚未完成，无法更新")

        # 处理大纲内容：支持两种格式
        outline_content_str = None

        if request.outline_content:
            # 格式2：传递JSON字符串
            outline_content_str = request.outline_content
        elif request.slides is not None:
            # 格式1：直接传递JSON对象
            outline_dict = {
                "title": request.title or project.topic,
                "slides": request.slides,
                "content": request.content or "",
                "metadata": request.metadata or {},
                "confirmed": request.confirmed or False,
                "confirmed_at": request.confirmed_at
            }
            outline_content_str = json.dumps(outline_dict, ensure_ascii=False)
        else:
            raise HTTPException(status_code=400, detail="请提供大纲内容（outline_content或slides字段）")

        # 检测封面/目录/结束页开关状态并融合到 OutlineEditEvent 埋点上报
        _track_outline_edit_page_status(user.user_id, project_id, outline_content_str)


        # 更新大纲内容
        success = await user_ppt_service.update_project_outline(project_id, outline_content_str)

        if not success:
            raise HTTPException(status_code=500, detail="大纲更新失败")

        # 获取更新后的大纲
        updated_project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.user_id)

        logger.info(f"User {user.user_id} updated outline for project {project_id}")

        return UpdateOutlineResponse(
            success=True,
            message="大纲更新成功",
            outline=updated_project.outline
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating project outline: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新大纲失败: {str(e)}")


def _track_outline_edit_page_status(
        user_id: str,
        project_id: str,
        outline_content_str: str,
) -> None:
    """检测封面/目录/结束页开关状态并融合到 OutlineEditEvent 埋点上报

    从 update-outline 接口传入的大纲内容中解析 slides，
    检测 slide_type 为 title(封面)/agenda(目录)/thankyou(结束页) 的元素，
    读取其 enabled 属性（默认 True 表示开启），并将三种页面状态
    一次性上报为 OutlineEditEvent 埋点事件。

    埋点字段：
    - title_enabled：封面页是否开启
    - agenda_enabled：目录页是否开启
    - thankyou_enabled：结束页是否开启

    注意：
    - 埋点失败不影响 update-outline 主流程（异常被捕获并记录日志）
    - 每次 update-outline 调用都会上报一次携带页面状态的 OutlineEditEvent，
      用于统计"关闭封面/目录/结束页开关的PPT项目占比"
    """
    try:
        # 解析大纲内容
        try:
            outline_data = json.loads(outline_content_str)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"无法解析大纲内容为JSON，跳过页面状态埋点: project={project_id}")
            return

        slides = outline_data.get("slides", []) if isinstance(outline_data, dict) else []
        if not slides:
            return

        # 需要关注的页面类型：title(封面)/agenda(目录)/thankyou(结束页)
        # 默认均视为开启（enabled 默认为 True）
        page_status = {
            "title": True,
            "agenda": True,
            "thankyou": True,
        }

        for slide in slides:
            if not isinstance(slide, dict):
                continue

            # 获取页面类型（兼容 slide_type 或 type 字段）
            slide_type = str(slide.get("slide_type") or slide.get("type") or "").strip().lower()
            if slide_type not in page_status:
                continue

            # 获取 enabled 状态（默认 True 表示开启）
            page_status[slide_type] = bool(slide.get("enabled", True))

        # 上报埋点（融合到 OutlineEditEvent，携带页面状态字段）
        tracker.track(
            OutlineEditEvent,
            user_id=user_id,
            project_id=project_id,
            title_enabled=page_status["title"],
            agenda_enabled=page_status["agenda"],
            thankyou_enabled=page_status["thankyou"],
        )
        logger.info(
            f"大纲页面状态埋点: project={project_id}, user={user_id}, "
            f"title_enabled={page_status['title']}, agenda_enabled={page_status['agenda']}, "
            f"thankyou_enabled={page_status['thankyou']}"
        )
    except Exception as e:
        logger.warning(f"大纲页面状态埋点失败: project={project_id}, error={e}")



async def _process_uploaded_files(
        file_paths: Any,
        supplementary_description: Optional[str] = None
) -> str:
    """
    处理上传的文档文件，合并内容

    Args:
        file_paths: 已上传文件的对象列表，每个对象包含name(文件名)和key(OSS对象key)
        supplementary_description: 补充描述

    Returns:
        合并后的内容字符串
    """
    import os
    from .models import FileUploadItem
    from ..services.oss_service import get_oss_service

    all_processed_content = []
    temp_files_to_cleanup = []

    try:
        # 处理新的file_paths格式：对象列表，每个对象包含name和key
        for file_obj in file_paths:
            if isinstance(file_obj, FileUploadItem):
                # Pydantic模型对象
                file_name = file_obj.name
                file_key = file_obj.key
            elif isinstance(file_obj, dict):
                # 字典对象
                file_name = file_obj.get("name", "")
                file_key = file_obj.get("key", "")
            else:
                # 兼容旧的字符串格式（临时路径）
                file_name = os.path.basename(str(file_obj))
                file_key = str(file_obj)

            try:
                # 获取文件扩展名
                file_ext = os.path.splitext(file_name)[1] if file_name else ""

                # 创建临时目录和文件路径
                temp_dir = tempfile.mkdtemp(prefix="oss_download_")
                temp_file_path = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}_{file_name}")
                temp_files_to_cleanup.append(temp_file_path)
                temp_files_to_cleanup.append(temp_dir)

                # 从OSS下载文件
                oss_service = get_oss_service()
                logger.info(f"Downloading file from OSS by key: {file_key}")

                download_result = await oss_service.download_file(file_key)
                if not download_result.get("success"):
                    raise Exception(f"从OSS下载文件失败: {download_result.get('message', '未知错误')}")

                content = download_result["data"]
                if content is None or len(content) == 0:
                    raise Exception(f"下载文件内容为空，文件名: {file_name}")

                with open(temp_file_path, 'wb') as f:
                    f.write(content)

                logger.info(f"File downloaded from OSS to temp: {temp_file_path}, size: {len(content)}")

                # 处理文件
                file_result = await file_processor.process_file(
                    temp_file_path,
                    file_name,
                    file_processing_mode="markitdown",
                )

                all_processed_content.append({
                    "filename": file_name,
                    "content": file_result.processed_content
                })
            except Exception as e:
                logger.error(f"Failed to process file {file_name}: {e}")
                # 文件下载或解析失败时，直接抛出异常，阻断流程
                raise HTTPException(
                    status_code=400,
                    detail=f"文件处理失败: {file_name}, 错误: {str(e)}"
                )

        # 合并所有文件内容
        merged_content = file_processor.merge_multiple_files_to_markdown(all_processed_content)

        # 添加补充描述
        if supplementary_description:
            merged_content = f"{merged_content}\n\n【补充描述】\n{supplementary_description}"

        return merged_content

    finally:
        # 清理临时文件和目录
        import shutil
        for temp_path in temp_files_to_cleanup:
            try:
                if os.path.isdir(temp_path):
                    shutil.rmtree(temp_path, ignore_errors=True)
                    logger.debug(f"Cleaned up temp directory: {temp_path}")
                elif os.path.exists(temp_path):
                    os.unlink(temp_path)
                    logger.debug(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp path {temp_path}: {e}")


def _build_requirements_from_outline_request(request: GenerateOutlineRequest) -> str:
    """
    从GenerateOutlineRequest构建requirements字符串

    将用户在界面上的所有设置整合到requirements字段中
    """
    requirements_parts = []

    # 创建模式映射
    source_type_map = {
        "intelligent_creation": "智能创作PPT",
        "document_to_ppt": "文稿一键转PPT"
    }
    source_type_text = source_type_map.get(request.source_type, request.source_type)
    requirements_parts.append(f"创建模式：{source_type_text}")

    # 文本要求映射
    text_requirement_map = {
        "keep_original": "保留原文",
        "ai_expand": "AI扩写",
        "ai_summarize": "AI归纳"
    }
    text_requirement_text = text_requirement_map.get(request.text_requirement, request.text_requirement)
    requirements_parts.append(f"文本要求：{text_requirement_text}")

    # 页数设置映射
    page_count_mode_map = {
        "ai": "AI生成",
        "range": "范围",
        "fixed": "固定"
    }
    if request.page_count_mode == "ai":
        requirements_parts.append("页数：AI自动决定")
    elif request.page_count_mode == "range":
        requirements_parts.append(f"页数：{request.min_pages}-{request.max_pages}页")
    elif request.page_count_mode == "fixed":
        requirements_parts.append(f"页数：固定{request.fixed_pages}页")

    # 文本风格（仅智能创作PPT模式）
    if request.text_style:
        requirements_parts.append(f"文本风格：{request.text_style}")

    # 使用场景（仅智能创作PPT模式）
    if request.usage_scenario:
        requirements_parts.append(f"使用场景：{request.usage_scenario}")

    return "\n".join(requirements_parts)


async def _start_outline_generation_background(
        service,
        project_id: str,
        confirmed_requirements: Dict[str, Any],
        page_count_settings: Dict[str, Any]
):
    """后台任务：启动大纲生成（使用outline_harness）"""
    try:
        # 从confirmed_requirements获取user_id
        user_id = confirmed_requirements.get("user_id")

        # 更新大纲生成阶段状态为running
        await service.update_project_stage(
            project_id,
            "outline_generation",
            "running",
            progress=0.0,
            user_id=user_id
        )

        # 使用outline_harness生成大纲
        # outline_data = await _generate_outline_with_harness(confirmed_requirements, page_count_settings)
        #
        # if outline_data and outline_data.get("slides"):
        #     # 确保大纲数据格式正确
        #     if "title" not in outline_data:
        #         outline_data["title"] = confirmed_requirements.get("topic", "")
        #     if "metadata" not in outline_data:
        #         outline_data["metadata"] = {}
        # 使用GenerateOutlineRequest来保留所有参数
        from .models import GenerateOutlineRequest

        # 从confirmed_requirements重建GenerateOutlineRequest
        source_type = confirmed_requirements.get("source_type", "intelligent_creation")

        # 兼容旧数据：如果source_type是旧的值，需要转换
        legacy_source_type_map = {
            "paste": "intelligent_creation",
            "import": "document_to_ppt",
            "theme": "intelligent_creation",
            "beautify": "intelligent_creation"
        }
        mapped_source_type = legacy_source_type_map.get(source_type, source_type)

        request = GenerateOutlineRequest(
            source_type=mapped_source_type,
            title=confirmed_requirements.get("topic", ""),
            content=confirmed_requirements.get("description", ""),
            text_requirement=confirmed_requirements.get("text_requirement", "keep_original"),
            page_count_mode=confirmed_requirements.get("page_count_mode", "ai"),
            min_pages=confirmed_requirements.get("min_pages", 8),
            max_pages=confirmed_requirements.get("max_pages", 15),
            fixed_pages=confirmed_requirements.get("fixed_pages", 10),
            language=confirmed_requirements.get("language", "zh"),
            scenario=confirmed_requirements.get("type", "general"),
            user_id=confirmed_requirements.get("user_id"),
            text_style=confirmed_requirements.get("text_style"),
            usage_scenario=confirmed_requirements.get("usage_scenario"),
            enable_mcp_search=confirmed_requirements.get("enable_mcp_search", False),
        )

        # 调用非流式大纲生成接口，传递confirmed_requirements
        outline_start_time = time.time()
        outline = await service.generate_outline(request, page_count_settings, confirmed_requirements=confirmed_requirements)
        duration_ms = int((time.time() - outline_start_time) * 1000)

        if outline:
            # 更新项目大纲
            outline_data = {
                "title": outline.title,
                "slides": [slide.dict() if hasattr(slide, 'dict') else slide for slide in outline.slides],
                "metadata": outline.metadata or {}
            }

            # 最后一次检查是否已被取消
            ctx = await _get_regenerate_context(service, project_id, user_id)
            if ctx and ctx.get("cancelled"):
                logger.info(f"Outline regeneration was cancelled for project {project_id}, skipping outline save")
                return

            # 保存大纲到项目
            success = await service.project_manager.save_project_outline(project_id, outline_data)

            if success:
                # 更新大纲生成阶段状态为completed
                await service.update_project_stage(
                    project_id,
                    "outline_generation",
                    "completed",
                    progress=100.0,
                    result={"outline": outline_data},
                    user_id=user_id
                )
                # 更新项目状态为进行中（从failed状态恢复）
                await service.project_manager.update_project_status(
                    project_id,
                    "in_progress",
                    user_id=user_id
                )
                # 异步通知 ClawPartner 更新CP任务标题（失败不影响主流程）
                try:
                    from ..services.clawpartner_manage_service import clawpartner_manage_service
                    await clawpartner_manage_service.update_task_title(
                        chat_id=project_id,
                        title=outline.title,
                    )
                except Exception as e:
                    logger.warning(f"ClawPartner task title notification error: {str(e)}")

                # 异步调用ClawPartner发送招呼消息，通知用户大纲已完成生成
                try:
                    if user_id:
                        # 组装消息内容
                        msg = f"大纲已按您的需求生成完毕，点击即可进入编辑页调整结构。"
                        title = f"您的【{outline.title}】PPT大纲已准备就绪"

                        # 从 project_metadata 中读取创建项目时保存的 x_agent_id
                        x_agent_id = "default"
                        try:
                            project_for_agent = await service.project_manager.get_project(project_id, user_id=user_id)
                            if project_for_agent and project_for_agent.project_metadata:
                                x_agent_id = project_for_agent.project_metadata.get("x_agent_id")
                        except Exception as e:
                            logger.warning(f"[Outline] Failed to get x_agent_id from project metadata: {str(e)}")

                        await clawpartner_agent_service.send_notify_card(
                            employee_id=user_id,
                            msg=msg,
                            project_id=project_id,
                            title=title,
                            x_agent_id=x_agent_id
                        )
                    else:
                        logger.warning(f"[Outline] Cannot send notify card: user_id not found")
                except Exception as e:
                    logger.warning(f"[Outline] ClawPartner notify card send error: {str(e)}")

                logger.info(f"Background outline regeneration finished for project {project_id}")

                # 大纲生成结果埋点（成功）
                metadata = outline.metadata or {}
                tracker.track(
                    OutlineGenerateResultEvent,
                    user_id=user_id,
                    project_id=project_id,
                    success=True,
                    model=metadata.get("ai_model"),
                    prompt_tokens=metadata.get("prompt_tokens", 0),
                    completion_tokens=metadata.get("completion_tokens", 0),
                    duration_ms=duration_ms,
                    page_count=len(outline.slides),
                    is_regenerate=False,
                )
            else:
                logger.error(f"Failed to save regenerated outline for project {project_id}")
                await service.update_project_stage(
                    project_id,
                    "outline_generation",
                    "failed",
                    progress=0.0,
                    result={"error": "Failed to save outline"},
                    user_id=user_id
                )
                # 更新项目状态为失败
                await service.project_manager.update_project_status(
                    project_id,
                    "failed",
                    user_id=user_id
                )

                # 大纲生成结果埋点（保存失败）
                metadata = outline.metadata or {}
                tracker.track(
                    OutlineGenerateResultEvent,
                    user_id=user_id,
                    project_id=project_id,
                    success=False,
                    model=metadata.get("ai_model"),
                    prompt_tokens=metadata.get("prompt_tokens", 0),
                    completion_tokens=metadata.get("completion_tokens", 0),
                    duration_ms=duration_ms,
                    page_count=len(outline.slides),
                    is_regenerate=False,
                    error_msg="Failed to save outline",
                )
        else:
            logger.error(f"Outline regeneration returned empty result for project {project_id}")
            await service.update_project_stage(
                project_id,
                "outline_generation",
                "failed",
                progress=0.0,
                result={"error": "Outline generation returned empty result"},
                user_id=user_id
            )
            # 更新项目状态为失败
            await service.project_manager.update_project_status(
                project_id,
                "failed",
                user_id=user_id
            )

            # 大纲生成结果埋点（生成返回空结果）
            tracker.track(
                OutlineGenerateResultEvent,
                user_id=user_id,
                project_id=project_id,
                success=False,
                duration_ms=duration_ms,
                is_regenerate=False,
                error_msg="Outline generation returned empty result",
            )
    except Exception as e:
        logger.error(f"Error in background outline generation: {str(e)}")
        # 标记阶段为失败
        try:
            await service.update_project_stage(
                project_id,
                "outline_generation",
                "failed",
                progress=0.0,
                result={"error": str(e)},
                user_id=confirmed_requirements.get("user_id")
            )
            # 更新项目状态为失败
            await service.project_manager.update_project_status(
                project_id,
                "failed",
                user_id=confirmed_requirements.get("user_id")
            )
        except Exception as update_error:
            logger.error(f"Error updating stage status: {update_error}")

        # 大纲生成结果埋点（异常失败）
        try:
            duration_ms = int((time.time() - outline_start_time) * 1000)
        except NameError:
            duration_ms = 0
        tracker.track(
            OutlineGenerateResultEvent,
            user_id=confirmed_requirements.get("user_id"),
            project_id=project_id,
            success=False,
            duration_ms=duration_ms,
            is_regenerate=False,
            error_msg=str(e),
        )


async def _get_regenerate_context(service, project_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """从数据库获取重新生成的上下文"""
    try:
        project = await service.project_manager.get_project(project_id, user_id=user_id)
        if not project or not project.project_metadata:
            return None
        return project.project_metadata.get("_regenerate_outline_context")
    except Exception as e:
        logger.error(f"Error getting regenerate context: {e}")
        return None


async def _set_regenerate_cancelled_flag(service, project_id: str, user_id: str) -> bool:
    """设置取消标志到数据库"""
    try:
        project = await service.project_manager.get_project(project_id, user_id=user_id)
        if not project:
            logger.warning(f"Project {project_id} not found when setting cancelled flag")
            return False
        project_metadata = project.project_metadata or {}
        ctx = project_metadata.get("_regenerate_outline_context")
        if ctx:
            ctx["cancelled"] = True
            ctx["cancelled_at"] = time.time()  # 添加取消时间戳用于调试
            await service.project_manager.update_project_metadata(project_id, project_metadata, user_id=user_id)
            logger.info(f"Set cancelled flag for project {project_id}, ctx: {ctx}")
            return True
        else:
            logger.warning(f"No regenerate context found for project {project_id}")
        return False
    except Exception as e:
        logger.error(f"Error setting cancelled flag: {e}")
        return False


async def _start_regenerate_outline_background(
        service,
        project_id: str,
        confirmed_requirements: Dict[str, Any],
        page_count_settings: Dict[str, Any],
        user_id: str
):
    """后台任务：重新生成大纲（使用outline_harness）"""
    try:
        # 判断source_type来确定生成方式
        source_type = confirmed_requirements.get("source_type", "intelligent_creation")

        # 初始化processed_content
        processed_content = confirmed_requirements.get("description", "")

        # 如果有上传文件，需要重新处理
        uploaded_files = confirmed_requirements.get("uploaded_files", [])
        if uploaded_files:
            # 将uploaded_files转换为FileUploadItem列表
            file_paths = []
            for file_obj in uploaded_files:
                file_paths.append(FileUploadItem(
                    name=file_obj.get("name", ""),
                    key=file_obj.get("key", "")
                ))

            # 重新处理文档文件
            try:
                file_content = await _process_uploaded_files(file_paths, None)

                # 根据模式处理内容
                if source_type == "intelligent_creation":
                    # 智能创作PPT模式：文件内容作为背景资料
                    processed_content = f"{processed_content}\n\n【背景资料】\n{file_content}"
                elif source_type == "document_to_ppt":
                    # 文稿一键转PPT模式：文件内容作为主要内容
                    processed_content = file_content

                # 更新confirmed_requirements中的description
                confirmed_requirements = dict(confirmed_requirements)
                confirmed_requirements["description"] = processed_content
            except Exception as file_error:
                logger.error(f"Error processing uploaded files for regeneration: {file_error}")
                # 检查是否已被取消
                ctx = await _get_regenerate_context(service, project_id, user_id)
                if ctx and ctx.get("cancelled"):
                    logger.info(f"Outline regeneration was cancelled for project {project_id}, skipping error handling")
                    return
                await service.update_project_stage(
                    project_id,
                    "outline_generation",
                    "failed",
                    progress=0.0,
                    result={"error": f"文件处理失败: {str(file_error)}"},
                    user_id=user_id
                )
                # 更新项目状态为失败
                await service.project_manager.update_project_status(
                    project_id,
                    "failed",
                    user_id=user_id
                )
                # 清理备份上下文
                await _clear_regenerate_context(service, project_id, user_id)
                return

        # 检查是否已被取消
        ctx = await _get_regenerate_context(service, project_id, user_id)
        if ctx and ctx.get("cancelled"):
            logger.info(f"Outline regeneration was cancelled for project {project_id}, before generation")
            return

        # 重建GenerateOutlineRequest
        # 注意：source_type需要映射到新的值
        # 兼容旧数据：如果source_type是旧的值，需要转换
        legacy_source_type_map = {
            "paste": "intelligent_creation",
            "import": "document_to_ppt",
            "theme": "intelligent_creation",
            "beautify": "intelligent_creation"
        }
        mapped_source_type = legacy_source_type_map.get(source_type, source_type)

        request = GenerateOutlineRequest(
            source_type=mapped_source_type,
            title=confirmed_requirements.get("topic", ""),
            content=processed_content if mapped_source_type == "intelligent_creation" else None,
            text_requirement=confirmed_requirements.get("text_requirement", "keep_original"),
            page_count_mode=confirmed_requirements.get("page_count_mode", "ai"),
            min_pages=confirmed_requirements.get("min_pages", 8),
            max_pages=confirmed_requirements.get("max_pages", 15),
            fixed_pages=confirmed_requirements.get("fixed_pages", 10),
            language=confirmed_requirements.get("language", "zh"),
            scenario=confirmed_requirements.get("type", "general"),
            user_id=user_id,
            text_style=confirmed_requirements.get("text_style"),
            usage_scenario=confirmed_requirements.get("usage_scenario"),
            enable_mcp_search=confirmed_requirements.get("enable_mcp_search", False),
        )

        # 调用大纲生成
        outline_start_time = time.time()
        outline = await service.generate_outline(request, page_count_settings, confirmed_requirements=confirmed_requirements)
        duration_ms = int((time.time() - outline_start_time) * 1000)

        # 在写入数据库之前，再次检查是否已被取消
        ctx = await _get_regenerate_context(service, project_id, user_id)
        if ctx and ctx.get("cancelled"):
            logger.info(f"Outline regeneration was cancelled for project {project_id}, skipping database write")
            return

        # 检查大纲是否生成成功
        if outline:
            # 更新项目大纲
            outline_data = {
                "title": outline.title,
                "slides": [slide.dict() if hasattr(slide, 'dict') else slide for slide in outline.slides],
                "metadata": outline.metadata or {}
            }

            # 最后一次检查是否已被取消
            ctx = await _get_regenerate_context(service, project_id, user_id)
            if ctx and ctx.get("cancelled"):
                logger.info(f"Outline regeneration was cancelled for project {project_id}, skipping outline save")
                return

            # 保存大纲到项目
            success = await service.project_manager.save_project_outline(project_id, outline_data)

            if success:
                # 更新大纲生成阶段状态为completed
                await service.update_project_stage(
                    project_id,
                    "outline_generation",
                    "completed",
                    progress=100.0,
                    result={"outline": outline_data},
                    user_id=user_id
                )
                # 更新项目状态为进行中（从failed状态恢复）
                await service.project_manager.update_project_status(
                    project_id,
                    "in_progress",
                    user_id=user_id
                )
                # 异步调用ClawPartner发送招呼消息，通知用户大纲已完成生成
                try:
                    if user_id:
                        # 组装消息内容
                        msg = f"大纲已按您的需求生成完毕，点击即可进入编辑页调整结构。"
                        title = f"您的【{outline.title}】PPT大纲已准备就绪"

                        # 从 project_metadata 中读取创建项目时保存的 x_agent_id
                        x_agent_id = "default"
                        try:
                            project_for_agent = await service.project_manager.get_project(project_id, user_id=user_id)
                            if project_for_agent and project_for_agent.project_metadata:
                                x_agent_id = project_for_agent.project_metadata.get("x_agent_id")
                        except Exception as e:
                            logger.warning(f"[RE_Outline] Failed to get x_agent_id from project metadata: {str(e)}")

                        await clawpartner_agent_service.send_notify_card(
                            employee_id=user_id,
                            msg=msg,
                            project_id=project_id,
                            title=title,
                            x_agent_id=x_agent_id
                        )
                    else:
                        logger.warning(f"[RE_Outline] Cannot send notify card: user_id not found")
                except Exception as e:
                    logger.warning(f"[RE_Outline] ClawPartner notify card send error: {str(e)}")

                logger.info(f"Background outline regeneration finished for project {project_id}")

                # 大纲生成结果埋点（成功）
                metadata = outline.metadata or {}
                tracker.track(
                    OutlineGenerateResultEvent,
                    user_id=user_id,
                    project_id=project_id,
                    success=True,
                    model=metadata.get("ai_model"),
                    prompt_tokens=metadata.get("prompt_tokens", 0),
                    completion_tokens=metadata.get("completion_tokens", 0),
                    duration_ms=duration_ms,
                    page_count=len(outline.slides),
                    is_regenerate=True,
                )
            else:
                logger.error(f"Failed to save regenerated outline for project {project_id}")
                await service.update_project_stage(
                    project_id,
                    "outline_generation",
                    "failed",
                    progress=0.0,
                    result={"error": "Failed to save outline"},
                    user_id=user_id
                )
                # 更新项目状态为失败
                await service.project_manager.update_project_status(
                    project_id,
                    "failed",
                    user_id=user_id
                )

                # 大纲生成结果埋点（保存失败）
                metadata = outline.metadata or {}
                tracker.track(
                    OutlineGenerateResultEvent,
                    user_id=user_id,
                    project_id=project_id,
                    success=False,
                    model=metadata.get("ai_model"),
                    prompt_tokens=metadata.get("prompt_tokens", 0),
                    completion_tokens=metadata.get("completion_tokens", 0),
                    duration_ms=duration_ms,
                    page_count=len(outline.slides),
                    is_regenerate=True,
                    error_msg="Failed to save outline",
                )
        else:
            logger.error(f"Outline regeneration returned empty result for project {project_id}")
            await service.update_project_stage(
                project_id,
                "outline_generation",
                "failed",
                progress=0.0,
                result={"error": "Outline generation returned empty result"},
                user_id=user_id
            )
            # 更新项目状态为失败
            await service.project_manager.update_project_status(
                project_id,
                "failed",
                user_id=user_id
            )

            # 大纲生成结果埋点（生成返回空结果）
            tracker.track(
                OutlineGenerateResultEvent,
                user_id=user_id,
                project_id=project_id,
                success=False,
                duration_ms=duration_ms,
                is_regenerate=True,
                error_msg="Outline generation returned empty result",
            )
    except Exception as e:
        logger.error(f"Error in background outline regeneration: {str(e)}")
        # 检查是否已被取消
        ctx = await _get_regenerate_context(service, project_id, user_id)
        logger.info(f"Checking cancel flag in exception handler for project {project_id}, ctx: {ctx}")
        if ctx and ctx.get("cancelled"):
            logger.info(f"Outline regeneration was cancelled for project {project_id}, skipping error status update")
            return
        # 标记阶段为失败
        logger.warning(f"Outline regeneration failed for project {project_id}, will update status to failed")
        try:
            await service.update_project_stage(
                project_id,
                "outline_generation",
                "failed",
                progress=0.0,
                result={"error": str(e)},
                user_id=user_id
            )
            # 更新项目状态为失败
            await service.project_manager.update_project_status(
                project_id,
                "failed",
                user_id=user_id
            )
        except Exception as update_error:
            logger.error(f"Error updating stage status: {update_error}")

        # 大纲生成结果埋点（异常失败）
        try:
            duration_ms = int((time.time() - outline_start_time) * 1000)
        except NameError:
            duration_ms = 0
        tracker.track(
            OutlineGenerateResultEvent,
            user_id=user_id,
            project_id=project_id,
            success=False,
            duration_ms=duration_ms,
            is_regenerate=True,
            error_msg=str(e),
        )
    finally:
        # 清理备份上下文（仅当未被取消时）
        ctx = await _get_regenerate_context(service, project_id, user_id)
        logger.info(f"Checking cancel flag in finally handler for project {project_id}, cancelled: {ctx.get('cancelled') if ctx else 'no ctx'}")
        if not ctx or not ctx.get("cancelled"):
            await _clear_regenerate_context(service, project_id, user_id)
            logger.info(f"Cleared regenerate context for project {project_id}")


async def _clear_regenerate_context(service, project_id: str, user_id: str):
    """清理数据库中的重新生成上下文"""
    try:
        project = await service.project_manager.get_project(project_id, user_id=user_id)
        if not project:
            return
        project_metadata = project.project_metadata or {}
        if "_regenerate_outline_context" in project_metadata:
            del project_metadata["_regenerate_outline_context"]
            await service.project_manager.update_project_metadata(project_id, project_metadata, user_id=user_id)
    except Exception as e:
        logger.error(f"Error clearing regenerate context: {e}")


async def _set_adapted_outline_task_state(service, project_id: str, user_id: str,
                                           task_id: str, status: str, **changes):
    """Persist task state on the project so polling works across workers."""
    project = await service.project_manager.get_project(project_id, user_id=user_id)
    if not project:
        return
    metadata = dict(project.project_metadata or {})
    task = dict(metadata.get("_adapted_outline_task") or {})
    if task.get("task_id") != task_id:
        return
    task.update(changes)
    task["status"] = status
    metadata["_adapted_outline_task"] = task
    await service.project_manager.update_project_metadata(project_id, metadata, user_id=user_id)


async def _run_adapted_outline_task(service, project_id: str, user_id: str,
                                    task_id: str, requested_mode: str):
    """Generate with the company's request model and project stage API."""
    from ..services.outline.constrained_outline_generation_service import ConstrainedOutlineGenerationService

    try:
        project = await service.project_manager.get_project(project_id, user_id=user_id)
        if not project:
            raise ValueError("项目不存在或无权访问")
        confirmed = dict(project.confirmed_requirements or {})
        if not confirmed:
            raise ValueError("项目需求尚未确认")

        source_type = confirmed.get("source_type", "intelligent_creation")
        source_type = {
            "paste": "intelligent_creation", "theme": "intelligent_creation",
            "beautify": "intelligent_creation", "import": "document_to_ppt",
        }.get(source_type, source_type)
        original_text = (project.project_metadata or {}).get("_original_request_content") or confirmed.get("description", "")
        constrained = ConstrainedOutlineGenerationService(service)
        decision = (
            await constrained.classify_generation_mode(original_text)
            if requested_mode == "smart" else {"mode": "strict", "parser": "explicit"}
        )
        selected_mode = decision.get("mode", "original")
        await _set_adapted_outline_task_state(
            service, project_id, user_id, task_id, "running",
            selected_generation_mode=selected_mode, mode_reason=decision.get("reason", ""),
        )

        processed_content = confirmed.get("description", "")
        uploaded_files = confirmed.get("uploaded_files") or []
        if uploaded_files:
            file_items = [FileUploadItem(name=item.get("name", ""), key=item.get("key", ""))
                          for item in uploaded_files]
            file_content = await _process_uploaded_files(file_items, None)
            if source_type == "document_to_ppt":
                processed_content = file_content
            else:
                processed_content = f"{processed_content}\n\n【背景资料】\n{file_content}"

        generation_confirmed = dict(confirmed)
        generation_confirmed["description"] = processed_content
        request = GenerateOutlineRequest(
            source_type=source_type,
            title=confirmed.get("topic", ""),
            content=processed_content if source_type == "intelligent_creation" else None,
            text_requirement=confirmed.get("text_requirement", "keep_original"),
            page_count_mode=confirmed.get("page_count_mode", "ai"),
            min_pages=confirmed.get("min_pages", 8),
            max_pages=confirmed.get("max_pages", 15),
            fixed_pages=confirmed.get("fixed_pages", 10),
            language=confirmed.get("language", "zh"),
            scenario=confirmed.get("type", "general"),
            user_id=user_id,
            text_style=confirmed.get("text_style"),
            usage_scenario=confirmed.get("usage_scenario"),
            enable_mcp_search=confirmed.get("enable_mcp_search", False),
        )
        page_count_settings = {
            "mode": confirmed.get("page_count_mode", "ai"),
            "min_pages": confirmed.get("min_pages", 8),
            "max_pages": confirmed.get("max_pages", 15),
            "fixed_pages": confirmed.get("fixed_pages", 10),
        }

        constraints = None
        if selected_mode == "strict":
            constraints = await constrained.extract_constraints_with_llm(original_text)
            if constraints.get("intent_parse_failed"):
                selected_mode = "original"
                await _set_adapted_outline_task_state(
                    service, project_id, user_id, task_id, "running",
                    selected_generation_mode="original", fallback_reason=constraints.get("intent_parse_error"),
                )
            else:
                extra_prompt = constrained._constraint_prompt(constraints)
                if extra_prompt:
                    if source_type == "intelligent_creation":
                        request.content = f"{request.content or ''}{extra_prompt}"
                    generation_confirmed["description"] = f"{processed_content}{extra_prompt}"

        outline = await service.generate_outline(
            request, page_count_settings, confirmed_requirements=generation_confirmed
        )
        if not outline:
            raise RuntimeError("生成器未返回大纲")
        outline_data = {
            "title": outline.title,
            "slides": [slide.dict() if hasattr(slide, "dict") else slide for slide in outline.slides],
            "metadata": dict(outline.metadata or {}),
        }
        if selected_mode == "strict":
            outline_data = constrained._ensure_cover_and_agenda(outline_data)
            target = constraints.get("requested_total_pages")
            if target and constraints.get("page_count_scope") == "content_only":
                target += constrained.FIXED_PREFIX_PAGES
            if not target and page_count_settings.get("mode") == "fixed":
                target = page_count_settings.get("fixed_pages")
            if target:
                outline_data = constrained._normalize_page_count(outline_data, int(target), constraints)
            outline_data = constrained._enforce_page_constraints(outline_data, constraints)
            outline_data["metadata"]["constraint_parser"] = constraints.get("parser")
        outline_data["metadata"].update({
            "generation_entrypoint": f"{requested_mode}-{selected_mode}",
            "generation_request_id": task_id,
            "selected_generation_mode": selected_mode,
        })

        context = await _get_regenerate_context(service, project_id, user_id)
        if context and context.get("cancelled"):
            await _set_adapted_outline_task_state(service, project_id, user_id, task_id, "cancelled")
            return
        saved = await service.project_manager.save_project_outline(project_id, outline_data)
        if not saved:
            raise RuntimeError("大纲保存失败")
        await service.update_project_stage(
            project_id, "outline_generation", "completed", progress=100.0,
            result={"outline": outline_data}, user_id=user_id,
        )
        await service.project_manager.update_project_status(project_id, "in_progress", user_id=user_id)
        await _set_adapted_outline_task_state(
            service, project_id, user_id, task_id, "completed",
            selected_generation_mode=selected_mode,
        )
        await _clear_regenerate_context(service, project_id, user_id)
    except Exception as exc:
        logger.exception("Adapted outline generation failed: project=%s task=%s", project_id, task_id)
        await service.update_project_stage(
            project_id, "outline_generation", "failed", progress=0.0,
            result={"error": str(exc)}, user_id=user_id,
        )
        await _set_adapted_outline_task_state(
            service, project_id, user_id, task_id, "failed", error=str(exc),
        )


async def _create_adapted_outline_task(project_id: str, mode: str, user: User):
    service = get_ppt_service_for_user(user.user_id)
    project = await service.project_manager.get_project(project_id, user_id=user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    if not project.confirmed_requirements:
        raise HTTPException(status_code=400, detail="项目需求尚未确认")
    metadata = dict(project.project_metadata or {})
    previous = metadata.get("_adapted_outline_task") or {}
    if previous.get("status") in {"pending", "running"}:
        previous_task_id = previous.get("task_id")
        return JSONResponse(status_code=409, content={
            "status": "already_processing", "task_id": previous_task_id,
            "polling_endpoint": f"/projects/{project_id}/outline-generation-tasks/{previous_task_id}",
        })

    task_id = str(uuid.uuid4())
    metadata["_adapted_outline_task"] = {
        "task_id": task_id, "status": "pending", "requested_mode": mode,
        "user_id": user.user_id, "created_at": time.time(),
    }
    metadata["_regenerate_outline_context"] = {
        "previous_outline": project.outline,
        "previous_stage_status": None,
        "user_id": user.user_id,
        "cancelled": False,
    }
    await service.project_manager.update_project_metadata(project_id, metadata, user_id=user.user_id)
    await service.update_project_stage(
        project_id, "outline_generation", "running", progress=0.0, user_id=user.user_id
    )
    asyncio.create_task(_run_adapted_outline_task(service, project_id, user.user_id, task_id, mode))
    return {
        "status": "accepted", "task_id": task_id,
        "generation_request_id": task_id,
        "polling_endpoint": f"/projects/{project_id}/outline-generation-tasks/{task_id}",
    }


@router.post("/projects/{project_id}/generate-outline-constrained")
async def create_constrained_outline_generation_task(
        project_id: str, user: User = Depends(get_current_user_required)):
    return await _create_adapted_outline_task(project_id, "strict", user)


@router.post("/projects/{project_id}/generate-outline-smart")
async def create_smart_outline_generation_task(
        project_id: str, user: User = Depends(get_current_user_required)):
    return await _create_adapted_outline_task(project_id, "smart", user)


@router.get("/projects/{project_id}/outline-generation-tasks/{task_id}")
async def get_adapted_outline_task_status(
        project_id: str, task_id: str, user: User = Depends(get_current_user_required)):
    service = get_ppt_service_for_user(user.user_id)
    project = await service.project_manager.get_project(project_id, user_id=user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    task = (project.project_metadata or {}).get("_adapted_outline_task") or {}
    outline = project.outline if isinstance(project.outline, dict) else {}
    outline_metadata = outline.get("metadata") or {}
    if outline_metadata.get("generation_request_id") == task_id and isinstance(outline.get("slides"), list):
        return {
            "task_id": task_id, "status": "completed", "progress": 100.0,
            "result": {"success": True, "outline": outline},
            "recovered_from_project": task.get("status") != "completed",
        }
    if task.get("task_id") != task_id:
        raise HTTPException(status_code=404, detail="Task not found")
    response = {
        "task_id": task_id, "status": task.get("status", "pending"),
        "progress": 100.0 if task.get("status") == "completed" else 0.0,
        "selected_generation_mode": task.get("selected_generation_mode"),
        "message": "正在生成大纲" if task.get("status") in {"pending", "running"} else "",
    }
    if task.get("error"):
        response["error"] = task["error"]
    return response


def _get_file_extension(filename: str) -> str:
    """获取文件扩展名（小写）"""
    import os
    _, ext = os.path.splitext(filename)
    return ext.lower()
