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
    assert m and "top:130px" in m.group(1) and "overflow:hidden" in m.group(1), "应注入标准 CSS 覆盖错误 top"

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
    assert ".suite-stage{position:absolute;top:130px" in p or "top:130px" in p
    assert "overflow:hidden" in p


def test_content_suite_constraint_mentions_standard_stage_and_column_basis():
    """A2 B4 + A3：内容页约束 prompt 应说明 .suite-stage 容器与列宽基准 1160px。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {
        "header_footer": '<div class="suite-stage">{{ page_content }}</div>'
                         "<style>.suite-stage{position:absolute;top:130px;left:60px;right:60px;bottom:60px;overflow:hidden}</style>",
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


def test_brand_context_extracts_from_project_and_requirements():
    """品牌上下文：topic/title/audience 从 confirmed_requirements；year 优先 project.created_at。"""
    import asyncio
    from types import SimpleNamespace
    from landppt.services.slide.slide_media_service import SlideMediaService

    class FakePM:
        def __init__(self, project):
            self._p = project

        async def get_project(self, project_id):
            return self._p

    class Host:
        pass

    # 有 project + created_at（2026-08-11 时间戳 ≈ 1786446950 → 2026 年）
    project = SimpleNamespace(
        topic="部门工作情况汇报", title="部门工作情况汇报 - general",
        created_at=1786446950.66,
    )
    svc = SlideMediaService(Host())
    svc.project_manager = FakePM(project)

    async def run():
        return await svc._get_brand_context("p1", {"topic": "部门工作情况汇报", "target_audience": "企业管理层"})

    ctx = asyncio.run(run())
    assert ctx["topic"] == "部门工作情况汇报"
    assert ctx["year"] == "2026", "应从 created_at 推导年份"
    assert ctx["audience"] == "企业管理层"

    # 无 project（project_id=None）→ year 用当前年份，仍返回结构
    svc2 = SlideMediaService(Host())
    ctx2 = asyncio.run(svc2._get_brand_context(None, {"topic": "T"}))
    assert ctx2["topic"] == "T"
    assert ctx2["year"], "无 project 时也应给当前年份"


def test_brand_replace_instruction_lists_year_topic_and_department():
    """品牌替换指令：包含年份/部门/主题语义化替换要求，且明确不动结构/正文。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    ctx = {"topic": "部门工作情况汇报", "title": "部门工作情况汇报", "year": "2026", "audience": "企业管理层"}
    inst = SlideMediaService._build_brand_replace_instruction(ctx)
    assert "2026" in inst
    assert "部门工作情况汇报" in inst
    assert "DEPARTMENT · WORK REPORT" in inst, "应点名常见部门英文标识示例"
    assert "只替换品牌装饰区" in inst or "不动正文" in inst
    assert "不要臆造" in inst

    assert SlideMediaService._build_brand_replace_instruction(None) == ""
    assert SlideMediaService._build_brand_replace_instruction({}) == ""


def test_content_constraint_injects_brand_instruction_when_context_given():
    """内容页约束：传 brand_context 时注入品牌替换指令，不传时不影响。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    suite = {"header_footer": '<div class="suite-stage">{{ page_content }}</div>', "design_tokens": "t"}
    base = SlideMediaService._build_content_suite_constraint(suite)
    assert "品牌装饰文案语义化替换" not in base

    with_brand = SlideMediaService._build_content_suite_constraint(
        suite, {"topic": "T", "title": "T", "year": "2026"}
    )
    assert "品牌装饰文案语义化替换" in with_brand
    assert "2026" in with_brand


def test_extract_html_from_response_handles_code_fence():
    """从 LLM 响应提取 HTML：兼容 ```html ... ``` 包裹与裸 HTML。"""
    from landppt.services.slide.slide_media_service import SlideMediaService

    fenced = "```html\n<!DOCTYPE html><html><head></head><body>x</body></html>\n```"
    out = SlideMediaService._extract_html_from_response(fenced)
    assert out.startswith("<!DOCTYPE html>") and "</html>" in out and "```" not in out

    bare = "<!DOCTYPE html><html><body>y</body></html>"
    assert SlideMediaService._extract_html_from_response(bare).startswith("<!DOCTYPE html>")

    assert SlideMediaService._extract_html_from_response("") == ""
    assert SlideMediaService._extract_html_from_response("没有 HTML") == ""


def test_semantic_brand_replace_respects_flag_and_empty_context():
    """品牌语义化替换：brand_context 为空或开关关闭时原样返回（不调 LLM）。"""
    import asyncio
    import os
    from types import SimpleNamespace
    from landppt.services.slide.slide_media_service import SlideMediaService

    html = "<!DOCTYPE html><html><body>2024</body></html>"
    svc = SlideMediaService(SimpleNamespace())

    # 空上下文 → 原样
    assert asyncio.run(svc._semantic_brand_replace(html, None, 1)) == html

    # 开关关闭 → 原样
    old = os.getenv("ENABLE_BRAND_SEMANTIC_REPLACE")
    os.environ["ENABLE_BRAND_SEMANTIC_REPLACE"] = "false"
    try:
        ctx = {"topic": "T", "title": "T", "year": "2026"}
        assert asyncio.run(svc._semantic_brand_replace(html, ctx, 1)) == html
    finally:
        if old is None:
            os.environ.pop("ENABLE_BRAND_SEMANTIC_REPLACE", None)
        else:
            os.environ["ENABLE_BRAND_SEMANTIC_REPLACE"] = old
