import os
import sys
import types
import json

import pytest


os.environ["DEBUG"] = "false"


if "tavily" not in sys.modules:
    fake_tavily = types.ModuleType("tavily")

    class _BootstrapTavilyClient:
        def __init__(self, api_key, api_base_url=None):
            self.api_key = api_key
            self.api_base_url = api_base_url

        def search(self, **kwargs):
            return {"results": []}

    fake_tavily.TavilyClient = _BootstrapTavilyClient
    sys.modules["tavily"] = fake_tavily


from landppt.services import deep_research_service as drs
from landppt.services.deep_research_service import (
    DEEPResearchService,
    _is_tavily_auth_error,
    _normalize_secret_value,
)


def test_normalize_secret_value_filters_empty_and_masked_values():
    assert _normalize_secret_value(None) is None
    assert _normalize_secret_value("") is None
    assert _normalize_secret_value("   ") is None
    assert _normalize_secret_value("********") is None
    assert _normalize_secret_value("  tvly-good  ") == "tvly-good"


def test_is_tavily_auth_error_matches_common_messages():
    assert (
        _is_tavily_auth_error(Exception("Unauthorized: missing or invalid API key."))
        is True
    )
    assert _is_tavily_auth_error(Exception("invalid_api_key")) is True
    assert _is_tavily_auth_error(Exception("timeout")) is False


