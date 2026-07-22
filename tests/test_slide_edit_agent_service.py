import json
from types import SimpleNamespace

import pytest

from landppt.ai.base import ImageContent, TextContent
from landppt.services.slide.slide_edit_agent_service import (
    SlideEditAgentContext,
    SlideEditAgentRequest,
    SlideEditAgentService,
    SlideEditToolRunner,
    compute_slide_html_hash,
    coerce_agent_max_iterations,
    parse_agent_action,
    sanitize_slide_html,
    strip_agent_ids,
    validate_slide_html,
)


def test_parse_agent_action_supports_json_code_fence():
    action = parse_agent_action(
        "```json\n"
        + json.dumps(
            {
                "thought": "Inspect the slide before editing.",
                "action": "inspect_slide_html",
                "action_input": {"slide_index": 1},
            }
        )
        + "\n```"
    )

    assert action.thought == "Inspect the slide before editing."
    assert action.action == "inspect_slide_html"
    assert action.action_input == {"slide_index": 1}


def test_parse_agent_action_falls_back_to_final_for_unparseable_text():
    action = parse_agent_action("I cannot parse this as JSON.")

    assert action.action == "final"
    assert action.action_input["summary"] == "I cannot parse this as JSON."


def test_coerce_agent_max_iterations_defaults_and_clamps():
    assert coerce_agent_max_iterations(None) == 6
    assert coerce_agent_max_iterations(1) == 2
    assert coerce_agent_max_iterations(8) == 8
    assert coerce_agent_max_iterations(99) == 99
    assert coerce_agent_max_iterations(999) == 100
    assert coerce_agent_max_iterations("bad") == 6


def test_compute_slide_html_hash_is_stable_for_equivalent_text():
    assert compute_slide_html_hash(" <div>A</div>\n") == compute_slide_html_hash("<div>A</div>")
    assert compute_slide_html_hash("<div>A</div>") != compute_slide_html_hash("<div>B</div>")


def test_sanitize_slide_html_removes_scripts_event_handlers_and_agent_ids():
    html = (
        '<div data-agent-id="a1" onclick="bad()" style="width:1280px;height:720px">'
        '<a href="javascript:bad()">x</a><script>alert(1)</script>'
        "</div>"
    )

    sanitized = sanitize_slide_html(html)

    assert "<script" not in sanitized.lower()
    assert "onclick" not in sanitized.lower()
    assert "javascript:" not in sanitized.lower()
    assert "data-agent-id" not in strip_agent_ids(sanitized)


def test_validate_slide_html_reports_unsafe_original_html():
    result = validate_slide_html('<div><script>alert(1)</script><p onclick="x()">Hi</p></div>')

    assert result.valid is False
    assert "script tags are not allowed" in result.errors
    assert "inline event handlers are not allowed" in result.errors
    assert "<script" not in result.sanitized_html.lower()


def test_validate_slide_html_rejects_encoded_javascript_urls():
    result = validate_slide_html('<div><a href="java&#115;cript:alert(1)">x</a></div>')

    assert result.valid is False
    assert "javascript urls are not allowed" in result.errors
    assert "javascript:" not in result.sanitized_html.lower()
    assert "href=" not in result.sanitized_html.lower()


@pytest.mark.parametrize(
    "html",
    [
        '<div><a href="java&#10;script:alert(1)">x</a></div>',
        '<div><a href="jav&#x09;ascript:alert(1)">x</a></div>',
    ],
)
def test_validate_slide_html_rejects_encoded_control_javascript_urls(html):
    result = validate_slide_html(html)

    assert result.valid is False
    assert "javascript urls are not allowed" in result.errors
    assert "href=" not in result.sanitized_html.lower()


def test_validate_slide_html_rejects_srcdoc_attributes():
    result = validate_slide_html(
        '<div><iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;"></iframe></div>'
    )

    assert result.valid is False
    assert "srcdoc attributes are not allowed" in result.errors
    assert "srcdoc" not in result.sanitized_html.lower()
    assert "<script" not in result.sanitized_html.lower()


