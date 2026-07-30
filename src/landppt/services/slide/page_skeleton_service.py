"""页型骨架（Page-Type Skeletons）生成 + 缓存 + 占位符注入服务。

选定模板后，一次性生成按页型分型的固化 HTML 骨架并存入项目级缓存：
- 封面/目录/过渡/结尾页：固化整页结构，生成时仅做命名占位符替换（不调 LLM 即得整页）。
- 内容页：固化页头页脚，主体区保留 {{MAIN_CONTENT}}，由 AI 只生成片段后机械拼回。

页头页脚跨页一致性由此从「LLM 自然语言约束」升级为「机械注入」。
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..prompts import prompts_manager

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class PageSkeletonService:
    """按页型分型的固化骨架生成与占位符注入。

    遵循 CreativeDesignService 的 owner 包装模式：缓存属性写入 owner（EnhancedPPTService），
    其余行为通过 __getattr__ 转发。
    """

    _OWNER_CACHE_ATTRS = {
        "_cached_page_type_skeletons",
        "_page_type_skeletons_ready_events",
    }

    # 页型键，与 DesignPrompts._normalize_page_guidance_type 输出对齐
    PAGE_TYPES: tuple = ("cover", "agenda", "transition", "content", "ending")

    def __init__(self, service: "EnhancedPPTService"):
        object.__setattr__(self, "_service", service)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def __setattr__(self, name: str, value):
        if name == "_service":
            object.__setattr__(self, name, value)
            return
        if name in self._OWNER_CACHE_ATTRS:
            setattr(self._service, name, value)
            return
        object.__setattr__(self, name, value)

    # ================================================================
    # 占位符替换工具（机械注入）
    # ================================================================

    @staticmethod
    def html_escape(text: Any) -> str:
        """转义用户/大纲文本，避免破坏骨架 HTML。"""
        if text is None:
            return ""
        s = str(text)
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    @staticmethod
    def has_main_content_placeholder(skeleton_html: str) -> bool:
        return bool(skeleton_html) and "{{MAIN_CONTENT}}" in skeleton_html

    @staticmethod
    def render_content_skeleton(skeleton_html: str, main_content: str, page_title: str,
                                page_number: int, total_pages: int) -> str:
        """把内容页片段与页头页脚变量机械注入内容页骨架。"""
        html = skeleton_html
        html = html.replace("{{MAIN_CONTENT}}", main_content or "")
        html = html.replace("{{PAGE_TITLE}}", PageSkeletonService.html_escape(page_title))
        html = html.replace("{{PAGE_NUMBER}}", str(page_number))
        html = html.replace("{{TOTAL_PAGES}}", str(total_pages))
        return html

    @staticmethod
    def render_special_skeleton(skeleton_html: str, variables: Dict[str, str]) -> str:
        """把具名变量机械注入特殊页骨架。

        variables 键为占位符名（不带花括号），例如 {{'TITLE': '...'}}。
        缺失的占位符原样保留（无内容则视为空，统一置空避免暴露占位符原文）。
        """
        html = skeleton_html
        for key, value in (variables or {}).items():
            html = html.replace("{{" + key + "}}", PageSkeletonService.html_escape(value))
        # 视为空的占位符：凡骨架内仍残留的具名占位符，统一替换为空白
        html = re.sub(r"\{\{[A-Z_]+\}\}", "", html)
        return html

    # ================================================================
    # 大纲 -> 变量映射（特殊页填值用）
    # ================================================================

    @staticmethod
    def _first_point(slide_data: Dict[str, Any]) -> str:
        points = slide_data.get("content_points") or slide_data.get("content") or []
        if isinstance(points, list):
            for p in points:
                t = str(p).strip()
                if t:
                    return t
        elif isinstance(points, str) and points.strip():
            return points.strip()
        return ""

    @staticmethod
    def _second_point(slide_data: Dict[str, Any]) -> str:
        points = slide_data.get("content_points") or []
        if isinstance(points, list):
            texts = [str(p).strip() for p in points if str(p).strip()]
            if len(texts) >= 2:
                return texts[1]
        return ""

    def build_special_variables(self, slide_data: Dict[str, Any], page_number: int,
                                total_pages: int, page_type: str) -> Dict[str, str]:
        """根据大纲字段构造特定页型的占位符变量集。"""
        title = slide_data.get("title", f"第{page_number}页")
        subtitle = slide_data.get("subtitle", "") or ""
        points = slide_data.get("content_points") or slide_data.get("content") or []

        if page_type == "cover":
            subtitle_value = subtitle or self._first_point(slide_data)
            return {"TITLE": title, "SUBTITLE": subtitle_value}

        if page_type == "agenda":
            # 目录条目逐项填入 {{AGENDA_ITEMS}}
            items_html = ""
            if isinstance(points, list):
                items = [str(p).strip() for p in points if str(p).strip()]
            elif isinstance(points, str) and points.strip():
                items = [line.strip() for line in points.splitlines() if line.strip()]
            else:
                items = []
            for i, it in enumerate(items, start=1):
                items_html += f'<li><span class="ag-num">{i}</span><span class="ag-text">{self.html_escape(it)}</span></li>\n'
            return {"TITLE": title, "AGENDA_ITEMS": items_html}

        if page_type == "transition":
            chapter_hint = subtitle or self._second_point(slide_data) or self._first_point(slide_data)
            return {"CHAPTER_NAME": title, "CHAPTER_HINT": chapter_hint}

        if page_type == "ending":
            ending_hint = subtitle or self._first_point(slide_data) or "感谢聆听"
            return {"TITLE": title, "ENDING_HINT": ending_hint}

        return {"TITLE": title}

    # ================================================================
    # 骨架解析
    # ================================================================

    @classmethod
    def _parse_skeletons(cls, raw_text: str) -> Dict[str, str]:
        """从模型返回中提取各页型骨架与页头/页脚令牌块。

        返回: {
            "cover": "<html>...", "agenda": ..., ..., "content": ...,
            "_header_lock": "...", "_footer_lock": "...",
            "_constitution": "===HEADER_LOCK===...===FOOTER_LOCK===...",
        }
        """
        result: Dict[str, str] = {}
        if not raw_text:
            return result

        # 各页型骨架
        pattern = re.compile(
            r"===SKELETON:(cover|agenda|transition|content|ending)===(.*?)(?====SKELETON:|===HEADER_LOCK===|===FOOTER_LOCK===|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        for m in pattern.finditer(raw_text):
            result[m.group(1).lower()] = m.group(2).strip()

        # 页头/页脚令牌块（供 AestheticPreFlightChecker 比对的整段宪法文本）
        header_match = re.search(
            r"===HEADER_LOCK===(.*?)(?====FOOTER_LOCK===|\Z)", raw_text, re.DOTALL | re.IGNORECASE
        )
        footer_match = re.search(
            r"===FOOTER_LOCK===(.*?)\Z", raw_text, re.DOTALL | re.IGNORECASE
        )
        header_block = header_match.group(1).strip() if header_match else ""
        footer_block = footer_match.group(1).strip() if footer_match else ""
        if header_block and footer_block:
            result["_constitution"] = f"===HEADER_LOCK===\n{header_block}\n===FOOTER_LOCK===\n{footer_block}"
        result["_header_lock"] = header_block
        result["_footer_lock"] = footer_block

        return result

    def _fill_missing_with_template(self, skeletons: Dict[str, str], template_html: str) -> Dict[str, str]:
        """任一页型骨架缺失时回退：内容页用原模板作为片段注入容器，特殊页留空（调用方再回退 fallback）。"""
        if not skeletons.get("content"):
            skeletons["content"] = template_html or ""
        for t in ("cover", "agenda", "transition", "ending"):
            skeletons.setdefault(t, "")
        return skeletons

    # ================================================================
    # 生成 + 缓存
    # ================================================================

    async def _generate_page_type_skeletons(
        self,
        template_html: str,
        confirmed_requirements: Dict[str, Any],
        all_slides: List[Dict[str, Any]],
        total_pages: int,
    ) -> Dict[str, str]:
        """调用 LLM 生成整套页型骨架并解析。"""
        default = {
            "cover": "", "agenda": "", "transition": "", "content": template_html or "", "ending": "",
            "_header_lock": "", "_footer_lock": "", "_constitution": "",
        }
        if not template_html or not template_html.strip():
            return default
        try:
            prompt = prompts_manager.get_page_type_skeletons_prompt(
                template_html=template_html,
                confirmed_requirements=confirmed_requirements or {},
                total_pages=total_pages,
                all_slides=all_slides or [],
            )
            response = await self._text_completion_for_role("creative", prompt=prompt, temperature=0.5)
            raw = self._strip_think_tags(response.content.strip())
            skeletons = self._parse_skeletons(raw)
            # 关键页型缺失则回退
            if not skeletons.get("content"):
                skeletons["content"] = template_html
            for t in ("cover", "agenda", "transition", "ending"):
                skeletons.setdefault(t, "")
            if not skeletons.get("_constitution"):
                skeletons["_header_lock"] = ""
                skeletons["_footer_lock"] = ""
                skeletons["_constitution"] = ""
            logger.info(
                "生成页型骨架完成: cover=%s agenda=%s transition=%s content=%s ending=%s",
                bool(skeletons.get("cover")), bool(skeletons.get("agenda")),
                bool(skeletons.get("transition")), bool(skeletons.get("content")),
                bool(skeletons.get("ending")),
            )
            return skeletons
        except Exception as exc:
            logger.warning("生成页型骨架失败，回退到模板作为内容骨架: %s", exc)
            return default

    async def _get_or_generate_page_type_skeletons(
        self,
        project_id: str,
        template_html: str,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        total_pages: int = 1,
    ) -> Dict[str, str]:
        """获取或生成页型骨架，内存 Event + 文件缓存保证并发安全与可复用。

        缓存键为 project_id；模板切换时由 clear_cached_style_genes 一并清理。
        """
        cache_attr = "_cached_page_type_skeletons"
        event_attr = "_page_type_skeletons_ready_events"
        fallback = {
            "cover": "", "agenda": "", "transition": "", "content": template_html or "", "ending": "",
            "_header_lock": "", "_footer_lock": "", "_constitution": "",
        }

        if not project_id:
            return await self._generate_page_type_skeletons(
                template_html, confirmed_requirements, all_slides, total_pages
            )

        if hasattr(self, cache_attr) and project_id in getattr(self, cache_attr, {}):
            logger.info("从内存缓存获取项目 %s 的页型骨架", project_id)
            return getattr(self, cache_attr)[project_id]

        skeletons = None
        if hasattr(self, "cache_dirs") and self.cache_dirs:
            cache_file = self.cache_dirs["style_genes"] / f"{project_id}_page_type_skeletons.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                        skeletons = data.get("skeletons")
                        logger.info("从文件缓存获取项目 %s 的页型骨架", project_id)
                except Exception as exc:
                    logger.warning("读取页型骨架缓存文件失败: %s", exc)

        if skeletons and skeletons.get("content"):
            if not hasattr(self, cache_attr):
                setattr(self, cache_attr, {})
            getattr(self, cache_attr)[project_id] = skeletons
            return skeletons

        if not hasattr(self, event_attr):
            setattr(self, event_attr, {})
        events_dict = getattr(self, event_attr)

        if project_id not in events_dict:
            event = asyncio.Event()
            events_dict[project_id] = event
            try:
                skeletons = await self._generate_page_type_skeletons(
                    template_html, confirmed_requirements, all_slides, total_pages
                )
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = skeletons

                if hasattr(self, "cache_dirs") and self.cache_dirs:
                    try:
                        cache_file = self.cache_dirs["style_genes"] / f"{project_id}_page_type_skeletons.json"
                        cache_data = {
                            "project_id": project_id,
                            "skeletons": skeletons,
                            "created_at": time.time(),
                            "template_hash": hashlib.md5(template_html.encode()).hexdigest()[:8],
                        }
                        with open(cache_file, "w", encoding="utf-8") as handle:
                            json.dump(cache_data, handle, ensure_ascii=False, indent=2)
                        logger.info("提取并缓存项目 %s 的页型骨架到文件", project_id)
                    except Exception as exc:
                        logger.warning("保存页型骨架缓存文件失败: %s", exc)
                return skeletons
            except Exception as exc:
                logger.warning("生成项目 %s 的页型骨架失败，使用回退值: %s", project_id, exc)
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = fallback
                return fallback
            finally:
                event.set()

        event = events_dict[project_id]
        if not event.is_set():
            try:
                await asyncio.wait_for(event.wait(), timeout=600.0)
            except asyncio.TimeoutError:
                logger.warning("等待项目 %s 的页型骨架缓存超时，使用回退值", project_id)
                return fallback
        return getattr(self, cache_attr, {}).get(project_id, fallback)

    def get_skeletons(self, project_id: str) -> Dict[str, str]:
        """同步读取已缓存的页型骨架（无则返回空字典）。"""
        if not project_id or not hasattr(self, "_cached_page_type_skeletons"):
            return {}
        return getattr(self, "_cached_page_type_skeletons", {}).get(project_id, {})

    def is_enabled(self) -> bool:
        """页型骨架特性是否启用。"""
        from ...core.config import ai_config
        return bool(getattr(ai_config, "enable_page_type_skeletons", True))

    @staticmethod
    def resolve_page_type(slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """判定单页归属的页型键（cover/agenda/transition/content/ending）。

        复用 DesignPrompts._normalize_page_guidance_type 的归一规则，保证分发与
        现有三层架构提示词、AestheticPreFlightChecker 豁免口径一致。
        """
        from ..prompts.design_prompts import DesignPrompts
        return DesignPrompts._normalize_page_guidance_type(slide_data or {}, page_number, total_pages)

    async def render_slide_from_skeleton_or_none(
        self,
        project_id: str,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        system_prompt: str,
        style_genes: str = "",
        global_constitution: str = "",
        current_page_brief: str = "",
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        template_html: str = "",
    ) -> Optional[str]:
        """若页型骨架可用，按页型分型产出整页 HTML；否则返回 None 让调用方走原整页生成链路。

        - 特殊页（cover/agenda/transition/ending）：填命名变量，不调 LLM。
        - 内容页：调 _generate_content_fragment_with_retry 生成主体片段，再机械注入骨架。
        拼装后的整页交给调用方做后续溢出测量/布局修复，本方法不做 layout repair 以免重复。
        """
        if not self.is_enabled() or not project_id:
            return None
        skeletons = self.get_skeletons(project_id)
        if not skeletons or not skeletons.get("content"):
            return None

        page_type = self.resolve_page_type(slide_data, page_number, total_pages)
        if page_type == "content":
            return await self._render_content_page(
                skeletons, slide_data, page_number, total_pages,
                system_prompt, style_genes, global_constitution, current_page_brief,
                confirmed_requirements or {}, all_slides or [], template_html,
            )

        skeleton_html = skeletons.get(page_type) or ""
        if not skeleton_html:
            return None
        return self._render_special_page(skeleton_html, slide_data, page_number, total_pages, page_type)

    async def _render_content_page(
        self,
        skeletons: Dict[str, str],
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        system_prompt: str,
        style_genes: str,
        global_constitution: str,
        current_page_brief: str,
        confirmed_requirements: Dict[str, Any],
        all_slides: List[Dict[str, Any]],
        template_html: str,
    ) -> str:
        """内容页：AI 只生成主体片段，机械注入内容页骨架。失败回退到整页 fallback。"""
        skeleton_html = skeletons["content"]
        if not self.has_main_content_placeholder(skeleton_html):
            # 骨架无效（缺 {{MAIN_CONTENT}}），交回原整页链路
            return None  # type: ignore[return-value]

        context_info = self._build_slide_context(slide_data, page_number, total_pages)
        # 确保图片上下文（沿用现状：填入 slide_data 供片段引用）
        try:
            await self._ensure_slide_images_context(
                slide_data, confirmed_requirements, page_number, total_pages, template_html
            )
        except Exception as exc:
            logger.warning("内容页图片上下文准备失败（slide %s），继续生成: %s", page_number, exc)

        fragment_prompt = prompts_manager.get_slide_content_fragment_prompt(
            slide_data=slide_data,
            confirmed_requirements=confirmed_requirements,
            page_number=page_number,
            total_pages=total_pages,
            context_info=context_info,
            style_genes=style_genes or "",
            skeleton_html=skeleton_html,
            global_constitution=global_constitution or "",
            current_page_brief=current_page_brief or "",
        )
        try:
            fragment = await self._generate_content_fragment_with_retry(
                fragment_prompt, system_prompt, slide_data, page_number, total_pages, max_retries=5
            )
        except Exception as exc:
            logger.error("内容页片段生成异常（slide %s）: %s", page_number, exc)
            fragment = ""

        if not fragment or not fragment.strip():
            logger.warning("内容页片段为空，回退整页 fallback slide %s", page_number)
            fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
            return await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)

        full_html = self.render_content_skeleton(
            skeleton_html,
            main_content=fragment,
            page_title=slide_data.get("title", f"第{page_number}页"),
            page_number=page_number,
            total_pages=total_pages,
        )
        full_html = self._inject_anti_overflow_css(full_html)
        return await self._apply_auto_layout_repair(full_html, slide_data, page_number, total_pages)

    def _render_special_page(
        self,
        skeleton_html: str,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        page_type: str,
    ) -> str:
        """特殊页：填命名变量（不调 LLM）。"""
        variables = self.build_special_variables(slide_data, page_number, total_pages, page_type)
        html = self.render_special_skeleton(skeleton_html, variables)
        html = self._inject_anti_overflow_css(html)
        logger.info("使用页型骨架填充特殊页: page_type=%s, page=%s", page_type, page_number)
        return html