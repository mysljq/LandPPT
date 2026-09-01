import base64
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_table_svg_opacity_smoke.html"
EXPECTED_PATCH_VERSION = "2026-09-01-svg-pattern-alpha-v48"
EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


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


def test_table_inherited_paint_and_svg_ancestor_opacity_are_preserved():
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
            page.wait_for_function("window.domToPptx && window.runTableSvgOpacitySmokeTest")
            result = page.evaluate("() => window.runTableSvgOpacitySmokeTest()")
        finally:
            browser.close()

    assert not errors
    assert result["patchVersion"] == EXPECTED_PATCH_VERSION

    with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["pptxBase64"]))) as pptx:
        root = ET.fromstring(pptx.read("ppt/slides/slide1.xml"))

    table = next(root.iter(f"{{{DRAWING_NS}}}tbl"))
    rows = list(table.findall(f"{{{DRAWING_NS}}}tr"))
    assert len(rows) == 4

    expected_row_fills = ["C00000", "F0F7FF", "FFFFFF", "F0F7FF"]
    for row, expected_fill in zip(rows, expected_row_fills):
        cells = row.findall(f"{{{DRAWING_NS}}}tc")
        assert len(cells) == 2
        for cell in cells:
            fill = cell.find(
                f"./{{{DRAWING_NS}}}tcPr/{{{DRAWING_NS}}}solidFill/"
                f"{{{DRAWING_NS}}}srgbClr"
            )
            assert fill is not None
            assert fill.get("val") == expected_fill

    # Body rows have only their authored bottom rule. Transparent/default
    # borders must not turn into dark lines on all four sides.
    for row_index, row in enumerate(rows[1:], start=1):
        for cell in row.findall(f"{{{DRAWING_NS}}}tc"):
            cell_props = cell.find(f"{{{DRAWING_NS}}}tcPr")
            assert cell_props is not None
            for side in ("lnL", "lnR", "lnT"):
                line = cell_props.find(f"{{{DRAWING_NS}}}{side}")
                assert line is not None
                assert line.find(f"{{{DRAWING_NS}}}noFill") is not None
            bottom = cell_props.find(f"{{{DRAWING_NS}}}lnB")
            assert bottom is not None
            if row_index < len(rows) - 1:
                color = bottom.find(f".//{{{DRAWING_NS}}}srgbClr")
                assert color is not None and color.get("val") == "EEEEEE"
            else:
                assert bottom.find(f"{{{DRAWING_NS}}}noFill") is not None

    # Parent opacity 0.1 must survive when the child SVG becomes a picture.
    alpha_amounts = [
        int(node.get("amt"))
        for node in root.iter(f"{{{DRAWING_NS}}}alphaModFix")
        if node.get("amt")
    ]
    assert 10_000 in alpha_amounts
    assert 8_000 not in alpha_amounts
