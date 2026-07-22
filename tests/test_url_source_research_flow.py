from types import SimpleNamespace

import pytest

from landppt.api.models import PPTProject
from landppt.services.research.content_extractor import ExtractedContent
from landppt.web.route_modules import outline_support


class FakePPTService:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.research_calls = []
        self.generated_requests = []
        self.updated_outlines = []

    async def conduct_research_and_merge_with_files(
        self,
        *,
        topic,
        language,
        file_paths,
        context,
        event_callback=None,
    ):
        self.research_calls.append(
            {
                "topic": topic,
                "language": language,
                "file_paths": list(file_paths),
                "context": dict(context),
            }
        )
        if event_callback:
            await event_callback(
                {
                    "type": "status",
                    "step": "research",
                    "message": "running research",
                    "progress": 0.4,
                }
            )

        merged_path = self.tmp_path / "merged_with_research.md"
        merged_path.write_text("# merged research\n\nurl content", encoding="utf-8")
        return str(merged_path)

    async def generate_outline_from_file(self, request):
        self.generated_requests.append(request)
        return SimpleNamespace(
            success=True,
            outline={"title": "URL Outline", "slides": [], "metadata": {}},
            processing_stats={"llm_call_count": 2},
            error=None,
        )

    def iter_research_stream_payloads(self, event):
        yield {
            "status": {
                "step": event.get("step", "research"),
                "message": event.get("message", ""),
                "progress": event.get("progress", 0),
            }
        }

    async def _update_outline_generation_stage(self, project_id, outline):
        self.updated_outlines.append((project_id, outline))


class FakeWebContentExtractor:
    async def extract_multiple(self, urls, max_concurrent=3, delay_between_requests=0.1):
        return [
            ExtractedContent(
                url=urls[0],
                title="Example Article",
                content="This is extracted URL source content for outline generation.",
            )
        ]


def _save_test_project_file(tmp_path):
    def _save(content: bytes, filename: str) -> str:
        path = tmp_path / filename
        path.write_bytes(content)
        return str(path)

    return _save


def _project(network_mode=True):
    return PPTProject(
        project_id="project-1",
        title="Project",
        scenario="business",
        topic="AI market",
        requirements="Use recent market facts.",
        project_metadata={"network_mode": network_mode, "language": "zh"},
    )


def _confirmed_requirements():
    return {
        "content_source": "url",
        "source_urls": ["https://example.com/article"],
        "topic": "AI market",
        "target_audience": "Executives",
        "requirements": "Use recent market facts.",
        "page_count_settings": {"mode": "fixed", "fixed_pages": 5},
        "ppt_style": "general",
        "file_processing_mode": "markitdown",
        "content_analysis_depth": "standard",
    }


def _patch_url_flow(monkeypatch, tmp_path, fake_service):
    async def fake_url_likely_points_to_file(session, source_url):
        return False

    monkeypatch.setattr(
        outline_support,
        "_url_likely_points_to_file",
        fake_url_likely_points_to_file,
    )
    monkeypatch.setattr(
        outline_support,
        "_save_project_file_sync",
        _save_test_project_file(tmp_path),
    )
    monkeypatch.setattr(
        "landppt.services.research.content_extractor.WebContentExtractor",
        FakeWebContentExtractor,
    )
    monkeypatch.setattr(
        outline_support,
        "get_ppt_service_for_user",
        lambda user_id: fake_service,
    )


@pytest.mark.asyncio
async def test_url_source_network_mode_runs_research_before_outline(monkeypatch, tmp_path):
    fake_service = FakePPTService(tmp_path)
    _patch_url_flow(monkeypatch, tmp_path, fake_service)

    events = []

    async def event_callback(event):
        events.append(event)

    outline = await outline_support._generate_outline_from_confirmed_sources(
        _project(network_mode=True),
        _confirmed_requirements(),
        user_id=1,
        event_callback=event_callback,
    )

    assert fake_service.research_calls
    assert "url_sources_" in fake_service.research_calls[0]["file_paths"][0]
    assert fake_service.generated_requests[0].file_path.endswith("merged_with_research.md")
    assert fake_service.generated_requests[0].filename == "merged_with_search_1_url_sources.md"
    assert outline["metadata"]["research_merged"] is True
    assert outline["file_info"]["research_merged"] is True
    assert events and events[0]["step"] == "research"


@pytest.mark.asyncio
async def test_url_source_stream_emits_research_status(monkeypatch, tmp_path):
    fake_service = FakePPTService(tmp_path)
    _patch_url_flow(monkeypatch, tmp_path, fake_service)

    async def fake_persist(project_id, confirmed_requirements, outline, *, user_id):
        return confirmed_requirements

    monkeypatch.setattr(
        outline_support,
        "_persist_generated_source_outline",
        fake_persist,
    )

    chunks = []
    async for chunk in outline_support._stream_outline_from_confirmed_sources_v2(
        "project-1",
        _project(network_mode=True),
        _confirmed_requirements(),
        user_id=1,
    ):
        chunks.append(chunk)

    stream_text = "".join(chunks)
    assert '"step": "research"' in stream_text
    assert '"done": true' in stream_text
    assert fake_service.research_calls
    assert fake_service.updated_outlines
