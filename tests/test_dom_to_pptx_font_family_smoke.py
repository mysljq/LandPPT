import base64
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_font_family_smoke.html"
EXPECTED_PATCH_VERSION = "2026-08-31-font-fidelity-v34"
EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
WINDOWS_FONT_DIR = Path(r"C:\Windows\Fonts")


def _launch_browser(playwright):
    try:
        return playwright.chromium.launch()
    except Exception as chromium_exc:  # pragma: no cover - depends on local browser install
        if not EDGE_PATH.exists():
            pytest.skip(f"Chromium is not available for Playwright: {chromium_exc}")
        try:
            return playwright.chromium.launch(executable_path=str(EDGE_PATH))
        except Exception as edge_exc:
            pytest.skip(f"Neither Playwright Chromium nor system Edge is available: {edge_exc}")


def _font_data_url(path: Path) -> str:
    return "data:font/ttf;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def test_inline_georgia_font_and_variants_are_preserved_in_pptx():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local dependency install
        pytest.skip(f"Playwright is not installed: {exc}")

    variant_files = {
        "regular": (WINDOWS_FONT_DIR / "georgia.ttf", 400, "normal"),
        "bold": (WINDOWS_FONT_DIR / "georgiab.ttf", 700, "normal"),
        "italic": (WINDOWS_FONT_DIR / "georgiai.ttf", 400, "italic"),
        "boldItalic": (WINDOWS_FONT_DIR / "georgiaz.ttf", 700, "italic"),
    }
    if not all(font_path.exists() for font_path, _, _ in variant_files.values()):
        pytest.skip("Windows Georgia font variants are not available")

    font_manifest = [
        {
            "name": "Georgia",
            "url": _font_data_url(font_path),
            "type": "ttf",
            "weight": weight,
            "style": style,
        }
        for font_path, weight, style in variant_files.values()
    ]

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page_errors = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        try:
            page.goto(FIXTURE_PATH.resolve().as_uri(), wait_until="load")
            page.wait_for_function("window.domToPptx && window.runGeorgiaFontPptxSmokeTest")
            unembedded_result = page.evaluate("() => window.runGeorgiaFontPptxSmokeTest([])")
            result = page.evaluate("fonts => window.runGeorgiaFontPptxSmokeTest(fonts)", font_manifest)
        finally:
            browser.close()

    assert not page_errors
    assert result["patchVersion"] == EXPECTED_PATCH_VERSION
    assert result["computedFamily"].replace("\u00a0", " ").startswith("Georgia")

    unembedded_bytes = base64.b64decode(unembedded_result["pptxBase64"])
    with zipfile.ZipFile(io.BytesIO(unembedded_bytes)) as pptx:
        unembedded_slide_xml = pptx.read("ppt/slides/slide1.xml").decode("utf-8")
    assert 'typeface="Georgia"' in unembedded_slide_xml
    assert "Georgia Inline Segment" in unembedded_slide_xml

    pptx_bytes = base64.b64decode(result["pptxBase64"])
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as pptx:
        slide_xml = pptx.read("ppt/slides/slide1.xml").decode("utf-8")
        presentation_xml = pptx.read("ppt/presentation.xml").decode("utf-8")
        presentation_rels_xml = pptx.read("ppt/_rels/presentation.xml.rels").decode("utf-8")
        content_types_xml = pptx.read("[Content_Types].xml").decode("utf-8")
        embedded_font_files = [
            name for name in pptx.namelist()
            if name.startswith("ppt/fonts/") and name.endswith(".fntdata")
        ]
        svg_media = [
            pptx.read(name).decode("utf-8")
            for name in pptx.namelist()
            if name.startswith("ppt/media/") and name.endswith(".svg")
        ]

    assert 'typeface="Georgia"' in slide_xml
    assert "Georgia Regular 123" in slide_xml
    assert "Georgia Bold 456" in slide_xml
    assert "Georgia Italic 789" in slide_xml
    assert "Georgia Bold Italic" in slide_xml
    assert "Georgia Inline Segment" in slide_xml
    assert "2026" in slide_xml
    assert 'typeface="Georgia"' in presentation_xml
    for slot in variant_files:
        assert f"p:{slot}" in presentation_xml
    assert len(embedded_font_files) == 4

    embedded = result["fontDebug"]["embeddedFonts"]
    assert {entry["slot"] for entry in embedded if entry["status"] == "ok"} >= set(variant_files)

    drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    slide_root = ET.fromstring(slide_xml)
    year_runs = [
        run
        for run in slide_root.iter(f"{{{drawing_ns}}}r")
        if (
            run.find(f"{{{drawing_ns}}}t") is not None
            and run.find(f"{{{drawing_ns}}}t").text == "2026"
        )
    ]
    assert len(year_runs) == 2
    year_typefaces = {
        run.find(f"{{{drawing_ns}}}rPr")
        .find(f"{{{drawing_ns}}}latin")
        .get("typeface")
        for run in year_runs
    }
    assert year_typefaces == {"Arial", "Georgia"}
    georgia_run_props = next(
        run.find(f"{{{drawing_ns}}}rPr")
        for run in slide_root.iter(f"{{{drawing_ns}}}r")
        if (
            run.find(f"{{{drawing_ns}}}t") is not None
            and run.find(f"{{{drawing_ns}}}t").text == "Georgia Regular 123"
        )
    )
    font_child_order = [
        child.tag.rsplit("}", 1)[-1]
        for child in georgia_run_props
        if child.tag.rsplit("}", 1)[-1] in {"latin", "ea", "cs"}
    ]
    assert font_child_order == ["latin", "ea", "cs"]
    assert not any(
        "display-font-raster" in entry["reasons"]
        for entry in result["riskDebug"]
    )
    exact_text_values = [
        text_node.text
        for text_node in slide_root.iter(f"{{{drawing_ns}}}t")
    ]
    assert "1" in exact_text_values
    assert "2" in exact_text_values
    assert "CONTENTS" in exact_text_values
    assert "01" in exact_text_values
    assert "第 1 章" in exact_text_values
    assert "第 2 章" in exact_text_values
    assert "486个" in exact_text_values
    assert "8/20" in exact_text_values
    assert "大模型方向" in exact_text_values
    assert "低代码方向" in exact_text_values

    presentation_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ellipse_count = sum(
        1
        for geometry in slide_root.iter(f"{{{drawing_ns}}}prstGeom")
        if geometry.get("prst") == "ellipse"
    )
    assert ellipse_count >= 3
    assert any(
        dash.get("val") == "dash"
        for dash in slide_root.iter(f"{{{drawing_ns}}}prstDash")
    )
    alpha_values = {
        int(alpha.get("val"))
        for alpha in slide_root.iter(f"{{{drawing_ns}}}alpha")
        if alpha.get("val")
    }
    assert {8000, 10000, 12000}.issubset(alpha_values)

    padded_shape = next(
        shape
        for shape in slide_root.iter(f"{{{presentation_ns}}}sp")
        if any(
            text_node.text == "演示标题：部门工作情况汇报"
            for text_node in shape.iter(f"{{{drawing_ns}}}t")
        )
    )
    padded_body = padded_shape.find(f".//{{{drawing_ns}}}bodyPr")
    assert padded_body is not None
    assert int(padded_body.get("lIns")) == 114300

    assert any("<polygon" in svg and "45.000,0.000" in svg for svg in svg_media)
    assert not any("<feDropShadow" in svg for svg in svg_media)
    assert any(
        'fill="#C00000"' in svg
        and 'width="4"' in svg
        and 'fill="#E8E8E8"' in svg
        for svg in svg_media
    )
    assert not any(
        "<linearGradient" in svg and 'stroke="#E8E8E8"' in svg
        for svg in svg_media
    )
    assert any("polygon-svg" in entry["reasons"] for entry in result["riskDebug"])
    polygon_png = next(
        entry for entry in result["riskDebug"] if "polygon-png" in entry["reasons"]
    )
    assert polygon_png["captured"] is True
    assert not any("transformed-clipping" in entry["reasons"] for entry in result["riskDebug"])

    assert 'xmlns=""' not in presentation_rels_xml
    assert 'xmlns=""' not in content_types_xml
    assert 'embedTrueTypeFonts="1"' in presentation_xml
    assert 'saveSubsetFonts="1"' in presentation_xml

    transition_shapes = [
        shape
        for shape in slide_root.iter(f"{{{presentation_ns}}}sp")
        if any(text_node.text == "第 1 章" for text_node in shape.iter(f"{{{drawing_ns}}}t"))
    ]
    transition_layouts = [
        (
            int(shape.find(f".//{{{drawing_ns}}}off").get("x")),
            int(shape.find(f".//{{{drawing_ns}}}bodyPr").get("lIns")),
        )
        for shape in transition_shapes
    ]
    assert any(left >= 6572250 or inset == 381000 for left, inset in transition_layouts), transition_layouts

    progress_shape = next(
        shape
        for shape in slide_root.iter(f"{{{presentation_ns}}}sp")
        if any(text_node.text == "8/20" for text_node in shape.iter(f"{{{drawing_ns}}}t"))
    )
    assert progress_shape.find(f".//{{{drawing_ns}}}pPr").get("algn") == "r"

    for direction_title in ("大模型方向", "低代码方向"):
        direction_shape = next(
            shape
            for shape in slide_root.iter(f"{{{presentation_ns}}}sp")
            if any(
                text_node.text == direction_title
                for text_node in shape.iter(f"{{{drawing_ns}}}t")
            )
        )
        direction_body = direction_shape.find(f".//{{{drawing_ns}}}bodyPr")
        assert direction_body is not None
        assert direction_body.get("wrap") == "none"
