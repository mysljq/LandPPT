import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from summeryanyfile.core.json_parser import JSONParser
from summeryanyfile.generators.chains import ChainExecutor
from summeryanyfile.graph.nodes import GraphNodes
from landppt.services.outline.outline_workflow_service import OutlineWorkflowService


def outline(pages=24):
    return {"title": "报告", "slides": [
        {"title": f"第{i}页", "content_points": [f"正文{i}"], "slide_type": "content"}
        for i in range(1, pages + 1)
    ]}


@pytest.mark.asyncio
@pytest.mark.parametrize("fenced", [False, True])
async def test_complete_outline_survives_provider_error_at_stream_end(fenced):
    raw = json.dumps(outline(), ensure_ascii=False)
    if fenced:
        raw = f"```json\n{raw}\n```"
    calls = []
    async def stream(*args):
        calls.append(args)
        for offset in range(0, len(raw), 10):
            yield raw[offset:offset + 10]
        raise RuntimeError("provider failed closing stream")
    executor = ChainExecutor(SimpleNamespace(stream_chain=stream))
    result = await executor.execute_with_retry_streaming("initial_outline", {})
    assert len(json.loads(result)["slides"]) == 24
    assert len(calls) == 1
    assert executor.llm_call_count == 1


@pytest.mark.asyncio
async def test_truncated_outline_is_not_recovered_as_one_inner_slide():
    async def stream(*args):
        yield '{"title":"报告","slides":[{"title":"开场","content_points":["正文"]},'
        raise RuntimeError("incomplete stream")
    executor = ChainExecutor(SimpleNamespace(stream_chain=stream), max_retries=1)
    with pytest.raises(RuntimeError, match="incomplete"):
        await executor.execute_with_retry_streaming("initial_outline", {})


@pytest.mark.parametrize("raw", [None, "", "not json"])
def test_unparseable_response_never_becomes_placeholder_cover(raw):
    with pytest.raises(ValueError):
        JSONParser.extract_json_from_response(raw)


@pytest.mark.parametrize("value", [{}, {"slides": []}, {"slides": ["bad"]}])
def test_missing_outline_is_rejected(value):
    with pytest.raises(ValueError):
        JSONParser.validate_ppt_structure(value)


@pytest.mark.asyncio
async def test_initial_failure_does_not_return_one_page_success():
    nodes = GraphNodes.__new__(GraphNodes)
    nodes.config = None
    nodes.chain_executor = SimpleNamespace(execute_with_retry_streaming=AsyncMock(return_value="not json"))
    nodes.json_parser = JSONParser()
    with pytest.raises(ValueError, match="初始大纲生成失败"):
        await nodes.generate_initial_outline_streaming({"document_structure": {}, "document_chunks": ["正文"]}, {})


@pytest.mark.asyncio
async def test_failed_file_stream_does_not_publish_rule_fallback(tmp_path):
    async def stream(*args, **kwargs):
        yield {"content": "中间生成内容"}
        raise RuntimeError("generation failed")
    workflow = OutlineWorkflowService(SimpleNamespace())
    workflow._create_outline_generator = AsyncMock(return_value=(SimpleNamespace(stream_generate_from_file=stream), tmp_path))
    workflow._generate_outline_from_file_fallback = AsyncMock()
    request = SimpleNamespace(filename="a.md", file_path="missing.md", topic="报告", scenario="general", requirements="")
    events = [event async for event in workflow.generate_outline_from_file_streaming(request)]
    assert events[-1] == {"error": "generation failed"}
    assert not any("outline" in event for event in events)
    workflow._generate_outline_from_file_fallback.assert_not_awaited()
