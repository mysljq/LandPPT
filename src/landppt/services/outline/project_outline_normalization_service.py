import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...api.models import PPTProject


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .project_outline_validation_service import ProjectOutlineValidationService


class ProjectOutlineNormalizationService:
    """统一处理大纲文本解析与结构标准化。"""

    _VALID_SLIDE_TYPES = {"title", "content", "agenda", "transition", "thankyou", "conclusion"}
    _SLIDE_TYPE_ALIASES = {
        "title": "title",
        "cover": "title",
        "intro": "title",
        "introduction": "title",
        "agenda": "agenda",
        "outline": "agenda",
        "catalog": "agenda",
        "directory": "agenda",
        "section": "agenda",
        "transition": "transition",
        "section_transition": "transition",
        "section_divider": "transition",
        "chapter_divider": "transition",
        "content": "content",
        "body": "content",
        "main": "content",
        "thankyou": "thankyou",
        "thanks": "thankyou",
        "thank_you": "thankyou",
        "end": "thankyou",
        "ending": "thankyou",
        "q&a": "thankyou",
        "qa": "thankyou",
        "conclusion": "conclusion",
        "summary": "conclusion",
        "closing": "conclusion",
        "final": "conclusion",
    }
    _TITLE_KEYWORDS = {
        "title": ("标题", "封面", "title", "cover"),
        "agenda": ("目录", "大纲", "agenda", "catalog", "outline", "direc6tory"),
        "transition": ("过渡", "转场", "transition", "section divider", "chapter divider"),
        "thankyou": ("谢谢", "感谢", "致谢", "thank", "q&a", "qa"),
        "conclusion": ("总结", "结论", "收尾", "summary", "conclusion"),
    }
    _JSON_VALUE_ENDINGS = {",", "}", "]", ":"}

    def __init__(self, service: "ProjectOutlineValidationService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @staticmethod
    def _strip_markdown_code_fence(content: str) -> str:
        """去掉包裹最外层的 Markdown 代码块。"""
        text = (content or "").strip()
        fenced_match = re.fullmatch(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", text)
        if fenced_match:
            return fenced_match.group(1).strip()
        return text

    @classmethod
    def _extract_first_balanced_json_block(cls, content: str) -> Optional[str]:
        """提取首个括号平衡的 JSON 对象或数组。"""
        text = (content or "").strip()
        for start_index, char in enumerate(text):
            if char not in "{[":
                continue
            candidate = cls._consume_balanced_json_block(text, start_index)
            if candidate:
                return candidate
        return None

    @staticmethod
    def _consume_balanced_json_block(content: str, start_index: int) -> Optional[str]:
        """在忽略字符串内部括号的前提下，截取平衡 JSON 片段。"""
        opening_char = content[start_index]
        closing_char = "}" if opening_char == "{" else "]"
        stack = [closing_char]
        in_string = False
        escaped = False

        for current_index in range(start_index + 1, len(content)):
            char = content[current_index]

            if escaped:
                escaped = False
                continue

            if in_string:
                if char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char in "{[":
                stack.append("}" if char == "{" else "]")
                continue

            if char in "}]":
                if not stack or char != stack[-1]:
                    return None
                stack.pop()
                if not stack:
                    return content[start_index:current_index + 1]

        return None

    @classmethod
    def _find_next_significant_char(cls, content: str, start_index: int) -> Optional[str]:
        for char in content[start_index:]:
            if not char.isspace():
                return char
        return None

    @classmethod
    def _escape_inner_quotes_in_json_strings(cls, content: str) -> str:
        """修复字符串值内部未转义的双引号，例如 `" "少样本"场景"`。"""
        if not content:
            return content

        result: List[str] = []
        in_string = False
        escaped = False
        pending_inner_quote = False

        for index, char in enumerate(content):
            if escaped:
                result.append(char)
                escaped = False
                continue

            if not in_string:
                result.append(char)
                if char == '"':
                    in_string = True
                    pending_inner_quote = False
                continue

            if char == "\\":
                result.append(char)
                escaped = True
                continue

            if char != '"':
                result.append(char)
                continue

            next_significant = cls._find_next_significant_char(content, index + 1)
            should_close_string = (
                not pending_inner_quote
                and (
                    next_significant is None
                    or next_significant in cls._JSON_VALUE_ENDINGS
                )
            )

            if should_close_string:
                result.append(char)
                in_string = False
                pending_inner_quote = False
                continue

            result.append('\\"')
            pending_inner_quote = not pending_inner_quote

        return "".join(result)

    @classmethod
    def _repair_json_candidate(cls, content: str) -> str:
        """修复常见的轻微 JSON 污损，避免直接退回兜底流程。"""
        text = (content or "").strip().lstrip("\ufeff")
        text = text.replace("“", '"').replace("”", '"')
        text = text.replace("‘", "'").replace("’", "'")
        text = re.sub(r",(?=\s*[}\]])", "", text)
        return cls._escape_inner_quotes_in_json_strings(text)

    @classmethod
    def _iter_json_candidates(cls, content: str) -> List[str]:
        """按可信度输出待解析候选串，优先复用原始结构。"""
        text = (content or "").strip()
        stripped_fence = cls._strip_markdown_code_fence(text)
        extracted_from_raw = cls._extract_first_balanced_json_block(text)
        extracted_from_stripped = cls._extract_first_balanced_json_block(stripped_fence)

        candidates: List[str] = []
        for candidate in [text, stripped_fence, extracted_from_raw, extracted_from_stripped]:
            candidate = (candidate or "").strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    @classmethod
    def _parse_json_like_outline(cls, content: str) -> Optional[Any]:
        """尝试把文本解析成 JSON/JSON-like 结构。"""
        for candidate in cls._iter_json_candidates(content):
            for payload in [candidate, cls._repair_json_candidate(candidate)]:
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
        return None

    @classmethod
    def _normalize_page_number(cls, raw_value: Any, fallback_value: int) -> int:
        try:
            parsed = int(str(raw_value).strip())
            return parsed if parsed > 0 else fallback_value
        except (TypeError, ValueError):
            return fallback_value

    @staticmethod
    def _flatten_text_values(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            result: List[str] = []
            for item in value:
                result.extend(ProjectOutlineNormalizationService._flatten_text_values(item))
            return result
        return [str(value)]

    @classmethod
    def _coerce_content_points(cls, slide: Dict[str, Any]) -> List[str]:
        """兼容不同字段名并转成标准要点数组。"""
        raw_points = (
            slide.get("content_points")
            if slide.get("content_points") is not None
            else slide.get("bullet_points")
        )
        if raw_points is None:
            raw_points = slide.get("points")
        if raw_points is None:
            raw_points = slide.get("key_points")
        if raw_points is None:
            raw_points = slide.get("outline_points")
        if raw_points is None:
            raw_points = slide.get("content")
        if raw_points is None:
            raw_points = slide.get("description")

        points: List[str] = []
        for raw_text in cls._flatten_text_values(raw_points):
            for line in re.split(r"\r?\n+", raw_text):
                text = line.strip()
                if not text:
                    continue
                text = re.sub(r"^[\-\*\u2022]+\s*", "", text)
                text = re.sub(r"^\d+[\.\)]\s*", "", text)
                if text:
                    points.append(text)
        return points

    @classmethod
    def _normalize_content_points_for_slide(
        cls,
        content_points: List[str],
        slide_type: str,
        page_number: int,
        total_slides: int,
        slide_title: str,
        description: str = "",
    ) -> List[str]:
        """清洗并补齐最小可用要点，避免后续结构校验被空数组卡住。"""
        cleaned_points = []
        for point in content_points or []:
            text = str(point).strip()
            if text:
                cleaned_points.append(text)

        if cleaned_points:
            return cleaned_points

        if description.strip():
            return [description.strip()]

        if slide_type == "title":
            return [slide_title.strip() or "演示主题"]
        if slide_type == "agenda":
            return ["本页为章节导航"]
        if slide_type == "transition":
            return [slide_title.strip() or "章节过渡"]
        if slide_type in {"thankyou", "conclusion"} or page_number == total_slides:
            return [slide_title.strip() or "总结与结束"]
        return [slide_title.strip() or "内容要点"]

    @classmethod
    def _normalize_slide_type(
        cls,
        raw_slide_type: Any,
        title_text: str,
        page_number: int,
        total_slides: int,
    ) -> str:
        normalized_raw_type = str(raw_slide_type or "").strip().lower().replace(" ", "_")
        normalized_raw_type = cls._SLIDE_TYPE_ALIASES.get(normalized_raw_type, normalized_raw_type)
        if normalized_raw_type in cls._VALID_SLIDE_TYPES:
            return normalized_raw_type

        title_lower = (title_text or "").strip().lower()
        for slide_type, keywords in cls._TITLE_KEYWORDS.items():
            if any(keyword in title_lower for keyword in keywords):
                return slide_type

        if page_number == 1:
            return "title"
        if page_number == total_slides and any(keyword in title_lower for keyword in ("thanks", "thank", "q&a", "qa")):
            return "thankyou"
        return "content"

    # ------------------------------------------------------------------
    # Transition slide type correction heuristics
    # ------------------------------------------------------------------
    _TRANSITION_DESCRIPTION_KEYWORDS: List[str] = [
        "章节过渡",
        "转场",
        "章节分隔",
        "过渡页",
        "transition",
        "section divider",
        "chapter divider",
        "section transition",
    ]

    @classmethod
    def _correct_transition_slide_types(cls, slides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Heuristic correction: slides whose description clearly indicates a
        transition page should have slide_type='transition' regardless of what
        the LLM originally labelled them."""

        for slide in slides:
            current_type = str(slide.get("slide_type") or "").strip().lower()
            if current_type != "content":
                continue

            description = str(slide.get("description") or "").strip().lower()
            if not description:
                continue

            if any(keyword in description for keyword in cls._TRANSITION_DESCRIPTION_KEYWORDS):
                slide["slide_type"] = "transition"
                slide["type"] = "transition"

        return slides

    # 章节编号前缀（一级章节标题）：中文数字/阿拉伯数字/第X章
    _CHAPTER_PREFIX_RE = re.compile(r"^\s*[一二三四五六七八九十百]+[、.．]\s*")
    _CHAPTER_NUM_PREFIX_RE = re.compile(r"^\s*\d{1,2}[、.．]\s*")
    _CHAPTER_CN_RE = re.compile(r"^\s*第[一二三四五六七八九十百\d]+\s*[章节部分篇]\s*[:：\-]?\s*")

    @classmethod
    def _extract_chapter_titles(cls, slides: List[Dict[str, Any]]) -> List[str]:
        """从第一个 agenda 页的 content_points 提取一级章节标题（带编号前缀，如"一、室组人员管理"）。

        缩进子项（如"   ZA38使用情况"）无编号前缀，不是一级章节，忽略。
        """
        for s in slides:
            if (s or {}).get("slide_type") != "agenda":
                continue
            titles = []
            for cp in (s.get("content_points") or []):
                t = str(cp).strip()
                if not t:
                    continue
                if (
                    cls._CHAPTER_PREFIX_RE.match(t)
                    or cls._CHAPTER_NUM_PREFIX_RE.match(t)
                    or cls._CHAPTER_CN_RE.match(t)
                ):
                    titles.append(t)
            if titles:
                return titles
        return []

    @classmethod
    def _strip_chapter_prefix(cls, title: str) -> str:
        """去掉一级章节标题的编号前缀，返回核心标题（如"一、室组人员管理"→"室组人员管理"）。"""
        t = (title or "").strip()
        t = cls._CHAPTER_PREFIX_RE.sub("", t)
        t = cls._CHAPTER_NUM_PREFIX_RE.sub("", t)
        t = cls._CHAPTER_CN_RE.sub("", t)
        return t.strip()

    @classmethod
    def _chapter_key_of_slide(
        cls,
        slide: Dict[str, Any],
        prev_out: Optional[Dict[str, Any]],
        chapter_titles: List[str],
    ) -> Optional[str]:
        """若该 content 页是"章节起始页"，返回它的章节 key；否则返回 None。

        三类信号：
        1. 标题自带章节编号前缀（一、/1、/第X章）；
        2. 标题匹配 agenda 一级章节标题核心（含"低代码方向"→"三、低代码方向"）；
        3. 从封面/目录等非内容页直接进入的第一个内容页（含第一章）。

        同一章节 key 只允许插入一次过渡页（同一章下的多个子页不重复插）。
        """
        if (slide or {}).get("slide_type") != "content":
            return None
        title = str(slide.get("title") or "").strip()
        if not title:
            return None

        # 1) 标题带章节编号前缀
        if (
            cls._CHAPTER_PREFIX_RE.match(title)
            or cls._CHAPTER_NUM_PREFIX_RE.match(title)
            or cls._CHAPTER_CN_RE.match(title)
        ):
            return cls._strip_chapter_prefix(title)

        # 2) 标题匹配 agenda 一级章节标题核心词
        for ct in chapter_titles:
            ct_core = cls._strip_chapter_prefix(ct)
            if len(ct_core) >= 3 and (ct_core in title or title in ct_core):
                return ct_core

        # 3) 封面/目录/结尾后进入的第一个内容页（含第一章）
        if prev_out and prev_out.get("slide_type") not in ("content", "transition"):
            return title

        return None

    @classmethod
    def _ensure_transition_slides(
        cls,
        slides: List[Dict[str, Any]],
        include_transition_pages: bool,
    ) -> List[Dict[str, Any]]:
        """开启过渡页时，保证每个一级章节（含第一章）前都有 transition 页。

        这是对 LLM 生成结果的确定性兜底：LLM prompt 已要求每章过渡，但仍可能
        遗漏第一章或部分章节。这里按章节起始信号补齐缺失的过渡页并重排页码。
        同一章节只补插一次（后续同章子页不重复插）。
        """
        if not include_transition_pages or not slides:
            return slides

        chapter_titles = cls._extract_chapter_titles(slides)
        out: List[Dict[str, Any]] = []
        last_chapter_key: Optional[str] = None
        for slide in slides:
            if (slide or {}).get("slide_type") == "content":
                prev_out = out[-1] if out else None
                key = cls._chapter_key_of_slide(slide, prev_out, chapter_titles)
                if key:
                    prev_is_transition = bool(prev_out and prev_out.get("slide_type") == "transition")
                    if key != last_chapter_key and not prev_is_transition:
                        title = str(slide.get("title") or "").strip() or f"第{len(out) + 1}页"
                        out.append({
                            "page_number": len(out) + 1,
                            "title": title,
                            "content_points": [title, "章节过渡 · 进入本部分"],
                            "slide_type": "transition",
                            "type": "transition",
                            "description": "章节过渡页（自动补齐）",
                        })
                    last_chapter_key = key
            new_slide = dict(slide)
            new_slide["page_number"] = len(out) + 1
            out.append(new_slide)
        return out

    @classmethod
    def _normalize_outline_root(cls, outline_data: Any) -> Dict[str, Any]:
        """兼容数组、嵌套 outline、pages 等多种根结构。"""
        if isinstance(outline_data, list):
            return {"slides": outline_data}

        if not isinstance(outline_data, dict):
            raise ValueError("大纲数据必须是对象或数组")

        root = dict(outline_data)
        nested_outline = root.get("outline")
        if isinstance(nested_outline, dict):
            merged = dict(nested_outline)
            for key, value in root.items():
                if key == "outline":
                    continue
                merged.setdefault(key, value)
            root = merged

        if "slides" not in root:
            if isinstance(root.get("pages"), list):
                root["slides"] = root["pages"]
            elif isinstance(root.get("sections"), list):
                root["slides"] = root["sections"]

        return root

    def _parse_text_outline_to_slides(self, content: str, project: PPTProject) -> List[Dict[str, Any]]:
        """仅在明确是文本大纲时才做按行解析，不再伪造默认页。"""
        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        if not lines:
            return []

        slides: List[Dict[str, Any]] = []
        current_slide: Optional[Dict[str, Any]] = None

        def flush_current_slide():
            if current_slide:
                slides.append(current_slide.copy())

        for raw_line in lines:
            is_slide_heading = (
                raw_line.startswith("#")
                or re.match(r"^第\s*\d+\s*[页章节]\s*[:：\-]?\s*", raw_line)
                or re.match(r"^page\s*\d+\s*[:：\-]?\s*", raw_line, flags=re.IGNORECASE)
                or re.match(r"^\d+[\.\)]\s+\S+", raw_line)
            )

            if is_slide_heading:
                flush_current_slide()
                title = re.sub(r"^#+\s*", "", raw_line)
                title = re.sub(r"^第\s*\d+\s*[页章节]\s*[:：\-]?\s*", "", title)
                title = re.sub(r"^page\s*\d+\s*[:：\-]?\s*", "", title, flags=re.IGNORECASE)
                title = re.sub(r"^\d+[\.\)]\s*", "", title)
                current_slide = {
                    "page_number": len(slides) + 1,
                    "title": title.strip() or f"第{len(slides) + 1}页",
                    "content_points": [],
                    "slide_type": "content",
                }
                continue

            if current_slide is None:
                continue

            point = re.sub(r"^[\-\*\u2022]+\s*", "", raw_line)
            point = re.sub(r"^\d+[\.\)]\s*", "", point)
            point = point.strip()
            if point:
                current_slide["content_points"].append(point)

        flush_current_slide()

        if not slides:
            return []

        return self._standardize_outline_format(
            {
                "title": getattr(project, "topic", "") or "PPT大纲",
                "slides": slides,
            }
        )["slides"]

    def _parse_outline_content(self, content: str, project: PPTProject) -> Dict[str, Any]:
        """从文本中解析大纲，不再退回默认三页兜底。"""
        parsed_outline = self._parse_json_like_outline(content)
        if parsed_outline is not None:
            standardized_data = self._standardize_outline_format(parsed_outline)
            logger.info(
                "成功解析结构化大纲，共 %s 页",
                len(standardized_data.get("slides", [])),
            )
            return standardized_data

        slides = self._parse_text_outline_to_slides(content, project)
        if slides:
            logger.info("成功按文本大纲解析，共 %s 页", len(slides))
            return {
                "title": getattr(project, "topic", "") or "PPT大纲",
                "slides": slides,
                "metadata": {},
            }

        raise ValueError("无法从输入内容中解析出有效的大纲结构")

    def _standardize_outline_format(self, outline_data: Dict[str, Any]) -> Dict[str, Any]:
        """标准化大纲结构，统一字段名与幻灯片类型。"""
        root = self._normalize_outline_root(outline_data)

        title = str(
            root.get("title")
            or root.get("topic")
            or root.get("name")
            or root.get("project_title")
            or "PPT大纲"
        ).strip() or "PPT大纲"

        slides_data = root.get("slides", [])
        if not isinstance(slides_data, list):
            raise ValueError("slides 字段必须是数组")
        if not slides_data:
            raise ValueError("slides 不能为空")

        metadata = root.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        standardized_slides: List[Dict[str, Any]] = []
        total_slides = len(slides_data)

        for index, slide in enumerate(slides_data, start=1):
            if not isinstance(slide, dict):
                slide = {"title": str(slide)}

            title_text = str(
                slide.get("title")
                or slide.get("page_title")
                or slide.get("name")
                or slide.get("heading")
                or f"第{index}页"
            ).strip() or f"第{index}页"

            description = str(slide.get("description") or "").strip()
            page_number = self._normalize_page_number(slide.get("page_number"), index)
            slide_type = self._normalize_slide_type(
                slide.get("slide_type", slide.get("type")),
                title_text,
                page_number,
                total_slides,
            )
            content_points = self._normalize_content_points_for_slide(
                content_points=self._coerce_content_points(slide),
                slide_type=slide_type,
                page_number=page_number,
                total_slides=total_slides,
                slide_title=title_text,
                description=description,
            )

            standardized_slide = {
                "page_number": index,
                "title": title_text,
                "content_points": content_points,
                "slide_type": slide_type,
                "type": slide_type,
                "description": description,
            }

            if slide.get("chart_config"):
                standardized_slide["chart_config"] = slide["chart_config"]

            standardized_slides.append(standardized_slide)

        # Apply transition type correction based on description heuristics
        standardized_slides = self._correct_transition_slide_types(standardized_slides)

        standardized_outline = {
            "title": title,
            "slides": standardized_slides,
            "metadata": metadata,
        }
        logger.info("大纲标准化完成：%s，共 %s 页", title, len(standardized_slides))
        return standardized_outline

    def _create_default_slides_from_content(self, content: str, project: PPTProject) -> List[Dict[str, Any]]:
        """保留旧接口名，但不再伪造默认页，只解析显式文本大纲。"""
        return self._parse_text_outline_to_slides(content, project)
