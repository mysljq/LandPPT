"""
Global Master Template Service for managing reusable master templates
"""

import json
import logging
import time
import base64
from typing import Dict, Any, List, Optional
from io import BytesIO

from ..ai import get_ai_provider, get_role_provider, AIMessage, MessageRole
from ..ai.base import TextContent, ImageContent, MessageContentType
from ..core.config import ai_config
from ..database.service import DatabaseService
from ..database.database import AsyncSessionLocal
from .prompts.system_prompts import SystemPrompts

# Configure logger for this module
logger = logging.getLogger(__name__)


class GlobalMasterTemplateService:
    """Service for managing global master templates"""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider_name = provider_name

    @property
    def ai_provider(self):
        """Dynamically get AI provider to ensure latest config"""
        provider, _ = get_role_provider("template", provider_override=self.provider_name)
        return provider

    def _get_template_role_provider(self):
        """Get provider and settings for template generation role"""
        return get_role_provider("template", provider_override=self.provider_name)

    async def _text_completion(self, *, prompt: str, **kwargs):
        provider, settings = self._get_template_role_provider()
        if settings.get("model"):
            kwargs.setdefault("model", settings["model"])
        prompt = SystemPrompts.with_text_cache_prefix(prompt)
        return await provider.text_completion(prompt=prompt, **kwargs)

    async def _chat_completion(self, *, messages: List[AIMessage], **kwargs):
        provider, settings = self._get_template_role_provider()
        if settings.get("model"):
            kwargs.setdefault("model", settings["model"])
        messages = SystemPrompts.normalize_messages_for_cache(messages)
        return await provider.chat_completion(messages=messages, **kwargs)

    async def _stream_text_completion(self, *, prompt: str, **kwargs):
        provider, settings = self._get_template_role_provider()
        if settings.get("model"):
            kwargs.setdefault("model", settings["model"])
        prompt = SystemPrompts.with_text_cache_prefix(prompt)
        if hasattr(provider, 'stream_text_completion'):
            async for chunk in provider.stream_text_completion(prompt=prompt, **kwargs):
                yield chunk
        else:
            response = await provider.text_completion(prompt=prompt, **kwargs)
            yield response.content

    async def _stream_chat_completion(self, *, messages: List[AIMessage], **kwargs):
        provider, settings = self._get_template_role_provider()
        if settings.get("model"):
            kwargs.setdefault("model", settings["model"])
        messages = SystemPrompts.normalize_messages_for_cache(messages)
        if hasattr(provider, 'stream_chat_completion'):
            async for chunk in provider.stream_chat_completion(messages=messages, **kwargs):
                yield chunk
        else:
            response = await provider.chat_completion(messages=messages, **kwargs)
            yield response.content

    async def create_template(self, template_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new global master template"""
        try:
            template_settings = ai_config.get_model_config_for_role("template", provider_override=self.provider_name)
            # Validate required fields
            required_fields = ['template_name', 'html_template']
            for field in required_fields:
                if not template_data.get(field):
                    raise ValueError(f"Missing required field: {field}")

            # Check if template name already exists
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                existing = await db_service.get_global_master_template_by_name(template_data['template_name'])
                if existing:
                    raise ValueError(f"Template name '{template_data['template_name']}' already exists")

            # Generate preview image if not provided
            if not template_data.get('preview_image'):
                template_data['preview_image'] = await self._generate_preview_image(template_data['html_template'])

            # Extract style config if not provided
            if not template_data.get('style_config'):
                template_data['style_config'] = self._extract_style_config(template_data['html_template'])

            # Set default values
            template_data.setdefault('description', '')
            template_data.setdefault('tags', [])
            template_data.setdefault('is_default', False)
            template_data.setdefault('is_active', True)
            template_data.setdefault('created_by', 'system')

            # Create template
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                template = await db_service.create_global_master_template(template_data)

                return {
                    "id": template.id,
                    "template_name": template.template_name,
                    "description": template.description,
                    "preview_image": template.preview_image,
                    "tags": template.tags,
                    "is_default": template.is_default,
                    "is_active": template.is_active,
                    "usage_count": template.usage_count,
                    "created_by": template.created_by,
                    "created_at": template.created_at,
                    "updated_at": template.updated_at
                }

        except Exception as e:
            logger.error(f"Failed to create global master template: {e}")
            raise

    async def get_all_templates(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get all global master templates"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                templates = await db_service.get_all_global_master_templates(active_only)

                return [
                    {
                        "id": template.id,
                        "template_name": template.template_name,
                        "description": template.description,
                        "preview_image": template.preview_image,
                        "tags": template.tags,
                        "is_default": template.is_default,
                        "is_active": template.is_active,
                        "usage_count": template.usage_count,
                        "created_by": template.created_by,
                        "created_at": template.created_at,
                        "updated_at": template.updated_at
                    }
                    for template in templates
                ]

        except Exception as e:
            logger.error(f"Failed to get global master templates: {e}")
            raise

    async def get_all_templates_paginated(
        self,
        active_only: bool = True,
        page: int = 1,
        page_size: int = 6,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get all global master templates with pagination"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)

                # Calculate offset
                offset = (page - 1) * page_size

                # Get templates with pagination
                templates, total_count = await db_service.get_global_master_templates_paginated(
                    active_only=active_only,
                    offset=offset,
                    limit=page_size,
                    search=search
                )

                # Calculate pagination info
                total_pages = (total_count + page_size - 1) // page_size
                has_next = page < total_pages
                has_prev = page > 1

                template_list = [
                    {
                        "id": template.id,
                        "template_name": template.template_name,
                        "description": template.description,
                        "preview_image": template.preview_image,
                        "tags": template.tags,
                        "is_default": template.is_default,
                        "is_active": template.is_active,
                        "usage_count": template.usage_count,
                        "created_by": template.created_by,
                        "created_at": template.created_at,
                        "updated_at": template.updated_at
                    }
                    for template in templates
                ]

                return {
                    "templates": template_list,
                    "pagination": {
                        "current_page": page,
                        "page_size": page_size,
                        "total_count": total_count,
                        "total_pages": total_pages,
                        "has_next": has_next,
                        "has_prev": has_prev
                    }
                }
        except Exception as e:
            logger.error(f"Failed to get paginated templates: {e}")
            raise

    async def get_template_by_id(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Get global master template by ID"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                template = await db_service.get_global_master_template_by_id(template_id)

                if not template:
                    return None

                return {
                    "id": template.id,
                    "template_name": template.template_name,
                    "description": template.description,
                    "html_template": template.html_template,
                    "preview_image": template.preview_image,
                    "style_config": template.style_config,
                    "tags": template.tags,
                    "is_default": template.is_default,
                    "is_active": template.is_active,
                    "usage_count": template.usage_count,
                    "created_by": template.created_by,
                    "created_at": template.created_at,
                    "updated_at": template.updated_at
                }

        except Exception as e:
            logger.error(f"Failed to get global master template {template_id}: {e}")
            raise

    async def update_template(self, template_id: int, update_data: Dict[str, Any]) -> bool:
        """Update a global master template"""
        try:
            # Check if template name conflicts (if being updated)
            if 'template_name' in update_data:
                async with AsyncSessionLocal() as session:
                    db_service = DatabaseService(session)
                    existing = await db_service.get_global_master_template_by_name(update_data['template_name'])
                    if existing and existing.id != template_id:
                        raise ValueError(f"Template name '{update_data['template_name']}' already exists")

            # Update preview image if HTML template is updated
            if 'html_template' in update_data and 'preview_image' not in update_data:
                update_data['preview_image'] = await self._generate_preview_image(update_data['html_template'])

            # Update style config if HTML template is updated
            if 'html_template' in update_data and 'style_config' not in update_data:
                update_data['style_config'] = self._extract_style_config(update_data['html_template'])

            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                return await db_service.update_global_master_template(template_id, update_data)

        except Exception as e:
            logger.error(f"Failed to update global master template {template_id}: {e}")
            raise

    async def delete_template(self, template_id: int) -> bool:
        """Delete a global master template"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)

                # Check if template exists
                template = await db_service.get_global_master_template_by_id(template_id)
                if not template:
                    logger.warning(f"Template {template_id} not found for deletion")
                    return False

                # Check if it's the default template
                if template.is_default:
                    raise ValueError("Cannot delete the default template")

                logger.info(f"Deleting template {template_id}: {template.template_name}")
                result = await db_service.delete_global_master_template(template_id)

                if result:
                    logger.info(f"Successfully deleted template {template_id}")
                else:
                    logger.warning(f"Failed to delete template {template_id} - no rows affected")

                return result

        except Exception as e:
            logger.error(f"Failed to delete global master template {template_id}: {e}")
            raise

    async def set_default_template(self, template_id: int) -> bool:
        """Set a template as default"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                return await db_service.set_default_global_master_template(template_id)

        except Exception as e:
            logger.error(f"Failed to set default template {template_id}: {e}")
            raise

    async def get_default_template(self) -> Optional[Dict[str, Any]]:
        """Get the default template"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                template = await db_service.get_default_global_master_template()

                if not template:
                    return None

                return {
                    "id": template.id,
                    "template_name": template.template_name,
                    "description": template.description,
                    "html_template": template.html_template,
                    "preview_image": template.preview_image,
                    "style_config": template.style_config,
                    "tags": template.tags,
                    "is_default": template.is_default,
                    "is_active": template.is_active,
                    "usage_count": template.usage_count,
                    "created_by": template.created_by,
                    "created_at": template.created_at,
                    "updated_at": template.updated_at
                }

        except Exception as e:
            logger.error(f"Failed to get default template: {e}")
            raise

    async def generate_template_with_ai(self, prompt: str, template_name: str, description: str = "",
                                      tags: List[str] = None, generation_mode: str = "text_only",
                                      reference_image: dict = None):
        """Generate a new template using AI (non-streaming) - does not save to database"""
        import json

        # 构建AI提示词
        if generation_mode == "text_only" or not reference_image:
            # 纯文本生成模式
            ai_prompt = f"""
作为专业的PPT模板设计师，请根据以下要求生成一个HTML母版模板。

请按照以下步骤思考并生成：

1. 首先分析用户需求
2. 设计模板的整体风格和布局
3. 确定色彩方案和字体选择
4. 编写HTML结构
5. 添加CSS样式
6. 优化和完善

用户需求：{prompt}

设计要求：
1. **严格尺寸控制**：页面尺寸必须为1280x720像素（16:9比例）
2. **完整HTML结构**：包含<!DOCTYPE html>、head、body等完整结构
3. **内联样式**：所有CSS样式必须内联，确保自包含性
4. **响应式设计**：适配不同屏幕尺寸但保持16:9比例
5. **占位符支持**：在适当位置使用占位符，如：
   - {{{{ page_title }}}} - 页面标题，默认居左
   - {{{{ page_content }}}} - 页面内容
   - {{{{ current_page_number }}}} - 当前页码
   - {{{{ total_page_count }}}} - 总页数
6. **技术要求**：
   - 使用Tailwind CSS或内联CSS
   - 支持Font Awesome图标
   - 支持Chart.js、ECharts.js、D3.js等图表库
   - 确保所有内容在720px高度内完全显示
   - 绝对不允许出现任何滚动条

请详细说明你的设计思路，然后生成完整的HTML模板代码，使用```html代码块格式返回。
"""
            messages = [{"role": "user", "content": ai_prompt}]
        else:
            # 多模态生成模式
            if generation_mode == "reference_style":
                mode_instruction = """
请参考上传的图片风格，借鉴其设计元素、色彩搭配、布局结构等，但不需要完全复制。
重点关注：
- 色彩方案和配色理念
- 设计风格和视觉元素
- 布局结构和空间安排
- 字体选择和排版风格
"""
            else:  # one_to_one
                mode_instruction = """
请尽可能准确地复制上传图片的设计，包括：
- 精确的布局结构
- 相同的色彩搭配
- 类似的视觉元素
- 相近的字体和排版
- 整体的设计风格
"""

            ai_prompt = f"""
作为专业的PPT模板设计师，请根据参考图片和以下要求生成一个HTML母版模板。

{mode_instruction}

用户需求：{prompt}

设计要求：
1. **严格尺寸控制**：页面尺寸必须为1280x720像素（16:9比例）
2. **完整HTML结构**：包含<!DOCTYPE html>、head、body等完整结构
3. **内联样式**：所有CSS样式必须内联，确保自包含性
4. **响应式设计**：适配不同屏幕尺寸但保持16:9比例
5. **占位符支持**：在适当位置使用占位符，如：
   - {{{{ page_title }}}} - 页面标题，默认居左
   - {{{{ page_content }}}} - 页面内容
   - {{{{ current_page_number }}}} - 当前页码
   - {{{{ total_page_count }}}} - 总页数
6. **技术要求**：
   - 使用Tailwind CSS或内联CSS
   - 支持Font Awesome图标
   - 支持Chart.js、ECharts.js、D3.js等图表库
   - 确保所有内容在720px高度内完全显示
   - 绝对不允许出现任何滚动条

请详细说明你的设计思路，然后生成完整的HTML模板代码，使用```html代码块格式返回。
"""

            # 构建多模态消息
            # 确保图片URL格式正确
            image_data = reference_image['data']
            if not image_data.startswith("data:"):
                # 如果是纯base64数据,添加data URL前缀
                image_data = f"data:{reference_image['type']};base64,{image_data}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ai_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data
                            }
                        }
                    ]
                }
            ]

        try:
            # 获取模板生成任务的配置
            provider, template_settings = self._get_template_role_provider()

            if not provider:
                raise ValueError("AI服务未配置或不可用")

            # 转换消息格式
            ai_messages = []
            for msg in messages:
                if isinstance(msg["content"], str):
                    # 纯文本消息
                    ai_messages.append(AIMessage(
                        role=MessageRole.USER,
                        content=[TextContent(text=msg["content"])]
                    ))
                else:
                    # 多模态消息
                    content_parts = []
                    for part in msg["content"]:
                        if part["type"] == "text":
                            content_parts.append(TextContent(text=part["text"]))
                        elif part["type"] == "image_url":
                            # 提取图片URL (已经是完整的data URL格式)
                            image_url = part["image_url"]["url"]
                            if image_url.startswith("data:"):
                                content_parts.append(ImageContent(
                                    image_url={"url": image_url},
                                    content_type=MessageContentType.IMAGE_URL
                                ))
                    ai_messages.append(AIMessage(
                        role=MessageRole.USER,
                        content=content_parts
                    ))

            # 重试逻辑：最多尝试5次
            max_retries = 5
            full_response = None
            html_template = None

            for attempt in range(max_retries):
                try:
                    logger.info(f"AI generation attempt {attempt + 1}/{max_retries}")
                    # 使用配置的模型进行生成
                    ai_response = await self._chat_completion(
                        messages=ai_messages,
                        model=template_settings.get('model')
                    )
                    full_response = ai_response.content

                    logger.info(f"AI response length: {len(full_response)}")

                    # 检查响应是否为空或过短
                    if not full_response or not full_response.strip():
                        logger.warning(f"Attempt {attempt + 1}: Empty response")
                        if attempt < max_retries - 1:
                            logger.info(f"Retrying due to empty response... ({attempt + 2}/{max_retries})")
                            continue
                        else:
                            logger.error("All retries exhausted, received empty response")
                            raise ValueError("AI服务返回空响应")

                    if len(full_response) < 2000:
                        logger.warning(f"Attempt {attempt + 1}: Response too short ({len(full_response)} chars)")
                        if attempt < max_retries - 1:  # 不是最后一次尝试
                            logger.info(f"Retrying due to short response... ({attempt + 2}/{max_retries})")
                            continue
                        else:
                            logger.warning("All retries exhausted, proceeding with short response")

                    # 提取HTML模板
                    html_template = self._extract_html_from_response(full_response)

                    if not html_template or not html_template.strip():
                        logger.warning(f"Attempt {attempt + 1}: Failed to extract HTML template")
                        if attempt < max_retries - 1:
                            logger.info(f"Retrying due to extraction failure... ({attempt + 2}/{max_retries})")
                            continue
                        else:
                            logger.error("All retries exhausted, failed to extract HTML template")
                            raise ValueError("AI响应中未找到有效的HTML模板")

                    logger.info(f"Extracted HTML template length: {len(html_template)}")

                    # 验证HTML模板
                    if not self._validate_html_template(html_template):
                        logger.warning(f"Attempt {attempt + 1}: HTML template validation failed")
                        if attempt < max_retries - 1:
                            logger.info(f"Retrying due to validation failure... ({attempt + 2}/{max_retries})")
                            continue
                        else:
                            logger.error("All retries exhausted, HTML template validation failed")
                            raise ValueError("生成的HTML模板验证失败")

                    # 成功生成有效模板
                    logger.info(f"Successfully generated valid HTML template on attempt {attempt + 1}")
                    break

                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed: {e}")
                        logger.info(f"Retrying... ({attempt + 2}/{max_retries})")
                        continue
                    else:
                        logger.error(f"All {max_retries} attempts failed")
                        raise

            if not html_template:
                raise ValueError("Failed to generate valid HTML template after all retries")

            # 返回结果（不保存到数据库）
            return {
                'html_template': html_template,
                'template_name': template_name,
                'description': description or f"AI生成的模板：{prompt[:100]}",
                'tags': tags or ['AI生成'],
                'llm_response': full_response  # 包含完整的LLM响应
            }

        except Exception as e:
            logger.error(f"Failed to generate template with AI: {e}", exc_info=True)
            raise

    async def generate_template_with_ai_stream(self, prompt: str, template_name: str, description: str = "",
                                             tags: List[str] = None, generation_mode: str = "text_only",
                                             reference_image: dict = None):
        """Generate a new template using AI with streaming response"""
        import asyncio
        import json

        # 构建AI提示词
        if generation_mode == "text_only" or not reference_image:
            # 纯文本生成模式
            ai_prompt = f"""
作为专业的PPT模板设计师，请根据以下要求生成一个HTML母版模板。

请按照以下步骤思考并生成：

1. 首先分析用户需求
2. 设计模板的整体风格和布局
3. 确定色彩方案和字体选择
4. 编写HTML结构
5. 添加CSS样式
6. 优化和完善

用户需求：{prompt}

设计要求：
1. **严格尺寸控制**：页面尺寸必须为1280x720像素（16:9比例）
2. **完整HTML结构**：包含<!DOCTYPE html>、head、body等完整结构
3. **内联样式**：所有CSS样式必须内联，确保自包含性
4. **响应式设计**：适配不同屏幕尺寸但保持16:9比例
5. **占位符支持**：在适当位置使用占位符，如：
   - {{{{ page_title }}}} - 页面标题，默认居左
   - {{{{ page_content }}}} - 页面内容
   - {{{{ current_page_number }}}} - 当前页码
   - {{{{ total_page_count }}}} - 总页数
6. **技术要求**：
   - 使用Tailwind CSS或内联CSS
   - 支持Font Awesome图标
   - 支持Chart.js、ECharts.js、D3.js等图表库
   - 确保所有内容在720px高度内完全显示
   - 绝对不允许出现任何滚动条

请详细说明你的设计思路，然后生成完整的HTML模板代码，使用```html代码块格式返回。
"""
        else:
            # 多模态生成模式
            if generation_mode == "reference_style":
                mode_instruction = """
**生成模式：参考风格**
请分析参考图片的设计风格、色彩搭配、布局结构等视觉元素，并将这些设计理念融入到PPT模板中。
不需要完全复制图片内容，而是借鉴其设计精髓来创建符合用户需求的模板。
"""
            else:  # exact_replica
                mode_instruction = """
**生成模式：1:1还原**
请尽可能准确地分析和复制参考图片的设计，包括：
- 布局结构和元素位置
- 色彩方案和渐变效果
- 字体样式和排版
- 装饰元素和图形
- 整体视觉风格
在保持PPT模板功能性的前提下，最大程度还原图片的设计。
"""

            ai_prompt = f"""
作为专业的PPT模板设计师，请根据参考图片和用户要求生成一个HTML母版模板。

{mode_instruction}

用户需求：{prompt}

请按照以下步骤分析和生成：

1. **图片分析**：详细分析参考图片的设计元素
   - 整体布局和结构
   - 色彩方案和配色
   - 字体和排版风格
   - 装饰元素和图形
   - 视觉层次和重点

2. **设计适配**：将图片设计适配为PPT模板
   - 保持设计风格的一致性
   - 适配16:9的PPT比例
   - 确保内容区域的可用性
   - 添加必要的占位符

3. **技术实现**：编写HTML和CSS代码

设计要求：
1. **严格尺寸控制**：页面尺寸必须为1280x720像素（16:9比例）
2. **完整HTML结构**：包含<!DOCTYPE html>、head、body等完整结构
3. **内联样式**：所有CSS样式必须内联，确保自包含性
4. **响应式设计**：适配不同屏幕尺寸但保持16:9比例
5. **占位符支持**：在适当位置使用占位符，如：
   - {{{{ page_title }}}} - 页面标题，默认居左
   - {{{{ page_content }}}} - 页面内容
   - {{{{ current_page_number }}}} - 当前页码
   - {{{{ total_page_count }}}} - 总页数
6. **技术要求**：
   - 使用Tailwind CSS或内联CSS
   - 支持Font Awesome图标
   - 支持Chart.js、ECharts.js、D3.js等图表库
   - 确保所有内容在720px高度内完全显示
   - 绝对不允许出现任何滚动条

请详细说明你的分析过程和设计思路，然后生成完整的HTML模板代码，使用```html代码块格式返回。
"""

        try:
            # 获取模板生成任务的配置
            provider, template_settings = self._get_template_role_provider()

            # 构建AI消息
            if generation_mode != "text_only" and reference_image:
                # 多模态消息
                # 确保图片URL格式正确 (OpenAI需要完整的data URL格式)
                image_url = reference_image["data"]
                if not image_url.startswith("data:"):
                    # 如果是纯base64数据,添加data URL前缀
                    image_type = reference_image.get("type", "image/png")
                    image_url = f"data:{image_type};base64,{image_url}"

                content_parts = [
                    TextContent(text=ai_prompt),
                    ImageContent(image_url={"url": image_url})
                ]
                messages = [AIMessage(role=MessageRole.USER, content=content_parts)]

                # 检查AI提供商是否支持流式聊天
                if hasattr(provider, 'stream_chat_completion'):
                    # 使用流式聊天API
                    full_response = ""
                    async for chunk in provider.stream_chat_completion(
                        messages=messages,
                        max_tokens=ai_config.max_tokens,
                        temperature=0.7,
                        model=template_settings.get('model')
                    ):
                        full_response += chunk
                        yield {
                            'type': 'thinking',
                            'content': chunk
                        }
                else:
                    # 使用标准聊天API
                    response = await self._chat_completion(
                        messages=messages,
                        max_tokens=ai_config.max_tokens,
                        temperature=0.7
                    )
                    full_response = response.content

                    # 模拟流式输出
                    yield {'type': 'thinking', 'content': '🖼️ 正在分析参考图片...\n\n'}
                    await asyncio.sleep(1)
                    yield {'type': 'thinking', 'content': full_response}
            else:
                # 纯文本消息
                if hasattr(provider, 'stream_text_completion'):
                    # 使用流式API
                    full_response = ""
                    async for chunk in provider.stream_text_completion(
                        prompt=ai_prompt,
                        max_tokens=ai_config.max_tokens,
                        temperature=0.7,
                        model=template_settings.get('model')
                    ):
                        full_response += chunk
                        yield {
                            'type': 'thinking',
                            'content': chunk
                        }
                else:
                    # 使用标准文本完成API
                    response = await provider.text_completion(
                        prompt=ai_prompt,
                        max_tokens=ai_config.max_tokens,
                        temperature=0.7,
                        model=template_settings.get('model')
                    )
                    full_response = response.content

                    # 模拟流式输出
                    yield {'type': 'thinking', 'content': '🤔 正在分析您的需求...\n\n'}
                    await asyncio.sleep(1)
                    yield {'type': 'thinking', 'content': full_response}

                # 流式完成后，处理完整响应
                yield {'type': 'thinking', 'content': '\n\n✨ 优化样式和交互效果...\n'}
                await asyncio.sleep(0.5)

                # 处理AI响应
                html_template = self._extract_html_from_response(full_response)

                if not self._validate_html_template(html_template):
                    raise ValueError("Generated HTML template is invalid")

                yield {'type': 'thinking', 'content': '✅ 模板生成完成，准备预览...\n'}
                await asyncio.sleep(0.3)

                # 返回生成完成的信息，包含HTML模板用于预览
                yield {
                    'type': 'complete',
                    'message': '模板生成完成！',
                    'html_template': html_template,
                    'template_name': template_name,
                    'description': description or f"AI生成的模板：{prompt[:100]}",
                    'tags': tags or ['AI生成'],
                    'llm_response': full_response  # 添加完整的LLM响应
                }

        except Exception as e:
            logger.error(f"Failed to generate template with AI stream: {e}", exc_info=True)
            yield {
                'type': 'error',
                'message': str(e)
            }

    async def adjust_template_with_ai_stream(self, current_html: str, adjustment_request: str, template_name: str = "模板"):
        """Adjust an existing template based on user feedback with streaming response"""
        import asyncio

        # 构建调整提示词
        ai_prompt = f"""
作为专业的PPT模板设计师，请根据用户的调整需求修改现有的HTML模板。

当前模板：
```html
{current_html}
```

用户调整需求：{adjustment_request}

请按照以下要求进行调整：
1. **保持原有结构**：尽量保持原有的基本布局和结构
2. **精确调整**：只修改用户明确要求调整的部分
3. **保持占位符**：确保保留所有占位符（如 {{{{ page_title }}}}、{{{{ page_content }}}} 等）
4. **完整HTML**：返回完整的HTML代码，包含所有必要的样式和结构
5. **16:9比例**：确保页面尺寸保持1280x720像素的16:9比例

请详细说明你的调整思路，然后生成完整的调整后HTML模板代码，使用```html代码块格式返回。
"""

        try:
            # 获取模板生成任务的配置
            provider, template_settings = self._get_template_role_provider()

            # 检查AI提供商是否支持流式响应
            if hasattr(provider, 'stream_text_completion'):
                # 使用流式API
                full_response = ""
                async for chunk in provider.stream_text_completion(
                    prompt=ai_prompt,
                    max_tokens=ai_config.max_tokens,
                    temperature=0.7,
                    model=template_settings.get('model')
                ):
                    full_response += chunk
                    yield {
                        'type': 'thinking',
                        'content': chunk
                    }

                # 流式完成后,处理完整响应
                yield {'type': 'thinking', 'content': '\n\n✨ 完成模板调整...\n'}
                await asyncio.sleep(0.5)

                # 处理AI响应
                html_template = self._extract_html_from_response(full_response)

                if not self._validate_html_template(html_template):
                    raise ValueError("Adjusted HTML template is invalid")

                # 返回调整完成的信息
                yield {
                    'type': 'complete',
                    'message': '模板调整完成！',
                    'html_template': html_template,
                    'template_name': template_name
                }

            else:
                # 模拟流式响应
                yield {'type': 'thinking', 'content': '🔄 正在分析调整需求...\n\n'}
                await asyncio.sleep(1)

                yield {'type': 'thinking', 'content': f'调整需求：{adjustment_request}\n\n'}
                await asyncio.sleep(0.5)

                yield {'type': 'thinking', 'content': '🎨 开始调整模板...\n'}
                await asyncio.sleep(1)

                # 调用标准AI生成
                response = await provider.text_completion(
                    prompt=ai_prompt,
                    max_tokens=ai_config.max_tokens,
                    temperature=0.7,
                    model=template_settings.get('model')
                )

                yield {'type': 'thinking', 'content': '✨ 完成模板调整...\n'}
                await asyncio.sleep(0.5)

                # 处理AI响应
                html_template = self._extract_html_from_response(response.content)

                if not self._validate_html_template(html_template):
                    raise ValueError("Adjusted HTML template is invalid")

                # 返回调整完成的信息
                yield {
                    'type': 'complete',
                    'message': '模板调整完成！',
                    'html_template': html_template,
                    'template_name': template_name
                }

        except Exception as e:
            logger.error(f"Failed to adjust template with AI stream: {e}", exc_info=True)
            yield {
                'type': 'error',
                'message': str(e)
            }



    def _extract_html_from_response(self, response_content: str) -> str:
        """Extract HTML code from AI response with improved extraction"""
        import re

        logger.info(f"Extracting HTML from response. Content length: {len(response_content)}")

        # Try to extract HTML code block (most common format)
        html_match = re.search(r'```html\s*(.*?)\s*```', response_content, re.DOTALL)
        if html_match:
            extracted = html_match.group(1).strip()
            logger.info(f"Extracted HTML from code block. Length: {len(extracted)}")
            return extracted

        # Try to extract any code block that contains DOCTYPE
        code_block_match = re.search(r'```[a-zA-Z]*\s*(<!DOCTYPE html.*?</html>)\s*```', response_content, re.DOTALL | re.IGNORECASE)
        if code_block_match:
            extracted = code_block_match.group(1).strip()
            logger.info(f"Extracted HTML from generic code block. Length: {len(extracted)}")
            return extracted

        # Try to extract DOCTYPE HTML directly
        doctype_match = re.search(r'<!DOCTYPE html.*?</html>', response_content, re.DOTALL | re.IGNORECASE)
        if doctype_match:
            extracted = doctype_match.group(0).strip()
            logger.info(f"Extracted HTML from direct match. Length: {len(extracted)}")
            return extracted

        # If no specific pattern found, check if the content itself is HTML
        content_stripped = response_content.strip()
        if content_stripped.lower().startswith('<!doctype html') and content_stripped.lower().endswith('</html>'):
            logger.info(f"Content appears to be direct HTML. Length: {len(content_stripped)}")
            return content_stripped

        # Return original content as last resort
        logger.warning(f"Could not extract HTML from response, returning original content. Preview: {response_content[:200]}")
        return response_content.strip()

    def _validate_html_template(self, html_content: str) -> bool:
        """Validate HTML template with improved error reporting"""
        try:
            if not html_content or not html_content.strip():
                logger.error("HTML validation failed: Content is empty")
                return False

            html_lower = html_content.lower().strip()

            # Check basic HTML structure with more flexible validation
            if not html_lower.startswith('<!doctype html'):
                logger.error(f"HTML validation failed: Missing or incorrect DOCTYPE. Content starts with: {html_content[:100]}")
                return False

            if '</html>' not in html_lower:
                logger.error("HTML validation failed: Missing closing </html> tag")
                return False

            # Check required elements with better error reporting
            required_elements = {
                '<head>': '<head',
                '<body>': '<body',
                '<title>': '<title'
            }
            missing_elements = []

            for element_name, element_pattern in required_elements.items():
                if element_pattern not in html_lower:
                    missing_elements.append(element_name)

            if missing_elements:
                logger.error(f"HTML validation failed: Missing required elements: {missing_elements}")
                return False

            logger.info("HTML template validation passed successfully")
            return True

        except Exception as e:
            logger.error(f"HTML validation failed with exception: {e}")
            return False

    async def _generate_preview_image(self, html_template: str) -> str:
        """Generate preview image for template (placeholder implementation)"""
        # This is a placeholder implementation
        placeholder_svg = """
        <svg width="320" height="180" xmlns="http://www.w3.org/2000/svg">
            <rect width="320" height="180" fill="#f3f4f6"/>
            <text x="160" y="90" text-anchor="middle" font-family="Arial" font-size="14" fill="#6b7280">
                模板预览
            </text>
        </svg>
        """
        return f"data:image/svg+xml;base64,{base64.b64encode(placeholder_svg.encode()).decode()}"

    def _extract_style_config(self, html_content: str) -> Dict[str, Any]:
        """Extract style configuration from HTML"""
        import re

        style_config = {
            "dimensions": "1280x720",
            "aspect_ratio": "16:9",
            "framework": "HTML + CSS"
        }

        try:
            # Extract color configuration
            color_matches = re.findall(r'(?:background|color)[^:]*:\s*([^;]+)', html_content, re.IGNORECASE)
            if color_matches:
                style_config["colors"] = list(set(color_matches[:10]))  # Limit to 10 colors

            # Extract font configuration
            font_matches = re.findall(r'font-family[^:]*:\s*([^;]+)', html_content, re.IGNORECASE)
            if font_matches:
                style_config["fonts"] = list(set(font_matches[:5]))  # Limit to 5 fonts

            # Check for frameworks
            if 'tailwind' in html_content.lower():
                style_config["framework"] = "Tailwind CSS"
            elif 'bootstrap' in html_content.lower():
                style_config["framework"] = "Bootstrap"

        except Exception as e:
            logger.warning(f"Failed to extract style config: {e}")

        return style_config

    async def get_templates_by_tags(self, tags: List[str], active_only: bool = True) -> List[Dict[str, Any]]:
        """Get global master templates by tags"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                templates = await db_service.get_global_master_templates_by_tags(tags, active_only)

                return [
                    {
                        "id": template.id,
                        "template_name": template.template_name,
                        "description": template.description,
                        "preview_image": template.preview_image,
                        "tags": template.tags,
                        "is_default": template.is_default,
                        "is_active": template.is_active,
                        "usage_count": template.usage_count,
                        "created_by": template.created_by,
                        "created_at": template.created_at,
                        "updated_at": template.updated_at
                    }
                    for template in templates
                ]

        except Exception as e:
            logger.error(f"Failed to get global master templates by tags: {e}")
            raise

    async def get_templates_by_tags_paginated(
        self,
        tags: List[str],
        active_only: bool = True,
        page: int = 1,
        page_size: int = 6,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get global master templates by tags with pagination"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)

                # Calculate offset
                offset = (page - 1) * page_size

                # Get templates with pagination
                templates, total_count = await db_service.get_global_master_templates_by_tags_paginated(
                    tags=tags,
                    active_only=active_only,
                    offset=offset,
                    limit=page_size,
                    search=search
                )

                # Calculate pagination info
                total_pages = (total_count + page_size - 1) // page_size
                has_next = page < total_pages
                has_prev = page > 1

                template_list = [
                    {
                        "id": template.id,
                        "template_name": template.template_name,
                        "description": template.description,
                        "preview_image": template.preview_image,
                        "tags": template.tags,
                        "is_default": template.is_default,
                        "is_active": template.is_active,
                        "usage_count": template.usage_count,
                        "created_by": template.created_by,
                        "created_at": template.created_at,
                        "updated_at": template.updated_at
                    }
                    for template in templates
                ]

                return {
                    "templates": template_list,
                    "pagination": {
                        "current_page": page,
                        "page_size": page_size,
                        "total_count": total_count,
                        "total_pages": total_pages,
                        "has_next": has_next,
                        "has_prev": has_prev
                    }
                }
        except Exception as e:
            logger.error(f"Failed to get paginated templates by tags: {e}")
            raise

    async def increment_template_usage(self, template_id: int) -> bool:
        """Increment template usage count"""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                return await db_service.increment_global_master_template_usage(template_id)

        except Exception as e:
            logger.error(f"Failed to increment template usage {template_id}: {e}")
            raise
