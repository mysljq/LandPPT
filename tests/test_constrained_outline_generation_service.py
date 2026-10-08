import asyncio
from types import SimpleNamespace


def test_normalizes_llm_page_and_total_page_requirements():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    constraints = ConstrainedOutlineGenerationService._normalize_llm_constraints({
        "requested_total_pages": 6,
        "page_count_scope": "final_presentation",
        "reference_semantics": "content_page",
        "page_constraints": [
            {"page_number": 1, "must_include": ["行业背景"]},
            {"page_number": 2, "must_include": ["市场规模"]},
        ],
    })

    assert constraints["requested_total_pages"] == 6
    assert [item["page_number"] for item in constraints["page_constraints"]] == [1, 2]
    assert constraints["page_constraints"][0]["must_include"] == ["行业背景"]
    assert constraints["page_constraints"][1]["must_include"] == ["市场规模"]
    assert constraints["reference_semantics"] == "content_page"


def test_normalizes_llm_last_page_requirement():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    resolved = ConstrainedOutlineGenerationService._normalize_llm_constraints({
        "requested_total_pages": 6,
        "page_constraints": [{"position": "last", "must_include": ["投资建议"]}],
    })

    assert resolved["page_constraints"][0]["page_number"] is None
    assert resolved["page_constraints"][0]["position"] == "last"
    assert resolved["page_constraints"][0]["page_number"] is None
    assert resolved["page_constraints"][0]["position"] == "last"


def test_enforces_missing_page_requirement_without_changing_other_pages():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    outline = {
        "title": "行业分析",
        "slides": [
            {"page_number": 1, "title": "行业分析", "content_points": ["行业分析"], "slide_type": "title"},
            {"page_number": 2, "title": "目录", "content_points": [], "slide_type": "agenda"},
            {"page_number": 3, "title": "背景", "content_points": ["行业概览"], "slide_type": "content"},
            {"page_number": 4, "title": "规模", "content_points": ["市场规模"], "slide_type": "content"},
        ],
        "metadata": {},
    }
    constraints = {
        "page_constraints": [
            {"page_number": 1, "must_include": ["行业背景"]},
            {"page_number": 2, "must_include": ["市场规模"]},
        ]
    }

    result = ConstrainedOutlineGenerationService._enforce_page_constraints(outline, constraints)

    assert "行业背景" in result["slides"][2]["content_points"]
    assert result["slides"][3]["content_points"] == ["市场规模"]
    assert result["metadata"]["constraint_validation"]["version"] == "stage1"


def test_normalizes_fixed_page_count_and_preserves_required_page():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    outline = {
        "title": "主题",
        "slides": [
            {"page_number": index, "title": str(index), "content_points": [str(index)], "slide_type": "content"}
            for index in range(1, 6)
        ],
        "metadata": {},
    }
    constraints = {"page_constraints": [{"page_number": 1, "must_include": ["保留"], "reference_semantics": "content_page"}]}

    result = ConstrainedOutlineGenerationService._normalize_page_count(outline, 3, constraints)

    assert len(result["slides"]) == 3
    assert [slide["page_number"] for slide in result["slides"]] == [1, 2, 3]
    assert result["slides"][0]["title"] == "1"


def test_conflicting_total_page_count_does_not_drop_explicit_page():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    outline = {"title": "主题", "slides": [], "metadata": {}}
    constraints = {"page_constraints": [{"page_number": 5, "must_include": ["风险"]}]}

    result = ConstrainedOutlineGenerationService._normalize_page_count(outline, 3, constraints)

    assert len(result["slides"]) == 7
    assert "constraint_conflict" in result["metadata"]


def test_constrained_flow_always_adds_cover_and_agenda_before_content_pages():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    outline = {
        "title": "主题",
        "slides": [
            {"page_number": 1, "title": "市场规模", "content_points": ["规模"], "slide_type": "content"},
        ],
        "metadata": {},
    }
    result = ConstrainedOutlineGenerationService._ensure_cover_and_agenda(outline)
    result = ConstrainedOutlineGenerationService._normalize_page_count(
        result,
        3,
        {"page_constraints": [{"page_number": 1, "must_include": ["市场规模"], "reference_semantics": "content_page"}]},
    )
    result = ConstrainedOutlineGenerationService._enforce_page_constraints(
        result,
        {"page_constraints": [{"page_number": 1, "must_include": ["市场规模"], "reference_semantics": "content_page"}]},
    )

    assert [slide["slide_type"] for slide in result["slides"]] == ["title", "agenda", "content"]
    assert "市场规模" in " ".join([
        result["slides"][2].get("title", ""),
        *result["slides"][2].get("content_points", []),
    ])


