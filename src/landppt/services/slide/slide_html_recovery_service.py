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
    from .slide_html_validation_service import SlideHtmlValidationService

class SlideHtmlRecoveryService:
    """Extracted logic from SlideHtmlValidationService."""

    def __init__(self, service: 'SlideHtmlValidationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @staticmethod
    def _extract_suite_locked_colors(context: str) -> Optional[set]:
        """从生成上下文提取模板套件"强约束"块中锁定区的既定配色。

        套件模式下，prompt 上下文会包含 `**页头页脚强约束**`/`**内容页强约束**`/
        `**目录页强约束**` 及其 ```html``` 片段（套件 header_footer/catalog 原文）。
        这些颜色是设计既定值，审美预检应跳过，避免把套件自身的页头红/页脚黄误判为
        LLM 的多 accent 套路。解析失败返回 None（等价于不排除任何颜色）。
        """
        if not context or "强约束" not in context:
            return None
        try:
            import re as _re
            # 提取强约束代码块（兼容"页头页脚强约束/内容页强约束/目录页强约束"三种标题）
            match = _re.search(
                r"强约束.*?```html\s*(.*?)```",
                context,
                flags=_re.DOTALL,
            )
            if not match:
                return None
            fragment = match.group(1)
            colors: set = set()
            for m in _re.finditer(r"#([0-9a-fA-F]{3,8})\b", fragment):
                h = m.group(1).upper()
                if len(h) == 3:
                    h = "".join(ch * 2 for ch in h)
                colors.add("#" + h)
            return colors or None
        except Exception:
            return None

    async def _measure_overflow(self, html_content: str, page_number: int):
        """按需用 Playwright 测量主内容区是否溢出 1280×720。

        返回 dict：{overflow_px, overflow_ratio, overflows:[...]} 或 None（不可用/关闭/异常）。
        设计为非阻塞：Playwright 未就绪、未启用或任何异常都静默返回 None，
        不影响主生成流程（此时溢出仅靠 prompt 层约束 + 防溢出 CSS 兜底）。
        """
        # 开关：默认开启，可用环境变量关闭以完全跳过浏览器测量开销
        enabled = os.getenv("ENABLE_OVERFLOW_MEASURE", "true").lower() in {"true", "1", "yes", "on"}
        if not enabled or not html_content or len(html_content) < 50:
            return None
        try:
            from ..pyppeteer_pdf_converter import get_pdf_converter
            converter = get_pdf_converter()
            if converter is None:
                return None
        except Exception as exc:
            logger.debug(f"Playwright 测量器不可用，跳过溢出测量 (slide {page_number}): {exc}")
            return None
        # 落临时文件给 Playwright 读取（与 screenshot_html 同路径）
        tmp_path = None
        try:
            tmp_path = tempfile.mkdtemp(prefix=f"slide_{page_number}_overflow_")
            html_file = Path(tmp_path) / "slide.html"
            html_file.write_text(html_content, encoding="utf-8")
            measure = await converter.measure_content_overflow(str(html_file))
            return measure
        except Exception as exc:
            logger.warning(f"溢出测量异常 (slide {page_number}, 非致命): {exc}")
            return None
        finally:
            if tmp_path:
                try:
                    shutil.rmtree(tmp_path, ignore_errors=True)
                except Exception:
                    pass

    async def _generate_html_with_retry(self, context: str, system_prompt: str, slide_data: Dict[str, Any], page_number: int, total_pages: int, max_retries: int=3) -> str:
        """Generate HTML with retry mechanism for incomplete responses"""
        # 从 prompt context 中解析全册页头页脚令牌（非解析失败也无妨，退化为常规审美预检）
        try:
            header_lock = self._parse_header_lock(context)
        except Exception:
            header_lock = None
        try:
            footer_lock = self._parse_footer_lock(context)
        except Exception:
            footer_lock = None
        # 若上下文含"页头页脚强约束"（模板套件模式），提取其锁定配色，
        # 供审美预检跳过套件自身的既定颜色（避免误判为 LLM 套路指纹）。
        excluded_colors = self._extract_suite_locked_colors(context)
        lock_repr = ', '.join(f'{k}={v}' for k, v in (header_lock or {}).items()) or '无'
        logger.info(f'页头令牌 (slide {page_number}): {lock_repr}')
        from .retry_progress import notify_retry_progress
        for attempt in range(max_retries):
            try:
                logger.info(f'Generating HTML for slide {page_number}, attempt {attempt + 1}/{max_retries}')
                # 实时上报：本轮开始生成（attempt 从 1 计数供展示）
                await notify_retry_progress(
                    page_number=page_number, total_pages=total_pages,
                    attempt=attempt + 1, max_retries=max_retries,
                    stage="generating",
                    detail=f"第 {page_number}/{total_pages} 页：正在生成 HTML（第 {attempt + 1}/{max_retries} 次）",
                )
                retry_context = context
                if attempt > 0:
                    retry_context += f'\n\n    **重要提醒（第{attempt + 1}次尝试）：**\n    - 前面的尝试可能生成了不完整的HTML，请确保这次生成完整的HTML文档\n    - 必须包含完整的HTML结构：<!DOCTYPE html>, <html>, <head>, <body>等标签\n    - 确保所有标签都正确闭合\n    - 使用markdown代码块格式：```html\n[完整HTML代码]\n```\n    - 不要截断HTML代码，确保以</html>结束\n    '
                response = await self._text_completion_for_role('slide_generation', prompt=retry_context, system_prompt=system_prompt, temperature=max(0.1, ai_config.temperature))
                try:
                    html_content = self._clean_html_response(response.content)
                    html_content = self._inject_anti_overflow_css(html_content)
                    if not html_content or len(html_content.strip()) < 50:
                        logger.warning(f'AI returned empty or too short HTML content for slide {page_number}')
                        continue
                except Exception as e:
                    logger.error(f'Error cleaning HTML response for slide {page_number}: {e}')
                    continue
                validation_result = self._validate_html_completeness(html_content)
                logger.info(f"HTML validation result for slide {page_number}, attempt {attempt + 1}: Complete: {validation_result['is_complete']}, Errors: {len(validation_result['errors'])}, Missing elements: {len(validation_result['missing_elements'])}")
                if validation_result['is_complete']:
                    if validation_result['missing_elements']:
                        logger.warning(f"Missing elements (warnings only): {', '.join(validation_result['missing_elements'])}")
                    logger.info(f'Successfully generated complete HTML for slide {page_number} on attempt {attempt + 1}')
                    # 审美维度预检（结构合法之后的第二道闸），传入页头/页脚令牌做跨页一致性守恒
                    # 非内容页（封面/尾页/目录/过渡）由预检器按 slide_data 自动豁免页头/页脚比对
                    aesthetic_hard, aesthetic_warn = self._aesthetic_preflight_check(
                        html_content, header_lock, footer_lock, slide_data, page_number, total_pages,
                        excluded_colors=excluded_colors)
                    if aesthetic_warn:
                        for w in aesthetic_warn:
                            logger.info(f'🎨 审美预警 (slide {page_number}): {w}')
                    if aesthetic_hard:
                        # hard fail：在仍有重试次数时重生成，否则降级返回当前结构合法的 HTML（审美软约束不阻塞交付）
                        hard_summary = '；'.join(aesthetic_hard)
                        logger.info(f'🎨 审美 hard fail (slide {page_number}, attempt {attempt + 1}): {hard_summary}')
                        if attempt < max_retries - 1:
                            logger.info(f'🔄 审美不符，重新生成 slide {page_number}...')
                            await notify_retry_progress(
                                page_number=page_number, total_pages=total_pages,
                                attempt=attempt + 2, max_retries=max_retries,
                                stage="aesthetic_retry",
                                detail=f"第 {page_number} 页审美预检不过，重试（{attempt + 2}/{max_retries}）：{'；'.join(aesthetic_hard)}",
                            )
                            # 把违规反馈注入下一轮 retry_context，让模型针对性修正
                            context = context + (
                                f'\n\n    **上一轮审美预检未通过，请修正以下问题：**\n    '
                                + '\n    '.join(f'- {h}' for h in aesthetic_hard)
                                + '\n    请确保本轮输出避开这些 AI 套路指纹。\n    '
                            )
                            continue
                        else:
                            logger.warning(f'⚠️ 审美未达标但已用尽重试次数，交付当前结构合法的 slide {page_number}')
                            return await self._apply_auto_layout_repair(html_content, slide_data, page_number, total_pages)
                    # 审美通过后：测量主内容区是否溢出固定画布（Playwright 测高，非阻塞）
                    overflow = await self._measure_overflow(html_content, page_number)
                    # 阈值收紧：轻微溢出（≤12px 且占比≤2%）靠防溢出 CSS 自处理即可，
                    # 不触发重生成，避免不必要地反复烧 token。
                    ov_px = int(overflow.get('overflow_px', 0)) if overflow else 0
                    ov_ratio = float(overflow.get('overflow_ratio', 0)) if overflow else 0.0
                    # 局部溢出：正文/列表容器内容高超过容器高（如套件 .page-body 586 vs 544），
                    # 顶层容器 absolute 定位不贡献 scrollHeight，只靠子元素 overflows 可感知。
                    local_items = (overflow or {}).get('overflows') or []
                    local_ov_px = max(
                        [int(it.get('item_h', 0)) - int(it.get('box_h', 0)) for it in local_items] or [0]
                    )
                    # 页脚遮挡：正文/目录列表区（absolute 定位）内容底边越过页脚顶边 → 覆盖页尾
                    # （套件内容页 .page-body / 目录页 .items 都有此问题，顶层 overflow 测不到）。
                    zone = (overflow or {}).get('zone_overlap') or {}
                    zone_ov_px = int(zone.get('overlap_px', 0)) if isinstance(zone, dict) else 0
                    zone_cls = zone.get('zone_cls', '') if isinstance(zone, dict) else ''
                    significant_overflow = overflow is not None and (
                        (ov_px > 0 and (ov_px > 12 or ov_ratio > 0.02))
                        or local_ov_px > 12
                        or zone_ov_px > 12
                    )
                    if significant_overflow:
                        ov_pct = round(ov_ratio * 100, 1)
                        logger.info(
                            f'📏 内容溢出 (slide {page_number}, attempt {attempt + 1}): '
                            f'顶层 {ov_px}px / 局部 {local_ov_px}px / 盖页脚 {zone_ov_px}px'
                        )
                        # 把溢出摘要反馈给模型，让其主动减负；仅有重试次数才退回重生成
                        detail_items = overflow.get('overflows') or []
                        detail_text = ''
                        reason_parts = []
                        if zone_ov_px > 12:
                            reason_parts.append(
                                f"正文/目录区（{zone_cls[:30]}）内容底边超出页脚 {zone_ov_px}px，会盖住页脚——请优化布局密度（缩字号 1 级/收紧行距/转横向排列），使正文区不越过页脚"
                            )
                        elif ov_px > 0:
                            reason_parts.append(f"主内容区总高度超出 1280×720 可用空间 {ov_px}px，底部内容会被裁切看不到——请优化布局密度")
                        elif local_ov_px > 12:
                            reason_parts.append(
                                f"某个块/卡片内容高超出其容器 {local_ov_px}px，文字超出块底——"
                                "**不要减少内容**：块改用 `min-height`/不写死 `height` 让其自适应内容高度；"
                                "或缩小字号 1 级、收紧行距、增加列数/转横向堆叠，让同样信息量落在更紧凑空间"
                            )
                        if detail_items:
                            parts = [f"{it.get('tag')}#{(it.get('cls') or '')[:30]}(子内容高{it.get('item_h')}px vs 容器高{it.get('box_h')}px)" for it in detail_items[:5]]
                            reason_parts.append('超出元素示例：' + '；'.join(parts))
                        detail_text = '\n    ' + '\n    '.join(reason_parts)
                        if attempt < max_retries - 1:
                            logger.info(f'🔄 内容溢出，重新生成 slide {page_number}...')
                            await notify_retry_progress(
                                page_number=page_number, total_pages=total_pages,
                                attempt=attempt + 2, max_retries=max_retries,
                                stage="overflow_retry",
                                detail=f"第 {page_number} 页内容溢出（顶层 {ov_px}px/局部 {local_ov_px}px/盖页脚 {zone_ov_px}px），重试（{attempt + 2}/{max_retries}）",
                            )
                            context = context + (
                                f'\n\n    **上一轮内容区域溢出（顶层 {ov_px}px/局部 {local_ov_px}px/盖页脚 {zone_ov_px}px），请修正：**\n'
                                f'- **不要减少内容、不要加 overflow:hidden 裁切**；通过优化布局密度让已有信息量落进可用空间。\n'
                                f'- 优化手段（按优先级）：块用 `min-height` 而非固定 `height` 让其自适应内容；缩字号 1 级 / 收紧行距 0.05~0.1；'
                                f'增加列数或转横向排列；卡片堆叠用 flex+gap 自分配空间；左右空时收缩空侧列宽。\n'
                                f'{detail_text}\n    '
                            )
                            continue
                        else:
                            logger.warning(f'⚠️ 内容溢出 {max(ov_px, local_ov_px, zone_ov_px)}px 但已用尽重试次数，交付当前 slide {page_number}（靠防溢出 CSS 兜底）')
                    elif ov_px > 0 or local_ov_px > 0 or zone_ov_px > 0:
                        logger.info(f'📏 轻微溢出 (slide {page_number}): 顶层 {ov_px}px/局部 {local_ov_px}px/盖页脚 {zone_ov_px}px，在阈值内，不重生成')
                    # 7. 横向溢出检测（内容超出 1280px 宽度）
                    ovx_px = int(overflow.get('overflow_x_px', 0)) if overflow else 0
                    ovx_ratio = float(overflow.get('overflow_x_ratio', 0)) if overflow else 0.0
                    significant_x_overflow = overflow is not None and ovx_px > 0 and (ovx_px > 12 or ovx_ratio > 0.02)
                    if significant_x_overflow:
                        ovx_pct = round(ovx_ratio * 100, 1)
                        logger.info(f'📏 横向溢出 (slide {page_number}, attempt {attempt + 1}): 超出 {ovx_px}px ({ovx_pct}%)')
                        x_detail_items = overflow.get('overflows_x') or []
                        x_detail_text = ''
                        if x_detail_items:
                            parts = [f"{it.get('tag')}#{(it.get('cls') or '')[:30]}(子内容宽{it.get('item_w')}px vs 容器宽{it.get('box_w')}px)" for it in x_detail_items[:5]]
                            x_detail_text = '\n    超出元素示例：' + '；'.join(parts)
                        if attempt < max_retries - 1:
                            logger.info(f'🔄 横向溢出，重新生成 slide {page_number}...')
                            await notify_retry_progress(
                                page_number=page_number, total_pages=total_pages,
                                attempt=attempt + 2, max_retries=max_retries,
                                stage="overflow_retry",
                                detail=f"第 {page_number} 页横向溢出 {ovx_px}px（{ovx_pct}%），重试（{attempt + 2}/{max_retries}）",
                            )
                            context = context + (
                                f'\n\n    **上一轮内容横向超出可见范围 {ovx_px}px（约 {ovx_pct}%），请修正：**\n    '
                                f'- 主内容区宽度超出 1280px 可用空间，右侧内容会被裁切看不到。\n    '
                                f'- 请收紧水平布局：减少单项宽度、缩小字体、减少列数、检查 flex/grid 是否正确包裹、用 max-width 而非固定 width。\n    '
                                f'{x_detail_text}\n    '
                            )
                            continue
                        else:
                            logger.warning(f'⚠️ 横向溢出 {ovx_px}px 但已用尽重试次数，交付当前 slide {page_number}')
                    elif ovx_px > 0:
                        logger.info(f'📏 轻微横向溢出 {ovx_px}px (slide {page_number})，在阈值内，不重生成')
                    return await self._apply_auto_layout_repair(html_content, slide_data, page_number, total_pages)
                else:
                    if validation_result['missing_elements']:
                        logger.warning(f"Missing elements (warnings only): {', '.join(validation_result['missing_elements'])}")
                    if validation_result['errors']:
                        logger.error(f"Validation errors: {'; '.join(validation_result['errors'])}")
                    if validation_result['errors']:
                        logger.info(f'🔧 Attempting automatic parser fix for slide {page_number}')
                        parser_fixed_html = self._auto_fix_html_with_parser(html_content)
                        if parser_fixed_html != html_content:
                            logger.info(f'✅ Successfully fixed HTML with parser for slide {page_number}, returning fixed result')
                            return await self._apply_auto_layout_repair(parser_fixed_html, slide_data, page_number, total_pages)
                        else:
                            logger.info(f'🔧 Parser did not change HTML for slide {page_number}')
                        if attempt < max_retries - 1:
                            logger.info(f'🔄 HTML has errors after parser fix, retrying fresh generation for slide {page_number}...')
                            await notify_retry_progress(
                                page_number=page_number, total_pages=total_pages,
                                attempt=attempt + 2, max_retries=max_retries,
                                stage="structure_retry",
                                detail=f"第 {page_number} 页 HTML 结构不完整，重试（{attempt + 2}/{max_retries}）",
                            )
                            continue
                        else:
                            logger.warning(f'❌ All generation and parser fix attempts failed, using fallback for slide {page_number}')
                            fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
                            return await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)
                    else:
                        logger.info(f'✅ HTML is valid with only missing element warnings for slide {page_number}')
                        return await self._apply_auto_layout_repair(html_content, slide_data, page_number, total_pages)
            except Exception as e:
                error_msg = str(e)
                logger.error(f'Error in HTML generation attempt {attempt + 1} for slide {page_number}: {error_msg}')
                if 'Expecting value' in error_msg or 'JSON' in error_msg:
                    logger.warning(f'JSON parsing error detected, this might be due to malformed AI response')
                    if attempt < max_retries - 1:
                        logger.info('Waiting 1 second before retry due to JSON parsing error...')
                        await asyncio.sleep(1)
                        continue
                if attempt == max_retries - 1:
                    logger.error(f'All attempts failed with errors, using fallback for slide {page_number}')
                    fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
                    return await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)
                continue
        fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
        return await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)

    def _fix_incomplete_html(self, html_content: str, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """Try to fix incomplete HTML by adding missing elements"""
        import re
        html_content = html_content.strip()
        if len(html_content) < 50:
            return self._generate_fallback_slide_html(slide_data, page_number, total_pages)
        if not html_content.lower().startswith('<!doctype'):
            html_content = '<!DOCTYPE html>\n' + html_content
        if not re.search('<html[^>]*>', html_content, re.IGNORECASE):
            html_content = html_content.replace('<!DOCTYPE html>', '<!DOCTYPE html>\n<html lang="zh-CN">')
        if not re.search('</html>', html_content, re.IGNORECASE):
            html_content += '\n</html>'
        if not re.search('<head[^>]*>', html_content, re.IGNORECASE):
            head_section = '<head>\n        <meta charset="UTF-8">\n        <meta name="viewport" content="width=device-width, initial-scale=1.0">\n        <title>{}</title>\n    </head>'.format(slide_data.get('title', f'第{page_number}页'))
            html_content = re.sub('(<html[^>]*>)', '\\1\\n' + head_section, html_content, flags=re.IGNORECASE)
        elif not re.search('</head>', html_content, re.IGNORECASE):
            head_match = re.search('<head[^>]*>', html_content, re.IGNORECASE)
            if head_match:
                head_start = head_match.end()
                if not re.search('<meta[^>]*charset[^>]*>', html_content, re.IGNORECASE):
                    charset_meta = '\n    <meta charset="UTF-8">'
                    html_content = html_content[:head_start] + charset_meta + html_content[head_start:]
                if '<body' in html_content.lower():
                    html_content = re.sub('(<body[^>]*>)', '</head>\\n\\1', html_content, flags=re.IGNORECASE)
                elif '</title>' in html_content.lower():
                    html_content = re.sub('(</title>)', '\\1\\n</head>', html_content, flags=re.IGNORECASE)
                else:
                    html_content = re.sub('(<html[^>]*>.*?<head[^>]*>.*?)(<body|$)', '\\1\\n</head>\\n\\2', html_content, flags=re.IGNORECASE | re.DOTALL)
        if not re.search('<body[^>]*>', html_content, re.IGNORECASE):
            if '</head>' in html_content.lower():
                html_content = re.sub('(</head>)', '\\1\\n<body>', html_content, flags=re.IGNORECASE)
            else:
                html_content = re.sub('(<html[^>]*>)', '\\1\\n<body>', html_content, flags=re.IGNORECASE)
        if not re.search('</body>', html_content, re.IGNORECASE):
            html_content = re.sub('(</html>)', '</body>\\n\\1', html_content, flags=re.IGNORECASE)
        return html_content
