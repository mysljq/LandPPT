"""Exercise multipart routes without initializing live AI/database services."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.testclient import TestClient

from landppt.api.models import PPTGenerationRequest
from landppt.services.outline.document_structure_service import (
    DOCUMENT_STRUCTURE_MODE, MAX_DOCUMENT_UPLOAD_BYTES, read_document_source, generate_document_outline, get_document_outline,
)

from test_document_structure_outline import sample_outline as build_document_outline

ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


@pytest.fixture
def creation_client():
    manager = SimpleNamespace(
        create_project=AsyncMock(return_value=SimpleNamespace(project_id="new-project")),
        update_project_status=AsyncMock(return_value=True),
        update_todo_board_with_confirmed_requirements=AsyncMock(return_value=True),
        save_project_outline=AsyncMock(return_value=True),
        update_stage_status=AsyncMock(return_value=True),
    )
    namespace = dict(globals())
    namespace.update(
        User=SimpleNamespace,
        get_current_user_required=lambda: SimpleNamespace(id=7),
        ppt_service=SimpleNamespace(project_manager=manager),
        run_blocking_io=asyncio.to_thread,
        get_ppt_service_for_user=lambda user_id: SimpleNamespace(
            get_role_provider_async=AsyncMock(return_value=(None, {"provider": "test"})),
            _text_completion_for_role=AsyncMock(return_value=SimpleNamespace(content=json.dumps(build_document_outline())))),
        check_credits_for_operation=AsyncMock(return_value=(True, 3, 100)),
        consume_credits_for_operation=AsyncMock(return_value=(True, "")),
        templates=SimpleNamespace(TemplateResponse=lambda name, context, status_code=200: HTMLResponse(context["error"], status_code)),
    )
    endpoint = load_function("src/landppt/web/route_modules/project_lifecycle_routes.py", "web_create_project", namespace)
    app = FastAPI()
    app.post("/projects/create")(endpoint)
    with TestClient(app) as client:
        yield client, manager


def test_document_creation_upload_confirms_requirements_and_saves_outline(creation_client):
    client, manager = creation_client
    response = client.post("/projects/create", data={
        "scenario": "general", "creation_mode": DOCUMENT_STRUCTURE_MODE, "network_mode": "true",
    }, files={"source_document": ("report.md", "# 报告\n## 章节\n内容原文".encode(), "text/markdown")}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/projects/new-project/todo"
    request = manager.create_project.call_args.args[0]
    assert request.topic == "报告"
    assert request.user_id == 7
    assert request.network_mode is False
    confirmed = manager.update_todo_board_with_confirmed_requirements.call_args.args[1]
    assert confirmed["creation_mode"] == DOCUMENT_STRUCTURE_MODE
    assert confirmed["document_source_outline"]["slides"][1]["content_points"] == ["内容原文"]
    assert manager.update_todo_board_with_confirmed_requirements.call_args.kwargs == {"user_id": 7}
    manager.save_project_outline.assert_awaited_once()
    assert manager.update_stage_status.call_args.args[1:3] == ("outline_generation", "completed")


@pytest.mark.parametrize("filename, content", [(None, None), ("bad.doc", b"bad"), ("empty.md", b"")])
def test_invalid_document_does_not_create_project(creation_client, filename, content):
    client, manager = creation_client
    files = {"source_document": (filename, content)} if filename else None
    response = client.post("/projects/create", data={"scenario": "general", "creation_mode": DOCUMENT_STRUCTURE_MODE}, files=files)
    assert response.status_code == 400
    manager.create_project.assert_not_awaited()


def test_standard_creation_still_uses_existing_workflow(creation_client):
    client, manager = creation_client
    response = client.post("/projects/create", data={"scenario": "business", "topic": "原模式"}, follow_redirects=False)
    assert response.status_code == 302
    manager.create_project.assert_awaited_once()
    manager.save_project_outline.assert_not_awaited()
    manager.update_todo_board_with_confirmed_requirements.assert_not_awaited()


@pytest.mark.asyncio
async def test_regeneration_restores_source_before_any_ai_or_credit_calls():
    source = build_document_outline(b"# Report\n## A\nOriginal", "input.md")
    project = SimpleNamespace(outline={}, confirmed_requirements={
        "creation_mode": DOCUMENT_STRUCTURE_MODE, "document_source_outline": source,
    })
    service = SimpleNamespace(_update_outline_generation_stage=AsyncMock())
    namespace = dict(globals())
    namespace.update(
        User=SimpleNamespace,
        get_current_user_required=lambda: SimpleNamespace(id=7),
        ppt_service=SimpleNamespace(project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project))),
        get_ppt_service_for_user=lambda user_id: service,
    )
    endpoint = load_function("src/landppt/web/route_modules/outline_generation_routes.py", "generate_outline", namespace)
    result = await endpoint("project", user=SimpleNamespace(id=7))
    assert result["status"] == "success"
    assert json.loads(result["outline_content"]) == source
    service._update_outline_generation_stage.assert_awaited_once_with("project", source)


@pytest.mark.asyncio
async def test_document_stream_restores_source_without_model_or_research():
    path = "src/landppt/services/outline/project_outline_streaming_service.py"
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate_outline_streaming")
    namespace = {"__package__": "landppt.services.outline"}
    exec(compile(ast.Module(body=[method], type_ignores=[]), path, "exec"), namespace)
    source = build_document_outline(b"# Report\nText", "input.md")
    project = SimpleNamespace(outline=None, confirmed_requirements={
        "creation_mode": DOCUMENT_STRUCTURE_MODE, "document_source_outline": source,
    })
    service = SimpleNamespace(
        project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project)),
        _update_outline_generation_stage=AsyncMock(),
    )
    events = [json.loads(chunk.removeprefix("data: ")) async for chunk in namespace[method.name](service, "project", force_regenerate=True)]
    assert events[-1] == {"done": True, "llm_call_count": 0}
    assert json.loads("".join(event.get("content", "") for event in events)) == source
