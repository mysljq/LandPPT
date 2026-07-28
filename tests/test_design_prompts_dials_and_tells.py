from landppt.services.prompts import design_prompts as prompts_module


def test_global_constitution_prompt_has_structured_dials_blocks():
    prompt = prompts_module.DesignPrompts.get_global_visual_constitution_prompt(
        confirmed_requirements={"topic": "AI 战略汇报", "target_audience": "高管"},
        template_html="<div class='page'><header></header><main></main><footer></footer></div>",
        total_pages=8,
        first_slide_data={"title": "AI 战略汇报", "slide_type": "cover"},
    )
    assert "===DIALS===" in prompt
    assert "===PALETTE===" in prompt
    assert "===RADIUS===" in prompt
    assert "===HEADER_LOCK===" in prompt
    assert "===FOOTER_LOCK===" in prompt
    assert "font_family" in prompt and "background" in prompt
    assert "icon:" in prompt  # 页头是否带图标的令牌
    assert "DESIGN_VARIANCE" in prompt
    assert "MOTION_INTENSITY" in prompt
    assert "VISUAL_DENSITY" in prompt
    assert "设计定位" in prompt
    assert "三刻度推理表" in prompt


def test_self_check_context_has_ai_tells_blacklist():
    text = prompts_module.DesignPrompts._build_generation_self_check_context()
    assert "AI 套路禁令" in text
    assert "em-dash" in text or "—" in text
    assert "000000" in text and "ffffff" in text
    assert "三张" in text or "三等" in text or "三列" in text
    assert "accent" in text
    # 原有的模板换字自检仍保留
    assert "模板换字" in text or "模板中段骨架" in text


def test_global_constitution_still_forbids_pixel_layout():
    prompt = prompts_module.DesignPrompts.get_global_visual_constitution_prompt(
        confirmed_requirements={"topic": "demo"},
        template_html="",
        total_pages=3,
    )
    # 仍要求不锁死像素布局
    assert "不要给出具体像素布局" in prompt or "具体像素" in prompt


def test_fixed_canvas_guardrails_has_height_budget_rule():
    text = prompts_module.DesignPrompts._build_fixed_canvas_html_guardrails()
    assert "高度预算" in text
    # 横向溢出约束
    assert "1280px" in text or "宽度" in text or "max-width" in text
    # 明确要求宁可减内容也不让内容被裁切
    assert "裁切" in text and ("删次要项" in text or "减少内容" in text or "宁可减少" in text)