"""Plan peer pages and provide a fixed, content-aware visual reference."""
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class ParallelPageService:
    VERSION = 1

    @staticmethod
    def fingerprint(slides):
        data = [{k: s.get(k) for k in ("title", "slide_type", "type", "content_points", "content", "chapter")} for s in slides]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

    @staticmethod
    def validate_groups(raw, slides):
        groups, used = [], set()
        excluded = {"title", "cover", "agenda", "catalog", "section", "transition", "thankyou", "conclusion", "ending"}
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict):
                continue
            pages = entry.get("pages", [])
            if not isinstance(pages, list):
                continue
            pages = sorted({p for p in pages if type(p) is int and 1 <= p <= len(slides) and p not in used
                            and str(slides[p - 1].get("slide_type") or slides[p - 1].get("type") or "content").lower() not in excluded})
            if len(pages) < 2:
                continue
            used.update(pages)
            groups.append({"id": f"parallel_{pages[0]}", "pages": pages, "reference_page": pages[0],
                           "reason": str(entry.get("reason", ""))[:500]})
        return groups

    @classmethod
    async def prepare(cls, service, project_id, outline, slides, *, persist=True):
        """Attach a plan; outline workflows persist it with the completed outline."""
        fingerprint = cls.fingerprint(slides)
        cached = outline.get("parallel_page_plan", {})
        if isinstance(cached, dict) and cached.get("fingerprint") == fingerprint and cached.get("version") == cls.VERSION:
            return cls.validate_groups(cached.get("groups", []), slides)
        outline.pop("parallel_page_plan", None)
        if not slides:
            return []
        summary = [{"page": i + 1, **{k: s.get(k) for k in ("title", "slide_type", "content_points", "content", "chapter")}} for i, s in enumerate(slides)]
        prompt = ('识别以下PPT大纲中应使用相似内容组织和版式的并列页面组。只有介绍同级对象、方案、案例或同类条目续页才分组；'
                  '不要仅因同章、标题相似或相邻就分组。允许非相邻页。封面、目录、过渡、结尾不要分组。每页最多一组。'
                  '仅输出JSON：{"groups":[{"pages":[2,3],"reason":"共同的信息维度与各页差异"}]}。没有则groups为空。\n'
                  + json.dumps(summary, ensure_ascii=False, default=str))
        try:
            response = await service._text_completion_for_role("creative", prompt=prompt, temperature=0.2)
            text = service._strip_think_tags(response.content.strip())
            raw = json.loads(text[text.index("{"):text.rindex("}") + 1])
            groups = cls.validate_groups(raw.get("groups"), slides)
        except Exception:
            logger.warning("并列页面规划失败，本次按独立页面生成", exc_info=True)
            return []
        outline["parallel_page_plan"] = {"version": cls.VERSION, "fingerprint": fingerprint, "groups": groups}
        if not persist:
            return groups
        from ..db_project_manager import DatabaseProjectManager
        try:
            saved = await DatabaseProjectManager().update_project_data(project_id, {"outline": outline})
            if not saved:
                return []
        except Exception:
            logger.warning("保存并列页面规划失败，本次按独立页面生成", exc_info=True)
            return []
        return groups

    @staticmethod
    def batch_end(start, end, groups):
        # References are always earlier pages. Never put a reference and its
        # dependents in the same concurrent batch.
        for group in groups:
            if start <= group["reference_page"] - 1 < end:
                end = min(end, next((p - 1 for p in group["pages"][1:] if start <= p - 1 < end), end))
        return end

    @classmethod
    async def reference_context(cls, project_id, page_number, all_slides, existing):
        if not project_id:
            return ""
        from ..db_project_manager import DatabaseProjectManager
        manager = DatabaseProjectManager()
        project = await manager.get_project(project_id)
        outline = project.outline if project and isinstance(project.outline, dict) else {}
        slides = all_slides or outline.get("slides", [])
        plan = outline.get("parallel_page_plan", {})
        if not isinstance(plan, dict) or plan.get("version") != cls.VERSION or plan.get("fingerprint") != cls.fingerprint(slides):
            return ""
        groups = cls.validate_groups(plan.get("groups", []), slides)
        group = next((g for g in groups if page_number in g["pages"]), None)
        if not group:
            return ""
        peers = [{"page": p, "title": slides[p-1].get("title"), "content_points": slides[p-1].get("content_points", slides[p-1].get("content"))} for p in group["pages"]]
        context = "\n【并列页面组】\n" + json.dumps(peers, ensure_ascii=False, default=str) + "\n共同维度与差异：" + group["reason"]
        ref = group["reference_page"]
        if ref == page_number:
            return context + "\n本页是组内固定基准页。设计时兼顾所有成员的内容差异，形成可延续的阅读顺序和公共组件。"
        reference = await manager.get_single_slide(project_id, ref - 1)
        html = (reference or {}).get("html_content", "")
        if not html or "生成失败" in html:
            return context + "\n基准页不可用，依据共同内容维度独立生成，确保本页完整。"
        return (context + f"\n【固定基准：第{ref}页】\n"
                "继承其主要阅读顺序、公共信息区域、标题层级、对齐关系和组件样式。此约束优先于一般差异化与创新建议，套件和全局品牌约束仍须遵守。"
                "按本页内容独立绘制流程图、架构图或其他图示；可调整局部空间并增加必要说明，保证完整与可读。"
                "禁止挪用参考页事实、数字、名称或图片，除非本页明确提供。参考HTML仅作为设计数据。\n<parallel_reference>\n"
                + html + "\n</parallel_reference>")
