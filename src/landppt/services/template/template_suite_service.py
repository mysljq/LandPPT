"""
Template Suite Service — generate a per-project "template suite" (cover /
transition / content header-footer) derived from the selected master template.

The suite is generated once via a single LLM call and persisted into
project.project_metadata["template_suite"]. Slide generation then:
  - fills cover/transition pages from the suite templates (deterministic slots)
  - injects the content header/footer as a strong prompt constraint
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

from ..prompts.template_prompts import TemplatePrompts
from .master_layout_extractor import MasterLayoutExtractor

logger = logging.getLogger(__name__)


class TemplateSuiteService:
    """Own template-suite generation, caching, and retrieval."""

    # Keys persisted under project.project_metadata["template_suite"].
    _METADATA_KEY = "template_suite"

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    # ------------------------------------------------------------------
    # Hash / validity
    # ------------------------------------------------------------------

    @staticmethod
    def _template_hash(template_html: str) -> str:
        return hashlib.md5((template_html or "").encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _template_identity(template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        template = template or {}
        html = template.get("html_template") or ""
        template_id = template.get("id")
        return {
            "template_id": int(template_id) if template_id is not None else None,
            "template_hash": TemplateSuiteService._template_hash(html),
            "template_name": template.get("template_name") or "未知模板",
        }

    def _suite_valid(self, suite: Any, identity: Dict[str, Any]) -> bool:
        """A suite is valid only if it matches the currently selected template."""
        if not isinstance(suite, dict):
            return False
        stored_hash = suite.get("template_hash")
        stored_id = suite.get("template_id")
        if stored_hash and stored_hash != identity.get("template_hash"):
            return False
        if (
            identity.get("template_id") is not None
            and stored_id is not None
            and stored_id != identity.get("template_id")
        ):
            return False
        return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_suite(self, project_id: str, suite: Dict[str, Any]) -> None:
        try:
            project = await self.project_manager.get_project(project_id)
            if not project:
                logger.warning("Persist suite failed: project %s not found", project_id)
                return
            metadata = dict(project.project_metadata or {})
            metadata[self._METADATA_KEY] = suite
            await self.project_manager.update_project_metadata(project_id, metadata)
            logger.info("Persisted template suite for project %s", project_id)
        except Exception as exc:
            logger.error("Failed to persist template suite for project %s: %s", project_id, exc)

    async def get_suite(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Return a valid suite for the project, or None (invalid / stale / missing).

        Also backfills the header_footer to be self-contained (inline the master's
        :root CSS variables) so old suites whose header_footer references var(--x)
        without defining them render correctly.
        """
        try:
            project = await self.project_manager.get_project(project_id)
            if not project:
                return None
            metadata = project.project_metadata or {}
            suite = metadata.get(self._METADATA_KEY)
            if not isinstance(suite, dict) or not suite:
                return None
            template = await self.get_selected_global_template(project_id)
            if not template:
                # No template selected — treat the suite as inapplicable.
                return None
            identity = self._template_identity(template)
            if not self._suite_valid(suite, identity):
                logger.info(
                    "Template suite for project %s is stale (template changed), ignoring",
                    project_id,
                )
                return None

            # 自包含兜底：若 header_footer 引用母版 :root 变量或骨架不完整
            # （缺 canvas 容器 / 缺装饰 CSS / 存在残缺标签），则补齐并回写
            # （旧套件无需重新生成即自动修复）。_ensure_header_footer_complete
            # 内部会做严格的骨架完整性检测。
            try:
                hf = str(suite.get("header_footer") or "")
                import re as _re
                needs_fix = (
                    _re.search(r"var\(--", hf)
                    or not _re.search(r'class="[^"]*(?:canvas|hf-canvas)[^"]*"', hf)
                    or not _re.search(r'\.(?:canvas|bg-paper|bg-grid|frame-corner)\s*\{', hf)
                    or bool(_re.search(r'<div class="[^"]*$', hf, _re.MULTILINE))
                )
                if needs_fix:
                    extracted = MasterLayoutExtractor.extract_header_footer(
                        template.get("html_template") or ""
                    )
                    fixed = self._ensure_header_footer_complete(
                        hf,
                        template.get("html_template") or "",
                        extracted.get("root_variables") or "",
                    )
                    if fixed and fixed != hf:
                        updated = dict(suite)
                        updated["header_footer"] = fixed
                        await self._persist_suite(project_id, updated)
                        return updated
            except Exception as exc:
                logger.warning("Backfill header_footer failed for %s: %s", project_id, exc)

            return suite
        except Exception as exc:
            logger.warning("Failed to get template suite for project %s: %s", project_id, exc)
            return None

    async def get_suite_status(self, project_id: str) -> Dict[str, Any]:
        """Lightweight status for the frontend button (existence + freshness)."""
        suite = await self.get_suite(project_id)
        if not suite:
            return {"status": "none"}
        return {
            "status": "ready",
            "template_name": suite.get("template_name"),
            "generated_at": suite.get("generated_at"),
        }

    def build_preview_html(self, suite: Dict[str, Any]) -> Dict[str, str]:
        """Render the suite into three preview pages with sample slot content.

        Returns {"cover": ..., "transition": ..., "content": ...} where each value
        is a complete, standalone HTML document (1280x720) the frontend can show
        in an iframe. Content page composes header_footer with a placeholder body.
        """
        from .template_suite_renderer import TemplateSuiteRenderer

        def _fill(entry: str, slots: Dict[str, str]) -> str:
            import re as _re

            filled = TemplateSuiteRenderer.fill_suite_template(entry or "", slots)
            # Any remaining unfilled slot -> sample placeholder text, so the
            # preview never shows raw {{ }} tokens.
            remaining = TemplateSuiteRenderer.find_unfilled_slots(filled)
            for name in remaining:
                # 正文占位槽位保留原样，交给 _wrap_content_preview 替换成预览占位提示。
                if name == "page_content":
                    continue
                filled = _re.sub(
                    r"{{\s*" + _re.escape(name) + r"\s*}}",
                    f"[{name} 示例]",
                    filled,
                )
            return filled

        cover = _fill(
            suite.get("cover"),
            {
                "cover_title": "演示文稿标题（示例）",
                "cover_subtitle": "副标题 · 用于展示封面套件效果",
                "cover_extra": "演讲人：某某 · 2026年8月",
            },
        )
        transition = _fill(
            suite.get("transition"),
            {
                "transition_title": "第一章 · 章节名称（示例）",
                "transition_subtitle": "这一页用于章节之间的过渡",
                "transition_extra": "",
            },
        )

        # Content page: header/footer fragment + a sample body.
        hf = str(suite.get("header_footer") or "")
        hf = _fill(
            hf,
            {
                "page_title": "内容页标题（示例）",
                "current_page_number": "3",
                "total_page_count": "10",
            },
        )
        content = self._wrap_content_preview(hf)

        return {"cover": cover, "transition": transition, "content": content}

    def _wrap_content_preview(self, header_footer_fragment: str) -> str:
        """Wrap the header/footer fragment into a standalone 1280x720 document.

        不再注入示例"要点一/要点二"正文（避免因各种 header_footer 结构差异导致
        插入位置错乱）。预览只展示页头、正文占位区、页脚；若存在 {{ page_content }}
        槽位则替换为一行中性占位文字，否则保持空正文区。
        """
        import re as _re

        fragment = header_footer_fragment or ""

        has_head = "<head" in fragment.lower()
        if has_head:
            # Extract any <style> from the fragment and strip head/body tags so we
            # can compose a single valid document.
            styles = _re.findall(r"<style[^>]*>.*?</style>", fragment, _re.IGNORECASE | _re.DOTALL)
            body_frag = _re.sub(r"<head.*?</head>", "", fragment, flags=_re.IGNORECASE | _re.DOTALL)
            body_frag = _re.sub(r"<!DOCTYPE[^>]*>", "", body_frag, flags=_re.IGNORECASE)
            body_frag = _re.sub(r"<html[^>]*>|</html>", "", body_frag, flags=_re.IGNORECASE)
            body_frag = _re.sub(r"<body[^>]*>|</body>", "", body_frag, flags=_re.IGNORECASE)
            style_html = "\n".join(styles)
        else:
            body_frag = fragment
            style_html = ""

        # 若存在正文槽位 {{ page_content }}，替换为一行中性占位文字（便于预览页头页脚效果）。
        if "{{ page_content }}" in body_frag or "{{page_content}}" in body_frag:
            placeholder = (
                '<div style="display: flex; align-items: center; justify-content: center; '
                'height: 100%; color: #9aa0a6; font-size: 14px; letter-spacing: 1px;">'
                "正文占位区 · 生成 PPT 时由 AI 填充内容</div>"
            )
            body_frag = _re.sub(
                r"\{\{\s*page_content\s*\}\}",
                placeholder,
                body_frag,
                flags=_re.IGNORECASE,
            )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
