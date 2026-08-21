import ast
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from landppt.services.outline.project_outline_normalization_service import (
    ProjectOutlineNormalizationService,
)


ROOT = Path(__file__).resolve().parents[1]


SAMPLE_OUTLINE = '''```json
{
  "title": "少样本过拟合：挑战与应对策略",
  "slides": [
    {
      "page_number": 1,
      "title": "少样本过拟合",
      "content_points": [
        "技术团队内部培训",
        "主讲人：[姓名]",
        "日期：2026-04-05"
      ],
      "slide_type": "title"
    },
    {
      "page_number": 2,
      "title": "目录",
      "content_points": [
        "过拟合问题定义与背景",
        " "少样本"场景的特殊性",
        "过拟合的根源分析",
        "核心缓解策略与实践",
        "案例分析与代码实现",
        "总结与讨论"
      ],
      "slide_type": "agenda"
    },
    {
      "page_number": 3,
      "title": "过拟合问题回顾",
      "content_points": [
        "定义：模型在训练集表现优异，但在测试集/新数据上泛化能力差",
        "本质：模型学习了数据中的噪声或特定样本特征，而非普遍规律",
        "表现：训练Loss持续下降，验证Loss先降后升（U型曲线）",
        "传统解决思路：增加数据量、正则化、Dropout、Early Stopping"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 4,
      "title": "少样本学习 (FSL) 的困境",
      "content_points": [
        "场景：类别样本极少（如每类仅1-5个样本），常见于医疗、工业缺陷检测",
        "矛盾：数据量不足以支撑复杂模型训练，极易陷入过拟合陷阱",
        "挑战：模型参数量远大于样本数量，缺乏统计显著性",
        "影响：微调阶段稍微不慎，模型性能即断崖式下跌"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 5,
      "title": "少样本过拟合的根源分析",
      "content_points": [
        "样本多样性不足：有限样本无法覆盖类内方差",
        "模型复杂度过高：参数空间大，模型倾向于“记忆”而非“理解”",
        "特征提取器偏差：基类训练得到的特征可能不适应新类",
        "任务定义偏差：Support Set与Query Set分布不一致"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 6,
      "title": "策略一：数据增强与合成",
      "content_points": [
        "传统增强：旋转、裁剪、颜色变换（效果有限）",
        "高级增强：Mixup、CutMix、CutOut（增加决策边界的平滑性）",
        "生成式方法：利用GAN或Diffusion模型生成逼真伪样本扩充Support Set",
        "特征空间增强：在特征层添加噪声或进行插值"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 7,
      "title": "策略二：模型架构与度量学习",
      "content_points": [
        "参数高效微调 (PEFT)：冻结Backbone，仅训练分类头或使用Adapter/LoRA",
        "度量学习：孪生网络、原型网络，将分类问题转化为距离度量问题",
        "图神经网络 (GNN)：利用样本间关系构建图结构进行传播",
        "注意力机制：引入自注意力机制增强特征表达"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 8,
      "title": "策略三：正则化与优化技巧",
      "content_points": [
        "强正则化：大幅提高Weight Decay系数，限制权重幅度",
        "Transductive Inference：利用未标注的Query Set信息辅助推理",
        "Meta-Regularization：在元学习阶段引入正则项，学习如何避免过拟合",
        "减少训练轮次：少样本场景下往往只需极少的Epoch即可收敛"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 9,
      "title": "技术实践：代码级建议",
      "content_points": [
        "冻结BatchNorm层：防止少量样本导致的统计量偏移",
        "使用更大的Batch Size（配合Gradient Accumulation）",
        "学习率调整：采用更小的学习率或Cosine Annealing",
        "交叉验证：使用Leave-One-Out策略最大化验证可靠性"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 10,
      "title": "总结与下一步行动",
      "content_points": [
        "核心观点：少样本过拟合是数据稀缺与模型复杂度的博弈",
        "关键策略：数据增强 + 度量学习/PEFT + 强正则化",
        "建议：优先尝试冻结Backbone和原型网络，再考虑复杂微调",
        "后续计划：团队内部复现基准测试，建立少样本任务开发规范"
      ],
      "slide_type": "conclusion"
    },
    {
      "page_number": 11,
      "title": "Q&A",
      "content_points": [
        "感谢聆听",
        "欢迎提问与讨论"
      ],
      "slide_type": "thankyou"
    }
  ]
}
```'''


