from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import pytest
from docx import Document

from landppt.services.outline.document_structure_service import (
    DOCUMENT_STRUCTURE_MODE, read_document_source, generate_document_outline,
    validate_document_outline, get_document_outline,
)
from landppt.services.outline.project_outline_normalization_service import ProjectOutlineNormalizationService


def sample_outline(*args):
    return {"title": "报告", "slides": [
        {"title": "报告", "slide_type": "title", "content_points": [], "source_id": "root",
         "source_parent_id": None, "source_path": ["报告"], "source_heading_level": 0, "section": "报告", "chapter": 0},
        {"title": "章节", "slide_type": "content", "content_points": ["内容原文"], "source_id": "child",
         "source_parent_id": "root", "source_path": ["报告", "章节"], "source_heading_level": 1, "section": "章节", "chapter": 1}],
        "metadata": {"generation_mode": DOCUMENT_STRUCTURE_MODE}}


@pytest.mark.asyncio
async def test_model_interprets_nonstandard_source_and_receives_complete_document():
    source = "【项目汇报】\n一、现状\n加粗文字作为子标题\n原始数据 27.65%\n- 列表\n  - 子项"
    result = sample_outline()
    result["slides"][1]["content_points"] = [source]
    service = SimpleNamespace(_text_completion_for_role=AsyncMock(return_value=SimpleNamespace(content=json.dumps(result))))
    outline = await generate_document_outline(source, "report.md", "项目主题", service)
    assert outline["slides"][1]["content_points"] == [source]
    assert outline["title"] == "项目主题"
    assert outline["metadata"]["structure_parser"] == "llm"
    assert outline["metadata"]["llm_call_count"] == 1
    prompt = service._text_completion_for_role.call_args.kwargs["prompt"]
    assert source in prompt
    assert "手工编号" in prompt and "不要扩写" in prompt


@pytest.mark.asyncio
async def test_invalid_model_output_is_repaired_by_model_without_rule_fallback():
    service = SimpleNamespace(_text_completion_for_role=AsyncMock(side_effect=[
        SimpleNamespace(content="invalid"), SimpleNamespace(content=json.dumps(sample_outline()))]))
    outline = await generate_document_outline("original", "a.md", "", service)
    assert outline["metadata"]["llm_call_count"] == 2
    assert "格式校验失败" in service._text_completion_for_role.call_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_invalid_model_output_fails_after_three_attempts():
    service = SimpleNamespace(_text_completion_for_role=AsyncMock(return_value=SimpleNamespace(content="{}")))
    with pytest.raises(ValueError, match="大模型"):
        await generate_document_outline("original", "a.md", "", service)
    assert service._text_completion_for_role.await_count == 3


def test_word_is_read_as_original_xml_and_styles_for_model_interpretation():
    document = Document()
    document.add_heading("报告", 0)
    document.add_paragraph("正文原文")
    buffer = BytesIO()
    document.save(buffer)
    filename, source = read_document_source(buffer.getvalue(), "report.docx")
    assert filename == "report.docx"
    assert "word/document.xml" in source and "word/styles.xml" in source
    assert "正文原文" in source and "w:pStyle" in source


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "gb18030"])
def test_markdown_is_sent_verbatim_without_heading_detection(encoding):
    source = "**自定义标题**\n一、内容\n    嵌套正文\n# 普通文字"
    assert read_document_source(source.encode(encoding), "a.md")[1] == source


@pytest.mark.parametrize("data,filename", [(b"", "a.md"), (b" ", "a.md"), (b"bad", "a.doc"), (b"bad", "a.docx"), (b"\x00binary", "a.md")])
def test_invalid_files(data, filename):
    with pytest.raises(ValueError):
        read_document_source(data, filename)


def test_model_hierarchy_validation_rejects_conflicting_parent_paths():
    result = sample_outline()
    result["slides"][1]["source_path"] = ["其他父节点", "章节"]
    with pytest.raises(ValueError, match="父子关系"):
        validate_document_outline(result)


def test_saving_preserves_model_structure_and_full_original_text():
    outline = sample_outline()
    outline["slides"][1]["content_points"] = ["1. 原文\n  - 子项\n\n| 表头 | 值 |"]
    saved = ProjectOutlineNormalizationService(SimpleNamespace())._standardize_outline_format(outline)
    for original, slide in zip(outline["slides"], saved["slides"]):
        for key in ("source_path", "source_parent_id", "content_points", "chapter"):
            assert slide[key] == original[key]
    project = SimpleNamespace(outline=saved, confirmed_requirements={"creation_mode": DOCUMENT_STRUCTURE_MODE, "document_source_outline": outline})
    restored = get_document_outline(project, restore_source=True)
    assert restored == outline
    restored["title"] = "edited"
    assert outline["title"] == "报告"
