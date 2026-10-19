"""Contract regressions with scripted model responses (no paid model calls)."""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from landppt.services.outline.constrained_outline_generation_service import ConstrainedOutlineGenerationService
from landppt.services.outline.strict_outline_requirements import PlanValidationError, StrictOutlineRequirements as StrictOutlinePlan


def intent_for(texts, roles=None):
    roles = roles or ["content"] * len(texts)
    return {
        "precision": {"content": "明确逐页内容", "structure": "部分", "position": "素材顺序", "count": "未指定最终页数"},
        "counts": [],
        "sources": [
            {"id": f"s{i}", "text": f"第 {i} 页 ---{text}--- ", "label": f"第 {i} 页 ---",
             "kind": "page", "role": role, "independent": True,
             "content_points": [text], "special_page_evidence": text if role != "content" else "",
             "fixed_page": None, "position": None, "reason": "依据页面功能"}
            for i, (text, role) in enumerate(zip(texts, roles), 1)
        ],
    }


def page(pid, role, refs=()):
    return {"page_id": pid, "slide_type": role, "source_ids": list(refs),
            "title": pid, "section": "银企合作", "brief": "围绕银企合作主题组织本页"}


def plan_for_content(n, agenda=False, transition=False):
    pages = [page("cover", "title")]
    if agenda:
        pages.append(page("agenda", "agenda"))
    if transition:
        pages.append(page("section", "transition"))
    pages.extend(page(f"p{i}", "content", [f"s{i}"]) for i in range(1, n + 1))
    pages.append(page("end", "conclusion"))
    return {"pages": pages}


def normalized(intent):
    text = "".join(s["text"] for s in intent["sources"])
    return StrictOutlinePlan().validate_requirements(deepcopy(intent), text)


def outline_for(plan, intent):
    sources = {s["id"]: s for s in normalized(intent)["sources"]}
    return {"title": "银企合作", "slides": [
        {"page_id": p["page_id"], "slide_type": p["slide_type"], "title": p["title"],
         "source_ids": list(p["source_ids"]), "section": p["section"],
         "content_points": ([sources[s]["required_content"] for s in p["source_ids"]] or [p["brief"]])
             + (list(dict.fromkeys(q["section"] for q in plan["pages"] if q["slide_type"] == "content"))
                if p["slide_type"] == "agenda" else [])}
        for p in plan["pages"]
    ]}


class FakeService:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []
        self.saved = None
        self.legacy_calls = []

    async def _text_completion_for_role(self, role, *, prompt, temperature):
        self.prompts.append(prompt)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(content=value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))

    async def generate_outline(self, request, settings):
        self.legacy_calls.append((request, settings))
        return SimpleNamespace(title="原始生成", slides=[{"title": "original"}], metadata={})

    async def _update_outline_generation_stage(self, project_id, outline):
        self.saved = deepcopy(outline)


def generate(fake, intent, settings=None):
    request = SimpleNamespace(requirements="".join(s["text"] for s in intent["sources"]), topic="银企合作")
    return asyncio.run(ConstrainedOutlineGenerationService(fake).generate(
        "project", request, settings, generation_request_id="operation-1",
    ))


@pytest.mark.parametrize("total,agenda,transition", [(3, False, False), (5, False, False), (6, True, False), (8, True, False), (9, True, True), (12, True, True)])
def test_final_page_count_boundaries(total, agenda, transition):
    n = total - 2 - int(agenda) - int(transition)
    intent = intent_for([f"内容{i}" for i in range(n)])
    intent["counts"] = [{"scope": "final", "kind": "exact", "min": total, "max": total}]
    plan = plan_for_content(n, agenda, transition)
    StrictOutlinePlan().validate_structure(plan["pages"], intent)
    assert len(plan["pages"]) == total


@pytest.mark.parametrize("n,invalid,valid", [
    (4, plan_for_content(4), plan_for_content(4, True)),
    (6, plan_for_content(6, True), plan_for_content(6, True, True)),
])
def test_structure_additions_cross_band_and_candidate_is_rechecked(n, invalid, valid):
    intent = intent_for([f"正文{i}" for i in range(n)])
    with pytest.raises(PlanValidationError):
        StrictOutlinePlan().validate_structure(invalid["pages"], intent)
    StrictOutlinePlan().validate_structure(valid["pages"], intent)


