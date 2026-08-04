"""Tests for the template-suite extractor and renderer."""
import json

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


def test_renderer_returns_none_when_entry_missing():
    assert TemplateSuiteRenderer.apply_suite_to_slide(
        {"cover": ""}, {"title": "x", "slide_type": "title"}, 1, 10
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
    suite["header_footer"] = "<header>{{ page_title }}</header><footer>{{ current_page_number }} / {{ total_page_count }}</footer>"
    preview = svc.build_preview_html(suite)

    assert set(preview.keys()) == {"cover", "transition", "content"}
    for key, html in preview.items():
        assert html.strip().lower().startswith("<!doctype html"), f"{key} must be a full document"
        assert "{{" not in html, f"{key} should have all slots filled"
    assert "演示文稿标题" in preview["cover"]
    assert "章节" in preview["transition"]
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