def test_validate_slide_html_accepts_clean_slide_html():
    result = validate_slide_html('<div style="width:1280px;height:720px"><h1>Hello</h1></div>')

    assert result.valid is True
    assert result.errors == []
    assert "Hello" in result.sanitized_html


def _tool_request(**overrides):
    data = {
        "projectId": "p1",
        "slideIndex": 1,
        "userRequest": "Make the title shorter",
        "slideTitle": "Original",
        "slideContent": '<div style="width:1280px;height:720px"><h1>Long Original Title</h1><p>Body</p></div>',
        "projectInfo": {"title": "Project", "topic": "Topic", "scenario": "Pitch"},
        "slideOutline": {"title": "Original", "content_points": ["Body"]},
    }
    data.update(overrides)
    return SlideEditAgentRequest(**data)


def _tool_context(**overrides):
    request = _tool_request(**overrides)
    return SlideEditAgentContext.from_request(request)


@pytest.mark.asyncio
async def test_tool_runner_inspects_slide_html():
    runner = SlideEditToolRunner(_tool_context())

    result = await runner.execute_tool("inspect_slide_html", {"slide_index": 1})

    assert result["success"] is True
    assert result["tool"] == "inspect_slide_html"
    assert result["headings"][0]["text"] == "Long Original Title"
    assert result["text_blocks"]


@pytest.mark.asyncio
async def test_compact_observation_keeps_tool_results_needed_by_model():
    service = SlideEditAgentService()
    runner = SlideEditToolRunner(_tool_context())

    inspect_result = await runner.execute_tool("inspect_slide_html", {})
    inspect_compact = service._compact_observation(inspect_result)

    assert inspect_compact["headings"][0]["text"] == "Long Original Title"

    select_result = await runner.execute_tool("select_elements", {"selector": "h1"})
    select_compact = service._compact_observation(select_result)

    assert select_compact["matches"][0]["agent_id"].startswith("agent-el-")

    slide_result = await runner.execute_tool("get_slide", {})
    slide_compact = service._compact_observation(slide_result)

    assert "html_content" in slide_compact["slide"]


@pytest.mark.asyncio
async def test_tool_runner_replace_slide_html_updates_draft_not_base():
    context = _tool_context()
    runner = SlideEditToolRunner(context)
    original_hash = context.base_hash

    result = await runner.execute_tool(
        "replace_slide_html",
        {"html": '<div style="width:1280px;height:720px"><h1>New</h1></div>'},
    )

    assert result["success"] is True
    assert "New" in runner.current_html
    assert context.base_hash == original_hash
    assert "Long Original Title" in context.base_html


@pytest.mark.asyncio
async def test_tool_runner_replace_slide_html_rejects_invalid_without_mutating_draft():
    runner = SlideEditToolRunner(_tool_context())
    original_html = runner.current_html

    result = await runner.execute_tool(
        "replace_slide_html",
        {"html": '<div style="width:1280px;height:720px"><script>alert(1)</script><h1>Bad</h1></div>'},
    )

    assert result["success"] is False
    assert result["tool"] == "replace_slide_html"
    assert "script tags are not allowed" in result["errors"]
    assert runner.current_html == original_html