def test_reuses_user_cover_agenda_transition_and_ending():
    roles = ["title", "agenda", "transition"] + ["content"] * 5 + ["conclusion"]
    intent = intent_for([f"页{i}" for i in range(9)], roles)
    plan = {"pages": [page(f"p{i}", role, [f"s{i}"]) for i, role in enumerate(roles, 1)]}
    fake = FakeService([intent, outline_for(plan, intent)])
    result = generate(fake, intent)
    assert len(result["slides"]) == 9
    assert all(s["origin"] == "user" for s in result["slides"])
    assert fake.saved["metadata"]["generation_request_id"] == "operation-1"


def test_exact_final_count_conflict_does_not_truncate_or_fall_back():
    intent = intent_for(["甲", "乙", "丙", "丁"])
    plan = plan_for_content(4, True)
    fake = FakeService([intent] + [outline_for(plan, intent)] * 3)
    with pytest.raises(PlanValidationError, match="要求 6–6 页"):
        generate(fake, intent, {"mode": "fixed", "fixed_pages": 6})
    assert fake.saved is None and not fake.legacy_calls


def test_exact_content_count_and_partial_special_pages():
    intent = intent_for(["封面主题", "一", "二", "三", "四", "总结"],
                        ["title"] + ["content"] * 4 + ["conclusion"])
    intent["counts"] = [{"scope": "content", "kind": "exact", "min": 4, "max": 4}]
    plan = {"pages": [page("cover", "title", ["s1"]), page("agenda", "agenda"),
                      *[page(f"p{i}", "content", [f"s{i}"]) for i in range(2, 6)],
                      page("end", "conclusion", ["s6"])]}
    StrictOutlinePlan().validate_structure(plan["pages"], intent)
    assert len(plan["pages"]) == 7


def test_legacy_fixed_positions_are_ignored_in_favor_of_order():
    intent = intent_for(["一", "二", "三", "四"])
    intent["sources"][0]["fixed_page"] = 3
    StrictOutlinePlan().validate_structure(plan_for_content(4, True)["pages"], intent)
    intent["sources"][0]["fixed_page"] = 1
    StrictOutlinePlan().validate_structure(plan_for_content(4, True)["pages"], intent)
    assert "fixed_page" not in normalized(intent)["sources"][0]


def test_content_ordinal_counts_only_content_even_after_transition_insertions():
    intent = intent_for([f"内容{i}" for i in range(6)])
    intent["sources"][2]["content_page"] = 3
    plan = plan_for_content(6, True, True)
    StrictOutlinePlan().validate_structure(plan["pages"], intent)
    intent["sources"][2]["content_page"] = 2
    StrictOutlinePlan().validate_structure(plan["pages"], intent)
    plan["pages"][3], plan["pages"][4] = plan["pages"][4], plan["pages"][3]
    with pytest.raises(PlanValidationError, match="相对顺序"):
        StrictOutlinePlan().validate_structure(plan["pages"], intent)


def test_custom_range_settings_and_approximate_counts():
    intent = intent_for(["一", "二", "三"])
    planner = StrictOutlinePlan()
    planner.add_page_settings(intent, {"mode": "custom_range", "min_pages": 6, "max_pages": 8})
    with pytest.raises(PlanValidationError, match="final 要求"):
        planner.validate_structure(plan_for_content(3)["pages"], intent)
    planner.validate_structure(plan_for_content(3, True)["pages"], intent)
    intent["counts"] = [{"scope": "final", "kind": "approx", "min": 5, "max": 5}]
    # Approximate counts are soft, both otherwise valid structures are allowed.
    planner.validate_structure(plan_for_content(3)["pages"], intent)
    planner.validate_structure(plan_for_content(3, True)["pages"], intent)


def test_missing_plan_contract_retries_and_falls_back_as_technical_failure():
    intent = intent_for(["正文"])
    fake = FakeService([intent, {}, {}, {}])
    result = generate(fake, intent)
    assert result["metadata"]["constraint_validation"]["skipped"]
    assert len(fake.prompts) == 4 and len(fake.legacy_calls) == 1


