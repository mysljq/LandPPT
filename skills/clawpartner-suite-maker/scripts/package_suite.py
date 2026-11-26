"""Validate five authored templates, resolve assets, and create API JSON + ZIP."""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from assets import digest, rewrite_html

PARTS = ('cover', 'catalog', 'transition', 'content', 'ending')
SLOTS = {part: {part + '_' + suffix for suffix in ('title', 'subtitle', 'extra')}
         for part in PARTS if part != 'content'}
SLOTS['content'] = {'page_title', 'page_content', 'current_page_number'}
OPTIONAL = {'total_page_count', 'chapter_number', 'brand_org', 'brand_tagline', 'brand_attribution', 'brand_year'}
SLOT = re.compile(r'{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}')


def validate(pages, analysis):
    from bs4 import BeautifulSoup
    for part, text in pages.items():
        slots = set(SLOT.findall(text))
        missing = SLOTS[part] - slots
        unknown = slots - SLOTS[part] - OPTIONAL
        if missing or unknown:
            raise ValueError(f'{part}: missing slots {sorted(missing)}, unsupported slots {sorted(unknown)}')
        soup = BeautifulSoup(text, 'html.parser')
        if not soup.html or not soup.body:
            raise ValueError(f'{part}: expected standalone HTML with html/body')
        if soup.find(['script', 'iframe', 'object', 'embed', 'base']) or soup.select('link[rel~="stylesheet"]'):
            raise ValueError(f'{part}: scripts/embedded documents/base/external styles are not allowed')
        for tag in soup.find_all(True):
            if any(key.lower().startswith('on') for key in tag.attrs):
                raise ValueError(f'{part}: event handler is not allowed')
        css = '\n'.join(tag.get_text() for tag in soup.find_all('style'))
        if re.search(r'@import\b', css, re.I):
            raise ValueError(f'{part}: inline external CSS before packaging')
        if not re.search(r'width\s*:\s*1280px', css) or not re.search(r'height\s*:\s*720px', css):
            raise ValueError(f'{part}: expected explicit 1280x720 CSS canvas')
        entry = analysis.get('pages', {}).get(part, {})
        if entry.get('method') not in ('adapted', 'synthesized') or not entry.get('reason') or not isinstance(entry.get('source_pages'), list):
            raise ValueError(f'{part}: missing page provenance in design-analysis.json')
        if part == 'content':
            stages = soup.select('.suite-stage')
            if len(stages) != 1 or len(SLOT.findall(stages[0].get_text())) != 1 or not re.fullmatch(r'\s*{{\s*page_content\s*}}\s*', stages[0].get_text()):
                raise ValueError('content: expected unique .suite-stage containing only page_content')
            if len(re.findall(r'{{\s*page_content\s*}}', text)) != 1:
                raise ValueError('content: duplicate page_content')
            stage_css = '\n'.join(re.findall(r'\.suite-stage\s*\{([^}]*)}', css)) + ';' + stages[0].get('style', '')
            declarations = dict(re.findall(r'([\w-]+)\s*:\s*([^;]+)', stage_css))
            if declarations.get('position', '').strip() != 'absolute' or declarations.get('overflow', '').strip() != 'hidden':
                raise ValueError('content: stage needs absolute position and overflow:hidden')
            bounds = {}
            for key in ('left', 'top', 'width', 'height'):
                value = declarations.get(key, '').strip()
                if not re.fullmatch(r'\d+(?:\.\d+)?px', value):
                    raise ValueError(f'content: stage {key} must be explicit nonnegative px')
                bounds[key] = float(value[:-2])
            if bounds['width'] <= 0 or bounds['height'] <= 0 or bounds['left'] + bounds['width'] > 1280 or bounds['top'] + bounds['height'] > 720:
                raise ValueError('content: stage outside canvas')
    for key in ('palette', 'typography', 'layout'):
        if not analysis.get(key):
            raise ValueError(f'design-analysis.json missing {key}')


def package(args):
    root = args.suite_dir.resolve()
    pages = {p: (root / f'{p}.html').read_text(encoding='utf-8-sig') for p in PARTS}
    tokens = (root / 'design_token.txt').read_text(encoding='utf-8-sig').strip()
    if not tokens:
        raise ValueError('design_token.txt is empty')
    analysis = json.loads((root / 'design-analysis.json').read_text(encoding='utf-8-sig'))
    validate(pages, analysis)
    from pptx_lock import validate_lock
    source_kind=analysis.get('source_kind') or (analysis.get('source',{}).get('kind') if isinstance(analysis.get('source'),dict) else None)
    if source_kind=='pptx':
        if not (root/'geometry-lock.json').exists():
            raise ValueError('PPTX suites require geometry-lock.json from build_pptx_suite.py')
        lock=json.loads((root/'geometry-lock.json').read_text(encoding='utf-8'))
        adapted={p for p,info in analysis['pages'].items() if info['method']=='adapted'}
        if not adapted.issubset(lock['pages']):
            raise ValueError('Every adapted PPTX page must retain its source geometry lock')
    validate_lock(root,pages)
    records = {}

    def resolve(ref):
        if not ref or ref.startswith('#'):
            return ref
        parsed = urlparse(ref)
        if parsed.scheme or parsed.netloc or parsed.query:
            raise ValueError(f'Invalid local resource; extract to assets/ first: {ref[:120]}')
        path = (root / unquote(parsed.path)).resolve()
        if not path.is_relative_to(root / 'assets') or not path.is_file():
            raise ValueError(f'Invalid local resource; missing file or outside assets/: {ref}')
        relative = path.relative_to(root).as_posix()
        if relative not in records:
            records[relative] = {'path': relative, 'sha256': digest(path.read_bytes())}
        return relative + ('#' + parsed.fragment if parsed.fragment else '')

    # Resolve and check every file before writing any production template.
    rewritten = {part: rewrite_html(value, resolve) for part, value in pages.items()}
    payload = {'suite_name': args.name, 'description': args.description, 'tags': args.tags,
               'design_tokens': tokens,
               **{('header_footer' if p == 'content' else p): text for p, text in rewritten.items()}}
    for part, value in rewritten.items():
        (root / f'{part}.html').write_text(value, encoding='utf-8')
    manifest_path = root / 'assets-manifest.json'
    manifest_path.write_text(json.dumps(list(records.values()), ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'suite.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(root / 'suite.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in [*(f'{p}.html' for p in PARTS), 'design_token.txt', 'design-analysis.json', 'assets-manifest.json', 'suite.json']:
            archive.write(root / name, name)
        for name in ('geometry-lock.json','source-samples.json','source-provenance.json'):
            if (root/name).is_file():archive.write(root/name,name)
        for path in sorted((root / 'assets').rglob('*')) if (root / 'assets').exists() else []:
            if path.is_file() and path.resolve().is_relative_to(root):
                archive.write(path, path.relative_to(root).as_posix())
    return {'suite': str(root), 'zip': str(root / 'suite.zip'),
            'local_assets': len(records), 'validation': 'structural only; visual review required'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--description', default='')
    parser.add_argument('--tags', nargs='*', default=[])
    args = parser.parse_args()
    print(json.dumps(package(args), ensure_ascii=False))


if __name__ == '__main__':
    main()