@pytest.mark.asyncio
async def test_tool_runner_updates_text_by_selector():
    runner = SlideEditToolRunner(_tool_context())

    result = await runner.execute_tool("update_text", {"selector": "h1", "text": "Short Title"})

    assert result["success"] is True
    assert "Short Title" in runner.current_html
    assert "Long Original Title" not in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_selector_takes_priority_over_selected_element_context():
    runner = SlideEditToolRunner(
        _tool_context(
            mode="element",
            slideContent=(
                '<div style="width:1280px;height:720px">'
                '<h1 data-quick-ai-id="el1">Long Original Title</h1><p>Body</p>'
                "</div>"
            ),
            selectedElementId="el1",
        )
    )

    result = await runner.execute_tool("update_text", {"selector": "p", "text": "Updated Body"})

    assert result["success"] is True
    assert "Long Original Title" in runner.current_html
    assert "Updated Body" in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_update_style_uses_css_whitelist():
    runner = SlideEditToolRunner(_tool_context())

    result = await runner.execute_tool(
        "update_style",
        {
            "selector": "h1",
            "styles": {
                "color": "#123456",
                "font-size": "48px",
                "position": "fixed",
                "behavior": "url(bad)",
            },
        },
    )

    assert result["success"] is True
    assert "color: #123456" in runner.current_html
    assert "font-size: 48px" in runner.current_html
    assert "position: fixed" not in runner.current_html
    assert "behavior" not in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_replaces_element_and_preserves_quick_ai_id_in_draft():
    runner = SlideEditToolRunner(
        _tool_context(
            mode="element",
            slideContent=(
                '<div style="width:1280px;height:720px">'
                '<h1 data-quick-ai-id="el1">Long Original Title</h1><p>Body</p>'
                "</div>"
            ),
            selectedElementHtml='<h1 data-quick-ai-id="el1">Long Original Title</h1>',
            selectedElementId="el1",
        )
    )

    result = await runner.execute_tool(
        "replace_element_html",
        {"element_id": "el1", "html": '<h1 data-quick-ai-id="el1">Short Title</h1>'},
    )

    assert result["success"] is True
    assert 'data-quick-ai-id="el1"' in runner.current_html
    assert "Short Title" in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_replace_element_by_selector_preserves_target_id_only():
    runner = SlideEditToolRunner(
        _tool_context(
            mode="element",
            slideContent=(
                '<div style="width:1280px;height:720px">'
                '<h1 data-quick-ai-id="el1">Long Original Title</h1>'
                '<p data-quick-ai-id="body1">Body</p>'
                "</div>"
            ),
            selectedElementId="el1",
        )
    )

    result = await runner.execute_tool(
        "replace_element_html",
        {"selector": "p", "html": "<p>Updated Body</p>"},
    )

    assert result["success"] is True
    assert runner.current_html.count('data-quick-ai-id="el1"') == 1
    assert 'data-quick-ai-id="body1"' in runner.current_html
    assert "Updated Body" in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_replace_element_missing_id_fails_without_mutating_draft():
    runner = SlideEditToolRunner(
        _tool_context(
            mode="element",
            selectedElementId="missing",
        )
    )
    original_html = runner.current_html

    result = await runner.execute_tool(
        "replace_element_html",
        {"element_id": "missing", "html": "<h1>Short Title</h1>"},
    )

    assert result["success"] is False
    assert result["tool"] == "replace_element_html"
    assert "not found" in result["error"]
    assert runner.current_html == original_html


@pytest.mark.asyncio
async def test_tool_runner_update_text_missing_target_fails_without_mutating_draft():
    runner = SlideEditToolRunner(_tool_context())
    original_html = runner.current_html

    result = await runner.execute_tool("update_text", {"text": "Short Title"})

    assert result["success"] is False
    assert result["tool"] == "update_text"
    assert "requires" in result["error"]
    assert runner.current_html == original_html


@pytest.mark.asyncio
async def test_tool_runner_delete_element_missing_target_fails_without_mutating_draft():
    runner = SlideEditToolRunner(_tool_context())
    original_html = runner.current_html

    result = await runner.execute_tool("delete_element", {})

    assert result["success"] is False
    assert result["tool"] == "delete_element"
    assert "requires" in result["error"]
    assert runner.current_html == original_html


@pytest.mark.asyncio
async def test_tool_runner_replace_element_rejects_unsafe_fragment_without_mutating_draft():
    runner = SlideEditToolRunner(
        _tool_context(
            mode="element",
            slideContent=(
                '<div style="width:1280px;height:720px">'
                '<h1 data-quick-ai-id="el1">Long Original Title</h1><p>Body</p>'
                "</div>"
            ),
            selectedElementId="el1",
        )
    )
    original_html = runner.current_html

    result = await runner.execute_tool(
        "replace_element_html",
        {"element_id": "el1", "html": '<h1 onclick="bad()">Bad</h1>'},
    )

    assert result["success"] is False
    assert "inline event handlers are not allowed" in result["errors"]
    assert runner.current_html == original_html


