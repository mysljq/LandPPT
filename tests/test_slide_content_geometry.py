import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from landppt.services.slide.layout_repair_service import LayoutRepairService
from landppt.services.slide.slide_html_recovery_service import SlideHtmlRecoveryService, SlideLayoutOverflowError
from landppt.services.content_density import plan_content_density, resolve_content_area


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def page():
    edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    with sync_playwright() as p:
        executable = edge if edge.exists() else Path(p.chromium.executable_path)
        if not executable.exists():
            pytest.skip('No local Chromium browser available')
        browser = p.chromium.launch(executable_path=str(executable), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        yield page
        browser.close()


@pytest.fixture(scope="module")
def measurement():
    # Run the exact production browser calculation without launching the app.
    tree = ast.parse((ROOT / 'src/landppt/services/pyppeteer_pdf_converter.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'measure_content_overflow')
    return next(n.args[0].value for n in ast.walk(method)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'evaluate' and n.args and isinstance(n.args[0], ast.Constant))


def test_fixed_canvas_width_is_not_the_suite_stage_width(page, measurement):
    html = '''<html><head><style>*{box-sizing:border-box}body{margin:0}
    .suite-stage{position:absolute;left:123px;right:123px;top:155px;bottom:80px;overflow:hidden}
    </style></head><body><main class="suite-stage"><div style="width:1160px;display:flex">
    <article style="width:460px">第一项</article><article style="width:370px">第二项</article>
    <article style="width:330px">第三项</article></div></main></body></html>'''
    page.set_content(html)
    assert page.evaluate(measurement)['overflow_x_px'] > 120
    repair = LayoutRepairService(SimpleNamespace())
    fixed = repair._inject_anti_overflow_css(html)
    assert repair._inject_anti_overflow_css(fixed).count('id="anti-overflow-fix"') == 1
    page.set_content(fixed)
    assert page.evaluate(measurement)['overflow_x_px'] == 0
    assert page.locator('article').all_text_contents() == ['第一项', '第二项', '第三项']


def test_scaled_template_is_not_reported_as_overflow(page, measurement):
    page.set_content('''<body><main style="width:800px;height:500px;transform:scale(.8);transform-origin:top left">
    <p style="width:800px;margin:0">正常目录</p></main></body>''')
    measured = page.evaluate(measurement)
    assert measured['overflow_px'] == measured['overflow_x_px'] == 0
    assert measured['overflows_x'] == []


def test_cropped_watermark_is_ignored_but_real_text_overflow_is_detected(page, measurement):
    page.set_content('''<body><main style="position:relative;width:600px;height:300px;overflow:hidden">
    <div class="bg-number" style="position:absolute;left:500px;top:100px;font-size:400px">01</div>
    <div class="wrapper" style="height:100px;overflow:hidden"><p style="height:150px;margin:0">正文</p></div>
    </main></body>''')
    measured = page.evaluate(measurement)
    assert measured['overflow_x_px'] == measured['overflow_px'] == 0
    assert any(x['cls'] == 'wrapper' and x['item_h'] - x['box_h'] >= 50 for x in measured['overflows'])
    assert page.locator('.bg-number').evaluate('(e)=>getComputedStyle(e).display') != 'none'


@pytest.mark.parametrize('css', [
    'position:absolute;left:123.33px;right:123.33px;top:193.33px;bottom:80px',
    'position:absolute;inset:155px 123px 80px;padding:10px 20px;border:2px solid;box-sizing:border-box',
    'width:clamp(500px,50vw,900px);height:400px;box-sizing:border-box;padding:1rem',
])
def test_static_capacity_bounds_match_browser_content_box(page, css):
    html = f'<style>body{{margin:0}}.suite-stage{{{css}}}</style><main class="suite-stage"></main>'
    page.set_content(html)
    actual = page.locator('main').evaluate('''e=>{const s=getComputedStyle(e);return {
        width:e.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight),
        height:e.clientHeight-parseFloat(s.paddingTop)-parseFloat(s.paddingBottom)}}''')
    estimate = resolve_content_area(html)
    assert estimate.width == pytest.approx(actual['width'], abs=1)
    assert estimate.height == pytest.approx(actual['height'], abs=1)


@pytest.mark.parametrize('points', [
    ['聚焦客户：解决高频需求', '改善交付：减少重复审批', '质量闭环：每周复盘'],
    ['举措：' + '明确交付范围、责任人与验收标准。' * 2] * 5,
    ['措施：' + '明确目标与职责，保留决策和反馈记录。' * 2] * 8,
    ['Step: ' + 'Review requirements and track delivery dependencies. ' * 5] * 3,
    ['W' * 100, '窄栏\n逐行\n展示\n信息'],
])
def test_recommended_typography_fits_when_rendered_with_its_budget(page, points):
    import html
    import re
    skeleton = '<main class="suite-stage" style="width:1100px;height:520px"></main>'
    plan = plan_content_density({'content_points': points}, skeleton)
    assert not plan.over_capacity
    cards = []
    heading_size = min(plan.profile.heading_size, plan.font_size + 4)
    for point in points:
        split = re.match(r'^([^：:\n]{1,30})[：:]\s*(.+)$', point, re.S)
        if split:
            title, text = split.groups()
            title = f'<h3>{html.escape(title)}</h3>'
        else:
            title, text = '', point
        cards.append(f'<article>{title}<p>{html.escape(text)}</p></article>')
    markup = f'''<style>*{{box-sizing:border-box}}body{{margin:0}}
        main{{width:{plan.area.width}px;height:{plan.text_height}px;display:grid;align-content:start;
        grid-template-columns:repeat({plan.columns},minmax(0,1fr));gap:{plan.profile.gap}px}}
        article{{padding:{plan.profile.padding}px;min-width:0}}
        p,h3{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-family:Arial,'Microsoft YaHei',sans-serif}}
        p{{font-size:{plan.font_size}px;line-height:{plan.profile.line_height}}}
        h3{{font-size:{heading_size}px;line-height:1.2;margin-bottom:6px}}
        </style><main>{''.join(cards)}</main>'''
    page.set_content(markup)
    measured = page.locator('main').evaluate('e=>({height:e.scrollHeight,width:e.scrollWidth,boxH:e.clientHeight,boxW:e.clientWidth})')
    assert measured['height'] <= measured['boxH'] + 1
    assert measured['width'] <= measured['boxW'] + 1


@pytest.mark.asyncio
@pytest.mark.parametrize('aesthetic_hard', [[], ['审美未通过']])
@pytest.mark.parametrize('overflow', [
    {'overflow_x_px': 127},
    {'overflows_x': [{'item_w': 400, 'box_w': 200}]},
    {'overflows': [{'item_h': 500, 'box_h': 300}]},
])
async def test_exhausted_retries_never_deliver_known_clipped_html(aesthetic_hard, overflow):
    async def complete(*args, **kwargs):
        return SimpleNamespace(content='<html><head></head><body>Generated complete slide</body></html>')

    async def measure(*args):
        return overflow

    async def should_not_deliver(*args):
        pytest.fail('A known clipped slide must not reach delivery/vision repair')

    owner = SimpleNamespace(
        _parse_header_lock=lambda _: {}, _parse_footer_lock=lambda _: {},
        _text_completion_for_role=complete, _measure_overflow=measure,
        _clean_html_response=lambda h: h, _inject_anti_overflow_css=lambda h: h,
        _validate_html_completeness=lambda h: {'is_complete': True, 'missing_elements': [], 'errors': []},
        _aesthetic_preflight_check=lambda *a, **kw: (aesthetic_hard, []),
        _apply_auto_layout_repair=should_not_deliver,
        _generate_fallback_slide_html=lambda *a: pytest.fail('Do not hide layout failure behind a fallback'),
    )
    service = SlideHtmlRecoveryService(owner)
    service._measure_overflow = measure
    with pytest.raises(SlideLayoutOverflowError, match='第 6 页'):
        await service._generate_html_with_retry('', '', {}, 6, 18, max_retries=1)
