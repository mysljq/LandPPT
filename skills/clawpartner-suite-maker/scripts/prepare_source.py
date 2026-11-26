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


def extract_pptx(path, out, store, native=None):
    from pptx import Presentation
    presentation = Presentation(str(path))
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith('ppt/media/') and not name.endswith('/'):
                store.save(archive.read(name), Path(name).suffix, name)
            if name.startswith('ppt/') and name.endswith(('.xml', '.rels')):
                dest = (out / 'ooxml' / name).resolve()
                if not dest.is_relative_to((out / 'ooxml').resolve()):
                    raise ValueError('OOXML path escapes extraction directory')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(name))
    from pptx_fidelity import extract
    return extract(presentation, out, store, native)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-reference', type=Path, help='Optional PowerPoint native-metrics.json')
    args = parser.parse_args()
    path, out = args.input.resolve(), args.output.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Output must be empty (preserves previous extraction)')
    if path.read_bytes()[:8] == bytes.fromhex('d0cf11e0a1b11ae1'):
        parser.error('Legacy binary PPT: convert to PPTX using LibreOffice/PowerPoint first')
    out.mkdir(parents=True, exist_ok=True)
    store = AssetStore(out)
    if zipfile.is_zipfile(path):
        native = json.loads(args.native_reference.read_text(encoding='utf-8-sig')) if args.native_reference else None
        result = extract_pptx(path, out, store, native)
    elif path.suffix.lower() in ('.html', '.htm'):
        result = extract_html(path, out, store)
    else:
        parser.error('Expected HTML or OOXML PowerPoint')
    result.update({'source': str(path), 'assets': store.mapping})
    (out / 'source.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(out), 'assets': len(set(store.mapping.values())), 'kind': result['kind']}))


if __name__ == '__main__':
    main()
