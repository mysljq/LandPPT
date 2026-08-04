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
from .slide_html_inspection_service import SlideHtmlInspectionService
from .slide_html_recovery_service import SlideHtmlRecoveryService
from .aesthetic_preflight_checker import AestheticPreFlightChecker

if TYPE_CHECKING:
    from .slide_html_service import SlideHtmlService


class SlideHtmlValidationService:
    """Facade over extracted subservices for SlideHtmlValidationService."""

    def __init__(self, service: "SlideHtmlService"):
        self._service = service
        self._inspection_service = SlideHtmlInspectionService(self)
        self._recovery_service = SlideHtmlRecoveryService(self)
        self._aesthetic_checker = AestheticPreFlightChecker()

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _extract_style_info(self, html_content: str) -> List[str]:
        return self._inspection_service._extract_style_info(html_content)

    def _validate_html_completeness(self, html_content: str) -> Dict[str, Any]:
        return self._inspection_service._validate_html_completeness(html_content)

    def _check_html_well_formedness(self, html_content: str, validation_result: Dict[str, Any]) -> None:
        return self._inspection_service._check_html_well_formedness(html_content, validation_result)

    def _auto_fix_html_with_parser(self, html_content: str) -> str:
        return self._inspection_service._auto_fix_html_with_parser(html_content)

    def _basic_html_syntax_check(self, html_content: str, validation_result: Dict[str, Any]) -> None:
        return self._inspection_service._basic_html_syntax_check(html_content, validation_result)

    def _aesthetic_preflight_check(self, html_content: str, header_lock=None, footer_lock=None,
                                    slide_data=None, page_number=None, total_pages=None,
                                    excluded_colors=None):
        """审美维度预检（机械正则），返回 (hard_fails, warnings)。

        header_lock 可选：传入宪法 HEADER_LOCK 令牌字典时一并做页头跨页一致性校验，
        非内容页（封面/尾页/目录/过渡）自动豁免不参与页头守恒比对。
        footer_lock 可选：传入宪法 FOOTER_LOCK 令牌字典时一并做页脚页码一致性校验，
        非内容页自动豁免。
        excluded_colors 可选：套件页头页脚等锁定区的既定配色集合，纯黑纯白/多 accent
        检查会跳过这些颜色，避免误判套件自身设计为 LLM 套路指纹。
        """
        return self._aesthetic_checker.check(
            html_content, header_lock=header_lock, footer_lock=footer_lock,
            slide_data=slide_data, page_number=page_number, total_pages=total_pages,
            excluded_colors=excluded_colors)

    def _parse_header_lock(self, constitution: str):
        """从宪法文本解析 ===HEADER_LOCK=== 令牌字典。"""
        return self._aesthetic_checker.parse_header_lock(constitution)

    def _parse_footer_lock(self, constitution: str):
        """从宪法文本解析 ===FOOTER_LOCK=== 令牌字典。"""
        return self._aesthetic_checker.parse_footer_lock(constitution)

    async def _measure_overflow(self, html_content: str, page_number: int):
        """用 Playwright 测量主内容区是否溢出固定画布。失败/关闭则返回 None。"""
        return await self._recovery_service._measure_overflow(html_content, page_number)

    async def _generate_html_with_retry(self, context: str, system_prompt: str, slide_data: Dict[str, Any], page_number: int, total_pages: int, max_retries: int=3) -> str:
        return await self._recovery_service._generate_html_with_retry(context, system_prompt, slide_data, page_number, total_pages, max_retries)

    def _fix_incomplete_html(self, html_content: str, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        return self._recovery_service._fix_incomplete_html(html_content, slide_data, page_number, total_pages)
