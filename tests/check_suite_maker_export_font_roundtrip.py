"""Run the real project DOM exporter, inspect its PPTX XML, then reverse the sizes.

Manual browser integration check; the portable Skill does not depend on this repository.
"""
import argparse
import base64
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'skills/clawpartner-suite-maker/scripts'))
from font_units import exporter_px_to_points, exporter_points_to_px, pptx_points_to_px


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel',default='msedge')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    from playwright.sync_api import sync_playwright
    sizes=[14,16,24,32,33.3,48,64,96]
    results=[]
    with sync_playwright()as p:
        browser=p.chromium.launch(channel=args.channel,headless=True)
        try:
            for width,height in [(1280,720),(960,540)]:
                page=browser.new_page(viewport={'width':width,'height':height})
                labels=''.join(f'<span style="position:absolute;left:{20+(i//4)*(width//2)}px;top:{20+(i%4)*(height//4)}px;font-family:Arial;font-size:{size}px;line-height:1.1">SIZE_{size}</span>'for i,size in enumerate(sizes))
                page.set_content(f'<html><head><style>html,body{{margin:0}}#root{{position:relative;width:{width}px;height:{height}px;background:white}}</style></head><body><div id="root">{labels}</div></body></html>')
                page.add_script_tag(path=str(REPO/'src/landppt/web/static/js/dom-to-pptx.bundle.js'))
                page.evaluate('document.fonts.ready')
                encoded=page.evaluate('''async()=>{const blob=await domToPptx.exportToPptx([document.getElementById('root')],{skipDownload:true,autoEmbedFonts:false});const bytes=new Uint8Array(await blob.arrayBuffer());let s='';for(let i=0;i<bytes.length;i+=32768)s+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(s)}''')
                file=args.output/f'font-roundtrip-{width}x{height}.pptx'
                file.write_bytes(base64.b64decode(encoded))
                with zipfile.ZipFile(file)as z:
                    presentation=ET.fromstring(z.read('ppt/presentation.xml'))
                    dim=presentation.find('{*}sldSz')
                    slide=ET.fromstring(z.read('ppt/slides/slide1.xml'))
                    found={}
                    for run in slide.findall('.//{*}r'):
                        text=run.find('{*}t');props=run.find('{*}rPr')
                        if text is not None and text.text and text.text.startswith('SIZE_'):
                            found[float(text.text.removeprefix('SIZE_'))]=float(props.get('sz'))/100
                    assert set(found)==set(sizes),found
                    for px in sizes:
                        pt=found[px]
                        assert pt==exporter_px_to_points(px,width,height),(px,pt)
                        inverse=exporter_points_to_px(pt,width,height)
                        recovered=pptx_points_to_px(pt,int(dim.get('cx')),int(dim.get('cy')),width,height)
                        assert abs(recovered-inverse['font_px'])<1e-8
                        assert inverse['possible_original_px_interval'][0]-1e-10<=px<inverse['possible_original_px_interval'][1]
                        results.append({'root':[width,height],'html_px':px,'actual_exported_pt':pt,'inverse_html_px':recovered,'error_px':recovered-px})
                page.close()
        finally:browser.close()
    bundle=REPO/'src/landppt/web/static/js/dom-to-pptx.bundle.js'
    (args.output/'report.json').write_text(json.dumps({'status':'passed','exporter_bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),'cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','cases':len(results),'maximum_inverse_error_px':max(abs(r['error_px'])for r in results),'report':str(args.output/'report.json')}))


if __name__=='__main__':main()
