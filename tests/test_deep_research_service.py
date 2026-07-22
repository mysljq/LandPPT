import os
import sys
import types

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
    assert _is_tavily_auth_error(Exception("Unauthorized: missing or invalid API key.")) is True
    assert _is_tavily_auth_error(Exception("invalid_api_key")) is True
    assert _is_tavily_auth_error(Exception("timeout")) is False


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

    monkeypatch.setattr(service, "_get_tavily_api_key_candidates_async", fake_candidates)
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

    monkeypatch.setattr(service, "_get_tavily_api_key_candidates_async", fake_candidates)
    monkeypatch.setattr(service, "_get_tavily_runtime_config_async", fake_runtime_config)
    monkeypatch.setattr(drs, "TavilyClient", FakeTavilyClient)

    results = await service._tavily_search("SkillNet", "zh")

    assert results == []
    assert created_clients[0].api_base_url == "https://gateway.example.com/tavily"


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
