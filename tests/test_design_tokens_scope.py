"""Regression checks for visual tokens versus template structure/content."""
import json
from pathlib import Path

from landppt.services.prompts.template_prompts import TemplatePrompts
from landppt.services.slide.creative_design_service import CreativeDesignService
from landppt.services.slide.slide_media_service import SlideMediaService
from landppt.services.template.master_layout_extractor import MasterLayoutExtractor


def test_extracted_tokens_keep_shared_style_but_not_region_rules():
    header = '<header style="font-family:Example Sans;color:#c8152d;background:#f2f2f2;top:33px">title</header>'
    footer = '<footer style="font-size:17px;color:#626870;bottom:20px">7</footer>'
    tokens = MasterLayoutExtractor._extract_design_tokens(header, footer, '', '')
    assert 'Example Sans' in tokens and '#c8152d' in tokens
    for region_value in ('#f2f2f2', '#626870', '17px', '33px', '20px', '页码', '页头'):
        assert region_value not in tokens


def test_suite_generation_requests_reusable_tokens():
    prompt = TemplatePrompts.build_template_suite_prompt()
    spec = prompt.split('7. `design_tokens`：', 1)[1].split('\n8.', 1)[0]
    assert '跨主题复用' in spec
    assert '属于 HTML 骨架' in spec
    assert '具体内容示例' in spec
    example = json.loads(prompt.split('```json', 1)[1].split('```', 1)[0])
    assert '字号/字重' in example['design_tokens']
    assert '页头背景' not in example['design_tokens'] and '页码样式' not in example['design_tokens']


def test_current_suite_tokens_do_not_embed_project_or_template_geometry():
    path = Path(__file__).resolve().parents[1] / 'template_examples/classic_red_white_v2/suite.json'
    suite = json.loads(path.read_text(encoding='utf8'))
    tokens = suite['design_tokens']
    for private_rule in ('LLM', 'Loop', 'Graph', 'Prompt', 'Context', 'Harness', '94号',
                         '95号', '1120', '446', '页头', '页尾', '页脚', '页码', 'Logo',
                         '.suite-', '具体参考', '管理汇报'):
        assert private_rule not in tokens
    # Tokens and structural markup both reach consumers without conflation.
    for topic in ('季度经营分析', '医学实验结果', '课程学习计划'):
        context = SlideMediaService._build_content_suite_constraint(suite, {'title': topic})
        assert tokens in context and suite['header_footer'] in context
        assert topic not in tokens
    assert tokens in CreativeDesignService._build_suite_design_context(suite)
