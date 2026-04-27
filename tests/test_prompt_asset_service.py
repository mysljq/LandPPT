import base64

import pytest

from landppt.services.prompt_asset_service import (
    materialize_base64_image_data_urls_for_prompt,
    strip_base64_image_payloads_for_prompt,
)
from landppt.services.prompts.design_prompts import DesignPrompts


def test_strip_base64_image_payloads_for_prompt_removes_payload():
    payload = base64.b64encode(b"large-image-bytes").decode("ascii")
    html = f'<div style="background:url(data:image/png;base64,{payload})"></div>'

    sanitized = strip_base64_image_payloads_for_prompt(html)

    assert payload not in sanitized
    assert "data:image/png;base64," not in sanitized
    assert "image/png" in sanitized


def test_creative_template_prompt_strips_template_image_payloads():
    payload = base64.b64encode(b"template-image-bytes").decode("ascii")
    template_html = f'<img src="data:image/svg+xml;base64,{payload}">'

    prompt = DesignPrompts.get_creative_template_context_prompt(
        slide_data={"title": "实验设计与结果分析", "content_points": ["指标验证"]},
        template_html=template_html,
        slide_title="实验设计与结果分析",
        slide_type="content",
        page_number=7,
        total_pages=9,
        context_info="context",
        style_genes="style",
    )

    assert payload not in prompt
    assert "data:image/svg+xml;base64," not in prompt
    assert "image/svg+xml" in prompt


@pytest.mark.asyncio
async def test_materialize_base64_image_data_urls_uses_hosted_urls():
    png_payload = base64.b64encode(b"png-bytes").decode("ascii")
    jpg_payload = base64.b64encode(b"jpg-bytes").decode("ascii")
    html = (
        f'<img src="data:image/png;base64,{png_payload}">'
        f"<style>.hero{{background-image:url(data:image/jpeg;base64,{jpg_payload})}}</style>"
    )

    calls = []

    async def fake_upload(image_bytes: bytes, mime_type: str, index: int):
        calls.append((image_bytes, mime_type, index))
        return f"https://assets.example.test/{index}"

    sanitized = await materialize_base64_image_data_urls_for_prompt(
        html,
        upload_func=fake_upload,
    )

    assert sanitized == (
        '<img src="https://assets.example.test/1">'
        "<style>.hero{background-image:url(https://assets.example.test/2)}</style>"
    )
    assert "base64," not in sanitized
    assert calls == [
        (b"png-bytes", "image/png", 1),
        (b"jpg-bytes", "image/jpeg", 2),
    ]
