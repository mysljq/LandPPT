from pathlib import Path

import pytest

from landppt.services.image.models import ImageGenerationRequest, ImageProvider
from landppt.services.image.providers.openai_image_provider import OpenAIImageProvider


def test_openai_image_provider_does_not_send_response_format_by_default():
    provider = OpenAIImageProvider(
        {
            "api_key": "test-key",
            "api_base": "https://api.example.test/v1",
            "model": "agnes-t2i-general-model",
        }
    )

    payload = provider._prepare_api_request(
        ImageGenerationRequest(
            prompt="presentation background",
            provider=ImageProvider.OPENAI_IMAGE,
            width=1536,
            height=1024,
            quality="auto",
        )
    )

    assert payload["model"] == "agnes-t2i-general-model"
    assert payload["size"] == "1536x1024"
    assert "response_format" not in payload


def test_openai_image_provider_can_send_response_format_when_configured():
    provider = OpenAIImageProvider(
        {
            "api_key": "test-key",
            "api_base": "https://api.example.test/v1",
            "model": "gpt-image-1",
            "response_format": "b64_json",
        }
    )

    payload = provider._prepare_api_request(
        ImageGenerationRequest(
            prompt="presentation background",
            provider=ImageProvider.OPENAI_IMAGE,
            width=1024,
            height=1024,
        )
    )

    assert payload["response_format"] == "b64_json"


@pytest.mark.asyncio
async def test_openai_image_provider_uses_url_when_b64_json_is_null(monkeypatch):
    provider = OpenAIImageProvider(
        {
            "api_key": "test-key",
            "api_base": "https://api.example.test/v1",
            "model": "agnes-t2i-general-model",
        }
    )
    request = ImageGenerationRequest(
        prompt="presentation background",
        provider=ImageProvider.OPENAI_IMAGE,
        width=1536,
        height=1024,
    )
    downloaded = []

    async def fake_download_image(image_url, download_request):
        downloaded.append((image_url, download_request))
        return Path("temp/test-openai-image.png"), 123

    monkeypatch.setattr(provider, "_download_image", fake_download_image)

    result = await provider._process_api_response(
        {"data": [{"b64_json": None, "url": "https://cdn.example.test/image.png"}]},
        request,
    )

    assert result.success is True
    assert downloaded == [("https://cdn.example.test/image.png", request)]
    assert result.image_info.image_id.startswith("openai_image_")


@pytest.mark.asyncio
async def test_openai_image_provider_reports_no_image_for_empty_payloads():
    provider = OpenAIImageProvider(
        {
            "api_key": "test-key",
            "api_base": "https://api.example.test/v1",
            "model": "agnes-t2i-general-model",
        }
    )

    result = await provider._process_api_response(
        {"data": [{"b64_json": None, "url": None}]},
        ImageGenerationRequest(
            prompt="presentation background",
            provider=ImageProvider.OPENAI_IMAGE,
            width=1536,
            height=1024,
        ),
    )

    assert result.success is False
    assert result.error_code == "no_image"
