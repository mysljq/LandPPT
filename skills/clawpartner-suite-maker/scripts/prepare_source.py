"""Extract editable source evidence. Deliberately does not invent template designs."""
from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from pathlib import Path

from assets import AssetStore, rewrite_html


def extract_html(path, out, store):
    from bs4 import BeautifulSoup
    text = path.read_text(encoding='utf-8-sig')
    soup = BeautifulSoup(text, 'html.parser')
    base = path.resolve().as_uri()
    if soup.find('base', href=True):
        from urllib.parse import urljoin
        base = urljoin(base, soup.find('base')['href'])
    for tag in soup.find_all('base'):
        tag.decompose()
    for tag in soup.find_all(['script', 'iframe', 'object', 'embed']):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith('on'):
                del tag[attr]
    for link in soup.select('link[rel~="stylesheet"]'):
        css = store.stylesheet(link['href'], base)
        # Already resolved stylesheet URLs must not be resolved a second time.
        replacement = soup.new_tag('style')
        replacement.string = css
        link.replace_with(replacement)
        replacement['data-extracted'] = 'true'
    for style in soup.find_all('style'):
        if not style.has_attr('data-extracted'):
            style.string = store.css(style.get_text(), base)
        style.attrs.pop('data-extracted', None)
    # css() has already extracted stylesheet resources; inline style and images remain.
    def resolve(ref):
        if ref.split('#')[0] in store.mapping.values():
            return ref
        return store.reference(ref, base)
    normalized = rewrite_html(str(soup), resolve)
    (out / 'source.html').write_text(normalized, encoding='utf-8')
    return {'kind': 'html', 'text': soup.get_text(' ', strip=True),
            'colors': list(dict.fromkeys(re.findall(r'#[0-9a-fA-F]{3,8}\b', text))),
            'warnings': ['Source HTML is structural evidence; inspect the rendered source before designing.']}


def extract_pptx(path, out, store):
    from pptx import Presentation
    presentation = Presentation(str(path))
    sx, sy = 1280 / presentation.slide_width, 720 / presentation.slide_height
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith('ppt/media/') and not name.endswith('/'):
                store.save(archive.read(name), Path(name).suffix, name)
        # Keep complete XML evidence: themes, masters, layouts, shapes, relationships.
        for name in archive.namelist():
            if name.startswith('ppt/') and name.endswith(('.xml', '.rels')):
                dest = out / 'ooxml' / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(name))
    slides = []
    (out / 'slides').mkdir()
    for index, slide in enumerate(presentation.slides, 1):
        shapes, elements = [], []
        def visit(items, parent=None):
            from pptx.enum.shapes import MSO_SHAPE_TYPE
            for shape in items:
                rect = {'left': round(shape.left * sx, 2), 'top': round(shape.top * sy, 2),
                        'width': round(shape.width * sx, 2), 'height': round(shape.height * sy, 2)}
                item = {'name': shape.name, 'type': str(shape.shape_type), **rect}
                if parent:
                    item['group'] = parent
                style = ';'.join(f'{k}:{v}px' for k, v in rect.items())
                if shape.has_text_frame:
                    item['text'] = shape.text
                    item['runs'] = []
                    for paragraph in shape.text_frame.paragraphs:
                        for run in paragraph.runs:
                            item['runs'].append({'text': run.text, 'font': run.font.name,
                                                 'size_pt': run.font.size.pt if run.font.size else None,
                                                 'bold': run.font.bold})
                    elements.append(f'<div style="position:absolute;{style};white-space:pre-wrap">{html.escape(shape.text)}</div>')
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    image = shape.image
                    item['asset'] = store.save(image.blob, '.' + image.ext, f'slide{index}/{shape.shape_id}')
                    elements.append(f'<img src="../{item["asset"]}" style="position:absolute;{style};object-fit:contain">')
                shapes.append(item)
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    visit(shape.shapes, shape.name)
        visit(slide.shapes)
        slides.append({'number': index, 'shapes': shapes})
        (out / 'slides' / f'{index:03}.html').write_text(
            '<!doctype html><meta charset="utf-8"><body style="margin:0"><main style="position:relative;width:1280px;height:720px;overflow:hidden">' + ''.join(elements) + '</main>', encoding='utf-8')
    return {'kind': 'pptx', 'original_size_emu': [presentation.slide_width, presentation.slide_height],
            'slides': slides, 'warnings': ['Structural preview omits master/layout visuals, inherited fonts, charts, transforms and fills. Read ooxml and inspect original slides for fidelity.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    path, out = args.input.resolve(), args.output.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Output must be empty (preserves previous extraction)')
    if path.read_bytes()[:8] == bytes.fromhex('d0cf11e0a1b11ae1'):
        parser.error('Legacy binary PPT: convert to PPTX using LibreOffice/PowerPoint first')
    out.mkdir(parents=True, exist_ok=True)
    store = AssetStore(out)
    if zipfile.is_zipfile(path):
        result = extract_pptx(path, out, store)
    elif path.suffix.lower() in ('.html', '.htm'):
        result = extract_html(path, out, store)
    else:
        parser.error('Expected HTML or OOXML PowerPoint')
    result.update({'source': str(path), 'assets': store.mapping})
    (out / 'source.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(out), 'assets': len(set(store.mapping.values())), 'kind': result['kind']}))


if __name__ == '__main__':
    main()
