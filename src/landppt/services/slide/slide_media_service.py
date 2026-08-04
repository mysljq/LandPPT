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
            selected_template = None
            if project_id:
                try:
                    selected_template = await self.get_selected_global_template(project_id)
                    if selected_template:
                        logger.info(f"为第{page_number}页使用全局母版: {selected_template['template_name']}")
                except Exception as e:
                    logger.warning(f'获取全局母版失败，使用默认生成方式: {e}')

            # 模板套件：封面/过渡页优先用套件模板填充槽位；内容页注入页头页脚强约束。
            suite_constraint = ""
            if project_id:
                try:
                    suite = await self.template_suite.get_suite(project_id)
                except Exception as e:
                    logger.warning(f'获取模板套件失败，按现状生成: {e}')
                    suite = None
                if suite:
                    filled = await self._try_fill_suite_slide(
                        suite, slide_data, page_number, total_pages, system_prompt
                    )
                    if filled:
                        return filled
                    suite_constraint = self._build_content_suite_constraint(suite)

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
    def _build_content_suite_constraint(suite: Dict[str, Any]) -> str:
        """Build the strong header/footer constraint text for content pages."""
        header_footer = str(suite.get("header_footer") or "").strip()
        if not header_footer:
            return ""
        tokens = str(suite.get("design_tokens") or "").strip()
        lines = [
            "**页头页脚强约束（必须逐字保留以下 HTML 片段，仅替换其中槽位，不得改写其结构与样式）**",
            "```html",
            header_footer,
            "```",
        ]
        if tokens:
            lines.append(f"\n**设计令牌（内容页全局对齐）**\n{tokens}")
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
        logger.info("第%s页使用模板套件渲染（封面/过渡）", page_number)
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
                f"请为以下 {page_number}/{total_pages} 页的封面/章节过渡页，补充其额外文案槽位"
                f"（{slots_text}），使其成为自然、专业的演示文案。\n\n"
                f"**页面标题**：{title}\n"
                f"**页面定位**：{description or '（未提供，请按标题自行推断）'}\n"
                f"**内容要点**：{points_text or '（无）'}\n\n"
                "**要求**：\n"
                "- 只输出各槽位的填充文案，用 JSON 对象，键为槽位名，值为一句/短语文案。\n"
                "- 文案要贴合页面定位与内容，不要出现『PPT封面页』『章节过渡页』『标题页』这类对页面类型的描述性称呼。\n"
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
                result[name] = value or fallback[name]
            return result
        except Exception as exc:
            logger.warning(
                "第%s页套件槽位 LLM 补全失败，使用确定性兜底: %s", page_number, exc
            )
            return fallback

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
