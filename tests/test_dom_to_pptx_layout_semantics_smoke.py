import base64
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_layout_semantics_smoke.html"
EXPECTED_PATCH_VERSION = "2026-08-31-font-fidelity-v34"
EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _launch_browser(playwright):
    try:
        return playwright.chromium.launch()
    except Exception as chromium_exc:  # pragma: no cover
        if not EDGE_PATH.exists():
            pytest.skip(f"Chromium is not available for Playwright: {chromium_exc}")
        try:
            return playwright.chromium.launch(executable_path=str(EDGE_PATH))
        except Exception as edge_exc:
            pytest.skip(f"Neither Playwright Chromium nor system Edge is available: {edge_exc}")


def _shape_text(shape):
    return "".join(node.text or "" for node in shape.iter(f"{{{DRAWING_NS}}}t"))


def _shape_for_text(root, text):
    return next(
        shape
        for shape in root.iter(f"{{{PRESENTATION_NS}}}sp")
        if _shape_text(shape) == text
    )


def _shape_x(shape):
    return int(shape.find(f".//{{{DRAWING_NS}}}off").get("x"))


def test_block_lines_flex_layout_empty_dots_and_animation_snapshot_are_preserved():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Playwright is not installed: {exc}")

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        try:
            page.goto(FIXTURE_PATH.resolve().as_uri(), wait_until="load")
            page.wait_for_function("window.domToPptx && window.runLayoutSemanticsSmokeTest")
            result = page.evaluate("() => window.runLayoutSemanticsSmokeTest()")
        finally:
            browser.close()

    assert not errors
    assert result["patchVersion"] == EXPECTED_PATCH_VERSION
    assert float(result["beforeState"]["opacity"]) < 0.01
    assert abs(float(result["afterState"]["opacity"]) - float(result["beforeState"]["opacity"])) < 0.01
    assert result["afterState"]["backgroundColor"] == result["beforeState"]["backgroundColor"]
    assert result["afterState"]["borderColor"] == result["beforeState"]["borderColor"]

    with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["pptxBase64"]))) as pptx:
        slide_xml = pptx.read("ppt/slides/slide1.xml").decode("utf-8")
        svg_media = [
            pptx.read(name).decode("utf-8", errors="ignore")
            for name in pptx.namelist()
            if name.startswith("ppt/media/") and name.endswith(".svg")
        ]
    root = ET.fromstring(slide_xml)

    catalog = _shape_for_text(root, "室组人员管理TEAM MANAGEMENT")
    catalog_paragraphs = catalog.findall(f".//{{{DRAWING_NS}}}p")
    assert len(catalog_paragraphs) == 2
    assert "室组人员管理" in _shape_text(catalog_paragraphs[0])
    assert "TEAM MANAGEMENT" in _shape_text(catalog_paragraphs[1])

    solid_colors = {
        color.get("val")
        for color in root.iter(f"{{{DRAWING_NS}}}srgbClr")
        if color.get("val")
    }
    assert {"22C55E", "EF4444"}.issubset(solid_colors)
    ellipse_colors = set()
    for shape in root.iter(f"{{{PRESENTATION_NS}}}sp"):
        geometry = shape.find(f".//{{{DRAWING_NS}}}prstGeom")
        fill = shape.find(f".//{{{DRAWING_NS}}}solidFill/{{{DRAWING_NS}}}srgbClr")
        if geometry is not None and geometry.get("prst") == "ellipse" and fill is not None:
            ellipse_colors.add(fill.get("val"))
    assert {"22C55E", "EF4444"}.issubset(ellipse_colors)

    assert "EDE8DC" in solid_colors
    assert "CDC7B8" in solid_colors

    number = _shape_for_text(root, "01")
    copy = _shape_for_text(root, "建设背景：这里保留编号与正文之间的真实间隔")
    assert _shape_x(copy) - _shape_x(number) >= 200_000

    progress_label = _shape_for_text(root, "完成进度")
    progress_value = _shape_for_text(root, "40%")
    assert _shape_x(progress_value) - _shape_x(progress_label) >= 3_500_000

    year = _shape_for_text(root, "176")
    year_body = year.find(f".//{{{DRAWING_NS}}}bodyPr")
    assert year_body is not None
    assert year_body.get("wrap") == "none"

    evolution = _shape_for_text(root, "EVOLUTION")
    evolution_transform = evolution.find(f".//{{{DRAWING_NS}}}xfrm")
    evolution_body = evolution.find(f".//{{{DRAWING_NS}}}bodyPr")
    assert evolution_transform is not None
    assert evolution_transform.get("rot") == "5400000"
    assert evolution_body is not None
    assert evolution_body.get("wrap") == "none"
    assert any(
        "<polygon" in svg and "#B8763D" in svg.upper()
        for svg in svg_media
    )