def test_structural_repair_does_not_change_extracted_constraints():
    intent = intent_for([f"正文{i}" for i in range(6)])
    bad = plan_for_content(6, True)
    good = plan_for_content(6, True, True)
    fake = FakeService([intent, outline_for(bad, intent), outline_for(good, intent)])
    result = generate(fake, intent)
    assert len(result["slides"]) == 10
    assert "必须含过渡页" in fake.prompts[2]
    assert len(result["metadata"]["page_requirements"]["sources"]) == 6
    assert len(fake.prompts) == 3
    assert "page_plan" not in result["metadata"]


def test_does_not_turn_rich_strategy_content_into_transition():
    intent = intent_for(["STRATEGY 01 具体措施与数字", "后续内容", "末项"])
    plan = plan_for_content(3)
    plan["pages"][1]["slide_type"] = "transition"
    with pytest.raises(PlanValidationError, match="页面功能不得"):
        StrictOutlinePlan().validate_structure(plan["pages"], intent)


def test_invalid_json_is_repaired_with_original_response():
    intent = intent_for(["正文"])
    plan = plan_for_content(1)
    fake = FakeService(["{broken", intent, outline_for(plan, intent)])
    result = generate(fake, intent)
    assert result["metadata"]["constraint_validation"]["passed"]
    assert "{broken" in fake.prompts[1] and "修正" in fake.prompts[1]


@pytest.mark.parametrize("responses", [[RuntimeError("offline")] * 3, ["not json"] * 3, [{"sources": []}] * 3])
def test_technical_extraction_failure_retries_twice_then_uses_original(responses):
    fake = FakeService(responses)
    result = generate(fake, intent_for(["正文"]), {"mode": "fixed", "fixed_pages": 8})
    assert len(fake.prompts) == 3 and len(fake.legacy_calls) == 1
    assert fake.legacy_calls[0][1]["fixed_pages"] == 8
    assert result["metadata"]["constraint_validation"]["skipped"]
    assert result["slides"] == [{"title": "original"}]


def test_dropped_source_cannot_pass_intent_validation():
    intent = intent_for(["市场占比69%", "签单2.76亿"])
    text = "".join(s["text"] for s in intent["sources"])
    intent["sources"].pop()
    with pytest.raises(PlanValidationError, match="完整输入"):
        StrictOutlinePlan().validate_requirements(intent, text)


def test_outline_number_loss_is_repaired_before_save():
    intent = intent_for(["签单2.76亿，派生不低于1.5倍"])
    plan = plan_for_content(1)
    good = outline_for(plan, intent)
    bad = deepcopy(good)
    bad["slides"][1]["content_points"] = ["签单成果显著"]
    fake = FakeService([intent, bad, good])
    result = generate(fake, intent)
    assert "2.76亿" in result["slides"][1]["content_points"][0]
    assert "s1" in fake.prompts[-1]


def test_classifier_failure_and_success():
    for responses, mode in [([{"mode": "strict"}], "strict"), (["invalid"] * 3, "original")]:
        fake = FakeService(responses)
        decision = asyncio.run(ConstrainedOutlineGenerationService(fake).classify_generation_mode("逐页要求"))
        assert decision["mode"] == mode


def bank_case():
    texts = json.loads((Path(__file__).parent / "fixtures/bank_developer_requirements.json").read_text(encoding="utf-8"))
    # One plausible model interpretation, not a live-model semantic evaluation.
    intent = intent_for(texts)
    plan = plan_for_content(18, True, True)
    return texts, intent, plan


def test_full_18_page_bank_case_keeps_all_content_pages_and_adds_structure():
    texts, intent, plan = bank_case()
    fake = FakeService([intent, outline_for(plan, intent)])
    result = generate(fake, intent)
    slides = result["slides"]
    assert len(texts) == 18 and len(slides) == 22
    assert [s["page_number"] for s in slides] == list(range(1, 23))
    assert [s["slide_type"] for s in slides[:3]] == ["title", "agenda", "transition"]
    assert slides[-1]["slide_type"] == "conclusion"
    for index, original in enumerate(texts, 1):
        matched = [s for s in slides if f"s{index}" in s["source_ids"]]
        assert len(matched) == 1 and original in matched[0]["content_points"]
    assert len(fake.prompts) == 2 and not fake.legacy_calls
    assert fake.saved["metadata"]["structure_band"] == "large"


