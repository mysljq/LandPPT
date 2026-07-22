from landppt.services.slide.aesthetic_preflight_checker import AestheticPreFlightChecker


_BASE = (
    "<!DOCTYPE html><html><head><style>"
    "body{background:#1A1A1A;color:#F7F7F5}"
    ".accent{color:#2D6A4F}"
    "</style></head><body><main><h1>标题</h1><p class='accent'>强调</p></main></body></html>"
)


def _check(html, header_lock=None, footer_lock=None, slide_data=None, page_number=None, total_pages=None):
    return AestheticPreFlightChecker.check(
        html, header_lock=header_lock, footer_lock=footer_lock,
        slide_data=slide_data, page_number=page_number,
        total_pages=total_pages)


def test_clean_html_passes():
    hard, warns = _check(_BASE)
    assert hard == []
    assert warns == []


# def test_em_dash_is_hard_fail():
#     hard, warns = _check(_BASE.replace("标题", "增长 — 复盘"))
#     assert any("em-dash" in h or "破折" in h or "en-dash" in h or "—" in h for h in hard), hard


def test_pure_black_and_white_is_hard_fail():
    html = "<style>.a{background:#000000;color:#ffffff}</style>"
    hard, warns = _check(html)
    assert hard
    assert any("#000000" in h or "#FFFFFF" in h for h in hard)


def test_multiple_active_accents_is_hard_fail():
    html = (
        "<style>"
        ".a{color:#2D6A4F}"   # 绿强调
        ".b{color:#E63946}"   # 红强调
        ".c{color:#2D6A4F}"
        ".d{color:#E63946}"
        "</style>"
    )
    hard, warns = _check(html)
    assert any("accent" in h for h in hard), hard


def test_neutral_grays_do_not_count_as_accents():
    html = (
        "<style>"
        ".a{color:#1A1A1A}"   # 近黑灰
        ".b{color:#F7F7F5}"   # 近白灰
        ".c{color:#6B6B6B}"   # 中灰
        ".d{color:#1A1A1A}"
        "</style>"
    )
    hard, warns = _check(html)
    assert hard == [], hard


def test_three_column_grid_is_warning_not_hard():
    html = "<style>.grid{grid-template-columns: repeat(3,1fr)}</style><div class='grid'><div class='card'></div><div class='card'></div><div class='card'></div></div>"
    hard, warns = _check(html)
    assert hard == []
    assert any("三列" in w or "三" in w for w in warns), warns


def test_empty_html_returns_empty():
    hard, warns = _check("")
    assert hard == [] and warns == []
    hard2, warns2 = _check("   ")
    assert hard2 == [] and warns2 == []


def test_idempotent_and_pure():
    h1, w1 = _check(_BASE)
    h2, w2 = _check(_BASE)
    assert (h1, w1) == (h2, w2)


def test_single_accent_only_not_flagged_for_collision():
    html = (
        "<style>"
        ".a{color:#2D6A4F}"
        ".b{color:#2D6A4F}"
        ".c{color:#2D6A4F}"
        "</style>"
    )
    hard, warns = _check(html)
    assert not any("accent" in h for h in hard), hard


def test_radius_chaos_is_warning():
    parts = "".join(f".r{i}{{border-radius:{v}px}}" for i, v in enumerate([2, 4, 8, 12, 16, 20, 24, 30]))
    html = f"<style>{parts}</style>"
    hard, warns = _check(html)
    assert hard == []
    assert any("圆角" in w for w in warns), warns


# ---- HEADER_LOCK 跨页一致性守恒 ----

_HEADER_LOCK_CONSTI = """
===DIALS===
DESIGN_VARIANCE: 6
===HEADER_LOCK===
font_family: 'Source Han Sans CN','PingFang SC',sans-serif
font_size: 36px
font_weight: 600
color: #1A1A1A
background: linear-gradient(135deg,#F7F7F5,#EFEFE9)
padding: 32px 40px
===RADIUS===
scale: soft
"""

_LOCK = {
    "font_family": "'Source Han Sans CN','PingFang SC',sans-serif",
    "font_size": "36px",
    "font_weight": "600",
    "color": "#1A1A1A",
    "background": "linear-gradient(135deg,#F7F7F5,#EFEFE9)",
    "padding": "32px 40px",
}


def test_parse_header_lock_extracts_all_fields():
    parsed = AestheticPreFlightChecker.parse_header_lock(_HEADER_LOCK_CONSTI)
    assert parsed["font_family"].startswith("'Source Han")
    assert parsed["color"] == "#1A1A1A"
    assert parsed["font_weight"] == "600"
    assert "linear-gradient" in parsed["background"]
    assert parsed["padding"] == "32px 40px"


def test_parse_header_lock_missing_returns_empty():
    assert AestheticPreFlightChecker.parse_header_lock("no token here") == {}
    assert AestheticPreFlightChecker.parse_header_lock("") == {}


