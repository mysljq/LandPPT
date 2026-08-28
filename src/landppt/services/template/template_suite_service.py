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
import re
import time
from typing import Any, Dict, List, Optional

from ..prompts.template_prompts import TemplatePrompts
from .master_layout_extractor import MasterLayoutExtractor

logger = logging.getLogger(__name__)

# 套件 AI 输出预算（token）。注意：对 glm-5.3-flash（opencode.ai 备用 OpenAI 通道）等
# 强制思考模型，端点把 max_tokens 视为「推理 + 可见输出」的总预算；长任务里推理几乎
# 吃光预算，可见内容直接为空（finish_reason=length）。套件一次要输出 5 大段 HTML，
# 预算必须同时盖住推理与可见 JSON，故整体放宽到 32000；重试是最后一次兜底，再留裕量
# 到 48000（端点实测接受 ≥50000）。
_SUITE_AI_OUTPUT_BUDGET = 32000
_SUITE_AI_RETRY_OUTPUT_BUDGET = 48000


class TemplateSuiteService:
    """Own template-suite generation, caching, and retrieval."""

    # Keys persisted under project.project_metadata["template_suite"].
    _METADATA_KEY = "template_suite"

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    # ------------------------------------------------------------------
    # 品牌槽位（生成 PPT 时用真实项目值替换套件里固化的品牌文案）
    # ------------------------------------------------------------------
    # 槽位名：套件（尤其新生成套件）里把年份/部门/主题/标语写成这些槽位，生成 PPT
    # 前统一替换为项目真实值。老套件固化的文案则走 LLM 语义分析识别。
    # brand_code（编号）已弃用：不再指导新套件生成，仅保留常量用于把老套件残留的
    # {{brand_code}} 槽位清空——PPT 只要章节编号/页码，不要整份文档的整体编号。
    BRAND_SLOT_YEAR = "{{brand_year}}"
    BRAND_SLOT_ORG = "{{brand_org}}"
    BRAND_SLOT_TOPIC = "{{brand_topic}}"
    BRAND_SLOT_TAGLINE = "{{brand_tagline}}"
    BRAND_SLOT_CODE = "{{brand_code}}"
    BRAND_SLOTS = (
        BRAND_SLOT_YEAR, BRAND_SLOT_ORG, BRAND_SLOT_TOPIC,
        BRAND_SLOT_TAGLINE, BRAND_SLOT_CODE,
    )
    # 语义分析的角色：year/org/topic/tagline/code 会被替换；skip = 通用结构标签不替换。
    # code（编号）角色仅对老套件生效：brand_code 真实值恒空，槽位会被标准替换清掉，
    # 固化的编号文本（No.01）因无值保持原样 —— 与"PPT 不要整体编号"一致。
    BRAND_ROLES = ("year", "org", "topic", "tagline", "code", "skip")
    # 章节号槽位（结构槽位性质）：过渡页/内容页 header_footer 用，生成 PPT 时填真实章节号。
    # 不是品牌槽位（每页变、生成时才知道），故不进 BRAND_SLOTS/_ROLE_TO_SLOT。
    CHAPTER_SLOT = "{{chapter_number}}"
    # 章节提示槽位（结构槽位性质）：内容页 header_footer 用，勾选"章节提示"后生成。
    # 内容页生成时确定性填充"全部章节名的块列表，当前章节高亮"。仅内容页展示。
    CHAPTER_INDICATOR_SLOT = "{{chapter_indicator}}"
    # 结构槽位（生成时有专门机制填充，不是品牌占位）——语义分析即使误归为品牌角色也不替换。
    STRUCTURE_SLOTS = frozenset({
        "cover_title", "cover_subtitle", "cover_extra",
        "transition_title", "transition_subtitle", "transition_extra",
        "catalog_title", "catalog_subtitle", "catalog_extra", "catalog_items",
        "ending_title", "ending_subtitle", "ending_extra", "ending_items",
        "page_title", "page_content", "current_page_number", "total_page_count",
        "chapter_number", "chapter_indicator",
    })
    # 角色 → 项目值槽位 的映射（用于把 LLM 归类的角色转成真实值来源）。
    _ROLE_TO_SLOT = {
        "year": BRAND_SLOT_YEAR,
        "org": BRAND_SLOT_ORG,
        "topic": BRAND_SLOT_TOPIC,
        "tagline": BRAND_SLOT_TAGLINE,
        "code": BRAND_SLOT_CODE,
    }

    @staticmethod
    @staticmethod
    def _brand_role_by_name(name: str) -> Optional[str]:
        """按槽位名关键词推断品牌角色（不依赖 LLM 语义分析）。

        用于 LLM 分析失败/未覆盖时的确定性兜底，让自定义品牌槽位名
        （{{ fiscal_year }} / {{ dept }} / {{ company }} / {{ brand_year }}…）
        也能被识别并替换为项目真实值。返回 None 表示无法判定为品牌槽位。
        """
        n = (name or "").strip().lower()
        if not n:
            return None
        if "year" in n:
            return "year"
        if any(
            k in n
            for k in ("org", "dept", "department", "company", "bank", "team",
                      "division", "unit", "institution", "group", "agency", "branch")
        ):
            return "org"
        if any(k in n for k in ("topic", "subject", "theme")):
            return "topic"
        if any(k in n for k in ("tagline", "slogan", "motto", "confidential", "internal", "privacy")):
            return "tagline"
        # 章节号槽位（chapter_number/chapter 等）是结构槽位，不是品牌"编号"角色——
        # 其值由大纲 chapter 字段在生成时填充，绝不能被启发式归为 code 以用空值清掉。
        if "chapter" in n:
            return None
        if any(k in n for k in ("code", "serial", "number", "issue")) or n.startswith("no"):
            return "code"
        return None

    @staticmethod
    def _merge_heuristic_brand_roles(
        suite: Dict[str, Any],
        llm_roles: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        """把 LLM 语义分析结果与名字启发式归类合并。

        LLM 结果优先；对 LLM 未覆盖的自定义品牌槽位，按槽位名关键词兜底归类
        （year/dept/company/topic/tagline/code）。结构槽位（cover_title 等）始终跳过，
        即使名字命中关键词也不归类（如 item_1_title 含 "title" 但不含 topic 类关键词，
        且本来就不在品牌词表）。
        """
        import re as _re

        llm_roles = dict(llm_roles or {})
        merged: Dict[str, str] = dict(llm_roles)
        for key in ("header_footer", "cover", "transition", "catalog", "ending"):
            html = str(suite.get(key) or "")
            for m in _re.finditer(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}", html):
                name = m.group(1)
                if name in TemplateSuiteService.STRUCTURE_SLOTS:
                    continue
                # LLM 已归类（key 可能是 "{{ name }}" 或 "name"）→ 保留 LLM 结果
                if m.group(0) in llm_roles or name in llm_roles:
                    continue
                role = TemplateSuiteService._brand_role_by_name(name)
                if role:
                    merged[m.group(0)] = role
        return merged

    @staticmethod
    def _brand_preview_sample(name: str) -> Optional[str]:
        """预览时按槽位名启发式推断品牌示例值（复用 _brand_role_by_name 归类）。

        覆盖 {{brand_year}}/{{year}}/{{company_year}}… 及未来 LLM 发挥的各种品牌槽位名；
        未命中的品牌槽位返回 None，由调用方回退 "[name 示例]"。
        """
        role = TemplateSuiteService._brand_role_by_name(name)
        if role == "year":
            return "2026"
        if role == "org":
            return "XX部门"
        if role == "topic":
            return "年度工作报告"
        if role == "tagline":
            return "DEPARTMENT WORK REPORT"
        if role == "code":
            return "No.01"
        return None

    @staticmethod
    def _resolve_brand_values(project: Any, confirmed_requirements: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """从项目数据解析品牌真实值（年份/主题/部门/标语/编号）。

        年份：project.created_at 优先，其次当前年；主题：project.topic/title；
        部门：从主题常见前缀提取（部门/集团/公司/银行/团队），未命中则空；
        标语：confirmed_requirements 里的 brand_tagline，未配置则空。
        brand_code（编号）已移除：不再从 confirmed 读取，恒为空串——只会把老套件
        残留的 {{brand_code}} 槽位清空（PPT 只要章节编号/页码，不要整体文档编号）。
        """
        import datetime as _dt

        confirmed = confirmed_requirements or {}
        topic = str(
            getattr(project, "topic", "") or confirmed.get("topic") or ""
        ).strip()
        if not topic:
            topic = str(getattr(project, "title", "") or "").strip()

        year = ""
        ts = getattr(project, "created_at", None)
        if ts:
            try:
                year = str(_dt.datetime.fromtimestamp(float(ts)).year)
            except (TypeError, ValueError, OSError):
                year = ""
        if not year:
            year = str(_dt.datetime.now().year)

        org = ""
        if topic:
            for kw in ("部门", "集团", "公司", "银行", "团队", "工厂", "研究院"):
                if topic.startswith(kw):
                    org = kw
                    break

        return {
            TemplateSuiteService.BRAND_SLOT_YEAR: year,
            TemplateSuiteService.BRAND_SLOT_TOPIC: topic,
            TemplateSuiteService.BRAND_SLOT_ORG: org,
            TemplateSuiteService.BRAND_SLOT_TAGLINE: str(confirmed.get("brand_tagline") or "").strip(),
            # brand_code（编号）不再生成/配置：恒空串，仅用于把老套件残留槽位替换为空（清除）。
            TemplateSuiteService.BRAND_SLOT_CODE: "",
        }

    @staticmethod
    def _extract_visible_texts_from_html(html: str, max_len: int = 60) -> List[str]:
        """提取 HTML 里可见文本节点与槽位 token（跳过 <style>/<script> 与纯符号）。

        槽位 {{...}} 也保留作为语义分析项——LLM 需要看到它们才能把自定义品牌槽位
        （如 {{year}}/{{dept}}）归到对应角色；结构槽位由 prompt 与代码双保险归 skip。
        """
        import re as _re

        if not html:
            return []
        stripped = _re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=_re.DOTALL | _re.IGNORECASE)
        stripped = _re.sub(r"<script[^>]*>.*?</script>", " ", stripped, flags=_re.DOTALL | _re.IGNORECASE)
        texts = _re.findall(r">([^<>]{1," + str(max_len) + r"})<", stripped)
        out: List[str] = []
        for t in texts:
            t = t.strip()
            if not t:
                continue
            # 纯符号/数字不构成品牌占位（页码等）
            if _re.fullmatch(r"[\s\d·.\-/—|:]+", t):
                continue
            if t not in out:
                out.append(t)
        return out

    @staticmethod
    def _extract_visible_texts_from_suite(suite: Dict[str, Any]) -> List[str]:
        """汇总套件各页面可见文本（去重），供品牌语义分析。"""
        out: List[str] = []
        for key in ("header_footer", "cover", "transition", "catalog", "ending"):
            for t in TemplateSuiteService._extract_visible_texts_from_html(str(suite.get(key) or "")):
                if t not in out:
                    out.append(t)
        return out

    @staticmethod
    def _replace_brand_in_html(
        html: str,
        brand_values: Dict[str, str],
        roles: Optional[Dict[str, str]] = None,
    ) -> str:
        """在 HTML 里做品牌替换：①标准品牌槽位 {{brand_xxx}} → 真实值；②语义归类项
        （槽位名 {{year}}/{{dept}} 或老套件固化文案 "2025"/"DEPARTMENT"）→ 真实值。

        语义归类项由 LLM 给出角色（year/org/topic/tagline/code/skip）：
        - 槽位形式（{{...}}）→ 直接全局替换（槽位不会出现在 CSS 里）；
        - 纯文本 → 仅替换正文节点（跳过 <style>/<script>）；
        - skip 角色 / 结构槽位（cover_title 等，即使误归为品牌角色）→ 绝不替换。
        项目值缺失的角色（如 tagline 未配置）→ 跳过，保持原样。
        """
        if not html:
            return html
        import re as _re
        out = html
        # ① 标准品牌槽位：正则匹配兼容 `{{brand_year}}` 与 `{{ brand_year }}`（带空格）
        # 写法（生成套件的 prompt 转义后常产出带空格写法）；值空也清掉，避免残留。
        for slot, value in brand_values.items():
            name = slot.strip("{}").strip()
            out = _re.sub(r"{{\s*" + _re.escape(name) + r"\s*}}", value, out)
        # ② 语义归类项（槽位名或纯文本）
        if roles:
            for key, role in roles.items():
                if role == "skip" or not key:
                    continue
                # 结构槽位即使被误归为品牌角色也绝不替换（由专门的填充机制处理）
                bare = key.strip()
                if bare.startswith("{{") and bare.endswith("}}"):
                    bare = bare[2:-2].strip()
                if bare in TemplateSuiteService.STRUCTURE_SLOTS:
                    continue
                replacement = brand_values.get(TemplateSuiteService._ROLE_TO_SLOT.get(role, ""), "")
                if not replacement:
                    continue
                if key.startswith("{{") and key.endswith("}}"):
                    out = _re.sub(r"{{\s*" + _re.escape(bare) + r"\s*}}", replacement, out)
                elif key in out:
                    out = TemplateSuiteService._replace_text_node_safe(out, key, replacement)
        return out

    @staticmethod
    def _replace_text_node_safe(html: str, old: str, new: str) -> str:
        """仅替换 HTML 正文里的文本（跳过 <style>/<script>），避免误伤 CSS/JS 里的子串。"""
        import re as _re

        def _repl(m: _re.Match) -> str:
            seg = m.group(0)
            if seg.lstrip().lower().startswith(("<style", "<script")):
                return seg  # CSS/JS 段原样保留，不替换
            return seg.replace(old, new)

        pattern = _re.compile(
            r"(?s)<style[^>]*>.*?</style>|<script[^>]*>.*?</script>|" + _re.escape(old)
        )
        return pattern.sub(_repl, html)

    @staticmethod
    def _instantiate_suite_brand(
        suite: Dict[str, Any],
        brand_values: Dict[str, str],
        roles: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """返回品牌实例化后的套件副本（只影响生成 PPT 用，不改库数据/预览）。
        对 header_footer/cover/transition/catalog/ending 做品牌槽位 + 固化文案替换。"""
        updated = dict(suite)
        for key in ("header_footer", "cover", "transition", "catalog", "ending"):
            html = str(updated.get(key) or "")
            if not html:
                continue
            branded = TemplateSuiteService._replace_brand_in_html(html, brand_values, roles)
            if branded != html:
                updated[key] = branded
        return updated

    # 套件品牌语义分析结果缓存（按套件内容哈希）
    _brand_roles_cache: Dict[str, Dict[str, str]] = {}

    @classmethod
    def _build_brand_analysis_prompt(cls, texts: List[str]) -> str:
        """构建套件品牌文案语义分析提示词：识别固化文案/槽位的角色。"""
        structure_slots = "、".join(sorted(TemplateSuiteService.STRUCTURE_SLOTS))
        listed = "\n".join(f"- {t}" for t in texts)
        return f"""请分析下面这套 PPT 套件里可见的文案与槽位（{{{{...}}}}）分别是什么角色。

角色定义：
- "year"：年份（如 2025、{{{{brand_year}}}}、{{{{year}}}}、{{{{company_year}}}}）
- "org"：部门/单位/机构（如 DEPARTMENT、{{{{brand_org}}}}、{{{{dept}}}}、{{{{department}}}}、{{{{company}}}}）
- "topic"：主题/标题标识（如 ANNUAL REVIEW、{{{{brand_topic}}}}）
- "tagline"：标语/保密标识/补充英文（如 CONFIDENTIAL / INTERNAL USE、DEPT. REPORT、{{{{brand_tagline}}}}）
- "code"：编号（如 No.01、{{{{brand_code}}}}）
- "skip"：**结构槽位 / 通用结构标签，不是品牌占位，绝不替换**

**以下结构槽位一律归 "skip"**（生成时有专门机制填充页面标题/页码/正文/章节，不是品牌值）：
{structure_slots}

判定原则：
- 槽位名或文案语义上是"年份/部门/主题/标语/编号"品牌占位 → 归对应角色（无论名字是不是 brand_ 开头）。
- 结构槽位（上面列表）或纯结构标签（SECTION/CHAPTER/PAGE/THANKS/CONTENTS/NOTE/KEY TAKEAWAYS/TRANSITION 等）→ 一律 skip。
- 只对希望生成时替换成真实品牌值的项归类。

可见文案/槽位列表：
{listed}

只输出 JSON 对象，键为原文案或槽位、值为角色，不要解释：
{{"原文案或槽位1": "role", "原文案或槽位2": "role"}}
"""

    async def _analyze_suite_brand_roles(self, suite: Dict[str, Any]) -> Dict[str, str]:
        """LLM 语义分析套件固化的品牌文案角色（year/org/topic/tagline/code/skip）。

        结果按套件内容哈希缓存（套件不变则复用，避免每次生成都烧 LLM）。
        分析失败/未命中返回 {}（不替换、不阻断生成）。
        """
        import hashlib as _h
        import json as _j

        if not suite:
            return {}
        key_src = "".join(str(suite.get(k) or "") for k in ("header_footer", "cover", "transition", "catalog", "ending"))
        key = _h.md5(key_src.encode("utf-8")).hexdigest()
        cache = type(self)._brand_roles_cache
        if key in cache:
            return cache[key]

        texts = self._extract_visible_texts_from_suite(suite)
        if not texts:
            return {}
        prompt = self._build_brand_analysis_prompt(texts)
        try:
            response = await self._text_completion_for_role(
                "template", prompt=prompt, temperature=0.2
            )
            content = response.content if hasattr(response, "content") else str(response)
            parsed = self._parse_brand_roles_json(content)
            if parsed:
                cache[key] = parsed
                return parsed
        except Exception as exc:
            logger.warning("套件品牌语义分析失败（保持原样）: %s", exc)
        return {}

    @staticmethod
    def _parse_brand_roles_json(content: str) -> Dict[str, str]:
        """解析 LLM 输出的品牌角色 JSON（兼容代码块/前后散文/损坏引号）。"""
        import json as _j
        import re as _re

        if not content:
            return {}
        text = content.strip()
        m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=_re.DOTALL)
        if m:
            text = m.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                text = text[start:end + 1]
        try:
            data = _j.loads(text)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        valid = set(TemplateSuiteService.BRAND_ROLES)
        return {
            str(k).strip(): str(v).strip()
            for k, v in data.items()
            if str(k).strip() and str(v).strip() in valid
        }

    async def instantiate_suite_brand_for_project(
        self,
        project_id: str,
        suite: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """生成 PPT 专用：把套件品牌槽位/固化文案替换为项目真实值，返回副本。

        仅影响本次生成（不改库数据、不影响预览/套件编辑）。
        - 新套件含品牌槽位 {{brand_xxx}} → 直接替换为项目值。
        - 老套件无槽位 → LLM 语义分析识别固化文案角色（按套件缓存），非 skip 才替换。
        - 品牌值来源：project.created_at（年份）、project.topic（主题）、标题前缀（部门）。
        任何失败保持原套件生成，不阻断。
        """
        if not suite or not isinstance(suite, dict):
            return suite
        try:
            project = None
            confirmed: Dict[str, Any] = {}
            if project_id:
                project = await self.project_manager.get_project(project_id)
                if project is not None:
                    cr = getattr(project, "confirmed_requirements", None) or {}
                    confirmed = dict(cr) if isinstance(cr, dict) else {}
            brand_values = self._resolve_brand_values(project, confirmed)
            # 总是跑 LLM 语义分析（按套件内容哈希缓存，套件不变不重复烧）：
            # 覆盖 ①标准品牌槽位、②LLM 自由发挥的自定义品牌槽位（{{year}}/{{dept}}…）、
            # ③老套件固化文案（2025/DEPARTMENT…）。结构槽位（cover_title 等）双保险归 skip。
            roles = await self._analyze_suite_brand_roles(suite)
            # 名字启发式兜底：LLM 分析失败/未覆盖的自定义品牌槽位，按槽位名关键词归类
            # （fiscal_year→year、dept→org…），让品牌替换不完全依赖 LLM 成功。
            roles = self._merge_heuristic_brand_roles(suite, roles)
            updated = self._instantiate_suite_brand(suite, brand_values, roles)
            # 精确适配内容区 top：按套件实测 header 底边（各套件差异大，id=13 底 115 /
            # id=15 底 135 / id=14 底 235），用精确值覆盖 .suite-stage top，并写入
            # `_suite_stage_top` 供生成 prompt 使用（LLM 生成内容页沿用正确 top）。
            try:
                stage_top = await self._measure_stage_top(updated)
                if stage_top:
                    updated["header_footer"] = self._ensure_standard_content_stage(
                        updated.get("header_footer") or "", stage_top=stage_top
                    )
                    updated["_suite_stage_top"] = stage_top
            except Exception as exc:
                logger.warning("套件内容区 top 精确适配失败（用默认值）: %s", exc)
            return updated
        except Exception as exc:
            logger.warning("套件品牌实例化失败（按原套件生成）: %s", exc)
            return suite

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

    async def select_global_suite(self, project_id: str, suite_id: int) -> bool:
        """Persist a chosen global-library suite as this project's suite source."""
        try:
            from .global_template_suite_service import GlobalTemplateSuiteService
            svc = GlobalTemplateSuiteService(self._service)
            suite = await svc.get_suite_payload(suite_id)
            if not suite:
                return False
            project = await self.project_manager.get_project(project_id)
            if not project:
                return False
            metadata = dict(project.project_metadata or {})
            metadata["selected_global_suite_id"] = suite_id
            metadata.pop("template_suite", None)  # 全局套件优先，清掉项目内旧套件避免混淆
            await self.project_manager.update_project_metadata(project_id, metadata)
            await svc.increment_usage(suite_id)
            return True
        except Exception as exc:
            logger.error("Failed to select global suite %s for %s: %s", suite_id, project_id, exc)
            return False

    async def clear_selected_global_suite(self, project_id: str) -> bool:
        """Remove the project's selected global-library suite (fall back to project suite)."""
        try:
            project = await self.project_manager.get_project(project_id)
            if not project:
                return False
            metadata = dict(project.project_metadata or {})
            if "selected_global_suite_id" in metadata:
                metadata.pop("selected_global_suite_id")
                await self.project_manager.update_project_metadata(project_id, metadata)
            return True
        except Exception as exc:
            logger.error("Failed to clear selected global suite for %s: %s", project_id, exc)
            return False

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
            # 历史 brand_code → chapter_number 迁移（读时 backfill 安全网）：老项目套件
            # 可能在 migration 014 落库前仍含 {{brand_code}}，读取时即时转换并回写库，
            # 与下面 header_footer 自包含 backfill 同风格（变换 + 回写 _persist_suite）。
            try:
                migrated = self._migrate_suite_brand_code(suite)
                if migrated is not suite and migrated != suite:
                    await self._persist_suite(project_id, migrated)
                    suite = migrated
            except Exception as exc:
                logger.warning("Migrate brand_code for project suite %s failed: %s", project_id, exc)
            # 大纲智能套件：不依赖母版模板，直接生效。
            if suite.get("template_mode") == "outline":
                return suite
            # 仅使用套件模式：项目不绑定母版模板，套件自包含直接生效
            # （header_footer 已被回填为内联 :root 变量，无需与模板做 template_hash 校验）。
            if metadata.get("template_mode") == "suite":
                return suite
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

            # 自包含兜底 + A2 标准化内容舞台 backfill：若 header_footer 引用母版
            # :root 变量、骨架不完整，或缺少标准 .suite-stage 容器，则补齐并回写。
            try:
                hf = str(suite.get("header_footer") or "")
                import re as _re
                needs_fix = (
                    _re.search(r"var\(--", hf)
                    or not _re.search(r'class="[^"]*(?:canvas|hf-canvas)[^"]*"', hf)
                    or not _re.search(r'\.(?:canvas|bg-paper|bg-grid|frame-corner)\s*\{', hf)
                    or bool(_re.search(r'<div class="[^"]*$', hf, _re.MULTILINE))
                )
                # 标准化内容舞台容器（每页免重生成即生效）
                standardized = self._ensure_standard_content_stage(hf)
                if standardized != hf:
                    needs_fix = True
                    header_footer_standardized = standardized
                else:
                    header_footer_standardized = None
                if needs_fix:
                    extracted = MasterLayoutExtractor.extract_header_footer(
                        template.get("html_template") or ""
                    )
                    hf_current = header_footer_standardized if header_footer_standardized is not None else hf
                    fixed = self._ensure_header_footer_complete(
                        hf_current,
                        template.get("html_template") or "",
                        extracted.get("root_variables") or "",
                    )
                    # 完整性 backfill 可能未含标准舞台，再标准化一次确保 .suite-stage 在
                    fixed = self._ensure_standard_content_stage(fixed)
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
        """Lightweight status for the frontend button (existence + freshness).

        用 get_effective_suite：选中的套件库套件也算作项目当前有效套件。
        """
        suite = await self.get_effective_suite(project_id)
        if not suite:
            return {"status": "none"}
        return {
            "status": "ready",
            "template_name": suite.get("template_name"),
            "generated_at": suite.get("generated_at"),
        }

    async def get_effective_suite(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Return the suite the project should use when generating PPT.

        Priority:
        1. A suite explicitly selected from the global suite library
           (project_metadata["selected_global_suite_id"]) — no template_hash check
           (the user explicitly chose this suite, respect it).
        2. Otherwise the project's own generated template_suite (existing logic).
        3. None if neither exists.
        """
        try:
            project = await self.project_manager.get_project(project_id)
            if not project:
                return None
            metadata = project.project_metadata or {}

            global_suite_id = metadata.get("selected_global_suite_id")
            if global_suite_id:
                try:
                    from .global_template_suite_service import GlobalTemplateSuiteService
                    svc = GlobalTemplateSuiteService(self._service)
                    suite = await svc.get_suite_payload(global_suite_id)
                    if suite:
                        return suite
                except Exception as exc:
                    logger.warning(
                        "Failed to load selected global suite %s for %s: %s",
                        global_suite_id, project_id, exc,
                    )
                    # fall through to project-local suite

            return await self.get_suite(project_id)
        except Exception as exc:
            logger.warning("Failed to get effective suite for project %s: %s", project_id, exc)
            return None

    _PREVIEW_CHAPTER_TITLES = ("概述", "核心方案", "实施路径", "总结与展望")

    @staticmethod
    def _preview_chapter_titles(
        all_slides: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """预览章节名优先取项目目录页；无项目大纲时使用统一示例章节。"""
        if all_slides:
            from ..slide.slide_media_service import SlideMediaService

            chapters = SlideMediaService._extract_directory_chapter_titles(all_slides)
            if chapters:
                return chapters
        return list(TemplateSuiteService._PREVIEW_CHAPTER_TITLES)

    @staticmethod
    def _catalog_items_sample(chapters: Optional[List[str]] = None) -> str:
        """Styled example rows for the catalog items slot (preview only).

        Renders as a designed 目录 list (bullets + dividers + responsive two-column
        grid) instead of a plain text paragraph, so previews show the intended look.
        """
        from html import escape as _escape

        chapter_names = chapters or list(TemplateSuiteService._PREVIEW_CHAPTER_TITLES)
        chinese_numbers = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
        rows = "".join(
            '<div style="display:flex; align-items:center; gap:10px; padding:10px 2px; '
            'border-bottom:1px solid rgba(127,127,127,0.25);">'
            '<span style="flex:0 0 auto; width:8px; height:8px; border-radius:50%; '
            'background:currentColor; opacity:0.35;"></span>'
            f'<span style="font-size:1em; font-weight:600; line-height:1.35;">'
            f'第{chinese_numbers[index - 1] if index <= len(chinese_numbers) else index}章 '
            f'{_escape(str(title))}</span>'
            "</div>"
            for index, title in enumerate(chapter_names, 1)
        )
        return (
            '<div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); '
            'gap:2px 36px; margin-top:8px; text-align:left;">'
            + rows
            + "</div>"
        )

    def build_preview_html(
        self,
        suite: Dict[str, Any],
        all_slides: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, str]:
        """Render the suite into preview pages with sample slot content.

        Returns {"cover", "transition", "catalog", "ending", "content"} where each
        value is a complete, standalone HTML document (1280x720) the frontend can
        show in an iframe. All special pages are filled with rich natural sample
        content so users can see the actual suite effect; the content page composes
        header_footer with a placeholder body.
        """
        from .template_suite_renderer import TemplateSuiteRenderer
        from ..slide.slide_media_service import SlideMediaService

        # 项目内预览使用真实目录章节；套件库预览没有项目上下文时，目录页和内容页
        # 共用同一组示例章节，确保两个 Tab 展示完全一致的章节名称与顺序。
        preview_chapters = self._preview_chapter_titles(all_slides)
        current_chapter = min(2, len(preview_chapters)) if preview_chapters else 0

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
                # 品牌槽位（{{brand_year}}/{{year}}/{{dept}}…）按名字启发式给真实感示例值，
                # 而非 "[name 示例]"。
                sample = TemplateSuiteService._brand_preview_sample(name)
                filled = _re.sub(
                    r"{{\s*" + _re.escape(name) + r"\s*}}",
                    sample if sample is not None else f"[{name} 示例]",
                    filled,
                )
            return filled

        # 封面：主标题 + 副标题 + 演讲人/日期等补充文案
        cover = _fill(
            suite.get("cover"),
            {
                "cover_title": "年度工作报告",
                "cover_subtitle": "2026 年上半年度工作汇报",
                "cover_extra": "汇报人：张三 · 2026年8月",
            },
        )
        # 过渡页：章节标题 + 引导语 + 章节说明 + 章节号示例
        transition = _fill(
            suite.get("transition"),
            {
                "transition_title": (
                    f"第{current_chapter}章 · {preview_chapters[current_chapter - 1]}"
                    if current_chapter else "章节过渡"
                ),
                "transition_subtitle": "从规划到落地，本部分介绍具体实施方案",
                "transition_extra": "核心章节 · 敬请期待",
                "chapter_number": "2",
            },
        )
        # 目录页：有样式的目录行示例（圆点 + 分隔线 + 双栏网格），而非纯段落文本
        catalog = _fill(
            suite.get("catalog"),
            {
                "catalog_title": "目录",
                "catalog_subtitle": "内容概览",
                "catalog_extra": "",
                "catalog_items": self._catalog_items_sample(preview_chapters),
            },
        )
        # 结尾页：感谢标题 + 副标题 + 收尾要点
        ending = _fill(
            suite.get("ending"),
            {
                "ending_title": "感谢聆听",
                "ending_subtitle": "期待与您进一步交流",
                "ending_extra": "",
                "ending_items": "联系方式：contact@example.com\n欢迎关注后续分享",
            },
        )

        # Content page: header/footer fragment + a sample body. 章节提示复用目录页
        # 章节，并采用实际生成阶段相同的“覆盖整个容器”逻辑，避免把完整容器嵌套到
        # 套件原有的 .chapter-indicator 中，导致套件 CSS 无法命中。
        hf = str(suite.get("header_footer") or "")
        indicator_enabled = SlideMediaService._suite_has_chapter_indicator(suite)
        chapter_indicator_sample = ""
        if indicator_enabled and preview_chapters:
            preview_slides = [{
                "slide_type": "agenda",
                "title": "目录",
                "content_points": preview_chapters,
                "chapter": 0,
            }]
            chapter_indicator_sample = SlideMediaService.build_chapter_indicator_html(
                preview_slides,
                {"slide_type": "content", "chapter": current_chapter},
            )
            # 对已有空容器/错误示例列表，先替换整个元素；只有裸槽位时由 _fill 填入。
            hf = SlideMediaService._upsert_chapter_indicator(hf, chapter_indicator_sample)
        hf = _fill(
            hf,
            {
                "page_title": "内容页标题（示例）",
                "current_page_number": "3",
                "total_page_count": "10",
                "chapter_number": "2",
                "chapter_indicator": chapter_indicator_sample,
            },
        )
        content = self._wrap_content_preview(hf)
        if indicator_enabled:
            content = SlideMediaService._upsert_chapter_indicator(
                content, chapter_indicator_sample
            )
            content = SlideMediaService._ensure_chapter_indicator_style(content, suite)

        return {
            "cover": cover,
            "transition": transition,
            "catalog": catalog,
            "ending": ending,
            "content": content,
        }

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


    # ------------------------------------------------------------------
    # 历史 brand_code → chapter_number 迁移（读时 backfill 安全网 + migration 014 落库共用）
    # ------------------------------------------------------------------
    # 老套件把"整体编号"写在 {{brand_code}}。新体系改为：过渡页/内容页用 {{chapter_number}}
    # 表示当前章节序号；封面/目录/结尾页不要任何编号槽位。这里把老套件残留的 brand_code
    # 槽位 token 按页面类型转换：transition/header_footer → chapter_number；其余 → 删除。
    _BRAND_CODE_SLOT_RE = re.compile(r"{{\s*brand_code\s*}}")

    @classmethod
    def _migrate_brand_code_to_chapter(cls, html: str, page_kind: str) -> str:
        """把一段套件 HTML 里的 {{brand_code}} 槽位按页面类型转换。

        - page_kind in ("transition", "header_footer") → 替换成 {{chapter_number}}（章节号槽位）；
        - page_kind in ("cover", "catalog", "ending") → 删除（这些页面不该有编号槽位）；
        - 其它/无 brand_code → 原样返回。

        兼容 {{brand_code}} 与 {{ brand_code }} 两种写法（与品牌替换正则一致）。
        幂等：不含 brand_code 的 HTML 原样返回；已迁移过的不会重复处理。
        """
        if not html:
            return html
        if page_kind in ("transition", "header_footer"):
            return cls._BRAND_CODE_SLOT_RE.sub("{{chapter_number}}", html)
        if page_kind in ("cover", "catalog", "ending"):
            return cls._BRAND_CODE_SLOT_RE.sub("", html)
        return html

    @classmethod
    def _migrate_suite_brand_code(cls, suite: Dict[str, Any]) -> Dict[str, Any]:
        """对一份套件 dict 的 5 段 HTML 各自做 brand_code→chapter 迁移，返回新副本。

        只在含 brand_code 时改动；幂等。design_tokens 不动（非 HTML，含 CSS 变量字面量）。
        """
        if not isinstance(suite, dict):
            return suite
        if not any(
            cls._BRAND_CODE_SLOT_RE.search(str(suite.get(k) or ""))
            for k in ("cover", "transition", "catalog", "ending", "header_footer")
        ):
            return suite
        updated = dict(suite)
        for k in ("cover", "transition", "catalog", "ending", "header_footer"):
            html = str(suite.get(k) or "")
            migrated = cls._migrate_brand_code_to_chapter(html, k)
            if migrated != html:
                updated[k] = migrated
        return updated

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

    # 标准内容舞台容器：度量、约束 prompt、LLM 视觉三方正此锚定。
    # 必须固定 px 边界（含安全间距）+ overflow:hidden 兜住溢出，使内容不覆盖
    # 页头分割线 / 页脚，并让 measure_content_overflow 能选对容器测出真实溢出。
    _STAGE_CLASS = "suite-stage"
    # 标准 top：≥ 页头底边 + 20px 安全间距。实测不同套件 header 底边差异大——
    # 套件 id=13 底 ~115px，id=15 底 ~135px（.suite-header top:60 + 内容高 + padding）。
    # 统一 top:155 保证绝大多数套件内容区不压页头分割线。
    _STAGE_TOP_MIN = 155
    _STAGE_BOTTOM_MIN = 60      # ≥ 页脚顶边
    _STAGE_LEFT_MAX = 1220      # ≤ 1280 - 60
    _STAGE_RIGHT_MIN = 60       # left ≥ 60
    _STANDARD_STAGE_CSS = (
        ".suite-stage{position:absolute;top:155px;left:60px;right:60px;"
        "bottom:60px;z-index:5;overflow:hidden}"
    )
    # 已知可识别为"内容区"的类名（含 suite 自由发挥的常见命名）
    # —— 仅作文档说明；实际匹配在 _ensure_standard_content_stage 里用局部正则。

    @classmethod
    def _strip_redundant_master_skeleton(cls, header_footer: str) -> str:
        """移除套件 header_footer 里多余的母版骨架注入块。

        当套件自带 suite- 前缀骨架（.suite-canvas/.suite-bg-paper 等）完整时，
        母版骨架块是 _ensure_header_footer_complete 旧正则（不识别 suite- 前缀）
        误判"缺骨架"后注入的 → 双骨架（body 里两个完整页面 = 上下两个完整页）。
        这里裁掉母版块（注释 + .canvas 装饰 div），保留套件自骨架。

        仅当套件确有 suite- 自骨架时才清理——避免误删 id=2/4 这类"母版骨架即套件骨架"的套件。
        """
        hf = header_footer or ""
        marker = "<!-- 母版内容页骨架"
        if marker not in hf:
            return hf
        # 仅当套件自带 suite- 前缀骨架才清理
        if not (
            "suite-canvas" in hf or "suite-bg-paper" in hf or "suite-frame-corner" in hf
        ):
            return hf
        m_start = hf.find(marker)
        if m_start == -1:
            return hf
        # 套件自骨架起点：母版块后的第一个 <style（套件 CSS）或 suite-canvas div
        cut = None
        for m in ("<style", '<div class="suite-canvas"'):
            idx = hf.find(m, m_start)
            if idx != -1 and (cut is None or idx < cut):
                cut = idx
        if cut and cut > m_start:
            return hf[:m_start] + hf[cut:]
        return hf

    @classmethod
    def _ensure_standard_content_stage(cls, header_footer: str, stage_top: Optional[int] = None) -> str:
        """A2：标准化套件内容区标识——保证 header_footer 含一个标准、可测量的
        正文舞台容器 `.suite-stage`，固定 px 边界、overflow:hidden 兜住溢出。

        三种情况统一收敛到 `.suite-stage`：
        1. 已有 `.suite-stage` 或 CSS 规则：校验 top，不足则覆盖；
        2. 有现成内容区 div（.page-content/.page-body/.main-stage 等）：
           追加 `suite-stage` class，并注入标准 CSS；
        3. 无内容区容器、`{{page_content}}` 散落：包一个新 `.suite-stage` div。

        stage_top：精确适配值（生成前按套件实测 header 底边得到）；None 用默认
        `_STAGE_TOP_MIN`（155）。top 不足时追加 `!important` 覆盖，不破坏原规则。
        """
        import re as _re

        if not header_footer:
            return header_footer
        hf = header_footer
        # 清理重复母版骨架注入：套件自骨架（suite- 前缀）已完整时，移除生成时误注入的
        # 母版 `.canvas` 骨架块（否则 body 里两个完整骨架 = 上下两个完整页）。
        hf = cls._strip_redundant_master_skeleton(hf)
        stage = cls._STAGE_CLASS
        target_top = stage_top if stage_top and stage_top > 0 else cls._STAGE_TOP_MIN
        stage_css = (
            f".{stage}{{position:absolute;top:{target_top}px;left:60px;right:60px;"
            f"bottom:60px;z-index:5;overflow:hidden}}"
        )

        has_rule = bool(_re.search(r'\.' + stage + r'\s*\{', hf))
        has_class = bool(
            f'"{stage}"' in hf or f"'{stage}'" in hf or f' {stage}"' in hf or f' {stage}\''
            in hf
        )

        if not has_rule or not has_class:
            # 情况 2：已有现成内容区 div → 追加 suite-stage class
            content_div_re = _re.compile(
                r'(<div\b[^>]*class=["\'])([^"\']*(?:page-content|page-body|main-stage|hf-stage|content-area|content-main|body-area|stage|canvas|slide-page|hf-canvas|slide)\b[^"\']*)(["\'])',
                _re.IGNORECASE,
            )
            m = content_div_re.search(hf)
            if m:
                old_classes = m.group(2)
                if stage not in old_classes.split():
                    new_classes = old_classes.rstrip() + (" " if old_classes.strip() else "") + stage
                    hf = hf[: m.start(1)] + m.group(1) + new_classes + m.group(3) + hf[m.end():]
            else:
                # 情况 3：无内容区容器 → 把 {{page_content}} 包进新 div
                if "{{ page_content }}" in hf or "{{page_content}}" in hf:
                    for token in ("{{ page_content }}", "{{page_content}}"):
                        if token in hf:
                            hf = hf.replace(token, f'<div class="{stage}">{token}</div>', 1)
                            break
                # 既无容器也无占位槽：只补 CSS（若缺），不破坏结构
            if not _re.search(r'\.' + stage + r'\s*\{', hf):
                # 注入标准边界 CSS
                if _re.search(r"<style[^>]*>", hf):
                    last_close = hf.rfind("</style>")
                    if last_close != -1:
                        hf = hf[:last_close] + stage_css + "\n" + hf[last_close:]
                else:
                    hf = hf + f"\n<style>{stage_css}</style>"

        # 统一末尾：确保 .suite-stage top ≥ target_top（不足则 !important 覆盖）。
        # 覆盖老套件/LLM 生成的过小 top（如 130px < header 底边 135px → 交叉）。
        if f"top:{target_top}px !important" not in hf:
            m_top = _re.search(r'\.' + stage + r'\s*\{\s*[^}]*?top\s*:\s*(\d+)px', hf)
            top_val = int(m_top.group(1)) if m_top else 0
            if top_val < target_top:
                last_close = hf.rfind("</style>")
                if last_close != -1:
                    hf = (
                        hf[:last_close]
                        + f".{stage}{{top:{target_top}px !important}}\n"
                        + hf[last_close:]
                    )
        return hf

    # 套件内容区 top 测量结果缓存（按 header_footer 内容哈希；套件不变不重复渲染）
    _stage_top_cache: Dict[str, int] = {}

    async def _measure_stage_top(self, suite: Dict[str, Any]) -> Optional[int]:
        """生成前测量套件 header 底边 → 该套件内容区 top 精确值（header_bottom + 20px 余量）。

        不同套件 header 结构差异大（实测 id=13 底 115px / id=15 底 135px / id=14 底 235px），
        固定值无法适配；按套件实测后，把该值用于①backfill 覆盖 .suite-stage top、②生成 prompt。
        Playwright 不可用/失败返回 None（调用方回退默认 stage top）。
        """
        import hashlib as _h
        import re as _re

        hf = str(suite.get("header_footer") or "")
        if not hf:
            return None
        key = _h.md5(hf.encode("utf-8")).hexdigest()
        cache = type(self)._stage_top_cache
        if key in cache:
            return cache[key]
        try:
            from ..pyppeteer_pdf_converter import get_pdf_converter, _loop_supports_subprocess
            if not _loop_supports_subprocess():
                return None
            converter = get_pdf_converter()
            if converter is None:
                return None
            import tempfile
            import os as _os
            import shutil as _sh

            # 代表性标题填充 {{page_title}}（空标题时 header 高度偏小）；品牌槽位已由调用方替换
            hf_filled = _re.sub(r"{{\s*page_title\s*}}", "部门工作情况汇报", hf)
            full = f"<!DOCTYPE html><html><head><meta charset='UTF-8'></head><body>{hf_filled}</body></html>"
            tmp = tempfile.mkdtemp(prefix="stage_top_")
            fp = _os.path.join(tmp, "s.html")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(full)
            try:
                await converter._get_or_create_browser()
                page = await converter.context.new_page()
                await page.set_viewport_size({"width": 1280, "height": 720})
                await page.goto(f"file://{_os.path.abspath(fp)}", wait_until="domcontentloaded")
                await converter._wait_for_fonts_and_resources(page, max_wait_time=3000)
                header_bottom = await page.evaluate(
                    """() => {
                        // 以 .suite-stage 当前 top 为基准，找其上方所有块状可见元素的最大底边。
                        // 覆盖各种 header 结构（header/.page-header/.suite-header 等，不依赖类名）；
                        // header 若已侵入 stage 区域（bottom > stageTop）也计入，表示冲突需下移。
                        const stage = document.querySelector('.suite-stage');
                        const stageTop = stage ? Math.round(stage.getBoundingClientRect().top) : 155;
                        const skip = /bg-|paper|grid|deco|corner|shadow|overlay|grain|ticks|stamp|accent|mark|dot|line|seal/;
                        let maxBottom = 0;
                        document.querySelectorAll('body *').forEach(function (el) {
                            const r = el.getBoundingClientRect();
                            // 排除装饰/小元素，也排除撑满整页的骨架容器（高度 >200 的是画布/背景层）
                            if (r.height < 6 || r.height > 200 || r.width < 100) return;
                            if (r.top >= stageTop - 2) return;   // 只在 stage 上方
                            if (r.bottom <= 0) return;
                            const cls = el.className && el.className.toString ? String(el.className) : '';
                            if (skip.test(cls)) return;          // 纯背景/装饰
                            if (r.bottom > maxBottom) maxBottom = r.bottom;
                        });
                        return maxBottom > 0 ? Math.round(maxBottom) : null;
                    }"""
                )
                await page.close()
                if not header_bottom or header_bottom <= 0:
                    return None
                stage_top = header_bottom + 20
                cache[key] = stage_top
                return stage_top
            finally:
                try:
                    _sh.rmtree(tmp, ignore_errors=True)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("测量套件内容区 top 失败（用默认值）: %s", exc)
            return None

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
            # 兼容前缀：套件骨架类名可能是 .canvas / .bg-paper（母版风格）或
            # .suite-canvas / .suite-bg-paper（现代 suite- 前缀）。旧正则只认无前缀
            # 导致把完整套件骨架误判为"缺骨架"，生成时重复注入母版骨架 → 双骨架。
            _re.search(r'\.[\w-]*(?:canvas|hf-canvas|bg-paper|bg-grid|frame-corner)\s*\{', hf)
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
        content = (content or "").split("</think>")[-1].strip()
        try:
            from summeryanyfile.core.json_parser import JSONParser
        except Exception:
            JSONParser = None

        if JSONParser is not None:
            # 复用健壮解析器：括号配对提取（正确跳过 HTML 内的引号/CSS 花括号）、
            # 容错清洗（代码块/前后缀/尾逗号/智能引号）、ast.literal_eval 兜底。
            candidates = [content]
            candidates.extend(JSONParser._extract_fenced_code_blocks(content))
            cleaned = JSONParser._clean_response(content)
            if cleaned:
                candidates.append(cleaned)
            candidates.extend(JSONParser._extract_json_candidates(content))
            seen = set()
            for candidate in candidates:
                candidate = candidate.strip()
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                parsed = JSONParser._loads_best_effort(candidate)
                if isinstance(parsed, dict):
                    return parsed
            return None

        # 兜底：原有简单逻辑（无 summeryanyfile 时）
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
        """Validate/normalize the LLM suite payload; raise on invalid cover/transition.

        catalog/ending are optional (older suites may lack them) but when present
        must be full HTML with their title slot.
        """
        cover = str(payload.get("cover") or "").strip()
        transition = str(payload.get("transition") or "").strip()
        catalog = str(payload.get("catalog") or "").strip()
        ending = str(payload.get("ending") or "").strip()
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
        if catalog and not catalog.lower().startswith("<!doctype html"):
            missing.append("catalog")
        if catalog and "catalog_title" not in catalog:
            missing.append("catalog缺少槽位 {{catalog_title}}")
        if ending and not ending.lower().startswith("<!doctype html"):
            missing.append("ending")
        if ending and "ending_title" not in ending:
            missing.append("ending缺少槽位 {{ending_title}}")
        for slot in ("page_title", "current_page_number", "total_page_count"):
            if slot not in header_footer:
                missing.append(f"header_footer缺少槽位 {{{{{slot}}}}}")

        if missing:
            raise ValueError("模板套件生成校验失败：" + "、".join(missing))

        return {
            "cover": cover,
            "transition": transition,
            "catalog": catalog,
            "ending": ending,
            "header_footer": header_footer,
            "design_tokens": design_tokens,
        }

    async def generate_suite(
        self,
        project_id: str,
        template: Optional[Dict[str, Any]] = None,
        force: bool = False,
        creativity: int = 0,
        reference_outline: bool = False,
        free: bool = False,
        custom_requirements: str = "",
        chapter_indicator: bool = False,
    ) -> Dict[str, Any]:
        """Generate (or refresh) a template suite for a project and persist it.

        creativity：0-10 刻度，0=严格遵循母版设计语言，10=最具创意。
        reference_outline：默认 False = 套件只基于母版模板生成，不绑定项目大纲/主题；
        为 True 时把项目主题/大纲/受众等信息传给模型。
        free=True：大纲智能套件——无需母版模板，直接根据项目大纲/主题设计一套套件。
        custom_requirements：用户自定义要求（如主题色/风格），设计时须遵循。
        chapter_indicator：True 时内容页 header_footer 生成 {{chapter_indicator}} 章节提示槽位。
        """
        template = template or {}
        html = (template.get("html_template") or "") if template else ""
        if not html.strip() and not free:
            raise ValueError("所选模板无 HTML 内容，无法生成套件")

        # 从项目加载上下文（大纲/确认需求），供可选 reference_outline 使用。
        project = await self.project_manager.get_project(project_id)
        if not project:
            raise ValueError(f"项目 {project_id} 不存在")

        suite = await self._generate_suite_payload(
            template,
            creativity=creativity,
            reference_outline=(reference_outline or free),
            project=project,
            allow_no_template=free,
            custom_requirements=custom_requirements,
            chapter_indicator=chapter_indicator,
        )
        if free:
            suite["template_mode"] = "outline"
            suite["template_name"] = "大纲智能套件"
            suite["template_id"] = None
            suite["template_hash"] = "outline-suite"

        await self._persist_suite(project_id, suite)
        self._clear_caches(project_id)
        logger.info(
            "Generated template suite for project %s (template=%s%s)",
            project_id,
            suite.get("template_name"),
            "，大纲模式" if free else "",
        )
        return suite

    async def _generate_suite_payload(
        self,
        template: Dict[str, Any],
        creativity: int = 0,
        reference_outline: bool = False,
        project: Any = None,
        allow_no_template: bool = False,
        custom_requirements: str = "",
        source_kind: str = "master",
        chapter_indicator: bool = False,
    ) -> Dict[str, Any]:
        """Generate a suite dict via one LLM call (no project persistence).

        Reused by both the per-project flow and the global suite library.
        creativity：0-10 刻度；reference_outline：为 True 时把项目主题/大纲传入模型。
        allow_no_template=True：无母版（大纲智能套件）——模型根据项目大纲/主题自行设计一套。
        custom_requirements：用户自定义要求（如主题色/风格），注入 prompt 让模型遵循。
        source_kind："master"=基于 PPT 母版（默认）；"web"=基于用户粘贴的网页 HTML；
        "reference_image"=基于视觉模型生成的参考图设计报告。后二者生成 header_footer 时
        传空 template_html 给 _ensure_header_footer_complete，避免把非母版内容注入页面骨架。
        chapter_indicator：True 时内容页 header_footer 生成 {{chapter_indicator}} 章节提示槽位。
        """
        template = template or {}
        html = (template.get("html_template") or "") if template else ""
        if not html.strip() and not allow_no_template:
            raise ValueError("所选模板无 HTML 内容，无法生成套件")

        _tpl_name = template.get("template_name") or f"#{template.get('id')}"
        _t0 = time.time()
        logger.info(
            "套件生成开始：模板=%s，创意度=%s，reference_outline=%s，chapter_indicator=%s",
            _tpl_name,
            creativity,
            reference_outline,
            chapter_indicator,
        )

        extracted = MasterLayoutExtractor.extract_header_footer(html)
        outline = (project.outline or {}) if project else {}
        confirmed = (project.confirmed_requirements or {}) if project else {}

        prompt = TemplatePrompts.build_template_suite_prompt(
            project=project,
            outline=outline,
            confirmed=confirmed,
            template_html=html,
            extracted_header_footer=extracted,
            creativity=creativity,
            reference_outline=reference_outline,
            custom_requirements=custom_requirements,
            source_kind=source_kind,
            chapter_indicator=chapter_indicator,
        )
        logger.info("套件提示词构建完成（%s 字符），开始调用 AI...", len(prompt))

        # max_output_tokens 显式放宽：套件一次输出 5 大段 HTML，模型默认输出上限
        # 可能不足以容纳完整 JSON，导致截断后无法解析（本项目 max_tokens 是分块参数，
        # 不能用；max_output_tokens 才是输出长度）。glm-5.3-flash 等强制思考模型的
        # max_tokens 是「推理+可见输出」总预算，预算需同时覆盖推理量与 JSON 本身。
        response = await self._text_completion_for_role(
            "template", prompt=prompt, temperature=0.7, max_output_tokens=_SUITE_AI_OUTPUT_BUDGET
        )
        raw = (response.content or "").strip()
        logger.info("套件 AI 调用完成，耗时 %.1fs，响应 %s 字符", time.time() - _t0, len(raw))
        if not raw:
            # 思考模型可能把输出预算全花在 <think> 上被截断，think 过滤后为 0 字符。
            logger.warning("套件 AI 返回空响应，发起免思考重试...")
            raw = await self._retry_suite_empty(prompt) or ""
            logger.info("套件 AI 免思考重试完成，耗时 %.1fs，响应 %s 字符", time.time() - _t0, len(raw))
        if not raw:
            raise ValueError("AI 服务返回空响应")

        payload = self._extract_json_from_response(raw)
        if not payload:
            logger.warning("套件 AI 响应无法解析为 JSON，发起一次修正重试（响应预览：%s）", raw[:200])
            payload = await self._repair_suite_json(prompt, raw)
            if payload:
                logger.info("套件 JSON 修正重试成功")
        if not payload:
            logger.error("套件 AI 响应最终无法解析为 JSON（响应预览：%s）", raw[:300])
            raise ValueError("AI 响应中未找到有效的套件 JSON")

        validated = self._validate_suite_payload(payload)
        logger.info("套件 AI 响应校验通过，执行页头页脚自包含修复...")

        identity = self._template_identity(template)
        header_footer = validated["header_footer"]
        # web / 参考图模式没有 PPT 母版骨架，传空 html 跳过骨架注入
        # （仍保留 :root 变量内联与 main-stage 兜底）。master 模式沿用原逻辑。
        hf_template_html = "" if source_kind in ("web", "reference_image") else html
        header_footer = self._ensure_header_footer_complete(
            header_footer, hf_template_html, extracted.get("root_variables") or ""
        )
        suite = {
            "cover": validated["cover"],
            "transition": validated["transition"],
            "catalog": validated.get("catalog") or "",
            "ending": validated.get("ending") or "",
            "header_footer": header_footer,
            "design_tokens": validated["design_tokens"],
            "template_hash": identity["template_hash"],
            "template_id": identity["template_id"],
            "template_name": identity["template_name"],
            "generated_at": time.time(),
        }
        logger.info("套件生成完成：模板=%s，总耗时 %.1fs", _tpl_name, time.time() - _t0)
        return suite

    async def _repair_suite_json(
        self,
        original_prompt: str,
        bad_raw: str,
    ) -> Optional[Dict[str, Any]]:
        """One corrective LLM call: re-emit the suite as strict JSON.

        Called when the first response couldn't be parsed (bad HTML escaping,
        prose wrapping, or truncation). The model gets its own earlier output and
        is asked to re-emit it as a valid, json.loads-able object.
        """
        repair_prompt = (
            "你之前为「PPT 模板套件」输出的内容不是有效的 JSON（可能因为 HTML 字符串里的引号/换行"
            "未正确转义，或内容被截断）。请把下面「你之前输出的内容」整理成严格 JSON 对象后重新输出：\n"
            "- 字段必须为：cover、transition、catalog、ending、header_footer、design_tokens"
            "（catalog/ending 可省略，缺失字段给空字符串）。\n"
            "- HTML 字符串内：双引号必须转义为 \\\"，换行必须写成 \\n，确保 json.loads 可直接解析。\n"
            "- 只输出 JSON 本身，不要 Markdown 代码块、不要任何解释。\n\n"
            "你之前输出的内容：\n"
            f"{bad_raw[:6000]}\n\n"
            "（若上方内容被截断，请基于字段结构补全必要部分；宁可保留未被截断的 HTML，"
            "也不要输出不完整 JSON。）"
        )
        try:
            response = await self._text_completion_for_role(
                "template", prompt=repair_prompt, temperature=0.2, max_output_tokens=_SUITE_AI_OUTPUT_BUDGET
            )
        except Exception as exc:
            logger.warning("套件 JSON 修正重试调用失败: %s", exc)
            return None
        return self._extract_json_from_response(response.content or "")

    async def _retry_suite_empty(self, prompt: str) -> Optional[str]:
        """Recover from an empty AI response caused by thinking-model truncation.

        MiniMax M 系列 / DeepSeek-R1 等思考模型可能把全部输出 token 花在
        <think>…</think> 思考过程上，未及输出可见 JSON 就被截断（finish_reason=length），
        随后 think 过滤把内容清空为 0 字符。重试时明确要求跳过思考、直接输出 JSON，
        并放宽输出上限，让可见 JSON 有足够空间。
        """
        retry_prompt = (
            prompt
            + "\n\n【重要】请直接输出上述要求的 JSON 结果：不要输出任何思考过程，"
            "不要输出 <think> 标签或解释文字，直接给出可被 json.loads 解析的 JSON 对象。"
        )
        try:
            response = await self._text_completion_for_role(
                "template", prompt=retry_prompt, temperature=0.2, max_output_tokens=_SUITE_AI_RETRY_OUTPUT_BUDGET
            )
        except Exception as exc:
            logger.warning("套件空响应重试调用失败: %s", exc)
            return None
        return (response.content or "").strip()

    _SUITE_PART_KEYS = ("cover", "transition", "catalog", "ending", "header_footer")

    async def regenerate_suite_part(
        self,
        project_id: str,
        part: str,
        template: Dict[str, Any],
        user_feedback: str = "",
        creativity: int = 0,
        reference_outline: bool = False,
        chapter_indicator: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Only regenerate one part (cover/transition/header_footer) of the suite.

        Loads the existing suite, calls the LLM to produce just `part`, merges it
        back while keeping every other part and design_tokens intact. Much cheaper
        than a full regeneration and keeps cross-part consistency.

        creativity：0-10 刻度，0=严格遵循母版设计语言，10=最具创意（仅 cover/transition 生效）。
        reference_outline：默认 False = 仅基于母版/现有套件，不绑定项目大纲/主题。
        chapter_indicator：None（默认）= 从现有 header_footer 是否含 {{chapter_indicator}}
        自推断（重新生成部分时保留章节提示状态）；bool 时显式指定。
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

        # 重新生成 header_footer 时保留章节提示状态：若既有 header_footer 含
        # {{chapter_indicator}} 槽位，则新生成的也应保留（不依赖前端传值）。
        if chapter_indicator is None:
            chapter_indicator = (
                part == "header_footer"
                and TemplateSuiteService.CHAPTER_INDICATOR_SLOT in str(existing.get("header_footer") or "")
            )

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
            creativity=creativity,
            reference_outline=reference_outline,
            chapter_indicator=bool(chapter_indicator),
        )

        response = await self._text_completion_for_role(
            "template", prompt=prompt, temperature=0.7, max_output_tokens=_SUITE_AI_OUTPUT_BUDGET
        )
        raw = (response.content or "").strip()
        if not raw:
            logger.warning("套件局部重生成 AI 返回空响应，发起免思考重试...")
            raw = await self._retry_suite_empty(prompt) or ""
        if not raw:
            raise ValueError("AI 服务返回空响应")

        payload = self._extract_json_from_response(raw)
        if not payload or part not in payload:
            raise ValueError(f"AI 响应中未找到新的 {part} 内容")

        new_value = str(payload.get(part) or "").strip()
        if not new_value:
            raise ValueError(f"新的 {part} 内容为空")

        # 对 cover/transition/catalog/ending 做完整 HTML 校验；header_footer 只需含页头页脚槽位。
        _full_pages = {"cover", "transition", "catalog", "ending"}
        if part in _full_pages:
            if not new_value.lower().startswith("<!doctype html"):
                raise ValueError(f"重新生成的 {part} 不是完整 HTML")
            title_slot = {
                "cover": "cover_title",
                "transition": "transition_title",
                "catalog": "catalog_title",
                "ending": "ending_title",
            }.get(part)
            if title_slot and title_slot not in new_value:
                raise ValueError(f"重新生成的 {part} 缺少槽位 {{{{{title_slot}}}}}")
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
        creativity: int = 0,
        chapter_indicator: Optional[bool] = None,
    ):
        """Stream single-type suite regeneration events, persisting on success.

        creativity：0-10 刻度，0=严格遵循母版设计语言，10=最具创意（仅 cover/transition 生效）。
        chapter_indicator：None=由 regenerate_suite_part 从现有 header_footer 自推断；bool=显式指定。
        """
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
                        project_id, part, template, user_feedback=user_feedback, creativity=creativity,
                        chapter_indicator=chapter_indicator,
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
        creativity: int = 0,
        free: bool = False,
        custom_requirements: str = "",
        chapter_indicator: bool = False,
    ):
        """Stream suite-generation events and persist the suite on success.

        creativity：0-10 刻度，0=严格遵循母版设计语言，10=最具创意。
        free=True：大纲智能套件——无需母版模板，直接根据项目大纲/主题设计一套。
        custom_requirements：用户自定义要求（如主题色/风格）。
        chapter_indicator：True 时内容页 header_footer 生成 {{chapter_indicator}} 章节提示槽位。
        """
        lock = self._template_suite_locks.setdefault(project_id, asyncio.Lock())
        if lock.locked():
            yield {"type": "status", "message": "已有套件生成任务正在进行，请稍候..."}

        async with lock:
            try:
                if free:
                    template = None
                else:
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

                if free:
                    yield {"type": "status", "message": "正在基于大纲内容智能生成套件（封面/过渡/目录/结尾/内容页头页脚）..."}
                else:
                    yield {"type": "status", "message": "正在基于母版风格生成套件（封面/过渡/内容页头页脚）..."}
                try:
                    suite = await self.generate_suite(
                        project_id, template, force=force, creativity=creativity,
                        free=free, custom_requirements=custom_requirements,
                        chapter_indicator=chapter_indicator,
                    )
                except Exception as exc:
                    logger.error("Template suite generation failed for project %s: %s", project_id, exc)
                    yield {"type": "error", "message": f"套件生成失败：{exc}"}
                    return

                yield {
                    "type": "complete",
                    "message": "模板套件生成完成！" if not free else "大纲智能套件生成完成！",
                    "suite": suite,
                    "template_name": suite.get("template_name"),
                }
            except Exception as exc:
                logger.error("Stream suite generation error for project %s: %s", project_id, exc)
                yield {"type": "error", "message": str(exc)}