def test_llm_intent_parser_is_primary_for_page_semantics():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    class FakePPTService:
        async def _text_completion_for_role(self, role, *, prompt, temperature):
            assert role == "outline"
            assert "内容区第 1 页" in prompt
            return SimpleNamespace(content='{"reference_semantics":"content_page","requested_total_pages":6,"page_count_scope":"final_presentation","page_constraints":[{"page_number":1,"must_include":["市场规模"],"slide_type":"content"}]}')

    service = ConstrainedOutlineGenerationService(FakePPTService())
    result = asyncio.run(service.extract_constraints_with_llm("第一页介绍市场规模，共6页"))

    assert result["parser"] == "llm"
    assert result["page_constraints"][0]["reference_semantics"] == "content_page"
    assert result["page_constraints"][0]["slide_type"] == "content"


def test_llm_intent_parser_failure_returns_failure_marker_without_regex_fallback():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    class FailingPPTService:
        async def _text_completion_for_role(self, role, *, prompt, temperature):
            raise RuntimeError("parser unavailable")

    result = asyncio.run(
        ConstrainedOutlineGenerationService(FailingPPTService()).extract_constraints_with_llm(
            "第一页包含行业背景"
        )
    )

    assert result["intent_parse_failed"] is True
    assert result["parser"] == "llm_failed"
    assert result["page_constraints"] == []


def test_llm_intent_parser_retries_invalid_json_with_repair_prompt():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    class RetryingPPTService:
        def __init__(self):
            self.prompts = []

        async def _text_completion_for_role(self, role, *, prompt, temperature):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return SimpleNamespace(content="这不是 JSON")
            return SimpleNamespace(content='{"page_constraints": [{"page_number": 1, "must_include": ["行业背景"]}]}')

    ppt_service = RetryingPPTService()
    result = asyncio.run(
        ConstrainedOutlineGenerationService(ppt_service).extract_constraints_with_llm(
            "第一页包含行业背景"
        )
    )

    assert result["parser"] == "llm"
    assert len(ppt_service.prompts) == 2
    assert "不是有效 JSON" in ppt_service.prompts[1]


def test_llm_intent_parser_retries_call_errors_twice_before_failure():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    class AlwaysFailingPPTService:
        def __init__(self):
            self.calls = 0

        async def _text_completion_for_role(self, role, *, prompt, temperature):
            self.calls += 1
            raise RuntimeError("temporary outage")

    ppt_service = AlwaysFailingPPTService()
    result = asyncio.run(
        ConstrainedOutlineGenerationService(ppt_service).extract_constraints_with_llm(
            "第一页包含行业背景"
        )
    )

    assert ppt_service.calls == 3
    assert result["intent_parse_failed"] is True


def test_generation_mode_classifier_chooses_strict_from_valid_model_json():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    class FakePPTService:
        async def _text_completion_for_role(self, role, *, prompt, temperature):
            return SimpleNamespace(content='{"mode":"strict","reason":"明确指定页码内容"}')

    result = asyncio.run(
        ConstrainedOutlineGenerationService(FakePPTService()).classify_generation_mode(
            "第一页包含行业背景，第二页包含市场规模"
        )
    )
    assert result["mode"] == "strict"
    assert result["parser"] == "llm"


def test_generation_falls_back_to_original_flow_when_intent_parser_fails():
    from landppt.services.outline.constrained_outline_generation_service import (
        ConstrainedOutlineGenerationService,
    )

    class FakePPTService:
        def __init__(self):
            self.called_request = None
            self.saved = None

        async def _text_completion_for_role(self, role, *, prompt, temperature):
            raise RuntimeError("parser unavailable")

        async def generate_outline(self, request, page_count_settings):
            self.called_request = request
            return SimpleNamespace(title="legacy", slides=[{"page_number": 1}], metadata={})

        async def _update_outline_generation_stage(self, project_id, outline):
            self.saved = outline

    ppt_service = FakePPTService()
    request = SimpleNamespace(requirements="第一页包含行业背景", description="")
    result = asyncio.run(
        ConstrainedOutlineGenerationService(ppt_service).generate("project", request, {"mode": "fixed", "fixed_pages": 8})
    )

    assert ppt_service.called_request is request
    assert result["metadata"]["generation_entrypoint"] == "constrained-stage1-fallback-original"
    assert result["metadata"]["constraint_parser"] == "llm_failed"
    assert result["slides"] == [{"page_number": 1}]