def test_bank_case_accepts_multiple_real_chapter_transitions_and_counts_them():
    _, intent, plan = bank_case()
    for sid in ("s9", "s15"):
        index = next(i for i, p in enumerate(plan["pages"]) if sid in p["source_ids"])
        plan["pages"].insert(index, page(f"transition-{sid}", "transition"))
        for p in plan["pages"][index:]:
            if p["slide_type"] in ("content", "transition"):
                p["section"] = f"章节-{sid}"
    StrictOutlinePlan().validate_structure(plan["pages"], intent)
    assert len(plan["pages"]) == 24


def test_bank_case_missing_source_or_repeated_ending_cannot_pass():
    _, intent, plan = bank_case()
    plan["pages"] = [p for p in plan["pages"] if "s8" not in p["source_ids"]]
    with pytest.raises(PlanValidationError, match="遗漏"):
        StrictOutlinePlan().validate_structure(plan["pages"], intent)
    _, intent, plan = bank_case()
    plan["pages"].append(page("extra-end", "thankyou"))
    with pytest.raises(PlanValidationError, match="结束页"):
        StrictOutlinePlan().validate_structure(plan["pages"], intent)


def test_real_failed_response_repairs_global_context_without_label_prefix_failure():
    fixture = json.loads((Path(__file__).parent / "fixtures/strict_outline_label_regression.json").read_text(encoding="utf-8"))
    planner = StrictOutlinePlan()
    with pytest.raises(PlanValidationError, match="遗漏") as error:
        planner.validate_requirements(deepcopy(fixture["model_response"]), fixture["request"])
    assert "帮我对这个ppt进行文字和排版的美化" in str(error.value)
    assert "label 必须" not in str(error.value)
    repaired = deepcopy(fixture["model_response"])
    prefix = fixture["request"].split("---", 1)[0]
    repaired["sources"].insert(0, {"id": "context", "text": prefix, "label": "", "kind": "context",
                                      "role": "unspecified", "independent": False})
    # The actual model also omitted the leading list markers on source page 18.
    # Keep those rather than suppressing arbitrary unmatched numbers.
    repaired["sources"][-1]["text"] = "010203" + repaired["sources"][-1]["text"]
    # New contract keeps the original first page intact, not split into special pages.
    repaired["sources"][1]["text"] += repaired["sources"][2]["text"]
    repaired["sources"].pop(2)
    for source in repaired["sources"]:
        source["content_points"] = [source["text"]]
        source["special_page_evidence"] = ""
    intent = planner.validate_requirements(repaired, fixture["request"])
    assert len(intent["sources"]) == len(fixture["model_response"]["sources"])
    assert intent["sources"][1]["required_content"].startswith("深挖银企合作新模式，破局一手头部开发商")


def test_real_extraction_validation_failure_never_silently_falls_back():
    fixture = json.loads((Path(__file__).parent / "fixtures/strict_outline_label_regression.json").read_text(encoding="utf-8"))
    fake = FakeService([deepcopy(fixture["model_response"]) for _ in range(3)])
    request = SimpleNamespace(requirements=fixture["request"], topic="银企合作")
    with pytest.raises(PlanValidationError):
        asyncio.run(ConstrainedOutlineGenerationService(fake).generate("project", request))
    assert len(fake.prompts) == 3
    assert not fake.legacy_calls and fake.saved is None


def test_fallback_is_visible_when_reopening_saved_project():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(Path(__file__).parents[1] / "src/landppt/web/templates"))
    template = env.get_template("components/project/strict_generation_notice.html")
    html = template.render(project=SimpleNamespace(outline={"metadata": {"constraint_validation": {"skipped": True}}}))
    assert "display: block" in html and "未通过严格结构校验" in html
    assert "display: none" in template.render(project=SimpleNamespace(outline={"metadata": {"constraint_validation": {"passed": True}}}))


@pytest.mark.parametrize("role,evidence,points,expected", [
    ("transition", "章节起始", ["措施甲", "措施乙"], "content"),
    ("agenda", "", ["市场分析"], "content"),
    ("title", "原文没有的证据", ["市场分析"], "content"),
    ("transition", "章节起始", ["市场分析"], "transition"),
    ("thankyou", "结束致谢", [], "thankyou"),
    ("unspecified", "", ["市场分析"], "content"),
])
def test_special_roles_require_user_evidence_and_at_most_one_point(role, evidence, points, expected):
    intent = intent_for(["章节起始：市场分析；措施甲；措施乙；结束致谢"], [role])
    intent["sources"][0].update(content_points=points, special_page_evidence=evidence)
    assert normalized(intent)["sources"][0]["role"] == expected


