"""Check locked geometry in the browser and compare source-text pixels to native references."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from pptx_lock import validate_lock


def verify(root, channel=None, native_dir=None, max_changed=0.03):
    from playwright.sync_api import sync_playwright
    pages={p.stem:p.read_text(encoding='utf-8') for p in root.glob('*.html') if p.stem in ('cover','catalog','transition','content','ending')}
    validate_lock(root,pages)
    lock=json.loads((root/'geometry-lock.json').read_text(encoding='utf-8'))
    samples=json.loads((root/'source-samples.json').read_text(encoding='utf-8'))
    output=root/'fidelity-check';output.mkdir(exist_ok=True)
    checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,**({'channel':channel} if channel else {}))
        try:
            page=browser.new_page(viewport={'width':1280,'height':720},device_scale_factor=1)
            for part,evidence in lock['pages'].items():
                text=re.sub(r'{{\s*(\w+)\s*}}',lambda m:samples[m[1]] if m[1]=='page_content' else html.escape(samples.get(m[1],'')),pages[part])
                text=re.sub(r'(<head\b[^>]*>)',r'\1<base href="../">',text,count=1,flags=re.I)
                file=output/f'{part}.html';file.write_text(text,encoding='utf-8')
                page.goto(file.as_uri());page.evaluate('document.fonts.ready');page.wait_for_timeout(300)
                png=output/f'{part}.png';page.screenshot(path=str(png))
                actual=page.evaluate('''() => [...document.querySelectorAll('[data-pptx-id]')].map(e=>{let r=e.getBoundingClientRect();return {id:e.dataset.pptxId,bounds:[r.x,r.y,r.width,r.height],fonts:[...e.querySelectorAll('[data-pptx-run]')].map(s=>parseFloat(getComputedStyle(s).fontSize))}})''')
                failures=[]
                for expected,measured in zip(evidence['elements'],actual):
                    error=max(abs(a-b)for a,b in zip(expected['bounds'],measured['bounds']))
                    measured['max_geometry_error_px']=error
                    if error>0.15:failures.append(f'{expected["id"]}: geometry error {error:.3f}px')
                    if expected.get('font_sizes_px'):
                        if len(expected['font_sizes_px'])!=len(measured['fonts']) or any(abs(a-b)>0.05 for a,b in zip(expected['font_sizes_px'],measured['fonts'])):
                            failures.append(f'{expected["id"]}: font sizes changed')
                broken=page.evaluate('() => [...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.getAttribute("src"))')
                failures.extend('broken asset '+ref for ref in broken)
                report={'part':part,'source_slide':evidence['source_slide'],'elements':actual,'failures':failures}
                cdp=page.context.new_cdp_session(page)
                try:
                    cdp.send('DOM.enable');cdp.send('CSS.enable')
                    dom=cdp.send('DOM.getDocument')
                    font_audit=[]
                    aliases={'微软雅黑':'microsoftyahei','微软雅黑 light':'microsoftyaheilight'}
                    def normalized(name):return aliases.get(name.lower(),name.lower().replace(' ',''))
                    for expected in evidence['elements']:
                        if not expected.get('font_families'):continue
                        query=cdp.send('DOM.querySelector',{'nodeId':dom['root']['nodeId'],'selector':'[data-pptx-id="'+expected['id']+'"] [data-pptx-run]'})
                        actual_fonts=cdp.send('CSS.getPlatformFontsForNode',{'nodeId':query['nodeId']})['fonts']
                        used=[f['familyName'] for f in actual_fonts if f['glyphCount']>0]
                        font_audit.append({'id':expected['id'],'expected':expected['font_families'],'actual':used})
                        if used and not any(normalized(a)==normalized(e)for a in used for e in expected['font_families']):
                            failures.append(f'{expected["id"]}: actual platform font differs: {used}')
                    report['platform_fonts']=font_audit
                finally:cdp.detach()
                if native_dir:
                    from PIL import Image, ImageChops, ImageStat
                    reference=Image.open(native_dir/f'{evidence["source_slide"]:03}.png').convert('RGB')
                    rendered=Image.open(png).convert('RGB')
                    if reference.size!=rendered.size:raise ValueError('Reference must be 1280x720')
                    diff=ImageChops.difference(reference,rendered)
                    fraction=sum(max(pixel)>16 for pixel in diff.getdata())/(1280*720)
                    report['pixel_comparison']={'threshold_per_channel':16,'changed_fraction':fraction,'mean_absolute_channel_error':sum(ImageStat.Stat(diff).mean)/3,'max_allowed_changed_fraction':max_changed,'note':'Native and browser rasterization may differ; geometry and text-style checks are separate.'}
                    diff.save(output/f'{part}-difference.png')
                    if fraction>max_changed:failures.append(f'Native pixel comparison changed {fraction:.2%}, limit {max_changed:.2%}')
                checks.append(report)
        finally:browser.close()
    result={'status':'passed' if not any(c['failures'] for c in checks) else 'failed','pages':checks,'native_reference':bool(native_dir),'scope':'Measured frame/style fidelity with original source text; no claim of identical rasterization across engines'}
    (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'report':str(output/'report.json'),'pages':[{'part':c['part'],'failures':c['failures'],'pixel':c.get('pixel_comparison')}for c in checks]},ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite-dir',type=Path,required=True)
    parser.add_argument('--channel')
    parser.add_argument('--native-dir',type=Path)
    parser.add_argument('--max-changed-fraction',type=float,default=0.03)
    args=parser.parse_args()
    result=verify(args.suite_dir.resolve(),args.channel,args.native_dir.resolve() if args.native_dir else None,args.max_changed_fraction)
    if result['status']!='passed':raise SystemExit(1)
