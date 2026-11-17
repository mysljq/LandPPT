"""Build the reviewed red/white suite without calling an LLM or changing slides.

Run from the repository root. Output is importable by the suite library API.
The database is deliberately not modified by this builder.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "template_examples" / "classic_red_white_v2"
LOGO = "https://s3gw.cmbchina.com/lt5230-images-prd/TE0xNS4wMw==/805b2fa5f6834f8c81e1ec1d80902762"

# These exact variables are shared by all five template parts and their tokens.
VARIABLES = {
    "brand": "#C8152D", "brand-soft": "#F8ECEE", "ink": "#25282D",
    "muted": "#626870", "line": "#DFE2E6", "paper": "#FFFFFF",
    "surface": "#FFFFFF", "font-title": "32px", "font-body": "20px",
    "font-label": "18px", "font-note": "16px", "space": "8px",
}
FONT = 'Arial,"Microsoft YaHei","PingFang SC",sans-serif'
BASE = ":root{" + ";".join(f"--suite-{k}:{v}" for k, v in VARIABLES.items()) + "}\n" + """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1280px;height:720px;margin:0;overflow:hidden}
body{font-family:FONT;color:var(--suite-ink);background:var(--suite-paper)}
.suite-slide{position:relative;width:1280px;height:720px;overflow:hidden;background:var(--suite-paper)}
.suite-logo{position:absolute;right:60px;top:40px;width:164px;height:41px;object-fit:contain}
.suite-footer{position:absolute;left:60px;right:60px;bottom:24px;height:24px;display:flex;align-items:center;justify-content:space-between;gap:32px;color:var(--suite-muted);font-size:var(--suite-font-note);line-height:24px}
.suite-footer-brand{max-width:960px;overflow-wrap:anywhere}
.suite-page{flex-shrink:0;font-variant-numeric:tabular-nums}
.suite-top-mark{position:absolute;top:0;left:60px;width:56px;height:6px;background:var(--suite-brand)}
.suite-title{font-weight:700;overflow-wrap:anywhere;word-break:normal}
.suite-subtitle{color:var(--suite-muted);font-weight:400;overflow-wrap:anywhere}
.suite-rule{height:1px;background:var(--suite-line)}
""".replace("FONT", FONT)


def logo() -> str:
    return f'<img class="suite-logo" src="{LOGO}" alt="" />'


def footer(number: bool = False) -> str:
    page = '<span class="suite-page">{{ current_page_number }} / {{ total_page_count }}</span>' if number else ''
    return '<footer class="suite-footer"><span class="suite-footer-brand">{{ brand_org }}</span>' + page + '</footer>'


def fragment(css: str, content: str, number: bool = False) -> str:
    return '<style>\n' + BASE + css + '\n</style>\n<section class="suite-slide">' + '<div class="suite-top-mark" aria-hidden="true"></div>' + logo() + content + footer(number) + '</section>'


def document(title: str, css: str, content: str) -> str:
    return '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=1280, initial-scale=1"><title>' + title + '</title></head><body>' + fragment(css, content) + '</body></html>'


def build_suite() -> dict:
    original = json.loads((OUTPUT / 'source_suite.json').read_text(encoding='utf8'))
    cover = document("封面", """
.suite-cover-accent{position:absolute;left:60px;top:164px;width:72px;height:5px;background:var(--suite-brand)}
.suite-cover-copy{position:absolute;left:60px;top:196px;width:1100px;display:flex;flex-direction:column;gap:24px}
.suite-cover-title{font-size:56px;line-height:1.25;letter-spacing:-1px;max-width:1080px}
.suite-cover-subtitle{font-size:26px;line-height:1.5;max-width:1040px}
.suite-cover-extra{font-size:18px;line-height:1.5;color:var(--suite-muted)}
.suite-cover-baseline{position:absolute;left:60px;right:60px;bottom:88px;height:1px;background:var(--suite-line)}
""", '<div class="suite-cover-accent" aria-hidden="true"></div><header class="suite-cover-copy"><h1 class="suite-title suite-cover-title">{{ cover_title }}</h1><div class="suite-subtitle suite-cover-subtitle">{{ cover_subtitle }}</div><div class="suite-cover-extra">{{ cover_extra }}</div></header><div class="suite-cover-baseline" aria-hidden="true"></div>')

    transition = document("章节过渡", """
