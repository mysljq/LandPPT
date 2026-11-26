"""Bind source text to slots without retyping coordinates/styles. Missing pages remain authored work."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from bs4 import BeautifulSoup

from pptx_fidelity import document, number
from pptx_lock import create_lock


def build(source_dir, output, page_map):
    source=json.loads((source_dir/'source.json').read_text(encoding='utf-8'))
    if source.get('evidence_version')!=2:raise ValueError('Re-extract PPTX with current prepare_source.py first')
    if output.exists() and any(output.iterdir()):raise ValueError('Output must be empty; never modify an existing suite')
    output.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source_dir/'assets',output/'assets',dirs_exist_ok=True)
    lock={'version':1,'source':source.get('source'),'pages':{}}
    samples={}
    provenance={}
    for part,config in page_map.items():
        if part not in ('cover','catalog','transition','content','ending'):raise ValueError(f'Unknown page {part}')
        slide=next(s for s in source['slides'] if s['number']==config['slide'])
        items={i['id']:i for i in slide['shapes']}
        soup=BeautifulSoup(document(slide['shapes']),'html.parser')
        used=set()
        for slot,uid in config['slots'].items():
            if uid in used:raise ValueError(f'{part}: do not bind multiple slots to the same shape')
            used.add(uid)
            item=items[uid]
            if item['kind']!='text':raise ValueError(f'{part}/{slot}: only editable source text can be bound')
            target=soup.find(attrs={'data-pptx-id':uid})
            if slot=='page_content':
                x,y,w,h=item['bounds']
                stage=soup.new_tag('div',attrs={'class':'suite-stage','style':f'position:absolute;left:{number(x)}px;top:{number(y)}px;width:{number(w)}px;height:{number(h)}px;overflow:hidden'})
                # Preserve the original editable paragraph markup as the source-text sample.
                inner=target.select_one('[data-pptx-text]')
                samples[slot]=str(inner) if inner else item['text']['text']
                stage.string='{{ '+slot+' }}'
                target.replace_with(stage)
            else:
                runs=target.select('[data-pptx-run]')
                if not runs:raise ValueError(f'{uid}: no editable run')
                # Keep every run wrapper/style; only replace textual payloads.
                runs[0].string='{{ '+slot+' }}'
                runs[0]['style']=runs[0].get('style','')+';white-space:pre-wrap'
                for run in runs[1:]:run.string=''
                samples[slot]=item['text']['text']
        required=({'page_title','page_content','current_page_number'} if part=='content' else {part+'_'+n for n in ('title','subtitle','extra')})
        missing=required-set(config['slots'])
        visible_required=missing-({'current_page_number'} if part=='content' else {part+'_extra',part+'_subtitle'})
        if visible_required:raise ValueError(f'{part}: missing editable source binding {sorted(visible_required)}; author as synthesized instead')
        for slot in sorted(missing):
            # Original has no extra/subtitle/page number area: don't invent a visible one.
            hidden=soup.new_tag('span',attrs={'hidden':''});hidden.string='{{ '+slot+' }}';soup.main.append(hidden);samples[slot]=''
        text=str(soup)
        (output/f'{part}.html').write_text(text,encoding='utf-8')
        lock['pages'][part]=create_lock(text,slide)
        provenance[part]={'method':'adapted','source_pages':[slide['number']],'reason':'Measured source shapes preserved; text-only slot binding, no geometry/style redesign'}
    (output/'geometry-lock.json').write_text(json.dumps(lock,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'source-samples.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'source-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'output':str(output),'bound_pages':list(page_map),'remaining_pages':sorted(set(('cover','catalog','transition','content','ending'))-set(page_map))}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--page-map',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.source_dir.resolve(),args.output.resolve(),json.loads(args.page_map.read_text(encoding='utf-8-sig'))),ensure_ascii=False))
