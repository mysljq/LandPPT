"""Protect measured source frames/styles against subsequent agent re-layout."""
from __future__ import annotations

import hashlib
import json
from bs4 import BeautifulSoup, NavigableString


def signature(node):
    clone=BeautifulSoup(str(node),'html.parser')
    for text in list(clone.find_all(string=True)):
        if isinstance(text,NavigableString):text.extract()
    return hashlib.sha256(str(clone).encode()).hexdigest()


def style_signature(soup):
    return hashlib.sha256('\n'.join(t.get_text() for t in soup.find_all('style')).encode()).hexdigest()


def create_lock(text, source_slide):
    soup=BeautifulSoup(text,'html.parser')
    source={i['id']:i for i in source_slide['shapes']}
    elements=[]
    for element in soup.select('[data-pptx-id]'):
        uid=element['data-pptx-id'];item=source[uid]
        entry={'id':uid,'kind':item['kind'],'bounds':item['bounds'],'markup_sha256':signature(element)}
        if item['kind']=='text':
            entry['font_sizes_px']=[r['font_size_px'] for p in item['text']['paragraphs'] for r in p['runs']]
            entry['font_families']=sorted(set(r['font'] for p in item['text']['paragraphs'] for r in p['runs']))
        if item['kind']=='image':entry.update(asset=item['asset'],crop=item['crop'])
        if item['kind']=='line':entry['line']=item['line']
        elements.append(entry)
    return {'source_slide':source_slide['number'],'styles_sha256':style_signature(soup),'elements':elements}


def validate_lock(root, pages):
    path=root/'geometry-lock.json'
    if not path.exists():return
    lock=json.loads(path.read_text(encoding='utf-8'))
    for part,expected in lock['pages'].items():
        if part not in pages:raise ValueError(f'Geometry lock references missing page: {part}')
        soup=BeautifulSoup(pages[part],'html.parser')
        if style_signature(soup)!=expected['styles_sha256']:
            raise ValueError(f'{part}: locked stylesheet changed; restore measured source CSS')
        actual=soup.select('[data-pptx-id]')
        if [e.get('data-pptx-id') for e in actual]!=[e['id'] for e in expected['elements']]:
            raise ValueError(f'{part}: locked source elements or stacking order changed')
        for element,entry in zip(actual,expected['elements']):
            if signature(element)!=entry['markup_sha256']:
                raise ValueError(f'{part}: source geometry/style changed: {entry["id"]}')
