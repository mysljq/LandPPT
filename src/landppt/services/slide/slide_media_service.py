import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...api.models import (
    PPTGenerationRequest,
    PPTOutline,
    EnhancedPPTOutline,
    SlideContent,
    PPTProject,
    TodoBoard,
    FileOutlineGenerationResponse,
)
from ...ai import get_ai_provider, get_role_provider, AIMessage, MessageRole
from ...ai.base import TextContent, ImageContent
from ...core.config import ai_config, app_config
from ..runtime.ai_execution import ExecutionContext
from ..prompts import prompts_manager
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .slide_html_service import SlideHtmlService


class SlideMediaService:
    """Extracted logic from SlideHtmlService."""

    def __init__(self, service: 'SlideHtmlService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _generate_single_slide_html_with_prompts(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any], system_prompt: str, page_number: int, total_pages: int, all_slides: List[Dict[str, Any]]=None, existing_slides_data: List[Dict[str, Any]]=None, project_id: str=None) -> str:
        """Generate HTML for a single slide using prompts.md and first step information with template selection"""
        try:
            if not project_id:
                project_id = confirmed_requirements.get('project_id')
            # 章节号刷新：老/坏大纲可能把所有 slide 的 chapter 存成 0（典型"第 0 章"事故）。
            # _assign_chapter_numbers 幂等重算全部章节号（确定性、按页序）——对
            # "过渡页=章节边界 + 无编号前缀章节名/agenda 匹配"更鲁棒，保证生成时
            # {{chapter_number}} 渲染成真实章节号而非"第 0 章"。幂等：已正确的重算结果一致。
            if all_slides:
                try:
                    from ..outline.project_outline_normalization_service import (
                        ProjectOutlineNormalizationService as _ONorm,
                    )
                    refreshed = _ONorm._assign_chapter_numbers(
                        [dict(s) if isinstance(s, dict) else {} for s in all_slides]
                    )
                    pos = max(0, int(page_number) - 1)
                    if pos < len(refreshed):
                        new_ch = (refreshed[pos] or {}).get("chapter", 0)
                        if isinstance(slide_data, dict):
                            slide_data["chapter"] = new_ch
                        all_slides = refreshed
                except Exception as _ce:
                    logger.warning(f"刷新章节号失败，按原值生成: {_ce}")
            # 套件优先：封面/过渡页用套件模板填充槽位；内容页注入页头页脚强约束；
            # 目录页不直接模板填充，改为让 LLM 参考套件里的目录页设计生成完整目录页。
            # get_effective_suite 优先用项目显式选择的全局套件库套件，否则回退到项目内生成套件。
            # 有有效套件的项目不再拉取/使用任何全局模板（模板仅作为生成套件的可选来源）。
            from ..template.template_suite_renderer import TemplateSuiteRenderer as _TSR
            page_type = _TSR.normalize_page_type(slide_data, page_number, total_pages)
            suite_skeleton_marker = ""  # 套件 header_footer 的特征标记，用于校验内容页是否使用了套件骨架
            suite_constraint = ""
            selected_template = None  # 仅在无有效套件时使用全局模板
            if project_id:
                try:
                    suite = await self.template_suite.get_effective_suite(project_id)
                    # 品牌实例化：把套件里固化的年份/部门/主题/标语替换为项目真实值
                    # （仅影响本次生成，不改库、不影响预览；新套件走品牌槽位，老套件走语义分析）。
                    instantiator = getattr(
                        self.template_suite, "instantiate_suite_brand_for_project", None
                    )
                    if suite and instantiator is not None:
                        suite = await instantiator(project_id, suite)
                except Exception as e:
                    logger.warning(f'获取模板套件失败，按现状生成: {e}')
                    suite = None
                if suite:
                    if page_type == "catalog" and str(suite.get("catalog") or "").strip():
                        suite_constraint = self._build_catalog_suite_constraint(suite)
                        suite_skeleton_marker = self._extract_suite_skeleton_marker(
                            str(suite.get("catalog") or "")
                        )
                        # 目录页：只参考套件目录设计，忽略母版模板
                    else:
                        filled = await self._try_fill_suite_slide(
                            suite, slide_data, page_number, total_pages, system_prompt
                        )
                        if filled:
                            return filled
                        suite_constraint = self._build_content_suite_constraint(suite, slide_data)
                        suite_skeleton_marker = self._extract_suite_skeleton_marker(
                            str(suite.get("header_footer") or "")
                        )
                        # 内容页：有套件时只按套件设计（页头页脚 + 设计令牌），忽略母版模板
                        if page_type == "content":
                            logger.info(
                                "第%s页使用套件设计（忽略母版模板），仅按套件页头页脚/设计令牌生成内容页",
                                page_number,
                            )
                else:
                    # 无有效套件（纯模板 / 无模板项目）才拉取全局母版。
                    try:
                        selected_template = await self.get_selected_global_template(project_id)
                        if selected_template:
                            logger.info(f"为第{page_number}页使用全局母版: {selected_template['template_name']}")
                    except Exception as e:
                        logger.warning(f'获取全局母版失败，使用默认生成方式: {e}')

            if selected_template:
                return await self._generate_slide_with_template(slide_data, selected_template, page_number, total_pages, confirmed_requirements, all_slides=all_slides, project_id=project_id, content_suite_constraint=suite_constraint)
            template_html = selected_template.get('html_template', '') if selected_template else ''
            await self._ensure_slide_images_context(slide_data, confirmed_requirements, page_number, total_pages, template_html)
            (
                style_genes,
                global_constitution,
                current_page_brief,
            ) = await self._get_creative_design_inputs(project_id, template_html, slide_data, page_number, total_pages, confirmed_requirements=confirmed_requirements, all_slides=all_slides)
            images_collection = await self._process_slide_image(slide_data, confirmed_requirements, page_number, total_pages, template_html)
            if images_collection and images_collection.total_count > 0:
                slide_data['images_collection'] = images_collection
                slide_data['images_info'] = images_collection.to_dict()
                slide_data['images_summary'] = images_collection.get_summary_for_ai()
                logger.info(f'为第{page_number}页添加{images_collection.total_count}张图片: 本地{images_collection.local_count}张, 网络{images_collection.network_count}张, AI生成{images_collection.ai_generated_count}张')
            context_info = self._build_slide_context(slide_data, page_number, total_pages)
            context = prompts_manager.get_single_slide_html_prompt(
                slide_data, confirmed_requirements, page_number, total_pages,
                context_info, style_genes, template_html,
                global_constitution=global_constitution,
                current_page_brief=current_page_brief,
                content_suite_constraint=suite_constraint,
            )
            html_content = await self._generate_html_with_retry(context, system_prompt, slide_data, page_number, total_pages, max_retries=5)
            # 套件内容/目录页安全网：若输出未包含套件骨架标记，重试一次并强调必须用套件骨架整页。
            if page_type in ("content", "catalog") and suite_skeleton_marker and suite_skeleton_marker not in html_content:
                logger.warning(
                    "第%s页未使用套件骨架（缺 %s），重试生成一次...",
                    page_number,
                    suite_skeleton_marker,
                )
                context_retry = (
                    f"{context}\n\n注意：上一次输出未包含套件骨架（缺 {suite_skeleton_marker}）。"
                    "本页必须使用上方「内容页强约束/目录页强约束」中的套件骨架作为整页，"
                    "只替换槽位、沿用其设计语言与类名，不得自行设计整页骨架。"
                )
                html_content = await self._generate_html_with_retry(
                    context_retry, system_prompt, slide_data, page_number, total_pages, max_retries=2
                )
            # C1：内容页/目录页 LLM 输出后兜底替换残留的套件占位符（{{page_title}} 等），
            # 避免 LLM 未替换的槽位原样进最终页面（用户报告 6/7/8 页占位符残留）。
            if page_type in ("content", "catalog") and suite:
                # 章节提示：契合"仅内容页展示"——内容页用全部章节名块列表确定性填充
                # {{chapter_indicator}}（目录页/其他页若套件里有该槽位也会被清空）。
                chapter_indicator_html = self.build_chapter_indicator_html(all_slides, slide_data)
                html_content = self._replace_remaining_content_slots(
                    html_content, slide_data, page_number, total_pages,
                    chapter_indicator_html=chapter_indicator_html,
                )
                # D1：内容页样式全丢兜底——若 LLM 保留了骨架 div 却丢掉了套件 <style> 块，
                # 从套件 header_footer 里把 CSS 补回 head（用户报告 4/5/9/10 页样式丢失）。
                if page_type == "content":
                    html_content = self._ensure_content_suite_style_injected(html_content, suite)
                    # B3：章节提示兜底样式——若套件没为 .chapter-indicator 提供 CSS，注入默认导航样式。
                    html_content = self._ensure_chapter_indicator_style(html_content, suite)
                    # A：body 默认 8px margin 兜底清零——内容页 HTML 必须 1280×720 无滚动条
                    # （套件 header_footer 是内层片段，多数不带 body reset）。
                    html_content = self._ensure_suite_body_reset(html_content)
            return html_content
        except Exception as e:
            logger.error(f'Error generating single slide HTML with prompts: {e}')
            fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
        repaired_fallback = await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)
        return repaired_fallback

    # ------------------------------------------------------------------
    # 模板套件辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_suite_skeleton_marker(header_footer: str) -> str:
        """从套件 header_footer/catalog 提取一个特征标记（首个 class 名），
        用于校验生成页是否使用了套件骨架。

        注意：套件 HTML 的 class 既可能用双引号 `class="..."`，也可能用单引号
        `class='...'`（大纲智能套件库实测为单引号）。同时匹配两种引号，否则
        正则恒不命中、退化为取前 20 字符（如 `<!DOCTYPE html><html`），导致
        重试安全网永不触发。
        """
        import re as _re

        hf = header_footer or ""
        m = _re.search(r"class=[\"']([A-Za-z0-9_-]+)", hf)
        if m:
            return m.group(1)
        stripped = hf.strip()
        return stripped[:20] if stripped else ""

    @staticmethod
    def _build_deterministic_page_content(slide_data: Dict[str, Any], page_number: int) -> str:
        """兜底正文：用卡片化结构呈现本页 content_points，自带可读样式。

        当 LLM 未填 `{{page_content}}` 槽位时用这段确定性正文填入，避免页面出现
        空占位或正文沉底。设计为自包含内联样式、不依赖套件 CSS 也能成立。
        """
        slide_data = slide_data or {}
        title = str(slide_data.get("title") or "").strip() or f"第{page_number}页"
        content_points = slide_data.get("content_points") or slide_data.get("content") or []
        if isinstance(content_points, str):
            points = [p.strip() for p in content_points.split("\n") if p.strip()]
        elif isinstance(content_points, list):
            points = [str(p).strip() for p in content_points if str(p).strip()]
        else:
            points = []
        if not points:
            points = [title]
        cards = []
        for i, pt in enumerate(points, 1):
            cards.append(
                f'<div style="display:flex;align-items:flex-start;gap:14px;'
                f'padding:14px 18px;border-left:3px solid currentColor;'
                f'background:rgba(127,127,127,0.04);border-radius:6px;">'
                f'<span style="font-size:15px;font-weight:700;line-height:1.4;'
                f'flex-shrink:0;">{i:02d}</span>'
                f'<span style="font-size:16px;line-height:1.55;">{pt}</span>'
                f'</div>'
            )
        return (
            f'<div style="display:flex;flex-direction:column;gap:12px;'
            f'padding:8px 4px;">' + "".join(cards) + '</div>'
        )

    @staticmethod
    def build_chapter_indicator_html(
        all_slides: List[Dict[str, Any]],
        slide_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """确定性构建"章节提示" HTML：当前 PPT 全部章节名块列表，当前章节块加 `.current` 高亮。

        仅用于内容页 header_footer 的 `{{chapter_indicator}}` 槽位（勾选"章节提示"后由套件生成，
        这里在生成内容页时确定性填充，不经 LLM）：
        - 章节名 = 各章节首个 content 页的 title（与大纲 `_assign_chapter_numbers` 的章节号一致）；
        - 每章节一个 `.chapter-item` 块，当前章节（slide_data 的 chapter）额外加 `.current`；
        - 外层容器 `<div class="chapter-indicator">`，块样式由套件 header_footer 的 CSS 或兜底 CSS 提供；
        - 无任何章节时返回空串（替换对无该槽位的 HTML 无害）。
        """
        import re as _re
        from collections import OrderedDict

        slide_data = slide_data or {}
        current = 0
        try:
            current = int(slide_data.get("chapter") or 0)
        except (TypeError, ValueError):
            current = 0

        chapters: "OrderedDict[int, str]" = OrderedDict()
        for s in all_slides or []:
            if not isinstance(s, dict):
                continue
            stype = str(s.get("slide_type") or s.get("type") or "").strip().lower()
            if stype != "content":
                continue
            try:
                ch = int(s.get("chapter") or 0)
            except (TypeError, ValueError):
                ch = 0
            if ch < 1 or ch in chapters:
                continue
            title = str(s.get("title") or "").strip()
            chapters[ch] = title or f"第{ch}章"

        if not chapters:
            return ""

        def _esc(text: str) -> str:
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        items = []
        for ch, name in chapters.items():
            cls = "chapter-item" + (" current" if ch == current else "")
            items.append(f'<span class="{cls}">{_esc(name)}</span>')
        return '<div class="chapter-indicator">' + "".join(items) + "</div>"

    @staticmethod
    def _ensure_chapter_indicator_style(html: str, suite: dict) -> str:
        """B3 兜底：若内容页出现 `.chapter-indicator` 但套件未定义其样式，注入默认 CSS。

        套件 header_footer 勾选"章节提示"时会设计 `.chapter-indicator`/`.chapter-item`/
        `.chapter-item.current` 的样式；若 LLM 生成的 header_footer 只放了容器却没写样式
        （或槽位未定义），这里注入一套中性的横向导航样式兜底，保证非空、可读。
        已定义 `.chapter-indicator{` 规则则跳过（LLM 设计样式优先）。
        """
        if not html or not suite:
            return html
        import re as _re

        if "chapter-indicator" not in html:
            return html
        if _re.search(r"\.chapter-indicator\s*\{", html):
            return html  # 已有样式，跳过
        hf = str(suite.get("header_footer") or "")
        if not _re.search(r"\.chapter-indicator\s*\{", hf):
            inject = (
                '<style id="chapter-indicator-fallback">'
                ".chapter-indicator{display:flex;flex-wrap:wrap;gap:8px;align-items:center;"
                "font-family:inherit;} "
                ".chapter-indicator .chapter-item{display:inline-block;padding:4px 12px;"
                "border:1px solid rgba(127,127,127,0.35);border-radius:20px;"
                "font-size:12px;line-height:1.4;color:#4b5563;opacity:0.85;} "
                ".chapter-indicator .chapter-item.current{"
                "background:#c00000;border-color:#c00000;color:#ffffff;font-weight:700;opacity:1;}"
                "</style>"
            )
            lowered = html.lower()
            idx_head = lowered.rfind("</head>")
            if idx_head != -1:
                return html[:idx_head].rstrip() + "\n" + inject + "\n" + html[idx_head:]
            idx_body = lowered.rfind("</body>")
            if idx_body != -1:
                return html[:idx_body].rstrip() + "\n" + inject + "\n" + html[idx_body:]
            return html.rstrip() + "\n" + inject
        # 套件 header_footer 自身已定义 `.chapter-indicator` 样式（但生成页没带）→ 由
        # _ensure_content_suite_style_injected 负责从套件补回，这里不重复注入。
        return html

    @staticmethod
    def _replace_remaining_content_slots(
        html: str, slide_data: Dict[str, Any], page_number: int, total_pages: int,
        chapter_indicator_html: str = "",
    ) -> str:
        """C1 兜底：替换内容页 LLM 输出里残留的套件槽位。

        内容页不走 _try_fill_suite_slide 的确定性填充，全靠 LLM 自己替换
        `{{page_title}}`/`{{page_content}}`/`{{current_page_number}}`/
        `{{total_page_count}}`。LLM 偶尔保留原始 token，需这里兜底替换，
        否则占位符原样进最终 HTML（用户报告 6/7/8 页现象）。

        仅替换这四个内容页已知槽位（及章节号/章节提示）；其它未知槽位（如套件特有的额外槽位）保留，
        避免误伤。

        chapter_indicator_html：勾选"章节提示"时，由调用方用
        SlideMediaService.build_chapter_indicator_html 预生成的章节提示 HTML；为空则
        `{{chapter_indicator}}` 被替换为空串清掉（不残留）。
        """
        if not html:
            return html
        import re as _re
        slide_data = slide_data or {}
        title = str(slide_data.get("title") or "").strip() or f"第{page_number}页"
        body = SlideMediaService._build_deterministic_page_content(slide_data, page_number)
        mapping = {
            "page_title": title,
            "page_content": body,
            "current_page_number": str(page_number),
            "total_page_count": str(total_pages),
            "chapter_number": str((slide_data or {}).get("chapter") or ""),
            "chapter_indicator": chapter_indicator_html,
        }
        def _sub(m: _re.Match) -> str:
            name = m.group(1).strip()
            if name in mapping:
                return str(mapping[name])
            return m.group(0)
        return _re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", _sub, html)

    @staticmethod
    def _ensure_content_suite_style_injected(html: str, suite: Dict[str, Any]) -> str:
        """D1 兜底：若生成页缺失套件 header_footer 的 `<style>` 块，从套件里补回。

        用户报告 4/5/9/10 页"样式全丢"：LLM 保留了骨架 div、却丢掉了尾部
        `<style>` 块，导致无布局样式。这里检测输出是否含套件 header_footer 的
        首条 CSS 规则（如 `.slide-page{`），缺失则把套件 header_footer 里的
        整个 `<style>` 块注入到生成页的 `</head>` 前。

        若连 `</head>` 都没有（LLM 输出结构异常），退一步注入到 `</body>` 前；
        再不行原样追加。不重写整个页面，只补 CSS，避免破坏 LLM 的正文内容。
        """
        if not html or not suite:
            return html
        import re as _re
        hf = str(suite.get("header_footer") or "")
        if not hf:
            return html
        # 取套件 header_footer 里的 <style>...</style>（可能多个，全收）
        style_blocks = _re.findall(r"<style[^>]*>(.*?)</style>", hf, flags=_re.DOTALL)
        if not style_blocks:
            return html
        # 选一条最具代表性的 CSS：含页头页脚/骨架类规则的那块（通常最大）。
        target_block_style = max(style_blocks, key=len)
        # 判断注入点：优先 </head>，其次 </body>，最后直接 append。
        # 用第一个 CSS 选择器第一条规则名做存在性探测（如 .slide-page{ / .page-header{）
        first_rule = _re.search(r"([.#][A-Za-z0-9_-]+)\s*\{", target_block_style)
        probe = first_rule.group(1) if first_rule else None
        if probe and probe in html:
            # 生成页已经含有这条套件骨架 CSS 选择器 → 认为样式在，无需注入。
            return html
        inject = f'<style id="suite-style-backfill">{target_block_style}</style>'
        lowered = html.lower()
        idx_head = lowered.rfind("</head>")
        if idx_head != -1:
            return html[:idx_head].rstrip() + "\n" + inject + "\n" + html[idx_head:]
        idx_body = lowered.rfind("</body>")
        if idx_body != -1:
            return html[:idx_body].rstrip() + "\n" + inject + "\n" + html[idx_body:]
        return html.rstrip() + "\n" + inject

    @staticmethod
    def _ensure_suite_body_reset(html: str) -> str:
        """A 兜底：内容页 body 默认 8px margin 会把 1280×720 骨架撑到 1296×736，产生滚动条。

        套件 header_footer 是内层片段，多数（如库套件 id=14）不带头部 html/body reset，
        LLM 自包 <body> 时继承浏览器默认 margin。这里无论套件/LLM 输出如何，确定性注入
        body reset（html/body 1280×720 + margin:0 + overflow:hidden）。若页面已含等效
        reset（`*{margin:0}` 或 `html,body{margin:0}` / `body{margin:0}`）则跳过。
        """
        if not html:
            return html
        import re as _re
        lowered = html.lower()
        if (
            _re.search(r"html\s*,\s*body\s*\{[^}]*margin\s*:\s*0", lowered)
            or _re.search(r"(?<![A-Za-z0-9_-])body\s*\{[^}]*margin\s*:\s*0", lowered)
            or _re.search(r"\*\s*\{[^}]*margin\s*:\s*0", lowered)
        ):
            return html
        inject = (
            '<style id="suite-body-reset">'
            "html,body{width:1280px;height:720px;margin:0!important;overflow:hidden!important;"
            "box-sizing:border-box}"
            "</style>"
        )
        idx_head = lowered.rfind("</head>")
        if idx_head != -1:
            return html[:idx_head].rstrip() + "\n" + inject + "\n" + html[idx_head:]
        idx_body = lowered.rfind("</body>")
        if idx_body != -1:
            return html[:idx_body].rstrip() + "\n" + inject + "\n" + html[idx_body:]
        return html.rstrip() + "\n" + inject

    @staticmethod
    def _extract_suite_design_language(suite: Dict[str, Any]) -> str:
        """从套件各页面提取整体设计语言（配色 + 字体），供内容页保持一致。

        标题页/过渡/目录/结尾与内容页常为互补色系，只参考内容页会导致内容页
        另造一套颜色；这里汇总整套配色与字体，让内容页沿用整体色板。
        """
        import re as _re
        from collections import Counter

        parts = []
        for key in ("cover", "transition", "catalog", "ending", "header_footer"):
            html = str(suite.get(key) or "")
            if html:
                parts.append(html)
        if not parts:
            return ""
        all_html = "\n".join(parts)

        # 提取 6 位/3 位 hex 颜色
        colors = _re.findall(r"#[0-9a-fA-F]{6}\b", all_html)
        colors += [
            _re.sub(r"#([0-9a-fA-F])([0-9a-fA-F])([0-9a-fA-F])\b", r"#\1\1\2\2\3\3", m)
            for m in _re.findall(r"#[0-9a-fA-F]{3}\b", all_html)
        ]
        counter = Counter(c.lower() for c in colors)
        # 过滤纯黑/纯白/透明，取出现最多的颜色作为色板
        ignored = {"#000000", "#ffffff"}
        palette = [c for c, _ in counter.most_common(16) if c.lower() not in ignored][:10]

        # 字体（取前几个 font-family 的字面量）
        fonts = _re.findall(r"font-family\s*:\s*([^;}{]+)", all_html)
        font_pool = []
        for f in fonts:
            for name in f.split(","):
                name = name.strip().strip("'\"")
                if name and name not in font_pool and not name.startswith("var("):
                    font_pool.append(name)
            if len(font_pool) >= 3:
                break

        lines = []
        if palette:
            lines.append("套件整体配色（内容页选色必须从以下色板中取，不得另造新色）：" + "、".join(palette))
        if font_pool:
            lines.append("套件字体：" + "、".join(font_pool[:3]))
        return "\n".join(lines)

    @staticmethod
    def _build_content_suite_constraint(suite: Dict[str, Any], slide_data: Optional[Dict[str, Any]] = None) -> str:
        """Build the strong content-page constraint text.

        让 LLM 把套件的 header_footer 当作内容页的整页骨架逐字保留，只替换槽位；
        正文放 {{page_content}}，避免出现双标题 / 层级错乱 / 风格不一的页面。
        slide_data 用于把本页真实章节号（chapter 字段）传给 LLM 填 {{chapter_number}}。
        """
        header_footer = str(suite.get("header_footer") or "").strip()
        if not header_footer:
            return ""
        tokens = str(suite.get("design_tokens") or "").strip()
        design_lang = SlideMediaService._extract_suite_design_language(suite)
        slide_data = slide_data or {}
        chapter = slide_data.get("chapter")
        # chapter=0 表示"不属于任何章节"（封面/目录/结尾等），绝不渲染成"第 0 章"。
        chapter_num_text = str(chapter) if chapter not in (None, "", 0) else "（本页不属于任何章节，章节号槽位留空）"
        lines = [
            "**内容页强约束（必须把下面这段 HTML 作为本页的整页骨架，逐字保留，不得重新设计、不得丢弃任何元素——尤其 `<style>` 块必须整段保留，缺了样式整页就废了）**",
            "页头与页脚（含高度、位置、背景、装饰、样式）必须与套件**完全一致**，禁止改动高度/位置/配色；"
            "**只有 `{{page_content}}` 内容区域随每页内容变化**。",
            "本页 HTML 输出为 `<!DOCTYPE html>...<body>` 包裹该骨架；骨架通常是 1280×720 的容器"
            "（含背景/装饰/页头/页脚/正文占位）；**套件骨架里的 `<style>` 块必须整段照抄进本页 `<head>`，不得省略、不得改写规则**。",
            "**必须把以下槽位用真实内容替换，不得保留 `{{...}}` 原样**（双大括号是占位符，不是装饰）：",
            "  - `{{page_title}}` → 本页标题（**标题只出现在这里**；正文内容里不要再出现与页头重复的大标题/标题块）；",
            "  - `{{current_page_number}}` / `{{total_page_count}}` → 页码（数字）；",
            f"  - `{{chapter_number}}` → 本页所属章节序号（纯数字）：**{chapter_num_text}**；骨架里若无该槽位则忽略，有则必须替换为这个数字，不得保留 `{{chapter_number}}` 原样；",
            "  - `{{page_content}}` → 本页正文内容（**填在该槽位处，作为页头与页脚之间的正文占位区；正文不得放到该槽位之外、不得在骨架外另起内容块、不得放在页面底部**）。排版沿用骨架的配色/字体。",
            "层级与布局：背景/装饰层绝对定位铺满整页且 z-index 低；正文内容容器 z-index 必须**高于**背景/装饰层，"
            "正文不能被背景图案盖住；正文不要溢出到页头/页脚区域。",
            "配色/字体：正文排版必须从套件整体色板中选色（见下方「套件整体设计语言」），不得另造新色；"
            "让整页与套件风格完全一致。",
            "**标准正文舞台 `.suite-stage`**：套件骨架里已含 `<div class=\"suite-stage\">...{{ page_content }}...</div>`，"
            "其位置固定、`overflow:hidden` 兜住溢出，内宽 1160px。"
            "**所有正文内容必须写在 `.suite-stage` 容器内**——它已避开页头分割线、不压页脚；超出会被容器 overflow:hidden 兜住，"
            "所以请通过优化布局密度让内容落进 1160×~530px 区域，而不是溢出到页头页脚。",
            "**`.suite-stage` 的 top 必须保持套件骨架给定的值（不得改小/上移）**——这是按套件实测的页头底边精确算出的"
            "安全间距，改小会让正文与页头分割线交叉。",
            "**布局列宽基准为 `.suite-stage` 内宽 1160px**：flex/grid 多列时 `gap + 各列宽 ≤ 1160px`；"
            "用 `flex:1` 自适应或 `calc(100% - Npx)` 计算列宽，禁用 `45%+55%+gap` 这种必然超出容器右沿的组合；"
            "百分比列宽以容器内宽为基准，而非 1280px。",
        ]
        # 章节提示槽位：若骨架含 {{chapter_indicator}}，后端会确定性填入全部章节名的块列表并高亮当前章节，
        # 因此要求 LLM 保留该槽位原样、不要删除也不要用文字顶替（避免页头出现无样式残留）。
        if "chapter_indicator" in header_footer:
            lines.append(
                "  - `{{chapter_indicator}}` → 章节提示（**保留该槽位原样，不要移除、不要替换成文字**）；"
                "生成本页时后端会自动把它填成全部章节名的块列表并高亮当前章节，保持骨架里的容器与样式即可。"
            )
        if design_lang:
            lines.append(f"\n**套件整体设计语言（内容页配色/字体必须沿用）**\n{design_lang}")
        lines += [
            "**骨架 HTML（逐字保留，仅替换槽位）**",
            "```html",
            header_footer,
            "```",
        ]
        if tokens:
            lines.append(f"\n**设计令牌（内容页全局对齐）**\n{tokens}")
        return "\n".join(lines)

    @staticmethod
    def _build_catalog_suite_constraint(suite: Dict[str, Any]) -> str:
        """Build the catalog-page reference constraint for LLM generation.

        目录页不再做确定性模板填充：把套件里的目录页当作设计骨架，让 LLM
        按真实章节（content_points）生成完整目录页，**整页沿用其视觉/布局/条目排版**，
        并显式锚定套件整体配色/字体，避免 LLM 私自换色。
        """
        catalog = str(suite.get("catalog") or "").strip()
        if not catalog:
            return ""
        design_lang = SlideMediaService._extract_suite_design_language(suite)
        lines = [
            "**目录页强约束（必须以套件里的目录页为整页设计骨架，沿用其视觉/布局/条目排版，不得重新设计整页）**",
            "- 用套件目录页作为本页骨架：保留其背景/装饰/标题样式/目录条目区的整体结构与类名（编号、分隔线、行布局、配色）。",
            "- 只替换槽位：`{{catalog_title}}`→本页标题（如“目录”）、`{{catalog_subtitle}}`→副标题、`{{catalog_extra}}`→（可空）。",
            "- 目录条目用本页真实章节（slide_data 的 content_points），逐条套用参考页条目区的样式（编号/分隔/布局/配色）呈现。",
            "- 不要照抄参考页里的示例章节文案，但**整页的设计语言、类名、结构、配色必须沿用参考页**（不得改成其它配色/布局）。",
            "- **配色/字体必须与套件整本一致**：背景、标题色、编号色、分隔色等都从套件整体色板取色，严禁另造新色（如套件是红主题就不能生成蓝色目录页）。",
        ]
        if design_lang:
            lines.append(f"\n**套件整体设计语言（目录页配色/字体必须沿用）**\n{design_lang}")
        lines += [
            "```html",
            catalog,
            "```",
        ]
        return "\n".join(lines)

    async def _try_fill_suite_slide(
        self,
        suite: Dict[str, Any],
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        system_prompt: str,
    ) -> Optional[str]:
        """Fill a cover/transition slide from the suite template.

        Returns the completed HTML, or None when this page type is not covered by
        the suite (caller falls through). Leftover optional slots (e.g.
        {{ cover_extra }}) are filled with an LLM that understands the page's
        meaning; if the LLM pass fails, a smart deterministic fallback is used —
        the suite still renders, and never falls back to the generic path.
        """
        from ..template.template_suite_renderer import TemplateSuiteRenderer

        filled = TemplateSuiteRenderer.apply_suite_to_slide(
            suite, slide_data, page_number, total_pages
        )
        if not filled:
            return None

        # Fill leftover optional slots: LLM-first (semantic), deterministic fallback.
        remaining = TemplateSuiteRenderer.find_unfilled_slots(filled)
        if remaining:
            slot_values = await self._resolve_remaining_slots(
                filled, remaining, slide_data, page_number, total_pages, system_prompt
            )
            filled = TemplateSuiteRenderer.fill_suite_template(filled, slot_values)
        logger.info("第%s页使用模板套件渲染（封面/过渡/目录/结尾）", page_number)
        return filled

    async def _resolve_remaining_slots(
        self,
        html: str,
        remaining_slots: list,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        system_prompt: str,
    ) -> Dict[str, str]:
        """Resolve leftover optional slot values.

        Tries one LLM call that understands the slide's meaning and fills the
        slots; on any failure, falls back to deterministic values derived from
        real content (never from the page-type description, so "PPT封面页" /
        "章节过渡页" labels never leak into the rendered slide).
        """
        # Deterministic fallback first (always safe).
        fallback = {
            name: self._default_slot_text(name, slide_data, page_number)
            for name in remaining_slots
        }

        try:
            slots_text = "、".join(f"{{{{{s}}}}}" for s in remaining_slots)
            title = str(slide_data.get("title") or "").strip() or f"第{page_number}页"
            description = str(slide_data.get("description") or "").strip()
            content_points = slide_data.get("content_points") or []
            if isinstance(content_points, list):
                points_text = "；".join(str(p).strip() for p in content_points[:4] if str(p).strip())
            else:
                points_text = str(content_points).strip()

            context = (
                f"请为以下 {page_number}/{total_pages} 页的封面/章节过渡/目录/结尾页，补充其额外文案槽位"
                f"（{slots_text}），使其成为自然、专业的演示文案。\n\n"
                f"**页面标题**：{title}\n"
                f"**页面定位**：{description or '（未提供，请按标题自行推断）'}\n"
                f"**内容要点**：{points_text or '（无）'}\n\n"
                "**要求**：\n"
                "- 只输出各槽位的填充文案，用 JSON 对象，键为槽位名，值为一句/短语文案。\n"
                "- 文案要贴合页面定位与内容，不要出现『PPT封面页』『章节过渡页』『标题页』这类对页面类型的描述性称呼。\n"
                "- **槽位值必须是纯文本**，严禁返回对象/字典/数组/嵌套 JSON 结构；如需多行文案用 `\\n` 分隔。\n"
                "- 若某个槽位不适用，值给空字符串即可。\n"
                "- 只输出 JSON，不要附加解释。"
            )
            response = await self._text_completion_for_role(
                "creative", prompt=context, temperature=0.6, max_tokens=300
            )
            raw = self._strip_think_tags((response.content or "").strip())
            import json as _json
            parsed = _json.loads(self._extract_json_object(raw))
            result: Dict[str, str] = {}
            for name in remaining_slots:
                value = str(parsed.get(name) or "").strip()
                # 净化：若 LLM 把槽位值写成了嵌套 dict/list（如 cover_extra 被填成
                # "{'subtitle': ...}"），提取为可读纯文本；否则回退确定性兜底。
                result[name] = self._sanitize_slot_value(value, fallback[name])
            return result
        except Exception as exc:
            logger.warning(
                "第%s页套件槽位 LLM 补全失败，使用确定性兜底: %s", page_number, exc
            )
            return fallback

    @staticmethod
    def _sanitize_slot_value(value: str, fallback: str = "") -> str:
        """净化 LLM 返回的槽位值：若它是嵌套 JSON/Python dict/list 字符串
        （如 `{'subtitle': '...', 'presenter': '...'}`），解析并提取为可读纯文本。

        - dict → 取最长（最有信息量）的值；值仍是嵌套 → 递归一次；
        - list → 各元素用换行连接；
        - 解析失败 / 结果为空 → 回退 fallback（确定性兜底）。
        """
        import json as _json
        import ast as _ast

        v = (value or "").strip()
        if not v:
            return fallback
        if not (v.startswith("{") or v.startswith("[")):
            return v

        parsed = None
        for parser in (lambda s: _json.loads(s), _ast.literal_eval):
            try:
                parsed = parser(v)
                break
            except Exception:
                continue
        if parsed is None:
            return fallback
        if isinstance(parsed, dict):
            if not parsed:
                return fallback
            longest = max(parsed.values(), key=lambda x: len(str(x)), default="")
            if isinstance(longest, (dict, list)):
                # 值仍是嵌套 → 递归一次防御
                return SlideMediaService._sanitize_slot_value(
                    _json.dumps(longest, ensure_ascii=False), fallback
                )
            return str(longest).strip() or fallback
        if isinstance(parsed, list):
            items = [str(x).strip() for x in parsed if str(x).strip()]
            return "\n".join(items) if items else fallback
        return str(parsed).strip() or fallback

    @staticmethod
    def _extract_json_object(text: str) -> str:
        """Best-effort extraction of a JSON object from a model response."""
        if not text:
            return "{}"
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
        return text

    @staticmethod
    def _default_slot_text(name: str, slide_data: Dict[str, Any], page_number: int) -> str:
        """Smart deterministic fallback for an unfilled optional slot.

        Deliberately derives from real content (content_points) and never from
        the page-type description, so labels like "PPT封面页" / "章节过渡页"
        never leak into the rendered slide.
        """
        slide_data = slide_data or {}
        # 品牌槽位（brand_ 前缀）由品牌实例化统一替换；这里兜底清空，
        # 避免出现 "[brand_org]" 这类占位残留（也不应交给每页 LLM 补全导致各页不一致）。
        if str(name or "").startswith("brand_"):
            return ""

        # 章节号槽位（过渡页/内容页）：取大纲后端赋的 chapter 字段，纯数字。
        # chapter 为 0/缺失（非章节页或未归属）→ 返回空串清掉槽位（绝不渲染成"第 0 章"）。
        if name == "chapter_number":
            chapter = slide_data.get("chapter")
            return str(chapter) if chapter not in (None, "", 0) else ""

        def _first_content_point() -> str:
            content_points = slide_data.get("content_points") or slide_data.get("content") or []
            if isinstance(content_points, list):
                for p in content_points:
                    p = str(p).strip()
                    if p:
                        return p
            elif isinstance(content_points, str) and content_points.strip():
                return content_points.strip()
            return ""

        def _title() -> str:
            return str(slide_data.get("title") or "").strip() or f"第{page_number}页"

        if name == "cover_extra":
            point = _first_content_point()
            if point:
                return point
            return f"—— {_title()} ——"
        if name == "transition_extra":
            return ""
        if name == "catalog_extra":
            return ""
        if name == "ending_extra":
            return ""
        if name in ("catalog_items", "ending_items"):
            content_points = slide_data.get("content_points") or slide_data.get("content") or []
            if isinstance(content_points, list):
                return "\n".join(str(p).strip() for p in content_points if str(p).strip())
            if isinstance(content_points, str) and content_points.strip():
                return content_points.strip()
            return ""
        return f"[{name}]"

    async def _process_slide_image(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any], page_number: int, total_pages: int, template_html: str=''):
        """使用图片处理器处理幻灯片多图片"""
        try:
            existing_collection = slide_data.get('images_collection')
            if existing_collection is not None:
                return existing_collection
            from ..ppt_image_processor import PPTImageProcessor
            from ..models.slide_image_info import SlideImagesCollection
            image_processor = PPTImageProcessor(image_service=self.image_service, user_id=self.user_id, provider_override=self.provider_name)
            return await image_processor.process_slide_image(slide_data, confirmed_requirements, page_number, total_pages, template_html)
        except Exception as e:
            logger.error(f'图片处理器处理失败: {e}')
            return None

    async def _ensure_slide_images_context(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any], page_number: int, total_pages: int, template_html: str='') -> None:
        """Populate image-related context onto slide data before prompt generation."""
        images_collection = await self._process_slide_image(slide_data, confirmed_requirements, page_number, total_pages, template_html)
        if images_collection and images_collection.total_count > 0:
            slide_data['images_collection'] = images_collection
            slide_data['images_info'] = images_collection.to_dict()
            slide_data['images_summary'] = images_collection.get_summary_for_ai()
            logger.info(f'第{page_number}页添加{images_collection.total_count}张图片资源，本地{images_collection.local_count}张，网络{images_collection.network_count}张，AI生成{images_collection.ai_generated_count}张')

    def _get_innovation_guidelines(self, slide_type: str, page_number: int, total_pages: int) -> List[str]:
        """Get innovation guidelines based on slide type and position"""
        guidelines = []
        if page_number == 1:
            guidelines.extend(['- 标题页：可以创新的开场设计，如独特的标题排版、引人注目的视觉元素', '- 考虑使用大胆的视觉冲击力，为整个演示定下基调'])
        elif page_number == total_pages:
            guidelines.extend(['- 结尾页：可以设计总结性的视觉元素，如回顾要点的创新布局', '- 考虑使用呼应开头的设计元素，形成完整的视觉闭环'])
        else:
            guidelines.extend(['- 内容页：可以根据内容特点选择最适合的展示方式', '- 考虑使用渐进式的视觉变化，保持观众的注意力'])
        content_innovations = {'title': ['- 可以尝试非对称布局、创意字体排列、背景图案变化', '- 考虑添加微妙的动画效果或视觉引导元素'], 'content': ['- 可以创新内容组织方式：卡片式、时间线、流程图、对比表格等', '- 考虑使用图标、插图、数据可视化来增强信息传达', '- 可以尝试分栏布局、重点突出框、引用样式等'], 'conclusion': ['- 可以设计总结性的视觉框架：要点回顾、行动号召、联系方式展示', '- 考虑使用视觉化的总结方式，如思维导图、关键词云等']}
        if slide_type in content_innovations:
            guidelines.extend(content_innovations[slide_type])
        else:
            guidelines.extend(content_innovations['content'])
        guidelines.extend(['', '**创新原则：**', '- 在保持风格一致性的前提下，大胆尝试新的视觉表达方式', '- 根据内容的重要性和复杂度调整视觉层次', '- 考虑观众的阅读习惯和认知负荷', '- 确保创新不影响信息的清晰传达', '- 可以适度使用当前流行的设计趋势，但要与整体风格协调'])
        return guidelines

    async def _suggest_images(self, slide_title: str, scenario: str, content: str='', topic: str='', page_number: int=1, total_pages: int=1) -> List[str]:
        """Suggest images for a slide based on title and scenario"""
        try:
            if self.image_service:
                slide_context = PPTSlideContext(title=slide_title, content=content, scenario=scenario, topic=topic, page_number=page_number, total_pages=total_pages, language='zh')
                suggested_images = await self.image_service.suggest_images_for_ppt_slide(slide_context, max_suggestions=5)
                if suggested_images:
                    return [img.local_path for img in suggested_images if img.local_path]
            image_suggestions = {'general': ['business-meeting.jpg', 'professional-chart.jpg', 'office-space.jpg'], 'tourism': ['landscape.jpg', 'travel-destination.jpg', 'cultural-site.jpg'], 'education': ['classroom.jpg', 'learning-materials.jpg', 'students.jpg'], 'analysis': ['data-visualization.jpg', 'analytics-dashboard.jpg', 'research.jpg'], 'history': ['historical-artifact.jpg', 'ancient-building.jpg', 'timeline.jpg'], 'technology': ['innovation.jpg', 'digital-technology.jpg', 'futuristic.jpg'], 'business': ['corporate-building.jpg', 'business-strategy.jpg', 'team-meeting.jpg']}
            return image_suggestions.get(scenario, image_suggestions['general'])
        except Exception as e:
            logger.error(f'Failed to suggest images: {e}')
            return ['professional-slide.jpg', 'business-background.jpg', 'presentation-template.jpg']

    async def generate_slide_image(self, slide_title: str, slide_content: str, scenario: str, topic: str, page_number: int=1, total_pages: int=1, provider: str='dalle') -> Optional[str]:
        """为PPT幻灯片生成AI图片"""
        try:
            if not self.image_service:
                logger.warning('Image service not available')
                return None
            slide_context = PPTSlideContext(title=slide_title, content=slide_content, scenario=scenario, topic=topic, page_number=page_number, total_pages=total_pages, language='zh')
            from ..image.models import ImageProvider
            image_provider = ImageProvider.DALLE if provider.lower() == 'dalle' else ImageProvider.STABLE_DIFFUSION
            result = await self.image_service.generate_ppt_slide_image(slide_context, image_provider)
            if result.success and result.image_info:
                logger.info(f"Generated AI image for slide '{slide_title}': {result.image_info.local_path}")
                return result.image_info.local_path
            else:
                logger.warning(f'Failed to generate AI image: {result.message}')
                return None
        except Exception as e:
            logger.error(f'Error generating slide image: {e}')
            return None

    async def create_image_prompt_for_slide(self, slide_title: str, slide_content: str, scenario: str, topic: str, page_number: int=1, total_pages: int=1) -> str:
        """为PPT幻灯片创建图片生成提示词"""
        try:
            if not self.image_service:
                return f'Professional PPT slide background for {slide_title}, {scenario} style'
            slide_context = PPTSlideContext(title=slide_title, content=slide_content, scenario=scenario, topic=topic, page_number=page_number, total_pages=total_pages, language='zh')
            prompt = await self.image_service.create_ppt_image_prompt(slide_context)
            return prompt
        except Exception as e:
            logger.error(f'Error creating image prompt: {e}')
            return f'Professional PPT slide background for {slide_title}, {scenario} style'
