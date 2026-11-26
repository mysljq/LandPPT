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


@pytest.mark.asyncio
async def test_outline_completion_can_attach_plan_without_separate_database_write(monkeypatch):
    service = SimpleNamespace(
        _text_completion_for_role=AsyncMock(return_value=SimpleNamespace(
            content='{"groups":[{"pages":[1,2],"reason":"同级方案"}]}'
        )), _strip_think_tags=lambda s: s,
    )
    write = AsyncMock()
    monkeypatch.setitem(sys.modules, "landppt.services.db_project_manager",
                        SimpleNamespace(DatabaseProjectManager=lambda: SimpleNamespace(update_project_data=write)))
    outline = {"slides": [{"title": "A"}, {"title": "B"}]}
    groups = await Planner.prepare(service, "p", outline, outline["slides"], persist=False)
    assert groups[0]["pages"] == [1, 2]
    assert outline["parallel_page_plan"]["fingerprint"] == Planner.fingerprint(outline["slides"])
    write.assert_not_awaited()
    # Opening the outline or starting PPT generation reuses the attached plan.
    assert await Planner.prepare(service, "p", outline, outline["slides"]) == groups
    assert service._text_completion_for_role.await_count == 1


@pytest.mark.asyncio
async def test_failed_regroup_drops_stale_plan():
    service = SimpleNamespace(_text_completion_for_role=AsyncMock(side_effect=RuntimeError("offline")))
    outline = {"slides": [{"title": "changed"}], "parallel_page_plan": {
        "version": 1, "fingerprint": "old", "groups": []}}
    assert await Planner.prepare(service, "p", outline, outline["slides"], persist=False) == []
    assert "parallel_page_plan" not in outline


@pytest.mark.asyncio
@pytest.mark.parametrize("model_fails", [False, True])
async def test_outline_completion_saves_grouping_before_marking_completed(monkeypatch, model_fails):
    from landppt.services.outline.project_outline_repair_service import ProjectOutlineRepairService
    outline = {"title": "报告", "slides": [{"title": "A"}, {"title": "B"}]}
    project = SimpleNamespace(outline=None, todo_board=SimpleNamespace(
        stages=[SimpleNamespace(id="outline_generation", status="running")]))
    events = []

    async def save(project_id, data):
        events.append("save")
        assert ("parallel_page_plan" in data) is (not model_fails)
        return True

    async def completed(*args, **kwargs):
        events.append("completed")

    manager = SimpleNamespace(get_project=AsyncMock(return_value=project),
                              save_project_outline=save, update_project_status=AsyncMock(),
                              update_stage_status=completed)
    monkeypatch.setitem(sys.modules, "landppt.services.db_project_manager",
                        SimpleNamespace(DatabaseProjectManager=lambda: manager))
    completion = AsyncMock(return_value=SimpleNamespace(content='{"groups":[{"pages":[1,2]}]}'))
    if model_fails:
        completion.side_effect = RuntimeError("offline")
    owner = SimpleNamespace(project_manager=manager, _text_completion_for_role=completion,
                            _strip_think_tags=lambda s: s)
    await ProjectOutlineRepairService(owner)._update_outline_generation_stage("p", outline)
    assert events == ["save", "completed"]
    assert project.todo_board.stages[0].status == "completed"