@pytest.mark.asyncio
async def test_tool_runner_insert_element_rejects_unsafe_fragment_without_mutating_draft():
    runner = SlideEditToolRunner(_tool_context())
    original_html = runner.current_html

    result = await runner.execute_tool(
        "insert_element",
        {"parent_selector": "div", "html": "<h2><script>alert(1)</script>Bad</h2>"},
    )

    assert result["success"] is False
    assert "script tags are not allowed" in result["errors"]
    assert runner.current_html == original_html


@pytest.mark.asyncio
async def test_tool_runner_insert_element_missing_target_fails_without_mutating_full_html_body():
    html = (
        "<!doctype html><html><head><title>Slide</title></head>"
        '<body><section id="slide"><p>Body</p></section></body></html>'
    )
    runner = SlideEditToolRunner(_tool_context(slideContent=html))
    original_html = runner.current_html

    result = await runner.execute_tool("insert_element", {"html": "<p>New</p>"})

    assert result["success"] is False
    assert result["tool"] == "insert_element"
    assert "requires parent_selector or element_id" in result["error"]
    assert runner.current_html == original_html
    assert "New" not in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_insert_element_succeeds_with_explicit_parent_selector():
    runner = SlideEditToolRunner(_tool_context())

    result = await runner.execute_tool(
        "insert_element",
        {"parent_selector": "div", "html": "<h2>New Section</h2>"},
    )

    assert result["success"] is True
    assert result["tool"] == "insert_element"
    assert "<h2>New Section</h2>" in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_invalid_selector_returns_structured_error():
    runner = SlideEditToolRunner(_tool_context())
    original_html = runner.current_html

    result = await runner.execute_tool(
        "update_text",
        {"selector": "[", "text": "Short Title"},
    )

    assert result["success"] is False
    assert result["tool"] == "update_text"
    assert "invalid selector" in result["error"]
    assert runner.current_html == original_html


def test_tool_runner_build_proposal_strips_agent_ids():
    runner = SlideEditToolRunner(
        _tool_context(
            slideContent='<div style="width:1280px;height:720px"><h1 data-agent-id="a1">Title</h1></div>'
        )
    )

    proposal = runner.build_proposal("Edited title")

    assert proposal.proposal_id
    assert proposal.summary == "Edited title"
    assert "data-agent-id" not in proposal.html_content
    assert proposal.validation.valid is True


def _agent_prompt_context(service: SlideEditAgentService, request: SlideEditAgentRequest):
    runner = SlideEditToolRunner(SlideEditAgentContext.from_request(request))
    prompt = service._build_prompt(request, runner, scratchpad=[], max_iterations=6)
    return json.loads(prompt.split("\n\n", 1)[1])


def test_slide_edit_agent_prompt_includes_sanitized_conversation_history():
    service = SlideEditAgentService()
    request = _tool_request(
        chatHistory=[
            {"role": "system", "content": "Do not include this."},
            {"role": "user", "content": "Make the heading shorter first."},
            {"role": "assistant", "content": "I shortened the heading."},
            {"role": "tool", "content": "Internal tool output."},
            {"role": "assistant", "content": "   "},
        ]
    )

    context = _agent_prompt_context(service, request)

    assert context["conversation_history"] == [
        {"role": "user", "content": "Make the heading shorter first."},
        {"role": "assistant", "content": "I shortened the heading."},
    ]
    assert context["user_request"] == "Make the title shorter"


