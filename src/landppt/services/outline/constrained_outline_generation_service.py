"""First-stage constrained outline generation.

This service intentionally lives beside the existing outline workflow.  It is
used only by the new constrained-generation endpoint and does not change the
legacy generation paths.
"""

from __future__ import annotations

import re
import json
from copy import deepcopy
from typing import Any, Dict, List, Optional


class ConstrainedOutlineGenerationService:
    """Wrap the legacy generator with first-stage hard-constraint handling."""

    VERSION = "stage1"
    FIXED_PREFIX_PAGES = 2

    def __init__(self, ppt_service: Any):
        self.ppt_service = ppt_service

    @staticmethod
    def _extract_json_object(content: str) -> Optional[Dict[str, Any]]:
        content = (content or "").strip()
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content, re.IGNORECASE)
        candidate = fenced.group(1) if fenced else content
        if not fenced:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start:end + 1]
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    @classmethod
    def _normalize_llm_constraints(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only the small, stable contract used by the stage-1 planner."""
        normalized_pages: List[Dict[str, Any]] = []
        for raw in value.get("page_constraints") or []:
            if not isinstance(raw, dict):
                continue
            page_number = raw.get("page_number")
            if page_number is not None:
                try:
                    page_number = int(page_number)
                except (TypeError, ValueError):
                    continue
                if page_number < 1:
                    continue
            requirements = raw.get("must_include") or raw.get("requirements") or []
            if isinstance(requirements, str):
                requirements = [requirements]
            requirements = [str(item).strip() for item in requirements if str(item).strip()]
            if not requirements:
                continue
            semantics = raw.get("reference_semantics") or value.get("reference_semantics") or "content_page"
            if semantics not in {"content_page", "final_page"}:
                semantics = "content_page"
            item = {
                "page_number": page_number,
                "must_include": requirements,
                "priority": "hard",
                "reference_semantics": semantics,
            }
            if raw.get("position") == "last" or raw.get("page_number") in {"last", "最后一页", "末页"}:
                item["page_number"] = None
                item["position"] = "last"
                item["reference_semantics"] = "final_page"
            if raw.get("slide_type") in {"title", "agenda", "transition", "content", "conclusion", "thankyou"}:
                item["slide_type"] = raw["slide_type"]
            normalized_pages.append(item)
        normalized_pages.sort(key=lambda item: (item.get("page_number") is None, item.get("page_number") or 0))
        total_pages = value.get("requested_total_pages")
        try:
            total_pages = int(total_pages) if total_pages is not None else None
        except (TypeError, ValueError):
            total_pages = None
        scope = value.get("page_count_scope") or "final_presentation"
        if scope not in {"final_presentation", "content_only"}:
            scope = "final_presentation"
        semantics = value.get("reference_semantics") or "content_page"
        if semantics not in {"content_page", "final_page", "mixed"}:
            semantics = "content_page"
        return {
            "page_constraints": normalized_pages,
            "requested_total_pages": total_pages,
            "page_count_scope": scope,
            "reference_semantics": semantics,
            "parser": "llm",
            "parser_version": cls.VERSION,
        }

    async def extract_constraints_with_llm(self, text: str) -> Dict[str, Any]:
        """Use the outline model to resolve page-reference intent.

        The model is asked only for intent extraction, not outline generation.
        This keeps the decision auditable and prevents the main generation
        prompt from having to infer page-number semantics itself.
        """
        text = (text or "").strip()
        if not text:
            return {
                "page_constraints": [],
                "requested_total_pages": None,
                "page_count_scope": "final_presentation",
                "reference_semantics": "content_page",
                "parser": "llm",
                "parser_version": self.VERSION,
            }
        prompt = f"""
你是 PPT 需求意图解析器，不负责生成大纲。请分析下面的用户原始需求，识别页面级硬约束和页码语义。

请先理解用户想讲什么、希望怎样组织内容，以及哪些要求必须保留，再提取结构化约束。
结合完整上下文、页面承担的表达功能、叙述顺序、数量的指代范围和要求之间的关系进行判断。
不要将任何特定词语、句式或编号形式作为判定某种意图的必要条件或充分条件；相同措辞在不同上下文中可以表达不同意图。

产品结构要求：最终 PPT 以封面、目录开头。用户未描述的封面和目录由后续生成环节补充。
判断用户是在安排正文内容的先后顺序，还是在定位完整演示文稿中的页面：
- content_page 表示正文内容序列中的位置。若用户实际描述的是实质内容，即使将其称为第一页，也应保留为正文，并在前面补充封面和目录。内容区第 1 页最终对应第 3 页。
- final_page 表示完整演示文稿中的位置。只有上下文整体支持这种定位意图时才采用，不要求用户使用某种特定表述。
- 同一需求可以包含两种定位方式，请逐条判断；顶层 reference_semantics 在这种情况下为 mixed。
页面类型应根据该页承担的功能判断；指定页面类型本身不代表用户采用了完整文稿页码。
若定位仍有歧义，优先采用能保留实质内容及其先后关系、又能满足封面目录开头要求的解释。

判断数量限制针对整份演示文稿还是正文部分，将 page_count_scope 分别设为 final_presentation 或 content_only。
只有语境支持一个确定的页数要求时才填写 requested_total_pages；大致数量、范围、章节数或举例中的数字不能直接当作精确页数，无法确定时填 null。
区分必须满足的要求、可选建议和示例。must_include 保留用户要求中的细节、数据和限定条件，不要通过概括丢失信息，也不要把建议升级成硬约束。
可以基于上下文推断指代和表达意图，但不要创造没有依据的新要求、页码或内容。这里仅解析意图，补充页面和组织大纲交给后续生成环节。

用户原始需求：
{text}

只返回有效 JSON，不要返回 Markdown 或解释文字：
{{
  "reference_semantics": "content_page|final_page|mixed",
  "requested_total_pages": null,
  "page_count_scope": "final_presentation|content_only",
  "page_constraints": [
    {{
      "page_number": 1,
      "reference_semantics": "content_page",
      "must_include": ["用户明确要求的内容"],
      "slide_type": "content"
    }}
  ]
}}
"""
        # Use at most three calls: the initial attempt plus two retries.  A
        # malformed response gets a targeted repair prompt; a transport/model
        # exception gets a normal retry.  Only after all attempts fail do we
        # let the caller fall back to the legacy generation flow.
        last_error = "unknown"
        attempt_prompt = prompt
        for attempt in range(3):
            try:
                response = await self.ppt_service._text_completion_for_role(
                    "outline",
                    prompt=attempt_prompt,
                    temperature=0.0,
                )
                raw_content = getattr(response, "content", "") or ""
                parsed = self._extract_json_object(raw_content)
                if parsed is not None:
                    return self._normalize_llm_constraints(parsed)
                last_error = "invalid_json"
                attempt_prompt = f"""
上一次输出不是有效 JSON，请修正并重新输出。不要解释，不要 Markdown 代码块，只返回一个完整、可被 json.loads 解析的 JSON 对象。

上一次原始输出：
{str(raw_content)[:8000]}

必须严格遵循之前要求的字段结构，并保留用户明确表达的页面约束。重新输出 JSON：
{prompt}
"""
            except Exception as exc:
                last_error = str(exc) or "llm_call_failed"
                attempt_prompt = f"""
上一次模型调用失败，请重新执行同一个 PPT 需求意图解析任务。只返回有效 JSON，不要解释文字。

{prompt}
"""
        return self._intent_parse_failure(last_error)

    async def classify_generation_mode(self, text: str) -> Dict[str, Any]:
        """Let the model choose between hard-constraint and legacy generation."""
        text = (text or "").strip()
        if not text:
            return {"mode": "original", "parser": "llm"}
        prompt = f"""
你是 PPT 生成方案路由器。请理解完整需求中的目的、表达意图和约束强度，再选择生成模式，不要按关键词或固定句式分类。
判断自由归纳和重新组织是否会破坏用户明确要求保留的内容分配、顺序、数量或结构；区分硬性要求与建议、示例、近似目标。
选择生成模式：
- strict：用户明确提出了页码对应内容、明确总页数、页面类型或必须逐项保留的硬性结构，需要先做页面意图解析和约束校验。
- original：用户只是描述主题、受众、风格或希望生成一个常规大纲，没有明确页面级硬约束。

只返回 JSON，不要解释：{{"mode":"strict|original","reason":"简短原因"}}

用户原始需求：
{text}
"""
        last_error = "invalid_json"
        for _ in range(3):
            try:
                response = await self.ppt_service._text_completion_for_role(
                    "outline", prompt=prompt, temperature=0.0
                )
                parsed = self._extract_json_object(getattr(response, "content", ""))
                mode = parsed.get("mode") if parsed else None
                if mode in {"strict", "original"}:
                    return {"mode": mode, "reason": str(parsed.get("reason") or ""), "parser": "llm"}
                last_error = "invalid_mode_json"
                prompt = f"上一次返回不是有效路由 JSON，请只返回 {{\"mode\":\"strict\" 或 \"original\", \"reason\":\"...\"}}。\n{prompt}"
            except Exception as exc:
                last_error = str(exc) or "llm_call_failed"
        return {"mode": "original", "parser": "llm_failed", "reason": last_error}

    @classmethod
    def _intent_parse_failure(cls, reason: str) -> Dict[str, Any]:
        return {
            "page_constraints": [],
            "requested_total_pages": None,
            "page_count_scope": "final_presentation",
            "reference_semantics": "unknown",
            "parser": "llm_failed",
            "parser_version": cls.VERSION,
            "intent_parse_failed": True,
            "intent_parse_error": reason or "unknown",
        }

    @staticmethod
    def _constraint_prompt(constraints: Dict[str, Any]) -> str:
        page_constraints = constraints.get("page_constraints") or []
        requested_total = constraints.get("requested_total_pages")
        if not page_constraints and not requested_total:
            return ""
        lines = [
            "\n\n【页面级硬性要求（必须满足，不得自行改写或删除）】",
            "以下要求来自用户原始输入，优先级高于一般内容归纳要求：",
            "- 最终PPT以第1页封面、第2页目录开头；以下逐条要求已根据完整上下文解析页码含义，请遵循标注的正文位置或最终位置，不要根据原始措辞重新套用页码规则。",
        ]
        if requested_total:
            if constraints.get("page_count_scope") == "content_only":
                lines.append(f"- 用户要求 {requested_total} 页内容；加上固定封面和目录后，最终必须生成恰好 {requested_total + ConstrainedOutlineGenerationService.FIXED_PREFIX_PAGES} 页。")
            else:
                lines.append(f"- 最终必须生成恰好 {requested_total} 页。")
        for item in page_constraints:
            requirement = "；".join(item.get("must_include") or [])
            if item.get("position") == "last":
                lines.append(f"- 最后一页必须包含：{requirement}")
            else:
                if item.get("reference_semantics") == "final_page":
                    lines.append(f"- 最终第 {item['page_number']} 页必须包含：{requirement}")
                else:
                    final_page = int(item["page_number"]) + ConstrainedOutlineGenerationService.FIXED_PREFIX_PAGES
                    lines.append(f"- 内容区第 {item['page_number']} 页（最终第 {final_page} 页）必须包含：{requirement}")
            if item.get("slide_type"):
                lines.append(f"- 该页面类型必须为：{item['slide_type']}。")
        lines.extend([
            "- 不得改变已指定页面的页码和顺序。",
            "- 未指定页面可以由模型补充，但不得删除上述硬性要求。",
            "- 输出前逐页自检，并确保 page_number 连续。",
        ])
        return "\n".join(lines)

    @staticmethod
    def _slide_text(slide: Dict[str, Any]) -> str:
        points = slide.get("content_points") or []
        return " ".join(str(value) for value in [slide.get("title", ""), slide.get("description", ""), *points])

    @classmethod
    def _resolve_final_page_number(cls, item: Dict[str, Any], total_slides: int) -> int:
        if item.get("position") == "last":
            return total_slides
        page_number = int(item["page_number"])
        if item.get("reference_semantics") == "final_page":
            return page_number
        return page_number + cls.FIXED_PREFIX_PAGES

    @classmethod
    def _ensure_cover_and_agenda(cls, outline: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure the constrained entrypoint always has a fixed two-page prefix."""
        slides = [deepcopy(slide) for slide in (outline.get("slides") or [])]
        cover = slides[0] if slides and slides[0].get("slide_type") in {"title", "cover"} else {
            "title": outline.get("title") or "演示文稿",
            "content_points": [outline.get("title") or "演示文稿"],
            "slide_type": "title",
            "type": "title",
            "description": "封面页",
        }
        if slides and slides[0] is cover:
            slides = slides[1:]
        cover["slide_type"] = "title"
        cover["type"] = "title"
        cover.setdefault("description", "封面页")

        agenda = slides[0] if slides and slides[0].get("slide_type") == "agenda" else {
            "title": "目录",
            "content_points": [],
            "slide_type": "agenda",
            "type": "agenda",
            "description": "目录页",
        }
        if slides and slides[0] is agenda:
            slides = slides[1:]
        agenda["slide_type"] = "agenda"
        agenda["type"] = "agenda"
        agenda.setdefault("description", "目录页")
        agenda["content_points"] = [
            slide.get("title", "") for slide in slides
            if slide.get("slide_type") not in {"title", "agenda", "transition"} and slide.get("title")
        ][:8]
        outline["slides"] = [cover, agenda, *slides]
        for index, slide in enumerate(outline["slides"], start=1):
            slide["page_number"] = index
        return outline

    @classmethod
    def _normalize_page_count(
        cls,
        outline: Dict[str, Any],
        target: int,
        constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        slides = [deepcopy(slide) for slide in (outline.get("slides") or [])]
        required_numbers = {
            cls._resolve_final_page_number(item, max(len(slides), target))
            for item in constraints.get("page_constraints", [])
            if item.get("page_number") is not None or item.get("position") == "last"
        }
        if target <= 0:
            return outline
        if target < cls.FIXED_PREFIX_PAGES:
            outline.setdefault("metadata", {})["constraint_conflict"] = (
                f"requested_total_pages={target} 小于固定封面和目录所需的 {cls.FIXED_PREFIX_PAGES} 页"
            )
            target = cls.FIXED_PREFIX_PAGES
        if required_numbers and max(required_numbers) > target:
            # Preserve every explicitly addressed page.  The request is
            # contradictory, so the result stays usable and records the
            # conflict instead of silently dropping a required page.
            outline.setdefault("metadata", {})["constraint_conflict"] = (
                f"指定页面最大最终页码为 {max(required_numbers)}，超过 requested_total_pages={target}"
            )
            target = max(required_numbers)
        while len(slides) < target:
            page_number = len(slides) + 1
            slides.append({
                "page_number": page_number,
                "title": f"补充内容 {page_number}",
                "content_points": ["根据主题补充相关内容"],
                "slide_type": "content",
                "description": "由约束增强流程补充的内容页",
            })
        if len(slides) > target:
            removable = [
                index for index in range(len(slides) - 1, -1, -1)
                if index + 1 not in required_numbers
            ]
            remove_count = len(slides) - target
            remove_set = set(removable[:remove_count])
            if len(remove_set) < remove_count:
                # The request itself is contradictory: retain all explicitly
                # requested pages and expose the conflict in metadata.
                outline.setdefault("metadata", {})["constraint_conflict"] = (
                    "指定页面数量超过 requested_total_pages"
                )
            slides = [slide for index, slide in enumerate(slides) if index not in remove_set]
        for index, slide in enumerate(slides, start=1):
            slide["page_number"] = index
        outline["slides"] = slides[:target]
        return outline

    @classmethod
    def _enforce_page_constraints(
        cls,
        outline: Dict[str, Any],
        constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        slides = outline.get("slides") or []
        violations: List[Dict[str, Any]] = []
        for item in constraints.get("page_constraints", []):
            page_number = cls._resolve_final_page_number(item, len(slides))
            if page_number < 1 or page_number > len(slides):
                violations.append({"page_number": page_number, "reason": "page_not_present"})
                continue
            slide = slides[page_number - 1]
            if page_number > cls.FIXED_PREFIX_PAGES and item.get("reference_semantics") != "final_page":
                slide["slide_type"] = "content"
                slide["type"] = "content"
            text = cls._slide_text(slide).casefold()
            missing = [
                requirement for requirement in item.get("must_include", [])
                if str(requirement).casefold() not in text
            ]
            if missing:
                # Stage 1 is intentionally deterministic: preserve the user's
                # wording in content_points, then record the repair.
                points = slide.setdefault("content_points", [])
                for requirement in missing:
                    points.append(str(requirement))
                violations.append({
                    "page_number": page_number,
                    "content_page_number": item.get("page_number") if item.get("reference_semantics") != "final_page" else None,
                    "reason": "missing_must_include",
                    "repaired": missing,
                })
        metadata = outline.setdefault("metadata", {})
        metadata["constraint_validation"] = {
            "version": cls.VERSION,
            "requested_total_pages": constraints.get("requested_total_pages"),
            "checked_pages": len(constraints.get("page_constraints") or []),
            "violations": violations,
            "passed": not violations or all(item.get("repaired") for item in violations),
        }
        metadata["page_constraints"] = constraints.get("page_constraints") or []
        metadata["structure_policy"] = "always_cover_agenda"
        metadata["reference_semantics"] = constraints.get("reference_semantics", "content_page")
        metadata["total_slides"] = len(slides)
        metadata["total_pages"] = len(slides)
        metadata["actual_page_count"] = len(slides)
        return outline

    async def generate(
        self,
        project_id: str,
        request: Any,
        page_count_settings: Optional[Dict[str, Any]] = None,
        generation_request_id: Optional[str] = None,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raw_text = "\n".join(
            value for value in [getattr(request, "requirements", ""), getattr(request, "description", "")] if value
        )
        constraints = await self.extract_constraints_with_llm(raw_text)
        if constraints.get("intent_parse_failed"):
            # The constrained workflow must never make generation less
            # reliable than the legacy workflow.  If intent extraction is
            # unavailable, delegate the untouched request and skip all
            # constraint-specific structure or page-count transformations.
            outline = await self.ppt_service.generate_outline(
                request, page_count_settings, confirmed_requirements=confirmed_requirements
            )
            outline_data = {
                "title": outline.title,
                "slides": outline.slides,
                "metadata": dict(outline.metadata or {}),
            }
            metadata = outline_data.setdefault("metadata", {})
            metadata["generation_entrypoint"] = "constrained-stage1-fallback-original"
            metadata["constraint_parser"] = "llm_failed"
            if generation_request_id:
                metadata["generation_request_id"] = generation_request_id
            metadata["constraint_validation"] = {
                "skipped": True,
                "reason": constraints.get("intent_parse_error", "intent_parser_failed"),
            }
            await self.ppt_service._update_outline_generation_stage(project_id, outline_data)
            return outline_data
        constraint_text = self._constraint_prompt(constraints)
        if hasattr(request, "requirements"):
            update = {"requirements": f"{getattr(request, 'requirements', '') or ''}{constraint_text}"}
        elif hasattr(request, "content"):
            update = {"content": f"{getattr(request, 'content', '') or ''}{constraint_text}"}
        else:
            update = {}
        constrained_request = request.model_copy(update=update) if update else request
        outline = await self.ppt_service.generate_outline(
            constrained_request, page_count_settings, confirmed_requirements=confirmed_requirements
        )
        outline_data = {
            "title": outline.title,
            "slides": outline.slides,
            "metadata": dict(outline.metadata or {}),
        }
        outline_data = self._ensure_cover_and_agenda(outline_data)
        target = constraints.get("requested_total_pages")
        if target and constraints.get("page_count_scope") == "content_only":
            target = int(target) + self.FIXED_PREFIX_PAGES
        if not target and page_count_settings and page_count_settings.get("mode") == "fixed":
            target = page_count_settings.get("fixed_pages")
        if target:
            outline_data = self._normalize_page_count(outline_data, int(target), constraints)
        outline_data = self._enforce_page_constraints(outline_data, constraints)
        outline_data.setdefault("metadata", {})["generation_entrypoint"] = "constrained-stage1"
        outline_data["metadata"]["constraint_parser"] = constraints.get("parser")
        if generation_request_id:
            outline_data["metadata"]["generation_request_id"] = generation_request_id
        await self.ppt_service._update_outline_generation_stage(project_id, outline_data)
        return outline_data
