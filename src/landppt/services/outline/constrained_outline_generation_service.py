"""Model-led strict outline workflow, isolated from the original generator."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .strict_outline_requirements import InvalidModelResponse, PlanValidationError, StrictOutlineRequirements


class ModelUnavailable(RuntimeError):
    """The model could not return a usable response after bounded retries."""


class ConstrainedOutlineGenerationService:
    VERSION = "strict-outline-v5"

    def __init__(self, ppt_service: Any):
        self.ppt_service = ppt_service

    @staticmethod
    def _extract_json_object(content: str) -> Optional[Dict[str, Any]]:
        if not isinstance(content, str):
            return None
        content = content.strip()
        start, end = content.find("{"), content.rfind("}")
        try:
            value = json.loads(content[start:end + 1] if start >= 0 else content)
            return value if isinstance(value, dict) else None
        except ValueError:
            return None

    async def _ask_json(self, prompt, validate):
        """Three calls maximum per stage, with targeted JSON/contract repair."""
        current_prompt = prompt
        last_error = "模型未返回有效结果"
        validation_error = None
        for _ in range(3):
            try:
                response = await self.ppt_service._text_completion_for_role(
                    "outline", prompt=current_prompt, temperature=0.0,
                )
            except Exception as exc:
                last_error = str(exc)
                # Keep an outstanding repair request when its call fails.
                continue
            raw = getattr(response, "content", "")
            parsed = self._extract_json_object(raw)
            if parsed is None:
                last_error = "不是有效 JSON 对象"
            else:
                try:
                    return validate(parsed)
                except InvalidModelResponse as exc:
                    last_error = str(exc)
                except PlanValidationError as exc:
                    validation_error = exc
                    last_error = str(exc)
            current_prompt = (
                f"{prompt}\n\n上次输出未通过校验：{last_error}\n"
                "请修正上次结果，返回完整有效 JSON，不要省略原始需求或弱化已确定的约束。"
                f"\n上次输出（仅供修复）：\n{raw}\n"
            )
        # Semantic/structural conflicts must not silently become legacy success.
        if validation_error is not None:
            raise PlanValidationError(f"严格大纲校验未通过：{validation_error}")
        raise ModelUnavailable(last_error)

    async def classify_generation_mode(self, text: str) -> Dict[str, Any]:
        prompt = f"""你是 PPT 生成方案路由器。通读用户需求，以用户是否明确指定页面内的具体内容为核心判断，不按关键词或固定句式分类。
strict：用户已完整描述演示所需的各页具体内容，正文内容及页面分配已确定，生成时主要需要保留内容并补齐结构。无需用户额外声明“严格保留”或“禁止合并”。
original：用户只提供笼统要求、未分配到页面的背景材料，或仅指定部分页面内容，其余实质内容仍需要自由规划。
判断的是页面内容要求的具体程度，不是任务属于新建、修改、美化还是优化，也不是输入是否为已经组织好的文档。
“完整”指实质内容完整，不要求用户提供封面、目录、过渡、结束页；缺少这些特殊页与选择模式无关。仅部分页面具体、其余交由模型补充正文时选择 original。只有总页数而没有页面内具体内容，也不单独构成 strict 的依据。
结合上下文区分实际页面要求与仅供参考的示例、文档章节或素材编号；若明确允许完全打散重新组织，不将旧分页当作页面要求。
例如：美化完整逐页素材，或完整给出所有正文页面但没有封面目录，应选择 strict；只指定开头几页、其余让模型发挥，或仅提供主题和背景材料，应选择 original。
只返回 JSON：{{"mode":"strict 或 original","reason":"说明页面内具体内容是否已被指定的简短依据"}}。
用户需求：\n{text}"""

        def validate(value):
            if value.get("mode") not in ("strict", "original"):
                raise PlanValidationError("mode 必须为 strict 或 original")
            return {"mode": value["mode"], "reason": str(value.get("reason", "")), "parser": "llm"}

        try:
            return await self._ask_json(prompt, validate)
        except (ModelUnavailable, PlanValidationError) as exc:
            return {"mode": "original", "reason": str(exc), "parser": "llm_failed"}

    async def generate(self, project_id: str, request: Any,
                       page_count_settings: Optional[Dict[str, Any]] = None,
                       generation_request_id: Optional[str] = None,
                       confirmed_requirements: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raw_text = "\n".join(str(value) for value in [
            getattr(request, "requirements", ""), getattr(request, "content", ""),
            getattr(request, "description", ""),
        ] if value)
        topic = getattr(request, "topic", "") or "演示文稿"
        requirements_service = StrictOutlineRequirements()
        try:
            intent = await self._ask_json(
                requirements_service.requirements_prompt(raw_text, topic),
                lambda value: requirements_service.validate_requirements(value, raw_text),
            )
            requirements_service.add_page_settings(intent, page_count_settings or {})
            outline_data = await self._ask_json(
                requirements_service.outline_prompt(intent, request),
                lambda value: requirements_service.validate_outline(value, intent),
            )
            outline_data["metadata"] = {
                "generation_entrypoint": "constrained-stage1",
                "constraint_parser": "llm",
                "structure_policy": "final_page_count_tiers",
                "strict_workflow_version": self.VERSION,
                "structure_band": requirements_service.band(len(outline_data["slides"])),
                "page_requirements": intent,
                "page_count_source": intent["page_count_resolution"]["source"],
                "page_count_resolution": intent["page_count_resolution"],
                "constraint_validation": {"passed": True, "version": self.VERSION},
                "total_pages": len(outline_data["slides"]),
                "total_slides": len(outline_data["slides"]),
                "actual_page_count": len(outline_data["slides"]),
                "language": getattr(request, "language", "zh"),
                "scenario": getattr(request, "scenario", "general"),
                "generated_with_ai": True,
            }
        except ModelUnavailable as exc:
            # Preserve the real original generator's API and request unchanged.
            outline = await self.ppt_service.generate_outline(request, page_count_settings)
            outline_data = {"title": outline.title, "slides": outline.slides,
                            "metadata": dict(outline.metadata or {})}
            outline_data["metadata"].update({
                "generation_entrypoint": "constrained-stage1-fallback-original",
                "constraint_parser": "llm_failed",
                "constraint_validation": {"skipped": True, "passed": False, "reason": str(exc)},
            })
        if generation_request_id:
            outline_data["metadata"]["generation_request_id"] = generation_request_id
        await self.ppt_service._update_outline_generation_stage(project_id, outline_data)
        return outline_data
