from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel


AgentEditMode = Literal["slide", "element"]

_MAX_CONVERSATION_HISTORY_MESSAGES = 10
_MAX_CONVERSATION_HISTORY_TOTAL_CHARS = 6000
_MAX_CONVERSATION_HISTORY_MESSAGE_CHARS = 1200

_AGENT_MIN_ITERATIONS = 2
_AGENT_MAX_ITERATIONS = 100
_AGENT_DEFAULT_ITERATIONS = 6
_MAX_PROMPT_SCRATCHPAD_ENTRIES = 20


class SlideEditAgentRequest(BaseModel):
    projectId: str
    slideIndex: int
    userRequest: str
    chatHistory: Optional[List[Dict[str, Any]]] = None
    mode: AgentEditMode = "slide"
    slideTitle: Optional[str] = None
    slideContent: Optional[str] = None
    slideOutline: Optional[Dict[str, Any]] = None
    projectInfo: Optional[Dict[str, Any]] = None
    selectedElementHtml: Optional[str] = None
    selectedElementId: Optional[str] = None
    slideScreenshot: Optional[str] = None
    elementScreenshot: Optional[str] = None
    images: Optional[List[Dict[str, Any]]] = None
    visionEnabled: bool = False
    maxIterations: Optional[int] = None


class SlideEditAgentApplyRequest(BaseModel):
    proposalId: str
    projectId: str
    slideIndex: int
    expectedBaseHash: str
    htmlContent: str
    slideData: Optional[Dict[str, Any]] = None


@dataclass
class SlideEditAction:
    thought: str
    action: str
    action_input: Dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""


@dataclass
class SlideEditValidationResult:
    valid: bool
    errors: List[str]
    warnings: List[str]
    sanitized_html: str


@dataclass
class SlideEditProposal:
    proposal_id: str
    base_hash: str
    summary: str
    changed_slide_indices: List[int]
    html_content: str
    validation: SlideEditValidationResult
    tool_transcript: List[Dict[str, Any]]
    slide_data: Dict[str, Any]
    created_at: float

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "proposalId": self.proposal_id,
            "baseHash": self.base_hash,
            "summary": self.summary,
            "changedSlideIndices": self.changed_slide_indices,
            "htmlContent": self.html_content,
            "validation": {
                "valid": self.validation.valid,
                "errors": self.validation.errors,
                "warnings": self.validation.warnings,
            },
            "toolTranscript": self.tool_transcript,
            "slideData": self.slide_data,
            "createdAt": self.created_at,
        }


