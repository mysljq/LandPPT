import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.slide.parallel_page_service import ParallelPageService as Planner


def test_groups_reject_invalid_pages_and_special_pages():
    slides = [{"type": "cover"}, {}, {}, {}, {}]
    result = Planner.validate_groups([
        {"pages": [True, 0, 1, 2, 3, 99, "4", 3]},
        {"pages": [3, 4, 5]},
    ], slides)
    assert [g["pages"] for g in result] == [[2, 3], [4, 5]]


def test_batches_finish_references_before_dependents():
    groups = [{"reference_page": 2, "pages": [2, 4, 5]},
              {"reference_page": 3, "pages": [3, 6]}]
    assert Planner.batch_end(0, 6, groups) == 3
    assert Planner.batch_end(3, 6, groups) == 6
    assert Planner.batch_end(0, 1, groups) == 1


@pytest.mark.asyncio
async def test_reference_always_uses_group_first_page_and_invalidates_outline(monkeypatch):
    slides = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
    groups = [{"pages": [1, 2, 3], "reason": "并列方案"}]
    outline = {"slides": slides, "parallel_page_plan": {
        "version": 1, "fingerprint": Planner.fingerprint(slides), "groups": groups}}
    manager = SimpleNamespace(
        get_project=AsyncMock(return_value=SimpleNamespace(outline=outline)),
        get_single_slide=AsyncMock(return_value={"html_content": "<html>BASE</html>"}),
    )
    monkeypatch.setitem(sys.modules, "landppt.services.db_project_manager",
                        SimpleNamespace(DatabaseProjectManager=lambda: manager))
    for page in (2, 3):
        context = await Planner.reference_context("p", page, slides, [])
        assert "<html>BASE</html>" in context
        assert "按本页内容独立绘制" in context
        manager.get_single_slide.assert_awaited_with("p", 0)
    manager.get_single_slide.return_value = {"html_content": "生成失败"}
    assert "基准页不可用" in await Planner.reference_context("p", 2, slides, [])
    slides[1]["title"] = "changed"
    assert await Planner.reference_context("p", 2, slides, []) == ""


@pytest.mark.asyncio
async def test_malformed_planning_response_degrades_without_persisting():
    service = SimpleNamespace(_text_completion_for_role=AsyncMock(return_value=SimpleNamespace(content="bad json")),
                              _strip_think_tags=lambda s: s)
    outline = {"slides": [{}, {}]}
    assert await Planner.prepare(service, "p", outline, outline["slides"]) == []
    assert "parallel_page_plan" not in outline
