"""Render suite templates against a local project's real titles/content.

This checks browser geometry; it never writes generated slides or database rows.
Requires playwright and a locally installed Chromium browser.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
from pathlib import Path

from playwright.sync_api import sync_playwright

from build_classic_red_white_suite import OUTPUT, build_suite
from classic_red_white_editorial_previews import editorial_previews


def fill(source: str, values: dict) -> str:
    return re.sub(r"{{\s*(\w+)\s*}}", lambda m: values.get(m[1], ""), source)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    args = parser.parse_args()
    root = OUTPUT.parents[1]
    out = root / "tmp" / "template_audit"
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "landppt.db")
    conn.row_factory = sqlite3.Row
    project = conn.execute("SELECT * FROM projects WHERE project_id=?", (args.project_id,)).fetchone()
    outline = json.loads(project["outline"])["slides"]
    suite = build_suite()
    source_rows = conn.execute("SELECT slide_index, html_content FROM slide_data WHERE project_id=? ORDER BY slide_index", (args.project_id,)).fetchall()
    original_suite = dict(conn.execute("SELECT * FROM global_template_suites WHERE id=94").fetchone())
    (out / "suite-original.json").write_text(json.dumps(original_suite, ensure_ascii=False, indent=2), encoding="utf8")
    conn.close()
    values = {"brand_org": "", "brand_attribution":"部门", "brand_tagline":"第三章 AI Agent工程理念", "cover_extra": "2026年11月", "current_page_number": "4", "total_page_count": str(len(outline))}
    report = []
    previews = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        page.set_default_timeout(10000)

        def render(name: str, source: str) -> dict:
            (out / f"{name}.html").write_text(source, encoding="utf8")
            page.set_content(source, wait_until="domcontentloaded")
            try:
                page.wait_for_function("[...document.images].every(i=>i.complete)", timeout=8000)
            except Exception:
                pass
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(out / f"{name}.png"))
            return page.evaluate("""() => ({
              overflow: [...document.querySelectorAll('.suite-title,.suite-header-title,.suite-catalog-text,.suite-stage,.suite-catalog-row')]
                .filter(e=>e.scrollWidth>e.clientWidth+1 ||
                  (['hidden','clip'].includes(getComputedStyle(e).overflowY) && e.scrollHeight>e.clientHeight+1))
                .map(e=>({class:e.className,client:[e.clientWidth,e.clientHeight],scroll:[e.scrollWidth,e.scrollHeight]})),
              brokenImages:[...document.images].filter(i=>!i.naturalWidth).map(i=>i.src),
              stage:(()=>{let e=document.querySelector('.suite-stage');if(!e)return null;let r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})(),
              pageSize:[document.documentElement.scrollWidth,document.documentElement.scrollHeight]
            })""")

        # Actual generated pages, preserved as before images.
        for row in source_rows:
            if row["slide_index"] in (0, 1, 2, 3, 17, 24):
                report.append({"name": f"before-{row['slide_index']}", **render(f"before-{row['slide_index']}", row["html_content"])})

        for kind, index in [("cover", 0), ("catalog", 1), ("transition", 2), ("ending", len(outline)-1)]:
            slide = outline[index]
            data = {**values, f"{kind}_title": html.escape(slide["title"]), f"{kind}_subtitle": html.escape(slide["content_points"][0]), "chapter_number": str(slide.get("chapter", 1))}
            if kind == "catalog":
                data["catalog_subtitle"] = ""
            source = fill(suite[kind], data)
            if kind == "catalog":
                chapters = slide["content_points"]
                rows = ''.join(f'<li class="suite-catalog-row"><span class="suite-catalog-number">{n:02}</span><span class="suite-catalog-text">{html.escape(t)}</span></li>' for n, t in enumerate(chapters, 1))
                source = re.sub(r'(<ol class="suite-catalog-list">).*?(</ol>)', lambda m: m[1]+rows+m[2], source, flags=re.S)
            name = f"after-{kind}"
            result = render(name, source)
            assert not result["overflow"], (name, result)
            report.append({"name": name, **result})
            previews.append((name, source))

        for index in (3, 17):
            slide = outline[index]
            points = []
            for p in slide["content_points"]:
                label, sep, text = p.partition("：")
                if not sep:
                    label, text = "", p
                points.append('<div class="preview-row"><div class="preview-label">'+html.escape(label)+'</div><div>'+html.escape(text)+'</div></div>')
            css = '<style>.preview-body{display:flex;flex-direction:column;gap:12px;font-size:20px;line-height:1.5}.preview-row{display:grid;grid-template-columns:120px minmax(0,1fr);gap:24px;padding-bottom:8px;border-bottom:1px solid var(--suite-line)}.preview-label{font-weight:700;color:var(--suite-brand)}</style>'
            body = css + '<div class="preview-body">' + ''.join(points) + '</div>'
            source = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"></head><body>' + fill(suite["header_footer"], {**values, "page_title": html.escape(slide["title"]), "current_page_number": str(index+1), "page_content": body}) + '</body></html>'
            name = f"after-content-{index}"
            result = render(name, source)
            assert not result["overflow"], (name, result)
            assert result['stage'] == dict(x=80, y=194, width=1120, height=446)
            report.append({"name": name, **result})
            previews.append((name, source))

        for index, layout, body in editorial_previews(outline):
            slide = outline[index]
            source = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"></head><body>' + fill(suite['header_footer'], {**values, 'page_title': html.escape(slide['title']), 'current_page_number': str(index+1), 'page_content': body}) + '</body></html>'
            name = 'editorial-' + layout
            result = render(name, source)
            assert not result['overflow'], (name, result)
            assert result['stage'] == dict(x=80, y=194, width=1120, height=446)
            # Verify that layout references retain every original content point.
            text = page.locator('.suite-stage').inner_text()
            normalized = re.sub(r'\s+', '', text)
            for point in slide['content_points']:
                # CSS may put a label on a separate line; punctuation stays intact
                # except the label/body colon, which the visual layout replaces.
                assert re.sub(r'[\s：]', '', point) in re.sub(r'[\s：]', '', normalized), point
            report.append({'name': name, **result})
            previews.append((name, source))

        # Header/footer geometry must match the source suite for every title.
        chrome = '.logo,h1,.signature,.bar,.page,.attribution'
        geometry = '(es)=>es.map(e=>{let r=e.getBoundingClientRect(),s=getComputedStyle(e);return [e.className,r.x,r.y,r.width,r.height,s.fontSize,s.color,s.backgroundColor]})'
        for slide in outline:
            source = '<!DOCTYPE html><html><body>' + fill(suite["header_footer"], {**values, "page_title": html.escape(slide["title"])}) + '</body></html>'
            page.set_content(source, wait_until="domcontentloaded")
            updated = page.eval_on_selector_all(chrome, geometry)
            baseline = fill(original_suite['header_footer'], {**values, 'page_title':html.escape(slide['title'])})
            page.set_content(baseline, wait_until='domcontentloaded')
            assert updated == page.eval_on_selector_all(chrome, geometry), slide['title']
        browser.close()

    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    # A convenient local review document, with source HTML embedded and unscaled pixels.
    sections = ''.join('<section><h2>'+html.escape(n)+'</h2><iframe width="1280" height="720" srcdoc="'+html.escape(s, quote=True)+'"></iframe></section>' for n, s in previews)
    gallery = '<!DOCTYPE html><html lang="zh-CN"><meta charset="UTF-8"><title>红白商务模板排版优化预览</title><style>body{font-family:Microsoft YaHei,sans-serif;background:#eee;padding:24px}section{margin-bottom:40px}h2{font-size:20px}iframe{border:0;background:white}</style><h1>红白商务模板排版优化预览</h1><p>真实项目文本用于验证模板，内容页正文为排版示例，原任务25页内容未重生成。</p>'+sections+'</html>'
    (out / "preview.html").write_text(gallery, encoding="utf8")
    print(json.dumps({"rendered": len(report), "titles_checked":len(outline), "report":str(out / 'verification.json'), "preview":str(out / 'preview.html')},ensure_ascii=False))


if __name__ == "__main__":
    main()
