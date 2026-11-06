import pytest

from landppt.services.content_density import (
    ContentArea, content_blocks, plan_content_density, resolve_content_area, text_units,
)
from landppt.services.slide.slide_media_service import SlideMediaService


def stage(width=1034, height=485):
    return f'<main class="suite-stage" style="width:{width}px;height:{height}px"></main>'


def test_actual_suite_offsets_padding_border_and_cascade():
    html = '''<style>*{box-sizing:border-box}
    :root{--stage-top:155px}
    .suite-stage{position:absolute;inset:193px 123px 80px;padding:10px 20px;border:2px solid}
    .suite-stage{top:var(--stage-top) !important;padding-left:24px}
    </style><main class="suite-stage" style="top:200px"></main>'''
    area = resolve_content_area(html)
    assert area.width == 986  # 1280 - 246 - 44 padding - 4 border
    assert area.height == 461
    assert area.source == 'template_css'


def test_percent_calc_inline_and_content_box_dimensions():
    html = '''<style>.suite-stage{position:absolute;inset:100px 5%;padding:10px;
    width:calc(100% - 160px);height:500px}</style><main class="suite-stage"></main>'''
    area = resolve_content_area(html)
    assert area.width == 1120  # Explicit content-box width, not width minus padding twice.
    assert area.height == 500


def test_nested_positioned_parent_uses_padding_box():
    html = '''<style>*{box-sizing:border-box}.outer{position:relative;width:1000px;height:600px;padding:20px}
    .suite-stage{position:absolute;inset:10px;padding:10px}</style>
    <div class="outer"><main class="suite-stage"></main></div>'''
    area = resolve_content_area(html)
    assert (area.width, area.height) == (960, 560)


def test_clamp_viewport_and_rem_lengths_without_browser():
    html = '''<style>html{font-size:20px}.suite-stage{width:clamp(500px,50vw,900px);
    height:400px;box-sizing:border-box;padding:1rem}</style><main class="suite-stage"></main>'''
    area = resolve_content_area(html)
    # Match the implicit root the browser creates for a fragment.
    assert (area.width, area.height) == (600, 360)
    full = '<html>' + html + '</html>'
    assert resolve_content_area(full).width == 600


def test_suite_priority_and_unknown_geometry_are_conservative():
    context = '套件骨架\n```html\n' + stage(900, 360) + '\n```'
    assert resolve_content_area(stage(1200, 600), context).width == 900
    assert resolve_content_area('<main style="width:fit-content;height:auto"></main>') == ContentArea()
    assert resolve_content_area('<div>no identifiable body</div>') == ContentArea()


def test_flow_template_reserves_large_header_footer_and_body_padding():
    html = '''<style>*{box-sizing:border-box}.slide{width:1280px;height:720px;display:flex;flex-direction:column}
    header{height:250px}footer{height:70px}.slide-content{flex:1;padding:20px}</style>
    <div class="slide"><header>标题</header><main class="slide-content">{{page_content}}</main><footer>页码</footer></div>'''
    area = resolve_content_area(html)
    assert area.height == 360  # 720 - 250 - 70 - 40, not a blind 480px.
    assert area.width <= 1240


def test_max_height_and_sibling_reservation_are_not_subtracted_twice():
    html = '''<style>*{box-sizing:border-box}.slide{height:720px;display:flex;flex-direction:column}
    header{height:100px}.slide-content{flex:1;max-height:300px;padding:20px}</style>
    <div class="slide"><header>标题</header><main class="slide-content"></main></div>'''
    assert resolve_content_area(html).height == 260


def test_real_page_title_wraps_in_flow_header_and_reduces_capacity():
    html = '''<style>*{box-sizing:border-box}.slide{width:800px;height:720px;display:flex;flex-direction:column}
    header{padding:10px}h1{font-size:60px;line-height:1;margin:0}footer{height:60px}.slide-content{flex:1}</style>
    <div class="slide"><header><h1>{{page_title}}</h1></header><main class="slide-content"></main><footer>页码</footer></div>'''
    body = {'content_points': ['事项：明确责任与交付范围']}
    short = plan_content_density({**body, 'title': '简报'}, html)
    long = plan_content_density({**body, 'title': '很长的页面标题' * 8}, html)
    assert long.area.height < short.area.height


def test_shorthand_later_in_cascade_replaces_earlier_side():
    html = '<style>.suite-stage{width:1000px;height:400px;box-sizing:border-box;padding-left:90px;padding:10px}</style><main class="suite-stage"></main>'
    assert resolve_content_area(html).width == 980


