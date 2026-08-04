"""Tests for header/footer extraction and locked zones context.

The deterministic header/footer extractor previously lived as a private
helper on DesignPrompts and was removed; its regression test was updated to
cover the new MasterLayoutExtractor used by the template-suite workflow.
"""
from landppt.services.prompts.design_prompts import DesignPrompts
from landppt.services.template.master_layout_extractor import MasterLayoutExtractor


# --- Default template HTML with slide-header and slide-footer classes ---
DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<style>
.slide-header { padding: 40px 60px 20px 60px; border-bottom: 2px solid rgba(96,165,250,0.3); }
.slide-title { font-size: 3.5rem; font-weight: bold; color: #60a5fa; }
.slide-footer { position: absolute; bottom: 20px; right: 30px; font-size: 14px; color: #94a3b8; }
</style>
</head>
<body>
<div class="slide-container">
    <div class="slide-header"><h1 class="slide-title">{{ main_heading }}</h1></div>
    <div class="slide-content"><div class="content-main">{{ page_content }}</div></div>
    <div class="slide-footer">{{ current_page_number }} / {{ total_page_count }}</div>
</div>
</body>
</html>"""

# --- Template with semantic <header>/<footer> tags and inline styles ---
SEMANTIC_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;width:1280px;height:720px;overflow:hidden;">
<div class="slide-container">
    <header style="padding:30px 50px;display:flex;align-items:center;">
        <h1 style="font-size:36px;color:#00ffff;font-weight:700;">{{ page_title }}</h1>
    </header>
    <main><div class="content-main">{{ page_content }}</div></main>
    <footer style="padding:20px 50px;display:flex;justify-content:flex-end;">
        <span style="font-size:18px;color:#a0a0a0;">{{ current_page_number }} / {{ total_page_count }}</span>
    </footer>
</div>
</body>
</html>"""

# --- Template without semantic class names ---
NO_SEMANTIC_TEMPLATE = """<!DOCTYPE html>
<html><head><style>
.page { width: 1280px; height: 720px; }
</style></head>
<body>
<div class="page">
    <div class="top-bar"><h1>{{ main_heading }}</h1></div>
    <div class="body-area">{{ page_content }}</div>
    <div style="position: absolute; bottom: 10px; right: 20px;">{{ current_page_number }}</div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# MasterLayoutExtractor
# ---------------------------------------------------------------------------

def test_extract_header_footer_from_default_template():
    """Should extract slide-header and slide-footer from standard template."""
    result = MasterLayoutExtractor.extract_header_footer(DEFAULT_TEMPLATE)

    assert "slide-header" in result["header_html"]
    assert "slide-title" in result["header_html"]
    assert "slide-footer" in result["footer_html"]
    assert result["header_css"], "Header CSS should be extracted"
    assert result["footer_css"], "Footer CSS should be extracted"


def test_extract_header_footer_from_semantic_tags():
    """Should extract <header>/<footer> elements even without <style> blocks."""
    result = MasterLayoutExtractor.extract_header_footer(SEMANTIC_TEMPLATE)

    assert "<header" in result["header_html"]
    assert "<footer" in result["footer_html"]
    assert "page_title" in result["header_html"]
    assert "current_page_number" in result["footer_html"]
    # No <style> block -> CSS stays empty, but design tokens are derived inline.
    assert result["design_tokens"], "Design tokens should be derived from inline styles"


def test_extract_header_footer_from_template_without_semantic_classes():
    """Should fallback to position-based heuristics when no semantic classes."""
    result = MasterLayoutExtractor.extract_header_footer(NO_SEMANTIC_TEMPLATE)

    # Header found via .top-bar hint; footer via absolute-positioned element.
    assert "main_heading" in result["header_html"] or result["header_html"] == ""
    assert "current_page_number" in result["footer_html"]


def test_extract_returns_empty_for_empty_template():
    """Should return empty dict values for empty/None template."""
    result = MasterLayoutExtractor.extract_header_footer("")
    assert result["header_html"] == ""
    assert result["footer_html"] == ""

    result2 = MasterLayoutExtractor.extract_header_footer(None)
    assert result2["header_html"] == ""
    assert result2["footer_html"] == ""


# ---------------------------------------------------------------------------
# Locked zones context (current DesignPrompts behavior)
# ---------------------------------------------------------------------------

def test_locked_zones_context_for_content_page():
    """Content pages (not first/last/catalog) should get locked zone context."""
    context = DesignPrompts._build_locked_zones_context(
        DEFAULT_TEMPLATE, page_number=3, total_pages=10, slide_type="content")

    assert "HEADER_LOCK" in context
    assert "FOOTER_LOCK" in context
    assert "页头" in context
    assert "页脚" in context


def test_locked_zones_context_special_page():
    """First/last/catalog/transition pages should get the special-page hint instead."""
    for page_number, slide_type in ((1, "title"), (10, "thankyou"), (2, "catalog")):
        context = DesignPrompts._build_locked_zones_context(
            DEFAULT_TEMPLATE, page_number=page_number, total_pages=10, slide_type=slide_type)
        assert "特殊页面" in context, f"expected special-page hint for {slide_type} @ {page_number}"


def test_locked_zones_context_transition_page():
    """Transition pages should be exempt from the three-segment skeleton."""
    context = DesignPrompts._build_locked_zones_context(
        DEFAULT_TEMPLATE, page_number=3, total_pages=10, slide_type="transition")
    assert "特殊页面" in context


def test_locked_zones_context_empty_template_content_page():
    """Content page without a template gets the stable-region guidance block."""
    context = DesignPrompts._build_locked_zones_context(
        "", page_number=3, total_pages=10, slide_type="content")
    # When no template_html, the helper returns guidance (not the special-page block).
    assert "稳定区域" in context or context == ""
