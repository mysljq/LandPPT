"""
Global Template Suite Service — manage a shared, cross-project library of
template suites (cover / transition / content header-footer).

A suite in the library is a self-contained dict:
  {cover, transition, header_footer, design_tokens,
   template_id, template_hash, template_name, generated_at}
generated from a master template via one LLM call (reusing TemplateSuiteService.
_generate_suite_payload), then persisted to the global_template_suites table.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ...core.config import ai_config
from ...database.database import AsyncSessionLocal
from ...database.service import DatabaseService
from .template_suite_service import TemplateSuiteService

logger = logging.getLogger(__name__)


class GlobalTemplateSuiteService:
    """Own global template-suite CRUD and generation."""

    def __init__(self, service: Optional[Any] = None, user_id: Optional[int] = None):
        self._service = service  # optional EnhancedPPTService host for delegation
        self.user_id = user_id  # per-user LLM config lookup when built standalone

    def __getattr__(self, name: str):
        if self._service is not None:
            return getattr(self._service, name)
        raise AttributeError(name)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _db(self) -> DatabaseService:
        session = AsyncSessionLocal()
        return DatabaseService(session)

    @staticmethod
    def _suite_to_dict(suite) -> Dict[str, Any]:
        return {
            "id": suite.id,
            "suite_name": suite.suite_name,
            "description": suite.description or "",
            "cover": suite.cover,
            "transition": suite.transition,
            "catalog": suite.catalog or "",
            "ending": suite.ending or "",
            "header_footer": suite.header_footer,
            "design_tokens": suite.design_tokens or "",
            "template_id": suite.template_id,
            "template_hash": suite.template_hash,
            "template_name": suite.template_name,
            "tags": suite.tags or [],
            "is_active": suite.is_active,
            "usage_count": suite.usage_count or 0,
            "created_at": suite.created_at,
            "updated_at": suite.updated_at,
        }

    async def get_suite_payload(self, suite_id: int) -> Optional[Dict[str, Any]]:
        """Return the usable suite payload (cover/transition/header_footer/design_tokens...)
        for slide generation, or None if missing."""
        db = await self._db()
        try:
            suite = await db.get_global_template_suite_by_id(suite_id)
            if not suite or not suite.is_active:
                return None
            return {
                "cover": suite.cover,
                "transition": suite.transition,
                "catalog": suite.catalog or "",
                "ending": suite.ending or "",
                "header_footer": suite.header_footer,
                "design_tokens": suite.design_tokens or "",
                "template_hash": suite.template_hash,
                "template_id": suite.template_id,
                "template_name": suite.template_name or suite.suite_name,
                "generated_at": suite.updated_at or suite.created_at,
            }
        finally:
            await db.session.close()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_suite(self, suite_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a global template suite."""
        required = ["suite_name", "cover", "transition", "header_footer"]
        for field in required:
            if not suite_data.get(field):
                raise ValueError(f"缺少必需字段: {field}")
        db = await self._db()
        try:
            suite = await db.create_global_template_suite(suite_data)
            return self._suite_to_dict(suite)
        finally:
            await db.session.close()

    async def get_suite(self, suite_id: int) -> Optional[Dict[str, Any]]:
        db = await self._db()
        try:
            suite = await db.get_global_template_suite_by_id(suite_id)
            return self._suite_to_dict(suite) if suite else None
        finally:
            await db.session.close()

    async def list_suites(
        self,
        page: int = 1,
        page_size: int = 6,
        search: Optional[str] = None,
        template_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        db = await self._db()
        try:
            offset = (page - 1) * page_size
            suites, total = await db.list_global_template_suites_paginated(
                active_only=True, offset=offset, limit=page_size,
                search=search, template_id=template_id,
            )
            items = [self._suite_to_dict(s) for s in suites]
            total_pages = (total + page_size - 1) // page_size if total else 0
            return {
                "suites": items,
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_count": total,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                },
            }
        finally:
            await db.session.close()

    async def list_all_suites(self) -> List[Dict[str, Any]]:
        db = await self._db()
        try:
            suites = await db.list_all_global_template_suites(active_only=True)
            return [self._suite_to_dict(s) for s in suites]
        finally:
            await db.session.close()

    async def update_suite(self, suite_id: int, update_data: Dict[str, Any]) -> bool:
        db = await self._db()
        try:
            return await db.update_global_template_suite(suite_id, update_data)
        finally:
            await db.session.close()

    async def delete_suite(self, suite_id: int) -> bool:
        db = await self._db()
        try:
            return await db.delete_global_template_suite(suite_id)
        finally:
            await db.session.close()

    async def increment_usage(self, suite_id: int) -> bool:
        db = await self._db()
        try:
            return await db.increment_global_template_suite_usage(suite_id)
        finally:
            await db.session.close()

    # ------------------------------------------------------------------
    # Generation from a master template
    # ------------------------------------------------------------------

    async def _get_template_by_id(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Load a global master template dict (html_template + identity)."""
        if self._service is not None and hasattr(self._service, "global_template_service"):
            try:
                return await self._service.global_template_service.get_template_by_id(template_id)
            except Exception as exc:
                logger.warning("Failed to load template %s via service: %s", template_id, exc)
        db = await self._db()
        try:
            tpl = await db.get_global_master_template_by_id(template_id)
            if not tpl:
                return None
            return {
                "id": tpl.id,
                "template_name": tpl.template_name,
                "html_template": tpl.html_template,
                "description": tpl.description or "",
                "tags": tpl.tags or [],
            }
        finally:
            await db.session.close()

    def _build_host(self):
        """Build a TemplateSuiteService host that resolves _text_completion_for_role.

        When constructed standalone (no _service), build an EnhancedPPTService host
        carrying the user_id so generation resolves the user's configured model
        service (系统配置) instead of falling back to the global env config.
        """
        from .template_suite_service import TemplateSuiteService as _TSS
        host = _TSS(self._service)
        if self._service is None:
            from ...services.enhanced_ppt_service import EnhancedPPTService
            host = _TSS(EnhancedPPTService(user_id=self.user_id))
        return host

    @staticmethod
    def _decorate_suite(suite: Dict[str, Any], template: Dict[str, Any], template_id: int) -> Dict[str, Any]:
        """Attach library metadata (name/description/tags) to a generated suite."""
        suite["suite_name"] = template.get("template_name") or f"套件-模板{template_id}"
        suite["description"] = template.get("description") or ""
        suite["tags"] = template.get("tags") or []
        return suite

    async def generate_suite_from_template(
        self,
        template_id: int,
        creativity: int = 0,
    ) -> Dict[str, Any]:
        """Generate a suite payload from a master template (no persistence).

        Returns the suite dict the caller may preview then optionally save.
        """
        template = await self._get_template_by_id(template_id)
        if not template:
            raise ValueError(f"模板 {template_id} 不存在")
        logger.info(
            "开始基于模板生成套件：template_id=%s，模板=%s，创意度=%s",
            template_id,
            template.get("template_name"),
            creativity,
        )
        host = self._build_host()
        try:
            suite = await host._generate_suite_payload(
                template,
                creativity=creativity,
                reference_outline=False,
                project=None,
            )
        except Exception as exc:
            logger.error("基于模板生成套件失败（template_id=%s）: %s", template_id, exc)
            raise
        self._decorate_suite(suite, template, template_id)
        logger.info(
            "基于模板生成套件完成（template_id=%s，模板=%s）",
            template_id,
            template.get("template_name"),
        )
        return suite

    async def stream_generate_suite_from_template(
        self,
        template_id: int,
        creativity: int = 0,
    ):
        """Stream suite-generation events (status → complete / error) so the
        frontend can show live progress instead of a silent blocking request."""
        template = await self._get_template_by_id(template_id)
        if not template:
            logger.error("基于模板生成套件失败：模板 %s 不存在", template_id)
            yield {"type": "error", "message": f"模板 {template_id} 不存在"}
            return

        logger.info(
            "开始基于模板生成套件（流式）：template_id=%s，模板=%s，创意度=%s",
            template_id,
            template.get("template_name"),
            creativity,
        )
        yield {
            "type": "status",
            "message": f"已加载模板「{template.get('template_name')}」，正在解析母版布局并构建提示词...",
        }
        host = self._build_host()
        try:
            yield {
                "type": "status",
                "message": "正在调用 AI 生成套件（封面/过渡/目录/结尾/内容页头页脚），预计 30-60 秒，请稍候...",
            }
            suite = await host._generate_suite_payload(
                template,
                creativity=creativity,
                reference_outline=False,
                project=None,
            )
            self._decorate_suite(suite, template, template_id)
            logger.info(
                "基于模板生成套件完成（流式）：template_id=%s，模板=%s",
                template_id,
                template.get("template_name"),
            )
            yield {"type": "complete", "message": "套件生成完成！", "suite": suite}
        except Exception as exc:
            logger.error("基于模板生成套件失败（流式，template_id=%s）: %s", template_id, exc)
            yield {"type": "error", "message": f"套件生成失败：{exc}"}

    async def generate_and_save_suite(
        self,
        template_id: int,
        creativity: int = 0,
        suite_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a suite from a template and immediately persist to the library."""
        suite = await self.generate_suite_from_template(template_id, creativity=creativity)
        if suite_name:
            suite["suite_name"] = suite_name
        db = await self._db()
        try:
            row = await db.create_global_template_suite(suite)
            return self._suite_to_dict(row)
        finally:
            await db.session.close()

    async def preview_suite(self, suite_id: int) -> Dict[str, str]:
        """Preview pages for a stored suite (cover/transition/content)."""
        payload = await self.get_suite_payload(suite_id)
        if not payload:
            raise ValueError("套件不存在")
        host = TemplateSuiteService(self._service) if self._service is not None else None
        if host is None:
            from .template_suite_service import TemplateSuiteService as _TSS
            host = _TSS(self._service)
        return host.build_preview_html(payload)