def _load_class_method(relative_path: str, class_name: str, method_name: str):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method_node = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    module = ast.Module(body=[method_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "time": time,
        "logger": logging.getLogger("test-outline-normalization"),
    }
    exec(compile(module, relative_path, "exec"), namespace)
    return namespace[method_name]


def test_parse_outline_content_supports_fenced_json_with_inner_quotes():
    service = ProjectOutlineNormalizationService(SimpleNamespace())
    project = SimpleNamespace(topic="少样本过拟合：挑战与应对策略")

    outline = service._parse_outline_content(SAMPLE_OUTLINE, project)

    assert outline["title"] == "少样本过拟合：挑战与应对策略"
    assert len(outline["slides"]) == 11
    assert outline["slides"][1]["slide_type"] == "agenda"
    assert outline["slides"][1]["content_points"][1] == '"少样本"场景的特殊性'
    assert outline["slides"][-1]["slide_type"] == "thankyou"


def test_parse_outline_content_no_longer_fabricates_default_slides():
    service = ProjectOutlineNormalizationService(SimpleNamespace())
    project = SimpleNamespace(topic="测试主题")

    with pytest.raises(ValueError):
        service._parse_outline_content("这是一段没有结构的大纲文本", project)


@pytest.mark.asyncio
async def test_update_project_outline_uses_normalized_parser():
    update_project_outline = _load_class_method(
        "src/landppt/services/project_workflow_stage_service.py",
        "ProjectWorkflowStageService",
        "update_project_outline",
    )

    project = SimpleNamespace(
        topic="少样本过拟合：挑战与应对策略",
        outline={},
        todo_board=None,
    )

    class _FakeProjectManager:
        async def get_project(self, project_id):
            assert project_id == "project-1"
            return project

    normalizer = ProjectOutlineNormalizationService(SimpleNamespace())
    service = SimpleNamespace(
        project_manager=_FakeProjectManager(),
        _parse_outline_content=normalizer._parse_outline_content,
    )

    success = await update_project_outline(service, "project-1", SAMPLE_OUTLINE)

    assert success is True
    assert project.outline["title"] == "少样本过拟合：挑战与应对策略"
    assert len(project.outline["slides"]) == 11
    assert project.outline["slides"][1]["slide_type"] == "agenda"


def _mk_slide(page_number, title, slide_type):
    return {
        "page_number": page_number,
        "title": title,
        "content_points": [title],
        "slide_type": slide_type,
        "type": slide_type,
        "description": "",
    }


def _chapter_outline():
    """模拟真实项目 a4f19559：一/二/三 三章，仅第二章原有过渡页。"""
    return [
        _mk_slide(1, "部门工作情况汇报", "title"),
        _mk_slide(2, "目录", "agenda"),
        _mk_slide(3, "一、室组人员管理", "content"),
        _mk_slide(4, "二、大模型方向概览", "transition"),
        _mk_slide(5, "ZA38使用情况", "content"),
        _mk_slide(6, "ZA38功能建设——Skill能力体系", "content"),
        _mk_slide(7, "低代码方向——安全合规与模板建设", "content"),
        _mk_slide(8, "低代码方向——用户牵引与现状洞察", "content"),
        _mk_slide(9, "总结与展望", "conclusion"),
    ]


def test_ensure_transition_slides_backfills_every_chapter():
    """开启过渡页：每个一级章节（含第一章）前补过渡页；同一章子页不重复插；已有过渡不重复。"""
    slides = _chapter_outline()
    slides[1]["content_points"] = ["一、室组人员管理", "二、大模型方向", "三、低代码方向"]

    fixed = ProjectOutlineNormalizationService._ensure_transition_slides(slides, True)

    types = [s["slide_type"] for s in fixed]
    # title → agenda → transition(一) → content → transition(二, 原有) → content → content
    #        → transition(三) → content → content → conclusion
    assert types == [
        "title", "agenda",
        "transition", "content",                     # 第一章：一、室组人员管理（自动补）
        "transition", "content", "content",          # 第二章：二、大模型方向（原有过渡保留，ZA38 两子页不补）
        "transition", "content", "content",          # 第三章：三、低代码方向（自动补，两子页只补一次）
        "conclusion",
    ], types
    # 页码连续重排
    assert [s["page_number"] for s in fixed] == list(range(1, len(fixed) + 1))
    # 三个一级章节各有一个过渡页
    assert types.count("transition") == 3
    # 同章第二个子页（低代码方向——用户牵引）不重复补过渡，仍为 content
    assert fixed[9]["slide_type"] == "content"
    assert fixed[9]["title"] == "低代码方向——用户牵引与现状洞察"


def test_ensure_transition_slides_respects_disabled_and_existing():
    """未开启过渡页时原样返回；已有过渡的章节前不再插入。"""
    slides = _chapter_outline()
    slides[1]["content_points"] = ["一、室组人员管理", "二、大模型方向", "三、低代码方向"]

    unchanged = ProjectOutlineNormalizationService._ensure_transition_slides(slides, False)
    assert len(unchanged) == len(slides)
    assert [s["slide_type"] for s in unchanged] == [
        "title", "agenda", "content", "transition", "content", "content", "content", "content", "conclusion",
    ]

    # 第一章前已有过渡（LLM 已插）→ 不重复插
    first_content = 2  # 目录后第一个 content 的下标
    pre = _chapter_outline()
    pre[1]["content_points"] = ["一、室组人员管理", "二、大模型方向", "三、低代码方向"]
    pre.insert(first_content, _mk_slide(4, "一、室组人员管理", "transition"))  # 插在第一章 content 之前
    # 重新编号
    for i, s in enumerate(pre, 1):
        s["page_number"] = i
    fixed = ProjectOutlineNormalizationService._ensure_transition_slides(pre, True)
    types = [s["slide_type"] for s in fixed]
    assert types.count("transition") == 3, types


def test_ensure_transition_slides_chapter_start_by_number_prefix():
    """无 agenda 时，带编号前缀（一、/1、/第X章）的 content 也识别为章节起始。"""
    slides = [
        _mk_slide(1, "报告", "title"),
        _mk_slide(2, "一、背景", "content"),
        _mk_slide(3, "背景细节", "content"),
        _mk_slide(4, "二、方案", "content"),
        _mk_slide(5, "三、落地", "content"),
        _mk_slide(6, "结束", "conclusion"),
    ]
    fixed = ProjectOutlineNormalizationService._ensure_transition_slides(slides, True)
    types = [s["slide_type"] for s in fixed]
    # title → transition(一) → content → content → transition(二) → content → transition(三) → content → conclusion
    assert types == [
        "title", "transition", "content", "content",
        "transition", "content",
        "transition", "content",
        "conclusion",
    ], types


# ======================================================================
# 章节号字段 chapter：与 page_number 同级，按章节起始信号确定性赋值
# ======================================================================


def test_assign_chapter_numbers_basic():
    """chapter 字段：cover/catalog/ending=0；content 按章节起始递增；同章子页沿用。"""
    slides = [
        _mk_slide(1, "报告", "title"),
        _mk_slide(2, "目录", "agenda"),
        _mk_slide(3, "一、背景", "content"),
        _mk_slide(4, "背景细节", "content"),
        _mk_slide(5, "二、方案", "content"),
        _mk_slide(6, "三、落地", "content"),
        _mk_slide(7, "谢谢", "conclusion"),
    ]
    out = ProjectOutlineNormalizationService._assign_chapter_numbers(slides)
    chapters = [s["chapter"] for s in out]
    assert chapters == [0, 0, 1, 1, 2, 3, 0], chapters


def test_assign_chapter_numbers_transition_inherits_following_chapter():
    """过渡页 chapter 取其后第一个 content 页的章节号（过渡页属于它即将进入的章节）。"""
    slides = [
        _mk_slide(1, "报告", "title"),
        _mk_slide(2, "目录", "agenda"),
        _mk_slide(3, "一、背景", "transition"),  # 后面是"一、背景"content → chapter 1
        _mk_slide(4, "一、背景", "content"),
        _mk_slide(5, "二、方案", "transition"),  # chapter 2
        _mk_slide(6, "二、方案", "content"),
        _mk_slide(7, "谢谢", "conclusion"),
    ]
    out = ProjectOutlineNormalizationService._assign_chapter_numbers(slides)
    chapters = [(s["slide_type"], s["chapter"]) for s in out]
    assert chapters == [
        ("title", 0), ("agenda", 0),
        ("transition", 1), ("content", 1),
        ("transition", 2), ("content", 2),
        ("conclusion", 0),
    ], chapters


def test_ensure_transition_slides_assigns_chapter():
    """_ensure_transition_slides 插过渡页后，chapter 应整体重排且过渡页继承正确章节号。"""
    slides = [
        _mk_slide(1, "报告", "title"),
        _mk_slide(2, "目录", "agenda"),
        _mk_slide(3, "一、背景", "content"),
        _mk_slide(4, "二、方案", "content"),
        _mk_slide(5, "三、落地", "content"),
        _mk_slide(6, "结束", "conclusion"),
    ]
    fixed = ProjectOutlineNormalizationService._ensure_transition_slides(slides, True)
    # 每页 chapter 正确：cover/agenda=0；每章 transition+content 同号；conclusion=0
    expected = [
        ("title", 0), ("agenda", 0),
        ("transition", 1), ("content", 1),
        ("transition", 2), ("content", 2),
        ("transition", 3), ("content", 3),
        ("conclusion", 0),
    ]
    actual = [(s["slide_type"], s["chapter"]) for s in fixed]
    assert actual == expected, actual
    # page_number 仍连续
    assert [s["page_number"] for s in fixed] == list(range(1, len(fixed) + 1))


def test_standardize_outline_format_assigns_chapter():
    """_standardize_outline_format 产出的大纲每个 slide 应有 chapter 字段。"""
    outline = {
        "title": "T",
        "slides": [
            {"page_number": 1, "title": "报告", "content_points": ["a"], "slide_type": "title"},
            {"page_number": 2, "title": "目录", "content_points": ["一、背景", "二、方案"], "slide_type": "agenda"},
            {"page_number": 3, "title": "一、背景", "content_points": ["a"], "slide_type": "content"},
            {"page_number": 4, "title": "二、方案", "content_points": ["a"], "slide_type": "content"},
            {"page_number": 5, "title": "谢谢", "content_points": ["a"], "slide_type": "thankyou"},
        ],
        "metadata": {},
    }
    svc = ProjectOutlineNormalizationService.__new__(ProjectOutlineNormalizationService)
    out = svc._standardize_outline_format(outline)
    chapters = [(s["slide_type"], s.get("chapter")) for s in out["slides"]]
    assert chapters == [
        ("title", 0), ("agenda", 0),
        ("content", 1), ("content", 2),
        ("thankyou", 0),
    ], chapters


def test_assign_chapter_numbers_uses_transition_boundary_and_nonprefixed_agenda():
    """真实大纲（无编号前缀章节名 + 每章前有过渡页 + agenda 也是裸章节名）：
    transition 是章节边界信号，content 跟随过渡页即为新章节；无过渡的"现状与洞察"靠
    agenda 章节名匹配识别——全部分到 1/2/3/4，绝不出现"第 0 章"事故。"""
    slides = [
        _mk_slide(1, "部门工作情况汇报", "title"),
        _mk_slide(2, "目录", "agenda"),
        _mk_slide(3, "室组人员管理总体情况", "transition"),
        _mk_slide(4, "室组人员管理总体情况", "content"),
        _mk_slide(5, "大模型方向", "transition"),
        _mk_slide(6, "ZA38：智能体执行能力与可视化交互建设", "content"),
        _mk_slide(7, "ZA38：可观测能力完善与智能化CLI探索", "content"),
        _mk_slide(8, "训练与推理：性能优化与模型测评成果", "content"),
        _mk_slide(9, "低代码方向", "transition"),
        _mk_slide(10, "安全合规能力建设：运行与数据安全保障", "content"),
        _mk_slide(11, "薪福通精品模板建设与低代码用户牵引", "content"),
        _mk_slide(12, "现状与洞察：编码通（新）应用增长放缓分析", "content"),
        _mk_slide(13, "总结与展望", "conclusion"),
    ]
    # agenda 裸章节名（无编号前缀）：曾导致 _extract_chapter_titles 返回空 → 全部 chapter=0。
    slides[1]["content_points"] = [
        "室组人员管理",
        "大模型方向ZA38、ClawPartner、训练推理",
        "低代码方向：安全合规、模板建设、用户牵引",
        "现状与洞察",
    ]
    out = ProjectOutlineNormalizationService._assign_chapter_numbers(slides)
    chapters = [s["chapter"] for s in out]
    assert chapters == [
        0, 0,                     # title, agenda
        1, 1,                     # transition→1, content(室组人员管理)→1
        2, 2, 2, 2,               # transition→2, ZA38×2、训练推理 →2
        3, 3, 3,                  # transition→3, 安全合规、薪福通 →3
        4,                        # 现状与洞察 →4（靠 agenda 章节名匹配，无过渡）
        0,                        # conclusion
    ], chapters
    assert 0 not in chapters[2:12], "内容/过渡页绝不应出现 chapter=0（第 0 章）"

    # 顺带验证 _extract_chapter_titles 能识别无前缀章节名
    titles = ProjectOutlineNormalizationService._extract_chapter_titles(slides)
    assert "室组人员管理" in titles
    assert "现状与洞察" in titles

