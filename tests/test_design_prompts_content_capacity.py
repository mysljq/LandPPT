"""Capacity hints must reflect body length, rather than the number of bullets."""
import pytest

from landppt.services.prompts import design_prompts


@pytest.mark.parametrize("field", ["content_points", "bullet_points", "content", "description"])
def test_short_body_gets_sparse_guidance(field):
    hint = design_prompts.DesignPrompts._build_slide_content_fit_context({field: "缩短交付周期，减少重复审批。"})
    assert "短内容页" in hint
    assert "密度档：稀疏" in hint
    assert "正文建议 26px" in hint
    assert "不统一大字号" in hint


def test_three_long_points_are_not_treated_as_three_short_labels():
    hint = design_prompts.DesignPrompts._build_slide_content_fit_context({
        "content_points": [prefix + "确认客户目标、现有流程和验收条件。" * 5 for prefix in ("需求", "协同", "验收")],
    })
    assert "成段内容" in hint
    assert "密度档：稀疏" not in hint


def test_long_body_is_not_hidden_by_short_bullet_summary():
    hint = design_prompts.DesignPrompts._build_slide_content_fit_context({
        "content_points": ["需求", "协同", "验收"],
        "content": "明确交付范围与验收条件。" * 50,
    })
    assert "密度档：密集" in hint


@pytest.mark.parametrize("data", [{}, {"title": "只提供标题"}, {"slide_type": "cover", "content": "短内容"}, {"type": "transition", "content": "章节提示"}])
def test_missing_body_and_special_pages_do_not_get_ordinary_capacity_hint(data):
    assert design_prompts.DesignPrompts._build_slide_content_fit_context(data) == ""


@pytest.mark.parametrize("page", [1, 8])
def test_cover_and_ending_positions_are_exempt_even_without_type(page):
    assert design_prompts.DesignPrompts._build_slide_content_fit_context(
        {"content_points": ["项目介绍"]}, page_number=page, total_pages=8) == ""


def test_both_html_generation_routes_receive_capacity_hint(monkeypatch):
    monkeypatch.setattr(design_prompts, "_is_image_service_enabled", lambda: False)
    shared = dict(slide_data={"title": "执行重点", "content_points": ["缩短交付周期。"]},
                  template_html="", page_number=3, total_pages=8, context_info="", style_genes="")
    direct = design_prompts.DesignPrompts.get_single_slide_html_prompt(**shared, confirmed_requirements={})
    creative = design_prompts.DesignPrompts.get_creative_template_context_prompt(
        **shared, slide_title="执行重点", slide_type="content")
    assert "本页正文容量提示" in direct
    assert "本页正文容量提示" in creative
