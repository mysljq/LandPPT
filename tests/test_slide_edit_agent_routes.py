from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from landppt.services.slide.slide_edit_agent_service import (
    SlideEditAgentApplyRequest,
    SlideEditAgentRequest,
    compute_slide_html_hash,
)
from landppt.web.route_modules import slide_edit_agent_routes as routes


class _FakeProjectManager:
    def __init__(self, project):
        self.project = project

    async def get_project(self, project_id, user_id=None):
        return self.project


class _FakePPTService:
    def __init__(self, project=None, providers=None):
        self.project_manager = _FakeProjectManager(project)
        self.providers = providers or {}
        self.roles = []

    async def get_role_provider_async(self, role):
        self.roles.append(role)
        return None, {"provider": self.providers.get(role, "landppt")}


async def _collect_stream_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_apply_agent_proposal_rejects_base_hash_mismatch(monkeypatch):
    project = SimpleNamespace(
        slides_data=[
            {
                "title": "One",
                "html_content": "<div>Current</div>",
                "is_user_edited": False,
            }
        ]
    )
    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash("<div>Old</div>"),
        htmlContent="<div>New</div>",
        slideData={"title": "One"},
    )

    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(
            request, user=SimpleNamespace(id=10)
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_agent_proposal_saves_only_target_slide(monkeypatch):
    current_html = '<div style="width:1280px;height:720px"><h1>Current</h1></div>'
    project = SimpleNamespace(
        slides_data=[
            {"title": "One", "html_content": current_html, "is_user_edited": False},
            {
                "title": "Two",
                "html_content": "<div>Second</div>",
                "is_user_edited": False,
            },
        ]
    )
    saved = {}

    class _FakeDBManager:
        async def save_single_slide(self, project_id, slide_index, slide_data):
            saved["project_id"] = project_id
            saved["slide_index"] = slide_index
            saved["slide_data"] = slide_data
            return True

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )
    monkeypatch.setattr(routes, "DatabaseProjectManager", lambda: _FakeDBManager())

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent='<div style="width:1280px;height:720px"><h1>New</h1></div>',
        slideData={"title": "One"},
    )

    result = await routes.apply_slide_edit_agent_proposal(
        request, user=SimpleNamespace(id=10)
    )

    assert result["success"] is True
    assert saved["project_id"] == "proj"
    assert saved["slide_index"] == 0
    assert saved["slide_data"]["title"] == "One"
    assert "New" in saved["slide_data"]["html_content"]
    assert saved["slide_data"]["is_user_edited"] is True


@pytest.mark.asyncio
async def test_apply_agent_proposal_strips_agent_ids_before_save(monkeypatch):
    current_html = '<div style="width:1280px;height:720px"><h1>Current</h1></div>'
    project = SimpleNamespace(
        slides_data=[
            {"title": "One", "html_content": current_html, "is_user_edited": False}
        ]
    )
    saved = {}

    class _FakeDBManager:
        async def save_single_slide(self, project_id, slide_index, slide_data):
            saved["slide_data"] = slide_data
            return True

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )
    monkeypatch.setattr(routes, "DatabaseProjectManager", lambda: _FakeDBManager())

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent=(
            '<div data-agent-id="a1" data-quick-ai-id="q1" '
            'style="width:1280px;height:720px">'
            '<h1 data-quick-ai-id="q2">New</h1></div>'
        ),
        slideData={"title": "One"},
    )

    result = await routes.apply_slide_edit_agent_proposal(
        request, user=SimpleNamespace(id=10)
    )

    saved_html = saved["slide_data"]["html_content"]
    assert result["htmlContent"] == saved_html
    assert "data-agent-id" not in saved_html
    assert "data-quick-ai-id" not in saved_html
    assert "New" in saved_html