html, body {{ margin: 0; padding: 0; width: 1280px; height: 720px; overflow: hidden; }}
body {{ display: flex; flex-direction: column; font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; }}
{style_html}
</style>
</head>
<body>
{body_frag}
</body>
</html>"""


    def _clear_caches(self, project_id: str) -> None:
        try:
            self.clear_cached_style_genes(project_id)
        except Exception as exc:
            logger.warning("Failed to clear style-gene caches for project %s: %s", project_id, exc)

    @staticmethod
    def _ensure_header_footer_self_contained(header_footer: str, root_variables: str) -> str:
        """确保 header_footer 片段自包含：若它引用了母版 :root 的 CSS 变量但自身
        未定义，则把母版的 :root 变量块前置到片段内，避免 var(--xxx) 失效导致
        内容页样式错乱。"""
        import re as _re

        if not header_footer:
            return header_footer
        vars_used = set(_re.findall(r"var\((--[\w-]+)", header_footer))
        if not vars_used:
            return header_footer
        # 片段内已定义的变量（含内联 <style> 里的 :root 或 :where/html 兜底）
        defined = set(_re.findall(r"(--[\w-]+)\s*:", header_footer))
        missing = vars_used - defined
        if not missing:
            return header_footer
        if not root_variables:
            return header_footer
        # 只内联确实缺失的变量（从 root 块挑出来，避免整块重复）
        missing_lines = []
        for line in root_variables.splitlines():
            m = _re.search(r"(--[\w-]+)\s*:", line)
            if m and m.group(1) in missing:
                missing_lines.append(line)
        if not missing_lines:
            return header_footer
        inline = (
            "\n<!-- 母版设计变量（自包含兜底，供 var(--xxx) 使用） -->\n"
            "<style>\n:root {\n" + "\n".join(missing_lines) + "\n}\n</style>\n"
        )
        return inline + header_footer

    @staticmethod
    def _ensure_header_footer_complete(header_footer: str, template_html: str, root_variables: str) -> str:
        """确保 header_footer 片段"遵照模板本身"：

        1. 若片段缺模板的装饰骨架（canvas/背景/边框/印章），则从母版提取并注入，
           让内容页预览/生成时自带模板的背景与装饰，而不是只有孤立的页头页脚文字。
        2. 最后统一内联缺失的 :root 变量（var(--x) 引用，含骨架 CSS 里的）。
        """
        import re as _re

        if not header_footer:
            return header_footer

        hf = header_footer

        # 检测不完整标签（如 <div class=" 被截断）——说明已有骨架是坏的，需重新注入。
        has_incomplete_div = bool(
            _re.search(r'<div class="[^"]*$', hf, _re.MULTILINE)
        )

        # 骨架是否"完整"：需要 canvas 容器 + 背景层 + 对应 CSS + 正文占位区。
        # 仅有孤立的 bg-paper 裸 div 不算有效骨架；缺正文占位区（页头→页脚直连）
        # 也不算有效骨架（中间没有内容承载空间）。
        has_canvas_wrapper = bool(
            _re.search(r'class="[^"]*(?:canvas|hf-canvas|slide-container|page-wrapper)[^"]*"', hf)
        )
        has_bg_layer = ("bg-paper" in hf) or ("bg-grid" in hf)
        has_skeleton_css = bool(
            _re.search(r'\.(?:canvas|hf-canvas|bg-paper|bg-grid|frame-corner)\s*\{', hf)
        )
        has_stage = bool(
            _re.search(r'class="[^"]*(?:main-stage|hf-stage|main-stage-placeholder|stage|content-main|body-area|content-area)[^"]*"', hf)
            or ("{{ page_content }}" in hf or "{{page_content}}" in hf)
        )
        has_skeleton = bool(
            has_canvas_wrapper and has_bg_layer and has_skeleton_css and has_stage
        )
        if (not has_skeleton) or has_incomplete_div:
            try:
                skeleton = MasterLayoutExtractor.extract_content_skeleton(template_html or "")
                skeleton_html = (skeleton.get("skeleton_html") or "").strip()
                skeleton_css = (skeleton.get("skeleton_css") or "").strip()
                if skeleton_html:
                    # 若已存在坏的骨架，先移除旧的骨架注入块（从"母版内容页骨架"标记
                    # 到标题锚点/页头注释之前），再重新注入。
                    if has_incomplete_div and "母版内容页骨架" in hf:
                        # 定位标题锚点注释/第一个 title-anchor 结构
                        anchor_marker = _re.search(
                            r'(?:<!--[^>]*页头[^>]*-->|<div[^>]*class="[^"]*title-anchor")',
                            hf,
                        )
                        sk_start = hf.find("<!-- 母版内容页骨架")
                        if sk_start != -1 and anchor_marker and anchor_marker.start() > sk_start:
                            hf = hf[:sk_start] + hf[anchor_marker.start():]
                        elif sk_start != -1:
                            hf = hf[:sk_start]
                        hf = hf.strip("\n")
                    css_block = f"\n<style>\n{skeleton_css}\n</style>\n" if skeleton_css else ""
                    hf = (
                        "\n<!-- 母版内容页骨架（背景/装饰，自包含） -->\n"
                        + skeleton_html
                        + "\n"
                        + hf
                        + css_block
                    )
            except Exception as exc:
                logger.warning("注入模板骨架失败: %s", exc)

        # 若仍无正文占位区（页头→页脚直连），在页头闭合后插入 main-stage 正文占位区。
        has_stage = bool(
            _re.search(
                r'class="[^"]*(?:main-stage|hf-stage|main-stage-placeholder|stage|content-main|body-area|content-area)[^"]*"',
                hf,
            )
            or ("{{ page_content }}" in hf or "{{page_content}}" in hf)
        )
        if not has_stage:
            try:
                # 定位页头闭合（title-anchor 的 </div>）与页脚开始（number-anchor）
                ta_open = _re.search(r'<div[^>]*class="[^"]*title-anchor"[^>]*>', hf)
                na_open = _re.search(r'<div[^>]*class="[^"]*number-anchor"[^>]*>', hf)
                if ta_open and na_open and na_open.start() > ta_open.end():
                    # 页头容器结束 = 找到与 title-anchor 对应的闭合 </div>（在 number-anchor 前）
                    segment = hf[ta_open.end():na_open.start()]
                    # title-anchor 是 <div>...</div>，其闭合是最后一个 </div>
                    title_close = segment.rfind("</div>")
                    insert_at = ta_open.end() + title_close + len("</div>")
                    main_stage = (
                        "\n  <!-- 正文占位区 -->\n"
                        '  <div class="main-stage" style="position: relative; z-index: 2; '
                        'flex: 1 1 0; min-height: 0; min-width: 0; overflow: hidden; '
                        'padding: 22px 80px 18px; display: flex; flex-direction: column;">\n'
                        "    {{ page_content }}\n"
                        "  </div>\n"
                    )
                    hf = hf[:insert_at] + main_stage + hf[insert_at:]
            except Exception as exc:
                logger.warning("插入正文占位区失败: %s", exc)

        # 最后统一内联缺失的 :root 变量（页头页脚 + 骨架 CSS 都会引用）。
        return TemplateSuiteService._ensure_header_footer_self_contained(hf, root_variables)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_from_response(content: str) -> Optional[Dict[str, Any]]:
        content = (content or "")
        content = content.split("</think>")[-1]
        content = content.strip()
        if content.startswith("```json"):
            content = content[len("```json"):]
            if content.endswith("```"):
                content = content[:-3]
        elif content.startswith("```"):
            content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
        content = content.strip()

        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            try:
                return json.loads(content[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _validate_suite_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate/normalize the LLM suite payload; raise on invalid cover/transition."""
        cover = str(payload.get("cover") or "").strip()
        transition = str(payload.get("transition") or "").strip()
        header_footer = str(payload.get("header_footer") or "").strip()
        design_tokens = str(payload.get("design_tokens") or "").strip()

        missing = []
        if not cover or not cover.lower().startswith("<!doctype html"):
            missing.append("cover")
        if not transition or not transition.lower().startswith("<!doctype html"):
            missing.append("transition")
        if not header_footer:
            missing.append("header_footer")
        # Slot sanity: cover/transition must keep their title slot, header_footer
        # must keep page_title and page-number slots for later substitution.
        for slot in ("cover_title",):
            if slot not in cover:
                missing.append(f"cover缺少槽位 {{{{{slot}}}}}")
        for slot in ("transition_title",):
            if slot not in transition:
                missing.append(f"transition缺少槽位 {{{{{slot}}}}}")
        for slot in ("page_title", "current_page_number", "total_page_count"):
            if slot not in header_footer:
                missing.append(f"header_footer缺少槽位 {{{{{slot}}}}}")

        if missing:
            raise ValueError("模板套件生成校验失败：" + "、".join(missing))

        return {
            "cover": cover,
            "transition": transition,
            "header_footer": header_footer,
            "design_tokens": design_tokens,
        }

    async def generate_suite(
        self,
        project_id: str,
        template: Dict[str, Any],
        force: bool = False,
    ) -> Dict[str, Any]:
        """Generate (or refresh) a template suite for a project and persist it."""
        template = template or {}
        html = template.get("html_template") or ""
        if not html.strip():
            raise ValueError("所选模板无 HTML 内容，无法生成套件")

        extracted = MasterLayoutExtractor.extract_header_footer(html)

        # Load project context for the prompt (outline + confirmed requirements).
        project = await self.project_manager.get_project(project_id)
        if not project:
            raise ValueError(f"项目 {project_id} 不存在")
        outline = project.outline or {}
        confirmed = project.confirmed_requirements or {}

        prompt = TemplatePrompts.build_template_suite_prompt(
            project=project,
            outline=outline,
            confirmed=confirmed,
            template_html=html,
            extracted_header_footer=extracted,
        )

        response = await self._text_completion_for_role(
            "template", prompt=prompt, temperature=0.7
        )
        raw = (response.content or "").strip()
        if not raw:
            raise ValueError("AI 服务返回空响应")

        payload = self._extract_json_from_response(raw)
        if not payload:
            raise ValueError("AI 响应中未找到有效的套件 JSON")

        validated = self._validate_suite_payload(payload)

        identity = self._template_identity(template)
        header_footer = validated["header_footer"]
        header_footer = self._ensure_header_footer_complete(
            header_footer, html, extracted.get("root_variables") or ""
        )
        suite = {
            "cover": validated["cover"],
            "transition": validated["transition"],
            "header_footer": header_footer,
            "design_tokens": validated["design_tokens"],
            "template_hash": identity["template_hash"],
            "template_id": identity["template_id"],
            "template_name": identity["template_name"],
            "generated_at": time.time(),
        }

        await self._persist_suite(project_id, suite)
        self._clear_caches(project_id)
        logger.info(
            "Generated template suite for project %s (template=%s)",
            project_id,
            identity["template_name"],
        )
        return suite

    _SUITE_PART_KEYS = ("cover", "transition", "header_footer")

    async def regenerate_suite_part(
        self,
        project_id: str,
        part: str,
        template: Dict[str, Any],
        user_feedback: str = "",
    ) -> Dict[str, Any]:
        """Only regenerate one part (cover/transition/header_footer) of the suite.

        Loads the existing suite, calls the LLM to produce just `part`, merges it
        back while keeping every other part and design_tokens intact. Much cheaper
        than a full regeneration and keeps cross-part consistency.
        """
        if part not in self._SUITE_PART_KEYS:
            raise ValueError(f"不支持的套件类型: {part}")

        template = template or {}
        html = template.get("html_template") or ""
        if not html.strip():
            raise ValueError("所选模板无 HTML 内容，无法生成套件")

        existing = await self.get_suite(project_id)
        if not existing:
            raise ValueError("项目暂无已生成的套件，请先整体生成套件")

        extracted = MasterLayoutExtractor.extract_header_footer(html)
        project = await self.project_manager.get_project(project_id)
        if not project:
            raise ValueError(f"项目 {project_id} 不存在")
        outline = project.outline or {}
        confirmed = project.confirmed_requirements or {}

        prompt = TemplatePrompts.build_template_suite_part_prompt(
            part=part,
            project=project,
            outline=outline,
            confirmed=confirmed,
            template_html=html,
            extracted_header_footer=extracted,
            existing_suite=existing,
            user_feedback=user_feedback,
        )

        response = await self._text_completion_for_role(
            "template", prompt=prompt, temperature=0.7
        )
        raw = (response.content or "").strip()
        if not raw:
            raise ValueError("AI 服务返回空响应")

        payload = self._extract_json_from_response(raw)
        if not payload or part not in payload:
            raise ValueError(f"AI 响应中未找到新的 {part} 内容")

        new_value = str(payload.get(part) or "").strip()
        if not new_value:
            raise ValueError(f"新的 {part} 内容为空")

        # 对 cover/transition 做完整 HTML 校验；header_footer 只需含页头页脚槽位。
        if part in ("cover", "transition"):
            if not new_value.lower().startswith("<!doctype html"):
                raise ValueError(f"重新生成的 {part} 不是完整 HTML")
            slot = "cover_title" if part == "cover" else "transition_title"
            if slot not in new_value:
                raise ValueError(f"重新生成的 {part} 缺少槽位 {{{{{slot}}}}}")
        else:
            for slot in ("page_title", "current_page_number", "total_page_count"):
                if slot not in new_value:
                    raise ValueError(f"重新生成的 header_footer 缺少槽位 {{{{{slot}}}}}")

        updated = dict(existing)
        # header_footer 重新生成后同样内联母版 :root 变量 + 模板装饰骨架。
        if part == "header_footer":
            new_value = self._ensure_header_footer_complete(
                new_value, html, extracted.get("root_variables") or ""
            )
        updated[part] = new_value
        updated["updated_at"] = time.time()
        # 保留原 template_hash/template_id/template_name（仍是同一母版）
        await self._persist_suite(project_id, updated)
        self._clear_caches(project_id)
        logger.info("Regenerated suite part '%s' for project %s", part, project_id)
        return updated

    async def stream_suite_part_regeneration(
        self,
        project_id: str,
        part: str,
        user_feedback: str = "",
        user_id: Optional[int] = None,
    ):
        """Stream single-type suite regeneration events, persisting on success."""
        lock = self._template_suite_locks.setdefault(project_id, asyncio.Lock())
        if lock.locked():
            yield {"type": "status", "message": "已有套件任务正在进行，请稍候..."}

        async with lock:
            try:
                template = await self.get_selected_global_template(project_id, user_id=user_id)
                if not template:
                    yield {"type": "error", "message": "项目未选定模板，无法重新生成套件"}
                    return

                yield {"type": "status", "message": f"正在重新生成{part}..."}
                try:
                    updated = await self.regenerate_suite_part(
                        project_id, part, template, user_feedback=user_feedback
                    )
                except Exception as exc:
                    logger.error("Suite part regeneration failed for project %s: %s", project_id, exc)
                    yield {"type": "error", "message": f"重新生成失败：{exc}"}
                    return

                yield {
                    "type": "complete",
                    "message": f"套件{part}已重新生成！",
                    "suite": updated,
                    "part": part,
                    "template_name": updated.get("template_name"),
                }
            except Exception as exc:
                logger.error("Stream suite part regeneration error for project %s: %s", project_id, exc)
                yield {"type": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Streaming generation (frontend manual step)
    # ------------------------------------------------------------------

    async def stream_suite_generation(
        self,
        project_id: str,
        user_id: Optional[int] = None,
        force: bool = False,
    ):
        """Stream suite-generation events and persist the suite on success."""
        lock = self._template_suite_locks.setdefault(project_id, asyncio.Lock())
        if lock.locked():
            yield {"type": "status", "message": "已有套件生成任务正在进行，请稍候..."}

        async with lock:
            try:
                template = await self.get_selected_global_template(project_id, user_id=user_id)
                if not template:
                    yield {"type": "error", "message": "项目未选定模板，无法生成套件"}
                    return

                suite = None
                if not force:
                    suite = await self.get_suite(project_id)
                if suite:
                    yield {"type": "status", "message": "已加载现有套件（如需重新生成请传 force）"}
                    yield {
                        "type": "complete",
                        "message": "模板套件已就绪",
                        "suite": suite,
                        "template_name": suite.get("template_name"),
                    }
                    return

                yield {"type": "status", "message": "正在基于母版风格生成套件（封面/过渡/内容页头页脚）..."}
                try:
                    suite = await self.generate_suite(project_id, template, force=force)
                except Exception as exc:
                    logger.error("Template suite generation failed for project %s: %s", project_id, exc)
                    yield {"type": "error", "message": f"套件生成失败：{exc}"}
                    return

                yield {
                    "type": "complete",
                    "message": "模板套件生成完成！",
                    "suite": suite,
                    "template_name": suite.get("template_name"),
                }
            except Exception as exc:
                logger.error("Stream suite generation error for project %s: %s", project_id, exc)
                yield {"type": "error", "message": str(exc)}
