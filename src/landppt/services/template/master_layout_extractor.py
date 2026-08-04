"""
Master Layout Extractor — deterministic extraction of a master template's
header / footer layout for use in the template-suite workflow.

Design principles:
- Deterministic (regex + simple HTML scanning), no LLM, no I/O, no network.
- Best-effort: if the template has no recognizable header/footer, return empty
  values instead of raising — callers degrade to the existing free-generation path.
- Covers the mainstream master-template shapes observed in this repo:
    * semantic <header>/<footer> elements (inline styles, no <style> block), and
    * class-based containers such as .slide-header / .slide-footer / .top-bar /
      .page-number (styles may live in a <style> block).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional

# Title placeholders that may appear in a header container.
_HEADER_PLACEHOLDERS = ("page_title", "main_heading")
# Page-number placeholders that may appear in a footer container.
_FOOTER_PLACEHOLDERS = ("current_page_number", "total_page_count")

# Class-name hints used to locate a header container.
_HEADER_CLASS_HINTS = (
    "slide-header", "page-header", "top-bar", "topbar", "header",
    "title-bar", "banner", "brand-bar", "nav-bar",
)
# Class-name hints used to locate a footer container.
_FOOTER_CLASS_HINTS = (
    "slide-footer", "page-footer", "bottom-bar", "bottombar", "footer",
    "page-number", "page-num", "slide-num", "pagination",
)

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}")
_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}\"]+)", re.IGNORECASE)
_BACKGROUND_RE = re.compile(
    r"background(?:-color)?\s*:\s*(linear-gradient\([^)]+\)|radial-gradient\([^)]+\)|#[0-9a-fA-F]{3,8}\b)",
    re.IGNORECASE,
)
_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;}\"]+)", re.IGNORECASE)
_COLOR_RE = re.compile(r"color\s*:\s*(#[0-9a-fA-F]{3,8}\b)", re.IGNORECASE)

_NEUTRAL_SAT_THRESHOLD = 0.08


class MasterLayoutExtractor:
    """Deterministic extractor of a master template's stable header/footer layout."""

    @staticmethod
    def _is_neutral(rgb: tuple) -> bool:
        r, g, b = rgb
        sat = (max(r, g, b) - min(r, g, b)) / 255.0
        return sat <= _NEUTRAL_SAT_THRESHOLD

    @staticmethod
    def _hex_to_rgb(h: str) -> tuple:
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    @staticmethod
    def _sanitize(html: str) -> str:
        """Return HTML with comments removed so tag matching is not fooled."""
        return _COMMENT_RE.sub("", html or "")

    @staticmethod
    def _find_matching_close(html: str, open_start: int, tag: str) -> Optional[int]:
        """Return the index of the </tag> matching the opening tag at open_start."""
        tag = tag.lower()
        open_pat = re.compile(rf"<{tag}\b", re.IGNORECASE)
        close_pat = re.compile(rf"</{tag}\s*>", re.IGNORECASE)
        depth = 0
        i = open_start
        while i < len(html):
            m_open = open_pat.search(html, i)
            m_close = close_pat.search(html, i)
            if m_close is None:
                return None
            if m_open is not None and m_open.start() < m_close.start():
                gt = html.find(">", m_open.start())
                if gt < 0:
                    return None
                if html[m_open.start():gt].rstrip().endswith("/"):
                    # Self-closing (e.g. <div />) — ignore
                    i = gt + 1
                    continue
                depth += 1
                i = m_open.end()
            else:
                depth -= 1
                if depth == 0:
                    return m_close.start()
                i = m_close.end()
        return None

    @staticmethod
    def _extract_tag_block(html: str, open_match: re.Match, tag: str) -> Optional[str]:
        """Return the full '<tag ...>...</tag>' block for an opening-tag match."""
        open_start = open_match.start()
        close_idx = MasterLayoutExtractor._find_matching_close(html, open_start, tag)
        if close_idx is None:
            return None
        return html[open_start:close_idx + len(f"</{tag}>") + 2]

    # ------------------------------------------------------------------
    # Header / footer location
    # ------------------------------------------------------------------

    @staticmethod
    def _find_element_by_placeholder(
        html: str, tag: str, placeholders: tuple, class_hints: tuple,
    ) -> Optional[str]:
        """Locate a container by semantic tag, then by class hints + placeholder."""
        # 1. Semantic tag that contains a relevant placeholder (or any content for header/footer tags).
        for m in re.finditer(rf"<{tag}\b[^>]*>", html, re.IGNORECASE):
            block = MasterLayoutExtractor._extract_tag_block(html, m, tag)
            if not block:
                continue
            if any(ph in block for ph in placeholders):
                return block
        # 2. Class-hint based <div>/<section> containers containing a placeholder.
        for m in re.finditer(r"<(div|section)\b([^>]*)>", html, re.IGNORECASE):
            attrs = m.group(2) or ""
            cls_match = re.search(r'class\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
            if not cls_match:
                continue
            classes = {c.lower() for c in cls_match.group(1).split()}
            if not any(h in c for h in class_hints for c in classes):
                continue
            block = MasterLayoutExtractor._extract_tag_block(html, m, m.group(1))
            if not block:
                continue
            if any(ph in block for ph in placeholders):
                return block
        return None

    @staticmethod
    def extract_header_footer(template_html: str) -> Dict[str, str]:
        """Extract stable header/footer layout from a master template.

        Returns dict with keys:
          header_html, footer_html, header_css, footer_css, design_tokens, root_variables
        Values are '' when the region cannot be located deterministically.
        """
        result = {
            "header_html": "",
            "footer_html": "",
            "header_css": "",
            "footer_css": "",
            "design_tokens": "",
            "root_variables": "",
        }
        if not template_html or not str(template_html).strip():
            return result

        sanitized = MasterLayoutExtractor._sanitize(template_html)

        header_html = MasterLayoutExtractor._find_element_by_placeholder(
            sanitized, "header", _HEADER_PLACEHOLDERS, _HEADER_CLASS_HINTS
        )
        footer_html = MasterLayoutExtractor._find_element_by_placeholder(
            sanitized, "footer", _FOOTER_PLACEHOLDERS, _FOOTER_CLASS_HINTS
        )
        if not footer_html:
            # Some templates render the page number with a bare <span>/<div>
            # carrying no class hint but an absolute position.
            for m in re.finditer(
                r"<(span|div|p)\b[^>]*style=\"[^\"]*(?:position:\s*absolute|bottom\s*:)[^\"]*\"[^>]*>",
                sanitized, re.IGNORECASE,
            ):
                block = MasterLayoutExtractor._extract_tag_block(sanitized, m, m.group(1))
                if block and any(ph in block for ph in _FOOTER_PLACEHOLDERS):
                    footer_html = block
                    break

        # 母版的 :root 自定义属性（CSS 变量）始终提取，供 header_footer 片段自包含使用。
        result["root_variables"] = MasterLayoutExtractor._extract_root_variables(sanitized)

        if not header_html and not footer_html:
            return result

        result["header_html"] = header_html or ""
        result["footer_html"] = footer_html or ""

        # Collect CSS rules for the classes referenced inside header/footer.
        header_css, footer_css = MasterLayoutExtractor._collect_region_css(
            sanitized, header_html or "", footer_html or ""
        )
        result["header_css"] = header_css
        result["footer_css"] = footer_css
        result["design_tokens"] = MasterLayoutExtractor._extract_design_tokens(
            header_html or "", footer_html or "", header_css, footer_css
        )
        # 提取母版 :root 自定义属性（CSS 变量）。header/footer 片段可能引用
        # var(--xxx)，而这些变量定义在母版的 :root 块里；若不带上，片段独立
        # 使用时样式会全部失效。
        result["root_variables"] = MasterLayoutExtractor._extract_root_variables(sanitized)
        return result

    @staticmethod
    def _extract_root_variables(html: str) -> str:
        """提取母版 <style> 中的 :root { ... } 自定义属性块（原样返回）。"""
        if not html:
            return ""
        for block in _STYLE_BLOCK_RE.findall(html):
            m = re.search(r":root\s*\{[^}]*\}", block, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(0).strip()
        return ""

    @staticmethod
    def extract_content_skeleton(template_html: str) -> Dict[str, str]:
        """从母版提取"内容页完整骨架"：canvas 容器 + 背景/边框/印章装饰层 HTML，
        以及这些装饰类的 CSS 规则。返回 {"skeleton_html": ..., "skeleton_css": ...}。

        这样 header_footer 片段不仅能承载页头页脚，还带上模板的背景与装饰，
        内容页预览/生成时视觉上就"遵照模板本身"。
        """
        skeleton = {"skeleton_html": "", "skeleton_css": ""}
        if not template_html:
            return skeleton

        sanitized = MasterLayoutExtractor._sanitize(template_html)
        body_m = re.search(r"<body[^>]*>(.*?)</body>", sanitized, re.DOTALL | re.IGNORECASE)
        if not body_m:
            return skeleton
        body = body_m.group(1)

        # 装饰层 = body 里除 页头/正文/页脚 之外的部分。
        # 用已知锚点切分：title-anchor / main-stage / number-anchor。
        anchors = ["title-anchor", "main-stage", "number-anchor"]
        cuts = [body.find(a) for a in anchors]
        cuts = [c for c in cuts if c != -1]
        if not cuts:
            return skeleton

        first_anchor = min(cuts)
        # 装饰部分：从 <div class="canvas"> 到第一个锚点标签的起始之前（含 canvas 开头）。
        canvas_start = body.find('class="canvas"')
        if canvas_start != -1:
            # 找到包含 canvas 的 <div> 起始
            div_start = body.rfind("<div", 0, canvas_start)
            if div_start != -1:
                # 截断点需落在锚点 <div> 标签的起始处，而不是类名字符串位置
                # （否则会把 <div class="title-anchor"> 的 <div class=" 切进骨架）。
                cut = first_anchor
                anchor_div = body.rfind("<div", 0, first_anchor)
                # 若锚点前最近的 <div 之后紧接着就是锚点类名，说明截断点应是该 <div 起始
                if anchor_div != -1:
                    between = body[anchor_div:first_anchor]
                    if ">" not in between:
                        cut = anchor_div
                skeleton_html = body[div_start:cut]
                skeleton["skeleton_html"] = skeleton_html.strip()

        # 装饰 CSS：canvas / bg-* / frame-* / deco-* / stamp-* 等装饰类的规则
        if skeleton["skeleton_html"]:
            decor_classes = MasterLayoutExtractor._classes_in(skeleton["skeleton_html"])
            style_blocks = [b for b in _STYLE_BLOCK_RE.findall(sanitized)]
            css_lines = []
            for block in style_blocks:
                for sm in _CSS_RULE_RE.finditer(block):
                    selector = sm.group(1).strip()
                    rule_body = sm.group(2).strip()
                    if not rule_body:
                        continue
                    # 装饰类规则：选择器引用了装饰层里的类
                    if any(f".{c}" in selector for c in decor_classes):
                        css_lines.append(f"{selector} {{ {rule_body} }}")
            skeleton["skeleton_css"] = "\n".join(css_lines)

        return skeleton

    # ------------------------------------------------------------------
    # CSS collection
    # ------------------------------------------------------------------

    @staticmethod
    def _classes_in(html_fragment: str) -> set:
        classes: set = set()
        for m in re.finditer(r'class\s*=\s*["\']([^"\']*)["\']', html_fragment, re.IGNORECASE):
            classes.update(c for c in m.group(1).split() if c)
        return classes

    @staticmethod
    def _collect_region_css(html: str, header_html: str, footer_html: str) -> tuple:
        """Return (header_css, footer_css) — rules from <style> blocks whose
        selector references a class used inside the region."""
        style_blocks = [b.strip() for b in _STYLE_BLOCK_RE.findall(html)]
        if not style_blocks:
            return "", ""

        header_classes = MasterLayoutExtractor._classes_in(header_html)
        footer_classes = MasterLayoutExtractor._classes_in(footer_html)

        def collect(classes: set) -> str:
            if not classes:
                return ""
            lines: List[str] = []
            for block in style_blocks:
                for sm in _CSS_RULE_RE.finditer(block):
                    selector = sm.group(1).strip()
                    body = sm.group(2).strip()
                    if not body:
                        continue
                    if any(f".{c}" in selector for c in classes):
                        lines.append(f"{selector} {{ {body} }}")
            return "\n".join(lines)

        return collect(header_classes), collect(footer_classes)

    # ------------------------------------------------------------------
    # Design tokens
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_design_tokens(
        header_html: str, footer_html: str, header_css: str, footer_css: str
    ) -> str:
        """Build a one-line design-token summary (font stack / accent / header bg / footer style)."""
        region = header_html + footer_html + header_css + footer_css
        tokens: List[str] = []

        fonts = _FONT_FAMILY_RE.findall(region)
        if fonts:
            tokens.append(f"字体栈：{fonts[0].strip()}")

        hexes = [h.lower() for h in _HEX_RE.findall(region)]
        counter: Counter = Counter()
        for h in hexes:
            try:
                rgb = MasterLayoutExtractor._hex_to_rgb(h)
            except Exception:
                continue
            if MasterLayoutExtractor._is_neutral(rgb):
                continue
            counter[h] += 1
        if counter:
            accent, _count = counter.most_common(1)[0]
            tokens.append(f"强调色：{accent}")

        bg = _BACKGROUND_RE.findall(region)
        if bg:
            tokens.append(f"页头页脚背景：{bg[0].strip()}")

        footer_fs = _FONT_SIZE_RE.findall(footer_html)
        if footer_fs:
            tokens.append(f"页码字号：{footer_fs[0].strip()}")
        footer_color = _COLOR_RE.findall(footer_html)
        if footer_color:
            tokens.append(f"页码颜色：{footer_color[0]}")

        return "；".join(tokens) if tokens else ""
