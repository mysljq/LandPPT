import asyncio
import json

from landppt.ai.base import AIMessage, AIResponse, MessageRole
from landppt.services.models.slide_image_info import ImageSource
from landppt.services.ppt_image_processor import PPTImageProcessor
from landppt.services.prompts.system_prompts import SystemPrompts


def test_system_prompt_cache_prefix_is_stable_for_chat_messages():
    messages = [AIMessage(role=MessageRole.USER, content="生成一页PPT")]

    normalized = SystemPrompts.normalize_messages_for_cache(messages)

    assert normalized[0].role == MessageRole.SYSTEM
    assert normalized[0].content.startswith("LandPPT 系统提示词 v2")
    assert normalized[1:] == messages


def test_image_requirement_planning_carries_prompt_dimensions_and_keywords():
    async def run_case():
        processor = PPTImageProcessor()

        async def fake_text_completion(**_kwargs):
            payload = {
                "needs_images": True,
                "total_images": 1,
                "requirements": [
                    {
                        "source": "ai_generated",
                        "count": 1,
                        "purpose": "illustration",
                        "description": "产品架构示意图",
                        "priority": 3,
                        "search_keywords": "产品 架构 示意图",
                        "width": 1792,
                        "height": 1024,
                        "generation_prompts": [
                            "Clean professional product architecture illustration, no text, no watermark"
                        ],
                    }
                ],
                "reasoning": "需要一张架构图辅助理解",
            }
            return AIResponse(
                content=json.dumps(payload, ensure_ascii=False),
                model="fake",
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )

        processor._text_completion = fake_text_completion
        requirements = await processor._ai_analyze_image_requirements(
            {"title": "产品架构", "content_points": ["模块分层", "数据流转"]},
            "智能平台",
            "technology",
            3,
            10,
            enabled_sources=[ImageSource.AI_GENERATED],
            image_config={
                "max_total_images_per_slide": 1,
                "max_ai_images_per_slide": 1,
                "default_ai_image_provider": "dalle",
            },
        )

        requirement = requirements.requirements[0]
        assert requirement.source == ImageSource.AI_GENERATED
        assert requirement.width == 1792
        assert requirement.height == 1024
        assert requirement.search_keywords == "产品 架构 示意图"
        assert requirement.generation_prompts == [
            "Clean professional product architecture illustration, no text, no watermark"
        ]

    asyncio.run(run_case())