.suite-section-number{position:absolute;left:60px;top:188px;width:208px;font-size:144px;line-height:1;font-weight:700;letter-spacing:-8px;color:var(--suite-brand);font-variant-numeric:tabular-nums}
.suite-section-divider{position:absolute;left:304px;top:184px;bottom:160px;width:1px;background:var(--suite-line)}
.suite-section-copy{position:absolute;left:352px;right:76px;top:200px;display:flex;flex-direction:column;gap:24px}
.suite-section-title{font-size:44px;line-height:1.3}
.suite-section-subtitle{font-size:24px;line-height:1.55}
.suite-section-extra{font-size:18px;line-height:1.5;color:var(--suite-muted)}
""", '<div class="suite-section-number">{{ chapter_number }}</div><div class="suite-section-divider" aria-hidden="true"></div><header class="suite-section-copy"><h1 class="suite-title suite-section-title">{{ transition_title }}</h1><div class="suite-subtitle suite-section-subtitle">{{ transition_subtitle }}</div><div class="suite-section-extra">{{ transition_extra }}</div></header>')

    rows = ''.join(f'<li class="suite-catalog-row"><span class="suite-catalog-number">{i:02}</span><span class="suite-catalog-text">{name}</span></li>' for i, name in enumerate(['项目背景与目标', '现状分析与关键判断', '核心方案与实施路径', '重点工作与阶段成果', '总结与下一步计划'], 1))
    catalog = document("目录", """
.suite-catalog-heading{position:absolute;left:60px;top:48px;font-size:40px;line-height:1.25}
.suite-catalog-subtitle{position:absolute;left:60px;top:112px;font-size:18px;line-height:1.5;max-width:960px;color:var(--suite-muted)}
.suite-catalog-list{position:absolute;left:60px;right:60px;top:164px;height:456px;list-style:none;display:flex;flex-direction:column}
.suite-catalog-row{flex:1;min-height:0;display:flex;align-items:center;gap:32px;border-top:1px solid var(--suite-line);padding:8px 0}
.suite-catalog-number{flex:0 0 64px;font-size:36px;line-height:1.2;font-weight:700;color:var(--suite-brand);font-variant-numeric:tabular-nums}
.suite-catalog-text{flex:1;min-width:0;font-size:24px;line-height:1.35;font-weight:500;overflow-wrap:anywhere}
.suite-catalog-extra{position:absolute;left:60px;top:630px;max-width:1100px;font-size:16px;line-height:1.5;color:var(--suite-muted)}
""", '<h1 class="suite-title suite-catalog-heading">{{ catalog_title }}</h1><div class="suite-catalog-subtitle">{{ catalog_subtitle }}</div><ol class="suite-catalog-list">' + rows + '</ol><div class="suite-catalog-extra">{{ catalog_extra }}</div>')

    ending = document("结尾", """
.suite-ending-copy{position:absolute;left:60px;right:100px;top:228px;display:flex;flex-direction:column;gap:28px}
.suite-ending-title{font-size:56px;line-height:1.25;color:var(--suite-brand);max-width:1080px}
.suite-ending-subtitle{font-size:24px;line-height:1.55;max-width:1040px}
.suite-ending-extra{font-size:18px;line-height:1.5;color:var(--suite-muted)}
.suite-ending-baseline{position:absolute;left:60px;right:60px;bottom:88px;height:1px;background:var(--suite-line)}
""", '<main class="suite-ending-copy"><h1 class="suite-title suite-ending-title">{{ ending_title }}</h1><div class="suite-subtitle suite-ending-subtitle">{{ ending_subtitle }}</div><div class="suite-ending-extra">{{ ending_extra }}</div></main><div class="suite-ending-baseline" aria-hidden="true"></div>')

    content_css = """
