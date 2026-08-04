"""
Template Suite Renderer — deterministic slot-filling for cover/transition suite
templates, plus page-type dispatch used by the slide generation pipeline.

Slot semantics:
- Provided slots are substituted deterministically with real content.
- Unprovided slots (e.g. {{ cover_extra }}) are filled deterministically by
  the caller (SlideMediaService._default_slot_text), never left as raw tokens.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..prompts.design_prompts import DesignPrompts

_SLOT_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")

# Page-type keys the suite covers. Catalog/ending stay on the existing
# free-design path per the approved scope.
_SUITE_PAGE_TYPES = ("cover", "transition")

# Mapping from slide-type keys to the slot-set the suite template expects.
_COVER_SLOTS = ("cover_title", "cover_subtitle", "cover_extra")
_TRANSITION_SLOTS = ("transition_title", "transition_subtitle", "transition_extra")


class TemplateSuiteRenderer:
    """Fill cover/transition suite templates and dispatch page types."""

    @staticmethod
    def _suite_entry(suite: Dict[str, Any], page_type: str) -> Optional[str]:
        if not suite:
            return None
        entry = suite.get("cover") if page_type == "cover" else suite.get("transition")
        if not isinstance(entry, str) or not entry.strip():
            return None
        return entry

    @staticmethod
    def normalize_page_type(slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """Reuse DesignPrompts page-type normalization for consistent dispatch."""
        return DesignPrompts._normalize_page_guidance_type(
            slide_data or {}, page_number, total_pages
        )

    @staticmethod
    def should_use_suite(slide_data: Dict[str, Any], page_number: int, total_pages: int) -> bool:
        """True when the current page should be rendered from a suite template."""
        return TemplateSuiteRenderer.normalize_page_type(
            slide_data, page_number, total_pages
        ) in _SUITE_PAGE_TYPES

    @staticmethod
    def find_unfilled_slots(html: str) -> list:
        """Return slot names still present in the HTML (order preserved)."""
        return _SLOT_RE.findall(html or "")

    @staticmethod
    def fill_suite_template(suite_entry: str, slots: Dict[str, str]) -> str:
        """Substitute provided slots; leave unprovided slots in place."""
        html = suite_entry or ""
        for name, value in slots.items():
            if value is None:
                continue
            html = _SLOT_RE.sub(
                lambda m: str(value) if m.group(1) == name else m.group(0),
                html,
            )
        return html

    @staticmethod
    def apply_suite_to_slide(
        suite: Dict[str, Any],
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
    ) -> Optional[str]:
        """Render a cover/transition slide from its suite template.

        Returns the filled HTML, or None when no applicable suite template exists
        (caller falls back to the existing generation path).
        """
        page_type = TemplateSuiteRenderer.normalize_page_type(
            slide_data, page_number, total_pages
        )
        if page_type not in _SUITE_PAGE_TYPES:
            return None

        entry = TemplateSuiteRenderer._suite_entry(suite, page_type)
        if not entry:
            return None

        slide_data = slide_data or {}
        title = str(slide_data.get("title") or "").strip() or f"第{page_number}页"
        # Subtitle must come from real content, never from the page-type
        # description (which would leak labels like "PPT封面页"/"章节过渡页").
        subtitle = ""
        content_points = slide_data.get("content_points") or slide_data.get("content") or []
        if isinstance(content_points, list):
            for point in content_points:
                point = str(point).strip()
                if point:
                    subtitle = point
                    break
        elif isinstance(content_points, str) and content_points.strip():
            subtitle = content_points.strip()

        slots: Dict[str, str] = {}
        if page_type == "cover":
            slots["cover_title"] = title
            slots["cover_subtitle"] = subtitle
        else:
            slots["transition_title"] = title
            slots["transition_subtitle"] = subtitle

        filled = TemplateSuiteRenderer.fill_suite_template(entry, slots)
        if not filled.strip():
            return None
        return filled
