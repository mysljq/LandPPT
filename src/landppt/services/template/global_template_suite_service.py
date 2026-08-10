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

import asyncio
import base64
import logging
import re as _re
import time
from typing import Any, Dict, List, Optional

from ...ai.base import AIMessage, ImageContent, MessageRole, TextContent
from ...core.config import ai_config
from ...database.database import AsyncSessionLocal
from ...database.service import DatabaseService
from .template_suite_service import TemplateSuiteService

logger = logging.getLogger(__name__)


# 视觉读图生成套件的类型元信息：类型 -> (中文标签, 生成规格描述)
_SUITE_IMAGE_PARTS: Dict[str, tuple] = {
    "cover": (
        "封面页",
        "一个完整的封面 HTML（1280×720，overflow:hidden），预留槽位 {{cover_title}}（主标题）、"
        "{{cover_subtitle}}（副标题）、{{cover_extra}}（可选补充文案）",
    ),
    "transition": (
        "过渡页",
        "一个完整的章节过渡页 HTML（1280×720），预留槽位 {{transition_title}}（章节标题）、"
        "{{transition_subtitle}}（简短引导语）、{{transition_extra}}（可选补充）",
    ),
    "catalog": (
        "目录页",
        "一个完整的目录/大纲页 HTML（1280×720），预留槽位 {{catalog_title}}（页面标题，如“目录”）、"
        "{{catalog_subtitle}}（副标题）、{{catalog_extra}}（可选补充）；目录条目区要自带设计示例"
        "（编号 01/02… + 章节名 + 分隔线/双栏排版），不要预留 {{catalog_items}} 槽位",
    ),
    "ending": (
        "结尾页",
        "一个完整的结尾/致谢页 HTML（1280×720），预留槽位 {{ending_title}}（主标题，如“感谢聆听”）、"
        "{{ending_subtitle}}（副标题）、{{ending_extra}}（可选补充）",
    ),
    "header_footer": (
        "内容页",
        "内容页的自包含页头页脚片段（不是完整页面，但包含内容页全部视觉骨架）：页头/页脚/背景装饰，"
        "预留槽位 {{page_title}}（页头标题）、{{current_page_number}}（当前页码）、"
        "{{total_page_count}}（总页数）、{{page_content}}（正文占位容器）",
    ),
}


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
            # shield：即使请求任务被取消（客户端断开/SSE 结束），读取也能完成。
            suite = await asyncio.shield(db.get_global_template_suite_by_id(suite_id))
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
            # shield close：连接归还到池，避免任务取消时 await close() 被中断导致连接泄漏。
            try:
                await asyncio.shield(db.session.close())
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

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

    def _ensure_host(self):
        """Build (and cache) the TemplateSuiteService host for LLM delegation."""
        if getattr(self, "_cached_host", None) is None:
            self._cached_host = self._build_host()
        return self._cached_host

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

    # ------------------------------------------------------------------
    # 基于 AI 读图生成套件（多模态）
    # ------------------------------------------------------------------

    async def stream_generate_suite_from_images(
        self,
        images: Dict[str, bytes],
        creativity: int = 5,
        user_id: Optional[int] = None,
        extract_images: bool = True,
    ):
        """基于上传的页面截图生成套件（多模态读图）。

        images: {"cover": bytes, "transition": bytes, "catalog": bytes,
                 "ending": bytes, "header_footer": bytes} —— 部分键可缺省。
        有截图的类型用多模态模型按截图生成；缺失类型用大模型基于其它页面设计补全。
        extract_images=True 时：识别截图中的图片/图标区域并裁剪，直接在生成的 HTML
        中复用（而非让模型凭空编或另找图片）。
        逐个 yield status / complete / error 事件。
        """
        parts = {k: v for k, v in images.items() if v}
        if not parts:
            yield {"type": "error", "message": "请至少上传一张页面截图"}
            return

        try:
            from ..db_config_service import get_vision_provider
            vision_provider, vs = await get_vision_provider(user_id)
            vision_model = vs["model"]
            vision_temperature = vs.get("temperature")
            vision_top_p = vs.get("top_p")
        except Exception as exc:
            logger.error("获取多模态模型失败: %s", exc)
            yield {"type": "error", "message": str(exc)}
            return

        suite: Dict[str, str] = {}
        generated_html: Dict[str, str] = {}

        # 1) 有截图的类型 → 视觉生成
        vision_available = True
        for key, img_bytes in parts.items():
            label = _SUITE_IMAGE_PARTS.get(key, (key, ""))[0]
            yield {"type": "status", "message": f"正在识别{label}截图并生成..."}
            try:
                html = await self._generate_part_from_image(
                    vision_provider, vision_model, key, img_bytes, creativity,
                    extract_images=extract_images, temperature=vision_temperature, top_p=vision_top_p,
                )
                if not html:
                    raise ValueError(f"{label}生成结果为空")
                suite[key] = html
                generated_html[key] = html
            except Exception as exc:
                # 视觉生成失败不回退整个套件：该类型交由缺失补全逻辑（用其它页面设计生成）
                logger.warning("视觉生成 %s 失败（%s），改用其它页面设计补全该类型", key, exc)
                # 服务端/端点不可用（503/429/5xx/unavailable 等）：后续页调用大概率同样失败，
                # 立即停止视觉处理，剩余页面全部交给文本补全，避免逐页重复重试拖慢整体。
                if self._is_vision_server_error(exc):
                    vision_available = False
                    yield {
                        "type": "status",
                        "message": f"多模态模型暂时不可用（{exc}），后续页面将改用其它页面设计补全...",
                    }
                    break
                yield {
                    "type": "status",
                    "message": f"{label}截图识别失败，将改用其它页面设计补全...",
                }
            # 类型之间稍作停顿，降低连续请求触发限流概率
            await asyncio.sleep(0.4)

        if not vision_available:
            logger.warning("多模态模型不可用，已跳过剩余视觉生成，全部改用文本补全")

        # 2) 缺失的类型 → 大模型基于已生成部分补全
        missing = [k for k in _SUITE_IMAGE_PARTS if k not in suite]
        if missing:
            design_reference = self._build_design_reference(generated_html)
            for key in missing:
                label = _SUITE_IMAGE_PARTS[key][0]
                yield {"type": "status", "message": f"未上传{label}截图，正在基于其它页面设计补全..."}
                try:
                    html = await self._generate_missing_part(key, design_reference, creativity)
                    if not html:
                        raise ValueError(f"{label}补全结果为空")
                    suite[key] = html
                except Exception as exc:
                    logger.error("补全 %s 失败: %s", key, exc)
                    yield {"type": "error", "message": f"{label}补全失败：{exc}"}
                    return

        # 3) 组装（独立套件，无模板来源）
        try:
            final = self._assemble_image_suite(suite)
        except Exception as exc:
            logger.error("套件组装失败: %s", exc)
            yield {"type": "error", "message": f"套件组装失败：{exc}"}
            return
        if not final.get("cover") or not final.get("transition") or not final.get("header_footer"):
            yield {"type": "error", "message": "套件缺少必需部分（封面/过渡页/内容页页头页脚），请重试"}
            return

        logger.info("基于 AI 读图生成套件完成：parts=%s", list(suite.keys()))
        yield {"type": "complete", "message": "基于截图生成套件完成！", "suite": final}

    async def _call_vision_with_retry(
        self, vision_provider, vision_model: str, messages: list, *, max_tokens: int = 12000,
        temperature: Optional[float] = None, top_p: Optional[float] = None, attempts: int = 3,
    ):
        """调用视觉模型，对瞬时错误（503/429/5xx/网络）重试，避免一次失败中断整页。"""
        last_exc = None
        for attempt in range(attempts):
            try:
                kwargs: Dict[str, Any] = {"max_output_tokens": max_tokens}
                if temperature is not None:
                    kwargs["temperature"] = temperature
                if top_p is not None:
                    kwargs["top_p"] = top_p
                return await vision_provider.chat_completion(
                    messages=messages, model=vision_model, **kwargs
                )
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                # 认证/参数/模型不存在等非瞬时错误不重试
                if any(k in msg for k in ("401", "400", "invalid", "not found", "认证", "api key", "api_key", "unknown model", "不存在")):
                    raise exc
                if attempt < attempts - 1:
                    backoff = 1.0 * (attempt + 1)
                    logger.warning("视觉调用第 %s 次失败（%s），%.1fs 后重试", attempt + 1, exc, backoff)
                    await asyncio.sleep(backoff)
        raise last_exc

    async def _generate_part_from_image(
        self,
        vision_provider,
        vision_model: str,
        part: str,
        img_bytes: bytes,
        creativity: int,
        extract_images: bool = True,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> str:
        """用多模态模型读取截图，生成对应套件部分的 HTML。

        extract_images=True 时：先用视觉模型识别截图中的图片/图标区域，裁剪成 data URL，
        让生成结果直接用真实图片（`<img src="SUITE_ASSET:名称">` 占位，随后替换为图片）。
        """
        # 1) 识别并裁剪截图中的图片/图标区域（可复用真实图片，而非凭空编造）
        crops: Dict[str, Dict] = {}
        asset_names: List[str] = []
        if extract_images:
            try:
                raw_regions = await self._detect_image_regions(
                    vision_provider, vision_model, img_bytes,
                    temperature=temperature, top_p=top_p,
                )
                regions = self._normalize_regions(raw_regions)
                crops = self._crop_image_regions(img_bytes, regions)
                asset_names = list(crops.keys())
                if crops:
                    logger.info(
                        "从%s截图提取到 %s 张图片区域：%s", part, len(crops), asset_names
                    )
            except Exception as exc:
                logger.warning("截图图片提取失败（%s），继续生成: %s", part, exc)
                crops = {}

        # 2) 生成该类型 HTML（提示模型对识别出的图片用 SUITE_ASSET 占位）
        prompt = self._build_image_part_prompt(part, creativity, crops)
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime = self._guess_image_mime(img_bytes)
        messages = [
            AIMessage(
                role=MessageRole.SYSTEM,
                content="You are an expert PPT template designer. Replicate the design language from the screenshot into a styled slide template. Output only the HTML.",
            ),
            AIMessage(
                role=MessageRole.USER,
                content=[
                    TextContent(text=prompt),
                    ImageContent(image_url={"url": f"data:{mime};base64,{b64}"}),
                ],
            ),
        ]
        # 检测与生成之间稍作停顿，降低连续请求触发限流概率
        if crops:
            await asyncio.sleep(0.3)
        response = await self._call_vision_with_retry(
            vision_provider, vision_model, messages, max_tokens=12000,
            temperature=temperature, top_p=top_p,
        )
        raw = self._strip_code_fence((response.content or "").strip())
        html = self._ensure_standalone_html(raw) if part != "header_footer" else raw

        # 3) 把 SUITE_ASSET:名称 占位替换为真实 data URL
        if crops:
            html = self._inject_assets_into_html(html, crops)
        return html

    async def _detect_image_regions(
        self, vision_provider, vision_model: str, img_bytes: bytes,
        temperature: Optional[float] = None, top_p: Optional[float] = None,
    ) -> list:
        """用视觉模型识别截图中的图片/图标区域，返回原始 JSON 解析结果。"""
        prompt = (
            "分析这张 PPT 页面截图，识别其中属于「图片 / 图标 / 插画 / 照片 / 装饰图形」的区域"
            "（即需要作为真实图片保留的部分，不包括纯文字与纯背景）。\n"
            "对每个区域给一个简短英文名（如 logo、photo_1、icon_1、chart_1），并输出其边界框。\n"
            "只输出一个 JSON 数组，每个元素格式："
            '{"name": "英文名", "left": 0-1, "top": 0-1, "width": 0-1, "height": 0-1}，'
            "其中 left/top 是区域左上角相对整图的 0-1 小数，width/height 是相对整图的宽高比例。\n"
            "没有识别到图片区域则输出 []。只输出 JSON，不要任何解释。"
        )
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime = self._guess_image_mime(img_bytes)
        messages = [
            AIMessage(
                role=MessageRole.SYSTEM,
                content="You are an image analysis assistant. Output only JSON.",
            ),
            AIMessage(
                role=MessageRole.USER,
                content=[
                    TextContent(text=prompt),
                    ImageContent(image_url={"url": f"data:{mime};base64,{b64}"}),
                ],
            ),
        ]
        response = await self._call_vision_with_retry(
            vision_provider, vision_model, messages, max_tokens=2000,
            temperature=temperature, top_p=top_p,
        )
        return self._parse_region_list((response.content or "").strip())

    @staticmethod
    def _parse_region_list(raw: str) -> list:
        """从视觉模型响应中解析图片区域列表（兼容 [] / [{...}] / {"regions": [...]}）。"""
        if not (raw or "").strip():
            return []
        try:
            from summeryanyfile.core.json_parser import JSONParser
        except Exception:
            JSONParser = None
        candidates = [raw]
        if JSONParser is not None:
            candidates.extend(JSONParser._extract_fenced_code_blocks(raw))
            cleaned = JSONParser._clean_response(raw)
            if cleaned:
                candidates.append(cleaned)
            candidates.extend(JSONParser._extract_json_candidates(raw))
        for cand in candidates:
            cand = cand.strip()
            if not cand:
                continue
            try:
                if JSONParser is not None:
                    parsed = JSONParser._loads_best_effort(cand)
                else:
                    import json as _json
                    parsed = _json.loads(cand)
            except Exception:
                continue
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                for key in ("regions", "images", "items", "boxes"):
                    v = parsed.get(key)
                    if isinstance(v, list):
                        return v
                if "name" in parsed:
                    return [parsed]
        return []

    @staticmethod
    def _normalize_regions(raw_list: list) -> list:
        """归一化图片区域：坐标为 0-1 小数，裁剪非法值，限制数量。"""
        regions = []
        for r in raw_list or []:
            if not isinstance(r, dict):
                continue
            try:
                name = str(r.get("name") or f"img_{len(regions) + 1}")[:40]
                left = float(r.get("left", r.get("x", 0)))
                top = float(r.get("top", r.get("y", 0)))
                width = float(r.get("width", r.get("w", 0)))
                height = float(r.get("height", r.get("h", 0)))
            except (TypeError, ValueError):
                continue
            if width <= 0 or height <= 0 or left < 0 or top < 0:
                continue
            regions.append(
                {
                    "name": name,
                    "left": min(1.0, left),
                    "top": min(1.0, top),
                    "width": min(1.0, width),
                    "height": min(1.0, height),
                }
            )
            if len(regions) >= 8:
                break
        return regions

    @staticmethod
    def _crop_image_regions(img_bytes: bytes, regions: list) -> Dict[str, Dict]:
        """把截图中的图片区域裁剪为 {name: {data_url, left, top, width, height}}。"""
        if not regions:
            return {}
        try:
            import io as _io

            from PIL import Image
        except ImportError:
            logger.warning("PIL 不可用，跳过图片提取")
            return {}
        try:
            img = Image.open(_io.BytesIO(img_bytes)).convert("RGBA")
            W, H = img.size
        except Exception as exc:
            logger.warning("截图打开失败，跳过图片提取: %s", exc)
            return {}
        crops: Dict[str, Dict] = {}
        for r in regions:
            left = int(r["left"] * W)
            top = int(r["top"] * H)
            right = int((r["left"] + r["width"]) * W)
            bottom = int((r["top"] + r["height"]) * H)
            left, right = max(0, min(left, W)), max(0, min(right, W))
            top, bottom = max(0, min(top, H)), max(0, min(bottom, H))
            if right - left < 4 or bottom - top < 4:
                continue
            box = img.crop((left, top, right, bottom))
            # 缩小过大图片，控制 base64 体积
            max_side = 400
            bw, bh = box.size
            scale = min(1.0, max_side / max(bw, bh))
            if scale < 1.0:
                box = box.resize(
                    (max(1, int(bw * scale)), max(1, int(bh * scale))), Image.LANCZOS
                )
            buf = _io.BytesIO()
            if box.mode in ("RGBA", "P", "LA"):
                box.save(buf, format="PNG")
                mime = "image/png"
            else:
                box = box.convert("RGB")
                box.save(buf, format="JPEG", quality=85)
                mime = "image/jpeg"
            data_url = f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
            crops[r["name"]] = {
                "data_url": data_url,
                "left": min(1.0, r["left"]),
                "top": min(1.0, r["top"]),
                "width": min(1.0, r["width"]),
                "height": min(1.0, r["height"]),
            }
        return crops

    @staticmethod
    def _build_asset_img_tag(name: str, meta: Dict) -> str:
        """按检测到的位置/尺寸生成图片标签（用 SUITE_ASSET 占位，稍后替换为 data URL）。"""
        left = meta["left"] * 100
        top = meta["top"] * 100
        width = meta["width"] * 100
        height = meta["height"] * 100
        return (
            f'<img src="SUITE_ASSET:{name}" '
            f'style="position:absolute; left:{left:.2f}%; top:{top:.2f}%; '
            f'width:{width:.2f}%; height:{height:.2f}%; object-fit:contain;">'
        )

    @classmethod
    def _inject_assets_into_html(cls, html: str, crops: Dict[str, Dict]) -> str:
        """把 HTML 中的 SUITE_ASSET:名称 占位替换为真实 data URL。

        模型漏掉的图片：若某张识别出的图片在生成结果中连占位都没有，则按检测到的
        位置/尺寸在 </body> 前补一个绝对定位的 <img>，保证截图里的图片/图标都进套件。
        """
        if not crops or not html:
            return html
        for name, meta in crops.items():
            html = html.replace(f"SUITE_ASSET:{name}", meta["data_url"])
            html = html.replace(f"ASSET:{name}", meta["data_url"])
        for name, meta in crops.items():
            if meta["data_url"] in html:
                continue
            tag = cls._build_asset_img_tag(name, meta).replace(
                f"SUITE_ASSET:{name}", meta["data_url"]
            )
            if "</body>" in html.lower():
                html = html.replace("</body>", tag + "</body>", 1)
            else:
                html += tag
        return html

    async def _generate_missing_part(
        self, part: str, design_reference: str, creativity: int
    ) -> str:
        """用大模型基于其它页面设计补全缺失类型。"""
        prompt = self._build_missing_part_prompt(part, design_reference, creativity)
        # 独立构建时（无 _service）需经 host 才能解析 _text_completion_for_role。
        host = self._ensure_host()
        last_exc = None
        for attempt in range(3):
            try:
                response = await host._text_completion_for_role(
                    "template", prompt=prompt, temperature=0.7, max_output_tokens=12000
                )
                break
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                if any(k in msg for k in ("401", "400", "invalid", "not found", "认证", "api key", "api_key", "不存在")):
                    raise exc
                if attempt < 2:
                    logger.warning("补全 %s 调用第 %s 次失败（%s），%.1fs 后重试", part, attempt + 1, exc, 1.0 * (attempt + 1))
                    await asyncio.sleep(1.0 * (attempt + 1))
        else:
            raise last_exc
        raw = self._strip_code_fence((response.content or "").strip())
        return self._ensure_standalone_html(raw) if part != "header_footer" else raw

    def _assemble_image_suite(self, parts: Dict[str, str]) -> Dict[str, str]:
        """把视觉/补全生成的部分组装成套件 dict（独立套件）。"""
        from .template_suite_service import TemplateSuiteService as _TSS

        tss = _TSS(self._service)
        header_footer = str(parts.get("header_footer") or "")
        try:
            header_footer = tss._ensure_header_footer_complete(header_footer, "", "")
        except Exception as exc:
            logger.warning("header_footer 自包含修复跳过: %s", exc)
            header_footer = str(parts.get("header_footer") or "")
        return {
            "cover": self._ensure_standalone_html(parts.get("cover", "")),
            "transition": self._ensure_standalone_html(parts.get("transition", "")),
            "catalog": self._ensure_standalone_html(parts.get("catalog", "")),
            "ending": self._ensure_standalone_html(parts.get("ending", "")),
            "header_footer": header_footer,
            "design_tokens": "",
            "template_id": None,
            "template_hash": None,
            "template_name": None,
            "generated_at": time.time(),
        }

    # ---- prompt / 工具 ----

    @classmethod
    def _build_image_part_prompt(cls, part: str, creativity: int, crops: Optional[Dict[str, Dict]] = None) -> str:
        label, spec = _SUITE_IMAGE_PARTS.get(part, (part, "对应页面 HTML"))
        prompt = (
            f"你是一位专业的 PPT 模板设计师。请仔细观察这张【{label}】截图，分析其设计语言："
            f"配色、字体、版式、背景装饰、材质、间距等。然后严格按照该设计生成{spec}。\n"
            "要求：\n"
            "- 只输出 HTML 本身，不要 Markdown 代码块，不要任何解释文字。\n"
            "- 尽量沿用截图中的配色/字体/版式/装饰元素，让生成结果与该页面风格一致。\n"
            "- 不要照抄截图里的具体文字内容，保留槽位占位符供后续填入真实内容。\n"
            "- 画面适配 1280×720，overflow:hidden，禁止滚动条、禁止 @media。\n"
            f"- 创意度：{creativity}/10（0=严格复刻截图设计，10=可在截图基础上大胆优化）。"
        )
        if crops:
            tags = "\n".join(
                f"- {name}：{cls._build_asset_img_tag(name, meta)}"
                for name, meta in crops.items()
            )
            prompt += (
                "\n\n**截图中的真实图片/图标（必须直接复用，不要省略、不要另找图片、不要用色块替代）**\n"
                "以下是从该截图识别出的真实图片/图标，以及它们应放置的位置/尺寸。请在生成 HTML 时，"
                "把下列 <img> 标签**原样复制**到对应位置（src 保持 SUITE_ASSET: 前缀不变，style 可微调但不要删除这些 img）：\n"
                + tags
            )
        return prompt

    @staticmethod
    def _build_design_reference(generated_html: Dict[str, str]) -> str:
        refs = []
        for key, html in generated_html.items():
            label = _SUITE_IMAGE_PARTS.get(key, (key, ""))[0]
            refs.append(f"=== {label} ===" + "\n" + (html[:3000] if html else ""))
        return "\n\n".join(refs)

    @staticmethod
    def _build_missing_part_prompt(part: str, design_reference: str, creativity: int) -> str:
        label, spec = _SUITE_IMAGE_PARTS.get(part, (part, "对应页面 HTML"))
        return (
            f"你是一位专业的 PPT 模板设计师。请参考下面「已生成页面」的设计语言（配色/字体/版式/背景装饰），"
            f"为套件补充缺失的【{label}】。请生成{spec}。\n"
            "要求：\n"
            "- 沿用参考页的配色、字体、版式与装饰语言，让整套模板风格统一。\n"
            "- 只输出 HTML 本身，不要 Markdown 代码块，不要解释文字。\n"
            "- 画面适配 1280×720，overflow:hidden，禁止滚动条；不要照抄参考页的具体文字。\n"
            f"- 创意度：{creativity}/10（0=严格沿用参考设计，10=可在参考基础上大胆优化）。\n\n"
            "【已生成页面设计参考】\n" + design_reference
        )

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        text = (text or "").split("</think>")[-1].strip()
        m = _re.search(r"```(?:html)?\s*([\s\S]*?)\s*```", text, flags=_re.IGNORECASE)
        if m:
            return m.group(1).strip()
        idx = text.find("<")
        return text[idx:].strip() if idx != -1 else text

    @staticmethod
    def _guess_image_mime(data: bytes) -> str:
        if data[:4] == b"\x89PNG":
            return "image/png"
        if data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if data[:2] == b"BM":
            return "image/bmp"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return "image/png"

    @staticmethod
    def _is_vision_server_error(exc: Exception) -> bool:
        """判断视觉调用失败是否为服务端/端点不可用（此时可整体跳过后续视觉调用）。"""
        msg = str(exc or "").lower()
        return any(
            h in msg
            for h in (
                "503",
                "429",
                "500",
                "502",
                "504",
                "unavailable",
                "server_error",
                "upstream",
                "endpoint",
                "overloaded",
                "busy",
                "timeout",
                "service unavailable",
                "no response",
                "temporarily",
                "too many",
                "rate limit",
            )
        )

    @staticmethod
    def _ensure_standalone_html(html: str) -> str:
        html = (html or "").strip()
        if not html:
            return html
        low = html.lower()
        if low.startswith("<!doctype") or "<html" in low[:200]:
            return html
        return (
            "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
            "<style>html,body{margin:0;padding:0;width:1280px;height:720px;overflow:hidden}</style>"
            f"</head><body>{html}</body></html>"
        )

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
