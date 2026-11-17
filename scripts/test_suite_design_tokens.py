"""Isolated real-model A/B test. Saves artifacts; never modifies project slides.

Both arms share the same template, content, model and prompt. Only tokens vary.
This is a focused body-generation test, not the full production guide pipeline.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sqlite3
from pathlib import Path

from landppt.ai import AIMessage, MessageRole
from landppt.services.db_config_service import get_user_role_provider_sync

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp' / 'template_audit' / 'token_test'


def fill(source, values):
    return re.sub(r'{{\s*(\w+)\s*}}', lambda m: str(values.get(m[1], '')), source)


async def generate(project_id, only=None):
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(ROOT / 'landppt.db'); c.row_factory = sqlite3.Row
    project = dict(c.execute('select * from projects where project_id=?', (project_id,)).fetchone())
    c.close()
    slides = json.loads(project['outline'])['slides']
    suite = json.loads((ROOT / 'template_examples/classic_red_white_v2/suite.json').read_text(encoding='utf8'))
    previous = json.loads((OUT / 'suite-before.json').read_text(encoding='utf8'))
    provider, settings = get_user_role_provider_sync(project['user_id'], 'slide_generation')
    sem = asyncio.Semaphore(2)

    async def one(index, arm):
        name = f'{arm}-{index+1:02}'
        if (OUT / f'{name}.html').exists():
            print('Existing result retained:', name, flush=True)
            return
        tokens = previous['design_tokens'] if arm == 'before' else suite['design_tokens']
        prompt = '\n'.join([
            '为以下真实PPT页面生成正文HTML。独立设计正文构图，所有信息必须准确完整，不添加事实。',
            '本次仅输出{{page_content}}的HTML片段，可包含<style>，不要输出整页、页头、页尾、页面标题或解释。',
            '外部模板已固定.suite-stage，内宽1120px、高446px；不要修改容器边界。',
            '所有新增CSS选择器以.suite-stage为前缀，所有内容均位于其内部；禁止全局reset、script、iframe、外链资源。',
            '不得用overflow:hidden、文字省略、line-clamp、transform缩放或缩小画布掩盖正文溢出。',
            '【固定模板HTML，供读取样式；不要输出这部分】', suite['header_footer'],
            '【本页内容】', json.dumps(slides[index], ensure_ascii=False),
            '【必须遵守的design_tokens】', tokens,
        ])
        (OUT / f'{name}-prompt.txt').write_text(prompt, encoding='utf8')
        async with sem:
            print('Generating:', name, flush=True)
            response = await asyncio.wait_for(provider.chat_completion(
                messages=[AIMessage(role=MessageRole.SYSTEM, content='你是PPT信息设计师。依据给定设计系统与真实内容生成可读、结构清晰的HTML正文。只输出HTML。'), AIMessage(role=MessageRole.USER, content=prompt)],
                model=settings.get('model') or provider.model,
                temperature=0.3, max_output_tokens=16000,
            ), timeout=600)
        raw = response.content.strip()
        (OUT / f'{name}-raw.txt').write_text(raw, encoding='utf8')
        raw = re.sub(r'^```(?:html)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw).strip()
        if not raw or re.search(r'<(?:html|body|script|iframe)\b', raw, re.I):
            raise ValueError(f'{name}: invalid body fragment')
        values = dict(page_title=html.escape(slides[index]['title']), page_content=raw,
                      current_page_number=index+1, total_page_count=len(slides),
                      brand_tagline='第三章 AI Agent工程理念' if index==15 else ('第二章 智能体应用的落地' if index==10 else '第四章 执行组织方式与工程体系'),
                      brand_attribution='部门')
        result = fill(suite['header_footer'], values)
        (OUT / f'{name}.html').write_text(result, encoding='utf8')
        (OUT / f'{name}-meta.json').write_text(json.dumps(dict(model=response.model, usage=response.usage, finish_reason=response.finish_reason, slide=slides[index]), ensure_ascii=False, indent=2), encoding='utf8')
        print('Generated:', name, 'finish:',response.finish_reason, flush=True)

    cases = [(i,arm) for i in [10,15,23] for arm in ['before','after'] if not only or f'{arm}-{i+1:02}' in only]
    outcomes = await asyncio.gather(*(one(i, arm) for i,arm in cases), return_exceptions=True)
    errors = [str(x) for x in outcomes if isinstance(x, Exception)]
    run_name = 'generation-run' + ('-' + '-'.join(only) if only else '') + '.json'
    (OUT / run_name).write_text(json.dumps(dict(provider=settings['provider'], model=settings['model'], errors=errors, note='Isolated body generation, not full production workflow; one sample per arm and page.'), ensure_ascii=False, indent=2), encoding='utf8')
    if errors:
        print('Errors:', errors, flush=True)


def render():
    from playwright.sync_api import sync_playwright
    reports = []
    sections = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge')
        page = browser.new_page(viewport=dict(width=1280,height=720))
        for index in [10,15,23]:
            pair = []
            for arm in ['before','after']:
                name = f'{arm}-{index+1:02}'
                path = OUT / f'{name}.html'
                if not path.exists(): continue
                source = path.read_text(encoding='utf8')
                page.set_content(source,wait_until='domcontentloaded')
                try: page.wait_for_function('[...document.images].every(i=>i.complete)',timeout=5000)
                except Exception: pass
                page.screenshot(path=str(OUT / f'{name}.png'))
                result = page.evaluate('''()=>{
                  let stage=document.querySelector('.suite-stage'), r=stage.getBoundingClientRect();
                  let outside=[...stage.querySelectorAll('*')].filter(e=>!['STYLE','DEFS','MARKER','PATH','LINE','POLYLINE','POLYGON','CIRCLE','RECT','TEXT','TSPAN','G','SVG'].includes(e.tagName.toUpperCase())).map(e=>({e,r:e.getBoundingClientRect()})).filter(({e,r:q})=>q.width>0&&q.height>0&&(q.bottom>r.bottom+1||q.right>r.right+1||q.left<r.left-1||q.top<r.top-1)).map(({e,r})=>({tag:e.tagName,class:e.className,text:e.innerText?.slice(0,70),bottom:r.bottom}));
                  let elems=[...stage.querySelectorAll('*')].filter(e=>e instanceof HTMLElement);
                  return {stage:{x:r.x,y:r.y,width:r.width,height:r.height,scrollWidth:stage.scrollWidth,scrollHeight:stage.scrollHeight},outside,
                    maxTextFont:Math.max(...elems.filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())).map(e=>parseFloat(getComputedStyle(e).fontSize))),
                    fills:elems.map(e=>({color:getComputedStyle(e).backgroundColor,area:e.clientWidth*e.clientHeight})).filter(x=>x.area>5000&&!['rgba(0, 0, 0, 0)','rgb(255, 255, 255)'].includes(x.color)),
                    text:stage.innerText,svgCount:stage.querySelectorAll('svg').length};
                }''')
                reports.append(dict(name=name,**result))
                label = '旧 tokens' if arm=='before' else '新 tokens'
                pair.append('<div><h3>'+label+' · 第'+str(index+1)+'页</h3><a href="'+name+'.html" target="_blank"><img width="1280" height="720" src="'+name+'.png" alt="'+name+'"></a></div>')
            sections.append('<section>'+''.join(pair)+'</section>')
        browser.close()
    (OUT/'visual-check.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    gallery='<!DOCTYPE html><html lang="zh-CN"><meta charset="UTF-8"><title>design_tokens 新旧模型生成对照</title><style>body{font-family:Arial,Microsoft YaHei;background:#eee;padding:24px;max-width:1800px;margin:auto}img{width:100%;height:auto;display:block;background:white}section{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;margin-bottom:40px}h3{font-size:18px}</style><h1>design_tokens 新旧模型生成对照</h1><p>固定模板、内容、模型和通用指令，仅替换design_tokens。左为旧版，右为新版；点击图片可查看原尺寸HTML。隔离正文测试，原25页保持不变。</p><p>第16页新版首轮发生底部溢出，加入高度预算后已复测。三页均为单次样本观察，不代表完整生产流程的稳定性评测。</p>'+''.join(sections)+'</html>'
    (OUT/'comparison.html').write_text(gallery,encoding='utf8')
    print('Rendered results:',[(r['name'],len(r['outside']),r['maxTextFont']) for r in reports],flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('project_id');parser.add_argument('--render-only',action='store_true');parser.add_argument('--only',nargs='+');args=parser.parse_args()
    if args.render_only: render()
    else:
        asyncio.run(generate(args.project_id,args.only))
        render()
