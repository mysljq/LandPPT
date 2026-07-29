import logging
import re
from typing import TYPE_CHECKING


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from .slide_html_service import SlideHtmlService


class SlideHtmlCleanupService:
    """HTML response cleanup extracted from SlideHtmlService."""

    def __init__(self, service: "SlideHtmlService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    # ------------------------------------------------------------------
    # @media block removal
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_media_blocks(css_text: str) -> str:
        """Remove all @media blocks from CSS.

        PPT slides are always rendered at a fixed 1280×720 canvas in
        isolation — responsive @media queries are meaningless and are
        the primary source of unwanted transform: scale() rules that
        cause inconsistent sizing in PPTX export.
        """
        if not css_text or not isinstance(css_text, str):
            return css_text

        result: list[str] = []
        i = 0
        n = len(css_text)

        while i < n:
            # Find next @media
            m = re.search(r'@media\b', css_text[i:], re.IGNORECASE)
            if not m:
                result.append(css_text[i:])
                break

            # Keep everything before the @media
            start = i + m.start()
            result.append(css_text[i:start])

            # Find the opening brace of the @media block
            brace_start = css_text.find('{', start)
            if brace_start == -1:
                # Malformed — keep the rest as-is
                result.append(css_text[start:])
                break

            # Count braces to find the matching closing brace
            depth = 0
            j = brace_start
            while j < n:
                if css_text[j] == '{':
                    depth += 1
                elif css_text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        # Found the matching }
                        i = j + 1
                        break
                j += 1
            else:
                # No matching closing brace — keep the rest as-is
                result.append(css_text[start:])
                break

        return ''.join(result)

    # ------------------------------------------------------------------
    # transform: scale() removal (defence in depth)
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_transform_scale(html_content: str) -> str:
        """Remove scale()/scaleX()/scaleY() from transform CSS properties.

        Strips @media blocks first (primary source of scale), then
        removes any remaining scale() in inline styles and <style>
        blocks as defence in depth.
        """
        if not html_content or not isinstance(html_content, str):
            return html_content

        # --- 0. Strip @media blocks entirely ---
        html_content = SlideHtmlCleanupService._strip_media_blocks(html_content)

        # Pattern matches scale(), scaleX(), scaleY() inside transform values.
        _SCALE_RE = re.compile(
            r'\bscale[XxYy]?\s*\(\s*[\d.]+(?:%?)\s*(?:,\s*[\d.]+(?:%?)\s*)?\)',
        )

        def _clean_transform_value(value: str) -> str:
            """Remove scale functions from a transform value string."""
            cleaned = _SCALE_RE.sub('', value).strip()
            cleaned = re.sub(r'\s{2,}', ' ', cleaned)
            cleaned = re.sub(r'\s*\)\s+', ') ', cleaned)
            cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
            if cleaned == '' or cleaned.lower() == 'none':
                return 'none'
            return cleaned

        # --- 1. Strip from style="" attributes ---
        def _replace_style_attr(match: re.Match) -> str:
            attr_prefix = match.group(1)
            quote_char = match.group(2)
            style_value = match.group(3) or ''

            def _replace_transform(m: re.Match) -> str:
                before = m.group(1) or ''
                transform_val = m.group(2) or ''
                after = m.group(3) or ''
                cleaned = _clean_transform_value(transform_val)
                if cleaned == 'none':
                    before_clean = before.rstrip(';').rstrip()
                    if before_clean:
                        return before_clean + after
                    return after.lstrip(';').lstrip()
                return f'{before}transform:{cleaned}{after}'

            new_value = re.sub(
                r'(^|;\s*)transform\s*:\s*([^;"]+?)(;|(?=["\']))',
                _replace_transform,
                style_value,
                flags=re.IGNORECASE,
            )
            if new_value != style_value:
                return f'{attr_prefix}{quote_char}{new_value}{quote_char}'
            return match.group(0)

        html_content = re.sub(
            r'(style\s*=\s*)(["\'])(.*?)\2',
            _replace_style_attr,
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # --- 2. Strip from <style>...</style> blocks ---
        def _replace_style_block(match: re.Match) -> str:
            open_tag = match.group(1) or ''
            css_text = match.group(2) or ''
            close_tag = match.group(3) or ''

            def _replace_css_transform(m: re.Match) -> str:
                value = m.group(1) or ''
                cleaned = _clean_transform_value(value)
                return f'transform: {cleaned}'

            new_css = re.sub(
                r'transform\s*:\s*([^;}\n]+)',
                _replace_css_transform,
                css_text,
                flags=re.IGNORECASE,
            )
            return f'{open_tag}{new_css}{close_tag}'

        html_content = re.sub(
            r'(<style[^>]*>)' + r'(.*?)' + r'(</style>)',
            _replace_style_block,
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )

        return html_content

    def _clean_html_response(self, raw_content: str) -> str:
        """Clean and extract HTML content from AI responses."""
        raw_content = self._strip_think_tags(raw_content)

        if not raw_content:
            logger.warning("Received empty response from AI")
            return ""

        content = raw_content.strip()
        logger.debug("Raw AI response length: %s, preview: %s...", len(content), content[:200])
        content_lower = content.lower()

        if len(content) < 100:
            logger.warning("AI response is very short (%s chars), might be incomplete", len(content))
        has_error_indicators = any(
            error_indicator in content_lower for error_indicator in ["error", "sorry", "cannot", "unable"]
        )

        html_match = re.search(r"```html\s*\n(.*?)\n```", content, re.DOTALL | re.IGNORECASE)
        if html_match:
            logger.debug("Found HTML in markdown code block")
            return self._strip_transform_scale(html_match.group(1).strip())

        generic_match = re.search(r"```\s*\n(.*?)\n```", content, re.DOTALL)
        if generic_match:
            potential_html = generic_match.group(1).strip()
            if potential_html.lower().startswith("<!doctype html") or potential_html.lower().startswith("<html"):
                logger.debug("Found HTML in generic code block")
                return self._strip_transform_scale(potential_html)

        prefixes_to_remove = [
            "这是生成的HTML代码：",
            "以下是HTML代码：",
            "HTML代码如下：",
            "生成的完整HTML页面：",
            "Here's the HTML code:",
            "The HTML code is:",
            "```html",
            "```",
        ]
        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()

        if content.endswith("```"):
            content = content[:-3].strip()

        doctype_match = re.search(r"<!DOCTYPE html.*?</html>", content, re.DOTALL | re.IGNORECASE)
        if doctype_match:
            logger.debug("Found HTML using DOCTYPE pattern")
            return self._strip_transform_scale(doctype_match.group(0))

        html_tag_match = re.search(r"<html.*?</html>", content, re.DOTALL | re.IGNORECASE)
        if html_tag_match:
            logger.debug("Found HTML using html tag pattern")
            return self._strip_transform_scale(html_tag_match.group(0))

        html_lines = []
        in_html = False
        for line in content.split("\n"):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()

            if not line_stripped or line_stripped.startswith("#") or line_stripped.startswith("//"):
                continue

            if line_lower.startswith("<!doctype") or line_lower.startswith("<html"):
                in_html = True
                html_lines.append(line)
                continue

            if in_html:
                html_lines.append(line)
                if line_lower.endswith("</html>"):
                    break

        if html_lines:
            logger.debug("Found HTML using line-by-line extraction")
            return self._strip_transform_scale("\n".join(html_lines))

        if "<" in content and ">" in content:
            logger.warning("Could not extract HTML using strict patterns, returning cleaned content")
            return self._strip_transform_scale(content)

        if has_error_indicators:
            logger.warning("AI response appears to be an error message instead of HTML")

        logger.error("Failed to extract HTML from AI response")
        return ""