def test_slide_edit_agent_prompt_limits_conversation_history_to_recent_messages():
    service = SlideEditAgentService()
    history = [
        {"role": "user", "content": f"message {index}"}
        for index in range(14)
    ]
    history.append({"role": "assistant", "content": "x" * 1500})
    request = _tool_request(chatHistory=history)

    context = _agent_prompt_context(service, request)
    conversation_history = context["conversation_history"]

    assert len(conversation_history) == 10
    assert conversation_history[0] == {"role": "user", "content": "message 5"}
    assert conversation_history[-2] == {"role": "user", "content": "message 13"}
    assert conversation_history[-1]["role"] == "assistant"
    assert conversation_history[-1]["content"].endswith("...")
    assert len(conversation_history[-1]["content"]) <= 1200


def test_slide_edit_agent_prompt_limits_scratchpad_entries():
    service = SlideEditAgentService()
    request = _tool_request()
    runner = SlideEditToolRunner(SlideEditAgentContext.from_request(request))
    scratchpad = [
        {"iteration": index, "observation": {"summary": f"result {index}"}}
        for index in range(25)
    ]

    prompt = service._build_prompt(
        request, runner, scratchpad=scratchpad, max_iterations=100
    )
    context = json.loads(prompt.split("\n\n", 1)[1])

    assert context["max_iterations"] == 100
    assert len(context["scratchpad"]) == 21
    assert context["scratchpad"][0]["note"].startswith("5 earlier scratchpad")
    assert context["scratchpad"][1]["iteration"] == 5


class _FakePPTService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def _chat_completion_for_role(self, role, messages, **kwargs):
        self.calls.append((role, messages, kwargs))
        return SimpleNamespace(content=self.responses.pop(0))


class _FakeNativeToolPPTService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def _chat_completion_for_role(self, role, messages, **kwargs):
        self.calls.append((role, messages, kwargs))
        return self.responses.pop(0)


class _NoNativeToolPPTService(_FakePPTService):
    async def _chat_completion_for_role(self, role, messages, **kwargs):
        if kwargs.get("tools"):
            raise RuntimeError("unsupported parameter: tools")
        return await super()._chat_completion_for_role(role, messages, **kwargs)


class _FailingPPTService:
    async def _chat_completion_for_role(self, role, messages, **kwargs):
        raise RuntimeError("model unavailable")


@pytest.mark.asyncio
async def test_slide_edit_agent_uses_native_tool_calls_before_text_fallback():
    service = SlideEditAgentService()
    fake_ppt = _FakeNativeToolPPTService(
        [
            SimpleNamespace(
                content="Inspecting.",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "update_text",
                            "arguments": json.dumps({"selector": "h1", "text": "Short Title"}),
                        },
                    }
                ],
            ),
            SimpleNamespace(content="Shortened the title.", tool_calls=[]),
        ]
    )

    proposal = await service.run_agent(_tool_request(), fake_ppt)

    assert proposal.summary == "Shortened the title."
    assert "Short Title" in proposal.html_content
    first_role, _first_messages, first_kwargs = fake_ppt.calls[0]
    assert first_role == "editor"
    assert first_kwargs["tool_choice"] == "auto"
    assert first_kwargs["parallel_tool_calls"] is False
    assert first_kwargs["tools"][0]["type"] == "function"
    assert first_kwargs["tools"][0]["function"]["parameters"]["type"] == "object"
    second_messages = fake_ppt.calls[1][1]
    assert second_messages[-1].role.value == "tool"
    assert second_messages[-1].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_slide_edit_agent_native_text_action_keeps_observation_in_history():
    service = SlideEditAgentService()
    fake_ppt = _FakeNativeToolPPTService(
        [
            SimpleNamespace(
                content=json.dumps(
                    {
                        "thought": "Inspect before editing.",
                        "action": "inspect_slide_html",
                        "action_input": {},
                    }
                ),
                tool_calls=[],
            ),
            SimpleNamespace(
                content=json.dumps(
                    {
                        "thought": "Use the inspected title.",
                        "action": "final",
                        "action_input": {"summary": "Inspected the slide."},
                    }
                ),
                tool_calls=[],
            ),
        ]
    )

    proposal = await service.run_agent(_tool_request(), fake_ppt)

    assert proposal.summary == "Inspected the slide."
    second_messages = fake_ppt.calls[1][1]
    assert second_messages[-1].role.value == "user"
    assert "Tool result:" in second_messages[-1].content
    assert "Long Original Title" in second_messages[-1].content


