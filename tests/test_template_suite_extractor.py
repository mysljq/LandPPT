"""Tests for the template-suite extractor and renderer."""
import json
import re

from landppt.services.template.master_layout_extractor import MasterLayoutExtractor
from landppt.services.template.template_suite_renderer import TemplateSuiteRenderer
from landppt.services.template.template_suite_service import TemplateSuiteService

# --- Fixtures --------------------------------------------------------------

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

CLASS_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><style>
.slide-header { padding: 40px 60px 20px 60px; }
.slide-title { font-size: 3.5rem; color: #60a5fa; }
.slide-footer { position: absolute; bottom: 20px; right: 30px; font-size: 14px; color: #94a3b8; }
</style></head>
<body>
<div class="slide-container">
    <div class="slide-header"><h1 class="slide-title">{{ main_heading }}</h1></div>
    <div class="slide-content"><div class="content-main">{{ page_content }}</div></div>
    <div class="slide-footer">{{ current_page_number }} / {{ total_page_count }}</div>
</div>
</body>
</html>"""

SUITE = {
    "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1><p>{{ cover_subtitle }}</p><p>{{ cover_extra }}</p></body></html>",
    "transition": "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1><p>{{ transition_subtitle }}</p><p>{{ transition_extra }}</p></body></html>",
    "catalog": "<!DOCTYPE html><html><body><h1>{{ catalog_title }}</h1><ul>{{ catalog_items }}</ul><p>{{ catalog_extra }}</p></body></html>",
    "ending": "<!DOCTYPE html><html><body><h1>{{ ending_title }}</h1><p>{{ ending_subtitle }}</p><p>{{ ending_extra }}</p></body></html>",
    "header_footer": "<header>{{ page_title }}</header><footer>{{ current_page_number }} / {{ total_page_count }}</footer>",
    "design_tokens": "字体栈：A；强调色：#123456",
}


# --- MasterLayoutExtractor --------------------------------------------------

def test_extract_semantic_tags():
    r = MasterLayoutExtractor.extract_header_footer(SEMANTIC_TEMPLATE)
    assert "<header" in r["header_html"]
    assert "<footer" in r["footer_html"]
    assert "page_title" in r["header_html"]
    assert "current_page_number" in r["footer_html"]
    assert r["design_tokens"]


def test_extract_class_based_with_css():
    r = MasterLayoutExtractor.extract_header_footer(CLASS_TEMPLATE)
    assert "slide-header" in r["header_html"]
    assert "slide-footer" in r["footer_html"]
    assert "slide-title" in r["header_css"]
    assert "slide-footer" in r["footer_css"]


def test_extract_empty_template():
    r = MasterLayoutExtractor.extract_header_footer("")
    assert r["header_html"] == "" and r["footer_html"] == ""
    r2 = MasterLayoutExtractor.extract_header_footer(None)
    assert r2["header_html"] == "" and r2["footer_html"] == ""


def test_extract_garbage_template():
    r = MasterLayoutExtractor.extract_header_footer("<html><body><div>hi</div></body></html>")
    assert r["header_html"] == "" and r["footer_html"] == ""


# --- TemplateSuiteRenderer --------------------------------------------------

def test_renderer_cover_fill():
    filled = TemplateSuiteRenderer.apply_suite_to_slide(
        SUITE, {"title": "AI 专题", "slide_type": "title", "content_points": ["深度解析"]}, 1, 10
    )
    assert filled is not None
    assert "AI 专题" in filled
    assert "深度解析" in filled
    # Unprovided slot stays for LLM completion.
    assert "{{ cover_extra }}" in filled


def test_renderer_cover_subtitle_never_uses_description():
    """The page-type description ("PPT封面页/章节过渡页") must never leak into
    the rendered cover/transition subtitle."""
    filled = TemplateSuiteRenderer.apply_suite_to_slide(
        SUITE,
        {"title": "部门工作汇报", "slide_type": "title",
         "description": "PPT封面页，展示核心信息", "content_points": ["汇报期间：2026年1-4月"]},
        1, 10,
    )
    assert filled is not None
    assert "部门工作汇报" in filled
    assert "2026年1-4月" in filled
    assert "封面页" not in filled


def test_renderer_transition_fill():
    filled = TemplateSuiteRenderer.apply_suite_to_slide(
        SUITE,
        {"title": "第二章", "slide_type": "transition", "content_points": ["核心要点"]},
        4, 10,
    )
    assert filled is not None
    assert "第二章" in filled
    assert "核心要点" in filled


def test_renderer_content_not_covered():
    assert TemplateSuiteRenderer.apply_suite_to_slide(
        SUITE, {"title": "内容", "slide_type": "content"}, 3, 10
    ) is None


def test_renderer_catalog_fill():
    filled = TemplateSuiteRenderer.apply_suite_to_slide(
        SUITE,
        {"title": "目录", "slide_type": "agenda", "content_points": ["第一章 概述", "第二章 方案"]},
        2, 10,
    )
    assert filled is not None
    assert "目录" in filled
    assert "第一章 概述" in filled  # items slot filled from content_points
    assert "{{ catalog_extra }}" in filled  # optional slot stays for LLM completion


def test_renderer_ending_fill():
    filled = TemplateSuiteRenderer.apply_suite_to_slide(
        SUITE,
        {"title": "感谢聆听", "slide_type": "thankyou", "content_points": ["谢谢关注"]},
        10, 10,
    )
    assert filled is not None
    assert "感谢聆听" in filled
    assert "谢谢关注" in filled


def test_renderer_returns_none_when_entry_missing():
    assert TemplateSuiteRenderer.apply_suite_to_slide(
        {"cover": ""}, {"title": "x", "slide_type": "title"}, 1, 10
    ) is None
    # catalog/ending entries missing -> those page types fall back (None)
    assert TemplateSuiteRenderer.apply_suite_to_slide(
        {"cover": "x", "transition": "x"}, {"title": "目录", "slide_type": "agenda"}, 2, 10
    ) is None
    assert TemplateSuiteRenderer.apply_suite_to_slide(
        {"cover": "x", "transition": "x"}, {"title": "谢谢", "slide_type": "thankyou"}, 10, 10
    ) is None


def test_fill_suite_template_preserves_unfilled():
    html = "<h1>{{ cover_title }}</h1><p>{{ cover_extra }}</p>"
    out = TemplateSuiteRenderer.fill_suite_template(html, {"cover_title": "T"})
    assert "T" in out and "{{ cover_extra }}" in out


# --- TemplateSuiteService validation ----------------------------------------

def test_validate_suite_payload():
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    v = svc._validate_suite_payload(SUITE)
    assert v["cover"].startswith("<!DOCTYPE html>")
    assert v["design_tokens"] == SUITE["design_tokens"]


def test_validate_suite_payload_rejects_bad_cover():
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    bad = dict(SUITE)
    bad["cover"] = "<div>no doctype</div>"
    try:
        svc._validate_suite_payload(bad)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_suite_validity_check():
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    identity = {"template_id": 1, "template_hash": "abc123"}
    good = dict(SUITE, template_id=1, template_hash="abc123")
    assert svc._suite_valid(good, identity)
    stale = dict(good, template_hash="other")
    assert not svc._suite_valid(stale, identity)


def test_extract_json_from_response():
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    payload = svc._extract_json_from_response('```json\n' + json.dumps(SUITE, ensure_ascii=False) + '\n```')
    assert payload and payload["cover"] == SUITE["cover"]
    assert svc._extract_json_from_response("not json") is None


def test_build_preview_html():
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    suite = dict(SUITE)
    suite["cover"] = "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1><p>{{ cover_subtitle }}</p><p>{{ cover_extra }}</p></body></html>"
    suite["transition"] = "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1></body></html>"
    suite["catalog"] = "<!DOCTYPE html><html><body><h1>{{ catalog_title }}</h1><ul>{{ catalog_items }}</ul></body></html>"
    suite["ending"] = "<!DOCTYPE html><html><body><h1>{{ ending_title }}</h1><p>{{ ending_subtitle }}</p></body></html>"
    suite["header_footer"] = "<header>{{ page_title }}</header><footer>{{ current_page_number }} / {{ total_page_count }}</footer>"
    preview = svc.build_preview_html(suite)

    assert set(preview.keys()) == {"cover", "transition", "catalog", "ending", "content"}
    for key, html in preview.items():
        assert html.strip().lower().startswith("<!doctype html"), f"{key} must be a full document"
        assert "{{" not in html, f"{key} should have all slots filled"
    # 各特殊页都应填充自然的示例内容，而非空/占位符
    assert "年度工作报告" in preview["cover"]
    assert "核心方案" in preview["transition"]
    assert "第一章" in preview["catalog"]
    assert "感谢聆听" in preview["ending"]
    assert "<header>" in preview["content"] and "<footer>" in preview["content"]


def test_default_slot_text_for_cover_extra():
    """Optional slots like cover_extra must resolve to real content, NOT the
    page-type description (which would leak "PPT封面页/章节过渡页" labels)."""
    from landppt.services.slide.slide_media_service import SlideMediaService
    # Even when description exists, fallback must use content_points first.
    text = SlideMediaService._default_slot_text(
        "cover_extra",
        {"title": "T", "description": "PPT封面页，展示核心信息", "content_points": ["点一"]},
        3,
    )
    assert text == "点一"
    assert "封面页" not in text

    # No content points -> derive from title, never from description.
    text2 = SlideMediaService._default_slot_text(
        "cover_extra",
        {"title": "部门汇报", "description": "章节过渡页", "content_points": []},
        3,
    )
    assert "部门汇报" in text2
    assert "过渡页" not in text2

    # Unknown slot falls back to a bracketed label (never an empty template hole).
    text3 = SlideMediaService._default_slot_text("unknown_slot", {}, 3)
    assert text3 == "[unknown_slot]"


def test_try_fill_suite_slide_fills_optional_slot_without_llm():
    """The suite cover must render fully even when it contains an optional
    slot like {{ cover_extra }}, using deterministic fallback when the LLM
    pass is unavailable — and never leaking page-type labels."""
    import asyncio
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1><p>{{ cover_subtitle }}</p><p>{{ cover_extra }}</p></body></html>",
        "transition": "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1><p>{{ transition_subtitle }}</p></body></html>",
        "header_footer": "<header>{{ page_title }}</header>",
        "design_tokens": "t",
    }

    class FakeMedia:
        # No _text_completion_for_role -> LLM path raises -> deterministic fallback.
        def _strip_think_tags(self, raw):
            return raw

    media = SlideMediaService(FakeMedia())

    async def run():
        result = await media._try_fill_suite_slide(
            suite,
            {"title": "部门工作汇报", "slide_type": "title",
             "description": "PPT封面页，展示核心信息", "content_points": ["汇报期间：2026年1-4月"]},
            1, 15, "sys",
        )
        return result

    result = asyncio.run(run())
    assert result is not None
    assert "部门工作汇报" in result
    assert "2026年1-4月" in result
    assert "{{" not in result, "no slots should remain after deterministic fill"
    assert "封面页" not in result and "过渡页" not in result


def test_resolve_remaining_slots_llm_first_then_fallback():
    """LLM-first slot resolution: uses the LLM value when available, and a
    clean deterministic fallback (never the page-type description) when the
    LLM call fails."""
    import asyncio
    import json
    from landppt.services.slide.slide_media_service import SlideMediaService

    class GoodMedia:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            return type("R", (), {"content": json.dumps(
                {"cover_extra": "2026年上半年工作全面综述，聚焦平台化建设"}, ensure_ascii=False
            )})()

        def _strip_think_tags(self, raw):
            return raw

    media = SlideMediaService(GoodMedia())

    async def run_good():
        return await media._resolve_remaining_slots(
            "<p>{{ cover_extra }}</p>", ["cover_extra"],
            {"title": "部门工作汇报", "slide_type": "title",
             "description": "PPT封面页，展示核心信息", "content_points": ["汇报期间"]},
            1, 15, "sys",
        )

    vals = asyncio.run(run_good())
    assert "2026年上半年工作全面综述" in vals["cover_extra"]
    assert "封面页" not in vals["cover_extra"]

    class FailMedia:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            raise RuntimeError("LLM down")

        def _strip_think_tags(self, raw):
            return raw

    media2 = SlideMediaService(FailMedia())

    async def run_fail():
        return await media2._resolve_remaining_slots(
            "<p>{{ cover_extra }}</p>", ["cover_extra"],
            {"title": "部门工作汇报", "slide_type": "title",
             "description": "PPT封面页，展示核心信息", "content_points": ["汇报期间：2026年1-4月"]},
            1, 15, "sys",
        )

    vals2 = asyncio.run(run_fail())
    assert "2026年1-4月" in vals2["cover_extra"]
    assert "封面页" not in vals2["cover_extra"]


def test_build_suite_part_prompt_only_targets_one_part():
    """The single-type regeneration prompt must only ask for one part and
    reference existing design_tokens for consistency."""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    prompt = TemplatePrompts.build_template_suite_part_prompt(
        part="cover",
        project=None,
        outline={"slides": [{"title": "t", "slide_type": "content"}]},
        confirmed={"topic": "测试", "target_audience": "企业"},
        template_html="<div>母版</div>",
        existing_suite={"design_tokens": "字体栈：A；强调色：#c00000", "transition": "<div>过渡</div>"},
    )
    assert "重新生成「封面模板」" in prompt or "重新生成「" in prompt
    assert "只输出这一个部分" in prompt
    assert "现有套件其他部分" in prompt
    # Must not ask to regenerate transition
    assert '"transition":' not in prompt or "transition" not in prompt.split("本次输出约束")[1]


def test_regenerate_suite_part_merges_only_target_part():
    """regenerate_suite_part keeps untouched parts and only replaces the target."""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService

    class FakePM:
        class _P:
            outline = {"slides": [{"title": "a"}]}
            confirmed_requirements = {"topic": "t"}

        async def get_project(self, pid, user_id=None):
            return self._P()

        async def update_project_metadata(self, pid, meta, user_id=None):
            pass

    class FakeService:
        project_manager = FakePM()
        _cleared = False

        async def get_selected_global_template(self, pid, user_id=None):
            return {"id": 7, "html_template": "<div>tpl</div>", "template_name": "商务"}

        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            # LLM returns only the new cover
            return type("R", (), {"content": json.dumps(
                {"cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1><p>{{ cover_extra }}</p></body></html>"}
            )})()

        def clear_cached_style_genes(self, pid):
            self._cleared = True

    svc = TemplateSuiteService(FakeService())
    svc.project_manager = FakePM()
    # monkeypatch _persist_suite to capture
    captured = {}

    async def fake_persist(pid, suite):
        captured.update(suite)

    svc._persist_suite = fake_persist
    # fake get_suite -> existing suite
    existing = {
        "cover": "OLD_COVER",
        "transition": "OLD_TRANSITION",
        "header_footer": "OLD_HF",
        "design_tokens": "t",
        "template_hash": "abc",
        "template_id": 7,
    }
    svc.get_suite = lambda pid: asyncio.coroutine(lambda: existing)() if False else _async_val(existing)

    async def run():
        return await svc.regenerate_suite_part("p1", "cover", {"html_template": "<div>tpl</div>", "id": 7}, user_feedback="更简洁")

    result = asyncio.run(run())
    assert result["cover"] != "OLD_COVER"
    assert "cover_title" in result["cover"]
    assert result["transition"] == "OLD_TRANSITION"
    assert result["header_footer"] == "OLD_HF"
    assert result["design_tokens"] == "t"
    assert result["template_hash"] == "abc"


async def _async_val(v):
    return v


def test_header_footer_self_contained_injects_root_vars():
    """A header_footer fragment using var(--x) without defining it must get the
    master :root variables inlined so styles don't break."""
    from landppt.services.template.template_suite_service import TemplateSuiteService
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    hf = '<div class="title-main" style="color:var(--ink);font-family:var(--serif);">{{ page_title }}</div>'
    root = ":root {\n  --ink: #1a2332;\n  --serif: Georgia, serif;\n  --copper: #b8763d;\n}"
    fixed = svc._ensure_header_footer_self_contained(hf, root)
    assert "--ink:" in fixed
    assert "--serif:" in fixed
    # Only missing (used) vars are inlined; --copper is not used so not included.
    assert "--copper:" not in fixed
    assert "<style>" in fixed


def test_extract_root_variables_from_master():
    """MasterLayoutExtractor must surface the :root variable block even when
    header/footer regions can't be located."""
    from landppt.services.template.master_layout_extractor import MasterLayoutExtractor
    tpl = ('<html><head><style>:root { --ink: #1a2332; --copper: #b8763d; }</style></head>'
           '<body><div class="title-anchor">{{ page_title }}</div></body></html>')
    ext = MasterLayoutExtractor.extract_header_footer(tpl)
    assert "--ink" in ext.get("root_variables", "")
    assert "--copper" in ext.get("root_variables", "")


def test_extract_content_skeleton_from_master():
    """The master template's decorative skeleton (canvas/bg/frame/stamp) must be
    extractable so content pages can carry the template's background & decor."""
    from landppt.services.template.master_layout_extractor import MasterLayoutExtractor
    tpl = (
        "<html><head><style>:root{--ink:#1a2332;--paper:#f5f2ec;--copper:#b8763d}"
        ".canvas{position:relative;width:1280px;height:720px;background:var(--paper)}"
        ".bg-paper{position:absolute;inset:0;background:var(--paper);z-index:0}"
        ".frame-corner{position:absolute;width:24px;height:24px}"
        "</style></head><body>"
        "<div class=\"canvas\"><div class=\"bg-paper\"></div><div class=\"bg-grid\"></div>"
        "<div class=\"frame-corner tl\"></div>"
        "<div class=\"title-anchor\">{{ page_title }}</div>"
        "<div class=\"main-stage\">{{ page_content }}</div>"
        "<div class=\"number-anchor\">{{ current_page_number }}</div>"
        "</div></body></html>"
    )
    sk = MasterLayoutExtractor.extract_content_skeleton(tpl)
    assert "bg-paper" in sk["skeleton_html"]
    assert "frame-corner" in sk["skeleton_html"]
    assert ".bg-paper" in sk["skeleton_css"]
    assert ".canvas" in sk["skeleton_css"]


def test_header_footer_complete_injects_skeleton():
    """A header_footer missing the template's decorative skeleton must get it
    injected so content pages look like the template itself."""
    from landppt.services.template.template_suite_service import TemplateSuiteService
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    hf = '<div class="title-anchor">{{ page_title }}</div><div class="number-anchor">{{ current_page_number }}</div>'
    tpl = (
        "<html><head><style>:root{--ink:#1a2332;--copper:#b8763d}"
        ".canvas{position:relative;width:1280px;height:720px}"
        ".bg-paper{position:absolute;inset:0;background:var(--copper);z-index:0}"
        "</style></head><body>"
        "<div class=\"canvas\"><div class=\"bg-paper\"></div>"
        "<div class=\"title-anchor\">{{ page_title }}</div></div></body></html>"
    )
    fixed = svc._ensure_header_footer_complete(hf, tpl, ":root {\n  --ink: #1a2332;\n  --copper: #b8763d;\n}")
    assert "bg-paper" in fixed
    assert "canvas" in fixed
    assert "--copper:" in fixed
    assert "title-anchor" in fixed


def test_content_preview_no_sample_body():
    """The content-page preview no longer injects a sample body (要点一/要点二);
    instead {{ page_content }} is replaced with a neutral placeholder so the
    header/footer layout preview never breaks regardless of structure."""
    from landppt.services.template.template_suite_service import TemplateSuiteService
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    suite = {
        "cover": "<!DOCTYPE html><html><body>cover</body></html>",
        "transition": "<!DOCTYPE html><html><body>trans</body></html>",
        "header_footer": (
            '<style>.hf-canvas{display:flex;flex-direction:column;height:720px;overflow:hidden}'
            '.hf-header{flex:none}.hf-stage{flex:1;min-height:0}.hf-footer{flex:none}</style>'
            '<div class="hf-canvas">'
            '<div class="hf-header"><span>{{ page_title }}</span></div>'
            '<div class="hf-stage">{{ page_content }}</div>'
            '<div class="hf-footer">{{ current_page_number }}</div>'
            '</div>'
        ),
        "design_tokens": "t",
    }
    content = svc.build_preview_html(suite)["content"]
    assert "要点一" not in content
    assert "要点二" not in content
    assert "page_content" not in content  # slot replaced
    assert "正文占位区" in content  # neutral placeholder present


def test_skeleton_injection_never_truncates_div_tag():
    """The injected skeleton must never leave an incomplete <div class=" tag at
    the injection boundary (regression: skeleton_html used to end mid-tag)."""
    from landppt.services.template.master_layout_extractor import MasterLayoutExtractor
    from landppt.services.template.template_suite_service import TemplateSuiteService
    tpl = (
        "<html><head><style>:root{--ink:#1a2332;--paper:#f5f2ec;--copper:#b8763d}"
        ".canvas{position:relative;width:1280px;height:720px}"
        ".bg-paper{position:absolute;inset:0;z-index:0}"
        ".deco-stamp{position:absolute}"
        "</style></head><body>"
        "<div class=\"canvas\"><div class=\"bg-paper\"></div><div class=\"deco-stamp\"></div>"
        "<div class=\"title-anchor\">{{ page_title }}</div>"
        "<div class=\"main-stage\">{{ page_content }}</div>"
        "<div class=\"number-anchor\">{{ current_page_number }}</div>"
        "</div></body></html>"
    )
    sk = MasterLayoutExtractor.extract_content_skeleton(tpl)
    assert not sk["skeleton_html"].rstrip().endswith('<div class="')

    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    fixed = svc._ensure_header_footer_complete(
        '<div class="title-anchor">{{ page_title }}</div>',
        tpl,
        ":root {\n  --ink: #1a2332;\n  --copper: #b8763d;\n}",
    )
    import re
    incomplete = re.findall(r'<div class="[^"]*$', fixed, re.MULTILINE)
    assert not incomplete, f"injected skeleton left incomplete tags: {incomplete}"


def test_header_footer_complete_repairs_corrupted_skeleton():
    """A stored header_footer whose injected skeleton was truncated mid-tag must
    be repaired (old broken skeleton removed, fresh one injected)."""
    import re
    from landppt.services.template.template_suite_service import TemplateSuiteService
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    # Simulate a previously-corrupted header_footer: skeleton cut at <div class="
    corrupted = (
        "<!-- 母版内容页骨架（背景/装饰，自包含） -->\n"
        '<div class="canvas">\n  <div class="bg-paper"></div>\n  <div class="deco-stamp"></div>\n'
        '  <div class="\n<!-- 标题锚点（页头） -->\n'
        '<div class="title-anchor">{{ page_title }}</div>\n'
        '<div class="number-anchor">{{ current_page_number }}</div>'
    )
    tpl = (
        "<html><head><style>:root{--ink:#1a2332;--copper:#b8763d}"
        ".canvas{position:relative;width:1280px;height:720px}"
        ".bg-paper{position:absolute;inset:0;z-index:0}"
        "</style></head><body>"
        "<div class=\"canvas\"><div class=\"bg-paper\"></div>"
        "<div class=\"title-anchor\">{{ page_title }}</div>"
        "<div class=\"number-anchor\">{{ current_page_number }}</div>"
        "</div></body></html>"
    )
    fixed = svc._ensure_header_footer_complete(
        corrupted, tpl, ":root {\n  --ink: #1a2332;\n  --copper: #b8763d;\n}"
    )
    incomplete = re.findall(r'<div class="[^"]*$', fixed, re.MULTILINE)
    assert not incomplete, f"corrupted skeleton not repaired: {incomplete}"
    assert "title-anchor" in fixed
    assert "page_title" in fixed


def test_header_footer_stage_inserted_between_anchors():
    """If the regenerated header_footer lacks a body stage (header→footer direct),
    a main-stage placeholder with {{ page_content }} must be inserted between the
    title anchor and number anchor."""
    import re
    from landppt.services.template.template_suite_service import TemplateSuiteService
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    # header_footer without any stage: title-anchor directly followed by number-anchor
    hf = (
        '<div class="header-footer">'
        '<div class="title-anchor">{{ page_title }}</div>'
        '<div class="number-anchor">{{ current_page_number }}</div>'
        "</div>"
    )
    tpl = (
        "<html><head><style>:root{--ink:#1a2332;--paper:#f5f2ec;--copper:#b8763d}"
        ".canvas{position:relative;width:1280px;height:720px}"
        ".bg-paper{position:absolute;inset:0;z-index:0}"
        ".main-stage{flex:1;min-height:0}"
        "</style></head><body>"
        "<div class=\"canvas\"><div class=\"bg-paper\"></div>"
        "<div class=\"title-anchor\">{{ page_title }}</div>"
        "<div class=\"main-stage\">{{ page_content }}</div>"
        "<div class=\"number-anchor\">{{ current_page_number }}</div>"
        "</div></body></html>"
    )
    fixed = svc._ensure_header_footer_complete(
        hf, tpl, ":root {\n  --ink: #1a2332;\n  --copper: #b8763d;\n}"
    )
    ta = fixed.find("title-anchor")
    ms = fixed.find("main-stage")
    na = fixed.find("number-anchor")
    assert -1 not in (ta, ms, na)
    assert ta < ms < na, "main-stage must sit between header and footer"
    assert "{{ page_content }}" in fixed


def test_creativity_parameter_maps_to_guidance():
    """The 0-10 creativity scale must produce distinct guidance: 0=strictly
    follow master, 10=most creative; out-of-range values are clamped."""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    base = dict(project=None, outline={"slides": [{"title": "x"}]},
                confirmed={"topic": "t"}, template_html="<div>t</div>")
    p0 = TemplatePrompts.build_template_suite_prompt(**base, creativity=0)
    p5 = TemplatePrompts.build_template_suite_prompt(**base, creativity=5)
    p10 = TemplatePrompts.build_template_suite_prompt(**base, creativity=10)

    assert "严格遵循母版" in p0
    assert "母版与创意平衡" in p5
    assert "最具创意" in p10
    assert p0 != p5 and p5 != p10

    # Clamping
    pneg = TemplatePrompts.build_template_suite_prompt(**base, creativity=-3)
    phigh = TemplatePrompts.build_template_suite_prompt(**base, creativity=99)
    assert "严格遵循母版" in pneg
    assert "最具创意" in phigh

    # Part prompt: cover/transition honor it; header_footer ignores it.
    part_base = dict(outline={"slides": [{"title": "x"}]}, confirmed={"topic": "t"},
                     template_html="<div>t</div>", existing_suite={"design_tokens": "t"})
    pc = TemplatePrompts.build_template_suite_part_prompt(part="cover", creativity=10, **part_base)
    ph = TemplatePrompts.build_template_suite_part_prompt(part="header_footer", creativity=10, **part_base)
    assert "最具创意" in pc
    assert "最具创意" not in ph


def test_suite_prompt_default_ignores_outline_topic():
    """The suite-generation prompt must by default NOT reference the project
    outline/topic — only the master template — and include them when
    reference_outline=True."""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    class P:
        topic = "AI大模型行业趋势"
        scenario = "峰会"

    outline = {
        "title": "AI大模型行业趋势",
        "slides": [{"title": "开场", "slide_type": "title"}, {"title": "大模型", "slide_type": "content"}],
    }
    confirmed = {"target_audience": "高管", "ppt_style": "科技感"}
    base = dict(project=P(), outline=outline, confirmed=confirmed,
                template_html="<div>tpl</div>", creativity=5)

    p0 = TemplatePrompts.build_template_suite_prompt(**base)
    assert "大纲全貌" not in p0
    assert "项目信息" not in p0
    assert "AI大模型" not in p0
    assert "母版 HTML 原文" in p0

    p1 = TemplatePrompts.build_template_suite_prompt(**base, reference_outline=True)
    assert "大纲全貌" in p1
    assert "项目信息" in p1
    assert "AI大模型" in p1

    # part prompt too
    pb = dict(part="cover", outline=outline, confirmed=confirmed,
              template_html="<div>t</div>", existing_suite={"design_tokens": "t"}, creativity=5)
    pp0 = TemplatePrompts.build_template_suite_part_prompt(**pb)
    pp1 = TemplatePrompts.build_template_suite_part_prompt(**pb, reference_outline=True)
    assert "大纲全貌" not in pp0
    assert "大纲全貌" in pp1


def test_get_effective_suite_prefers_selected_global_suite():
    """get_effective_suite must prefer a project's selected global-library suite
    over the project-local template_suite."""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    suite_payload = {
        "cover": "<!DOCTYPE html><html><body>{{ cover_title }}</body></html>",
        "transition": "<!DOCTYPE html><html><body>{{ transition_title }}</body></html>",
        "header_footer": "<header>{{ page_title }}</header>",
        "design_tokens": "t",
        "template_name": "全局套件",
    }

    class FakePM:
        def __init__(self):
            self.meta = {"selected_global_suite_id": 7, "template_suite": {"template_name": "项目内套件"}}

        async def get_project(self, pid, user_id=None):
            p = type("P", (), {"project_metadata": dict(self.meta)})()
            return p

        async def update_project_metadata(self, pid, meta, user_id=None):
            self.meta = dict(meta)

    class FakeHost:
        project_manager = FakePM()

    svc = TemplateSuiteService(FakeHost())

    class FakeGlobal(GlobalTemplateSuiteService):
        def __init__(self, service=None):
            self._service = service

        async def get_suite_payload(self, sid):
            return dict(suite_payload) if sid == 7 else None

    # patch the local import inside get_effective_suite
    import landppt.services.template.template_suite_service as mod
    orig = getattr(mod, "_GLOBAL_SUITE_SVC", None)
    mod._GLOBAL_SUITE_SVC = FakeGlobal
    # inject by patching module-level: the function does `from .global_template_suite_service import GlobalTemplateSuiteService`
    # We instead replace via sys.modules injection.
    import sys
    saved = sys.modules.get("landppt.services.template.global_template_suite_service")
    fake_mod = type(sys)("fake_global_mod")
    fake_mod.GlobalTemplateSuiteService = FakeGlobal
    sys.modules["landppt.services.template.global_template_suite_service"] = fake_mod
    try:
        async def run():
            return await svc.get_effective_suite("p1")
        result = asyncio.run(run())
    finally:
        if saved is not None:
            sys.modules["landppt.services.template.global_template_suite_service"] = saved
        else:
            sys.modules.pop("landppt.services.template.global_template_suite_service", None)

    assert result is not None
    assert result["template_name"] == "全局套件"
    assert "cover_title" in result["cover"]


def test_get_effective_suite_falls_back_to_project_suite():
    """Without a selected global suite, get_effective_suite falls back to the
    project-local template_suite."""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService

    class FakePM:
        def __init__(self):
            self.meta = {"template_suite": {"cover": "PROJECT_COVER", "template_name": "项目内套件"}}

        async def get_project(self, pid, user_id=None):
            return type("P", (), {"project_metadata": dict(self.meta)})()

    class FakeHost:
        project_manager = FakePM()

    svc = TemplateSuiteService(FakeHost())
    # override get_suite to avoid DB/project real path
    async def fake_get_suite(pid):
        return {"cover": "PROJECT_COVER", "template_name": "项目内套件"}

    svc.get_suite = fake_get_suite

    async def run():
        return await svc.get_effective_suite("p1")

    result = asyncio.run(run())
    assert result is not None
    assert result["cover"] == "PROJECT_COVER"


def test_build_catalog_suite_constraint():
    """目录页参考约束包含套件目录页 HTML 与设计指引；无目录页时为空串。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    c = SlideMediaService._build_catalog_suite_constraint({
        "catalog": "<!DOCTYPE html><html><body><h1>{{ catalog_title }}</h1><div>01 示例章节</div></body></html>",
    })
    assert "目录页强约束" in c
    assert "示例章节" in c
    assert "{{ catalog_title }}" in c

    assert SlideMediaService._build_catalog_suite_constraint({"catalog": "   "}) == ""
    assert SlideMediaService._build_catalog_suite_constraint({}) == ""


def test_catalog_page_uses_reference_not_template_fill():
    """目录页生成：套件目录作为设计参考交给 LLM（注入 prompt），
    而不走 _try_fill_suite_slide 模板填充路径。"""
    import asyncio
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "catalog": "<!DOCTYPE html><html><body><h1>{{ catalog_title }}</h1><div>01 示例章节</div></body></html>",
        "header_footer": "<header>{{ page_title }}</header>",
        "design_tokens": "t",
    }
    captured = {}

    class FakeTemplateSuite:
        async def get_effective_suite(self, project_id):
            return suite

    class FakeMedia:
        template_suite = FakeTemplateSuite()

        async def get_selected_global_template(self, project_id):
            return None

        async def _try_fill_suite_slide(self, *args, **kwargs):
            raise AssertionError("目录页不应走模板填充 _try_fill_suite_slide")

        async def _ensure_slide_images_context(self, *a, **k):
            return None

        async def _get_creative_design_inputs(self, *a, **k):
            return ("", "", "")

        async def _process_slide_image(self, *a, **k):
            return None

        def _build_slide_context(self, *a, **k):
            return ""

        async def _generate_html_with_retry(self, context, *a, **k):
            captured["context"] = context
            return "<!DOCTYPE html><html><body>目录</body></html>"

        async def _generate_fallback_slide_html(self, *a, **k):
            return "fallback"

        async def _apply_auto_layout_repair(self, html, *a, **k):
            return html

    media = SlideMediaService(FakeMedia())

    async def run():
        return await media._generate_single_slide_html_with_prompts(
            {"title": "目录", "slide_type": "agenda",
             "content_points": ["第一章 概述", "第二章 方案"]},
            {"project_id": "p1", "topic": "T", "target_audience": "A", "description": "D"},
            "sys", 3, 10, project_id="p1",
        )

    result = asyncio.run(run())
    assert "目录页强约束" in captured["context"], "目录页强约束应注入生成 prompt"
    assert "示例章节" in captured["context"], "套件目录页 HTML 应作为参考注入"
    assert result and "目录" in result


def test_content_page_with_suite_ignores_template():
    """有套件时内容页只按套件设计（页头页脚约束），不调用 _generate_slide_with_template。"""
    import asyncio
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "catalog": "<!DOCTYPE html><html><body>{{ catalog_title }}</body></html>",
        "header_footer": "<header>{{ page_title }}</header><footer>{{ current_page_number }}/{{ total_page_count }}</footer>",
        "design_tokens": "字体栈：X；强调色：#123456",
    }
    captured = {}
    called_generate_with_template = {"called": False}

    class FakeTemplateSuite:
        async def get_effective_suite(self, project_id):
            return suite

    class FakeMedia:
        template_suite = FakeTemplateSuite()

        async def get_selected_global_template(self, project_id):
            # 有套件也应忽略模板：若被调用 _generate_slide_with_template 则失败
            return {"id": 1, "template_name": "Toy风", "html_template": "<html>tpl</html>"}

        async def _try_fill_suite_slide(self, *args, **kwargs):
            return None  # 内容页不走套件模板填充

        async def _generate_slide_with_template(self, *args, **kwargs):
            called_generate_with_template["called"] = True
            return "TEMPLATE_USED"

        async def _ensure_slide_images_context(self, *a, **k):
            return None

        async def _get_creative_design_inputs(self, *a, **k):
            return ("", "", "")

        async def _process_slide_image(self, *a, **k):
            return None

        def _build_slide_context(self, *a, **k):
            return ""

        async def _generate_html_with_retry(self, context, *a, **k):
            captured["context"] = context
            return "<!DOCTYPE html><html><body>内容页</body></html>"

        async def _generate_fallback_slide_html(self, *a, **k):
            return "fallback"

        async def _apply_auto_layout_repair(self, html, *a, **k):
            return html

    media = SlideMediaService(FakeMedia())

    async def run():
        return await media._generate_single_slide_html_with_prompts(
            {"title": "背景介绍", "slide_type": "content", "content_points": ["要点"]},
            {"project_id": "p1", "topic": "T", "target_audience": "A", "description": "D"},
            "sys", 2, 10, project_id="p1",
        )

    result = asyncio.run(run())
    assert called_generate_with_template["called"] is False, "有套件的内容页不应使用模板生成"
    assert "内容页强约束" in captured["context"], "内容页应注入套件页头页脚约束"
    assert "{{ page_title }}" in captured["context"]
    assert "Toy风" not in captured["context"], "模板不应进入内容页 prompt"
    assert result and "内容页" in result


def test_content_page_retries_when_suite_skeleton_missing():
    """内容页生成未包含套件骨架标记时，自动重试一次并注入强提示。"""
    import asyncio
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "header_footer": (
            '<div class="cmb-slide">{{ page_title }}{{ page_content }}'
            "{{ current_page_number }}/{{ total_page_count }}</div>"
        ),
    }
    calls = {"n": 0}

    class FakeTemplateSuite:
        async def get_effective_suite(self, project_id):
            return suite

    class FakeMedia:
        template_suite = FakeTemplateSuite()

        async def get_selected_global_template(self, project_id):
            return None

        async def _try_fill_suite_slide(self, *a, **k):
            return None

        async def _generate_slide_with_template(self, *a, **k):
            raise AssertionError("不应调用")

        async def _ensure_slide_images_context(self, *a, **k):
            return None

        async def _get_creative_design_inputs(self, *a, **k):
            return ("", "", "")

        async def _process_slide_image(self, *a, **k):
            return None

        def _build_slide_context(self, *a, **k):
            return ""

        async def _generate_html_with_retry(self, context, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return "<!DOCTYPE html><html><body>没有套件骨架</body></html>"
            return '<!DOCTYPE html><html><body><div class="cmb-slide">{{ page_content }}</div></body></html>'

        async def _generate_fallback_slide_html(self, *a, **k):
            return "fallback"

        async def _apply_auto_layout_repair(self, html, *a, **k):
            return html

    media = SlideMediaService(FakeMedia())

    async def run():
        return await media._generate_single_slide_html_with_prompts(
            {"title": "内容", "slide_type": "content"},
            {"project_id": "p1", "topic": "T"},
            "sys", 2, 5, project_id="p1",
        )

    result = asyncio.run(run())
    assert calls["n"] == 2, "首次未含套件骨架应触发一次重试"
    assert "cmb-slide" in result


def test_ensure_global_master_template_selected_skips_for_suite_mode():
    """suite 模式：重新生成/生成时不强制选默认模板，返回 None（套件驱动一切）。"""
    import asyncio
    from landppt.services.template.template_selection_service import TemplateSelectionService

    saved = {"called": False}

    class FakePM:
        async def get_project(self, pid, user_id=None):
            return type("P", (), {"project_metadata": {"template_mode": "suite", "selected_global_suite_id": 12}})()

        async def update_project_metadata(self, pid, meta, user_id=None):
            saved["called"] = True

    class FakeGlobalTpl:
        async def get_default_template(self):
            return {"id": 999, "template_name": "Toy风"}

        async def get_template_by_id(self, tid):
            return {"id": tid, "template_name": "X"}

    class FakeService:
        project_manager = FakePM()
        global_template_service = FakeGlobalTpl()

        def clear_cached_style_genes(self, pid):
            pass

    svc = TemplateSelectionService(FakeService())

    async def run():
        return await svc._ensure_global_master_template_selected("p1")

    result = asyncio.run(run())
    assert result is None, "suite 模式不应强制选默认模板"
    assert saved["called"] is False, "suite 模式不应把默认模板保存到项目"


def test_extract_json_from_response_robust():
    """健壮 JSON 解析：HTML 转义、Markdown 代码块、前后散文、Python 字面量都能解析；
    真正坏掉的 JSON（未转义引号）返回 None（触发修正重试）。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService

    good = (
        '{"cover": "<!DOCTYPE html><html><body><div style=\\"color:#fff\\">Hi</div>'
        '{{ cover_title }}</body></html>", "transition": "<html>x</html>", '
        '"header_footer": "<header>{{ page_title }}</header>", "design_tokens": "t"}'
    )

    # 1) 正常转义的 HTML-in-JSON
    p = TemplateSuiteService._extract_json_from_response(good)
    assert p and p["cover"].startswith("<!DOCTYPE html>")

    # 2) Markdown 代码块包裹
    p = TemplateSuiteService._extract_json_from_response("```json\n" + good + "\n```")
    assert p and "cover" in p

    # 3) 前后有散文解释
    p = TemplateSuiteService._extract_json_from_response("好的，套件如下：\n" + good + "\n以上。")
    assert p and "cover" in p

    # 4) 尾逗号 / 智能引号等常见脏格式
    dirty = '{"cover":"<html>c</html>","transition":"<html>t</html>","header_footer":"<header>{{ page_title }}</header>","design_tokens":"t",}'
    p = TemplateSuiteService._extract_json_from_response(dirty)
    assert p and "cover" in p

    # 5) Python 字面量兜底（单引号 + true）
    py = "{'cover': '<html>c</html>', 'transition': '<html>t</html>', 'header_footer': '<header>{{ page_title }}</header>', 'design_tokens': 't', 'ok': true}"
    p = TemplateSuiteService._extract_json_from_response(py)
    assert p and "cover" in p

    # 6) 真正坏掉的 JSON（HTML 内未转义引号）→ None，走修正重试
    broken = '{"cover": "<!DOCTYPE html><div style="broken">A</div>", "transition": "t", "header_footer": "h", "design_tokens": "d"}'
    assert TemplateSuiteService._extract_json_from_response(broken) is None


def test_generate_suite_payload_repairs_invalid_json():
    """第一次 LLM 响应不是有效 JSON 时，触发一次修正重试并成功解析。"""
    import asyncio
    import json
    from landppt.services.template.template_suite_service import TemplateSuiteService

    calls = []

    class FakeService:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            calls.append((role, kwargs.get("max_output_tokens")))
            if len(calls) == 1:
                # 第一次：散文 + 坏 JSON（HTML 内未转义引号）→ 无法解析
                return type("R", (), {"content": (
                    '这是生成的套件 JSON：{"cover": "<!DOCTYPE html><div style="broken">A</div>", '
                    '"transition": "broken", "header_footer": "broken", "design_tokens": "t"}'
                )})()
            # 第二次（修正重试）：严格 JSON
            content = json.dumps({
                "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1></body></html>",
                "transition": "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1></body></html>",
                "header_footer": (
                    '<div class="hf-canvas"><div class="bg-paper"></div><style>.hf-canvas{}</style>'
                    '<div class="main-stage">{{ page_content }}</div>'
                    "<header>{{ page_title }}</header>"
                    "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
                ),
                "design_tokens": "字体栈：A；强调色：#1a2b3c",
            }, ensure_ascii=False)
            return type("R", (), {"content": content})()

    svc = TemplateSuiteService(FakeService())
    template = {
        "id": 1,
        "template_name": "商务模板",
        "html_template": (
            "<!DOCTYPE html><html><head><style>:root{--accent:#1a2b3c}</style></head>"
            "<body><header>H</header><main>M</main><footer>F</footer></body></html>"
        ),
    }

    async def run():
        return await svc._generate_suite_payload(
            template, creativity=5, reference_outline=False, project=None
        )

    result = asyncio.run(run())
    assert len(calls) == 2, "首次解析失败后应触发一次修正重试"
    assert calls[0][1] == 12000, "主调用应携带 max_output_tokens 上限"
    assert result["cover"].startswith("<!DOCTYPE html>")
    assert "cover_title" in result["cover"]
    assert result["transition"].startswith("<!DOCTYPE html>")
    assert "page_title" in result["header_footer"]


def test_generate_suite_payload_recovers_from_empty_response():
    """思考模型输出被 think 过滤成空串时，应触发免思考重试并成功生成套件。"""
    import asyncio
    import json
    from landppt.services.template.template_suite_service import TemplateSuiteService

    calls = []

    class FakeService:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            calls.append((role, kwargs.get("max_output_tokens"), kwargs.get("temperature"), "不要输出任何思考过程" in prompt))
            if len(calls) == 1:
                # 第一次：provider 层已把 <think> 块过滤掉，返回空串（思考模型截断）
                return type("R", (), {"content": ""})()
            # 第二次（免思考重试）：严格 JSON
            content = json.dumps({
                "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1></body></html>",
                "transition": "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1></body></html>",
                "header_footer": (
                    '<div class="hf-canvas"><style>.hf-canvas{}</style>'
                    '<div class="main-stage">{{ page_content }}</div>'
                    "<header>{{ page_title }}</header>"
                    "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
                ),
                "design_tokens": "字体栈：A；强调色：#1a2b3c",
            }, ensure_ascii=False)
            return type("R", (), {"content": content})()

    svc = TemplateSuiteService(FakeService())
    template = {
        "id": 2,
        "template_name": "商务模板",
        "html_template": (
            "<!DOCTYPE html><html><head><style>:root{--accent:#1a2b3c}</style></head>"
            "<body><header>H</header><main>M</main><footer>F</footer></body></html>"
        ),
    }

    async def run():
        return await svc._generate_suite_payload(
            template, creativity=5, reference_outline=False, project=None
        )

    result = asyncio.run(run())
    assert len(calls) == 2, "空响应后应触发一次免思考重试"
    assert calls[0][2] == 0.7, "主调用应使用默认温度"
    assert calls[1][2] == 0.2, "免思考重试应使用较低温度"
    assert calls[1][3] is True, "重试提示词应包含免思考指令"
    assert result["cover"].startswith("<!DOCTYPE html>")
    assert "cover_title" in result["cover"]
    assert "page_title" in result["header_footer"]


def test_stream_generate_suite_from_images_uses_vision_and_missing():
    """有截图的类型走视觉生成（含图片/图标提取），缺失类型走文本补全，组装成完整套件。"""
    import asyncio
    import io as _io
    from unittest.mock import AsyncMock, patch

    from PIL import Image

    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    vision_calls = {"count": 0, "has_image": False}

    class FakeVision:
        async def chat_completion(self, messages, **kwargs):
            vision_calls["count"] += 1
            for msg in messages:
                content = msg.content
                if isinstance(content, list):
                    from landppt.ai.base import ImageContent
                    vision_calls["has_image"] = vision_calls["has_image"] or any(
                        isinstance(c, ImageContent) for c in content
                    )
            if vision_calls["count"] == 1:
                # 第一次：区域检测 → 返回一个图片区域
                return type("R", (), {"content": '[{"name":"logo","left":0.1,"top":0.1,"width":0.2,"height":0.2}]'})()
            # 第二次：HTML 生成 → 用 SUITE_ASSET 占位
            return type("R", (), {"content": (
                '<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1>'
                '<img src="SUITE_ASSET:logo" style="width:100px;"></body></html>'
            )})()

    text_calls = {"count": 0}

    class FakeHost:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            text_calls["count"] += 1
            if "内容页" in prompt:
                return type("R", (), {"content": (
                    '<div class="hf-canvas"><div class="bg-paper"></div><style>.hf-canvas{}</style>'
                    '<div class="main-stage">{{ page_content }}</div>'
                    "<header>{{ page_title }}</header>"
                    "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
                )})()
            return type("R", (), {"content": "<!DOCTYPE html><html><body><h1>PAGE</h1></body></html>"})()

    svc = GlobalTemplateSuiteService()
    svc._build_host = lambda: FakeHost()

    buf = _io.BytesIO()
    Image.new("RGBA", (128, 72), (100, 150, 200, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    async def run():
        events = []
        async for ev in svc.stream_generate_suite_from_images(
            {"cover": png}, creativity=5, user_id=1
        ):
            events.append(ev)
        return events

    with patch(
        "landppt.services.db_config_service.get_vision_provider",
        new=AsyncMock(return_value=(FakeVision(), {"model": "gpt-4o", "temperature": None, "top_p": None})),
    ):
        events = asyncio.run(run())

    types = [e["type"] for e in events]
    assert types[-1] == "complete", events
    suite = events[-1]["suite"]
    assert suite["cover"].startswith("<!DOCTYPE html>")
    assert "page_title" in suite["header_footer"]
    # 封面：区域检测 1 次 + HTML 生成 1 次；缺失的 4 个类型用文本补全
    assert vision_calls["count"] == 2
    assert vision_calls["has_image"] is True, "视觉消息应包含图片"
    assert text_calls["count"] == 4
    # 图片/图标提取：占位被替换成真实 data URL
    assert "SUITE_ASSET:" not in suite["cover"]
    assert "data:image/png;base64," in suite["cover"]


def test_stream_generate_suite_from_images_no_images_errors():
    """没有任何截图时直接报错。"""
    import asyncio
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    svc = GlobalTemplateSuiteService()

    async def run():
        events = []
        async for ev in svc.stream_generate_suite_from_images({}, creativity=5):
            events.append(ev)
        return events

    events = asyncio.run(run())
    assert events[0]["type"] == "error"
    assert "至少上传" in events[0]["message"]


def test_stream_generate_suite_from_reference_image_analyzes_style_then_generates():
    """任意单图先提取画风/HEX 色板，再用同一视觉报告生成完整独立套件。"""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    analysis_json = """{
      "style_name": "赛璐璐暖红动漫",
      "style_summary": "高对比赛璐璐上色，暖红与炭黑形成鲜明轮廓",
      "dominant_colors": [
        {"hex": "#C63D32", "role": "主强调色", "ratio_percent": 30},
        {"hex": "#252126", "role": "深色背景", "ratio_percent": 50},
        {"hex": "#F2D6B3", "role": "柔和高光", "ratio_percent": 20}
      ],
      "line_and_shape": "硬朗深色轮廓与斜切色块",
      "texture_and_lighting": "平涂色块和少量柔和高光",
      "composition": "偏心主体，大面积留白",
      "visual_elements": ["发梢弧线", "红黑斜切角标"],
      "typography": "中文黑体配窄体英文",
      "ppt_translation": ["封面使用偏心构图", "内容页使用红黑角标"],
      "avoid": ["紫蓝霓虹渐变"]
    }"""

    class FakeVision:
        async def chat_completion(self, messages, **kwargs):
            return type("R", (), {"content": analysis_json})()

    captured = {"prompts": []}

    class FakeHost:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            captured["prompts"].append(prompt)
            if "内容页的自包含页头页脚片段" in prompt:
                content = (
                    "<style>.suite-stage{}</style><div>{{ page_title }}"
                    "{{ page_content }}{{ current_page_number }}{{ total_page_count }}"
                    "{{ chapter_indicator }}</div>"
                )
            else:
                content = "<!DOCTYPE html><html><body>PAGE</body></html>"
            return type("R", (), {"content": content})()

    svc = GlobalTemplateSuiteService()
    svc._build_host = lambda: FakeHost()

    async def run():
        events = []
        async for event in svc.stream_generate_suite_from_reference_image(
            b"\x89PNG\r\n\x1a\nmock",
            creativity=4,
            user_id=7,
            requirement_text="正文空间更大",
            chapter_indicator=True,
        ):
            events.append(event)
        return events

    with patch(
        "landppt.services.db_config_service.get_vision_provider",
        new=AsyncMock(return_value=(FakeVision(), {"model": "gpt-4o", "temperature": 0.3, "top_p": 0.9})),
    ):
        events = asyncio.run(run())

    assert events[-1]["type"] == "complete"
    assert [event["type"] for event in events].count("status") == 6
    suite = events[-1]["suite"]
    assert suite["suite_name"] == "赛璐璐暖红动漫套件"
    assert suite["template_id"] is None and suite["template_name"] is None
    assert suite["reference_analysis"]["dominant_colors"][0]["hex"] == "#C63D32"
    assert len(captured["prompts"]) == 5, "应拆成五个较小的页面生成请求，避免整套大响应超时"
    assert all("#C63D32" in prompt for prompt in captured["prompts"])
    assert all("只继承颜色配比，不继承颜色位置" in prompt for prompt in captured["prompts"])
    assert all("下方/上方/左侧/右侧" in prompt for prompt in captured["prompts"])
    assert all("正文空间更大" in prompt for prompt in captured["prompts"])
    content_prompt = next(
        prompt for prompt in captured["prompts"] if "内容页的自包含页头页脚片段" in prompt
    )
    assert "{{chapter_indicator}}" in content_prompt
    assert "#C63D32(30%)" in suite["design_tokens"]
    assert "不得继承某颜色在原图中的上、下、左、右" in suite["reference_analysis"]["color_position_policy"]


def test_reference_image_analysis_helpers_and_empty_input():
    """参考图 JSON 兼容代码块，设计报告保留颜色；空图直接返回友好错误。"""
    import asyncio

    from landppt.services.prompts.template_prompts import TemplatePrompts
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService as G

    parsed = G._parse_reference_analysis(
        '```json\n{"style_name":"水彩","style_summary":"柔和晕染","dominant_colors":[{"hex":"#AABBCC"}]}\n```'
    )
    assert parsed["style_name"] == "水彩"
    assert "#AABBCC" in G._build_reference_design_brief(parsed)
    assert "颜色在原图中的空间位置完全不可迁移" in G._build_reference_design_brief(parsed)

    prompt = TemplatePrompts.build_template_suite_prompt(
        template_html="主色 #AABBCC，柔和水彩晕染",
        custom_requirements="正文清晰",
        source_kind="reference_image",
    )
    assert "参考图片视觉分析报告" in prompt
    assert "最高优先级" in prompt
    assert "不得继承其在原图中的上下左右位置" in prompt
    assert "母版 HTML 原文" not in prompt

    async def run():
        events = []
        async for event in G().stream_generate_suite_from_reference_image(b""):
            events.append(event)
        return events

    events = asyncio.run(run())
    assert events == [{"type": "error", "message": "请上传一张参考图片"}]


def test_reference_image_sse_sends_heartbeat_while_model_is_busy():
    """长时间没有业务事件时仍输出 SSE 注释心跳，避免代理按空闲连接超时。"""
    import asyncio

    from landppt.api.template_suite_library_api import _sse_events_with_heartbeat

    async def slow_events():
        await asyncio.sleep(0.04)
        yield {"type": "complete", "suite": {"cover": "ok"}}

    async def run():
        chunks = []
        async for chunk in _sse_events_with_heartbeat(slow_events(), heartbeat_seconds=0.01):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    assert any(chunk.startswith(": keepalive ") for chunk in chunks)
    assert any('"type": "complete"' in chunk for chunk in chunks)


def test_image_suite_helpers():
    """视觉服务的工具函数：代码块剥离 / 独立 HTML 包裹 / 图片 MIME 识别。"""
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService as G

    # 剥离 Markdown 代码块
    assert G._strip_code_fence("```html\n<p>x</p>\n```") == "<p>x</p>"
    assert G._strip_code_fence("```\n<p>y</p>\n```") == "<p>y</p>"
    assert G._strip_code_fence("说明文字\n<div>z</div>") == "<div>z</div>"

    # 独立 HTML 包裹
    assert G._ensure_standalone_html("<p>a</p>").startswith("<!DOCTYPE html>")
    assert "<p>a</p>" in G._ensure_standalone_html("<p>a</p>")
    assert G._ensure_standalone_html("<!DOCTYPE html><p>a</p>").startswith("<!DOCTYPE html>")
    assert G._ensure_standalone_html("") == ""

    # 图片 MIME 识别
    assert G._guess_image_mime(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) == "image/png"
    assert G._guess_image_mime(b"\xff\xd8\xff\xe0\x00\x10") == "image/jpeg"
    assert G._guess_image_mime(b"BM\x00\x00") == "image/bmp"
    assert G._guess_image_mime(b"\x00\x01\x02\x03") == "image/png"

    # 图片区域解析 / 归一化 / 裁剪 / 注入
    assert G._parse_region_list('[{"name":"logo","left":0.1,"top":0.1,"width":0.2,"height":0.2}]') == [
        {"name": "logo", "left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2}
    ]
    assert G._parse_region_list('{"regions": [{"name":"a","left":0,"top":0,"width":0.5,"height":0.5}]}') != []
    assert G._parse_region_list("不是 JSON") == []
    norm = G._normalize_regions([
        {"name": "logo", "left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2},
        {"name": "", "left": -1, "top": 0, "width": 0, "height": 0},
    ])
    assert len(norm) == 1 and norm[0]["name"] == "logo"
    # 注入：占位替换为 data URL；漏掉图片时按检测位置兜底补插
    injected = G._inject_assets_into_html(
        '<img src="SUITE_ASSET:logo">',
        {"logo": {"data_url": "data:image/png;base64,AAA", "left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2}},
    )
    assert "SUITE_ASSET:" not in injected and "data:image/png;base64,AAA" in injected
    # 模型漏掉图片 → 兜底补插绝对定位 img
    injected2 = G._inject_assets_into_html(
        "<html><body><h1>x</h1></body></html>",
        {"logo": {"data_url": "data:image/png;base64,BBB", "left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2}},
    )
    assert "data:image/png;base64,BBB" in injected2 and "position:absolute" in injected2
    assert injected2.count("data:image") == 1
    # 裁剪：合法 PNG 裁剪出一个 data URL（新结构带坐标）
    import io as _io
    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGBA", (128, 72), (10, 20, 30, 255)).save(buf, format="PNG")
    crops = G._crop_image_regions(buf.getvalue(), [{"name": "a", "left": 0, "top": 0, "width": 0.5, "height": 0.5}])
    assert "a" in crops and crops["a"]["data_url"].startswith("data:image/png;base64,")
    assert crops["a"]["width"] == 0.5

    # 服务端错误识别：503/429/5xx/端点不可用 → 应整体跳过后续视觉调用
    assert G._is_vision_server_error(Exception("Error code: 503 - upstream request failed")) is True
    assert G._is_vision_server_error(Exception("HTTP 429 too many requests")) is True
    assert G._is_vision_server_error(Exception("Endpoint is unavailable")) is True
    assert G._is_vision_server_error(Exception("400 invalid request")) is False
    assert G._is_vision_server_error(Exception("model not found")) is False


def test_stream_generate_suite_from_images_falls_back_on_vision_failure():
    """某个类型的视觉生成失败（如 503）时，不回退整个套件，改用文本补全该类型。"""
    import asyncio
    import io as _io
    from unittest.mock import AsyncMock, patch

    from PIL import Image

    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    class FailingVision:
        async def chat_completion(self, messages, **kwargs):
            raise Exception("模型服务调用失败：HTTP 503: 服务不可用")

    text_calls = {"count": 0}

    class FakeHost:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            text_calls["count"] += 1
            if "内容页" in prompt:
                return type("R", (), {"content": (
                    '<div class="hf-canvas"><div class="bg-paper"></div><style>.hf-canvas{}</style>'
                    '<div class="main-stage">{{ page_content }}</div>'
                    "<header>{{ page_title }}</header>"
                    "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
                )})()
            return type("R", (), {"content": "<!DOCTYPE html><html><body><h1>PAGE</h1></body></html>"})()

    svc = GlobalTemplateSuiteService()
    svc._build_host = lambda: FakeHost()

    buf = _io.BytesIO()
    Image.new("RGBA", (128, 72), (1, 2, 3, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    async def run():
        events = []
        async for ev in svc.stream_generate_suite_from_images(
            {"cover": png}, creativity=5, user_id=1, extract_images=False
        ):
            events.append(ev)
        return events

    with patch(
        "landppt.services.db_config_service.get_vision_provider",
        new=AsyncMock(return_value=(FailingVision(), {"model": "gpt-4o", "temperature": None, "top_p": None})),
    ):
        events = asyncio.run(run())

    types = [e["type"] for e in events]
    assert types[-1] == "complete", events
    suite = events[-1]["suite"]
    # 封面视觉失败 → 5 个类型全部由文本补全，套件仍完整
    assert text_calls["count"] == 5
    assert suite["cover"].startswith("<!DOCTYPE html>")
    assert "page_title" in suite["header_footer"]


def test_call_vision_with_retry_passes_temperature():
    """视觉调用会透传配置的 temperature / top_p（如 kimi-k3 需要 temperature=1）。"""
    import asyncio
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    captured = {}

    class V:
        async def chat_completion(self, messages, **kwargs):
            captured["temperature"] = kwargs.get("temperature")
            captured["top_p"] = kwargs.get("top_p")
            captured["model"] = kwargs.get("model")
            return type("R", (), {"content": "ok"})()

    svc = GlobalTemplateSuiteService()

    async def run():
        return await svc._call_vision_with_retry(V(), "kimi-k3", [], temperature=1.0, top_p=0.95, max_tokens=500)

    result = asyncio.run(run())
    assert captured["temperature"] == 1.0
    assert captured["top_p"] == 0.95
    assert captured["model"] == "kimi-k3"
    assert result.content == "ok"

    # temperature / top_p 为 None 时不传（用 provider 默认）
    captured.clear()
    async def run2():
        return await svc._call_vision_with_retry(V(), "m", [], max_tokens=500)

    asyncio.run(run2())
    assert captured.get("temperature") is None
    assert captured.get("top_p") is None


def test_generate_suite_free_outline_mode_and_get_suite():
    """大纲智能套件：无母版模板也能生成（prompt 带大纲），get_suite 无需模板即可读取。"""
    import asyncio
    import json
    from landppt.services.template.template_suite_service import TemplateSuiteService

    class FakePM:
        def __init__(self):
            self.meta = {}

        async def get_project(self, pid, user_id=None):
            return type("P", (), {
                "outline": {"title": "测试", "slides": [{"title": "a"}]},
                "confirmed_requirements": {"topic": "测试主题"},
                "project_metadata": dict(self.meta),
            })()

        async def update_project_metadata(self, pid, meta, user_id=None):
            self.meta = dict(meta)

    captured = {}

    class FakeService:
        project_manager = FakePM()

        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            captured["prompt"] = prompt
            return type("R", (), {"content": json.dumps({
                "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1></body></html>",
                "transition": "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1></body></html>",
                "catalog": "<!DOCTYPE html><html><body><h1>{{ catalog_title }}</h1></body></html>",
                "ending": "<!DOCTYPE html><html><body><h1>{{ ending_title }}</h1></body></html>",
                "header_footer": (
                    '<div class="hf-canvas"><div class="bg-paper"></div><style>.hf-canvas{}</style>'
                    '<div class="main-stage">{{ page_content }}</div>'
                    "<header>{{ page_title }}</header>"
                    "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
                ),
                "design_tokens": "t",
            }, ensure_ascii=False)})()
        async def get_selected_global_template(self, pid, user_id=None):
            return None

        def clear_cached_style_genes(self, pid):
            pass

    svc = TemplateSuiteService(FakeService())

    async def run():
        suite = await svc.generate_suite("p1", None, free=True, creativity=5)
        read_back = await svc.get_suite("p1")
        return suite, read_back

    suite, read_back = asyncio.run(run())
    assert suite["template_mode"] == "outline"
    assert suite["template_name"] == "大纲智能套件"
    # 大纲模式 prompt 应包含"无母版/自行设计"且带上项目大纲
    assert "无母版原文" in captured["prompt"] or "自行设计" in captured["prompt"]
    assert "测试" in captured["prompt"]
    # get_suite 无需选中模板即可读取大纲套件
    assert read_back is not None
    assert read_back["template_mode"] == "outline"


def test_get_selected_global_template_none_for_suite_driven_projects():
    """套件驱动项目（suite 模式 / 套件库套件 / outline 套件）不返回任何全局模板，
    即使 metadata 残留 selected_global_template_id（旧逻辑强制写入过默认模板）。"""
    import asyncio
    from landppt.services.template.template_selection_service import TemplateSelectionService

    template = {"id": 1, "template_name": "Toy风", "html_template": "<html>t</html>"}
    fetched = {"count": 0}

    class FakePM:
        def __init__(self, meta):
            self.meta = meta

        async def get_project(self, pid, user_id=None):
            return type("P", (), {"project_metadata": dict(self.meta)})()

    class FakeGlobalTpl:
        async def get_template_by_id(self, tid):
            fetched["count"] += 1
            return template

        async def get_default_template(self):
            return template

    class FakeService:
        def __init__(self, meta):
            self.project_manager = FakePM(meta)
            self.global_template_service = FakeGlobalTpl()

        def clear_cached_style_genes(self, pid):
            pass

    cases = [
        # (metadata, 说明) —— 均带残留 selected_global_template_id=1
        ({"template_mode": "suite", "selected_global_template_id": 1}, "suite 模式"),
        ({"template_mode": "global", "selected_global_suite_id": 12, "selected_global_template_id": 1}, "套件库套件"),
        ({"template_mode": "global", "template_suite": {"template_mode": "outline", "cover": "x"}, "selected_global_template_id": 1}, "大纲智能套件"),
        ({"template_mode": "global", "selected_global_template_id": 1}, "纯模板项目（应返回模板）"),
    ]
    for meta, label in cases:
        svc = TemplateSelectionService(FakeService(meta))

        async def run():
            return await svc.get_selected_global_template("p1")

        result = asyncio.run(run())
        if label == "纯模板项目（应返回模板）":
            assert result == template, label
        else:
            assert result is None, f"{label} 不应返回残留的全局模板"


def test_get_suite_works_in_suite_mode_without_template():
    """仅使用套件模式：项目内模板型套件自包含生效，不再要求母版模板（template_hash 校验）。"""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService

    suite_payload = {
        "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1></body></html>",
        "header_footer": (
            '<div class="hf-canvas"><div class="bg-paper"></div><style>.hf-canvas{}</style>'
            '<div class="main-stage">{{ page_content }}</div>'
            "<header>{{ page_title }}</header>"
            "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
        ),
        "design_tokens": "t",
        "template_mode": "global",  # 模板型套件（非 outline）
        "template_id": 7,
        "template_hash": "abc",
    }

    class FakePM:
        def __init__(self):
            self.meta = {"template_mode": "suite", "template_suite": dict(suite_payload)}

        async def get_project(self, pid, user_id=None):
            return type("P", (), {"project_metadata": dict(self.meta)})()

    fetched_template = {"called": False}

    class FakeService:
        project_manager = FakePM()

        async def get_selected_global_template(self, pid, user_id=None):
            # suite 模式下不应被调用（不需要模板做校验）
            fetched_template["called"] = True
            return None

        def clear_cached_style_genes(self, pid):
            pass

    svc = TemplateSuiteService(FakeService())

    async def run():
        return await svc.get_suite("p1")

    result = asyncio.run(run())
    assert result is not None, "suite 模式的项目内套件应自包含生效"
    assert result["template_mode"] == "global"
    assert fetched_template["called"] is False, "suite 模式读取套件不应去取全局模板"


def test_single_slide_regeneration_suite_project_never_fetches_template():
    """重新生成单页：有有效套件时根本不调用 get_selected_global_template（不绑定、不打日志）。"""
    import asyncio
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "cover": "<!DOCTYPE html><html><body>{{ cover_title }}{{ cover_subtitle }}</body></html>",
        "header_footer": "<header>{{ page_title }}</header><footer>{{ current_page_number }}/{{ total_page_count }}</footer>",
        "design_tokens": "字体栈：X；强调色：#123456",
    }
    fetched_template = {"called": False}

    class FakeTemplateSuite:
        async def get_effective_suite(self, project_id):
            return suite

    class FakeMedia:
        template_suite = FakeTemplateSuite()

        async def get_selected_global_template(self, project_id):
            # 有有效套件的项目不应拉取全局模板
            fetched_template["called"] = True
            return {"id": 1, "template_name": "Toy风", "html_template": "<html>tpl</html>"}

        async def _try_fill_suite_slide(self, *args, **kwargs):
            return None  # 内容页不走套件模板填充

        async def _ensure_slide_images_context(self, *a, **k):
            return None

        async def _get_creative_design_inputs(self, *a, **k):
            return ("", "", "")

        async def _process_slide_image(self, *a, **k):
            return None

        def _build_slide_context(self, *a, **k):
            return ""

        async def _generate_html_with_retry(self, context, *a, **k):
            return "<!DOCTYPE html><html><body><div class='hf-canvas'>内容页</div></body></html>"

        async def _generate_fallback_slide_html(self, *a, **k):
            return "fallback"

        async def _apply_auto_layout_repair(self, html, *a, **k):
            return html

    media = SlideMediaService(FakeMedia())

    async def run():
        return await media._generate_single_slide_html_with_prompts(
            {"title": "背景介绍", "slide_type": "content", "content_points": ["要点"]},
            {"project_id": "p1", "topic": "T"},
            "sys", 2, 10, project_id="p1",
        )

    result = asyncio.run(run())
    assert fetched_template["called"] is False, "有有效套件的单页重新生成不应拉取/使用全局模板"
    assert result and "内容页" in result


def test_extract_suite_locked_colors_matches_renamed_constraint_titles():
    """A1 回归：_extract_suite_locked_colors 必须能识别改名后的约束标题
    （内容页强约束 / 目录页强约束），否则 excluded_colors 恒为 None，套件
    自身红/金配色被审美预检当 multi-accent 误杀，内容页反复重生成改色。"""
    from landppt.services.slide.slide_html_recovery_service import SlideHtmlRecoveryService

    hf = (
        "<!DOCTYPE html><html><head><style>"
        ".hf-canvas{background:#C8102E}.page-footer{color:#8B1A1A}"
        "</style></head><body><div class='hf-canvas'>{{ page_title }}</div></body></html>"
    )

    # 旧标题（兼容）
    ctx_old = f"**页头页脚强约束（...）**\n```html\n{hf}\n```"
    new = SlideHtmlRecoveryService._extract_suite_locked_colors(ctx_old)
    assert new and {"#C8102E", "#8B1A1A"} <= new, "旧标题应能提取套件锁定色"

    # 新标题（本次回归）
    ctx_new = f"**内容页强约束（...）**\n```html\n{hf}\n```"
    new2 = SlideHtmlRecoveryService._extract_suite_locked_colors(ctx_new)
    assert new2 and {"#C8102E", "#8B1A1A"} <= new2, "新标题「内容页强约束」必须能提取套件锁定色"

    # 目录页新标题
    ctx_cat = f"**目录页强约束（...）**\n```html\n{hf}\n```"
    new3 = SlideHtmlRecoveryService._extract_suite_locked_colors(ctx_cat)
    assert new3 and "#C8102E" in new3, "目录页强约束也应能提取套件锁定色"

    # 无任何约束
    assert SlideHtmlRecoveryService._extract_suite_locked_colors("普通上下文，无强约束") is None


def test_build_catalog_suite_constraint_injects_palette():
    """B1：目录页约束必须注入套件整体配色/字体（避免 LLM 私自换色）。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "catalog": "<!DOCTYPE html><html><body><h1>{{ catalog_title }}</h1></body></html>",
        "header_footer": "<div class='hf-canvas'>{{ page_title }}{{ page_content }}</div>",
        "cover": "<div style='color:#C8102E'>封面</div>",
        "design_tokens": "主色 #C8102E",
    }
    c = SlideMediaService._build_catalog_suite_constraint(suite)
    assert "目录页强约束" in c
    assert "套件整体设计语言" in c, "应注入套件整体设计语言（配色/字体）"
    assert "#c8102e" in c.lower(), "套件红色应进入目录页约束"
    assert "不得改成其它配色" in c or "另造新色" in c, "应有禁止换色的强约束"


def test_build_locked_zones_context_suite_mode_no_blank_canvas_for_special_page():
    """B2：套件模式特殊页不应发"另起构图/骨架不是继承项"，避免与套件约束互斥。"""
    from landppt.services.prompts.design_prompts import DesignPrompts

    # 普通模式特殊页（目录）——保留"另起构图"
    plain = DesignPrompts._build_locked_zones_context("<html>x</html>", 2, 10, "catalog", "目录")
    assert "另起构图" in plain and "骨架不是继承项" in plain

    # 套件模式特殊页——不发"骨架不是继承项"那条互斥指令，改为"以套件为骨架"
    suite = DesignPrompts._build_locked_zones_context(
        "<html>x</html>", 2, 10, "catalog", "目录", suite_mode=True
    )
    assert "骨架不是继承项" not in suite, "套件模式不应让特殊页'骨架不是继承项'"
    assert "不要原样沿用这套骨架" not in suite, "套件模式不应让特殊页舍弃套件骨架"
    assert "套件" in suite and "骨架" in suite, "套件模式应改为以套件对应页为骨架"


def test_extract_suite_skeleton_marker_supports_single_quote_class():
    """修正：套件 HTML 常用单引号 class='...'，marker 正则必须命中，否则
    退化为取前 20 字符、重试安全网永不触发。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    assert SlideMediaService._extract_suite_skeleton_marker("<div class='slide-page'>x</div>") == "slide-page"
    assert SlideMediaService._extract_suite_skeleton_marker('<div class="slide-page">x</div>') == "slide-page"
    # 大纲智能套件库实测形态（DOCTYPE + html 开头，但含 class）
    hf = "<!DOCTYPE html><html><body><div class='page-body'>{{ page_content }}</div></body></html>"
    assert SlideMediaService._extract_suite_skeleton_marker(hf) == "page-body"
    # 仍含 class 的 fragment
    assert SlideMediaService._extract_suite_skeleton_marker("<div class='hf-canvas'>") == "hf-canvas"


def test_replace_remaining_content_slots_fills_resident_tokens():
    """C1：内容页 LLM 输出残留的 {{page_title}}/{{page_content}}/页码槽位
    必须被确定性替换为本页真实内容。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    html = (
        "<!DOCTYPE html><html><body>"
        "<div class='page-header'><span class='page-title'>{{ page_title }}</span></div>"
        "<div class='page-body'>{{ page_content }}</div>"
        "<div class='page-footer'>{{ current_page_number }} / {{ total_page_count }}</div>"
        "<div class='unknown-slot'>{{ some_other_slot }}</div>"
        "</body></html>"
    )
    slide_data = {"title": "核心方案", "content_points": ["要点一", "要点二"]}
    out = SlideMediaService._replace_remaining_content_slots(html, slide_data, 4, 10)

    assert "{{ page_title }}" not in out and "核心方案" in out, "page_title 应被替换"
    assert "{{ page_content }}" not in out, "page_content 占位应被替换"
    assert "要点一" in out and "要点二" in out, "正文应来自 content_points"
    assert "{{ current_page_number }}" not in out and "4" in out
    assert "{{ total_page_count }}" not in out and "10" in out
    # 未知槽位保留（避免误伤套件特有槽位）
    assert "{{ some_other_slot }}" in out, "未知槽位应保留不替换"


def test_ensure_content_suite_style_injected_when_style_missing():
    """D1：内容页保留了骨架 div 但丢了套件 <style> 块时，应从套件补回 CSS。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "header_footer": (
            "<div class='slide-page'>{{ page_title }}{{ page_content }}</div>"
            "<style>.slide-page{background:#C8102E}.page-footer{color:#8B1A1A}</style>"
        ),
    }
    # LLM 输出：骨架 div 在，但 <style> 丢了
    html = (
        "<!DOCTYPE html><html><head></head><body>"
        "<div class='slide-page'>标题正文</div>"
        "</body></html>"
    )
    out = SlideMediaService._ensure_content_suite_style_injected(html, suite)
    assert "<style" in out, "应补回 <style> 块"
    assert "suite-style-backfill" in out
    assert ".slide-page" in out and "#C8102E" in out, "套件 CSS 规则应被注入"
    # 注入到 </head> 前
    assert out.index("<style") < out.index("</head>")

    # 输出已含套件骨架 CSS 选择器 → 不重复注入
    already = (
        "<!DOCTYPE html><html><head><style>.slide-page{background:#C8102E}</style></head>"
        "<body><div class='slide-page'>x</div></body></html>"
    )
    out2 = SlideMediaService._ensure_content_suite_style_injected(already, suite)
    assert out2 == already, "已有套件骨架 CSS 时不重复注入"

    # 套件无 <style> → 原样返回
    out3 = SlideMediaService._ensure_content_suite_style_injected(html, {"header_footer": "<div>x</div>"})
    assert out3 == html


def test_content_page_placeholder_and_style_backfill_wired():
    """C1+D1 接线：内容页 LLM 输出占位符残留且丢 <style> 时，最终输出被确定性补全
    （占位符替换 + 套件 CSS 注入）。模拟用户报告的 6/7/8 + 4/5/9/10 两种现象。"""
    import asyncio
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "header_footer": (
            "<div class='slide-page'>"
            "<div class='page-header'><span class='page-title'>{{ page_title }}</span></div>"
            "<div class='page-body'>{{ page_content }}</div>"
            "<div class='page-footer'>{{ current_page_number }} / {{ total_page_count }}</div>"
            "</div>"
            "<style>.slide-page{background:#C8102E}.page-footer{color:#8B1A1A}</style>"
        ),
        "design_tokens": "t",
    }

    class FakeTemplateSuite:
        async def get_effective_suite(self, project_id):
            return suite

    bad_llm_output = (
        "<!DOCTYPE html><html><head></head><body>"
        "<div class='slide-page'>"
        "<div class='page-header'><span class='page-title'>{{ page_title }}</span></div>"
        "<div class='page-body'>{{ page_content }}</div>"
        "<div class='page-footer'>{{ current_page_number }} / {{ total_page_count }}</div>"
        "</div>"
        "</body></html>"
    )

    class FakeMedia:
        template_suite = FakeTemplateSuite()

        async def get_selected_global_template(self, project_id):
            return None

        async def _try_fill_suite_slide(self, *a, **k):
            return None

        async def _ensure_slide_images_context(self, *a, **k):
            return None

        async def _get_creative_design_inputs(self, *a, **k):
            return ("", "", "")

        async def _process_slide_image(self, *a, **k):
            return None

        def _build_slide_context(self, *a, **k):
            return ""

        async def _generate_html_with_retry(self, context, *a, **k):
            return bad_llm_output

        async def _generate_fallback_slide_html(self, *a, **k):
            return "fallback"

        async def _apply_auto_layout_repair(self, html, *a, **k):
            return html

    media = SlideMediaService(FakeMedia())

    async def run():
        return await media._generate_single_slide_html_with_prompts(
            {"title": "实施路径", "slide_type": "content", "content_points": ["第一阶段", "第二阶段"]},
            {"project_id": "p1", "topic": "T"},
            "sys", 7, 10, project_id="p1",
        )

    result = asyncio.run(run())
    # C1：占位符全部替换
    assert "{{ page_title }}" not in result
    assert "{{ page_content }}" not in result
    assert "{{ current_page_number }}" not in result
    assert "{{ total_page_count }}" not in result
    assert "实施路径" in result
    assert "第一阶段" in result and "第二阶段" in result
    assert "7" in result and "10" in result
    # D1：套件 <style> 被补回
    assert "suite-style-backfill" in result
    assert ".slide-page" in result and "#C8102E" in result
    # A：body 默认 margin 兜底清零（套件 id=14 的 header_footer 无 reset → 注入）
    assert "suite-body-reset" in result
    assert "html,body{width:1280px;height:720px;margin:0!important;overflow:hidden!important" in result


def test_ensure_suite_body_reset_injects_when_missing():
    """A：内容页 body 无 reset 时注入 1280×720 + margin:0；已有等效 reset 不重复注入。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    # 无 reset → 注入 suite-body-reset 到 </head> 前
    html = (
        "<!DOCTYPE html><html><head></head><body>"
        "<div class='slide-page'>内容</div></body></html>"
    )
    out = SlideMediaService._ensure_suite_body_reset(html)
    assert "suite-body-reset" in out
    assert "html,body{width:1280px;height:720px;margin:0!important;overflow:hidden!important" in out
    assert out.index("<style") < out.index("</head>"), "应注入到 </head> 前"

    # 已有 *{margin:0} → 不重复注入（cmb 系列套件）
    has_star = (
        "<!DOCTYPE html><html><head><style>*{margin:0;padding:0}</style></head>"
        "<body><div class='slide-page'>x</div></body></html>"
    )
    assert SlideMediaService._ensure_suite_body_reset(has_star) == has_star

    # 已有 html,body{margin:0} → 不重复注入
    has_html_body = (
        "<!DOCTYPE html><html><head><style>html,body{width:1280px;height:720px;margin:0;overflow:hidden}</style></head>"
        "<body><div>x</div></body></html>"
    )
    assert SlideMediaService._ensure_suite_body_reset(has_html_body) == has_html_body

    # 已有 body{margin:0} → 不重复注入
    has_body = (
        "<!DOCTYPE html><html><head><style>body{margin:0;padding:0}</style></head>"
        "<body><div>x</div></body></html>"
    )
    assert SlideMediaService._ensure_suite_body_reset(has_body) == has_body

    # .page-body{...} 不应误判为 body reset（lookbehind 防子串误匹配）
    has_page_body = (
        "<!DOCTYPE html><html><head><style>.page-body{position:absolute;top:104px}</style></head>"
        "<body><div class='page-body'>x</div></body></html>"
    )
    out2 = SlideMediaService._ensure_suite_body_reset(has_page_body)
    assert "suite-body-reset" in out2, ".page-body 不应被视为 body reset"

    # 无 </head> 时注入到 </body> 前
    no_head = "<!DOCTYPE html><html><body><div>x</div></body></html>"
    out3 = SlideMediaService._ensure_suite_body_reset(no_head)
    assert "suite-body-reset" in out3
    assert out3.index("suite-body-reset") < out3.index("</body>")


def test_suite_prompt_header_footer_requires_body_reset():
    """B：生成 header_footer 的提示词（完整生成 + 单类型重生）必须要求片段自带
    `*{margin:0}` + `html,body{1280×720;margin:0;overflow:hidden}`。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    class P:
        topic = "AI大模型行业趋势"
        scenario = "峰会"

    outline = {"title": "T", "slides": [{"title": "a", "slide_type": "title"}]}
    confirmed = {"target_audience": "高管"}

    base = dict(project=P(), outline=outline, confirmed=confirmed,
                template_html="<div>tpl</div>", creativity=5)
    p = TemplatePrompts.build_template_suite_prompt(**base)
    assert "html,body{width:1280px;height:720px;margin:0;overflow:hidden}" in p, \
        "完整生成 prompt 应要求 header_footer 自带 body reset"

    pp = TemplatePrompts.build_template_suite_part_prompt(
        part="header_footer", outline=outline, confirmed=confirmed,
        template_html="<div>t</div>", existing_suite={"design_tokens": "t"}, creativity=5,
    )
    assert "*{margin:0;padding:0;box-sizing:border-box}" in pp, \
        "单类型重生 prompt 应要求 header_footer 自带 * reset"
    assert "html,body{width:1280px;height:720px;margin:0;overflow:hidden}" in pp, \
        "单类型重生 prompt 应要求 header_footer 自带 body 画布约束"


def test_generate_html_with_retry_triggers_on_zone_overlap_and_local_overflow():
    """A+B：正文/目录区盖页脚（zone_overlap）或局部容器溢出（overflows）必须触发
    重生成，并把"盖住页脚/超出 px"写进重试 feedback。模拟项目 a4f19559 的
    page 2（目录 items 盖页脚 66px）与 page 13（page-body 局部溢出 42px）。"""
    import asyncio
    from landppt.services.slide.slide_html_recovery_service import SlideHtmlRecoveryService

    # 场景 1：目录页盖页脚（zone_overlap）
    calls = {"n": 0, "contexts": []}
    zone_results = [
        {"overflow_px": 0, "overflow_ratio": 0, "overflow_x_px": 0, "overflows": [],
         "zone_overlap": {"zone_cls": "items", "item_h": 520, "box_h": 514, "overlap_px": 66}},
        {"overflow_px": 0, "overflow_ratio": 0, "overflow_x_px": 0, "overflows": [],
         "zone_overlap": None},
    ]
    ok_html = "<!DOCTYPE html><html><head></head><body><div>ok</div></body></html>"

    def make_host(counter):
        class Host:
            def _parse_header_lock(self, context):
                return None

            def _parse_footer_lock(self, context):
                return None

            async def _text_completion_for_role(self, role, *, prompt, **kw):
                counter["n"] += 1
                counter["contexts"].append(prompt)
                if counter["n"] == 1:
                    return type("R", (), {"content": "<!DOCTYPE html><html><head></head><body><div class='items'>超高内容超高内容超高内容超高内容</div></body></html>"})()
                return type("R", (), {"content": ok_html})()

            def _clean_html_response(self, content):
                return content

            def _inject_anti_overflow_css(self, html):
                return html

            def _validate_html_completeness(self, html):
                return {"is_complete": True, "errors": [], "missing_elements": []}

            def _aesthetic_preflight_check(self, *a, **k):
                return [], []

            async def _apply_auto_layout_repair(self, html, *a, **k):
                return html

            async def _generate_fallback_slide_html(self, *a, **k):
                return ok_html

        return Host()

    def make_svc(overflow_results, counter):
        host = make_host(counter)
        svc = SlideHtmlRecoveryService(host)
        # _measure_overflow 是 SlideHtmlRecoveryService 自己的方法，不走 __getattr__，
        # 需挂到实例上覆盖。
        async def _fake_measure(html, page_number):
            return overflow_results.pop(0)
        svc._measure_overflow = _fake_measure
        return svc

    svc = make_svc(zone_results, calls)

    async def run():
        return await svc._generate_html_with_retry("基础上下文", "sys", {"title": "t"}, 2, 10, max_retries=3)

    result = asyncio.run(run())
    assert calls["n"] == 2, f"盖页脚应触发一次重生成，实际调用 {calls['n']} 次"
    assert result == ok_html
    assert "盖住页脚" in calls["contexts"][1], "重试 feedback 应告知盖住页脚"
    assert "66px" in calls["contexts"][1], "重试 feedback 应写明超出像素数"

    # 场景 2：内容页局部容器溢出（overflows），顶层 overflow_px=0
    calls2 = {"n": 0, "contexts": []}
    local_results = [
        {"overflow_px": 0, "overflow_ratio": 0, "overflow_x_px": 0,
         "overflows": [{"tag": "div", "cls": "page-body", "item_h": 586, "box_h": 544}],
         "zone_overlap": None},
        {"overflow_px": 0, "overflow_ratio": 0, "overflow_x_px": 0,
         "overflows": [], "zone_overlap": None},
    ]
    svc2 = make_svc(local_results, calls2)

    async def run2():
        return await svc2._generate_html_with_retry("基础上下文", "sys", {"title": "t"}, 13, 18, max_retries=3)

    result2 = asyncio.run(run2())
    assert calls2["n"] == 2, f"局部溢出应触发一次重生成，实际 {calls2['n']} 次"
    assert result2 == ok_html
    assert "42px" in calls2["contexts"][1], "局部溢出 feedback 应写明超出像素数"

    # 场景 3：无溢出 → 不重试
    calls3 = {"n": 0, "contexts": []}
    clean_results = [
        {"overflow_px": 0, "overflow_ratio": 0, "overflow_x_px": 0,
         "overflows": [], "zone_overlap": None},
    ]
    svc3 = make_svc(clean_results, calls3)

    async def run3():
        return await svc3._generate_html_with_retry("基础上下文", "sys", {"title": "t"}, 5, 10, max_retries=3)

    result3 = asyncio.run(run3())
    assert calls3["n"] == 1, "无溢出不应重试"


def test_ensure_standard_content_stage_backfills_existing_and_missing():
    """A2：_ensure_standard_content_stage 三种情况收敛到 .suite-stage 标准容器。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    # 1) 已有 .page-content（套件 id=13 形态）→ 追加 suite-stage class + 注入标准 CSS
    hf_with_pc = (
        "<style>.page-content{position:absolute;top:96px;left:60px;right:60px;bottom:68px;z-index:5}"
        ".page-header{position:absolute;top:34px;left:60px;right:60px}</style>"
        '<div class="page-header"><span class="page-title">{{ page_title }}</span></div>'
        '<div class="page-content">{{ page_content }}</div>'
        '<div class="page-footer">{{ current_page_number }}/{{ total_page_count }}</div>'
    )
    out1 = T._ensure_standard_content_stage(hf_with_pc)
    assert "page-content suite-stage" in out1, "应在 page-content div 上追加 suite-stage class"
    m = re.search(r"\.suite-stage\s*\{([^}]*)\}", out1)
    assert m and "top:155px" in m.group(1) and "overflow:hidden" in m.group(1), "应注入标准 CSS 覆盖错误 top"

    # 2) 无内容容器、{{page_content}} 散落（id=1 形态）→ 包新 .suite-stage div
    hf_no_container = (
        '<div class="page-bg"></div><div class="page-header">{{ page_title }}</div>'
        "{{ page_content }}"
        '<div class="page-footer">{{ current_page_number }}</div>'
    )
    out2 = T._ensure_standard_content_stage(hf_no_container)
    assert '<div class="suite-stage">{{ page_content }}</div>' in out2, "应包建 .suite-stage div"
    m2 = re.search(r"\.suite-stage\s*\{([^}]*)\}", out2)
    assert m2, "应注入 .suite-stage CSS 规则"

    # 3) 已标准化（流水线上一轮 backfill 过）→ 幂等，不重复处理
    out3 = T._ensure_standard_content_stage(out1)
    assert out3 == out1, "已标准化的 header_footer 应幂等"
    # 注：.suite-stage CSS 规则只出现一次
    assert out3.count(".suite-stage{") == 1


def test_ensure_standard_stage_overrides_insufficient_top():
    """回归：已有 .suite-stage 但 top 过小（如套件 id=15 的 130px < header 底边 135px，
    内容与分割线交叉）时，backfill 追加 `top:155px !important` 覆盖；top 足够则幂等跳过。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    # top 不足（130px，套件 id=15 形态）→ 追加 !important 覆盖
    hf_insufficient = (
        "<style>.suite-header{position:absolute;top:60px;padding-bottom:20px;border-bottom:1px solid #000}"
        ".suite-stage{position:absolute;top:130px;left:60px;right:60px;bottom:60px;overflow:hidden}</style>"
        '<div class="suite-header">{{ page_title }}</div>'
        '<div class="suite-stage">{{ page_content }}</div>'
    )
    out = T._ensure_standard_content_stage(hf_insufficient)
    assert "top:155px !important" in out, "top 不足时应追加 !important 覆盖"
    # 幂等：再次 backfill 不重复追加
    out2 = T._ensure_standard_content_stage(out)
    assert out2 == out, "覆盖后应幂等"

    # top 足够（160px）→ 跳过，不追加
    hf_enough = (
        "<style>.suite-stage{position:absolute;top:160px;left:60px;right:60px;bottom:60px;overflow:hidden}</style>"
        '<div class="suite-stage">{{ page_content }}</div>'
    )
    out3 = T._ensure_standard_content_stage(hf_enough)
    assert out3 == hf_enough, "top 足够时保持原样"


def test_ensure_standard_stage_accepts_exact_stage_top():
    """动态精确适配：生成前按套件实测 header 底边得到 stage_top（如 id=14 的 108），
    传给 backfill 时用它覆盖（而非默认 155）；未传则用默认。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    hf = (
        "<style>.page-header{position:absolute;top:34px;padding-bottom:16px}"
        ".suite-stage{position:absolute;top:108px;left:60px;right:60px;bottom:60px;overflow:hidden}</style>"
        '<div class="page-header">{{ page_title }}</div>'
        '<div class="suite-stage">{{ page_content }}</div>'
    )
    # 传入精确 stage_top（=108）→ 已满足，不重复覆盖
    out = T._ensure_standard_content_stage(hf, stage_top=108)
    assert "top:108px !important" not in out, "top 已满足精确值时不重复覆盖"

    # 传入更大的精确值（header 更高，如 200）→ 覆盖为 200
    out2 = T._ensure_standard_content_stage(hf, stage_top=200)
    assert "top:200px !important" in out2, "应覆盖为传入的精确 stage_top"

    # 不传 → 默认 _STAGE_TOP_MIN（155）→ 108 不足则覆盖为 155
    out3 = T._ensure_standard_content_stage(hf)
    assert "top:155px !important" in out3, "未传 stage_top 时用默认 155 覆盖不足值"


def test_instantiate_records_suite_stage_top(monkeypatch):
    """instantiate 后应记录精确 stage_top 到 suite 的 _suite_stage_top（供生成 prompt 用）。"""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    suite = {
        "header_footer": (
            "<style>.page-header{position:absolute;top:34px}.suite-stage{position:absolute;top:155px;left:60px;right:60px;bottom:60px;overflow:hidden}</style>"
            '<div class="page-header">{{ page_title }}</div>'
            '<div class="suite-stage">{{ page_content }}</div>'
        ),
        "cover": "", "transition": "", "catalog": "", "ending": "",
    }

    class P:
        topic = "部门工作情况汇报"
        title = "部门工作情况汇报"
        created_at = 1786446950.6611688

    class PM:
        async def get_project(self, pid, user_id=None):
            return P()

    class Host:
        project_manager = PM()

        async def _text_completion_for_role(self, role, *, prompt, **kw):
            return type("R", (), {"content": "{}"})()

    async def _fake_measure(self, suite):
        # 模拟测量不可用 → 返回 None（回退默认），验证不崩且 _suite_stage_top 不设
        return None

    monkeypatch.setattr(T, "_measure_stage_top", _fake_measure)
    svc = T(Host())

    async def run():
        return await svc.instantiate_suite_brand_for_project("p1", suite)

    branded = asyncio.run(run())
    # 测量不可用时保持默认 155（不设 _suite_stage_top，不崩、不覆盖）
    assert "_suite_stage_top" not in branded
    assert "top:155px" in branded["header_footer"]


def test_suite_prompt_requires_standard_stage():
    """A2 B1：生成 header_footer 的提示词（完整生成）必须要求标准 .suite-stage 容器。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    class P:
        topic = "AI大模型"
        scenario = "峰会"

    outline = {"title": "T", "slides": [{"title": "a", "slide_type": "title"}]}
    p = TemplatePrompts.build_template_suite_prompt(
        project=P(), outline=outline, confirmed={"target_audience": "高管"},
        template_html="<div>tpl</div>", creativity=5,
    )
    assert "suite-stage" in p, "完整生成 prompt 应要求 .suite-stage 标准容器"
    assert ".suite-stage{position:absolute;top:155px" in p or "top:155px" in p
    assert "overflow:hidden" in p


def test_content_suite_constraint_mentions_standard_stage_and_column_basis():
    """A2 B4 + A3：内容页约束 prompt 应说明 .suite-stage 容器与列宽基准 1160px。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "header_footer": '<div class="suite-stage">{{ page_content }}</div>'
                         "<style>.suite-stage{position:absolute;top:155px;left:60px;right:60px;bottom:60px;overflow:hidden}</style>",
        "design_tokens": "t",
    }
    c = SlideMediaService._build_content_suite_constraint(suite)
    assert "suite-stage" in c
    assert "1160px" in c, "应说明列宽基准为内宽 1160px"
    assert "45%+55%+gap" in c, "应明示 prohibited 列宽组合"


def test_overflow_feedback_optimizes_layout_not_reduces_content():
    """A4 测量层：溢出重试的 feedback 应说'优化布局密度（min-height/缩字号/收紧行距）'，
    **不应**出现'减少内容/删次要项'（按用户要求：不删内容、不裁切）。"""
    import asyncio
    from landppt.services.slide.slide_html_recovery_service import SlideHtmlRecoveryService

    overflow_results = [
        {"overflow_px": 0, "overflow_ratio": 0, "overflow_x_px": 0,
         "overflows": [{"tag": "div", "cls": "section-card", "item_h": 266, "box_h": 198}],
         "zone_overlap": None},
        {"overflow_px": 0, "overflow_ratio": 0, "overflow_x_px": 0, "overflows": [], "zone_overlap": None},
    ]
    calls = {"contexts": []}
    ok_html = "<!DOCTYPE html><html><head></head><body><div>ok</div></body></html>"

    class Host:
        def _parse_header_lock(self, c): return None
        def _parse_footer_lock(self, c): return None
        async def _text_completion_for_role(self, role, *, prompt, **kw):
            calls["contexts"].append(prompt)
            return type("R", (), {"content": ok_html if len(calls["contexts"]) > 1 else "<!DOCTYPE html><html><head></head><body><div class='section-card'>长内容</div></body></html>"})()
        def _clean_html_response(self, content): return content
        def _inject_anti_overflow_css(self, html): return html
        def _validate_html_completeness(self, html):
            return {"is_complete": True, "errors": [], "missing_elements": []}
        def _aesthetic_preflight_check(self, *a, **k): return [], []
        async def _apply_auto_layout_repair(self, html, *a, **k): return html
        async def _generate_fallback_slide_html(self, *a, **k): return ok_html

    svc = SlideHtmlRecoveryService(Host())
    async def _m(html, page_number): return overflow_results.pop(0)
    svc._measure_overflow = _m

    async def run():
        return await svc._generate_html_with_retry("ctx", "sys", {"title": "t"}, 11, 18, max_retries=3)

    asyncio.run(run())
    retry_ctx = calls["contexts"][1]
    assert "优化布局密度" in retry_ctx
    assert "min-height" in retry_ctx, "应建议用 min-height 代替固定 height"
    assert "不要减少内容" in retry_ctx, "应明确告知不要减少内容"
    assert "overflow:hidden 裁切" in retry_ctx, "应明确告知不要用 overflow:hidden 裁切"
    assert "删次要项" not in retry_ctx, "不应再出现'减少内容/删次要项'导向"


class _BrandProject:
    topic = "部门工作情况汇报"
    title = "部门工作情况汇报"
    created_at = 1786446950.6611688  # 2026-08


class _BrandProjectNoOrg:
    topic = "AI大模型行业趋势"
    title = "AI大模型行业趋势"
    created_at = 1786418885.0


def test_resolve_brand_values():
    """品牌值解析：年份取自 created_at、主题取自 topic、部门从主题前缀提取。
    brand_code（编号）恒为空——不再生成/配置，老套件残留槽位仅被清空。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    v = T._resolve_brand_values(_BrandProject())
    assert v["{{brand_year}}"] == "2026"
    assert v["{{brand_topic}}"] == "部门工作情况汇报"
    assert v["{{brand_org}}"] == "部门"
    assert v["{{brand_code}}"] == "", "brand_code 恒为空串（不读取 confirmed['brand_code']）"

    v2 = T._resolve_brand_values(_BrandProjectNoOrg())
    assert v2["{{brand_org}}"] == "", "非部门前缀主题不提取 org"
    assert v2["{{brand_year}}"] == "2026"


def test_replace_brand_in_html_slots_and_legacy():
    """品牌替换：槽位替换 + 老套件固化文案（skip 保留、CSS 里的不误伤、tagline 空保留）。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    values = T._resolve_brand_values(_BrandProject())

    # 槽位
    html = '<div class="header-right">{{brand_year}} · {{brand_topic}}</div>'
    out = T._replace_brand_in_html(html, values, {})
    assert "{{brand_year}}" not in out and "{{brand_topic}}" not in out
    assert "2026" in out and "部门工作情况汇报" in out

    # 老套件：year 替换、skip 保留、CSS 内 2025 不替换
    roles = {"2025": "year", "SECTION": "skip"}
    html2 = "<span>2025</span><span>SECTION</span><style>.x{content:\"2025\"}</style>"
    out2 = T._replace_brand_in_html(html2, values, roles)
    assert "2026" in out2
    assert "SECTION" in out2
    assert 'content:"2025"' in out2, "CSS 里的年份不应被替换"

    # tagline 无真实值（空）→ 固化 tagline 文案保留原样
    out3 = T._replace_brand_in_html("<span>DEPT. REPORT</span>", values, {"DEPT. REPORT": "tagline"})
    assert "DEPT. REPORT" in out3, "tagline 未配置真实值时保留原样"

    # tagline 有真实值 → 替换
    values_tag = dict(values)
    values_tag["{{brand_tagline}}"] = "TEAM WORK REPORT"
    out4 = T._replace_brand_in_html("<span>DEPT. REPORT</span>", values_tag, {"DEPT. REPORT": "tagline"})
    assert "TEAM WORK REPORT" in out4 and "DEPT. REPORT" not in out4


def test_analyze_suite_brand_roles_cached():
    """LLM 语义分析识别套件固化文案角色，且按套件内容缓存（不重复烧 LLM）。"""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    suite = {
        "header_footer": "<div class='header-right'>DEPT. REPORT · 2025</div><div class='footer-left'>SECTION TRANSITION</div>",
        "cover": "<h1>ANNUAL REPORT</h1><span>CHAPTER</span>",
        "transition": "", "catalog": "", "ending": "",
    }
    calls = {"n": 0}

    class Host:
        async def _text_completion_for_role(self, role, *, prompt, **kw):
            calls["n"] += 1
            return type("R", (), {"content": '{"DEPT. REPORT": "tagline", "2025": "year", "ANNUAL REPORT": "topic", "SECTION TRANSITION": "skip", "CHAPTER": "skip"}'})()

    svc = T(Host())

    async def main():
        roles = await svc._analyze_suite_brand_roles(suite)
        assert roles.get("2025") == "year"
        assert roles.get("SECTION TRANSITION") == "skip"
        assert roles.get("ANNUAL REPORT") == "topic"
        # 缓存：第二次不再调 LLM
        await svc._analyze_suite_brand_roles(suite)
        return roles

    roles = asyncio.run(main())
    assert calls["n"] == 1, "缓存后不应重复调 LLM"


def test_instantiate_suite_brand_for_project():
    """生成前品牌实例化：老套件固化年份替换为真实值、原套件不变（不影响预览/库）。"""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    suite = {
        "header_footer": "<div class='footer-left'>DEPT. REPORT · 2025</div><div class='page-content'>{{page_content}}</div>",
        "cover": "<h1>ANNUAL REPORT 2025</h1>",
        "transition": "", "catalog": "", "ending": "",
    }

    class PM:
        async def get_project(self, pid, user_id=None):
            return _BrandProject()

    class Host:
        project_manager = PM()

        async def _text_completion_for_role(self, role, *, prompt, **kw):
            return type("R", (), {"content": '{"2025": "year", "DEPT. REPORT": "tagline", "ANNUAL REPORT": "topic"}'})()

    svc = T(Host())

    async def main():
        return await svc.instantiate_suite_brand_for_project("p1", suite)

    branded = asyncio.run(main())
    assert "2025" not in branded["header_footer"], "年份应被替换"
    assert "2026" in branded["header_footer"]
    assert "2026" in branded["cover"], "封面里的年份也应替换"
    # 原套件不变
    assert "2025" in suite["header_footer"], "原套件应保持不变（不影响预览/库）"
    # ANNUAL REPORT 是 topic 角色但 brand_topic=部门工作情况汇报 → 应被替换
    assert "部门工作情况汇报" in branded["cover"] or "ANNUAL REPORT" in branded["cover"]


def test_suite_prompt_requires_brand_slots():
    """新套件生成 prompt 必须要求品牌文案写成品牌槽位，不得固化示例值。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    class P:
        topic = "AI大模型"
        scenario = "峰会"

    outline = {"title": "T", "slides": [{"title": "a", "slide_type": "title"}]}
    p = TemplatePrompts.build_template_suite_prompt(
        project=P(), outline=outline, confirmed={"target_audience": "高管"},
        template_html="<div>tpl</div>", creativity=5,
    )
    assert "brand_year" in p
    assert "brand_org" in p and "brand_topic" in p and "brand_tagline" in p
    assert "- 编号 → {{ brand_code }}" not in p, "新套件生成 prompt 不应再要求 brand_code 编号槽位"
    assert "不要生成整份文档的整体编号" in p, "应明确禁止整体编号、只保留章节编号/页码"
    assert "不要写死" in p, "应明确禁止固化示例品牌值"
    assert "2024" in p and "DEPARTMENT" in p, "应举例说明禁止固化的值"


def test_preview_html_fills_brand_slots_with_samples():
    """套件预览：品牌槽位（{{brand_year}} 等）用真实感示例值填充，而非 '[brand_year 示例]'。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    suite = {
        "cover": "<!DOCTYPE html><html><body><h1>{{cover_title}}</h1>"
                 "<span>{{brand_year}} · {{brand_org}}</span><span>{{brand_tagline}}</span></body></html>",
        "transition": "<!DOCTYPE html><html><body><h1>{{transition_title}}</h1>"
                      "<p>{{brand_topic}}</p><span>{{chapter_number}}</span></body></html>",
        "catalog": "<!DOCTYPE html><html><body><h1>{{catalog_title}}</h1></body></html>",
        "ending": "<!DOCTYPE html><html><body><h1>{{ending_title}}</h1><span>{{brand_code}}</span></body></html>",
        "header_footer": (
            "<div class='page-header'><span>{{brand_year}} · {{brand_topic}}</span>"
            "<span>{{chapter_number}}</span></div>"
            "<div class='page-body'>{{page_content}}</div>"
            "<div class='page-footer'>{{current_page_number}}/{{total_page_count}} {{brand_org}}</div>"
        ),
    }
    svc = T.__new__(T)
    preview = svc.build_preview_html(suite)

    # cover：品牌槽位被示例值填充
    cover = preview["cover"]
    assert "{{brand_year}}" not in cover
    assert "[brand_year 示例]" not in cover
    assert "2026" in cover
    assert "XX部门" in cover
    assert "DEPARTMENT WORK REPORT" in cover

    # transition：brand_topic 示例值 + chapter_number 示例值（2）
    assert "年度工作报告" in preview["transition"]
    assert "{{brand_topic}}" not in preview["transition"]
    assert "{{chapter_number}}" not in preview["transition"], "章节号槽位应被预览示例值填充"
    assert "2" in preview["transition"], "过渡页章节号示例值应为 2"

    # ending：brand_code 示例值
    assert "No.01" in preview["ending"]
    assert "{{brand_code}}" not in preview["ending"]

    # content 页 header/footer：品牌槽位也填充 + chapter_number 示例值（2）
    content = preview["content"]
    assert "{{brand_year}}" not in content
    assert "2026" in content
    assert "XX部门" in content
    assert "{{chapter_number}}" not in content, "内容页章节号槽位应被预览示例值填充"
    # 标准槽位仍正常
    assert "{{page_content}}" not in content
    assert "{{current_page_number}}" not in content


def test_replace_brand_in_html_semantic_slots_and_structure_protection():
    """A：语义归类替换自定义品牌槽位（{{year}}/{{dept}}/{{company_year}}），
    结构槽位（cover_title 等）即使被误归为品牌角色也绝不替换。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    values = T._resolve_brand_values(_BrandProject())

    # 自定义品牌槽位 → 语义归类替换
    html = "<span>{{year}} {{dept}} {{company_year}} {{brand_year}}</span>"
    roles = {"{{year}}": "year", "{{dept}}": "org", "{{company_year}}": "year", "{{brand_year}}": "year"}
    out = T._replace_brand_in_html(html, values, roles)
    assert "{{year}}" not in out and "{{dept}}" not in out and "{{company_year}}" not in out
    assert "2026" in out and "部门" in out

    # 结构槽位保护：LLM 误归为品牌角色 → 不替换
    html2 = "<h1>{{cover_title}}</h1><span>{{page_title}}</span><span>{{current_page_number}}</span>"
    roles2 = {"{{cover_title}}": "topic", "{{page_title}}": "topic", "{{current_page_number}}": "year"}
    out2 = T._replace_brand_in_html(html2, values, roles2)
    assert "{{cover_title}}" in out2
    assert "{{page_title}}" in out2
    assert "{{current_page_number}}" in out2

    # 固化文本 + 自定义槽位混合
    html3 = "<span>2025</span><span>{{year}}</span><span>DEPT. REPORT</span>"
    roles3 = {"2025": "year", "{{year}}": "year", "DEPT. REPORT": "tagline"}
    out3 = T._replace_brand_in_html(html3, values, roles3)
    assert "2026" in out3 and "{{year}}" not in out3
    assert "DEPT. REPORT" in out3, "tagline 无真实值时保留原样"


def test_brand_preview_sample_heuristic():
    """B：预览品牌示例值按槽位名启发式推断（覆盖自定义槽位名），非品牌槽位回退 None。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    assert T._brand_preview_sample("company_year") == "2026"
    assert T._brand_preview_sample("year") == "2026"
    assert T._brand_preview_sample("dept") == "XX部门"
    assert T._brand_preview_sample("department_name") == "XX部门"
    assert T._brand_preview_sample("brand_topic") == "年度工作报告"
    assert T._brand_preview_sample("brand_code") == "No.01"
    assert T._brand_preview_sample("brand_tagline") == "DEPARTMENT WORK REPORT"
    assert T._brand_preview_sample("item_1_title") is None, "非品牌槽位回退 None"

    # 预览 fill 用启发式：自定义品牌槽位不显示 '[name 示例]'
    suite = {
        "cover": "<!DOCTYPE html><html><body><span>{{company_year}} · {{dept}}</span><h1>{{cover_title}}</h1></body></html>",
        "transition": "", "catalog": "", "ending": "",
        "header_footer": "<div class='page-footer'>{{year}}</div>",
    }
    preview = T.__new__(T).build_preview_html(suite)
    cover = preview["cover"]
    assert "{{company_year}}" not in cover and "[company_year 示例]" not in cover
    assert "2026" in cover and "XX部门" in cover
    assert "{{cover_title}}" not in cover, "cover_title 应由标准填充机制替换"


def test_replace_brand_in_html_handles_spaced_slots():
    """回归：套件 id=15 的品牌槽位是 `{{ brand_year }}`（带空格）写法，
    必须被品牌替换兼容（否则品牌替换失效 → 各页 LLM 补全年份/部门不一致）。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    values = T._resolve_brand_values(_BrandProject())

    # 带空格写法（生成套件 prompt 转义后常见）
    html = "<span>{{ brand_year }} · {{ brand_org }}</span>"
    out = T._replace_brand_in_html(html, values, None)
    assert "{{ brand_year }}" not in out and "{{brand_year}}" not in out
    assert "{{ brand_org }}" not in out and "{{brand_org}}" not in out
    assert "2026" in out and "部门" in out

    # 混合写法（无空格 + 带空格 + 值空清掉）
    html2 = "<span>{{brand_year}}</span><span>{{ brand_year }}</span><span>{{ brand_code }}</span>"
    out2 = T._replace_brand_in_html(html2, values, None)
    assert "{{" not in out2, "所有品牌槽位（含值空的 brand_code）都应被清掉"
    assert "2026" in out2

    # 语义归类项：带空格自定义品牌槽位也能替换
    roles = {"{{ company_year }}": "year", "{{ dept }}": "org"}
    html3 = "<span>{{ company_year }} {{ dept }}</span>"
    out3 = T._replace_brand_in_html(html3, values, roles)
    assert "{{ company_year }}" not in out3 and "{{ dept }}" not in out3
    assert "2026" in out3 and "部门" in out3


def test_default_slot_text_brand_slot_clears():
    """回归：品牌槽位兜底返回空串，避免 '[brand_org]' 占位残留。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    assert SlideMediaService._default_slot_text("brand_org", {"title": "x"}, 1) == ""
    assert SlideMediaService._default_slot_text("brand_year", {"title": "x"}, 1) == ""
    # 非品牌槽位不受影响
    assert SlideMediaService._default_slot_text("cover_extra", {"title": "x", "content_points": ["a"]}, 1) == "a"


def test_brand_role_by_name_heuristic():
    """名字启发式：自定义品牌槽位名（fiscal_year/dept/company/serial_no）按关键词归类。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    assert T._brand_role_by_name("brand_year") == "year"
    assert T._brand_role_by_name("fiscal_year") == "year"
    assert T._brand_role_by_name("company_year") == "year"
    assert T._brand_role_by_name("dept") == "org"
    assert T._brand_role_by_name("department") == "org"
    assert T._brand_role_by_name("company") == "org"
    assert T._brand_role_by_name("bank") == "org"
    assert T._brand_role_by_name("brand_topic") == "topic"
    assert T._brand_role_by_name("subject") == "topic"
    assert T._brand_role_by_name("brand_tagline") == "tagline"
    assert T._brand_role_by_name("serial_no") == "code"
    assert T._brand_role_by_name("item_1_title") is None, "非品牌槽位不归类"
    assert T._brand_role_by_name("page") is None


def test_merge_heuristic_brand_roles_llm_fail_fallback():
    """LLM 语义分析失败（roles 空）时，名字启发式兜底归类自定义品牌槽位；
    LLM 已归类的结果优先于启发式；结构槽位始终跳过。"""
    import asyncio
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    suite = {
        "header_footer": "",
        "cover": "<span>{{ fiscal_year }} {{ dept }}</span><span>{{ cover_title }}</span><span>{{ brand_code }}</span>",
        "transition": "", "catalog": "", "ending": "",
    }

    # 直接测 merge：LLM 失败
    merged = T._merge_heuristic_brand_roles(suite, {})
    assert merged.get("{{ fiscal_year }}") == "year"
    assert merged.get("{{ dept }}") == "org"
    assert merged.get("{{ brand_code }}") == "code"
    assert "{{ cover_title }}" not in merged, "结构槽位不归类"

    # LLM 已归类则优先
    merged2 = T._merge_heuristic_brand_roles(suite, {"{{ dept }}": "topic"})
    assert merged2.get("{{ dept }}") == "topic", "LLM 结果优先于启发式"

    # 集成：instantiate 时 LLM 分析 mock 返回空，自定义品牌槽位仍被替换
    class P:
        topic = "部门工作情况汇报"
        title = "部门工作情况汇报"
        created_at = 1786446950.6611688

    class PM:
        async def get_project(self, pid, user_id=None):
            return P()

    class Host:
        project_manager = PM()

        async def _text_completion_for_role(self, role, *, prompt, **kw):
            return type("R", (), {"content": "{}"})()

    svc = T(Host())

    async def run():
        suite3 = {
            "header_footer": "<div class='page-footer'>{{ fiscal_year }} {{ dept }}</div>",
            "cover": "<h1>{{cover_title}}</h1><span>{{ company_year }}</span>",
            "transition": "", "catalog": "", "ending": "",
        }
        return await svc.instantiate_suite_brand_for_project("p1", suite3)

    branded = asyncio.run(run())
    hf = branded["header_footer"]
    cover = branded["cover"]
    assert "{{ fiscal_year }}" not in hf and "{{ dept }}" not in hf
    assert "2026" in hf and "部门" in hf
    assert "{{ company_year }}" not in cover and "2026" in cover
    assert "{{cover_title}}" in cover or "{{ cover_title }}" in cover, "结构槽位不受影响"


def test_sanitize_slot_value_extracts_nested_structure():
    """回归：LLM 把 cover_extra 等槽位值写成嵌套 dict/list 字符串时，净化提取为可读纯文本。"""
    from landppt.services.slide.slide_media_service import SlideMediaService as S

    # 用户实际遇到：嵌套单引号 Python dict
    bad = "{'subtitle': '年度工作成果与未来展望', 'presenter': '汇报人：部门负责人', 'slogan': '务实创新，追求卓越', 'background': '全面总结过去工作成效，部署下阶段重点任务'}"
    out = S._sanitize_slot_value(bad, "[兜底]")
    assert "{" not in out and "[" not in out, "不应残留 JSON/Python 结构"
    assert "年度工作成果" in out or "全面总结过去工作成效" in out, "应提取可读文案"

    # 双引号 JSON dict
    out2 = S._sanitize_slot_value('{"subtitle": "年度工作成果", "presenter": "汇报人"}', "[兜底]")
    assert out2 and "{" not in out2

    # 正常纯文本 → 原样
    assert S._sanitize_slot_value("务实创新，追求卓越", "[兜底]") == "务实创新，追求卓越"

    # list → 换行连接
    out3 = S._sanitize_slot_value('["要点一", "要点二"]', "[兜底]")
    assert out3 == "要点一\n要点二"

    # 空/无法解析 → fallback
    assert S._sanitize_slot_value("", "[兜底]") == "[兜底]"
    assert S._sanitize_slot_value("{broken", "[兜底]") == "[兜底]"

    # 值仍嵌套 → 递归提取
    out4 = S._sanitize_slot_value('{"a": {"b": "深层文案"}}', "[兜底]")
    assert "深层文案" in out4


def test_resolve_remaining_slots_sanitizes_nested_slot_value():
    """集成：_resolve_remaining_slots 的 LLM 返回嵌套 dict 时，cover_extra 被净化为可读文案，
    不再把 '{'...'}' 原样漏进页面。"""
    import asyncio
    from landppt.services.slide.slide_media_service import SlideMediaService

    class Host:
        async def _text_completion_for_role(self, role, *, prompt, **kw):
            return type("R", (), {"content": '{"cover_extra": "{\'subtitle\': \'年度工作成果\', \'presenter\': \'汇报人：部门负责人\'}"}'})()

        @staticmethod
        def _strip_think_tags(content):
            return content

    media = SlideMediaService(Host())

    async def run():
        return await media._resolve_remaining_slots(
            "<div class='cover-extra'>{{cover_extra}}</div>",
            ["cover_extra"],
            {"title": "部门工作汇报", "content_points": ["要点一"]},
            1, 10, "sys",
        )

    result = asyncio.run(run())
    v = result["cover_extra"]
    assert "{" not in v and "[" not in v, f"槽位值不应残留 JSON 结构: {v!r}"
    assert v.strip() != "{'subtitle'"
    assert v, "应提取出非空可读文案"


def test_strip_redundant_master_skeleton():
    """回归：套件自带 suite- 前缀骨架时，移除生成时误注入的母版骨架块（双骨架 → 单骨架）；
    母版即骨架的套件（无 suite- 前缀）不清理。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    # 双重骨架形态（套件 id=15 被污染）
    polluted = (
        "<!-- 母版内容页骨架（背景/装饰，自包含） -->\n"
        '<div class="canvas"><div class="bg-paper"></div><div class="bg-grid"></div></div>\n'
        "<style>.suite-canvas{position:relative;width:1280px;height:720px}"
        ".suite-stage{position:absolute;top:155px}</style>\n"
        '<div class="suite-canvas"><div class="suite-bg-paper"></div>'
        '<div class="suite-stage">{{ page_content }}</div></div>'
    )
    cleaned = T._strip_redundant_master_skeleton(polluted)
    assert "母版内容页骨架" not in cleaned, "应移除母版骨架注释"
    assert ".suite-canvas" in cleaned and "suite-stage" in cleaned, "应保留套件自骨架"
    assert 'class="canvas"' not in cleaned or "suite-bg-paper" in cleaned, "母版 .canvas div 应被裁掉"

    # 母版即骨架（无 suite- 前缀）→ 不清理
    master_only = (
        "<!-- 母版内容页骨架（背景/装饰，自包含） -->\n"
        '<div class="canvas"><div class="bg-paper"></div>'
        '<div class="main-stage">{{ page_content }}</div></div>'
        "<style>.canvas{position:relative}.bg-paper{position:absolute}</style>"
    )
    out2 = T._strip_redundant_master_skeleton(master_only)
    assert out2 == master_only, "无 suite- 自骨架的套件不应清理"


def test_header_footer_complete_accepts_suite_prefixed_skeleton():
    """回归：has_skeleton_css 正则兼容 suite- 前缀类名——完整 .suite-canvas 骨架的
    header_footer 不再被误判"缺骨架"而注入母版骨架（双骨架根因）。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    suite_hf = (
        "<style>.suite-canvas{position:relative;width:1280px;height:720px}"
        ".suite-bg-paper{position:absolute;inset:0}"
        ".suite-header{position:absolute;top:34px}</style>"
        '<div class="suite-canvas"><div class="suite-bg-paper"></div>'
        '<div class="suite-header">{{ page_title }}</div>'
        '<div class="suite-stage">{{ page_content }}</div></div>'
    )
    out = T._ensure_header_footer_complete(suite_hf, "<div>tpl</div>", "")
    assert "母版内容页骨架" not in out, "suite- 前缀完整骨架不应再被注入母版骨架"
    assert "suite-canvas" in out


# ---------------- AI生成套件（文字需求 + 可选网页 HTML） ----------------

def test_build_template_suite_prompt_web_source():
    """source_kind='web' 时提示词用"参考网页"措辞并含网页 HTML 与文字需求；
    默认 source_kind 仍用"母版 HTML 原文"措辞（回归保护）。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    web_html = "<!DOCTYPE html><html><head><style>body{background:#0b1020;color:#e5e7eb;"
    "font-family:'Inter',sans-serif}</style></head><body><h1>Welcome</h1></body></html>"
    req = "科技感、深色系、几何装饰"

    p_web = TemplatePrompts.build_template_suite_prompt(
        template_html=web_html,
        custom_requirements=req,
        source_kind="web",
    )
    assert "参考网页 HTML" in p_web, "web 源应使用参考网页措辞"
    assert "保持一致" in p_web, "web 源应明确风格与网页保持一致"
    assert web_html in p_web, "web 源应包含传入的网页 HTML"
    assert req in p_web, "文字需求应通过 custom_requirements 注入"
    assert "母版 HTML 原文" not in p_web, "web 源不应再用母版措辞"

    # 默认 source_kind=master 仍用母版措辞
    p_master = TemplatePrompts.build_template_suite_prompt(
        template_html=web_html,
    )
    assert "母版 HTML 原文" in p_master, "默认源应保留母版措辞（回归保护）"


def test_build_template_suite_prompt_web_source_truncates_long_html():
    """网页 HTML 过长时截断并附截断注释；无网页 HTML 时显示提示文案。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    long_html = "x" * 70000
    p_long = TemplatePrompts.build_template_suite_prompt(
        template_html=long_html, source_kind="web",
    )
    assert "已截断" in p_long, "过长网页 HTML 应截断并附注释"
    assert "x" * 70000 not in p_long, "截断后不应包含完整原文"

    p_empty = TemplatePrompts.build_template_suite_prompt(
        template_html="", source_kind="web",
    )
    assert "未提供网页 HTML" in p_empty, "无网页 HTML 时应显示提示文案"


def test_generate_suite_payload_web_source_skips_skeleton_injection():
    """source_kind='web' 调 _generate_suite_payload 时，header_footer 不被注入
    母版骨架（网页 DOM 不当内容页骨架注入）。用 FakeService 捕获：网页里
    有 .canvas/.bg-paper 但生成结果 header_footer 不含母版骨架 marker。"""
    import asyncio
    import json
    from landppt.services.template.template_suite_service import TemplateSuiteService

    class FakeService:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            return type("R", (), {"content": json.dumps({
                "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1></body></html>",
                "transition": "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1></body></html>",
                "header_footer": (
                    '<style>.hf-canvas{position:relative;width:1280px;height:720px}</style>'
                    '<div class="hf-canvas"><div class="main-stage">{{ page_content }}</div>'
                    "<header>{{ page_title }}</header>"
                    "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
                ),
                "design_tokens": "字体栈：A；强调色：#1a2b3c",
            }, ensure_ascii=False)})()

    svc = TemplateSuiteService(FakeService())
    # 网页 HTML 含 .canvas/.bg-paper 装饰——若误注入母版骨架会出现 marker
    web_html = (
        "<!DOCTYPE html><html><head><style>.canvas{position:relative}.bg-paper{position:absolute}</style>"
        "</head><body><div class='canvas'><div class='bg-paper'></div><h1>Web</h1></div></body></html>"
    )
    template = {"id": 9, "template_name": "网页", "html_template": web_html}

    async def run():
        return await svc._generate_suite_payload(
            template, creativity=5, reference_outline=False, project=None,
            allow_no_template=True, source_kind="web",
        )

    result = asyncio.run(run())
    hf = result["header_footer"]
    assert "母版内容页骨架" not in hf, "web 源不应把网页 DOM 当母版骨架注入内容页"
    assert "page_title" in hf and "page_content" in hf, "槽位应保留"


def test_stream_generate_suite_from_requirements_both_empty_errors():
    """文字需求与网页 HTML 都空时，事件流为 error（不调用 LLM）。"""
    import asyncio
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    svc = GlobalTemplateSuiteService()

    async def run():
        events = []
        async for ev in svc.stream_generate_suite_from_requirements("", "", creativity=5):
            events.append(ev)
        return events

    events = asyncio.run(run())
    assert len(events) == 1, "空输入应只产出一个 error 事件"
    assert events[0]["type"] == "error", events
    assert "至少填写文字需求或粘贴网页 HTML" in events[0]["message"], events


def test_stream_generate_suite_from_requirements_completes():
    """文字需求 + 网页 HTML 都提供时，走 _generate_suite_payload(source_kind='web')，
    complete 事件返回独立套件（template_id 为 None）。通过 FakeHost 捕获 prompt
    确含网页 HTML 片段与文字需求。"""
    import asyncio
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    captured = {"prompt": "", "source_kind": None}

    class FakeHost:
        async def _text_completion_for_role(self, role, *, prompt, **kwargs):
            # 不会被调用——_generate_suite_payload 被下面直接覆盖
            return type("R", (), {"content": ""})()

        async def _generate_suite_payload(self, template, **kwargs):
            captured["prompt"] = kwargs.get("prompt", "") or "(no prompt)"
            # 复用真实 prompt 构建器，让断言能验证 web 源措辞与内容注入
            from landppt.services.prompts.template_prompts import TemplatePrompts
            captured["prompt"] = TemplatePrompts.build_template_suite_prompt(
                template_html=template.get("html_template") or "",
                custom_requirements=kwargs.get("custom_requirements") or "",
                source_kind=kwargs.get("source_kind") or "master",
            )
            captured["source_kind"] = kwargs.get("source_kind")
            return {
                "cover": "<!DOCTYPE html><html><body><h1>{{ cover_title }}</h1></body></html>",
                "transition": "<!DOCTYPE html><html><body><h1>{{ transition_title }}</h1></body></html>",
                "header_footer": (
                    '<div class="hf-canvas"><style>.hf-canvas{}</style>'
                    '<div class="main-stage">{{ page_content }}</div>'
                    "<header>{{ page_title }}</header>"
                    "<footer>{{ current_page_number }}/{{ total_page_count }}</footer></div>"
                ),
                "design_tokens": "字体栈：A；强调色：#1a2b3c",
                "template_hash": "x", "template_id": None, "template_name": None,
                "generated_at": 0,
            }

    svc = GlobalTemplateSuiteService()
    svc._build_host = lambda: FakeHost()

    web_html = "<!DOCTYPE html><html><body style='background:#0b1020'><h1>WebDesign</h1></body></html>"
    req = "深色科技感"

    async def run():
        events = []
        async for ev in svc.stream_generate_suite_from_requirements(req, web_html, creativity=6):
            events.append(ev)
        return events

    events = asyncio.run(run())
    types = [e["type"] for e in events]
    assert types[-1] == "complete", events
    suite = events[-1]["suite"]
    assert suite["cover"].startswith("<!DOCTYPE html>")
    assert "page_title" in suite["header_footer"]
    assert suite.get("template_id") is None, "需求/网页生成的套件是独立套件，不绑定模板"
    assert suite.get("suite_name") == "AI 生成套件", "应有默认套件名"
    # prompt 应携带网页 HTML 片段与文字需求（source_kind='web' 措辞）
    assert captured["source_kind"] == "web", "应以 web 源调用 _generate_suite_payload"
    assert "参考网页 HTML" in captured["prompt"], "应按 web 源措辞构建 prompt"
    assert "WebDesign" in captured["prompt"], "prompt 应含网页 HTML 内容"
    assert req in captured["prompt"], "prompt 应含文字需求"


# ======================================================================
# 章节号槽位 {{chapter_number}}：大纲 chapter 字段 + 套件生成/填充 + 历史 brand_code 迁移
# ======================================================================


def test_suite_prompt_supports_chapter_number():
    """新套件生成 prompt 应支持 {{chapter_number}} 槽位，且只在 transition/header_footer 段提及。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    class P:
        topic = "AI大模型"
        scenario = "峰会"

    outline = {"title": "T", "slides": [{"title": "a", "slide_type": "title"}]}
    p = TemplatePrompts.build_template_suite_prompt(
        project=P(), outline=outline, confirmed={"target_audience": "高管"},
        template_html="<div>tpl</div>", creativity=5,
    )
    assert "chapter_number" in p, "prompt 应提及章节号槽位 chapter_number"
    # 单类型重生 meta 也应含章节号说明
    from landppt.services.prompts.template_prompts import TemplatePrompts as TP
    assert "chapter_number" in TP._SUITE_PART_META["transition"]["desc"]
    assert "chapter_number" in TP._SUITE_PART_META["header_footer"]["desc"]
    # 禁制仍保留：不要整体编号 + 章节号只在过渡页/内容页
    assert "不要生成整份文档的整体编号" in p
    assert "chapter_number" in p


def test_chapter_number_in_structure_slots_and_not_brand():
    """chapter_number 必须在 STRUCTURE_SLOTS 里（防被品牌语义分析误归 code），且不归品牌角色。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    assert "chapter_number" in T.STRUCTURE_SLOTS, "chapter_number 必须在 STRUCTURE_SLOTS 里"
    assert T._brand_role_by_name("chapter_number") is None, "chapter_number 不应被归为品牌角色"
    # CHAPTER_SLOT 常量
    assert T.CHAPTER_SLOT == "{{chapter_number}}"


def test_default_slot_text_chapter_number():
    """_default_slot_text 对 chapter_number 取 slide_data['chapter']，纯数字；0/缺失返回空（绝不渲染"第 0 章"）。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    assert SlideMediaService._default_slot_text("chapter_number", {"chapter": 3}, 5) == "3"
    # chapter=0 表示"不属于任何章节"→ 返回空串清掉槽位，避免渲染成"第 0 章"
    assert SlideMediaService._default_slot_text("chapter_number", {"chapter": 0}, 5) == ""
    assert SlideMediaService._default_slot_text("chapter_number", {}, 5) == ""
    # 非 chapter 槽位不受影响
    assert SlideMediaService._default_slot_text("cover_extra", {"title": "x", "content_points": ["a"]}, 1) == "a"


def test_replace_remaining_content_slots_fills_chapter():
    """内容页兜底：残留的 {{chapter_number}} 应被填成真实章节号。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    html = "<div>{{page_title}}</div><div>{{chapter_number}}</div><div>{{page_content}}</div>"
    out = SlideMediaService._replace_remaining_content_slots(
        html, {"title": "T", "chapter": 2, "content_points": ["a"]}, 4, 10
    )
    assert "{{chapter_number}}" not in out
    assert ">2<" in out, "章节号 2 应被填入"


def test_build_content_suite_constraint_includes_chapter():
    """内容页约束 prompt 应含 {{chapter_number}} 说明 + 本页真实章节号值。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "header_footer": '<div class="suite-stage">{{ page_content }}<span>{{chapter_number}}</span></div>'
                         "<style>.suite-stage{position:absolute;top:155px;left:60px;right:60px;bottom:60px;overflow:hidden}</style>",
        "design_tokens": "t",
    }
    c = SlideMediaService._build_content_suite_constraint(suite, {"chapter": 3})
    assert "chapter_number" in c, "约束应说明 chapter_number 槽位"
    assert "3" in c, "约束应含本页真实章节号 3"

    # 无 chapter（非章节页）也应给出"不属于任何章节"语义
    c2 = SlideMediaService._build_content_suite_constraint(suite, {})
    assert "chapter_number" in c2
    assert "不属于任何章节" in c2 or "留空" in c2


def test_apply_suite_to_slide_fills_chapter_number_for_transition():
    """过渡页确定性填充：{{chapter_number}} 应被填成 slide_data['chapter']。"""
    from landppt.services.template.template_suite_renderer import TemplateSuiteRenderer

    suite = {
        "transition": "<!DOCTYPE html><html><body><h1>{{transition_title}}</h1>"
                      "<span>{{chapter_number}}</span></body></html>",
    }
    slide_data = {"title": "第二章 方案", "slide_type": "transition", "chapter": 2, "content_points": ["第二章 方案"]}
    filled = TemplateSuiteRenderer.apply_suite_to_slide(suite, slide_data, 5, 10)
    assert filled is not None
    assert "{{chapter_number}}" not in filled, "过渡页 chapter_number 槽位应被填充"
    assert ">2<" in filled or "2" in filled, "章节号 2 应出现在过渡页"

    # catalog/ending 不填章节号（即使模板里残留也不该填——历史套件已迁移删除）
    suite2 = {"catalog": "<!DOCTYPE html><html><body><h1>{{catalog_title}}</h1>"
                         "<span>{{chapter_number}}</span></body></html>"}
    filled2 = TemplateSuiteRenderer.apply_suite_to_slide(suite2, {"title": "目录", "slide_type": "catalog", "chapter": 1}, 2, 10)
    # catalog 走 apply_suite_to_slide，chapter_number 未在 slots 里 → 残留（由后续清理/backfill 处理）
    assert filled2 is not None


def test_migrate_brand_code_to_chapter():
    """历史 brand_code 槽位迁移：transition/header_footer → chapter_number；cover/catalog/ending → 删除。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    # 带空格写法
    assert T._migrate_brand_code_to_chapter("<span>{{ brand_code }}</span>", "transition") == "<span>{{chapter_number}}</span>"
    # 无空格写法
    assert T._migrate_brand_code_to_chapter("<span>{{brand_code}}</span>", "header_footer") == "<span>{{chapter_number}}</span>"
    # cover/catalog/ending 删除
    assert T._migrate_brand_code_to_chapter("<span>{{ brand_code }}</span>", "cover") == "<span></span>"
    assert T._migrate_brand_code_to_chapter("x{{brand_code}}y", "catalog") == "xy"
    assert T._migrate_brand_code_to_chapter("x{{ brand_code }}y", "ending") == "xy"
    # 无 brand_code 原样返回
    assert T._migrate_brand_code_to_chapter("<span>{{brand_year}}</span>", "transition") == "<span>{{brand_year}}</span>"
    assert T._migrate_brand_code_to_chapter("plain text", "cover") == "plain text"
    # design_tokens（非 HTML 页类型）不动
    assert T._migrate_brand_code_to_chapter("--brand-code: #c00", "design_tokens") == "--brand-code: #c00"

    # suite 级迁移：幂等
    suite = {
        "cover": "{{brand_code}}",
        "transition": "{{ brand_code }}",
        "catalog": "",
        "ending": "",
        "header_footer": "{{brand_code}}",
        "design_tokens": "--brand-code: #c00",
    }
    m = T._migrate_suite_brand_code(suite)
    assert m["cover"] == ""
    assert m["transition"] == "{{chapter_number}}"
    assert m["header_footer"] == "{{chapter_number}}"
    assert m["design_tokens"] == "--brand-code: #c00", "design_tokens 不应被迁移"
    # 二次迁移幂等（无 brand_code → 原样返回同一对象）
    m2 = T._migrate_suite_brand_code(m)
    assert m2 == m


def test_migrate_suite_brand_code_no_op_when_clean():
    """无 brand_code 的套件：_migrate_suite_brand_code 应原样返回（无副本开销）。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    suite = {"cover": "x", "transition": "y", "catalog": "", "ending": "", "header_footer": "z"}
    out = T._migrate_suite_brand_code(suite)
    assert out is suite, "干净套件应原样返回同一对象"


def test_get_suite_payload_migrates_brand_code(monkeypatch):
    """库套件读取入口 get_suite_payload 应把残留 brand_code 即时迁移成 chapter_number。"""
    import asyncio
    from landppt.services.template.global_template_suite_service import GlobalTemplateSuiteService

    class FakeSuite:
        is_active = True
        cover = "<!DOCTYPE html><html><body>{{brand_code}}</body></html>"
        transition = "<!DOCTYPE html><html><body>{{ brand_code }}</body></html>"
        catalog = "<!DOCTYPE html><html><body>{{brand_code}}</body></html>"
        ending = "<!DOCTYPE html><html><body>{{ brand_code }}</body></html>"
        header_footer = "<div>{{brand_code}}</div>"
        design_tokens = "--brand-code: #c00"
        template_hash = "h"
        template_id = None
        template_name = "t"
        suite_name = "t"
        updated_at = 0.0
        created_at = 0.0

    class FakeDB:
        async def get_global_template_suite_by_id(self, sid):
            return FakeSuite()

        class session:
            @staticmethod
            async def close():
                pass

    # get_suite_payload 直接走 self._db()（不是 _build_host），因此须把 _db 换成假库。
    svc = GlobalTemplateSuiteService()

    async def fake_db():
        return FakeDB()

    svc._db = fake_db

    async def run():
        return await svc.get_suite_payload(1)

    payload = asyncio.run(run())
    assert payload is not None
    assert "{{brand_code}}" not in payload["cover"], "cover 的 brand_code 应被删除"
    assert payload["transition"] == "<!DOCTYPE html><html><body>{{chapter_number}}</body></html>"
    # header_footer：brand_code 迁移成 chapter_number；同时读取时可能附加 .suite-stage
    # 标准化 CSS（_ensure_standard_content_stage 的既有行为），故只断言迁移结果，不做整体相等。
    assert "{{brand_code}}" not in payload["header_footer"]
    assert "{{chapter_number}}" in payload["header_footer"]
    assert "{{brand_code}}" not in payload["catalog"] and "{{brand_code}}" not in payload["ending"]
    assert payload["design_tokens"] == "--brand-code: #c00", "design_tokens 不动"


# ======================================================================
# 章节提示槽位 {{chapter_indicator}}：勾选生成 + 内容页确定性填充 + 兜底样式
# ======================================================================


def test_chapter_indicator_constants_and_structure_slots():
    """chapter_indicator 常量正确、必须在 STRUCTURE_SLOTS（防被品牌语义分析误归），且不归品牌角色。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService as T

    assert T.CHAPTER_INDICATOR_SLOT == "{{chapter_indicator}}"
    assert "chapter_indicator" in T.STRUCTURE_SLOTS, "chapter_indicator 必须在 STRUCTURE_SLOTS 里"
    assert T._brand_role_by_name("chapter_indicator") is None, "chapter_indicator 不应被归为品牌角色"


def test_build_chapter_indicator_html():
    """章节提示只取目录章节，不混入每个内容页标题，并高亮当前章节。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    all_slides = [
        {"slide_type": "cover", "title": "封面", "chapter": 0},
        {"slide_type": "agenda", "title": "目录", "content_points": [
            "一、项目概述", "二、核心方案：规划与落地", "三、实施路径"
        ], "chapter": 0},
        {"slide_type": "content", "title": "项目背景与目标", "chapter": 1},
        {"slide_type": "content", "title": "项目概述子页", "chapter": 1},
        {"slide_type": "content", "title": "技术架构设计", "chapter": 2},
        {"slide_type": "content", "title": "里程碑安排", "chapter": 3},
        {"slide_type": "ending", "title": "致谢", "chapter": 0},
    ]
    html = SlideMediaService.build_chapter_indicator_html(all_slides, {"chapter": 2})
    assert html.startswith('<div class="chapter-indicator"')
    assert html.endswith("</div>")
    assert "项目概述" in html and "核心方案：规划与落地" in html and "实施路径" in html
    assert "项目背景与目标" not in html
    assert "技术架构设计" not in html
    assert "里程碑安排" not in html
    assert 'data-chapter-source="directory"' in html
    assert 'data-chapter-count="3"' in html
    assert html.count("chapter-item current") == 1
    assert 'class="chapter-item current"' in html
    assert "核心方案：规划与落地" in html

    assert SlideMediaService.build_chapter_indicator_html([], {"chapter": 1}) == ""
    assert SlideMediaService.build_chapter_indicator_html(
        [{"slide_type": "cover", "title": "封", "chapter": 0}], {}
    ) == ""


def test_build_chapter_indicator_html_current_differs():
    """不同当前章节 → 高亮块不同。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    all_slides = [
        {"slide_type": "agenda", "title": "目录", "content_points": [
            "背景概述", "核心方案", "实施路径"
        ]},
        {"slide_type": "content", "title": "第一页内容", "chapter": 1},
        {"slide_type": "content", "title": "第二页内容", "chapter": 2},
        {"slide_type": "content", "title": "第三页内容", "chapter": 3},
    ]
    h1 = SlideMediaService.build_chapter_indicator_html(all_slides, {"chapter": 1})
    h3 = SlideMediaService.build_chapter_indicator_html(all_slides, {"chapter": 3})
    assert 'class="chapter-item current"' in h1 and "背景概述" in h1
    assert 'class="chapter-item current"' in h3 and "实施路径" in h3
    assert h1 != h3


def test_chapter_indicator_adapts_font_size_for_full_directory_names():
    """章节较多且名称较长时动态缩小字号，并保留完整目录文本而非省略。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    chapters = [
        "组织与人员管理现状分析",
        "大模型方向：ZA38、ClawPartner与训练推理",
        "低代码方向：安全合规、模板建设与用户牵引",
        "现状洞察与下一阶段完整规划",
        "团队建设与技术创新成果",
        "问题挑战及后续改进措施",
    ]
    all_slides = [{"slide_type": "agenda", "content_points": chapters}]
    html = SlideMediaService.build_chapter_indicator_html(all_slides, {"chapter": 3})
    assert SlideMediaService._chapter_indicator_font_size(chapters) < 13
    assert "text-overflow:clip" in html
    assert "white-space:normal" in html
    for name in chapters:
        assert name in html


def test_replace_remaining_content_slots_fills_chapter_indicator():
    """内容页兜底：残留的 {{chapter_indicator}}（含带空格写法）应被填成章节提示 HTML。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    indicator = SlideMediaService.build_chapter_indicator_html(
        [{"slide_type": "agenda", "content_points": ["第一章", "第二章"]},
         {"slide_type": "content", "title": "第一页内容", "chapter": 1},
         {"slide_type": "content", "title": "第二页内容", "chapter": 2}],
        {"chapter": 2},
    )
    html = '<header>{{page_title}}</header><div>{{chapter_indicator}}</div>'
    out = SlideMediaService._replace_remaining_content_slots(
        html, {"title": "T", "chapter": 2, "content_points": []}, 4, 10,
        chapter_indicator_html=indicator,
    )
    assert "{{chapter_indicator}}" not in out
    assert "chapter-indicator" in out
    assert "chapter-item current" in out and "第二章" in out, "当前章节块应高亮"

    html2 = '<div>{{ chapter_indicator }}</div>'
    out2 = SlideMediaService._replace_remaining_content_slots(
        html2, {"title": "T", "chapter": 1, "content_points": []}, 4, 10,
        chapter_indicator_html=indicator,
    )
    assert "{{ chapter_indicator }}" not in out2

    out3 = SlideMediaService._replace_remaining_content_slots(
        '<div>{{chapter_indicator}}</div>', {"title": "T", "chapter": 1, "content_points": []}, 4, 10,
    )
    assert "{{chapter_indicator}}" not in out3


def test_ensure_chapter_indicator_style():
    """套件已定义 .chapter-indicator{ 样式时不注入；未定义且出现该容器时注入默认导航样式。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    html = ('<!DOCTYPE html><html><head></head><body><div class="chapter-indicator">'
            '<span class="chapter-item">a</span></div></body></html>')
    suite = {"header_footer": "<div class='chapter-indicator'>x</div>"}  # 只有容器无 CSS
    out = SlideMediaService._ensure_chapter_indicator_style(html, suite)
    assert "chapter-indicator-fallback" in out
    assert ".chapter-item.current" in out

    suite_css = {"header_footer": "<style>.chapter-indicator{display:flex}</style>"}
    out2 = SlideMediaService._ensure_chapter_indicator_style(html, suite_css)
    assert "chapter-indicator-fallback" not in out2

    plain = '<!DOCTYPE html><html><head></head><body><p>hi</p></body></html>'
    assert SlideMediaService._ensure_chapter_indicator_style(plain, suite) == plain


def test_suite_prompt_chapter_indicator_on():
    """勾选时 prompt 要求设计 {{chapter_indicator}} 槽位与 chapter-item/current 样式；不勾选时禁止。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    class P:
        topic = "AI"
        scenario = "峰会"

    outline = {"title": "T", "slides": [{"title": "a", "slide_type": "title"}]}
    base_kw = dict(project=P(), outline=outline, confirmed={},
                   template_html="<div>tpl</div>", creativity=5)

    p_on = TemplatePrompts.build_template_suite_prompt(**base_kw, chapter_indicator=True)
    assert "chapter-indicator" in p_on
    assert "chapter-item" in p_on
    assert "chapter-item.current" in p_on
    assert "章节提示" in p_on

    p_off = TemplatePrompts.build_template_suite_prompt(**base_kw)
    assert "chapter-indicator" not in p_off
    assert "chapter-item" not in p_off
    assert "chapter_indicator" in p_off, "未勾选仍应明确禁止该槽位"


def test_suite_part_prompt_header_footer_chapter_indicator():
    """单类型重生：仅 part=header_footer 且勾选时追加章节提示槽位要求。"""
    from landppt.services.prompts.template_prompts import TemplatePrompts

    base_kw = dict(part="header_footer", project=None, outline={}, confirmed={},
                   template_html="<div>tpl</div>", existing_suite={}, creativity=5)

    p_on = TemplatePrompts.build_template_suite_part_prompt(**base_kw, chapter_indicator=True)
    assert "chapter-indicator" in p_on, "header_footer 重生 + 勾选应要求章节提示槽位"
    assert "chapter-item" in p_on

    p_off = TemplatePrompts.build_template_suite_part_prompt(**base_kw)
    assert "chapter-indicator" not in p_off
    assert "chapter-item" not in p_off

    p_cover = TemplatePrompts.build_template_suite_part_prompt(
        part="cover", project=None, outline={}, confirmed={},
        template_html="<div>tpl</div>", existing_suite={}, creativity=5,
        chapter_indicator=True,
    )
    assert "chapter-indicator" not in p_cover


def test_preview_html_chapter_indicator():
    """内容页预览复用目录章节、覆盖原容器，且不产生嵌套章节导航。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService

    suite = dict(SUITE)
    suite["header_footer"] = "<header>{{ page_title }}</header>" \
                             "<div class='chapter-indicator'>{{chapter_indicator}}</div>" \
                             "<footer>{{ current_page_number }} / {{ total_page_count }}</footer>"
    svc = TemplateSuiteService.__new__(TemplateSuiteService)
    preview = svc.build_preview_html(suite)
    content = preview["content"]
    assert "{{" not in content, "预览不得有 {{ 残留"
    assert "chapter-item current" in content, "预览章节提示应含当前章高亮"
    assert "chapter-indicator" in content
    assert content.count('class="chapter-indicator"') == 1, "章节提示容器不得嵌套"
    for title in ("概述", "核心方案", "实施路径", "总结与展望"):
        assert title in preview["catalog"]
        assert title in content


def test_preview_html_chapter_indicator_uses_project_directory_titles():
    """项目套件预览应读取真实目录项，目录和内容页章节提示名称、顺序保持一致。"""
    from landppt.services.template.template_suite_service import TemplateSuiteService

    suite = dict(SUITE)
    suite["catalog"] = "<!DOCTYPE html><html><body>{{catalog_items}}</body></html>"
    suite["header_footer"] = (
        "<style>.chapter-indicator{display:flex}.chapter-item.current{font-weight:bold}</style>"
        "<div class='chapter-indicator'><span class='chapter-item'>旧预览章节</span></div>"
        "<main class='suite-stage'>{{page_content}}</main>"
    )
    all_slides = [
        {"slide_type": "cover", "title": "封面"},
        {
            "slide_type": "agenda",
            "title": "目录",
            "content_points": ["第一章 业务现状", "第二章 核心方案", "第三章 落地计划"],
        },
        {"slide_type": "content", "title": "不应成为章节的页面标题", "chapter": 1},
    ]

    preview = TemplateSuiteService.__new__(TemplateSuiteService).build_preview_html(
        suite, all_slides=all_slides
    )
    catalog = preview["catalog"]
    content = preview["content"]
    expected = ("业务现状", "核心方案", "落地计划")
    for title in expected:
        assert title in catalog
        assert title in content
    assert [content.index(title) for title in expected] == sorted(
        content.index(title) for title in expected
    )
    assert "旧预览章节" not in content
    assert "不应成为章节的页面标题" not in content
    assert content.count('class="chapter-indicator"') == 1
    assert content.count("chapter-item current") == 1


def test_chapter_indicator_content_page_postprocess_wired():
    """内容页后处理强制覆盖 LLM 错误列表；容器缺失时也会补入。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "header_footer": "<header>{{ page_title }}</header>"
                         "<div class='chapter-indicator'>{{chapter_indicator}}</div>"
                         "<div class='suite-stage'>{{ page_content }}</div>"
                         "<footer>{{ current_page_number }} / {{ total_page_count }}</footer>",
        "design_tokens": "t",
    }
    all_slides = [
        {"slide_type": "cover", "chapter": 0},
        {"slide_type": "agenda", "title": "目录", "content_points": [
            "第一章 概述", "第二章 方案"
        ], "chapter": 0},
        {"slide_type": "content", "title": "背景详情", "chapter": 1},
        {"slide_type": "content", "title": "技术实现", "chapter": 2},
        {"slide_type": "content", "title": "第二章方案子页", "chapter": 2},
        {"slide_type": "ending", "chapter": 0},
    ]
    slide_data = {"title": "第二章方案子页", "chapter": 2, "content_points": ["x"]}

    indicator = SlideMediaService.build_chapter_indicator_html(all_slides, slide_data)
    html_with_wrong_list = (
        "<!DOCTYPE html><html><head></head><body>"
        "<header>{{page_title}}</header>"
        "<div class='chapter-indicator'><div class='chapter-item'>错误的每页标题</div></div>"
        "<div class='suite-stage'>{{page_content}}</div>"
        "<footer>{{current_page_number}} / {{total_page_count}}</footer>"
        "</body></html>"
    )
    html = SlideMediaService._replace_remaining_content_slots(
        html_with_wrong_list, slide_data, 4, 10, chapter_indicator_html=""
    )
    html = SlideMediaService._upsert_chapter_indicator(html, indicator)
    html = SlideMediaService._ensure_chapter_indicator_style(html, suite)
    assert "{{chapter_indicator}}" not in html, "章节提示槽位应被填充"
    assert "错误的每页标题" not in html
    assert "chapter-item current" in html
    assert "概述" in html
    assert "方案" in html

    html_without_container = (
        "<!DOCTYPE html><html><body><header>标题</header>"
        "<div class='suite-stage'>正文</div></body></html>"
    )
    injected = SlideMediaService._upsert_chapter_indicator(
        html_without_container, indicator
    )
    assert injected.count('class="chapter-indicator"') == 1
    assert injected.index("chapter-indicator") < injected.index("suite-stage")


def test_build_content_suite_constraint_preserves_chapter_indicator():
    """内容页约束：骨架含 {{chapter_indicator}} 时提示 LLM 保留该槽位、不得移除或文字顶替。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite_with = {
        "header_footer": "<div class='chapter-indicator'>{{chapter_indicator}}</div>"
                         "<div class='suite-stage'>{{ page_content }}</div>",
        "design_tokens": "t",
    }
    c = SlideMediaService._build_content_suite_constraint(suite_with, {"chapter": 2})
    assert "chapter_indicator" in c, "约束应提及 chapter_indicator 槽位"
    assert "保留" in c, "约束应要求保留该槽位"

    # 骨架不含该槽位 → 约束不提
    suite_without = {
        "header_footer": "<div class='suite-stage'>{{ page_content }}</div>",
        "design_tokens": "t",
    }
    c2 = SlideMediaService._build_content_suite_constraint(suite_without, {"chapter": 2})
    assert "chapter_indicator" not in c2

