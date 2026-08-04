"""Tests for the lxml HTML5 semantic-tag false-positive fix in validation."""
from landppt.services.slide.slide_html_inspection_service import SlideHtmlInspectionService


class _Stub:
    def _basic_html_syntax_check(self, html, vr):
        pass


def _validate(html):
    insp = SlideHtmlInspectionService(_Stub())
    return insp._validate_html_completeness(html)


def test_html5_semantic_tags_pass_validation():
    """lxml strict rejects <header>/<footer>/<nav> as 'Tag X invalid'; the tag-balance
    fallback should treat well-formed HTML5 as valid."""
    html = (
        '<!DOCTYPE html><html><head><title>t</title></head>'
        '<body><header class="h"><h1>Title</h1></header>'
        '<main><section><p>content</p></section></main>'
        '<footer>page 3 / 10</footer></body></html>'
    )
    result = _validate(html)
    assert result["is_complete"] is True, result["errors"]


def test_real_unclosed_tags_still_fail():
    """A genuinely mismatched tag must still be rejected (fix must not over-tolerate)."""
    html = '<html><body><div></p></body></html>'
    result = _validate(html)
    assert result["is_complete"] is False
    assert any("HTML语法错误" in e for e in result["errors"])


def test_unclosed_div_inside_header_still_fails():
    """An unclosed <div> inside a <header> is a real error, not an HTML5 false positive."""
    html = '<html><body><header><div></header></body></html>'
    result = _validate(html)
    assert result["is_complete"] is False


def test_empty_html_fails():
    result = _validate("")
    assert result["is_complete"] is False


def test_llm_style_html_with_header_passes():
    """HTML that looks like MiniMax output (header/footer + semantic tags) must pass."""
    html = (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
        '<style>body{width:1280px;height:720px;overflow:hidden}</style>\n</head>\n'
        '<body>\n<div class="slide-container">\n<header class="header">'
        '<div class="title">测试页</div><div class="page-indicator">04</div></header>\n'
        '<main><p>要点</p></main>\n<footer>内部资料</footer>\n</div>\n</body>\n</html>'
    )
    result = _validate(html)
    assert result["is_complete"] is True, result["errors"]