@pytest.mark.asyncio
async def test_slide_edit_agent_runs_tools_and_returns_proposal():
    service = SlideEditAgentService()
    fake_ppt = _FakePPTService(
        [
            json.dumps(
                {
                    "thought": "Inspect before editing.",
                    "action": "inspect_slide_html",
                    "action_input": {"slide_index": 1},
                }
            ),
            json.dumps(
                {
                    "thought": "Update the title text.",
                    "action": "update_text",
                    "action_input": {"selector": "h1", "text": "Short Title"},
                }
            ),
            json.dumps(
                {
                    "thought": "The title is shorter and ready.",
                    "action": "final",
                    "action_input": {"summary": "Shortened the title."},
                }
            ),
        ]
    )
    events = []

    async def capture(event):
        events.append(event)

    proposal = await service.run_agent(_tool_request(), fake_ppt, capture)

    assert proposal.summary == "Shortened the title."
    assert "Short Title" in proposal.html_content
    assert proposal.validation.valid is True
    assert [event["type"] for event in events if event["type"] == "tool_call"] == [
        "tool_call",
        "tool_call",
    ]
    assert {event["type"] for event in events} >= {
        "agent_start",
        "agent_step",
        "tool_result",
        "draft_ready",
        "needs_confirmation",
    }


@pytest.mark.asyncio
async def test_slide_edit_agent_retries_initial_unstructured_text_response():
    service = SlideEditAgentService()
    fake_ppt = _NoNativeToolPPTService(
        [
            "I will make the title shorter.",
            json.dumps(
                {
                    "thought": "Use a structured tool call.",
                    "action": "update_text",
                    "action_input": {"selector": "h1", "text": "Short Title"},
                }
            ),
            json.dumps(
                {
                    "thought": "The title is shorter.",
                    "action": "final",
                    "action_input": {"summary": "Shortened the title."},
                }
            ),
        ]
    )

    proposal = await service.run_agent(_tool_request(maxIterations=3), fake_ppt)

    assert proposal.summary == "Shortened the title."
    assert "Short Title" in proposal.html_content
    second_prompt = fake_ppt.calls[1][1][-1].content
    second_context = json.loads(second_prompt.split("\n\n", 1)[1])
    assert "Response was not a valid JSON action" in second_context["scratchpad"][0]["error"]


@pytest.mark.asyncio
async def test_slide_edit_agent_allows_unstructured_final_after_tool_execution():
    service = SlideEditAgentService()
    fake_ppt = _NoNativeToolPPTService(
        [
            json.dumps(
                {
                    "thought": "Update the title text.",
                    "action": "update_text",
                    "action_input": {"selector": "h1", "text": "Short Title"},
                }
            ),
            "Shortened the title.",
        ]
    )

    proposal = await service.run_agent(_tool_request(maxIterations=3), fake_ppt)

    assert proposal.summary == "Shortened the title."
    assert "Short Title" in proposal.html_content


@pytest.mark.asyncio
async def test_slide_edit_agent_reports_unsupported_tool_and_continues():
    service = SlideEditAgentService()
    fake_ppt = _FakePPTService(
        [
            json.dumps(
                {
                    "thought": "Try an unknown tool.",
                    "action": "bad_tool",
                    "action_input": {},
                }
            ),
            json.dumps(
                {
                    "thought": "Finish without change.",
                    "action": "final",
                    "action_input": {"summary": "No safe change."},
                }
            ),
        ]
    )

    proposal = await service.run_agent(_tool_request(maxIterations=3), fake_ppt)

    assert proposal.summary == "No safe change."
    assert proposal.tool_transcript == []