@pytest.mark.parametrize(
    ("html_content", "expected_error"),
    [
        (
            '<div style="width:1280px;height:720px">'
            "<script>alert(1)</script><h1>New</h1></div>",
            "script tags are not allowed",
        ),
        (
            '<div style="width:1280px;height:720px">'
            '<h1 onclick="bad()">New</h1></div>',
            "inline event handlers are not allowed",
        ),
        (
            '<div style="width:1280px;height:720px">'
            '<a href="java&#115;cript:bad()">New</a></div>',
            "javascript urls are not allowed",
        ),
        ("", "html content is required"),
        (
            '<div style="width:1280px;height:720px"><section><h1>New</section></div>',
            "html is malformed",
        ),
    ],
)
@pytest.mark.asyncio
async def test_apply_agent_proposal_rejects_invalid_html_before_save(
    monkeypatch,
    html_content,
    expected_error,
):
    current_html = '<div style="width:1280px;height:720px"><h1>Current</h1></div>'
    project = SimpleNamespace(
        slides_data=[
            {"title": "One", "html_content": current_html, "is_user_edited": False}
        ]
    )

    class _FakeDBManager:
        async def save_single_slide(self, project_id, slide_index, slide_data):
            raise AssertionError("invalid HTML should not be saved")

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )
    monkeypatch.setattr(routes, "DatabaseProjectManager", lambda: _FakeDBManager())

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent=html_content,
        slideData={"title": "One"},
    )

    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(
            request, user=SimpleNamespace(id=10)
        )

    assert exc.value.status_code == 400
    assert expected_error in exc.value.detail["errors"]


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_charges_once_after_draft(monkeypatch):
    charges = []

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback):
            await event_callback({"type": "agent_start"})
            await event_callback(
                {"type": "draft_ready", "proposal": {"proposalId": "p1"}}
            )
            await event_callback({"type": "final", "proposalId": "p1"})
            await event_callback({"type": "needs_confirmation", "proposalId": "p1"})
            return SimpleNamespace(proposal_id="p1")

    async def check_credits(*args, **kwargs):
        return True, 1, 10

    async def consume_credits(*args, **kwargs):
        charges.append({"args": args, "kwargs": kwargs})
        return True, "ok"

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService()
    )
    monkeypatch.setattr(routes, "check_credits_for_operation", check_credits)
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume_credits)
    monkeypatch.setattr(routes, "SlideEditAgentService", _FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        SlideEditAgentRequest(
            projectId="proj",
            slideIndex=1,
            slideTitle="One",
            slideContent="<div>Current</div>",
            userRequest="Shorten the title",
        ),
        user=SimpleNamespace(id=10),
    )

    body = await _collect_stream_body(response)

    assert '"type": "draft_ready"' in body
    assert len(charges) == 1
    assert charges[0]["args"][:3] == (10, "ai_edit", 1)
    assert charges[0]["kwargs"]["reference_id"] == "proj"


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_charges_before_billable_chunk(monkeypatch):
    charges = []

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback):
            await event_callback(
                {"type": "draft_ready", "proposal": {"proposalId": "p1"}}
            )
            return SimpleNamespace(proposal_id="p1")

    async def check_credits(*args, **kwargs):
        return True, 1, 10

    async def consume_credits(*args, **kwargs):
        charges.append({"args": args, "kwargs": kwargs})
        return True, "ok"

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService()
    )
    monkeypatch.setattr(routes, "check_credits_for_operation", check_credits)
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume_credits)
    monkeypatch.setattr(routes, "SlideEditAgentService", _FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        SlideEditAgentRequest(
            projectId="proj",
            slideIndex=1,
            slideTitle="One",
            slideContent="<div>Current</div>",
            userRequest="Shorten the title",
        ),
        user=SimpleNamespace(id=10),
    )

    first_chunk = await anext(response.body_iterator)
    if isinstance(first_chunk, bytes):
        first_chunk = first_chunk.decode("utf-8")

    assert '"type": "draft_ready"' in first_chunk
    assert len(charges) == 1

    await _collect_stream_body(response)


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_uses_editor_provider_without_vision_inputs(
    monkeypatch,
):
    service = _FakePPTService(
        providers={
            "editor": "editor-provider",
            "vision_analysis": "vision-provider",
        }
    )
    check_provider_names = []
    charge_provider_names = []

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback):
            await event_callback(
                {"type": "draft_ready", "proposal": {"proposalId": "p1"}}
            )
            return SimpleNamespace(proposal_id="p1")

    async def check_credits(*args, **kwargs):
        check_provider_names.append(kwargs.get("provider_name"))
        return True, 1, 10

    async def consume_credits(*args, **kwargs):
        charge_provider_names.append(kwargs.get("provider_name"))
        return True, "ok"

    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda user_id: service)
    monkeypatch.setattr(routes, "check_credits_for_operation", check_credits)
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume_credits)
    monkeypatch.setattr(routes, "SlideEditAgentService", _FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        SlideEditAgentRequest(
            projectId="proj",
            slideIndex=1,
            slideContent="<div>Current</div>",
            userRequest="Shorten the title",
            visionEnabled=True,
        ),
        user=SimpleNamespace(id=10),
    )

    body = await _collect_stream_body(response)

    assert '"type": "draft_ready"' in body
    assert service.roles == ["editor"]
    assert check_provider_names == ["editor-provider"]
    assert charge_provider_names == ["editor-provider"]


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_does_not_charge_without_draft(monkeypatch):
    charges = []

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback):
            await event_callback({"type": "agent_start"})
            raise RuntimeError("model unavailable")

    async def check_credits(*args, **kwargs):
        return True, 1, 10

    async def consume_credits(*args, **kwargs):
        charges.append({"args": args, "kwargs": kwargs})
        return True, "ok"

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService()
    )
    monkeypatch.setattr(routes, "check_credits_for_operation", check_credits)
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume_credits)
    monkeypatch.setattr(routes, "SlideEditAgentService", _FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        SlideEditAgentRequest(
            projectId="proj",
            slideIndex=1,
            slideContent="<div>Current</div>",
            userRequest="Shorten the title",
        ),
        user=SimpleNamespace(id=10),
    )

    body = await _collect_stream_body(response)

    assert '"type": "error"' in body
    assert "model unavailable" in body
    assert charges == []


@pytest.mark.asyncio
async def test_cancel_slide_edit_agent_returns_success():
    result = await routes.cancel_slide_edit_agent(user=SimpleNamespace(id=10))

    assert result == {"success": True}
