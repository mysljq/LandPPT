from pathlib import Path
from types import SimpleNamespace

import pytest

from landppt.services.outline.outline_workflow_service import OutlineWorkflowService
from landppt.services.outline.outline_workflow_support import (
    build_project_requirements_text,
    create_outline_from_file_content,
    get_chunk_size_from_request,
    get_slides_range_from_request,
    is_enhanced_research_file,
)


def _build_request(**overrides):
    payload = {
        "file_path": "",
        "filename": "outline.md",
        "topic": "Quarterly Review",
        "scenario": "general",
        "requirements": "Keep it concise",
        "target_audience": "Leadership",
        "custom_audience": "",
        "description": "",
        "language": "zh",
        "page_count_mode": "ai_decide",
        "min_pages": 8,
        "max_pages": 15,
        "fixed_pages": 10,
        "ppt_style": "general",
        "custom_style_prompt": None,
        "file_processing_mode": "markitdown",
        "content_analysis_depth": "standard",
        "focus_content": [],
        "tech_highlights": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_outline_workflow_support_resolves_page_and_chunk_settings():
    fixed_request = _build_request(page_count_mode="fixed", fixed_pages=12)
    custom_request = _build_request(page_count_mode="custom_range", min_pages=6, max_pages=18)
    fast_request = _build_request(content_analysis_depth="fast")
    deep_request = _build_request(content_analysis_depth="deep")

    assert get_slides_range_from_request(fixed_request) == (12, 12)
    assert get_slides_range_from_request(custom_request) == (6, 18)
    assert get_slides_range_from_request(_build_request()) == (5, 30)

    assert get_chunk_size_from_request(fast_request) == 1500
    assert get_chunk_size_from_request(deep_request) == 4000
    assert get_chunk_size_from_request(_build_request()) == 3000


def test_outline_workflow_support_detects_enhanced_research_files(tmp_path):
    research_file = tmp_path / "enhanced_research_report.md"
    research_file.write_text(
        "# 深度研究报告\n\n## 核心发现\n\n要点 1\n",
        encoding="utf-8",
    )

    request = _build_request(
        filename=research_file.name,
        file_path=str(research_file),
    )

    assert is_enhanced_research_file(request) is True


def test_outline_workflow_support_builds_fixed_page_outline():
    request = _build_request(page_count_mode="fixed", fixed_pages=4)
    outline = create_outline_from_file_content(
        "# Opening\nFirst point\n## Market\nSecond point\n## Plan\nThird point\n",
        request,
    )

    assert outline["title"] == "Quarterly Review"
    assert len(outline["slides"]) == 4
    assert outline["slides"][0]["slide_type"] == "title"
    assert outline["slides"][-1]["page_number"] == 4


def test_outline_workflow_support_combines_requirements_and_description():
    request = _build_request(
        requirements="Highlight security risks",
        description="Prioritize mitigation roadmap",
    )

    project_requirements = build_project_requirements_text(request)

    assert "Highlight security risks" in project_requirements
    assert "Prioritize mitigation roadmap" in project_requirements


@pytest.mark.asyncio
async def test_outline_workflow_service_falls_back_when_generator_is_unavailable(tmp_path):
    source_file = tmp_path / "fallback.md"
    source_file.write_text(
        "# Introduction\nContext line\n## Results\nResult line\n",
        encoding="utf-8",
    )

    request = _build_request(
        file_path=str(source_file),
        filename=source_file.name,
        page_count_mode="fixed",
        fixed_pages=3,
    )

    class DummyService:
        def __init__(self):
            self.validation_requirements = None

        def _read_file_with_fallback_encoding(self, file_path):
            return Path(file_path).read_text(encoding="utf-8")

        async def _validate_and_repair_outline_json(self, outline, requirements):
            self.validation_requirements = requirements
            return outline

    workflow = OutlineWorkflowService(DummyService())

    async def _raise_import_error(_request):
        raise ImportError("summeryanyfile not installed")

    workflow._create_outline_generator = _raise_import_error

    result = await workflow.generate_outline_from_file(request)

    assert result.success is True
    assert result.processing_stats["generator"] == "fallback"
    assert result.processing_stats["slides_count"] == 3
    assert result.file_info["used_summeryanyfile"] is False
    assert result.outline["slides"][0]["title"] == "Quarterly Review"
    assert workflow._service.validation_requirements["topic"] == "Quarterly Review"


@pytest.mark.asyncio
async def test_outline_workflow_service_passes_user_context_to_summeryanyfile(tmp_path):
    source_file = tmp_path / "source.md"
    source_file.write_text("# Market\nContext", encoding="utf-8")

    request = _build_request(
        file_path=str(source_file),
        filename=source_file.name,
        requirements="Highlight security risks",
        description="Prioritize mitigation roadmap",
        custom_audience="Board audit committee",
    )

    class FakeOutline:
        total_pages = 1

        def to_dict(self):
            return {
                "title": "Quarterly Review",
                "slides": [
                    {
                        "page_number": 1,
                        "title": "Quarterly Review",
                        "content_points": ["Context"],
                        "slide_type": "title",
                    }
                ],
            }

    class FakeGenerator:
        def __init__(self):
            self.kwargs = None

        async def generate_from_file(self, file_path, **kwargs):
            self.kwargs = kwargs
            return FakeOutline()

    class DummyService:
        def __init__(self):
            self.validation_requirements = None

        def _standardize_summeryfile_outline(self, outline):
            return outline

        async def _validate_and_repair_outline_json(self, outline, requirements):
            self.validation_requirements = requirements
            return outline

        def _extract_summeryanyfile_llm_call_count(self, _generator):
            return 1

    fake_generator = FakeGenerator()
    workflow = OutlineWorkflowService(DummyService())

    async def _create_fake_generator(_request):
        return fake_generator, tmp_path

    workflow._create_outline_generator = _create_fake_generator

    result = await workflow.generate_outline_from_file(request)

    assert result.success is True
    assert "Highlight security risks" in fake_generator.kwargs["project_requirements"]
    assert "Prioritize mitigation roadmap" in fake_generator.kwargs["project_requirements"]
    assert fake_generator.kwargs["custom_audience"] == "Board audit committee"
    assert workflow._service.validation_requirements["custom_audience"] == "Board audit committee"
    assert workflow._service.validation_requirements["description"] == "Prioritize mitigation roadmap"