class _FakeAgentProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def stream_text_completion(self, prompt, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        yield response


@pytest.mark.asyncio
async def test_conduct_deep_research_runs_react_agent_loop(monkeypatch):
    service = DEEPResearchService()
    provider = _FakeAgentProvider(
        [
            json.dumps(
                {
                    "thought": "Find current evidence first.",
                    "action": "tavily_search",
                    "action_input": {"query": "AI PPT market 2026", "max_results": 3},
                }
            ),
            json.dumps(
                {
                    "thought": "Read the strongest source.",
                    "action": "fetch",
                    "action_input": {"url": "https://example.com/report"},
                }
            ),
            json.dumps(
                {
                    "thought": "The observations are sufficient.",
                    "action": "final",
                    "action_input": {
                        "executive_summary": "AI PPT tools are becoming agentic.",
                        "key_findings": [
                            "Agentic research is now part of the workflow."
                        ],
                        "recommendations": [
                            "Use cited observations in the PPT outline."
                        ],
                        "sources": ["https://example.com/report"],
                    },
                }
            ),
        ]
    )
    tool_calls = []
    events = []

    async def fake_get_provider():
        return provider

    async def fake_execute_tool(tool_name, tool_input, language):
        tool_calls.append((tool_name, tool_input, language))
        if tool_name == "tavily_search":
            return {
                "success": True,
                "tool": "tavily_search",
                "query": tool_input["query"],
                "results": [
                    {
                        "title": "AI PPT Report",
                        "url": "https://example.com/report",
                        "content": "Agentic research tools are being adopted.",
                        "score": 0.9,
                        "published_date": "2026-06-01",
                    }
                ],
            }
        return {
            "success": True,
            "tool": "fetch",
            "url": tool_input["url"],
            "title": "AI PPT Report",
            "content": "Fetched source content.",
        }

    async def capture_event(event):
        events.append(event)

    monkeypatch.setattr(service, "get_ai_provider_async", fake_get_provider)
    monkeypatch.setattr(service, "_execute_research_tool", fake_execute_tool)

    report = await service.conduct_deep_research(
        "AI PPT market",
        "en",
        context={"max_agent_iterations": 4},
        event_callback=capture_event,
    )

    assert [call[0] for call in tool_calls] == ["tavily_search", "fetch"]
    assert report.executive_summary == "AI PPT tools are becoming agentic."
    assert report.key_findings == ["Agentic research is now part of the workflow."]
    assert report.recommendations == ["Use cited observations in the PPT outline."]
    assert report.sources == ["https://example.com/report"]
    assert len(report.steps) == 2
    assert {event["type"] for event in events} >= {
        "agent_loop_start",
        "agent_iteration",
        "tool_call",
        "tool_result",
        "report_ready",
    }


def test_parse_react_action_supports_json_and_plain_text():
    service = DEEPResearchService()

    json_action = service._parse_react_action(
        '```json\n{"thought":"Search first","action":"search","action_input":{"query":"LandPPT"}}\n```'
    )
    assert json_action.action == "tavily_search"
    assert json_action.action_input == {"query": "LandPPT"}

    plain_action = service._parse_react_action(
        'Thought: Read the source\nAction: fetch\nAction Input: {"url":"https://example.com"}'
    )
    assert plain_action.action == "fetch"
    assert plain_action.action_input == {"url": "https://example.com"}


def test_fetch_and_curl_url_validation_rejects_local_targets():
    service = DEEPResearchService()

    assert service._validate_public_http_url("https://example.com") is None
    assert service._validate_public_http_url("http://localhost:8000") is not None
    assert service._validate_public_http_url("http://127.0.0.1:8000") is not None
    assert service._validate_public_http_url("file:///etc/passwd") is not None


def test_agent_max_iterations_allows_up_to_50():
    service = DEEPResearchService()

    assert service._get_agent_max_iterations(None) == 8
    assert service._get_agent_max_iterations({"max_agent_iterations": 1}) == 2
    assert service._get_agent_max_iterations({"max_agent_iterations": 30}) == 30
    assert service._get_agent_max_iterations({"max_agent_iterations": 999}) == 50


@pytest.mark.asyncio
async def test_tavily_search_retries_next_key_on_auth_error(monkeypatch):
    service = DEEPResearchService()

    async def fake_candidates():
        return [
            ("user database override", "bad-key"),
            ("system database default", "good-key"),
        ]

    class FakeTavilyClient:
        def __init__(self, api_key, api_base_url=None):
            self.api_key = api_key
            self.api_base_url = api_base_url

        def search(self, **kwargs):
            if self.api_key == "bad-key":
                raise Exception("Unauthorized: missing or invalid API key.")
            return {
                "results": [
                    {
                        "title": "SkillNet",
                        "url": "https://example.com",
                        "content": "ok",
                        "score": 0.9,
                        "published_date": "2026-03-08",
                    }
                ]
            }

    monkeypatch.setattr(
        service, "_get_tavily_api_key_candidates_async", fake_candidates
    )
    monkeypatch.setattr(drs, "TavilyClient", FakeTavilyClient)
    monkeypatch.setattr(drs.ai_config, "tavily_include_domains", None, raising=False)
    monkeypatch.setattr(drs.ai_config, "tavily_exclude_domains", None, raising=False)

    results = await service._tavily_search("SkillNet", "zh")

    assert results == [
        {
            "title": "SkillNet",
            "url": "https://example.com",
            "content": "ok",
            "score": 0.9,
            "published_date": "2026-03-08",
        }
    ]
    assert service._active_tavily_key_source == "system database default"


@pytest.mark.asyncio
async def test_tavily_search_uses_runtime_base_url(monkeypatch):
    service = DEEPResearchService()
    created_clients = []

    async def fake_candidates():
        return [("process environment", "good-key")]

    async def fake_runtime_config():
        return {
            "base_url": "https://gateway.example.com/tavily",
            "max_results": 7,
            "search_depth": "advanced",
            "include_domains": ["example.com"],
            "exclude_domains": None,
        }

    class FakeTavilyClient:
        def __init__(self, api_key, api_base_url=None):
            self.api_key = api_key
            self.api_base_url = api_base_url
            created_clients.append(self)

        def search(self, **kwargs):
            assert kwargs["max_results"] == 7
            assert kwargs["search_depth"] == "advanced"
            assert kwargs["include_domains"] == ["example.com"]
            return {"results": []}

    monkeypatch.setattr(
        service, "_get_tavily_api_key_candidates_async", fake_candidates
    )
    monkeypatch.setattr(
        service, "_get_tavily_runtime_config_async", fake_runtime_config
    )
    monkeypatch.setattr(drs, "TavilyClient", FakeTavilyClient)

    results = await service._tavily_search("SkillNet", "zh")

    assert results == []
    assert created_clients[0].api_base_url == "https://gateway.example.com/tavily"


@pytest.mark.asyncio
async def test_react_tool_tavily_extract_uses_sdk_method(monkeypatch):
    service = DEEPResearchService()
    calls = []

    async def fake_candidates():
        return [("process environment", "good-key")]

    class FakeTavilyClient:
        def __init__(self, api_key, api_base_url=None):
            self.api_key = api_key
            self.api_base_url = api_base_url

        def extract(self, **kwargs):
            calls.append(kwargs)
            return {
                "results": [
                    {
                        "title": "Source",
                        "url": "https://example.com/source",
                        "raw_content": "Long source content",
                    }
                ],
                "failed_results": [],
            }

    monkeypatch.setattr(
        service, "_get_tavily_api_key_candidates_async", fake_candidates
    )
    monkeypatch.setattr(drs, "TavilyClient", FakeTavilyClient)

    observation = await service._execute_research_tool(
        "tavily_extract",
        {"urls": ["https://example.com/source"], "format": "text"},
        "en",
    )

    assert observation["success"] is True
    assert calls == [
        {
            "urls": ["https://example.com/source"],
            "extract_depth": "advanced",
            "format": "text",
            "timeout": 30,
        }
    ]
    assert observation["results"] == [
        {
            "title": "Source",
            "url": "https://example.com/source",
            "content": "Long source content",
            "score": 0,
            "published_date": "",
        }
    ]


@pytest.mark.asyncio
async def test_tavily_runtime_config_ignores_blank_db_base_url(monkeypatch):
    import landppt.database.database as database_mod
    import landppt.database.repositories as repo_mod

    service = DEEPResearchService(user_id=123)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeRepo:
        def __init__(self, session):
            self.session = session

        async def get_all_configs(self, user_id=None):
            return {
                "tavily_base_url": {
                    "value": "",
                    "type": "url",
                    "category": "generation_params",
                    "is_user_override": True,
                }
            }

    monkeypatch.setattr(database_mod, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(repo_mod, "UserConfigRepository", FakeRepo)

    config = await service._get_tavily_runtime_config_async()

    assert config["base_url"] == "https://api.tavily.com"