def test_header_html_matching_lock_passes():
    html = (
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;"
        "font-size:36px;font-weight:600;color:#1A1A1A;"
        "background:linear-gradient(135deg,#F7F7F5,#EFEFE9);padding:32px 40px\">"
        "<h1>标题</h1></header>"
    )
    hard, warns = _check(html, _LOCK)
    assert not any("HEADER_LOCK" in h for h in hard), hard
    assert not any("HEADER_LOCK" in w for w in warns), warns


def test_header_divergent_font_family_is_hard_fail():
    html = (
        "<header style=\"font-family:Inter,sans-serif;"
        "font-size:36px;color:#1A1A1A;background:linear-gradient(135deg,#F7F7F5,#EFEFE9)\">"
        "<h1>标题</h1></header>"
    )
    hard, warns = _check(html, _LOCK)
    assert any("字体" in h and "HEADER_LOCK" in h for h in hard), hard


def test_header_divergent_background_is_hard_fail():
    html = (
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;"
        "font-size:36px;color:#1A1A1A;background:#EEEEEE\">"
        "<h1>标题</h1></header>"
    )
    hard, warns = _check(html, _LOCK)
    assert any("背景" in h and "HEADER_LOCK" in h for h in hard), hard


def test_header_font_size_mismatch_is_warning_only():
    html = (
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;"
        "font-size:42px;font-weight:700;color:#1A1A1A;background:linear-gradient(135deg,#F7F7F5,#EFEFE9)\">"
        "<h1>标题</h1></header>"
    )
    hard, warns = _check(html, _LOCK)
    # 字号/字重是软指标，不应 hard fail
    assert not any("HEADER_LOCK" in h for h in hard), hard
    assert any("字号" in w or "字重" in w for w in warns), warns


def test_header_lock_disabled_when_not_passed():
    # 不传 header_lock 时，字体漂移不应被判 hard fail（向后兼容）
    html = "<header style=\"font-family:Inter,sans-serif;font-size:36px;color:#1A1A1A;background:#FFFFFF\"><h1>x</h1></header>"
    hard, warns = _check(html)
    assert not any("HEADER_LOCK" in h for h in hard), hard


# ---- 非内容页豁免 + icon 一致性 ----

_ICON_LOCK_NONE = {**_LOCK, "icon": "none"}
_ICON_LOCK_SVG = {**_LOCK, "icon": "svg-inline,28px"}


def test_cover_page_exempt_from_header_lock():
    # 封面页：页头本可自由设计，不应触发页头令牌守恒
    html = (
        "<header style=\"font-family:Inter,sans-serif;font-size:80px;color:#000000;background:#FFFFFF\">"
        "<h1>封面标题</h1></header>"
    )
    hard, warns = _check(html, _ICON_LOCK_NONE, slide_data={"slide_type": "cover"}, page_number=1, total_pages=5)
    assert not any("HEADER_LOCK" in h for h in hard), hard


def test_catalog_page_exempt_from_header_lock():
    html = (
        "<header style=\"font-family:Inter,sans-serif;font-size:40px;color:#000000;background:#FFFFFF\">"
        "<h1>目录</h1></header>"
    )
    hard, warns = _check(html, _LOCK, slide_data={"slide_type": "catalog"}, page_number=2, total_pages=5)
    assert not any("HEADER_LOCK" in h for h in hard), hard


def test_transition_page_exempt_via_slide_type():
    hard, warns = _check(
        "<header style=\"font-family:Inter,sans-serif;font-size:36px;color:#1A1A1A;background:#EEEEEE\"><h1>过渡</h1></header>",
        _LOCK, slide_data={"slide_type": "divider"}, page_number=3, total_pages=8,
    )
    assert not any("HEADER_LOCK" in h for h in hard), hard


def test_transition_page_exempt_via_title_keyword():
    hard, warns = _check(
        "<header style=\"font-family:Inter,sans-serif;font-size:36px;color:#1A1A1A;background:#EEEEEE\"><h1>章节过渡</h1></header>",
        _LOCK, slide_data={"slide_type": "content", "title": "章节过渡"}, page_number=3, total_pages=8,
    )
    assert not any("HEADER_LOCK" in h for h in hard), hard


def test_content_page_still_enforces_header_lock():
    # 普通内容页：背景漂移仍判 hard
    hard, warns = _check(
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;font-size:36px;color:#1A1A1A;background:#EEEEEE\"><h1>x</h1></header>",
        _LOCK, slide_data={"slide_type": "content", "title": "市场分析"}, page_number=3, total_pages=5,
    )
    assert any("HEADER" in h for h in hard), hard


