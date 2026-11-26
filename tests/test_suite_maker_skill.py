"""Behavior checks for extraction and self-contained local asset packages."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills' / 'clawpartner-suite-maker' / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    # Scope script import wiring to this test; do not alter global search paths.
    monkeypatch.setitem(sys.modules, 'assets', load('assets'))
    return load('assets'), load('prepare_source'), load('package_suite')


def author_fixture(root, package):
    (root / 'assets').mkdir()
    (root / 'assets' / 'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    for part in package.PARTS:
        slots = ' '.join('{{ ' + s + ' }}' for s in sorted(package.SLOTS[part]))
        if part == 'content':
            slots = '{{ page_title }}<main class="suite-stage">{{ page_content }}</main>{{ current_page_number }}'
        text = '<!doctype html><html><head><meta charset="utf-8"><style>html,body{width:1280px;height:720px;overflow:hidden}.suite-stage{position:absolute;left:80px;top:140px;width:1120px;height:500px;overflow:hidden} .logo{background:url("assets/logo.svg")}</style></head><body><img src="assets/logo.svg">' + slots + '</body></html>'
        (root / f'{part}.html').write_text(text, encoding='utf-8')
    (root / 'design_token.txt').write_text('Primary #6657F5; font Arial; body 22px; gutter 80px.', encoding='utf-8')
    analysis = {'palette': ['#6657F5'], 'typography': {'body': 22}, 'layout': {'gutter': 80},
                'pages': {p: {'method': 'synthesized', 'source_pages': [], 'reason': 'Test authored layout'} for p in package.PARTS}}
    (root / 'design-analysis.json').write_text(json.dumps(analysis), encoding='utf-8')


def options(root, **changes):
    defaults = dict(suite_dir=root, name='Test', description='', tags=[])
    return argparse.Namespace(**(defaults | changes))


def test_nested_stylesheets_data_and_srcset(tmp_path, modules):
    assets, prepare, _ = modules
    source = tmp_path / 'source'
    (source / 'css').mkdir(parents=True)
    (source / 'logo.svg').write_text('<svg/>')
    (source / 'css' / 'one.css').write_text('@import "two.css"; .a{background:url(../logo.svg)}')
    (source / 'css' / 'two.css').write_text('.b{background:url(../logo.svg)}')
    data_uri = 'data:image/png;base64,' + base64.b64encode(b'test-png').decode()
    path = source / 'index.html'
    path.write_text('<link rel="stylesheet" href="css/one.css"><img src="logo.svg" srcset="logo.svg 1x, ' + data_uri + ' 2x"><script>alert(1)</script>', encoding='utf-8')
    out = tmp_path / 'extracted'
    store = assets.AssetStore(out)
    prepare.extract_html(path, out, store)
    normalized = (out / 'source.html').read_text(encoding='utf-8')
    assert '@import' not in normalized and '<script' not in normalized
    assert 'data:image' not in normalized and 'logo.svg' not in normalized
    assert len(list((out / 'assets').iterdir())) == 2
    assert '1x' in normalized and '2x' in normalized


def test_actual_inputs(tmp_path, modules):
    assets, prepare, _ = modules
    repo = SCRIPTS.parents[2]
    html_out, ppt_out = tmp_path / 'html', tmp_path / 'ppt'
    h = prepare.extract_html(repo / 'suite_maker/html/test_html.html', html_out, assets.AssetStore(html_out))
    p = prepare.extract_pptx(repo / 'suite_maker/ppt/test_ppt.ppt', ppt_out, assets.AssetStore(ppt_out))
    assert h['kind'] == 'html' and len(list((html_out / 'assets').iterdir())) == 6
    assert len(p['slides']) == 5
    assert list((ppt_out / 'ooxml/ppt/theme').glob('*.xml'))


def test_relative_images_in_html_json_and_zip(tmp_path, modules):
    _, _, package = modules
    author_fixture(tmp_path, package)
    package.package(options(tmp_path))
    payload = json.loads((tmp_path / 'suite.json').read_text(encoding='utf-8'))
    assert 'src="assets/logo.svg"' in payload['header_footer']
    assert 'src="assets/logo.svg"' in (tmp_path / 'content.html').read_text(encoding='utf-8')
    with zipfile.ZipFile(tmp_path / 'suite.zip') as archive:
        assert 'assets/logo.svg' in archive.namelist()
        assert 'suite.zip' not in archive.namelist()


def test_missing_image_does_not_mutate_templates(tmp_path, modules):
    _, _, package = modules
    author_fixture(tmp_path, package)
    path = tmp_path / 'ending.html'
    path.write_text(path.read_text(encoding='utf-8').replace('assets/logo.svg', 'assets/missing.svg'), encoding='utf-8')
    before = {p: p.read_bytes() for p in tmp_path.glob('*.html')}
    with pytest.raises(ValueError, match='Invalid local resource'):
        package.package(options(tmp_path))
    assert all(p.read_bytes() == value for p, value in before.items())
    assert not (tmp_path / 'suite.zip').exists()



@pytest.mark.parametrize('ref', ['https://example.test/logo.svg', '//example.test/logo.svg',
                                'data:image/svg+xml;base64,PHN2Zy8+', '../outside.svg'])
def test_nonlocal_resources_rejected_before_any_write(tmp_path, modules, ref):
    _, _, package = modules
    author_fixture(tmp_path, package)
    path = tmp_path / 'ending.html'
    path.write_text(path.read_text(encoding='utf-8').replace('assets/logo.svg', ref), encoding='utf-8')
    before = {p: p.read_bytes() for p in tmp_path.glob('*.html')}
    with pytest.raises(ValueError, match='Invalid local resource'):
        package.package(options(tmp_path))
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not (tmp_path / 'suite.json').exists()


def test_relative_fragment_deduplication_and_fresh_manifest(tmp_path, modules):
    assets, _, package = modules
    author_fixture(tmp_path, package)
    path = tmp_path / 'cover.html'
    path.write_text(path.read_text(encoding='utf-8').replace('assets/logo.svg', './assets/logo.svg#symbol'), encoding='utf-8')
    (tmp_path / 'assets-manifest.json').write_text('[{"url":"https://old.example.test/image"}]', encoding='utf-8')
    package.package(options(tmp_path))
    package.package(options(tmp_path))
    manifest = json.loads((tmp_path / 'assets-manifest.json').read_text(encoding='utf-8'))
    assert manifest == [{'path': 'assets/logo.svg', 'sha256': assets.digest((tmp_path / 'assets/logo.svg').read_bytes())}]
    assert 'assets/logo.svg#symbol' in path.read_text(encoding='utf-8')
    with zipfile.ZipFile(tmp_path / 'suite.zip') as archive:
        assert archive.read('assets/logo.svg') == (tmp_path / 'assets/logo.svg').read_bytes()
        assert archive.testzip() is None
