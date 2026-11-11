from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import ast
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from landppt.services.slide.slide_reset_service import SlideResetService


def result(value):
    return SimpleNamespace(scalar_one_or_none=lambda: value,
                           scalars=lambda: SimpleNamespace(all=lambda: value))


@pytest.mark.asyncio
async def test_reset_preserves_outline_configuration_and_clears_generation():
    project = SimpleNamespace(outline={"slides": [1, 2]}, confirmed_requirements={"topic": "demo"},
                              project_metadata={"selected_global_suite_id": 94}, slides_html="old", slides_data=[1], status="completed")
    stages = [SimpleNamespace(stage_id=name, stage_index=i, status="completed", progress=100, result={"old": True})
              for i, name in enumerate(["requirements_confirmation", "outline_generation", "ppt_creation"])]
    board = SimpleNamespace(current_stage_index=2, overall_progress=100)
    session = MagicMock()
    session.begin.return_value = AsyncMock()
    session.execute = AsyncMock(side_effect=[result(project), None, None, None, None, result(stages), result(board)])
    assert await SlideResetService.reset(session, "p", 1)
    assert project.slides_data == [] and project.slides_html is None
    assert project.outline == {"slides": [1, 2]}
    assert project.confirmed_requirements == {"topic": "demo"}
    assert project.project_metadata == {"selected_global_suite_id": 94}
    assert stages[0].status == stages[1].status == "completed"
    assert stages[2].status == "pending" and stages[2].result is None
    assert board.overall_progress == pytest.approx(200 / 3)


@pytest.mark.asyncio
async def test_reset_does_not_delete_for_missing_or_unowned_project():
    session = MagicMock()
    session.begin.return_value = AsyncMock()
    session.execute = AsyncMock(return_value=result(None))
    assert not await SlideResetService.reset(session, "p", 2)
    assert session.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("busy", [True, False])
async def test_return_route_waits_for_generator_lock_before_reset(monkeypatch, busy):
    path = Path(__file__).parents[1] / "src/landppt/web/route_modules/slide_routes.py"
    node = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "return_to_outline")
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    authoring = SimpleNamespace(_try_acquire_slides_generation_lock=AsyncMock(return_value={"acquired": not busy}),
                                _release_slides_generation_lock=AsyncMock())
    service = SimpleNamespace(request_cancel_slides_generation=AsyncMock(), slide_authoring=authoring)
    reset = AsyncMock(return_value=True)
    monkeypatch.setattr(SlideResetService, "reset", reset)
    manager = SimpleNamespace(update_stage_status=AsyncMock())
    monkeypatch.setitem(sys.modules, "landppt.services.db_project_manager", SimpleNamespace(DatabaseProjectManager=lambda: manager))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=object())
    context.__aexit__ = AsyncMock(return_value=False)
    ns = {"__name__": "landppt.web.route_modules.slide_routes", "HTTPException": HTTPException,
          "JSONResponse": JSONResponse, "AsyncSessionLocal": lambda: context,
          "ppt_service": SimpleNamespace(project_manager=SimpleNamespace(get_project=AsyncMock(return_value=object()))),
          "get_ppt_service_for_user": lambda user_id: service}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    response = await ns["return_to_outline"]("p", SimpleNamespace(id=1))
    if busy:
        assert response.status_code == 202
        reset.assert_not_awaited()
        authoring._release_slides_generation_lock.assert_not_awaited()
    else:
        assert response["redirect_url"] == "/projects/p/todo?outline_mode=true"
        reset.assert_awaited_once()
        authoring._release_slides_generation_lock.assert_awaited_once()
