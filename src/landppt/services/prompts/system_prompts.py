"""
PPT系统提示词和默认配置
包含所有系统级别的提示词和默认配置
"""

import os
from pathlib import Path


class SystemPrompts:
    """PPT系统提示词和默认配置集合"""

    CACHE_STABLE_PREFIX = """
角色：演示文稿规划、内容与 HTML 幻灯片生成助手。
稳定原则：
- 事实准确、结构清晰、输出格式可解析。
- 项目主题、页数、语言、模板、图片等变量只来自用户消息，不在系统层臆造。
- 生成 HTML 时遵守固定画布、资源可达性和性能约束。
- 若任务要求 JSON 或 HTML，只输出指定格式，不附加解释。"""

    @staticmethod
    def with_cache_prefix(task_prompt: str) -> str:
        """给系统提示词添加稳定前缀，提高多次调用的KV cache命中率。"""
        task_prompt = (task_prompt or "").strip()
        prefix = SystemPrompts.CACHE_STABLE_PREFIX.strip()
        if not task_prompt:
            return prefix
        if task_prompt.startswith(prefix):
            return task_prompt
        return f"{prefix}\n\n{task_prompt}"

    @staticmethod
    def with_text_cache_prefix(prompt: str) -> str:
        """给纯文本补全 prompt 添加稳定前缀，减少分散调用的首段差异。"""
        return SystemPrompts.with_cache_prefix(prompt)

    @staticmethod
    def normalize_messages_for_cache(messages):
        """确保聊天补全的首条 system 消息具备稳定前缀。"""
        from ...ai import AIMessage, MessageRole

        normalized = list(messages or [])
        if not normalized:
            return [AIMessage(role=MessageRole.SYSTEM, content=SystemPrompts.CACHE_STABLE_PREFIX.strip())]

        first = normalized[0]
        if first.role == MessageRole.SYSTEM and isinstance(first.content, str):
            normalized[0] = AIMessage(
                role=first.role,
                content=SystemPrompts.with_cache_prefix(first.content),
                name=first.name,
            )
            return normalized

        normalized.insert(0, AIMessage(
            role=MessageRole.SYSTEM,
            content=SystemPrompts.CACHE_STABLE_PREFIX.strip(),
        ))
        return normalized

    @staticmethod
    def get_resource_performance_prompt() -> str:
        """获取资源可达性与性能优化约束提示词"""
        return """**资源可达性与性能约束**：
- 不要引入海外公共 CDN 资源（`fonts.googleapis.com`、`fonts.gstatic.com`、`cdn.jsdelivr.net`、`unpkg.com`、`cdnjs.cloudflare.com`、`use.fontawesome.com` 等）。
- 不要通过海外外链加载字体（如 Google Fonts、Adobe Fonts），字体选择不受限制，但引入方式不能依赖海外域名。
- 图标少量场景优先内联 SVG / CSS / Unicode，不要为少量图标引入整套远程图标库。
- 图表可用 Chart.js、ECharts.js、D3.js，公式可用 MathJax，代码高亮可用 Prism.js；仅在确有需要时按需加载，并关闭非必要动画和重复初始化。
- 背景纹理、分隔线、装饰光效优先 CSS 或内联 SVG 实现；能不引入外链就不引入。"""
    
    @staticmethod
    def get_default_ppt_system_prompt() -> str:
        """获取默认PPT生成系统提示词"""
        return SystemPrompts.with_cache_prefix(
            "根据幻灯片内容生成高质量 HTML 页面。设计服务于内容表达，保持视觉层级清晰和整体风格统一。\n\n"
            + SystemPrompts.get_resource_performance_prompt())

    @staticmethod
    def get_keynote_style_prompt() -> str:
        """获取Keynote风格提示词"""
        return SystemPrompts.with_cache_prefix("""请生成Apple风格的发布会PPT页面，具有以下特点：
1. 黑色背景，简洁现代的设计
2. 卡片式布局，突出重点信息
3. 使用科技蓝或品牌色作为高亮色
4. 大字号标题，清晰的视觉层级
5. 响应式设计，支持多设备显示
6. 图标优先使用内联SVG或简洁几何图形，图表优先使用纯HTML/CSS/SVG实现
7. 平滑的动画效果

特别注意：
- **结尾页（thankyou/conclusion类型）**：必须设计得令人印象深刻！使用Apple风格的特殊背景效果、发光文字、动态装饰、庆祝元素等，留下深刻的最后印象

""" + SystemPrompts.get_resource_performance_prompt())

    @staticmethod
    def load_prompts_md_system_prompt() -> str:
        """加载prompts.md系统提示词"""
        try:
            # 获取当前文件的目录
            current_dir = Path(__file__).parent
            # 构建prompts.md的路径
            prompts_file = current_dir / "prompts.md"
            
            if prompts_file.exists():
                with open(prompts_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                return SystemPrompts.with_cache_prefix(content)
            else:
                # 如果文件不存在，返回默认提示词
                return SystemPrompts.get_default_ppt_system_prompt()
        except Exception as e:
            # 如果读取失败，返回默认提示词
            return SystemPrompts.get_default_ppt_system_prompt()

    @staticmethod
    def get_ai_assistant_system_prompt() -> str:
        """获取AI助手系统提示词"""
        return SystemPrompts.with_cache_prefix(
            "PPT 制作助手。理解用户需求与受众，设计清晰信息架构，"
            "保持视觉风格统一，生成高质量 HTML/CSS 代码.")

    @staticmethod
    def get_html_generation_system_prompt() -> str:
        """获取HTML生成系统提示词"""
        return SystemPrompts.with_cache_prefix(
            "生成 PPT 页面的 HTML 代码。使用语义化 HTML 和现代 CSS（Flexbox/Grid），"
            "保证代码质量和加载性能。\n\n"
            + SystemPrompts.get_resource_performance_prompt())

    @staticmethod
    def get_content_analysis_system_prompt() -> str:
        """获取内容分析系统提示词"""
        return SystemPrompts.with_cache_prefix(
            "分析和优化 PPT 内容。关注信息结构完整性、语言准确性、"
            "每页信息密度、受众适配和可视化机会.")

    @staticmethod
    def get_custom_style_prompt(custom_prompt: str) -> str:
        """获取自定义风格提示词"""
        return SystemPrompts.with_cache_prefix(f"""
                请根据以下自定义风格要求生成PPT页面：

                {custom_prompt}

                请确保生成的HTML页面符合上述风格要求，同时保持良好的可读性和用户体验。
                """)
