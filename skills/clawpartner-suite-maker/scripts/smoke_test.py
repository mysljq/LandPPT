"""Self-contained smoke test: no repository fixtures, pytest, service or browser."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def run(work):
    source = work / 'input'
    source.mkdir()
    (source / 'mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="#246"/></svg>', encoding='utf-8')
    (source / 'input.html').write_text('<!doctype html><html><head><style>body{color:#223344;background:url(mark.svg)}</style></head><body><h1>Portable input</h1><img src="mark.svg"></body></html>', encoding='utf-8')
    from pptx import Presentation
    ppt = Presentation()
    slide = ppt.slides.add_slide(ppt.slide_layouts[5])
    slide.shapes.title.text = 'Portable PPTX input'
    ppt.save(str(source / 'input.ppt'))

    def command(script, *arguments):
        # Run CLI entrypoints from the fixture directory, never the Skill/repo root.
        completed = subprocess.run([sys.executable, '-B', str(SKILL / 'scripts' / script), *map(str, arguments)],
                                   cwd=source, capture_output=True, text=True, encoding='utf-8', check=True)
        return json.loads(completed.stdout)
    h = command('prepare_source.py', '--input', source / 'input.html', '--output', work / 'html-source')
    p = command('prepare_source.py', '--input', source / 'input.ppt', '--output', work / 'ppt-source')
    assert h['assets'] == 1 and h['kind'] == 'html', h
    assert p['kind'] == 'pptx', p
    extracted = json.loads((work / 'ppt-source/source.json').read_text(encoding='utf-8'))
    assert extracted['slides'][0]['shapes'][0]['text'] == 'Portable PPTX input'
    suite = work / 'suite'
    shutil.copytree(SKILL / 'assets/reference-suite', suite)
    shutil.copytree(work / 'html-source/assets', suite / 'assets')
    asset = next((suite / 'assets').iterdir()).name
    for part in ('cover', 'catalog', 'transition', 'content', 'ending'):
        target = suite / f'{part}.html'
        text = target.read_text(encoding='utf-8').replace('</body>', f'<img src="assets/{asset}" alt="test"></body>')
        target.write_text(text, encoding='utf-8')
    result = command('package_suite.py', '--suite-dir', suite, '--name', 'Portable smoke')
    payload = json.loads((suite / 'suite.json').read_text(encoding='utf-8'))
    assert 'header_footer' in payload and '{{ page_content }}' in payload['header_footer']
    assert f'assets/{asset}' in payload['cover']
    with zipfile.ZipFile(suite / 'suite.zip') as archive:
        assert archive.testzip() is None
        assert f'assets/{asset}' in archive.namelist()
    return {'status': 'passed', 'checks': ['HTML extraction and deduplication', 'OOXML with .ppt extension', 'five template slots and content stage', 'relative images in API JSON and ZIP'], 'work_dir': str(work), 'suite_zip': result['zip']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, help='Empty directory for retained evidence; otherwise temporary')
    args = parser.parse_args()
    if args.work_dir:
        work = args.work_dir.resolve()
        if work.exists() and any(work.iterdir()):
            parser.error('--work-dir must be empty')
        work.mkdir(parents=True, exist_ok=True)
        result = run(work)
    else:
        with tempfile.TemporaryDirectory(prefix='clawpartner-suite-smoke-') as temporary:
            result = run(Path(temporary))
            result['evidence'] = 'temporary workspace cleaned after success'
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