.suite-stage{font-size:20px;line-height:1.5;color:var(--suite-ink)}
.suite-stage :where(p,h2,h3,ol,ul){margin:0;padding:0}
.suite-stage :where(h2,h3){font-size:24px;line-height:1.35;font-weight:700}
.suite-stage :where(p,li){overflow-wrap:anywhere}
.suite-stage :where(img,svg,canvas){max-width:100%}
.suite-stage :where(.suite-emphasis){color:var(--suite-brand);font-weight:700}
/* Content design vocabulary: open compositions, not a filled card system.
   Select one composition for the narrative; the slot remains free to vary. */
.suite-editorial{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:48px;height:100%}
.suite-display{font-size:40px;line-height:1.15;font-weight:700;color:var(--suite-brand)}
.suite-deck{font-size:24px;line-height:1.4;font-weight:600}
.suite-caption{font-size:18px;line-height:1.5;color:var(--suite-muted)}
.suite-open-list{display:flex;flex-direction:column;gap:24px;list-style:none}
.suite-open-item{display:grid;grid-template-columns:48px minmax(0,1fr);gap:20px;border-top:1px solid var(--suite-line);padding-top:16px}
.suite-index{font-size:24px;line-height:1.2;color:var(--suite-brand);font-weight:700;font-variant-numeric:tabular-nums}
.suite-path{display:flex;align-items:flex-start;gap:32px;position:relative}
.suite-path::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:var(--suite-brand)}
.suite-path-step{flex:1;min-width:0;padding-top:24px}
.suite-path-title{font-size:28px;line-height:1.2;font-weight:700;margin:12px 0}
.suite-contrast{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:64px}
.suite-contrast>div+div{border-left:1px solid var(--suite-line);padding-left:48px}
.suite-takeaway{border-top:2px solid var(--suite-brand);padding-top:12px;font-size:20px;line-height:1.5}
"""
    # All added rules are restricted to the body stage. The original header,
    # logo, background, tagline bar and footer markup/CSS remain byte-for-byte.
    content_css = re.sub(r'(?m)^(\.suite-(?!stage)[^{]+)', r'.suite-stage \1', content_css)
    stage_variables = '.suite-stage{' + ';'.join(f'--suite-{k}:{v}' for k,v in VARIABLES.items()) + '}\n'
    header_footer = original['header_footer'].replace('</style>', stage_variables + content_css + '\n</style>', 1)
    # Existing stage normalization recognizes integer px only. Round the body
    # stage downwards by 0.67px so it is not mistakenly moved up to 155px.
    header_footer = re.sub(r'(\.suite-stage\s*\{[^}]*?top:)\s*193\.33px', r'\g<1>194px', header_footer)
    header_footer = re.sub(
        r'(\.suite-stage\s*\{)([^}]*)(\})',
        lambda m: m[1] + re.sub(r'(left|right):\s*123\.33px', r'\1:80px', m[2]) + m[3],
        header_footer, count=1,
    )
    header_footer += '\n<!-- Total page metadata: {{ total_page_count }} -->'

    def restore_chrome(page: str, source: str) -> str:
        # Keep each page type's original logo and attribution, including the
        # different cover logo placement. No new shared header/footer is used.
        image = re.search(r'<img\b[^>]*class="logo"[^>]*>', source, re.S).group(0)
        attribution = re.search(r'<div class="attribution">.*?</div>', source, re.S).group(0)
        page = re.sub(r'<img\b[^>]*class="suite-logo"[^>]*>', lambda m:image, page)
        page = re.sub(r'<footer class="suite-footer">.*?</footer>', lambda m:attribution, page, flags=re.S)
        page = page.replace('<div class="suite-top-mark" aria-hidden="true"></div>', '')
        rules = re.findall(r'\.(?:logo|attribution(?:::before)?|signature)\s*\{[^}]*\}', source)
        if 'suite-catalog-heading' in page:
            heading_rule = re.search(r'\bh1\s*\{[^}]*\}', source).group(0)
            rules.append(re.sub(r'^h1', '.suite-catalog-heading', heading_rule))
        page = page.replace('</style>', '\n'+'\n'.join(rules)+'\n</style>', 1)
        if '<div class="signature"></div>' in source:
            page = page.replace('<section class="suite-slide">', '<section class="suite-slide"><div class="signature"></div>')
        return page

    cover, transition, catalog, ending = [restore_chrome(page, original[key]) for page,key in zip((cover,transition,catalog,ending),('cover','transition','catalog','ending'))]

    tokens = '\n'.join([
        '视觉风格：红黑编辑式排版，暖中性色表面，清楚的模块边界，紧凑的信息密度。依靠配色角色、版面分区和文字层级形成设计感。',
        '功能色板：品牌红 #C8152D；深酒红 #8C2838；主文字/深色强调面 #25282D；次文字 #65686E；基础面 #FFFFFF；模块面 #F6F3F1；强调浅面 #F9ECEE；边线 #DAD7D5。红色承载关键关系和重点，深灰承载主信息，暖浅色承载分组；同级对象使用一致配色。',
        '文字样式：正文优先"Microsoft YaHei","PingFang SC",Arial,sans-serif，18px/400/1.4；密集正文17px；模块标题22px/600/1.25；概念词26px/700/1.2；注释15px/400/1.35；重要数值30px/700，最多36px。正文元素显式设置这些字号，不沿用过大的展示字。',
        '空间样式：组内间距6-8px，段落间距8px，卡片内边距16px，模块/分栏间距20px，大分组间距24px。对齐共用基线，组内紧凑、组间清楚，容器高度随内容自然伸展。',
        '模块样式：普通卡片采用 #F6F3F1暖浅底、1px #DAD7D5边线、4px圆角，无阴影；标题深灰22px，正文18px，注释15px。白底模块保留边线，以免与基础面融合。简单分组可仅用标题、留白和分隔线，不必全部套卡。',
        '强调样式：有依据的主要结论或当前状态使用 #F9ECEE浅红面、3px品牌红侧线、22px/700标题；需要更强对比的关键结果可局部使用品牌红或深灰实底配白字。普通说明保持中性表面。并列卡片不单独套用强调样式。',
        '布局家族（按关系选用）：并列模块用等权双栏/三栏卡片或2×2网格；主从内容可用约2:1主区加辅助栏；客观比较用等宽双栏并按共同维度对齐；流程/演进用连续路径配说明；组成/层级用分层或关联模块。比例是可选构图起点，须适配实际内容，不强制每页采用同一种布局。',
        '组织样式：每组先有明确标题，再放说明、数据或子项；跨组关系用位置、缩进或连接线表达。卡片负责归属，关系图负责连接，表格负责维度比较；根据内容组合使用。',
        '对比原则：先判断真实语义。并列项同等呈现；主从、结论/论据、问题/方案及状态差异用位置、字重或表面区别。没有“核心”字样也可按叙述角色强调，但不因位置或装饰偏好臆造重点。',
        '图表样式：主要系列品牌红，对照系列深酒红或次灰，辅助网格用细浅灰线；直接标注数据与单位。线条1-2px，节点简洁，连接方向明确；角色稳定，不为每个条目分配不同艳色。',
        '页面节奏：信息密集页采用紧凑模块/表格，关系页让图形占据主要区域，观点页保留一块明确论点及相邻支撑；同类页保持结构一致，主题或信息关系改变时再换布局。保留有效内容，不靠放大字号、放大内边距或减少事实制造留白。'
    ])
    return dict(suite_name="经典红白商务 · 编辑设计版", description="保留原94号套件页头页尾，以适中字号、开放构图与信息关系优化正文，避免灰卡堆叠。", cover=cover, transition=transition, catalog=catalog, ending=ending, header_footer=header_footer, design_tokens=tokens, tags=["商务", "红白", "编辑设计", "开放排版"])


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    suite = build_suite()
    for key in ("cover", "transition", "catalog", "ending", "header_footer"):
        (OUTPUT / f"{key}.html").write_text(suite[key], encoding="utf-8")
    (OUTPUT / "design_tokens.txt").write_text(suite["design_tokens"], encoding="utf-8")
    (OUTPUT / "suite.json").write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)
