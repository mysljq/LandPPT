import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.slide.slide_task_scheduler import stream_slide_tasks
from landppt.services.slide.creative_design_service import CreativeDesignService
from landppt.services.slide.slide_html_recovery_service import SlideHtmlRecoveryService


@pytest.mark.asyncio
async def test_scheduler_refills_while_slow_page_runs_and_waits_for_saved_reference():
    slow = asyncio.Event()
    third_started = asyncio.Event()
    saved = set()
    active = 0
    peak = 0

    async def generate(idx, slide):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            if idx == 0:
                await slow.wait()
            if idx == 2:
                third_started.set()
            if idx == 3:
                assert 1 in saved
            return idx
        finally:
            active -= 1

    async def consume():
        async for idx in stream_slide_tasks(
            list(enumerate([{}] * 4)), generate, 2,
            [{"reference_page": 2, "pages": [2, 4]}], AsyncMock(return_value=False),
        ):
            saved.add(idx)

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(third_started.wait(), 1)
        assert not slow.is_set()
        slow.set()
        await asyncio.wait_for(task, 1)
        assert saved == {0, 1, 2, 3}
        assert peak <= 2
    finally:
        slow.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_scheduler_cancels_running_requests_without_starting_pending_pages():
    cancelled = False
    started = asyncio.Event()
    stopped = asyncio.Event()
    seen = []

    async def generate(idx, slide):
        seen.append(idx)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def check():
        return cancelled

    async def consume():
        async for result in stream_slide_tasks([(0, {}), (1, {})], generate, 1, [], check):
            assert result is None

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    cancelled = True
    await asyncio.wait_for(task, 1)
    assert stopped.is_set()
    assert seen == [0]


@pytest.mark.asyncio
async def test_scheduler_closing_stream_cancels_remaining_tasks():
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def generate(idx, slide):
        if idx == 0:
            await started.wait()
            return idx
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    stream = stream_slide_tasks([(0, {}), (1, {})], generate, 2, [], AsyncMock(return_value=False))
    assert await asyncio.wait_for(anext(stream), 1) == 0
    await stream.aclose()
    assert stopped.is_set()


def creative_owner(response):
    return SimpleNamespace(
        _text_completion_for_role=AsyncMock(return_value=SimpleNamespace(content=response)),
        _strip_think_tags=lambda text: text,
    )


@pytest.mark.asyncio
async def test_four_pages_share_one_call_but_have_independent_designs():
    owner = creative_owner(json.dumps({"guides": [
        {"page": p, "guide": f"A-F: page {p} unique design"} for p in range(1, 5)
    ]}))
    service = CreativeDesignService(owner)
    slides = [{"title": f"Page {p}"} for p in range(1, 6)]
    results = await asyncio.gather(*[
        service._generate_slide_creative_guide(
            slides[p - 1], p, 5, all_slides=slides, project_id="deck",
        ) for p in range(1, 5)
    ])
    assert len(set(results)) == 4
    assert owner._text_completion_for_role.await_count == 1
    prompt = owner._text_completion_for_role.call_args.kwargs['prompt']
    assert 'Page 4' in prompt and '禁止按类型共用' in prompt
    service.clear_cached_style_genes("deck")
    assert owner._batched_slide_guide_tasks == {}


@pytest.mark.asyncio
async def test_missing_batch_page_falls_back_only_for_that_page():
    owner = creative_owner('')
    owner._text_completion_for_role.side_effect = [
        SimpleNamespace(content='{"guides":[{"page":1,"guide":"design one"}]}'),
        SimpleNamespace(content='independent design two'),
    ]
    service = CreativeDesignService(owner)
    slides = [{"title": "One"}, {"title": "Two"}]
    guides = await asyncio.gather(*[
        service._generate_slide_creative_guide(
            slides[p - 1], p, 2, all_slides=slides, project_id="deck",
        ) for p in (1, 2)
    ])
    assert guides == ['design one', 'independent design two']
    assert owner._text_completion_for_role.await_count == 2


HTML = '<html><head><style>.card{gap:40px}</style></head><body><div>保留全部正文</div></body></html>'


def recovery_service(responses):
    owner = SimpleNamespace(
        _text_completion_for_role=AsyncMock(side_effect=[SimpleNamespace(content=r) for r in responses]),
        _strip_think_tags=lambda text: text,
        _parse_header_lock=lambda _: None, _parse_footer_lock=lambda _: None,
        _clean_html_response=lambda text: text, _inject_anti_overflow_css=lambda text: text,
        _validate_html_completeness=lambda _: {'is_complete': True, 'errors': [], 'missing_elements': []},
        _aesthetic_preflight_check=lambda *a, **kw: ([], []),
        _apply_auto_layout_repair=AsyncMock(side_effect=lambda html, *a: html),
        _generate_fallback_slide_html=lambda *a: 'fallback',
    )
    return SlideHtmlRecoveryService(owner), owner


