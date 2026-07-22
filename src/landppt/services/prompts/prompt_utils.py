"""Shared helpers for prompt feature switches."""

from __future__ import annotations

from typing import Any, Dict, Optional


_FALSE_VALUES = {"false", "0", "no", "off", "none", "null", ""}
_PAGE_NUMBER_GUIDANCE_KEYWORDS = (
    "页码",
    "页脚",
    "Footer",
    "footer",
    "current_page_number",
    "total_page_count",
    "编号锚点",
)


def should_include_page_numbers(confirmed_requirements: Optional[Dict[str, Any]]) -> bool:
    """Return whether generated PPT prompts should mention page numbers/footer."""
    if not confirmed_requirements or "include_page_numbers" not in confirmed_requirements:
        return True

    value = confirmed_requirements.get("include_page_numbers")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_VALUES
    return bool(value)


def strip_page_number_footer_guidance(prompt: str) -> str:
    """Remove prompt lines that instruct footer/page-number rendering."""
    if not prompt:
        return prompt
    lines = []
    for line in prompt.splitlines():
        if any(keyword in line for keyword in _PAGE_NUMBER_GUIDANCE_KEYWORDS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def apply_page_number_prompt_filter(
    prompt: str,
    confirmed_requirements: Optional[Dict[str, Any]],
) -> str:
    """Apply the page-number/footer opt-out filter when requested."""
    if should_include_page_numbers(confirmed_requirements):
        return prompt
    return strip_page_number_footer_guidance(prompt)
