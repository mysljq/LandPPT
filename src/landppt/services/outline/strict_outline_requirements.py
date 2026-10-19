"""Extract page requirements and check directly generated strict outlines.

No free-text intent is inferred here. Only model output, source coverage and
the product's final-page-count rules are checked deterministically.
"""

import json
from copy import deepcopy


STRUCTURE_POLICY = """页数一律指补全后的最终页数，所有特殊页都计入：
3–5 页：封面 + 内容页 + 结束页；不含目录和过渡页。
6–8 页：封面 + 目录 + 内容页 + 结束页；不含过渡页。
9 页以上：封面 + 目录 + 过渡页/内容页 + 结束页；第三页为首章过渡页，至少一张真实章节过渡页。
封面恰好一张且在最前，目录需要时恰好一张且在第二页，结束页恰好一张且在最后。
过渡页必须引出后续真实内容，可以按章节设置多张，不应连续堆放。
只有经过意图分析确认的特殊页才能复用，缺少才补充；不能仅凭“总结”“策略”等标题改判页面。
不要把充满措施、数据或案例的策略概览页变成空白过渡页，不凭标题词语或文字长短定类型。
不要为了满足结构而把实质内容塞到封面或目录。结构和用户明确要求冲突时必须说明。
"""


class PlanValidationError(ValueError):
    """A plan cannot be accepted as a successful strict generation."""


class InvalidModelResponse(PlanValidationError):
    """A JSON envelope is valid but does not implement the expected contract."""


def require(condition, message):
    if not condition:
        raise PlanValidationError(message)


def compact(text):
    return "".join(text.split())


def positive_int(value):
    return type(value) is int and value > 0