@pytest.mark.asyncio
@pytest.mark.parametrize('overflow', [
    {'overflow_px': 50, 'overflow_ratio': .1},
    {'overflow_x_px': 50, 'overflow_x_ratio': .1},
    {'zone_overlap': {'overlap_px': 50}},
    {'overflows': [{'item_h': 600, 'box_h': 540}]},
])
async def test_overflow_uses_small_edits_and_revalidates(overflow):
    edits = json.dumps({'edits': [{'old': 'gap:40px', 'new': 'gap:8px'}]})
    service, owner = recovery_service([HTML, edits])
    service._measure_overflow = AsyncMock(side_effect=[overflow, {}])
    result = await service._generate_html_with_retry('context', 'system', {}, 1, 1, 5)
    assert result == HTML.replace('gap:40px', 'gap:8px')
    assert owner._text_completion_for_role.await_count == 2
    assert service._measure_overflow.await_count == 2
    assert owner._text_completion_for_role.call_args.kwargs['max_tokens'] == 2500


@pytest.mark.asyncio
@pytest.mark.parametrize('edits', [
    [{'old': '不存在', 'new': 'x'}],
    [{'old': '保留全部正文', 'new': '删掉正文'}],
    [{'old': 'gap:40px', 'new': 'gap:8px'}, {'old': '40px', 'new': '4px'}],
    [],
])
async def test_bad_or_destructive_edits_are_rejected(edits):
    service, _ = recovery_service([json.dumps({'edits': edits})])
    assert await service._repair_html_with_edits(HTML, 'overflow', 'sys', {}) is None


@pytest.mark.asyncio
async def test_failed_patch_falls_back_to_one_fresh_generation():
    service, owner = recovery_service([HTML, 'bad patch', HTML.replace('40px', '8px')])
    service._measure_overflow = AsyncMock(side_effect=[{'overflow_px': 40}, {}])
    result = await service._generate_html_with_retry('context', 'system', {}, 1, 1, 5)
    assert '8px' in result
    assert owner._text_completion_for_role.await_count == 3


@pytest.mark.asyncio
async def test_cancelled_guide_can_be_resumed(tmp_path):
    owner = creative_owner('')
    owner.cache_dirs = {'style_genes': tmp_path}
    started = asyncio.Event()

    async def slow_response(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    owner._text_completion_for_role.side_effect = slow_response
    service = CreativeDesignService(owner)
    slides = [{'title': 'One'}, {'title': 'Two'}]
    kwargs = dict(project_id='deck', slide_data=slides[0], page_number=1,
                  total_pages=2, all_slides=slides)
    task = asyncio.create_task(service._get_or_generate_slide_creative_guide(**kwargs))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    owner._text_completion_for_role.side_effect = None
    owner._text_completion_for_role.return_value = SimpleNamespace(
        content='{"guides":[{"page":1,"guide":"resumed design"}]}')
    assert await service._get_or_generate_slide_creative_guide(**kwargs) == 'resumed design'


@pytest.mark.asyncio
async def test_generation_pipeline_saves_reference_before_dependents_and_skips_existing(monkeypatch):
    from landppt.services.slide.slide_generation_service import SlideGenerationService
    from landppt.services.slide.parallel_page_service import ParallelPageService
    import landppt.services.cache_service as cache_module

    slides = [{'title': str(p)} for p in range(4)]
    existing = {'page_number': 1, 'html_content': 'USER EDIT', 'is_user_edited': True}
    project = SimpleNamespace(
        outline={'slides': slides}, slides_data=[], confirmed_requirements={'topic': 'Test'},
        title='Test', topic='Test',
    )
    saved = {0: existing}
    calls = []

    async def generate(slide, requirements, prompt, page, *args):
        calls.append(page)
        if page == 4:
            assert 1 in saved
        return f'<html>page {page}</html>'

    async def save(project_id, idx, data, **kwargs):
        saved[idx] = data

    db = SimpleNamespace(
        get_single_slide=AsyncMock(side_effect=lambda project_id, idx: saved.get(idx)),
        save_single_slide=AsyncMock(side_effect=save), update_stage_status=AsyncMock(),
        update_project_data=AsyncMock(),
    )
    monkeypatch.setitem(sys.modules, 'landppt.services.db_project_manager',
                        SimpleNamespace(DatabaseProjectManager=lambda: db))
    monkeypatch.setattr(cache_module, 'get_cache_service', AsyncMock(return_value=None))
    monkeypatch.setattr(ParallelPageService, 'prepare', AsyncMock(return_value=[
        {'reference_page': 2, 'pages': [2, 4]},
    ]))
    owner = SimpleNamespace(
        user_id=None, project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project)),
        _get_user_generation_config=AsyncMock(return_value={
            'enable_parallel_generation': True, 'parallel_slides_count': 2,
        }),
        _is_slides_generation_cancelled=AsyncMock(return_value=False),
        _load_prompts_md_system_prompt=lambda: 'system',
        _prepare_project_creative_guidance=AsyncMock(),
        _generate_single_slide_html_with_prompts=generate,
        _combine_slides_to_full_html=lambda *a: 'combined',
    )
    events = [json.loads(chunk.removeprefix('data: ')) async for chunk in
              SlideGenerationService(owner)._generate_slides_streaming_impl('deck')]
    assert not [e for e in events if e.get('type') == 'error']
    assert set(calls) == {2, 3, 4}
    assert saved[0] == existing
    assert len(saved) == 4
    assert events[-1]['type'] == 'complete'