def test_content_counts_real_body_not_design_description_or_urls():
    slide = {'content_points': [{'title': '目标', 'text': '明确验收标准', 'url': 'https://invalid/' * 100}],
             'description': '设计说明' * 300, 'image_suggestions': ['a photo']}
    assert content_blocks(slide) == ['目标：明确验收标准']
    assert not plan_content_density(slide).media_height
    assert content_blocks({'content_points': ['同一项', '同一项']}) == ['同一项', '同一项']


def test_aliases_not_double_counted_but_expanded_body_is_counted():
    assert content_blocks({'content_points': ['A', 'B'], 'bullet_points': ['A', 'B']}) == ['A', 'B']
    assert content_blocks({'content_points': ['A', 'B'], 'content': 'A\nB'}) == ['A\nB']
    assert len(content_blocks({'content_points': ['摘要'], 'content': '新增完整事实'})) == 2


def test_cjk_and_explicit_breaks_affect_line_estimates():
    assert text_units('中' * 100) > text_units('a' * 100)
    assert text_units('e\u0301') == text_units('e')
    compact = plan_content_density({'content_points': ['信息' * 10]}, stage(800, 480))
    broken = plan_content_density({'content_points': ['\n'.join(['信息'] * 10)]}, stage(800, 480))
    assert broken.reference_ratio > compact.reference_ratio


def test_more_text_or_less_space_increases_density():
    short = {'content_points': [str(i) + '执行重点' * 3 for i in range(3)]}
    long = {'content_points': [str(i) + '执行重点' * 20 for i in range(3)]}
    large = plan_content_density(long, stage(1100, 540))
    small = plan_content_density(long, stage(800, 300))
    assert large.reference_ratio > plan_content_density(short, stage(1100, 540)).reference_ratio
    assert small.reference_ratio > large.reference_ratio
    assert small.font_size <= large.font_size


def test_asymmetric_longest_point_and_heading_are_not_averaged_away():
    balanced = plan_content_density({'content_points': ['要点：' + '事实' * 30] * 4}, stage(1000, 480))
    skewed = plan_content_density({'content_points': ['要点：' + '事实' * 117] + ['要点：事实'] * 3}, stage(1000, 480))
    assert skewed.longest_point_units > balanced.longest_point_units
    assert skewed.reference_ratio >= balanced.reference_ratio


@pytest.mark.parametrize('media', [{'chart_data': {'series': [1, 2]}}, {'images': [{'width': 4000, 'height': 3000}]}, {'table_data': {'rows': [['a']] * 4}}])
def test_media_reduces_text_capacity_without_using_intrinsic_image_height(media):
    body = {'content_points': ['执行事项：' + '事实说明' * 8 for _ in range(4)]}
    base = plan_content_density(body, stage())
    with_media = plan_content_density({**body, **media}, stage())
    assert 0 < with_media.media_height < with_media.area.height
    assert with_media.text_height < base.text_height
    assert with_media.reference_ratio > base.reference_ratio


def test_impossible_content_and_oversized_media_are_explicit_not_silent_shrinking():
    huge = plan_content_density({'content_points': ['重要事实' * 3000]}, stage(800, 300))
    assert huge.over_capacity and huge.font_size == 18
    assert '预估超容量' in huge.to_prompt()
    assert '必要时拆页' in huge.to_prompt()
    media = plan_content_density({'content_points': ['事实'], 'chart_data': {'series': [1]}, 'media_display_height': 800}, stage())
    assert media.text_height == 0 and media.over_capacity


def test_tiny_and_zero_content_areas_do_not_crash_or_claim_success():
    for width, height in [(100, 50), (0, 0)]:
        plan = plan_content_density({'content_points': ['事实' * 20]}, stage(width, height))
        assert plan.over_capacity
    assert plan_content_density({}) is None


def test_fitting_profiles_keep_reserve_and_column_width_budget():
    for length in (4, 20, 45):
        plan = plan_content_density({'content_points': [str(i) + '字' * length for i in range(6)]}, stage())
        if not plan.over_capacity:
            assert plan.required_height <= plan.text_height
        assert plan.column_width * plan.columns + plan.profile.gap * (plan.columns - 1) <= plan.area.width + .02


def test_suite_constraint_and_density_use_same_actual_bounds():
    html = '<style>.suite-stage{position:absolute;top:193.33px;left:123.33px;right:123.33px;bottom:80px}</style><main class="suite-stage">{{page_content}}</main>'
    constraint = SlideMediaService._build_content_suite_constraint({'header_footer': html})
    assert '1033×447px' in constraint
    assert '内宽 1160px' not in constraint
    assert '1160×~530px' not in constraint
    area = resolve_content_area('', constraint)
    assert area.width == pytest.approx(1033.34)
    assert area.height == pytest.approx(446.67)