@pytest.mark.asyncio
async def test_slide_edit_agent_finalizes_when_max_iterations_is_reached():
    service = SlideEditAgentService()
    fake_ppt = _FakePPTService(
        [
            json.dumps(
                {
                    "thought": "Inspect.",
                    "action": "inspect_slide_html",
                    "action_input": {},
                }
            ),
            json.dumps(
                {
                    "thought": "Inspect again.",
                    "action": "inspect_slide_html",
                    "action_input": {},
                }
            ),
        ]
    )

    proposal = await service.run_agent(_tool_request(maxIterations=2), fake_ppt)

    assert (
        proposal.summary
        == "Reached the maximum edit iterations and prepared the current draft."
    )
    assert proposal.validation.valid is True


@pytest.mark.asyncio
async def test_slide_edit_agent_emits_error_event_when_model_fails():
    service = SlideEditAgentService()
    events = []

    async def capture(event):
        events.append(event)

    with pytest.raises(RuntimeError, match="model unavailable"):
        await service.run_agent(_tool_request(), _FailingPPTService(), capture)

    error_events = [event for event in events if event["type"] == "error"]
    assert error_events == [
        {
            "type": "error",
            "phase": "model",
            "message": "model unavailable",
            "errorType": "RuntimeError",
            "iteration": 1,
        }
    ]


@pytest.mark.asyncio
async def test_slide_edit_agent_emits_error_event_when_tool_raises(monkeypatch):
    service = SlideEditAgentService()
    fake_ppt = _FakePPTService(
        [
            json.dumps(
                {
                    "thought": "Try to inspect.",
                    "action": "inspect_slide_html",
                    "action_input": {},
                }
            )
        ]
    )
    events = []

    async def capture(event):
        events.append(event)

    async def fail_tool(self, tool_name, tool_input):
        raise ValueError("tool exploded")

    monkeypatch.setattr(SlideEditToolRunner, "execute_tool", fail_tool)

    with pytest.raises(ValueError, match="tool exploded"):
        await service.run_agent(_tool_request(), fake_ppt, capture)

    error_events = [event for event in events if event["type"] == "error"]
    assert error_events == [
        {
            "type": "error",
            "phase": "tool",
            "message": "tool exploded",
            "errorType": "ValueError",
            "iteration": 1,
            "tool": "inspect_slide_html",
        }
    ]


@pytest.mark.asyncio
async def test_slide_edit_agent_vision_mode_sends_multimodal_context():
    service = SlideEditAgentService()
    screenshot = "data:image/png;base64,slide-shot"
    reference_url = "https://example.test/reference.png"
    fake_ppt = _FakePPTService(
        [
            json.dumps(
                {
                    "thought": "Vision context is enough.",
                    "action": "final",
                    "action_input": {"summary": "Checked visual context."},
                }
            )
        ]
    )

    proposal = await service.run_agent(
        _tool_request(
            visionEnabled=True,
            slideScreenshot=screenshot,
            images=[{"name": "Reference", "size": "120KB", "url": reference_url}],
        ),
        fake_ppt,
    )

    assert proposal.summary == "Checked visual context."
    role, messages, _kwargs = fake_ppt.calls[0]
    assert role == "vision_analysis"
    user_content = messages[-1].content
    assert isinstance(user_content, list)
    assert isinstance(user_content[0], TextContent)
    assert '"vision"' in user_content[0].text
    assert "slide_screenshot" in user_content[0].text
    assert "Reference" in user_content[0].text
    assert screenshot not in user_content[0].text
    image_parts = [part for part in user_content if isinstance(part, ImageContent)]
    assert [part.image_url["url"] for part in image_parts] == [
        screenshot,
        reference_url,
    ]


def test_slide_edit_agent_tool_schemas_match_runner_tool_names():
    service = SlideEditAgentService()
    runner = SlideEditToolRunner(_tool_context())

    schema_names = [schema["name"] for schema in service._tool_schemas(runner)]

    assert schema_names == runner.available_tool_names()