def test_icon_none_lock_flags_page_with_svg():
    # 令牌要求纯文字标题，但页头带 svg → hard
    html = (
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;"
        "font-size:36px;color:#1A1A1A;background:linear-gradient(135deg,#F7F7F5,#EFEFE9)\">"
        "<svg width=\"28\" height=\"28\"></svg><h1>x</h1></header>"
    )
    hard, warns = _check(
        html, _ICON_LOCK_NONE,
        slide_data={"slide_type": "content", "title": "要点"}, page_number=3, total_pages=5,
    )
    assert any("图标" in h for h in hard), hard


def test_icon_svg_lock_flags_page_without_svg():
    # 令牌要求带 svg，但页头纯文字 → hard
    html = (
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;"
        "font-size:36px;color:#1A1A1A;background:linear-gradient(135deg,#F7F7F5,#EFEFE9)\">"
        "<h1>x</h1></header>"
    )
    hard, warns = _check(
        html, _ICON_LOCK_SVG,
        slide_data={"slide_type": "content", "title": "要点"}, page_number=3, total_pages=5,
    )
    assert any("图标" in h for h in hard), hard


def test_icon_svg_lock_passes_when_svg_present():
    html = (
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;"
        "font-size:36px;color:#1A1A1A;background:linear-gradient(135deg,#F7F7F5,#EFEFE9)\">"
        "<svg width=\"28\" height=\"28\"></svg><h1>x</h1></header>"
    )
    hard, warns = _check(
        html, _ICON_LOCK_SVG,
        slide_data={"slide_type": "content", "title": "要点"}, page_number=3, total_pages=5,
    )
    assert not any("图标" in h for h in hard), hard


# ---- 增强 icon 检测（SVG 在 header 容器外）----

def test_icon_none_flags_tiny_svg_outside_header():
    """SVG 小图标不在 header 里、单独放在 header 外，仍判违反"""
    html = (
        "<div><svg width=\"28\" height=\"28\"><circle r=\"12\"/></svg></div>"
        "<header style=\"font-family:'Source Han Sans CN','PingFang SC',sans-serif;"
        "font-size:36px;color:#1A1A1A;background:linear-gradient(135deg,#F7F7F5,#EFEFE9)\">"
        "<h1>x</h1></header>"
    )
    hard, warns = _check(
        html, _ICON_LOCK_NONE,
        slide_data={"slide_type": "content", "title": "要点"}, page_number=3, total_pages=5,
    )
    assert any("图标" in h for h in hard), hard


# ---- FOOTER_LOCK 页脚页码一致性 ----

_FOOTER_LOCK = {
    "font_family": "'Source Han Sans CN',sans-serif",
    "font_size": "14px",
    "font_weight": "400",
    "color": "#6B6B6B",
}


def test_parse_footer_lock_extracts_fields():
    parsed = AestheticPreFlightChecker.parse_footer_lock(
        "===FOOTER_LOCK===\nfont_family: 'Source Han Sans CN',sans-serif\nfont_size: 14px\nfont_weight: 400\ncolor: #6B6B6B\n===RADIUS===\nscale: soft"
    )
    assert parsed["font_family"].startswith("'Source Han")
    assert parsed["color"] == "#6B6B6B"
    assert parsed["font_size"] == "14px"


def test_footer_page_number_match_passes():
    html = (
        "<div style=\"font-family:'Source Han Sans CN',sans-serif;font-size:14px;"
        "font-weight:400;color:#6B6B6B\">3 / 8</div>"
    )
    hard, warns = _check(
        html, footer_lock=_FOOTER_LOCK,
        slide_data={"slide_type": "content", "title": "x"}, page_number=3, total_pages=8,
    )
    assert not any("FOOTER_LOCK" in h for h in hard), hard


def test_footer_color_divergent_is_hard_fail():
    html = (
        "<div style=\"font-family:'Source Han Sans CN',sans-serif;font-size:14px;"
        "font-weight:400;color:#FF0000\">3 / 8</div>"
    )
    hard, warns = _check(
        html, footer_lock=_FOOTER_LOCK,
        slide_data={"slide_type": "content", "title": "x"}, page_number=3, total_pages=8,
    )
    assert any("FOOTER_LOCK" in h for h in hard), hard


def test_footer_missing_page_number_is_warning():
    html = "<div style=\"padding:20px\">仅正文内容，无 N/M 页码</div>"
    hard, warns = _check(
        html, footer_lock=_FOOTER_LOCK,
        slide_data={"slide_type": "content", "title": "x"}, page_number=3, total_pages=8,
    )
    # 没有 N/M 格式页码 → warning 而非 hard fail（可能用了纯数字格式）
    assert not any("FOOTER_LOCK" in h for h in hard), hard
    assert any("页码" in w for w in warns), warns


def test_cover_page_exempt_from_footer_lock():
    html = "<div style=\"font-family:Inter;color:#000\">1 / 5</div>"
    hard, warns = _check(
        html, footer_lock=_FOOTER_LOCK,
        slide_data={"slide_type": "cover"}, page_number=1, total_pages=5,
    )
    assert not any("FOOTER_LOCK" in h for h in hard), hard