def test_downstream_prompts_use_order_not_source_page_labels():
    intent = intent_for(["市场分析", "应对措施"])
    intent["sources"][0]["fixed_page"] = 1
    intent = normalized(intent)
    planner = StrictOutlinePlan()
    for prompt in (planner.outline_prompt(intent, SimpleNamespace()),):
        assert "第 1 页" not in prompt and "第 2 页" not in prompt
        assert "fixed_page" not in prompt and "content_page" not in prompt
        assert "在来源 s1 之后" in prompt
        assert "市场分析" in prompt and "应对措施" in prompt


def test_duplicate_original_page_cannot_be_split_into_cover_and_agenda():
    intent = intent_for(["封面主题", "目录条目"], ["title", "agenda"])
    intent["sources"][1]["text"] = "目录条目"
    intent["sources"][1]["label"] = intent["sources"][0]["label"]
    with pytest.raises(PlanValidationError, match="同一用户页面"):
        normalized(intent)


def test_agenda_coverage_and_chapter_order_are_validated():
    _, intent, plan = bank_case()
    for p in plan["pages"][10:-1]:
        p["section"] = "营销案例"
    planner = StrictOutlinePlan()
    chapters = planner.validate_structure(plan["pages"], normalized(intent))
    assert chapters == ["银企合作", "营销案例"]
    outline = outline_for(plan, intent)
    planner.validate_outline(outline, normalized(intent))
    outline["slides"][1]["content_points"] = ["营销案例", "银企合作"]
    with pytest.raises(PlanValidationError, match="目录必须"):
        planner.validate_outline(outline, normalized(intent))
    plan["pages"][-2]["section"] = "银企合作"
    with pytest.raises(PlanValidationError, match="章节内容必须连续"):
        planner.validate_structure(plan["pages"], normalized(intent))


def test_transitions_must_follow_agenda_and_start_real_chapters():
    _, intent, plan = bank_case()
    plan["pages"][2], plan["pages"][3] = plan["pages"][3], plan["pages"][2]
    with pytest.raises(PlanValidationError, match="第三页首章"):
        StrictOutlinePlan().validate_structure(plan["pages"], intent)
    _, intent, plan = bank_case()
    plan["pages"].insert(5, page("extra-transition", "transition"))
    with pytest.raises(PlanValidationError, match="章节起始"):
        StrictOutlinePlan().validate_structure(plan["pages"], intent)


def test_router_prompt_is_about_page_content_not_editing_or_structure():
    fake = FakeService([{"mode": "strict"}])
    asyncio.run(ConstrainedOutlineGenerationService(fake).classify_generation_mode("美化逐页素材"))
    prompt = fake.prompts[0]
    assert "页面内的具体内容" in prompt
    assert "无需用户额外声明" in prompt
    assert "与选择模式无关" in prompt


def test_configured_page_count_overrides_conflicting_prompt_count_in_generation():
    intent = intent_for(["最终做5页，市场趋势", "市场资源", "应对措施", "案例成果"])
    intent["counts"] = [{"scope": "final", "kind": "exact", "min": 5, "max": 5,
                         "evidence": "最终做5页"}]
    plan = plan_for_content(4, True)
    fake = FakeService([intent, outline_for(plan, intent)])
    result = generate(fake, intent, {"mode": "fixed", "fixed_pages": 7})
    assert len(result["slides"]) == 7
    resolution = result["metadata"]["page_count_resolution"]
    assert resolution["source"] == "settings"
    assert resolution["effective_counts"][0]["min"] == 7
    assert resolution["prompt_counts"][0]["min"] == 5
    assert result["metadata"]["page_count_source"] == "settings"
    assert not fake.legacy_calls


