"""
模板生成相关提示词

职责：
- 集中维护 HTML PPT 母版生成的通用约束
- 组装自由模板的项目专属上下文
"""

from typing import Any, Dict, List

from .system_prompts import SystemPrompts


class TemplatePrompts:
    """模板生成提示词构建器。"""

    # header_footer 片段必须自带的全局 reset 与画布约束。
    # build_template_suite_prompt 是 f-string，直接写 CSS 花括号会被当作表达式求值，
    # 故抽成常量引用。内容页骨架是内层片段，若不自带这些规则，body 默认 8px margin
    # 会把 1280×720 撑到 1296×736、出现滚动条（套件库 id=14 事故）。
    HF_RESET_CSS = "*{margin:0;padding:0;box-sizing:border-box}"
    HF_CANVAS_RULE = "html,body{width:1280px;height:720px;margin:0;overflow:hidden}"
    # A2 标准内容舞台容器——度量与约束 prompt 共同锚定 .suite-stage。
    # 固定 px 边界、overflow:hidden 兜住溢出；top 避开页头底边（实测可达 135px，
    # 统一 155px 留安全间距）、bottom 不压页脚。
    HF_STAGE_RULE = (
        ".suite-stage{position:absolute;top:155px;left:60px;right:60px;"
        "bottom:60px;z-index:5;overflow:hidden}"
    )

    @staticmethod
    def build_outline_slide_lines(slides: List[Dict[str, Any]]) -> List[str]:
        """从大纲中提取少量摘要行，用于感知内容类型。"""
        slide_lines: List[str] = []
        for idx, slide in enumerate(slides[:3], start=1):
            if not isinstance(slide, dict):
                continue

            title = slide.get("title") or f"第{idx}页"
            slide_type = slide.get("slide_type") or slide.get("type") or ""
            points = slide.get("content_points") or slide.get("content") or []

            if isinstance(points, list):
                points = [str(item) for item in points[:4]]
                points_text = "；".join([item for item in points if item])
            else:
                points_text = str(points)[:120]

            extra = f"（{slide_type}）" if slide_type else ""
            slide_lines.append(f"{idx}. {title}{extra}：{points_text}".strip("："))

        return slide_lines

    # ------------------------------------------------------------------
    # 大纲分析辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_compact_outline_summary(slides: List[Dict[str, Any]]) -> str:
        """全部幻灯片的紧凑摘要，每页一行：序号. 标题（类型）。"""
        lines: List[str] = []
        for idx, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                continue
            title = slide.get("title") or f"第{idx}页"
            slide_type = slide.get("slide_type") or slide.get("type") or ""
            tag = f"（{slide_type}）" if slide_type else ""
            lines.append(f"{idx}. {title}{tag}")
        return "\n".join(lines) if lines else "(暂无大纲)"

    @staticmethod
    def _build_slide_type_distribution(slides: List[Dict[str, Any]]) -> str:
        """统计页面类型分布，如 '封面1页 / 内容8页 / 结尾1页'。"""
        type_labels = {
            "cover": "封面", "title": "封面",
            "catalog": "目录", "outline": "目录", "directory": "目录", "agenda": "目录",
            "ending": "结尾", "thankyou": "结尾", "conclusion": "结尾",
        }
        counts: Dict[str, int] = {}
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            raw = (slide.get("slide_type") or slide.get("type") or "content").strip().lower()
            label = type_labels.get(raw, "内容")
            counts[label] = counts.get(label, 0) + 1
        if not counts:
            return "暂无"
        return " / ".join(f"{label}{n}页" for label, n in counts.items())

    @staticmethod
    def _build_narrative_arc_summary(slides: List[Dict[str, Any]]) -> str:
        """从幻灯片标题序列推导一句话叙事弧线。"""
        titles = []
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            t = slide.get("title") or ""
            if t:
                titles.append(t)
        if len(titles) <= 2:
            return ""
        # 紧凑展示：首 → 中段关键 → 尾
        mid_count = len(titles) - 2
        mid_preview = "→".join(titles[1:4]) if mid_count <= 3 else f"{'→'.join(titles[1:3])}→…→{titles[-2]}"
        return f"{titles[0]} → {mid_preview} → {titles[-1]}"

    @staticmethod
    def build_free_template_user_prompt(
        project: Any,
        outline: Dict[str, Any],
        confirmed: Dict[str, Any],
    ) -> str:
        """构建自由模板的项目专属需求，提供丰富的项目上下文和创意催化。"""
        slides = outline.get("slides", []) if isinstance(outline, dict) else []

        topic = getattr(project, "topic", "") or outline.get("title") or ""
        scenario = getattr(project, "scenario", "") or confirmed.get("scenario", "")
        target_audience = confirmed.get("target_audience") or ""
        ppt_style = confirmed.get("ppt_style") or ""
        custom_style_prompt = confirmed.get("custom_style_prompt") or ""
        description = confirmed.get("description") or ""
        requirements = confirmed.get("requirements") or ""
        focus_content = confirmed.get("focus_content") or []
        if isinstance(focus_content, list):
            focus_content = "、".join(str(item) for item in focus_content if item)

        # --- 项目信息 ---
        prompt_parts = [
            "===== 项目信息 =====",
            f"主题：{topic}" if topic else "",
            f"场景：{scenario}" if scenario else "",
            f"受众：{target_audience}" if target_audience else "",
            f"风格偏好：{ppt_style}" if ppt_style else "",
            f"自定义风格补充：{custom_style_prompt}" if custom_style_prompt else "",
            f"项目说明：{description}" if description else "",
            f"内容重点：{focus_content}" if focus_content else "",
            f"补充要求：{requirements}" if requirements else "",
        ]

        # --- 氛围感知 ---
        prompt_parts.append("")
        prompt_parts.append(
            TemplatePrompts.get_template_atmosphere_prompt_text(
                topic=topic,
                scenario=scenario,
                target_audience=target_audience,
                ppt_style=ppt_style,
            )
        )

        # --- 大纲全貌 ---
        total_pages = len(slides)
        type_dist = TemplatePrompts._build_slide_type_distribution(slides)
        arc = TemplatePrompts._build_narrative_arc_summary(slides)
        compact_outline = TemplatePrompts._build_compact_outline_summary(slides)

        prompt_parts.append("")
        prompt_parts.append("===== 大纲全貌（用于推导内容节奏与视觉密度变化） =====")
        prompt_parts.append(f"总页数：{total_pages}")
        prompt_parts.append(f"页面类型分布：{type_dist}")
        if arc:
            prompt_parts.append(f"叙事弧线：{arc}")
        prompt_parts.append(compact_outline)

        # --- 自由模板设计方向 ---
        topic_label = topic or "本项目"
        prompt_parts.append("")
        prompt_parts.append("===== 自由模板设计方向 =====")
        prompt_parts.append(
            f"- 这是为「{topic_label}」量身定制的视觉系统，不是换了标题的通用商务皮肤。"
        )
        prompt_parts.append(
            f"- 思考：什么视觉隐喻最能传达「{topic_label}」的本质？将它编码为跨页复现的设计语汇。"
        )
        prompt_parts.append(
            "- 母版需要兼容四种构图场景：封面的仪式感、目录的导航性、内容页的信息密度、结尾页的收束力。"
        )
        prompt_parts.append(
            "- 如果项目信息不足以建立强方向，从大纲的叙事弧线和内容类型中主动推导视觉主张。"
        )

        return "\n".join([part for part in prompt_parts if part]).strip()

    # ------------------------------------------------------------------
    # 角色定义与创意催化
    # ------------------------------------------------------------------

    @staticmethod
    def _get_role_framing() -> str:
        """附带创意方法论的角色定义，替代扁平头衔。"""
        return """你是一位以「场所精神」为理念的视觉系统建筑师。
你的工作不是排版，而是为一个主题建造它专属的视觉世界。

你的设计方法论：
1. 先感受——这个主题让人联想到什么材质、光线、空间气质？
2. 再提炼——从联想中提取可编码为 CSS 的设计语汇（色彩、字体气质、几何语言、空间节奏）。
3. 然后构建——将语汇编织成一套母版系统：稳定的锚点让人安心，灵活的主舞台让内容呼吸。
4. 最后检验——这套系统能否让 10+ 页内容各不相同却一眼同源？

你要交付的不是一张页面，而是一个能持续生长的视觉生态。"""

    @staticmethod
    def get_template_atmosphere_prompt_text(
        topic: str = "",
        scenario: str = "",
        target_audience: str = "",
        ppt_style: str = "",
    ) -> str:
        """根据主题信息动态生成氛围感知问题，引导模型建立情绪基调和视觉隐喻。"""
        parts = ["===== 氛围感知（在写代码前先回答） ====="]

        questions: List[str] = []
        topic_label = topic or "这个主题"
        questions.append(
            f"如果「{topic_label}」是一个物理空间，它的光线、材质和温度是什么样的？"
        )
        questions.append(
            "这套演示的情绪基调应该是什么？（庄重 / 轻快 / 前卫 / 温暖 / 沉浸 / 其他）"
        )
        questions.append(
            f"什么视觉隐喻最能代表「{topic_label}」的内在逻辑？"
            "（例如：数据流、年轮、星图、积木、水墨、晶格……）"
        )
        questions.append(
            "什么色彩组合能同时传递专业感和这个主题独有的情绪？"
        )
        if scenario:
            questions.append(
                f"在「{scenario}」场景下，演示者和观众之间的关系如何？"
                "这种关系应该如何反映在视觉节奏上？"
            )
        if target_audience:
            questions.append(
                f"面向「{target_audience}」，视觉系统应该偏向哪种气质——权威、亲和、激励、沉浸？"
            )

        for i, q in enumerate(questions, 1):
            parts.append(f"{i}. {q}")

        parts.append("")
        parts.append(
            "将你的回答内化为设计决策的依据——不需要在输出中写出答案，"
            "但每一个配色、字体、几何图形和空间关系的选择都应该能追溯到这些问题。"
        )
        return "\n".join(parts)

    @staticmethod
    def get_template_resource_performance_prompt_text() -> str:
        """统一模板生成阶段的资源可达性与性能约束。"""
        return SystemPrompts.get_resource_performance_prompt()

    @staticmethod
    def get_template_annotation_prompt_text() -> str:
        """固定画布与母版职责分层提示。"""
        return """
以下是实现层面的护栏，在创意决策完成后用于确保 HTML/CSS 的稳定性：

**母版/设计系统骨架**
- 根容器固定 `1280x720` 且 `overflow:hidden`；画布根容器负责 `position:relative` 与 1280x720 裁切。**整个页面不允许出现任何滚动条**——html、body、根容器及所有子容器都必须 `overflow:hidden`，禁止使用 `overflow:auto` 或 `overflow:scroll`。
- 母版必须建立三个职责层：标题锚点区、主舞台区、编号锚点区；请显式区分标题锚点区、主舞台区、编号锚点区三类职责层，但不要求必须使用 `header/main/footer` 标签。
- 页码结构必须兼容"页码 absolute 脱离文档流 + 内容层预留安全区"的固定画布骨架；如果不脱流，也要保证编号位置稳定且不会被正文轻易挤压。
- 编号锚点区负责页码或章节编号秩序；主舞台区负责后续页面自由重组。
- 编号锚点可以 `absolute` 脱流，也可以嵌入稳定容器；重点是位置关系稳定。
- 如果使用纵向 `flex` 骨架，必须让标题锚点和编号锚点 `flex:none`，主舞台 `flex:1; min-height:0; min-width:0; overflow:hidden`。
- 如果使用 `grid` 骨架，主舞台轨道必须写成 `minmax(0,1fr)`；不要让编号锚点和可增长正文共享会被内容撑开的裸 `1fr` 轨道。
- 所有承载正文的 flex/grid item 都要显式写出 `min-height:0; min-width:0`，不要依赖默认最小尺寸。
- 主舞台不能被固定大外框锁死，也不要把整页 body 做成只能容纳一种构图的大面板。
- 母版要同时兼容"内容较少时有气场"和"内容较多时不崩坏"，长列表、表格、图表等高风险模块要预留限高、分栏或简化空间。
- 类名仅用于说明结构关系，使用 inline style 做等价实现同样有效。
""".strip()

    @staticmethod
    def get_template_generation_creative_prompt_text() -> str:
        """母版创意愿景，以正面驱动替代负面禁令。"""
        return """
**创意愿景**
- 你正在创建一套**视觉语言系统**——一组可编码的设计规则，让后续 10+ 页各有表情却一眼同源。
- **主题即材料**：从主题内涵中提取视觉隐喻，让配色、几何语言和空间节奏都有"为什么是这样"的理由。
- **标题区是性格表达**：用排版、字重、装饰元素或空间关系赋予标题区辨识度，让它成为整套系统的签名。
- **主舞台是变化引擎**：设计一个框架，让封面的大留白、内容页的密集信息、结尾页的仪式感都能在同一语法下自然展开。
- **系统元素即记忆点**：从主题推导出的编号样式、章节标记、分隔语言、色彩节奏——这些跨页复现的小系统累积成整套 PPT 的气质。
- **维度分离创造变化**：让颜色、密度、重心、容器比例成为独立可调的旋钮，而非所有页面共享一个固定构图。
- **克制胜于堆叠**：一个精准的视觉隐喻胜过三个并列的装饰效果。渐变、纹理、几何、内联 SVG 和微动效都是好工具，用对比用多更重要。
""".strip()

    @staticmethod
    def get_template_generation_method_prompt_text() -> str:
        """模板创作过程，以创意思考驱动而非工程流水线。"""
        return """
**创作过程**
1. **感知** — 阅读项目信息和大纲全貌，感受这个主题的情绪重心、节奏和内在张力。
2. **提炼视觉主张** — 用一句话定义这套母版的灵魂（例如："用数据流的透明层叠感传递 AI 的理性与可能性"），这句话将指导后续所有决策。
3. **建立设计语汇** — 从视觉主张推导出：核心色彩逻辑、字体性格组合、标志性几何语言、空间节奏策略。
4. **构建系统骨架** — 定义三个职责层（标题锚点、主舞台、编号锚点），设计它们在封面/目录/内容/结尾四种场景下的变化关系。
5. **编码落地** — 将以上决策转化为 HTML/CSS，用 `:root` 变量、语义类名和清晰的装饰层表达这套母版语言。
""".strip()

    @staticmethod
    def get_template_generation_requirements_prompt_text() -> str:
        """母版生成技术要求（护栏层，创意决策完成后生效）。"""
        return f"""
**技术要求**
- 固定 1280x720，16:9，**绝对禁止出现任何滚动条**。根容器及所有子容器均须 `overflow:hidden`，不允许 `overflow:auto/scroll`。如果内容超出画布，必须通过删减、分栏或缩小来适配，而非允许滚动。
- 输出完整 HTML，自包含 `<style>`，优先使用 `:root` 变量。
- 仅使用以下四个占位符：`{{{{ page_title }}}}`、`{{{{ page_content }}}}`、`{{{{ current_page_number }}}}`、`{{{{ total_page_count }}}}`。它们会在渲染时被真实内容替换。
- **禁止使用模板条件语法**：不要输出 `{{% if %}}` / `{{% endif %}}` / `{{% for %}}` 等 Jinja/模板控制结构。母版是一个通用骨架，不做页面类型分支。
- **禁止硬编码示例文案**：不要在模板中写入具体的标题文字、口号或段落内容（如"感谢聆听""Let's…"等）。所有会变化的文字必须使用上述占位符。如果需要展示示例文案用于辅助理解，放在 `<!-- 注释 -->` 中。
- 图标优先内联 SVG / CSS / Unicode；图表、公式、代码高亮按需启用。
{TemplatePrompts.get_template_resource_performance_prompt_text()}
{TemplatePrompts.get_template_annotation_prompt_text()}
""".strip()

    @staticmethod
    def build_template_generation_prompt(user_prompt: str, mode_instruction: str = "") -> str:
        """组装完整母版生成提示词——创意优先，技术护栏在后。"""
        mode_section = f"{mode_instruction.strip()}\n\n" if mode_instruction else ""
        return f"""
{TemplatePrompts._get_role_framing()}

{mode_section}用户需求：
{user_prompt}

{TemplatePrompts.get_template_generation_creative_prompt_text()}

{TemplatePrompts.get_template_generation_method_prompt_text()}

{TemplatePrompts.get_template_generation_requirements_prompt_text()}

直接输出完整 HTML 模板，使用```html```代码块返回，不要附加解释。
""".strip()

    @staticmethod
    def _build_creativity_guidance(creativity: int) -> str:
        """根据 0-10 刻度生成封面/过渡页的"遵循母版 vs 创意自由"指引。

        0 = 严格遵循母版设计语言；10 = 最具创意（可超越母版构图/手法，
        仅保留配色基因）。
        """
        try:
            creativity = int(creativity)
        except (TypeError, ValueError):
            creativity = 0
        creativity = max(0, min(10, creativity))

        if creativity <= 1:
            # 严格遵循母版
            return (
                "**封面/过渡页创意度：低（严格遵循母版）**\n"
                "- 封面/过渡页的视觉语言应尽量贴近母版：沿用母版的配色、字体、材质、几何语言与构图逻辑，"
                "让它们看起来就是母版体系的自然延伸。\n"
                "- 可以在排版细节上做小幅润色（层次、间距、装饰点缀），但不要改变母版的整体气质与结构。"
            )
        if creativity <= 3:
            return (
                "**封面/过渡页创意度：中低（以母版为主，适度升华）**\n"
                "- 沿用母版的配色与字体基因，但可以适度提升构图张力与视觉层次。\n"
                "- 允许更丰富的装饰手法（背景层次、几何语言、细节点缀），但整体气质仍贴近母版。"
            )
        if creativity <= 6:
            return (
                "**封面/过渡页创意度：中（母版与创意平衡）**\n"
                "- 继承母版的配色基因（主色/强调色/字体气质），但封面/过渡页的构图、材质、层次、装饰手法"
                "可以明显更丰富、更有设计感。\n"
                "- 鼓励使用多背景层、材质纹理、几何张力、非对称构图等，让封面/过渡页显得更精致专业，"
                "但配色仍能追溯到母版。"
            )
        if creativity <= 8:
            return (
                "**封面/过渡页创意度：较高（大胆创意，保留配色基因）**\n"
                "- 封面/过渡页可以自由发挥成专业级设计（像精品模板/发布会的封面）：构图、材质、层次、"
                "装饰手法都可以大胆突破母版的框架。\n"
                "- 仅需保留母版的配色基因（从主色/强调色/字体气质出发，可提炼、可升华），"
                "不必逐字照搬母版结构。\n"
                "- 追求高完成度的视觉设计：多背景层叠、材质纹理、几何语言、细节点缀、光影质感等。"
            )
        # creativity 9-10：最具创意
        return (
            "**封面/过渡页创意度：最高（最具创意，仅保留配色线索）**\n"
            "- 封面/过渡页可以完全自由地发挥，追求惊艳的视觉冲击与记忆点，像顶级设计作品/发布会封面。\n"
            "- 只需从母版提炼一两个配色线索（主色/强调色之一）作为点缀，构图、材质、装饰可以完全超越母版。\n"
            "- 鼓励突破常规的排版、材质、层次与光影，让封面/过渡页成为整套 PPT 的视觉亮点。"
        )

    @staticmethod
    def build_template_suite_prompt(
        project: Any = None,
        outline: Dict[str, Any] = None,
        confirmed: Dict[str, Any] = None,
        template_html: str = "",
        extracted_header_footer: Dict[str, str] = None,
        creativity: int = 0,
        reference_outline: bool = False,
        custom_requirements: str = "",
        source_kind: str = "master",
    ) -> str:
        """组装"模板套件"生成提示词。

        基于已选母版的设计风格，一次生成：
        - 封面模板（{{cover_title}}/{{cover_subtitle}}/{{cover_extra}} 槽位）
        - 过渡页模板（{{transition_title}}/{{transition_subtitle}}/{{transition_extra}} 槽位）
        - 内容页规范页头页脚（{{page_title}}/{{current_page_number}}/{{total_page_count}} 槽位）
        - design_tokens 一行设计令牌
        输出固定 JSON 结构，供机械解析。

        creativity：0-10 刻度，0=严格遵循母版设计语言，10=最具创意。
        reference_outline：为 True 时才把项目主题/大纲/受众等信息传给模型；
        默认 False = 套件只基于母版模板生成，不绑定具体项目内容。
        custom_requirements：用户自定义要求（如主题色/风格），设计时须遵循。
        source_kind："master"=基于 PPT 母版模板（默认，保持现有行为）；
        "web"=基于用户粘贴的网页 HTML（template_html 即网页 HTML），套件配色/字体/版式/
        背景装饰/视觉语言须与该网页保持一致；无母版页头页脚原文可用。
        """
        outline = outline or {}
        confirmed = confirmed or {}
        slides = outline.get("slides", []) if isinstance(outline, dict) else []

        topic = getattr(project, "topic", "") or outline.get("title") or ""
        scenario = getattr(project, "scenario", "") or confirmed.get("scenario", "")
        target_audience = confirmed.get("target_audience") or ""
        ppt_style = confirmed.get("ppt_style") or ""
        custom_style_prompt = confirmed.get("custom_style_prompt") or ""

        # 项目上下文（仅 reference_outline=True 时包含）
        project_context = ""
        if reference_outline:
            outline_lines = TemplatePrompts._build_compact_outline_summary(slides)
            type_dist = TemplatePrompts._build_slide_type_distribution(slides)
            arc = TemplatePrompts._build_narrative_arc_summary(slides)
            project_context = f"""
**项目信息**
- 主题：{topic}
- 场景：{scenario}
- 受众：{target_audience}
- 风格偏好：{ppt_style}
- 自定义风格补充：{custom_style_prompt}

**大纲全貌**
- 总页数：{len(slides)}
- 页面类型分布：{type_dist}
{f"- 叙事弧线：{arc}" if arc else ""}
{outline_lines}
"""

        # 确定性提取的母版页头/页脚（作为内容页页头页脚的强约束来源）
        hf = extracted_header_footer or {}
        header_block = (hf.get("header_html") or "") + "\n" + (hf.get("header_css") or "")
        footer_block = (hf.get("footer_html") or "") + "\n" + (hf.get("footer_css") or "")
        hf_section = ""
        if header_block.strip() or footer_block.strip():
            hf_section = f"""
**母版页头原文（内容页页头必须与此同源，可沿用其字节/样式）**
{header_block.strip() or "(未能提取到明确页头)"}

**母版页脚原文（内容页页脚必须与此同源，可沿用其字节/样式）**
{footer_block.strip() or "(未能提取到明确页脚)"}
"""

        # 参考源区块：按 source_kind 分支。web 模式 = 基于用户粘贴的网页 HTML，
        # 无 PPT 母版页头页脚原文可用（网页导航/页脚不适合做内容页页头页脚），
        # 内容页页头页脚需模型自行设计（仍须遵循 .suite-stage 等结构约束）。
        if source_kind == "web":
            web_html_raw = (template_html or "").strip()
            if len(web_html_raw) > 60000:
                web_html_raw = (
                    web_html_raw[:60000]
                    + "\n<!-- 网页 HTML 较长，已截断；请重点参考其配色/字体/版式/背景装饰风格 -->"
                )
            source_section = (
                "**参考网页 HTML（套件的配色/字体/版式/背景装饰/视觉语言必须与此网页保持一致）**\n"
                f"{web_html_raw or '(未提供网页 HTML，请按文字需求自行设计一套)'}"
            )
            hf_section = ""  # 网页无 PPT 页头页脚原文，避免把网页导航当内容页页头
        else:
            source_section = (
                "**母版 HTML 原文**\n"
                f"{template_html or '(无母版原文，请按项目风格自行设计一套)'}"
            )

        # 用户自定义要求区块（避免在 f-string 表达式内用反斜杠）
        custom_req_section = ""
        if (custom_requirements or "").strip():
            custom_req_section = "**用户自定义要求（设计时必须遵循）**\n" + custom_requirements.strip() + "\n"

        return f"""
请基于已选母版的设计风格与主题色，生成一套通用的"模板套件"——封面模板、过渡页模板、内容页规范页头页脚。

{project_context}
{custom_req_section}
{source_section}

{hf_section}

{TemplatePrompts.get_template_resource_performance_prompt_text()}

**任务与输出约束**
1. `cover`：一个完整的封面 HTML（1280×720，无滚动条，设计丰富有仪式感），预留槽位 `{{{{ cover_title }}}}`（主标题）、`{{{{ cover_subtitle }}}}`（副标题）、`{{{{ cover_extra }}}}`（可选补充文案）。
2. `transition`：一个完整的章节过渡页 HTML（1280×720，无滚动条），预留槽位 `{{{{ transition_title }}}}`（章节标题）、`{{{{ transition_subtitle }}}}`（简短引导语）、`{{{{ transition_extra }}}}`（可选补充）、`{{{{ chapter_number }}}}`（当前章节序号，纯数字如 1/2/3，生成 PPT 时会替换为真实章节号；可用 CSS/文案包装成"第1章/01/Chapter 1"等样式）。
3. `catalog`：一个完整的**目录/大纲页** HTML（1280×720，无滚动条）。预留槽位 `{{{{ catalog_title }}}}`（页面标题，如"目录"）、`{{{{ catalog_subtitle }}}}`（副标题）、`{{{{ catalog_extra }}}}`（可选补充）。**目录条目区必须自带完整设计**：用编号（01/02/03…）+ 章节名 + 分隔线/双栏等排版，呈现 4-6 个示例章节（如"第一章 项目概述"），让条目区看起来像专业模板的目录，而不是一段文字；**不要预留 `{{{{ catalog_items }}}}` 槽位**，生成 PPT 时模型会参考本页设计并填入真实章节。
4. `ending`：一个完整的**结尾/致谢页** HTML（1280×720，无滚动条），预留槽位 `{{{{ ending_title }}}}`（主标题，如"感谢聆听"）、`{{{{ ending_subtitle }}}}`（副标题）、`{{{{ ending_extra }}}}`（可选补充）、`{{{{ ending_items }}}}`（可选收尾要点列表）。
5. `header_footer`：内容页的**自包含骨架片段**（不是完整页面，但包含内容页的全部视觉骨架）。必须包含：
   - 模板的背景装饰层（如 `bg-paper`/`bg-grid`/边框装饰/印章等，从母版同源继承），保证内容页有背景和装饰；
   - 页头 `{{{{ page_title }}}}`（页头标题）；
   - 一个正文占位容器 `{{{{ page_content }}}}`（供后续填充正文）；
   - 页脚 `{{{{ current_page_number }}}}`（当前页码）、`{{{{ total_page_count }}}}`（总页数）；
   - 可选 `{{{{ chapter_number }}}}`（本页所属章节序号，纯数字如 1/2/3；放在页头/页脚的章节标识位，可用 CSS 包装成"第1章/01"等样式）。
   样式与母版提取原文同源；整段片段后续会被逐字嵌入内容页提示词作为强约束，因此必须自带背景装饰，不能只有孤立的页头页脚文字。
   **片段自带 `<style>` 块必须同时包含全局 reset 与画布约束**（与封面/过渡页一致）：
   ```css
   {TemplatePrompts.HF_RESET_CSS}
   {TemplatePrompts.HF_CANVAS_RULE}
   ```
   （这段会被逐字嵌入内容页，保证内容页 body 无默认 8px margin、无滚动条。内层画布元素仍可用 `position:relative/absolute` 排版。）
   **必须含一个标准正文舞台容器 `<div class="suite-stage">{{ page_content }}</div>`**，其 `<style>` 规则固定为（标准化边界，让度量与约束锚定同一容器）：
   ```css
   {TemplatePrompts.HF_STAGE_RULE}
   ```
   （`top:155px` 避开页头底边、`bottom:60px` 不压页脚、`overflow:hidden` 兜住溢出。`left/right:60px` 与页头页脚对齐，内宽 1160px——所有 flex/grid 列宽基准由此固定。）
6. **品牌文案必须写成品牌槽位，不得固化具体值**（生成 PPT 时会替换为项目真实值：年份/部门/主题/标语）：
   - 年份 → `{{{{ brand_year }}}}`
   - 部门/单位名 → `{{{{ brand_org }}}}`
   - 主题/标题标识 → `{{{{ brand_topic }}}}`
   - 标语/保密标识/补充英文 → `{{{{ brand_tagline }}}}`
   适用位置：封面页眉页脚、过渡页 footer、目录页眉、结尾页，以及 header_footer 的页头右侧/页脚左侧。**不要写死 `2024`/`DEPARTMENT`/`CHINA MERCHANTS BANK`/`ANNUAL REVIEW`/`CONFIDENTIAL` 这类示例品牌值**；保持通用设计框架即可。**不要生成整份文档的整体编号或编号类槽位（如 `No.01`、`{{{{brand_code}}}}`）；章节号请用 `{{{{chapter_number}}}}` 槽位表示，且只在过渡页和内容页 header_footer 出现，封面/目录/结尾页不要章节号槽位。**
7. `design_tokens`：一行简短设计令牌文本（字体栈 / 主强调色 / 页头背景 / 页脚样式），供内容页生成器快速对齐。
8. 各块 HTML 都必须遵守固定 1280×720、`overflow:hidden`、禁止滚动条、禁止 @media、禁止 transform scale。封面/过渡/目录/结尾页必须用 `<!DOCTYPE html>` 开头完整 HTML；`header_footer` 是片段。
9. 不要使用纯黑 `#000000` / 纯白 `#ffffff`，避免 AI 套路紫蓝霓虹渐变，禁止 em-dash/en-dash。

{TemplatePrompts._build_creativity_guidance(creativity)}

**输出格式（严格 JSON，不要附加任何解释）**
```json
{{
  "cover": "<完整封面HTML>",
  "transition": "<完整过渡页HTML>",
  "catalog": "<完整目录页HTML>",
  "ending": "<完整结尾页HTML>",
  "header_footer": "<规范页头页脚HTML片段>",
  "design_tokens": "字体栈：...；强调色：...；页头背景：...；页码样式：..."
}}
```
""".strip()

    # 套件单类型重新生成：只重生 cover/transition/catalog/ending/header_footer 中的一种，
    # 其余部分和设计令牌保留，避免整套重生成浪费 token。
    _SUITE_PART_META = {
        "cover": {
            "key": "cover",
            "label": "封面模板",
            "desc": "一个完整的封面 HTML（1280×720，无滚动条），预留槽位 {{cover_title}}（主标题）、{{cover_subtitle}}（副标题）、{{cover_extra}}（可选补充文案）。",
        },
        "transition": {
            "key": "transition",
            "label": "过渡页模板",
            "desc": "一个完整的章节过渡页 HTML（1280×720，无滚动条），预留槽位 {{transition_title}}（章节标题）、{{transition_subtitle}}（简短引导语）、{{transition_extra}}（可选补充）、{{chapter_number}}（当前章节序号，纯数字，生成 PPT 时替换为真实章节号）。",
        },
        "catalog": {
            "key": "catalog",
            "label": "目录页模板",
            "desc": "一个完整的目录/大纲页 HTML（1280×720，无滚动条）。预留槽位 {{catalog_title}}（页面标题）、{{catalog_subtitle}}（副标题）、{{catalog_extra}}（可选补充）。目录条目区必须自带完整设计（编号 01/02… + 章节名 + 分隔/双栏排版），呈现 4-6 个示例章节，像专业模板的目录；不要预留 {{catalog_items}} 槽位。",
        },
        "ending": {
            "key": "ending",
            "label": "结尾/致谢页模板",
            "desc": "一个完整的结尾/致谢页 HTML（1280×720，无滚动条），预留槽位 {{ending_title}}（主标题）、{{ending_subtitle}}（副标题）、{{ending_extra}}（可选补充）、{{ending_items}}（可选收尾要点）。",
        },
        "header_footer": {
            "key": "header_footer",
            "label": "内容页页头页脚",
            "desc": "内容页的规范页头+页脚 HTML 片段（不是完整页面），必须包含槽位 {{page_title}}（页头标题）、{{current_page_number}}（当前页码）、{{total_page_count}}（总页数）。样式须与母版同源，后续会逐字嵌入内容页提示词作为强约束。**片段自带 <style> 必须包含全局 reset 与画布约束**：`*{margin:0;padding:0;box-sizing:border-box}` 和 `html,body{width:1280px;height:720px;margin:0;overflow:hidden}`（保证内容页 body 无默认 margin、无滚动条）。**必须含标准正文舞台容器 `<div class=\"suite-stage\">{{ page_content }}</div>`，规则固定为 `.suite-stage{position:absolute;top:155px;left:60px;right:60px;bottom:60px;z-index:5;overflow:hidden}`**（top 避开页头底边、bottom 不压页脚、内宽 1160px 作为 flex/grid 列宽基准）。**品牌文案（年份/部门/主题/标语）必须写成品牌槽位**：年份→{{brand_year}}、部门→{{brand_org}}、主题→{{brand_topic}}、标语→{{brand_tagline}}，不要写死 2024/DEPARTMENT/ANNUAL REVIEW/CONFIDENTIAL 等示例值；不要生成整份文档的整体编号或编号类槽位，章节号请用 `{{chapter_number}}` 槽位（本页所属章节序号，纯数字），只在此过渡页/内容页 header_footer 出现。",
        },
    }

    @staticmethod
    def build_template_suite_part_prompt(
        part: str,
        project: Any = None,
        outline: Dict[str, Any] = None,
        confirmed: Dict[str, Any] = None,
        template_html: str = "",
        extracted_header_footer: Dict[str, str] = None,
        existing_suite: Dict[str, Any] = None,
        user_feedback: str = "",
        creativity: int = 0,
        reference_outline: bool = False,
    ) -> str:
        """组装"模板套件单类型重新生成"提示词。

        只重新生成 part（cover/transition/header_footer）这一种，其余套件部分
        与 design_tokens 作为风格参考保留，从而节省 token、保持整体一致。

        creativity：0-10 刻度，0=严格遵循母版设计语言，10=最具创意（仅 cover/transition 生效）。
        reference_outline：为 True 时才把项目主题/大纲等信息传给模型；默认 False = 仅基于母版/现有套件。
        """
        meta = TemplatePrompts._SUITE_PART_META.get(part)
        if not meta:
            raise ValueError(f"不支持的套件类型: {part}")

        outline = outline or {}
        confirmed = confirmed or {}
        slides = outline.get("slides", []) if isinstance(outline, dict) else []
        existing_suite = existing_suite or {}

        topic = getattr(project, "topic", "") or outline.get("title") or ""
        scenario = getattr(project, "scenario", "") or confirmed.get("scenario", "")
        target_audience = confirmed.get("target_audience") or ""
        ppt_style = confirmed.get("ppt_style") or ""
        custom_style_prompt = confirmed.get("custom_style_prompt") or ""

        # 项目上下文（仅 reference_outline=True 时包含）
        project_context = ""
        if reference_outline:
            outline_lines = TemplatePrompts._build_compact_outline_summary(slides)
            type_dist = TemplatePrompts._build_slide_type_distribution(slides)
            project_context = f"""
**项目信息**
- 主题：{topic}
- 场景：{scenario}
- 受众：{target_audience}
- 风格偏好：{ppt_style}
- 自定义风格补充：{custom_style_prompt}

**大纲全貌**
- 总页数：{len(slides)}
- 页面类型分布：{type_dist}
{outline_lines}
"""

        hf = extracted_header_footer or {}
        header_block = (hf.get("header_html") or "") + "\n" + (hf.get("header_css") or "")
        footer_block = (hf.get("footer_html") or "") + "\n" + (hf.get("footer_css") or "")
        hf_section = ""
        if header_block.strip() or footer_block.strip():
            hf_section = (
                "**母版页头原文（内容页页头必须与此同源）**\n"
                f"{header_block.strip() or '(未能提取到明确页头)'}\n\n"
                "**母版页脚原文（内容页页脚必须与此同源）**\n"
                f"{footer_block.strip() or '(未能提取到明确页脚)'}"
            )

        # 作为风格参考：现有 design_tokens + 现有其他套件部分（截断展示即可，避免重复灌入全文）
        existing_ref_lines = []
        existing_tokens = str(existing_suite.get("design_tokens") or "").strip()
        if existing_tokens:
            existing_ref_lines.append(f"- design_tokens：{existing_tokens}")
        for ref_key, ref_label in (("cover", "封面"), ("transition", "过渡页"), ("header_footer", "内容页页头页脚")):
            if ref_key == part:
                continue
            ref_html = str(existing_suite.get(ref_key) or "").strip()
            if ref_html:
                existing_ref_lines.append(
                    f"- 现有{ref_label}（仅作风格参考，保持同源）前 600 字：\n```html\n{ref_html[:600]}\n```"
                )
        existing_ref = "\n".join(existing_ref_lines) if existing_ref_lines else "- （无）"

        feedback_section = f"\n**本次调整需求（务必满足）**\n{user_feedback.strip()}\n" if user_feedback.strip() else ""

        return f"""
请为这套 PPT 重新生成「{meta['label']}」，只输出这一个部分，其余套件部分保持不变。

{project_context}
**母版 HTML 原文**
{template_html or "(无母版原文，请按项目风格自行设计一套)"}

{hf_section}

**现有套件其他部分（风格参考，必须与之一眼同源）**
{existing_ref}

{feedback_section}

**本次输出约束**
- 只重新设计并输出 `{meta['key']}` 这一种：{meta['desc']}
- 必须遵守固定 1280×720、`overflow:hidden`、禁止滚动条、禁止 @media、禁止 transform scale；封面/过渡页用 `<!DOCTYPE html>` 开头完整 HTML；`header_footer` 是片段（但片段自带的 `<style>` 必须包含 `{TemplatePrompts.HF_RESET_CSS}` 与 `{TemplatePrompts.HF_CANVAS_RULE}`，保证内容页 body 无默认 margin、无滚动条）。
- 不要使用纯黑 `#000000` / 纯白 `#ffffff`，避免 AI 套路紫蓝霓虹渐变，禁止 em-dash/en-dash。
- 沿用现有套件的 design_tokens 与其余部分的视觉语言，保持同一套设计系统。
{TemplatePrompts._build_creativity_guidance(creativity) if part in ("cover", "transition", "catalog", "ending") else ""}
- 仅输出一个 JSON 对象，只包含你重生的字段，不要输出其他部分：
```json
{{ "{meta['key']}": "<新内容>" }}
```
""".strip()
