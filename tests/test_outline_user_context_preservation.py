import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object, Comment=object)

if "tavily" not in sys.modules:
    sys.modules["tavily"] = types.SimpleNamespace(TavilyClient=object)

if "langchain_core.documents" not in sys.modules:
    langchain_core_module = sys.modules.setdefault(
        "langchain_core",
        types.ModuleType("langchain_core"),
    )
    documents_module = types.ModuleType("langchain_core.documents")
    documents_module.Document = object
    sys.modules["langchain_core.documents"] = documents_module
    setattr(langchain_core_module, "documents", documents_module)

from landppt.services.outline.project_outline_research_service import ProjectOutlineResearchService


class _OutlineResearchStubService:
    enhanced_research_service = None
    enhanced_report_generator = None

    def _initialize_research_services(self):
        return None


@pytest.mark.asyncio
async def test_research_file_merge_preserves_user_requirements(monkeypatch, tmp_path):
    service = ProjectOutlineResearchService(_OutlineResearchStubService())

    fake_module = types.ModuleType("landppt.services.file_processor")

    class _FakeFileProcessor:
        async def process_file(self, file_path, filename, file_processing_mode=None):
            return SimpleNamespace(
                processed_content=f"{filename}:{file_processing_mode or 'default'}:{file_path}"
            )

    fake_module.FileProcessor = _FakeFileProcessor
    monkeypatch.setitem(sys.modules, "landppt.services.file_processor", fake_module)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    merged_path = await service.conduct_research_and_merge_with_files(
        topic="Test Topic",
        language="zh",
        file_paths=["dummy.txt"],
        context={
            "file_processing_mode": "markitdown",
            "requirements": "Highlight operational risk",
            "description": "Prioritize executive action items",
            "custom_audience": "CFO office",
            "source_summary": "File count: 1",
        },
    )

    merged_content = Path(merged_path).read_text(encoding="utf-8")
    assert "## User Requirements" in merged_content
    assert "Highlight operational risk" in merged_content
    assert "Prioritize executive action items" in merged_content
    assert "CFO office" in merged_content
    assert merged_content.index("## User Requirements") < merged_content.index("dummy.txt")
    assert "markitdown" in merged_content
    assert str(tmp_path) in str(Path(merged_path).parent.parent)


def test_url_source_outline_user_brief_preserves_requirements():
    from landppt.web.route_modules.outline_support import (
        _build_source_outline_user_brief_markdown,
    )

    brief = _build_source_outline_user_brief_markdown(
        topic="AI Strategy",
        scenario="business",
        target_audience="Executives",
        requirements="Use an investment committee perspective",
        description="Avoid generic market overview",
        custom_audience="Investment committee",
        ppt_style="general",
        custom_style_prompt="Concise and evidence-led",
        source_summary="URL count: 2",
    )

    assert "## User Requirements" in brief
    assert "Use an investment committee perspective" in brief
    assert "Avoid generic market overview" in brief
    assert "Investment committee" in brief
    assert "URL count: 2" in brief
