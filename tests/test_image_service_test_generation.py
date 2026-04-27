from types import SimpleNamespace

import pytest


class _FakeDbConfigService:
    async def get_config_by_category(self, category, user_id=None):
        assert category == "image_service"
        return {
            "enable_image_service": True,
            "enable_ai_generation": True,
            "default_ai_image_provider": "openai_image",
        }


class _FakeImageConfig:
    async def load_config_from_db_async(self, user_id):
        self.user_id = user_id

    def get_config(self):
        return {
            "openai_image": {
                "api_key": "img-key",
                "default_size": "1536x1024",
                "default_quality": "high",
            },
            "dalle": {
                "api_key": "dalle-key",
                "default_size": "1792x1024",
                "default_quality": "standard",
            },
        }


class _FakeImageService:
    def __init__(self):
        self.reload_user_ids = []
        self.generated_request = None

    async def reload_providers_for_user(self, user_id):
        self.reload_user_ids.append(user_id)

    async def generate_image(self, request):
        self.generated_request = request
        image_info = SimpleNamespace(
            image_id="img-1",
            metadata=SimpleNamespace(width=request.width, height=request.height),
        )
        return SimpleNamespace(
            success=True,
            message="ok",
            image_info=image_info,
            error_code=None,
        )


@pytest.mark.asyncio
async def test_test_generate_image_uses_user_config_and_requested_dimensions(monkeypatch):
    from landppt.api import image_api
    from landppt.auth.request_context import current_base_url
    from landppt.services.image.models import ImageProvider

    fake_service = _FakeImageService()
    monkeypatch.setattr(image_api, "get_db_config_service", lambda: _FakeDbConfigService())
    monkeypatch.setattr(image_api, "ImageServiceConfig", _FakeImageConfig)
    monkeypatch.setattr(image_api, "get_image_service", lambda: fake_service)

    token = current_base_url.set("http://testserver")
    try:
        result = await image_api.test_generate_image(
            image_api.ImageTestGenerateRequest(width=1200, height=675),
            user=SimpleNamespace(id=7),
        )
    finally:
        current_base_url.reset(token)

    assert result["success"] is True
    assert result["image_path"] == "http://testserver/api/image/view/img-1?width=1200px&height=675px"
    assert result["provider"] == "openai_image"
    assert fake_service.reload_user_ids == [7]
    assert fake_service.generated_request.provider == ImageProvider.OPENAI_IMAGE
    assert fake_service.generated_request.width == 1200
    assert fake_service.generated_request.height == 675
    assert fake_service.generated_request.quality == "high"


@pytest.mark.asyncio
async def test_generate_image_accepts_width_height_payload(monkeypatch):
    from landppt.api import image_api
    from landppt.auth.request_context import current_base_url
    from landppt.services.image.models import ImageProvider

    fake_service = _FakeImageService()
    monkeypatch.setattr(image_api, "get_image_service", lambda: fake_service)

    token = current_base_url.set("http://testserver")
    try:
        result = await image_api.generate_image(
            image_api.ImageGenerationRequest(
                prompt="demo",
                provider="openai_image",
                width=1536,
                height=1024,
            ),
            user=SimpleNamespace(id=9),
        )
    finally:
        current_base_url.reset(token)

    assert result["success"] is True
    assert result["image_path"] == "http://testserver/api/image/view/img-1?width=1536px&height=1024px"
    assert fake_service.reload_user_ids == [9]
    assert fake_service.generated_request.provider == ImageProvider.OPENAI_IMAGE
    assert fake_service.generated_request.width == 1536
    assert fake_service.generated_request.height == 1024
