"""Optional portable browser preview. Does not mutate production templates."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

PARTS = ('cover', 'catalog', 'transition', 'content', 'ending')
DEFAULTS = {
    'brand_org': '示例组织', 'brand_tagline': '清晰表达 · 有效协作',
    'brand_attribution': '示例团队', 'brand_year': '2026', 'chapter_number': '02',
    'current_page_number': '08', 'total_page_count': '16',
    'page_title': '从核心问题出发，形成清晰的实践路径',
    'page_content': '<h2>示例正文</h2><p>此区域由项目动态生成。检查正文布局、图片与页眉页脚的关系。</p>',
}
for _part, _title in [('cover', '能力建设与实践分享'), ('catalog', '内容导览'),
                      ('transition', '核心能力与实践路径'), ('ending', '感谢聆听，期待交流')]:
    DEFAULTS.update({_part + '_title': _title, _part + '_subtitle': '以清晰的结构连接目标、方法和行动。',
                     _part + '_extra': '示例文案 · 请按实际使用场景替换并复查'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite-dir', type=Path, required=True)
    parser.add_argument('--samples', type=Path, help='JSON object of slot values; page_content may be HTML')
    browser_arg = parser.add_mutually_exclusive_group()
    browser_arg.add_argument('--channel', help='Installed browser channel, e.g. msedge or chrome')
    browser_arg.add_argument('--executable-path', type=Path)
    args = parser.parse_args()
    root = args.suite_dir.resolve()
    preview = root / 'preview'
    samples = dict(DEFAULTS)
    if args.samples:
        provided = json.loads(args.samples.read_text(encoding='utf-8-sig'))
        if not isinstance(provided, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in provided.items()):
            parser.error('--samples requires a JSON object of string slot values')
        samples.update(provided)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        parser.error('Install scripts/requirements-preview.txt to enable browser previews')
    preview.mkdir(exist_ok=True)
    checks = []
    with sync_playwright() as p:
        options = {'headless': True}
        if args.channel:
            options['channel'] = args.channel
        if args.executable_path:
            options['executable_path'] = str(args.executable_path.resolve())
        browser = p.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 720}, device_scale_factor=1)
            for part in PARTS:
                text = (root / f'{part}.html').read_text(encoding='utf-8-sig')
                def fill(match):
                    name = match[1]
                    if name not in samples:
                        raise ValueError(f'No preview sample for slot {name}; supply --samples')
                    return samples[name] if name == 'page_content' else html.escape(samples[name])
                text = re.sub(r'{{\s*(\w+)\s*}}', fill, text)
                text, count = re.subn(r'(<head\b[^>]*>)', r'\1<base href="../">', text, count=1, flags=re.I)
                if not count:
                    raise ValueError(f'{part}: standalone HTML head required')
                target = preview / f'{part}.html'
                target.write_text(text, encoding='utf-8')
                page.goto(target.as_uri(), wait_until='load')
                page.evaluate('document.fonts.ready')
                page.evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                page.wait_for_timeout(200)
                page.screenshot(path=str(preview / f'{part}.png'))
                result = page.evaluate('''() => {
                  const failures=[];
                  for(const e of document.images)if(!e.complete||!e.naturalWidth)failures.push('broken image: '+e.getAttribute('src'));
                  for(const e of document.querySelectorAll('h1,h2,h3,p,.title,.subtitle,.extra,.suite-stage')){
                    const r=e.getBoundingClientRect();
                    if(e.scrollHeight>e.clientHeight+2||e.scrollWidth>e.clientWidth+2)failures.push('overflow: '+e.tagName+'.'+e.className);
                    if(r.x<0||r.y<0||r.right>1281||r.bottom>721)failures.push('outside canvas: '+e.tagName+'.'+e.className);
                  }
                  const stage=document.querySelector('.suite-stage');
                  if(stage){const r=stage.getBoundingClientRect();for(const e of stage.querySelectorAll('*')){const b=e.getBoundingClientRect();if(b.x<r.x-1||b.y<r.y-1||b.right>r.right+1||b.bottom>r.bottom+1)failures.push('outside stage: '+e.tagName+'.'+e.className);}}
                  return {canvas:[document.documentElement.clientWidth,document.documentElement.clientHeight],image_count:document.images.length,failures};
                }''')
                if result['canvas'] != [1280, 720]:
                    result['failures'].append('canvas is not 1280x720')
                checks.append({'part': part, **result})
        finally:
            browser.close()
    gallery = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Suite preview</title><style>body{font-family:sans-serif;background:#eee;padding:24px}iframe{width:1280px;height:720px;border:0;background:white}h2{margin-top:36px}</style><h1>套件示例预览</h1><p>示例文案已填入；正式模板保持动态槽位。自动检查不能替代逐页视觉核验。</p>'
    for part in PARTS:
        gallery += f'<h2>{part}</h2><iframe src="{part}.html" title="{part}"></iframe>'
    (preview / 'index.html').write_text(gallery + '</html>', encoding='utf-8')
    (preview / 'verification.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'preview': str(preview), 'checks': checks}, ensure_ascii=False))
    if any(c['failures'] for c in checks):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