class StrictOutlineRequirements:
    ROLES = {"title", "agenda", "transition", "content", "conclusion", "thankyou"}
    ENDINGS = {"conclusion", "thankyou"}

    @staticmethod
    def band(count):
        return "small" if count <= 5 else "medium" if count <= 8 else "large"

    @staticmethod
    def requirements_prompt(text, topic):
        return f"""将用户的 PPT 需求整理为逐页需求 JSON。主题：{topic}
此步骤只提取用户提供的需求，不生成大纲、不补充页面或规划完整 PPT 结构。

sources 按输入顺序记录，一张用户页面对应一个 kind=page、independent=true 的来源，不合并或拆分页面。
text 原样保留完整内容和数据；原始页码标签单独放在 label（没有则空字符串）。美化、受众等全局要求单列 kind=context、role=unspecified、independent=false，完整覆盖输入。
content_points 按语义列出各个独立内容要点，不将多个要点合成一个；context 使用空列表。
页面默认 role=content。仅在用户明确表达特殊页用途、且独立内容要点不超过一个时，才使用 title/agenda/transition/conclusion/thankyou。
特殊用途结合上下文判断，special_page_evidence 摘录原文依据，reason 简述判断理由；其他情况 evidence 为空，保留为内容页。
counts 仅记录用户明确提出的页数要求，不从页面编号或素材条目数推断总页数。scope=final/content，kind=exact/range/approx，min/max 为正整数，exact/approx 的 min=max；evidence 摘录原文，未提出数量要求则 counts=[]。

只返回 JSON：
{{"sources":[{{"id":"s1","text":"完整连续原文片段","label":"","kind":"page","role":"content","independent":true,"content_points":["独立内容要点"],"special_page_evidence":"","reason":"判断依据"}}],
"counts":[{{"scope":"final","kind":"exact","min":8,"max":8,"evidence":"原文"}}]}}
原始需求开始：
{text}
原始需求结束。"""

    def validate_requirements(self, value, text):
        if not isinstance(value.get("sources"), list) or not isinstance(value.get("counts"), list):
            raise InvalidModelResponse("必须提供 sources 列表和 counts 列表")
        ids = set()
        original = compact(text)
        cursor = 0
        omissions = []
        for source in value["sources"]:
            require(isinstance(source, dict), "source 必须是对象")
            sid = source.get("id")
            require(isinstance(sid, str) and sid and sid not in ids, "source id 必须唯一")
            ids.add(sid)
            require(isinstance(source.get("text"), str) and source["text"].strip(), f"{sid} 缺少原文")
            require(source.get("kind") in ("page", "context"), f"{sid} kind 无效")
            require(isinstance(source.get("role"), str) and source["role"] in self.ROLES | {"unspecified"}, f"{sid} role 无效")
            require(type(source.get("independent")) is bool, f"{sid} 需明确是否独立成页")
            for obsolete in ("fixed_page", "content_page", "position"):
                source.pop(obsolete, None)
            label = source.get("label", "")
            require(isinstance(label, str), f"{sid} label 必须是字符串")
            # A label is metadata, not a mandatory prefix of the quoted body.
            # Locate verbatim content while tolerating whitespace-only reformatting.
            quoted = compact(source["text"])
            start = original.find(quoted, cursor)
            require(start >= 0, f"{sid} text 无法按顺序匹配原文，可能改写或漏掉数据；请原样摘录该段")
            gap = original[cursor:start]
            # Only separators and this source's model-identified label may be
            # outside the body. Unmatched prose must be returned for repair.
            separators = "-—–_:：;；,，。|/\\[]【】()（）\"'“”"
            residue = gap.strip(separators)
            label_text = compact(label).strip(separators)
            if label_text and residue.endswith(label_text):
                residue = residue[:-len(label_text)].strip(separators)
            if residue:
                omissions.append(residue)
            cursor = start + len(quoted)
            body = source["text"]
            if label and body.startswith(label):
                body = body[len(label):]
            source["required_content"] = body.strip(" \n\r\t-")
            if source["kind"] == "page":
                require(bool(source["required_content"]), f"{sid} 不能只包含页码标记")
        tail = original[cursor:].strip("-—–_:：;；,，。|/\\[]【】()（）\"'“”")
        if tail:
            omissions.append(tail)
        require(not omissions,
                "sources 未覆盖完整输入。请将以下遗漏原文补回：全局要求单列 kind=context，页面内容保留独立来源，不得删减。遗漏："
                + json.dumps(omissions, ensure_ascii=False))
        labels = set()
        for source in value["sources"]:
            if source["kind"] != "page":
                continue
            label = compact(source.get("label", ""))
            require(not label or label not in labels, "同一用户页面不得拆成多个来源，请合并该页原文并保留为一个页面需求")
            if label:
                labels.add(label)
            points = source.get("content_points")
            require(isinstance(points, list) and all(isinstance(p, str) and p.strip() for p in points),
                    f"{source['id']} 需按语义列出 content_points，不能将多个要点包装为一个")
            evidence = source.get("special_page_evidence", "")
            require(isinstance(evidence, str), "special_page_evidence 必须为原文字符串")
            if (source["role"] == "unspecified" or len(points) > 1 or not evidence.strip()
                    or compact(evidence) not in compact(source["required_content"])):
                source["role"] = "content"
            source["independent"] = True
        for count in value["counts"]:
            self._validate_count(count)
            evidence = count.get("evidence")
            require(isinstance(evidence, str) and evidence.strip() and evidence in text, "页数要求必须有原文依据")
        value["inferred_content_pages"] = sum(
            s["kind"] == "page" and s["role"] == "content" for s in value["sources"]
        )
        return deepcopy(value)

    @staticmethod
    def _validate_count(count):
        require(isinstance(count, dict), "页数要求必须是对象")
        require(count.get("scope") in ("final", "content"), "页数范围必须为 final/content")
        require(count.get("kind") in ("exact", "range", "approx"), "页数强度无效")
        require(positive_int(count.get("min")) and positive_int(count.get("max")), "页数必须为正整数")
        require(count["min"] <= count["max"], "页数区间倒置")
        if count["kind"] in ("exact", "approx"):
            require(count["min"] == count["max"], "精确/近似目标的 min 和 max 应一致")

    def add_page_settings(self, intent, settings):
        mode = settings.get("mode")
        count = None
        if mode == "fixed":
            count = {"scope": "final", "kind": "exact", "min": settings.get("fixed_pages"), "max": settings.get("fixed_pages")}
        elif mode in ("range", "custom", "custom_range"):
            count = {"scope": "final", "kind": "range", "min": settings.get("min_pages"), "max": settings.get("max_pages")}
        if count:
            self._validate_count(count)
        prompt_counts = deepcopy(intent["counts"])
        effective = [{**count, "evidence": "页面设置"}] if count else prompt_counts
        intent["counts"] = effective
        intent["page_count_resolution"] = {
            "source": "settings" if count else "prompt" if prompt_counts else "inferred",
            "effective_counts": deepcopy(effective),
            "prompt_counts": prompt_counts,
            "inferred_content_pages": intent.get("inferred_content_pages", sum(
                s["kind"] == "page" and s["role"] == "content" for s in intent["sources"]
            )),
        }

    @staticmethod
    def requirements_text(intent):
        """Render ordered requirements, never propagating source page labels/indices."""
        blocks = []
        previous = None
        for source in intent["sources"]:
            body = source["required_content"]
            if source["kind"] == "context":
                blocks.append(f"全局要求：{body}")
                continue
            relation = f"在来源 {previous} 之后" if previous else "用户页面序列的起始"
            blocks.append(f"来源 {source['id']}（{relation}；类型 {source['role']}；独立成页）：\n{body}")
            previous = source["id"]
        blocks.append("数量要求：" + json.dumps(intent["counts"], ensure_ascii=False))
        resolution = intent.get("page_count_resolution")
        if resolution:
            if resolution["source"] == "settings":
                blocks.append("以上原文中的页数表述已被页面设置覆盖；数量以本段有效要求为准，原文内容仍需保留。")
            blocks.append("页数决策：" + json.dumps({
                "source": resolution["source"],
                "inferred_content_pages": resolution["inferred_content_pages"],
            }, ensure_ascii=False))
        return "\n\n".join(blocks)

    @staticmethod
    def outline_prompt(intent, request):
        return f"""根据逐页内容要求直接生成完整 PPT 大纲。主题：{getattr(request, 'topic', '')}。
语言：{getattr(request, 'language', 'zh')}；受众：{getattr(request, 'target_audience', '')}；风格：{getattr(request, 'ppt_style', '')}。
自定义风格：{getattr(request, 'custom_style_prompt', '') or ''}。
{STRUCTURE_POLICY}
逐页内容要求：
{StrictOutlineRequirements.requirements_text(intent)}
页数优先级：用户页面设置 > 用户提示词中的明确页数要求 > 根据已完整描述的内容页数量推断。
“数量要求”已按该优先级确定，来源为 settings 时覆盖原文中的低优先级数量表述，不将它们同时作为硬约束。
没有配置或明确页数时，从已识别的内容页和已有特殊页出发，补齐缺少结构，推断最终总页数；补页导致跨档时继续补全，直到最终页数与结构一致。
没有总页数硬约束时，以保持独立源页面、最少补充且章节合理为目标。
例如 4 张正文加封面结尾为 6 页，需目录，最终为 7 页；6 张正文加封面目录结尾为 9 页，需过渡，最终至少 10 页。
最终数量需满足所有 exact/range；approx 是软目标。不要用列表最后页码推断最终总页数。
高优先级页数较大时可基于已有内容补充讲解页，不编造事实；较小且无法保留所有独立页及必需结构时报告具体冲突，不擅自合并或改变配置页数。
每个 page source 恰好引用一次；independent=true 的来源不可与其他来源合并到同一页。
来源角色照用；全局 context 要求贯穿大纲，但不引用到单页。
所有用户源页面保持相对先后顺序，不绑定原始编号到最终页码。不得合并、拆分或省略源页面。
缺少的特殊页根据正文补充标题与内容，source_ids=[]。
先分析所有内容页的主题和递进关系，划分连续章节；每张内容页的 section 填有意义的章节标题，同章使用完全一致的名称，不同章名称不同。
目录按章节实际顺序组织，不把每页标题机械当成章节。章节不得交叉或回到已结束章节。
已确认的特殊页应复用。过渡页的 section 为所引出的章节标题，必须位于该章节起始并紧接同 section 的内容页，不得在同章中途重复插入。
大于8页的首章过渡必须紧跟目录，其余章节根据内容衔接需要设置过渡；不为凑页数增加无实质意义的章节。
在对应页面 title 和 content_points 中完整保留引用来源的内容和数据，可分点但不要删减、概括或改写原文。
目录 content_points 按顺序包含实际章节的完整标题；简短来源不能编造案例、图表或数据。
返回完整大纲 JSON，不生成候选计划：
{{"title":"演示标题","slides":[{{"slide_type":"title","title":"主题标题","section":"","source_ids":[],"content_points":["封面内容"],"description":"页面说明"}}]}}
收到不遵循之处的反馈后，分析原因并修改完整大纲；可以增删或移动补充页以满足最终页数和结构，但保留所有用户源页面及其先后关系。
若数量与独立页面及必需结构无法兼容，返回 {{"conflicts":["具体冲突与调整建议"]}}，不擅自放宽要求。"""

    def validate_structure(self, pages, intent):
        require(len(pages) >= 3, "至少需要封面、内容、结束三页")
        sources = {s["id"]: s for s in intent["sources"] if s["kind"] == "page"}
        seen_ids, seen_sources, roles, content_order = set(), set(), [], []
        for index, page in enumerate(pages, 1):
            require(isinstance(page, dict), "计划页面必须是对象")
            pid = page.get("page_id")
            require(isinstance(pid, str) and pid and pid not in seen_ids, "page_id 必须唯一")
            seen_ids.add(pid)
            role = page.get("slide_type")
            require(isinstance(role, str) and role in self.ROLES, f"{pid} 页面类型无效")
            roles.append(role)
            require(isinstance(page.get("title"), str) and page["title"].strip(), f"{pid} 必须有标题")
            refs = page.get("source_ids")
            require(isinstance(refs, list), f"{pid} source_ids 必须是列表")
            for sid in refs:
                require(isinstance(sid, str) and sid in sources and sid not in seen_sources, f"{pid} 来源不存在或被重复分配")
                source = sources[sid]
                seen_sources.add(sid)
                if source["independent"]:
                    require(len(refs) == 1, f"{sid} 要求独立成页，不能合并")
                require(source["role"] in (role, "unspecified"), f"{sid} 页面功能不得从 {source['role']} 改成 {role}")
                content_order.append(list(sources).index(sid))
        require(seen_sources == set(sources), "大纲遗漏用户页面")
        require(content_order == sorted(content_order), "用户页面来源的相对顺序被改变")
        band = self.band(len(pages))
        errors = []
        if roles[0] != "title" or roles.count("title") != 1:
            errors.append("必须恰有一张封面且在首页")
        if roles[-1] not in self.ENDINGS or sum(r in self.ENDINGS for r in roles) != 1:
            errors.append("必须恰有一张结束页且在末尾")
        if "content" not in roles:
            errors.append("必须包含内容页")
        if band == "small":
            if "agenda" in roles or "transition" in roles:
                errors.append("最终5页及以下不能有目录或过渡页")
        else:
            if roles[1] != "agenda" or roles.count("agenda") != 1:
                errors.append("最终6页以上需要第二页目录且不能重复")
            if band == "medium":
                if "transition" in roles:
                    errors.append("最终6–8页不能有过渡页")
            else:
                if roles[2] != "transition":
                    errors.append("最终9页以上必须含过渡页，并从第三页首章过渡开始")
        chapters = []
        for page in pages:
            if page["slide_type"] != "content":
                continue
            section = page.get("section")
            require(isinstance(section, str) and section.strip(), "内容页需要明确章节")
            if not chapters or chapters[-1] != section:
                require(section not in chapters, "章节内容必须连续，不可交叉")
                chapters.append(section)
        introduced = set()
        for index, page in enumerate(pages):
            if page["slide_type"] == "transition":
                require(isinstance(page.get("section"), str) and page["section"].strip(), "过渡页需要明确章节")
                if not (index + 1 < len(pages) and pages[index + 1]["slide_type"] == "content"
                        and pages[index + 1].get("section") == page["section"]):
                    errors.append(f"当前第 {index + 1} 页的过渡页必须紧接所属章节内容")
                if page["section"] in introduced:
                    errors.append(f"当前第 {index + 1} 页的过渡页必须在章节起始，不能在同章中途重复插入")
            elif page["slide_type"] == "content":
                introduced.add(page["section"])
        for count in intent["counts"]:
            if count["kind"] == "approx":
                continue
            actual = len(pages) if count["scope"] == "final" else roles.count("content")
            if not count["min"] <= actual <= count["max"]:
                errors.append(f"{count['scope']} 要求 {count['min']}–{count['max']} 页，大纲为 {actual} 页；请调整或报告冲突")
        require(not errors, f"当前大纲实际 {len(pages)} 页，结构档位 {band}；不遵循之处：" + "；".join(errors))
        return chapters

    def validate_outline(self, value, intent):
        if isinstance(value.get("conflicts"), list) and value["conflicts"]:
            raise PlanValidationError("；".join(str(e) for e in value["conflicts"]))
        if not isinstance(value.get("title"), str) or not isinstance(value.get("slides"), list):
            raise InvalidModelResponse("大纲必须包含 title 字符串和 slides 列表")
        require(isinstance(value.get("title"), str) and value["title"].strip(), "缺少演示标题")
        slides = value.get("slides")
        require(bool(slides), "大纲不能为空")
        slides = deepcopy(slides)
        for index, slide in enumerate(slides, 1):
            require(isinstance(slide, dict), "slide 必须是对象")
            slide["page_id"] = f"p{index}"
        sources = {s["id"]: s for s in intent["sources"]}
        chapters = self.validate_structure(slides, intent)
        result = []
        for index, slide in enumerate(slides, 1):
            page = slide
            require(isinstance(slide, dict), "slide 必须是对象")
            require(isinstance(slide.get("title"), str) and slide["title"].strip(), "缺少页面标题")
            points = slide.get("content_points")
            require(isinstance(points, list) and all(isinstance(p, str) for p in points), "content_points 必须是字符串列表")
            require(any(p.strip() for p in points), "页面不能只有标题而无内容")
            visible = compact(slide["title"] + "".join(points))
            if page["slide_type"] == "agenda":
                agenda_text = compact("".join(points))
                cursor = 0
                for chapter in chapters:
                    start = agenda_text.find(compact(chapter), cursor)
                    require(start >= 0, "目录必须按实际章节顺序覆盖全部章节标题")
                    cursor = start + len(compact(chapter))
            for sid in page["source_ids"]:
                require(compact(sources[sid]["required_content"]) in visible,
                        f"{page['page_id']} 未完整保留 {sid} 的内容/数据，请将该来源原文加入对应 content_points")
            result.append({**slide, "page_number": index, "type": page["slide_type"],
                           "source_ids": list(page["source_ids"]), "section": page.get("section", ""),
                           "origin": "user" if page["source_ids"] else "supplemented"})
        return {"title": value["title"], "slides": result, "chapters": chapters}
