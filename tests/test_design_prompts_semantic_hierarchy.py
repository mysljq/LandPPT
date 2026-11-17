import pytest

from landppt.services.prompts.design_prompts import DesignPrompts as P


@pytest.mark.parametrize('point_count', [3, 4, 5])
def test_peer_guidance_does_not_invent_a_featured_item(point_count, monkeypatch):
    monkeypatch.setattr('landppt.services.prompts.design_prompts._is_image_service_enabled', lambda: False)
    prompt = P.get_slide_design_guide_prompt(
        slide_data={'title':'同级举措', 'content_points':[f'举措{i}' for i in range(point_count)]},
        confirmed_requirements={'topic':'工作计划'}, slides_summary='',page_number=2,total_pages=8,
    )
    assert '不因缺少“核心”等标记词而一律判为并列' in prompt
    assert '首项/末项' in prompt
    assert '内容逻辑或叙述角色' in prompt
    for obsolete in ('仍要主动制造视觉层次','即使三项内容对等，也要用 2+1','也必须主动建立视觉层次'):
        assert obsolete not in prompt


def test_true_core_recommendation_and_current_state_remain_supported():
    context=P._build_semantic_hierarchy_context()
    assert '核心/推荐' in context and '当前步骤/选中状态' in context
    assert '比较结果' in context
    assert '数值不同不自动表示推荐' in context
    assert '标题、正文、注释' in context


def test_rules_reach_all_guidance_layers_and_final_self_check():
    global_prompt=P.get_global_visual_constitution_prompt({},'',8)
    page_prompt=P.get_page_creative_briefs_prompt({},[{'title':'概览'}],8,'旧指导偏好非对称')
    for prompt in (global_prompt,page_prompt,P._build_content_quality_context()):
        assert '真正并列的同组条目同级同权' in prompt
        assert '历史创意指导' in prompt
    assert '撤销无依据高亮' in P._build_generation_self_check_context()
    assert '并列同权' in P._build_slide_generation_principles_context()


@pytest.mark.parametrize('slide', [
    {'title':'模块说明','content_points':['模块一：目标、措施、结果','模块二：目标、措施、结果','模块三：目标、措施、结果']},
    {'title':'工作归属','content_points':['第一组包含两个子项','第二组包含三个子项']},
    {'title':'操作流程','content_points':['准备','执行','确认']},
])
def test_group_boundaries_are_preserved_without_forcing_everything_into_cards(slide, monkeypatch):
    monkeypatch.setattr('landppt.services.prompts.design_prompts._is_image_service_enabled', lambda:False)
    prompt=P.get_slide_design_guide_prompt(slide,{},'',2,8)
    assert '优先使用卡片/面板' in prompt
    assert '不强制全卡片或全无卡片' in prompt
    assert '组内区分标题、正文、辅助说明' in prompt
    assert '同级同样式，非并列按角色区分' in prompt


def test_grouping_reaches_global_page_and_output_review():
    for prompt in (P.get_global_visual_constitution_prompt({},'',8),
                   P.get_page_creative_briefs_prompt({},[],8,'')):
        assert '信息分组与容器选择' in prompt
    assert '混读时增加卡片/面板' in P._build_generation_self_check_context()


@pytest.mark.parametrize('points', [
    ['需求不明确会造成返工','采用需求评审降低返工风险'],
    ['客户流失率下降','用户访谈和交易数据支持这一结论'],
    ['业务目标','实现目标所需的资源与具体措施'],
])
def test_non_peer_relations_can_be_emphasized_without_magic_words(points, monkeypatch):
    monkeypatch.setattr('landppt.services.prompts.design_prompts._is_image_service_enabled',lambda:False)
    prompt=P.get_slide_design_guide_prompt({'title':'分析','content_points':points},{},'',2,8)
    assert '不因缺少“核心”等标记词而一律判为并列' in prompt
    assert '非并列关系应有可见层级与对比' in prompt
    assert '没有主次证据时默认并列' not in prompt
    assert '只有原文明确标出' not in prompt
    check=P._build_generation_self_check_context()
    assert '非并列是否被过度同质化' in check
    assert '保留有语义依据的强调与对比' in check