def compute_slide_html_hash(html: str) -> str:
    normalized = (html or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def coerce_agent_max_iterations(raw_value: Any) -> int:
    try:
        if raw_value is not None:
            return max(
                _AGENT_MIN_ITERATIONS,
                min(_AGENT_MAX_ITERATIONS, int(raw_value)),
            )
    except (TypeError, ValueError):
        pass
    return _AGENT_DEFAULT_ITERATIONS


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    object_match = re.search(r"\{[\s\S]*\}", cleaned)
    if object_match:
        try:
            parsed = json.loads(object_match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def parse_agent_action(text: str) -> SlideEditAction:
    payload = _extract_json_payload(text or "")
    if not payload:
        summary = (text or "").strip() or "Agent returned an empty response."
        return SlideEditAction(
            thought="Model response was not structured; treating it as final summary.",
            action="final",
            action_input={"summary": summary},
            raw_response=text or "",
        )

    action_input = payload.get("action_input") or payload.get("input") or {}
    if not isinstance(action_input, dict):
        action_input = {"value": action_input}

    action_name = str(payload.get("action") or payload.get("tool") or "final")
    return SlideEditAction(
        thought=str(payload.get("thought") or payload.get("reasoning") or "").strip(),
        action=action_name.strip().lower().replace("-", "_"),
        action_input=action_input,
        raw_response=text or "",
    )


def strip_agent_ids(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(True):
        for attr in ("data-agent-id", "data-quick-ai-id"):
            if attr in node.attrs:
                del node.attrs[attr]
    return str(soup).strip()


def _attribute_value_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _attribute_value_scheme_text(value: Any) -> str:
    return re.sub(r"[\x00-\x20]+", "", _attribute_value_text(value)).lower()


def _has_javascript_attribute_value(soup: BeautifulSoup) -> bool:
    for node in soup.find_all(True):
        for value in getattr(node, "attrs", {}).values():
            if "javascript:" in _attribute_value_scheme_text(value):
                return True
    return False


def _has_srcdoc_attribute(soup: BeautifulSoup) -> bool:
    return any(
        attr.lower() == "srcdoc"
        for tag in soup.find_all(True)
        for attr in getattr(tag, "attrs", {})
    )


def sanitize_slide_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for script in soup.find_all("script"):
        script.decompose()

    for node in soup.find_all(True):
        for attr in list(getattr(node, "attrs", {}).keys()):
            attr_lower = (attr or "").lower()
            value = node.attrs.get(attr)
            if attr_lower.startswith("on"):
                del node.attrs[attr]
                continue
            if attr_lower == "srcdoc":
                del node.attrs[attr]
                continue
            if "javascript:" in _attribute_value_scheme_text(value):
                del node.attrs[attr]
                continue
            if attr_lower == "data-agent-id":
                del node.attrs[attr]

    return str(soup).strip()


class _SlideHtmlStructureParser(HTMLParser):
    _VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[str] = []
        self.errors: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag_name = tag.lower()
        if tag_name not in self._VOID_ELEMENTS:
            self.stack.append(tag_name)

    def handle_startendtag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in self._VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append("html is malformed")
            return
        if self.stack[-1] == tag_name:
            self.stack.pop()
            return
        self.errors.append("html is malformed")

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append("html is malformed")


def _find_html_structure_errors(html: str) -> List[str]:
    parser = _SlideHtmlStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ["html is malformed"]
    return list(dict.fromkeys(parser.errors))


def validate_slide_html(html: str) -> SlideEditValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    original = html or ""
    original_lower = original.lower()

    if not original.strip():
        errors.append("html content is required")
        return SlideEditValidationResult(False, errors, warnings, "")

    if "<script" in original_lower:
        errors.append("script tags are not allowed")

    original_soup = BeautifulSoup(original, "html.parser")
    if any(attr.lower().startswith("on") for tag in original_soup.find_all(True) for attr in tag.attrs):
        errors.append("inline event handlers are not allowed")

    if "javascript:" in original_lower or _has_javascript_attribute_value(original_soup):
        errors.append("javascript urls are not allowed")

    if _has_srcdoc_attribute(original_soup):
        errors.append("srcdoc attributes are not allowed")

    errors.extend(_find_html_structure_errors(original))

    sanitized = sanitize_slide_html(original)
    soup = BeautifulSoup(sanitized, "html.parser")
    if not soup.find(True):
        errors.append("html must contain at least one element")

    root_text = soup.get_text(" ", strip=True)
    has_media = bool(soup.find(["img", "svg", "canvas", "video", "picture"]))
    if not root_text and not has_media:
        warnings.append("slide has no visible text or media")

    return SlideEditValidationResult(
        valid=not errors,
        errors=list(dict.fromkeys(errors)),
        warnings=warnings,
        sanitized_html=sanitized,
    )


@dataclass
class SlideEditAgentContext:
    request: SlideEditAgentRequest
    project_id: str
    slide_index: int
    mode: AgentEditMode
    base_html: str
    base_hash: str
    slide_data: Dict[str, Any]
    project_info: Dict[str, Any]
    slide_outline: Dict[str, Any]
    selected_element_id: Optional[str] = None
    selected_element_html: Optional[str] = None

    @classmethod
    def from_request(cls, request: SlideEditAgentRequest) -> "SlideEditAgentContext":
        base_html = request.slideContent or ""
        slide_data = {
            "page_number": request.slideIndex,
            "title": request.slideTitle
            or (request.slideOutline or {}).get("title")
            or f"Slide {request.slideIndex}",
            "html_content": base_html,
            "slide_type": (request.slideOutline or {}).get("slide_type")
            or (request.slideOutline or {}).get("type")
            or "content",
            "content_points": (request.slideOutline or {}).get("content_points") or [],
            "metadata": {},
            "is_user_edited": True,
        }
        return cls(
            request=request,
            project_id=request.projectId,
            slide_index=request.slideIndex,
            mode=request.mode,
            base_html=base_html,
            base_hash=compute_slide_html_hash(base_html),
            slide_data=slide_data,
            project_info=request.projectInfo or {},
            slide_outline=request.slideOutline or {},
            selected_element_id=request.selectedElementId,
            selected_element_html=request.selectedElementHtml,
        )


class SlideEditToolRunner:
    _STYLE_WHITELIST = {
        "background",
        "background-color",
        "border",
        "border-radius",
        "box-shadow",
        "color",
        "display",
        "font-family",
        "font-size",
        "font-weight",
        "height",
        "left",
        "line-height",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-height",
        "max-width",
        "min-height",
        "min-width",
        "opacity",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "text-align",
        "top",
        "transform",
        "width",
        "z-index",
    }

    def __init__(self, context: SlideEditAgentContext):
        self.context = context
        self.current_html = context.base_html
        self.transcript: List[Dict[str, Any]] = []

    def available_tool_names(self) -> List[str]:
        return [
            "get_project_context",
            "get_slide",
            "list_slides",
            "inspect_slide_html",
            "select_elements",
            "replace_slide_html",
            "replace_element_html",
            "update_text",
            "update_style",
            "insert_element",
            "delete_element",
            "validate_slide_html",
            "preview_patch",
        ]

    async def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        normalized = (tool_name or "").strip().lower().replace("-", "_")
        data = tool_input if isinstance(tool_input, dict) else {"value": tool_input}

        handlers = {
            "get_project_context": self._tool_get_project_context,
            "get_slide": self._tool_get_slide,
            "list_slides": self._tool_list_slides,
            "inspect_slide_html": self._tool_inspect_slide_html,
            "select_elements": self._tool_select_elements,
            "replace_slide_html": self._tool_replace_slide_html,
            "replace_element_html": self._tool_replace_element_html,
            "update_text": self._tool_update_text,
            "update_style": self._tool_update_style,
            "insert_element": self._tool_insert_element,
            "delete_element": self._tool_delete_element,
            "validate_slide_html": self._tool_validate_slide_html,
            "preview_patch": self._tool_preview_patch,
        }
        handler = handlers.get(normalized)
        if not handler:
            return {
                "success": False,
                "tool": normalized,
                "error": f"Unsupported slide edit tool: {normalized}",
                "available_tools": self.available_tool_names(),
            }

        result = handler(data)
        self.transcript.append(
            {
                "tool": normalized,
                "input": data,
                "success": bool(result.get("success")),
                "summary": result.get("summary") or result.get("error") or "",
            }
        )
        return result

    def _soup(self) -> BeautifulSoup:
        return BeautifulSoup(self.current_html or "", "html.parser")

    def _set_html_from_soup(self, soup: BeautifulSoup) -> None:
        self.current_html = str(soup).strip()

    def _next_agent_element_id(self, soup: BeautifulSoup) -> str:
        max_index = 0
        for node in soup.find_all(attrs={"data-agent-id": True}):
            value = str(node.get("data-agent-id") or "")
            match = re.fullmatch(r"agent-el-(\d+)", value)
            if match:
                max_index = max(max_index, int(match.group(1)))
        return f"agent-el-{max_index + 1}"

    def _invalid_selector_error(
        self, tool_name: str, selector: str, error: Exception
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "tool": tool_name,
            "error": f"invalid selector: {selector}",
            "details": str(error),
        }

    def _validate_fragment_html(
        self, tool_name: str, html: Any, empty_error: str
    ) -> tuple[Optional[BeautifulSoup], Optional[Dict[str, Any]]]:
        fragment_html = str(html or "").strip()
        validation = validate_slide_html(fragment_html)
        if not validation.sanitized_html:
            return None, {"success": False, "tool": tool_name, "error": empty_error}
        if not validation.valid:
            return None, {
                "success": False,
                "tool": tool_name,
                "error": "fragment html failed validation",
                "errors": validation.errors,
            }
        fragment = BeautifulSoup(validation.sanitized_html, "html.parser")
        if not fragment.find(True):
            return None, {"success": False, "tool": tool_name, "error": empty_error}
        return fragment, None

    def _tool_get_project_context(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "get_project_context",
            "project": self.context.project_info,
            "slide_index": self.context.slide_index,
            "mode": self.context.mode,
            "outline": self.context.slide_outline,
            "summary": "Loaded project and outline context.",
        }

    def _tool_get_slide(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "get_slide",
            "slide": {**self.context.slide_data, "html_content": self.current_html},
            "base_hash": self.context.base_hash,
            "summary": f"Loaded slide {self.context.slide_index}.",
        }

    def _tool_list_slides(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "list_slides",
            "slides": [
                {
                    "slide_index": self.context.slide_index,
                    "title": self.context.slide_data.get("title"),
                    "slide_type": self.context.slide_data.get("slide_type"),
                }
            ],
            "summary": "Listed available slide summaries.",
        }

    def _tool_inspect_slide_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        headings = [
            {"selector": tag.name, "text": tag.get_text(" ", strip=True)}
            for tag in soup.find_all(["h1", "h2", "h3"])[:10]
        ]
        text_blocks = [
            {"selector": tag.name, "text": tag.get_text(" ", strip=True)[:300]}
            for tag in soup.find_all(["p", "li", "span", "div"])[:20]
            if tag.get_text(" ", strip=True)
        ]
        images = [
            {"src": img.get("src", ""), "alt": img.get("alt", "")}
            for img in soup.find_all("img")[:20]
        ]
        return {
            "success": True,
            "tool": "inspect_slide_html",
            "headings": headings,
            "text_blocks": text_blocks,
            "images": images,
            "summary": f"Found {len(headings)} headings, {len(text_blocks)} text blocks, and {len(images)} images.",
        }

    def _tool_select_elements(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        selector = str(tool_input.get("selector") or "").strip()
        text = str(tool_input.get("text") or "").strip().lower()
        soup = self._soup()
        matches = []
        try:
            candidates = soup.select(selector) if selector else soup.find_all(True)
        except Exception as exc:
            return self._invalid_selector_error("select_elements", selector, exc)
        for idx, node in enumerate(candidates[:100], start=1):
            node_text = node.get_text(" ", strip=True)
            if text and text not in node_text.lower():
                continue
            agent_id = node.get("data-agent-id") or self._next_agent_element_id(soup)
            node["data-agent-id"] = agent_id
            matches.append({"agent_id": agent_id, "tag": node.name, "text": node_text[:200]})
        self._set_html_from_soup(soup)
        return {
            "success": True,
            "tool": "select_elements",
            "matches": matches,
            "summary": f"Selected {len(matches)} elements.",
        }

    def _resolve_one(
        self, soup: BeautifulSoup, tool_input: Dict[str, Any], tool_name: str
    ) -> tuple[Any, Optional[Dict[str, Any]]]:
        selector = str(tool_input.get("selector") or "").strip()
        element_id = str(tool_input.get("element_id") or "").strip()
        if element_id:
            found = soup.find(attrs={"data-agent-id": element_id}) or soup.find(
                attrs={"data-quick-ai-id": element_id}
            )
            if found:
                return found, None
            return None, {
                "success": False,
                "tool": tool_name,
                "error": f'target element id "{element_id}" not found',
            }
        if selector:
            try:
                return soup.select_one(selector), None
            except Exception as exc:
                return None, self._invalid_selector_error(tool_name, selector, exc)
        fallback_element_id = str(self.context.selected_element_id or "").strip()
        if fallback_element_id:
            found = soup.find(attrs={"data-agent-id": fallback_element_id}) or soup.find(
                attrs={"data-quick-ai-id": fallback_element_id}
            )
            if found:
                return found, None
            return None, {
                "success": False,
                "tool": tool_name,
                "error": f'target element id "{fallback_element_id}" not found',
            }
        return None, {
            "success": False,
            "tool": tool_name,
            "error": "target element requires element_id, selected element id, or selector",
        }

    def _tool_replace_slide_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        html = str(tool_input.get("html") or tool_input.get("value") or "").strip()
        validation = validate_slide_html(html)
        if not validation.sanitized_html:
            return {
                "success": False,
                "tool": "replace_slide_html",
                "error": "replacement html is empty",
            }
        if not validation.valid:
            return {
                "success": False,
                "tool": "replace_slide_html",
                "errors": validation.errors,
                "summary": "Replacement slide HTML failed validation.",
            }
        self.current_html = validation.sanitized_html
        return {
            "success": True,
            "tool": "replace_slide_html",
            "errors": validation.errors,
            "summary": "Replaced full slide draft HTML.",
        }

    def _tool_replace_element_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target, error = self._resolve_one(soup, tool_input, "replace_element_html")
        if error:
            return error
        if not target:
            return {
                "success": False,
                "tool": "replace_element_html",
                "error": "target element not found",
            }
        fragment, error = self._validate_fragment_html(
            "replace_element_html",
            tool_input.get("html"),
            "replacement element html is empty",
        )
        if error:
            return error
        replacement = fragment.find(True)
        explicit_element_id = str(tool_input.get("element_id") or "").strip()
        target_agent_id = str(target.get("data-agent-id") or "").strip()
        target_quick_ai_id = str(target.get("data-quick-ai-id") or "").strip()
        if target_agent_id:
            replacement["data-agent-id"] = target_agent_id
        if explicit_element_id or target_quick_ai_id:
            replacement["data-quick-ai-id"] = explicit_element_id or target_quick_ai_id
        target.replace_with(replacement)
        self._set_html_from_soup(soup)
        return {
            "success": True,
            "tool": "replace_element_html",
            "summary": "Replaced selected element draft HTML.",
        }

    def _tool_update_text(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target, error = self._resolve_one(soup, tool_input, "update_text")
        if error:
            return error
        if not target:
            return {"success": False, "tool": "update_text", "error": "target element not found"}
        target.clear()
        target.append(str(tool_input.get("text") or ""))
        self._set_html_from_soup(soup)
        return {"success": True, "tool": "update_text", "summary": "Updated element text."}

    def _tool_update_style(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target, error = self._resolve_one(soup, tool_input, "update_style")
        if error:
            return error
        if not target:
            return {
                "success": False,
                "tool": "update_style",
                "error": "target element not found",
            }
        styles = tool_input.get("styles") if isinstance(tool_input.get("styles"), dict) else {}
        current_style = target.get("style", "")
        style_map: Dict[str, str] = {}
        for item in current_style.split(";"):
            if ":" in item:
                key, value = item.split(":", 1)
                style_map[key.strip().lower()] = value.strip()
        for key, value in styles.items():
            css_key = str(key).strip().lower()
            css_value = str(value).strip()
            if css_key in self._STYLE_WHITELIST and css_value and "url(" not in css_value.lower():
                style_map[css_key] = css_value
        target["style"] = "; ".join(f"{key}: {value}" for key, value in style_map.items())
        self._set_html_from_soup(soup)
        return {
            "success": True,
            "tool": "update_style",
            "summary": "Updated whitelisted element styles.",
        }

    def _tool_insert_element(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        parent_selector = str(tool_input.get("parent_selector") or "").strip()
        element_id = str(tool_input.get("element_id") or "").strip()
        if not parent_selector and not element_id:
            return {
                "success": False,
                "tool": "insert_element",
                "error": "insert_element requires parent_selector or element_id",
            }
        if element_id:
            parent = soup.find(attrs={"data-agent-id": element_id}) or soup.find(
                attrs={"data-quick-ai-id": element_id}
            )
            if not parent:
                return {
                    "success": False,
                    "tool": "insert_element",
                    "error": f'target element id "{element_id}" not found',
                }
        else:
            try:
                parent = soup.select_one(parent_selector)
            except Exception as exc:
                return self._invalid_selector_error("insert_element", parent_selector, exc)
        fragment, error = self._validate_fragment_html(
            "insert_element",
            tool_input.get("html"),
            "parent or inserted element not found",
        )
        if error:
            return error
        node = fragment.find(True)
        if not parent or not node:
            return {
                "success": False,
                "tool": "insert_element",
                "error": "parent or inserted element not found",
            }
        parent.append(node)
        self._set_html_from_soup(soup)
        return {"success": True, "tool": "insert_element", "summary": "Inserted element into draft."}

    def _tool_delete_element(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target, error = self._resolve_one(soup, tool_input, "delete_element")
        if error:
            return error
        if not target:
            return {"success": False, "tool": "delete_element", "error": "target element not found"}
        target.decompose()
        self._set_html_from_soup(soup)
        return {"success": True, "tool": "delete_element", "summary": "Deleted element from draft."}

    def _tool_validate_slide_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        validation = validate_slide_html(self.current_html)
        return {
            "success": validation.valid,
            "tool": "validate_slide_html",
            "errors": validation.errors,
            "warnings": validation.warnings,
            "summary": "Validated draft HTML.",
        }

    def _tool_preview_patch(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "preview_patch",
            "base_hash": self.context.base_hash,
            "new_hash": compute_slide_html_hash(self.current_html),
            "changed": compute_slide_html_hash(self.current_html) != self.context.base_hash,
            "summary": "Prepared before/after patch preview.",
        }

    def build_proposal(
        self, summary: str, changed_slide_indices: Optional[List[int]] = None
    ) -> SlideEditProposal:
        cleaned_html = strip_agent_ids(self.current_html)
        validation = validate_slide_html(cleaned_html)
        slide_data = {
            **self.context.slide_data,
            "html_content": validation.sanitized_html,
            "is_user_edited": True,
        }
        return SlideEditProposal(
            proposal_id=f"slide-edit-{uuid.uuid4().hex}",
            base_hash=self.context.base_hash,
            summary=summary or "Prepared slide edit proposal.",
            changed_slide_indices=changed_slide_indices or [self.context.slide_index],
            html_content=validation.sanitized_html,
            validation=validation,
            tool_transcript=list(self.transcript),
            slide_data=slide_data,
            created_at=time.time(),
        )


EventEmitter = Callable[[Dict[str, Any]], Awaitable[None]]


class SlideEditAgentService:
    async def _emit(
        self, event_callback: Optional[EventEmitter], event: Dict[str, Any]
    ) -> None:
        if event_callback:
            await event_callback(event)

    async def run_agent(
        self,
        request: SlideEditAgentRequest,
        user_ppt_service: Any,
        event_callback: Optional[EventEmitter] = None,
    ) -> SlideEditProposal:
        context = SlideEditAgentContext.from_request(request)
        runner = SlideEditToolRunner(context)
        max_iterations = coerce_agent_max_iterations(request.maxIterations)
        role = (
            "vision_analysis"
            if request.visionEnabled
            and (request.slideScreenshot or request.elementScreenshot or request.images)
            else "editor"
        )

        await self._emit(
            event_callback,
            {
                "type": "agent_start",
                "projectId": request.projectId,
                "slideIndex": request.slideIndex,
                "mode": request.mode,
                "maxIterations": max_iterations,
                "tools": runner.available_tool_names(),
            },
        )

        try:
            return await self._run_native_tool_iteration(
                request,
                user_ppt_service,
                runner,
                role,
                max_iterations,
                event_callback,
            )
        except Exception as exc:
            if getattr(exc, "_slide_edit_error_emitted", False):
                raise
            if self._is_native_tool_protocol_error(exc):
                await self._emit(
                    event_callback,
                    {
                        "type": "agent_fallback",
                        "reason": str(exc) or exc.__class__.__name__,
                    },
                )
                # Restart from the base slide so any partial native-loop edits
                # are not silently re-applied on top of themselves.
                runner = SlideEditToolRunner(context)
            else:
                await self._emit_error(
                    event_callback,
                    exc,
                    phase="model",
                    iteration=1,
                )
                raise

        scratchpad: List[Dict[str, Any]] = []
        executed_tool = False
        for iteration in range(1, max_iterations + 1):
            try:
                prompt = self._build_prompt(request, runner, scratchpad, max_iterations)
                response = await user_ppt_service._chat_completion_for_role(
                    role,
                    messages=self._build_messages(request, prompt),
                )
                content = str(getattr(response, "content", "") or "")
                action = parse_agent_action(content)
            except Exception as exc:
                await self._emit_error(
                    event_callback,
                    exc,
                    phase="model",
                    iteration=iteration,
                )
                raise

            if (
                action.action == "final"
                and not executed_tool
                and not self._is_structured_agent_action(content)
                and iteration < max_iterations
            ):
                scratchpad.append(
                    {
                        "iteration": iteration,
                        "error": (
                            "Response was not a valid JSON action. Return strict JSON "
                            'with "thought", "action", and "action_input".'
                        ),
                        "response": content[:500],
                    }
                )
                continue

            await self._emit(
                event_callback,
                {
                    "type": "agent_step",
                    "iteration": iteration,
                    "thought": action.thought,
                    "action": action.action,
                    "actionInput": action.action_input,
                },
            )

            if action.action == "final":
                summary = str(
                    action.action_input.get("summary")
                    or action.thought
                    or "Prepared slide edit proposal."
                )
                proposal = runner.build_proposal(summary)
                await self._emit_validation_and_draft(event_callback, proposal)
                return proposal

            await self._emit(
                event_callback,
                {
                    "type": "tool_call",
                    "iteration": iteration,
                    "tool": action.action,
                    "toolInput": action.action_input,
                    "thought": action.thought,
                },
            )
            try:
                observation = await runner.execute_tool(
                    action.action, action.action_input
                )
            except Exception as exc:
                await self._emit_error(
                    event_callback,
                    exc,
                    phase="tool",
                    iteration=iteration,
                    tool=action.action,
                )
                raise
            await self._emit(
                event_callback,
                {
                    "type": "tool_result",
                    "iteration": iteration,
                    "tool": action.action,
                    "success": observation.get("success", False),
                    "observation": observation,
                },
            )
            executed_tool = True
            scratchpad.append(
                {
                    "iteration": iteration,
                    "thought": action.thought,
                    "action": action.action,
                    "action_input": action.action_input,
                    "observation": self._compact_observation(observation),
                }
            )

        proposal = runner.build_proposal(
            "Reached the maximum edit iterations and prepared the current draft."
        )
        await self._emit_validation_and_draft(event_callback, proposal)
        return proposal

    async def _run_native_tool_iteration(
        self,
        request: SlideEditAgentRequest,
        user_ppt_service: Any,
        runner: SlideEditToolRunner,
        role: str,
        max_iterations: int,
        event_callback: Optional[EventEmitter],
    ) -> Optional[SlideEditProposal]:
        messages = self._build_native_messages(request, runner)
        tools = self._openai_tool_schemas(runner)
        executed_native_or_text_tool = False

        for iteration in range(1, max_iterations + 1):
            response = await user_ppt_service._chat_completion_for_role(
                role,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
            )
            tool_calls = list(getattr(response, "tool_calls", None) or [])
            content = str(getattr(response, "content", "") or "")

            if not tool_calls:
                text_action = parse_agent_action(content)
                if (
                    not executed_native_or_text_tool
                    and text_action.action == "final"
                    and not self._is_structured_agent_action(content)
                ):
                    raise RuntimeError("Provider did not return native tool_calls for the slide edit agent")
                await self._emit(
                    event_callback,
                    {
                        "type": "agent_step",
                        "iteration": iteration,
                        "thought": text_action.thought,
                        "action": text_action.action,
                        "actionInput": text_action.action_input,
                    },
                )
                if text_action.action != "final":
                    messages.append(
                        self._ai_message(
                            "assistant",
                            content,
                        )
                    )
                    observation = await self._execute_agent_action(
                        event_callback,
                        runner,
                        iteration,
                        text_action.thought,
                        text_action.action,
                        text_action.action_input,
                    )
                    executed_native_or_text_tool = True
                    messages.append(
                        self._ai_message(
                            "user",
                            "Tool result:\n"
                            + json.dumps(self._compact_observation(observation), ensure_ascii=False),
                        )
                    )
                    continue
                summary = content.strip() or "Prepared slide edit proposal."
                if text_action.action == "final":
                    summary = str(
                        text_action.action_input.get("summary")
                        or text_action.thought
                        or summary
                    )
                proposal = runner.build_proposal(summary)
                await self._emit_validation_and_draft(event_callback, proposal)
                return proposal

            messages.append(
                self._ai_message(
                    "assistant",
                    content,
                    tool_calls=tool_calls,
                )
            )

            for call in tool_calls:
                tool_name, tool_input = self._tool_call_name_and_input(call)
                observation = await self._execute_agent_action(
                    event_callback,
                    runner,
                    iteration,
                    content,
                    tool_name,
                    tool_input,
                )
                executed_native_or_text_tool = True
                messages.append(
                    self._ai_message(
                        "tool",
                        json.dumps(self._compact_observation(observation), ensure_ascii=False),
                        tool_call_id=str(call.get("id") or ""),
                    )
                )

        proposal = runner.build_proposal(
            "Reached the maximum edit iterations and prepared the current draft."
        )
        await self._emit_validation_and_draft(event_callback, proposal)
        return proposal

    async def _execute_agent_action(
        self,
        event_callback: Optional[EventEmitter],
        runner: SlideEditToolRunner,
        iteration: int,
        thought: str,
        action: str,
        action_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        await self._emit(
            event_callback,
            {
                "type": "tool_call",
                "iteration": iteration,
                "tool": action,
                "toolInput": action_input,
                "thought": thought,
            },
        )
        try:
            observation = await runner.execute_tool(action, action_input)
        except Exception as exc:
            await self._emit_error(
                event_callback,
                exc,
                phase="tool",
                iteration=iteration,
                tool=action,
            )
            setattr(exc, "_slide_edit_error_emitted", True)
            raise
        await self._emit(
            event_callback,
            {
                "type": "tool_result",
                "iteration": iteration,
                "tool": action,
                "success": observation.get("success", False),
                "observation": observation,
            },
        )
        return observation

    def _tool_call_name_and_input(self, call: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        function = call.get("function") or {}
        tool_name = str(function.get("name") or call.get("name") or "").strip()
        raw_arguments = function.get("arguments") if "arguments" in function else call.get("arguments")
        if isinstance(raw_arguments, dict):
            return tool_name, raw_arguments
        try:
            parsed = json.loads(str(raw_arguments or "{}"))
        except json.JSONDecodeError:
            parsed = {}
        return tool_name, parsed if isinstance(parsed, dict) else {}

    def _ai_message(
        self,
        role: str,
        content: Any,
        *,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ):
        from ...ai import AIMessage, MessageRole

        role_map = {
            "system": MessageRole.SYSTEM,
            "user": MessageRole.USER,
            "assistant": MessageRole.ASSISTANT,
            "tool": MessageRole.TOOL,
        }
        return AIMessage(
            role=role_map.get(role, MessageRole.USER),
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )

    def _build_native_messages(self, request: SlideEditAgentRequest, runner: SlideEditToolRunner) -> List[Any]:
        context = {
            "project": request.projectInfo or {},
            "slide_index": request.slideIndex,
            "slide_title": request.slideTitle,
            "slide_outline": request.slideOutline or {},
            "mode": request.mode,
            "selected_element_id": request.selectedElementId,
            "selected_element_html": request.selectedElementHtml,
            "conversation_history": self._conversation_history_context(request),
            "current_html": runner.current_html,
            "vision": self._vision_context(request),
            "max_iterations": coerce_agent_max_iterations(request.maxIterations),
        }
        prompt = (
            "Edit this PPT slide by calling the provided tools. Use tool calls for inspection and edits. "
            "When the draft is ready, respond with a concise summary and no tool calls.\n\n"
            f"Latest user request: {request.userRequest}\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )
        messages = [
            self._ai_message(
                "system",
                "You are LandPPT's slide editing agent. Use the provided tools to inspect and edit slides.",
            )
        ]
        vision_urls = self._vision_image_urls(request)
        if request.visionEnabled and vision_urls:
            from ...ai.base import ImageContent, TextContent

            user_content = [TextContent(text=prompt)]
            user_content.extend(ImageContent(image_url={"url": url}) for url in vision_urls)
            messages.append(self._ai_message("user", user_content))
        else:
            messages.append(self._ai_message("user", prompt))
        return messages

    def _is_native_tool_protocol_error(self, error: Exception) -> bool:
        message = (str(error) or error.__class__.__name__).lower()
        markers = (
            "tools",
            "tool_choice",
            "tool calls",
            "tool_calls",
            "function calling",
            "unsupported parameter",
            "unknown parameter",
            "unrecognized request argument",
        )
        return any(marker in message for marker in markers)

    def _is_structured_agent_action(self, content: str) -> bool:
        payload = _extract_json_payload(content or "")
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("action") or payload.get("tool"))

    def _build_messages(self, request: SlideEditAgentRequest, prompt: str) -> List[Any]:
        messages = [
            self._ai_message(
                "system",
                "You are LandPPT's slide editing agent. Return one JSON action per turn.",
            )
        ]
        vision_urls = self._vision_image_urls(request)
        if request.visionEnabled and vision_urls:
            from ...ai.base import ImageContent, TextContent

            user_content = [TextContent(text=prompt)]
            user_content.extend(
                ImageContent(image_url={"url": url}) for url in vision_urls
            )
            messages.append(self._ai_message("user", user_content))
        else:
            messages.append(self._ai_message("user", prompt))
        return messages

    async def _emit_validation_and_draft(
        self, event_callback: Optional[EventEmitter], proposal: SlideEditProposal
    ) -> None:
        await self._emit(
            event_callback,
            {
                "type": "validation_result",
                "valid": proposal.validation.valid,
                "errors": proposal.validation.errors,
                "warnings": proposal.validation.warnings,
            },
        )
        await self._emit(
            event_callback,
            {"type": "draft_ready", "proposal": proposal.to_public_dict()},
        )
        await self._emit(
            event_callback,
            {
                "type": "needs_confirmation",
                "proposalId": proposal.proposal_id,
                "message": "Review the draft before applying it.",
            },
        )

    async def _emit_error(
        self,
        event_callback: Optional[EventEmitter],
        error: Exception,
        *,
        phase: str,
        iteration: Optional[int] = None,
        tool: Optional[str] = None,
    ) -> None:
        event: Dict[str, Any] = {
            "type": "error",
            "phase": phase,
            "message": str(error) or error.__class__.__name__,
            "errorType": error.__class__.__name__,
        }
        if iteration is not None:
            event["iteration"] = iteration
        if tool:
            event["tool"] = tool
        await self._emit(event_callback, event)

    def _build_prompt(
        self,
        request: SlideEditAgentRequest,
        runner: SlideEditToolRunner,
        scratchpad: List[Dict[str, Any]],
        max_iterations: int,
    ) -> str:
        context = {
            "project": request.projectInfo or {},
            "slide_index": request.slideIndex,
            "slide_title": request.slideTitle,
            "slide_outline": request.slideOutline or {},
            "mode": request.mode,
            "selected_element_id": request.selectedElementId,
            "selected_element_html": request.selectedElementHtml,
            "user_request": request.userRequest,
            "conversation_history": self._conversation_history_context(request),
            "current_html": runner.current_html,
            "vision": self._vision_context(request),
            "available_tools": self._tool_schemas(runner),
            "scratchpad": self._prompt_scratchpad(scratchpad),
            "max_iterations": max_iterations,
        }
        return (
            "Use a ReAct loop to edit this PPT slide. Choose exactly one action. "
            "Use conversation_history for continuity, but execute the latest "
            "user_request. Use final when the draft is ready. Return strict JSON only.\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )

    def _prompt_scratchpad(
        self, scratchpad: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if len(scratchpad) <= _MAX_PROMPT_SCRATCHPAD_ENTRIES:
            return scratchpad
        omitted = len(scratchpad) - _MAX_PROMPT_SCRATCHPAD_ENTRIES
        return [
            {"note": f"{omitted} earlier scratchpad entries omitted to bound prompt size."}
        ] + scratchpad[-_MAX_PROMPT_SCRATCHPAD_ENTRIES:]

    def _conversation_history_context(
        self, request: SlideEditAgentRequest
    ) -> List[Dict[str, str]]:
        cleaned: List[Dict[str, str]] = []
        total_chars = 0

        for item in reversed(request.chatHistory or []):
            if len(cleaned) >= _MAX_CONVERSATION_HISTORY_MESSAGES:
                break
            if not isinstance(item, dict):
                continue

            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue

            content = str(item.get("content") or "").strip()
            if not content:
                continue

            remaining_chars = _MAX_CONVERSATION_HISTORY_TOTAL_CHARS - total_chars
            if remaining_chars <= 0:
                break

            max_chars = min(
                remaining_chars,
                _MAX_CONVERSATION_HISTORY_MESSAGE_CHARS,
            )
            content = self._truncate_history_content(content, max_chars)
            if not content:
                continue

            cleaned.append({"role": role, "content": content})
            total_chars += len(content)

        cleaned.reverse()
        return cleaned

    @staticmethod
    def _truncate_history_content(content: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        if len(content) <= max_chars:
            return content
        if max_chars <= 3:
            return content[:max_chars]
        return content[: max_chars - 3].rstrip() + "..."

    def _vision_context(self, request: SlideEditAgentRequest) -> Dict[str, Any]:
        attachments: List[Dict[str, Any]] = []
        if request.slideScreenshot:
            attachments.append(
                {
                    "source": "slide_screenshot",
                    "attached": request.visionEnabled,
                    "url": self._prompt_safe_image_url(request.slideScreenshot),
                }
            )
        if request.elementScreenshot:
            attachments.append(
                {
                    "source": "element_screenshot",
                    "attached": request.visionEnabled,
                    "url": self._prompt_safe_image_url(request.elementScreenshot),
                }
            )
        for index, image in enumerate(request.images or [], start=1):
            if not isinstance(image, dict):
                continue
            url = str(image.get("url") or "")
            attachments.append(
                {
                    "source": f"reference_image_{index}",
                    "name": image.get("name"),
                    "size": image.get("size"),
                    "attached": bool(request.visionEnabled and url),
                    "url": self._prompt_safe_image_url(url),
                }
            )

        return {
            "enabled": request.visionEnabled,
            "uses_vision_model": bool(
                request.visionEnabled and self._vision_image_urls(request)
            ),
            "attached_image_count": (
                len(self._vision_image_urls(request)) if request.visionEnabled else 0
            ),
            "attachments": attachments,
            "instruction": (
                "When vision attachments are present, inspect them for visual layout, "
                "text, color, spacing, and selected-element context before choosing an action."
            ),
        }

    def _vision_image_urls(self, request: SlideEditAgentRequest) -> List[str]:
        urls = [
            str(url)
            for url in (request.slideScreenshot, request.elementScreenshot)
            if url
        ]
        for image in request.images or []:
            if not isinstance(image, dict):
                continue
            url = image.get("url")
            if url:
                urls.append(str(url))
        return urls

    def _prompt_safe_image_url(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("data:image"):
            return "[attached data URL omitted from text prompt]"
        return url

    def _tool_schemas(self, runner: SlideEditToolRunner) -> List[Dict[str, Any]]:
        schema_by_name = {
            "get_project_context": {"name": "get_project_context", "input": {}},
            "get_slide": {"name": "get_slide", "input": {"slide_index": "integer"}},
            "list_slides": {"name": "list_slides", "input": {}},
            "inspect_slide_html": {
                "name": "inspect_slide_html",
                "input": {"slide_index": "integer"},
            },
            "select_elements": {
                "name": "select_elements",
                "input": {"selector": "string", "text": "string"},
            },
            "replace_slide_html": {
                "name": "replace_slide_html",
                "input": {"html": "string"},
            },
            "replace_element_html": {
                "name": "replace_element_html",
                "input": {"element_id": "string", "html": "string"},
            },
            "update_text": {
                "name": "update_text",
                "input": {
                    "selector": "string",
                    "element_id": "string",
                    "text": "string",
                },
            },
            "update_style": {
                "name": "update_style",
                "input": {
                    "selector": "string",
                    "element_id": "string",
                    "styles": "object",
                },
            },
            "insert_element": {
                "name": "insert_element",
                "input": {"parent_selector": "string", "html": "string"},
            },
            "delete_element": {
                "name": "delete_element",
                "input": {"selector": "string", "element_id": "string"},
            },
            "validate_slide_html": {"name": "validate_slide_html", "input": {}},
            "preview_patch": {"name": "preview_patch", "input": {}},
        }
        tool_names = runner.available_tool_names()
        missing = [name for name in tool_names if name not in schema_by_name]
        if missing:
            raise ValueError(f"Missing slide edit tool schemas: {', '.join(missing)}")
        return [schema_by_name[name] for name in tool_names]

    def _openai_tool_schemas(self, runner: SlideEditToolRunner) -> List[Dict[str, Any]]:
        def object_schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
            schema: Dict[str, Any] = {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            }
            if required:
                schema["required"] = required
            return schema

        string = {"type": "string"}
        integer = {"type": "integer"}
        schema_by_name = {
            "get_project_context": object_schema({}),
            "get_slide": object_schema({"slide_index": integer}),
            "list_slides": object_schema({}),
            "inspect_slide_html": object_schema({"slide_index": integer}),
            "select_elements": object_schema({"selector": string, "text": string}),
            "replace_slide_html": object_schema({"html": string}, ["html"]),
            "replace_element_html": object_schema({"element_id": string, "html": string}, ["html"]),
            "update_text": object_schema({"selector": string, "element_id": string, "text": string}, ["text"]),
            "update_style": object_schema(
                {
                    "selector": string,
                    "element_id": string,
                    "styles": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                ["styles"],
            ),
            "insert_element": object_schema(
                {"parent_selector": string, "element_id": string, "html": string},
                ["html"],
            ),
            "delete_element": object_schema({"selector": string, "element_id": string}),
            "validate_slide_html": object_schema({}),
            "preview_patch": object_schema({}),
        }
        descriptions = {
            "get_project_context": "Load project, outline, and edit mode context.",
            "get_slide": "Load the current slide draft and base hash.",
            "list_slides": "List editable slide summaries.",
            "inspect_slide_html": "Inspect headings, text blocks, and images in the slide HTML.",
            "select_elements": "Mark matching elements with agent ids for later edits.",
            "replace_slide_html": "Replace the full slide HTML draft.",
            "replace_element_html": "Replace one selected element with safe HTML.",
            "update_text": "Update text content on one selected element.",
            "update_style": "Update whitelisted inline styles on one selected element.",
            "insert_element": "Insert safe HTML under a parent element.",
            "delete_element": "Delete one selected element.",
            "validate_slide_html": "Validate the current draft HTML.",
            "preview_patch": "Summarize whether the draft differs from the base slide.",
        }
        tool_names = runner.available_tool_names()
        missing = [name for name in tool_names if name not in schema_by_name]
        if missing:
            raise ValueError(f"Missing slide edit tool schemas: {', '.join(missing)}")
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": descriptions[name],
                    "parameters": schema_by_name[name],
                },
            }
            for name in tool_names
        ]

    def _compact_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            "success": observation.get("success", False),
            "summary": observation.get("summary") or observation.get("error") or "",
        }
        tool_name = observation.get("tool")
        if tool_name:
            compact["tool"] = tool_name
        preserved_keys_by_tool = {
            "get_project_context": ("project", "slide_index", "mode", "outline"),
            "get_slide": ("slide", "base_hash"),
            "list_slides": ("slides",),
            "inspect_slide_html": ("headings", "text_blocks", "images"),
            "select_elements": ("matches",),
            "validate_slide_html": ("errors", "warnings"),
            "preview_patch": ("base_hash", "new_hash", "changed"),
        }
        for key in preserved_keys_by_tool.get(str(tool_name), ()):
            if key in observation:
                compact[key] = self._compact_observation_value(observation[key])
        if observation.get("errors"):
            compact["errors"] = observation["errors"]
        if observation.get("warnings"):
            compact["warnings"] = observation["warnings"]
        return compact

    def _compact_observation_value(
        self, value: Any, *, max_string: int = 1600, max_items: int = 20
    ) -> Any:
        if isinstance(value, str):
            if len(value) <= max_string:
                return value
            return value[: max_string - 3].rstrip() + "..."
        if isinstance(value, list):
            return [
                self._compact_observation_value(
                    item, max_string=max_string, max_items=max_items
                )
                for item in value[:max_items]
            ]
        if isinstance(value, dict):
            return {
                str(key): self._compact_observation_value(item, max_string=max_string, max_items=max_items)
                for key, item in list(value.items())[:max_items]
            }
        return value