def test_configured_range_overrides_exact_prompt_and_approximate_preferences():
    planner = StrictOutlinePlan()
    intent = intent_for(["一", "二", "三"])
    intent["counts"] = [{"scope": "final", "kind": "exact", "min": 5, "max": 5},
                        {"scope": "final", "kind": "approx", "min": 5, "max": 5}]
    planner.add_page_settings(intent, {"mode": "range", "min_pages": 6, "max_pages": 8})
    with pytest.raises(PlanValidationError):
        planner.validate_structure(plan_for_content(3)["pages"], intent)
    planner.validate_structure(plan_for_content(3, True)["pages"], intent)
    assert len(intent["counts"]) == 1 and intent["counts"][0]["kind"] == "range"


def test_ai_page_settings_keep_prompt_count_above_inferred_count():
    planner = StrictOutlinePlan()
    intent = intent_for(["做6页PPT：市场趋势", "资源分布", "应对措施"])
    intent["counts"] = [{"scope": "final", "kind": "exact", "min": 6, "max": 6,
                         "evidence": "做6页PPT"}]
    intent = normalized(intent)
    planner.add_page_settings(intent, {"mode": "ai_decide"})
    assert intent["page_count_resolution"]["source"] == "prompt"
    assert intent["page_count_resolution"]["inferred_content_pages"] == 3
    with pytest.raises(PlanValidationError):
        planner.validate_structure(plan_for_content(3)["pages"], intent)
    planner.validate_structure(plan_for_content(3, True)["pages"], intent)


@pytest.mark.parametrize("content_count,total,agenda,transition", [
    (3, 5, False, False), (4, 7, True, False), (5, 8, True, False), (6, 10, True, True),
])
def test_inferred_content_count_is_not_final_count_and_structure_uses_completed_total(
    content_count, total, agenda, transition
):
    intent = intent_for([f"内容{i}" for i in range(content_count)])
    plan = plan_for_content(content_count, agenda, transition)
    fake = FakeService([intent, outline_for(plan, intent)])
    result = generate(fake, intent)
    assert len(result["slides"]) == total
    resolution = result["metadata"]["page_count_resolution"]
    assert resolution["source"] == "inferred"
    assert resolution["inferred_content_pages"] == content_count
    assert resolution["effective_counts"] == []
    assert result["metadata"]["structure_band"] == StrictOutlinePlan.band(total)


def test_inferred_content_count_excludes_confirmed_special_pages():
    intent = normalized(intent_for(["封面", "正文甲", "正文乙", "结束致谢"],
                                   ["title", "content", "content", "thankyou"]))
    StrictOutlinePlan().add_page_settings(intent, {})
    assert intent["inferred_content_pages"] == 2
    assert intent["page_count_resolution"]["inferred_content_pages"] == 2


def test_direct_outline_reports_all_missing_structure_then_repairs_without_plan():
    _, intent, good_pages = bank_case()
    bad_pages = plan_for_content(18)
    fake = FakeService([intent, outline_for(bad_pages, intent), outline_for(good_pages, intent)])
    result = generate(fake, intent)
    assert len(result["slides"]) == 22
    assert len(fake.prompts) == 3 and not fake.legacy_calls
    repair = fake.prompts[-1]
    assert "当前大纲实际 20 页" in repair
    assert "第二页目录" in repair and "第三页首章过渡" in repair
    assert "上次输出（仅供修复）" in repair
    assert "已锁定" not in repair
    assert "page_plan" not in result["metadata"]
    assert "intent_analysis" not in result["metadata"]


def test_direct_outline_repair_cannot_merge_user_sources():
    intent = intent_for(["市场占比69%", "签单2.76亿"])
    good = outline_for(plan_for_content(2), intent)
    merged = deepcopy(good)
    merged["slides"][1]["source_ids"].append("s2")
    merged["slides"][1]["content_points"].extend(merged["slides"][2]["content_points"])
    merged["slides"].pop(2)
    fake = FakeService([intent, merged, good])
    result = generate(fake, intent)
    assert "不能合并" in fake.prompts[-1]
    assert len(result["slides"]) == 4
    assert [s["source_ids"] for s in result["slides"] if s["origin"] == "user"] == [["s1"], ["s2"]]


def test_direct_outline_invalid_json_is_repaired_before_save():
    intent = intent_for(["正文"])
    good = outline_for(plan_for_content(1), intent)
    fake = FakeService([intent, "{broken outline", good])
    result = generate(fake, intent)
    assert len(fake.prompts) == 3 and "{broken outline" in fake.prompts[-1]
    assert fake.saved == result and not fake.legacy_calls
