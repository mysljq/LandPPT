"""Regression coverage for source units, group transforms, crops, fonts and locking."""
import importlib
import json
import re
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.util import Inches, Pt

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/clawpartner-suite-maker/scripts'


@pytest.fixture
def evidence(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    prepare=importlib.import_module('prepare_source')
    assets=importlib.import_module('assets')
    p=Presentation();p.slide_width=Inches(13.33333333);p.slide_height=Inches(7.5)
    s=p.slides.add_slide(p.slide_layouts[6])
    title=s.shapes.add_textbox(Inches(4),Inches(2),Inches(6),Inches(1))
    title.text='Source title';title.text_frame.paragraphs[0].font.size=Pt(48)
    subtitle=s.shapes.add_textbox(Inches(4),Inches(3),Inches(5),Inches(.5))
    subtitle.text='Source subtitle';subtitle.text_frame.paragraphs[0].runs[0].font.size=Pt(25)
    line=s.shapes.add_connector(1,0,Inches(1),p.slide_width,Inches(1));line.line.width=Pt(1);line.line.dash_style=MSO_LINE_DASH_STYLE.DASH
    image=tmp_path/'source.png';Image.new('RGB',(100,50),'red').save(image)
    picture=s.shapes.add_picture(str(image),Inches(7),Inches(3),Inches(2),Inches(1));picture.crop_left=.1;picture.crop_right=.2
    group=s.shapes.add_group_shape();child=group.shapes.add_textbox(Inches(1),Inches(4),Inches(3),Inches(1));child.text='Grouped';child.text_frame.paragraphs[0].runs[0].font.size=Pt(30)
    # Preserve visible group frame while changing the internal coordinate unit by 10x.
    for element in [group._element.find('.//{*}chOff'),group._element.find('.//{*}chExt'),child._element.find('.//{*}off'),child._element.find('.//{*}ext')]:
        for key,value in list(element.attrib.items()):element.set(key,str(round(int(value)/10)))
    path=tmp_path/'source.pptx';p.save(path)
    out=tmp_path/'source';store=assets.AssetStore(out)
    result=prepare.extract_pptx(path,out,store)
    result['assets']=store.mapping
    (out/'source.json').write_text(json.dumps(result),encoding='utf-8')
    return out,result


def test_points_are_scaled_once_and_paragraph_font_is_inherited(evidence):
    _,data=evidence
    title=next(i for i in data['slides'][0]['shapes'] if i['kind']=='text')
    assert title['text']['paragraphs'][0]['runs'][0]['font_size_px']==pytest.approx(64,abs=.001)
    assert title['bounds'][0]==pytest.approx(384,abs=.001)


def test_group_coordinate_units_do_not_scale_font(evidence):
    _,data=evidence
    child=next(i for i in data['slides'][0]['shapes'] if 'g' in i['layer'])
    assert child['bounds']==pytest.approx([96,384,288,96],abs=.002)
    assert child['text']['paragraphs'][0]['runs'][0]['font_size_px']==pytest.approx(40,abs=.001)
    assert child['transform'][0]==pytest.approx(1)


def test_full_width_dash_and_picture_crop_survive(evidence):
    out,data=evidence
    items=data['slides'][0]['shapes']
    line=next(i for i in items if i['kind']=='line')
    picture=next(i for i in items if i['kind']=='image')
    assert line['bounds']==pytest.approx([0,96,1280,0],abs=.002)
    assert line['line']['dash']=='dash'
    assert line['line']['width']==pytest.approx(4/3,abs=.001)
    assert picture['crop']==pytest.approx([.1,0,.2,0])
    markup=(out/'slides/001.html').read_text(encoding='utf-8')
    assert 'stroke-dasharray=' in markup and 'object-fit:fill' in markup


@pytest.fixture
def bound(evidence,tmp_path):
    out,data=evidence
    build=importlib.import_module('build_pptx_suite')
    texts=[i for i in data['slides'][0]['shapes'] if i['kind']=='text']
    suite=tmp_path/'suite'
    build.build(out,suite,{'cover':{'slide':1,'slots':{'cover_title':texts[0]['id'],'cover_subtitle':texts[1]['id']}}})
    return suite


@pytest.mark.parametrize('change', ['transform','font','dash','crop'])
def test_changes_to_source_styles_fail_lock(bound,change):
    locks=importlib.import_module('pptx_lock')
    text=(bound/'cover.html').read_text(encoding='utf-8')
    if change=='transform':
        def shifted(match):
            values=match[1].split(',');values[4]=str(float(values[4])+16)
            return 'matrix('+','.join(values)+')'
        text=re.sub(r'matrix\(([^)]+)\)',shifted,text,count=1)
    elif change=='font':text=text.replace('font-size:64px','font-size:60px')
    elif change=='dash':text=text.replace('stroke-dasharray=', 'changed-dasharray=')
    else:text=text.replace('object-fit:fill','object-fit:cover')
    assert text!=(bound/'cover.html').read_text(encoding='utf-8')
    with pytest.raises(ValueError,match='geometry/style changed'):
        locks.validate_lock(bound,{'cover':text})


def test_only_text_payloads_can_change_without_moving_source(bound):
    locks=importlib.import_module('pptx_lock')
    text=(bound/'cover.html').read_text(encoding='utf-8').replace('{{ cover_title }}','A different title')
    locks.validate_lock(bound,{'cover':text})
