import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from landppt.services.slide.parallel_page_service import ParallelPageService


def load_route(project):
    path = Path(__file__).parents[1] / "src/landppt/web/route_modules/outline_generation_routes.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    method = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "preview_parallel_page_plan")
    method.decorator_list = []
    method.args.defaults = []
    for arg in method.args.args:
        arg.annotation = None
    manager = SimpleNamespace(get_project=AsyncMock(return_value=project))
    namespace = {"__name__": "landppt.web.route_modules.outline_generation_routes",
                 "HTTPException": HTTPException, "ppt_service": SimpleNamespace(project_manager=manager),
                 "get_ppt_service_for_user": lambda user_id: SimpleNamespace()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[method.name], manager


@pytest.mark.asyncio
async def test_plan_preview_checks_ownership_and_unsaved_edits(monkeypatch):
    prepare = AsyncMock()
    monkeypatch.setattr(ParallelPageService, "prepare", prepare)
    route, manager = load_route(None)
    user = SimpleNamespace(id=17)
    request = SimpleNamespace(json=AsyncMock(return_value={"slides": [{"title": "changed"}]}))
    with pytest.raises(HTTPException) as error:
        await route("p", request, user)
    assert error.value.status_code == 404
    manager.get_project.assert_awaited_with("p", user_id=17)
    route, _ = load_route(SimpleNamespace(outline={"slides": [{"title": "saved"}]}))
    with pytest.raises(HTTPException) as error:
        await route("p", request, user)
    assert error.value.status_code == 409
    prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_returns_persisted_plan(monkeypatch):
    plan = {"groups": [{"pages": [1, 2], "reference_page": 1}]}
    outline = {"slides": [{"title": "A"}, {"title": "B"}], "parallel_page_plan": plan}
    monkeypatch.setattr(ParallelPageService, "prepare", AsyncMock())
    route, _ = load_route(SimpleNamespace(outline=outline))
    request = SimpleNamespace(json=AsyncMock(return_value={"slides": outline["slides"]}))
    assert await route("p", request, SimpleNamespace(id=17)) == {"plan": plan}
