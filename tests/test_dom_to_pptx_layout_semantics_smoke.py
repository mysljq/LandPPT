import base64
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_layout_semantics_smoke.html"
EXPECTED_PATCH_VERSION = "2026-09-01-premultiplied-gradient-v49"
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

    # Keep gradient angles in the canonical 0..360-degree range. CSS
    # directions such as `to top` used to become negative OOXML angles, which
    # causes some Office versions to repair/remove slide content on open.
    gradient_angles = [int(lin.get("ang", "0")) for lin in root.iter(f"{{{DRAWING_NS}}}lin")]
    assert gradient_angles
    assert all(0 <= angle <= 21_600_000 for angle in gradient_angles)
    assert 16_200_000 in gradient_angles  # `linear-gradient(to top, ...)`

    # CSS uses premultiplied-alpha interpolation. The midpoint of opaque white
    # -> transparent black must therefore remain white at 50% alpha, not gray.
    corrected_midpoints = [
        stop
        for stop in root.iter(f"{{{DRAWING_NS}}}gs")
        if stop.get("pos") == "50000"
        and (color := stop.find(f"{{{DRAWING_NS}}}srgbClr")) is not None
        and color.get("val") == "FFFFFF"
        and (alpha := color.find(f"{{{DRAWING_NS}}}alpha")) is not None
        and alpha.get("val") == "50000"
    ]
    assert corrected_midpoints

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

    strike_shape = _shape_for_text(root, "铺设铁轨的工人")
    strike_run = strike_shape.find(f".//{{{DRAWING_NS}}}rPr")
    assert strike_run is not None
    assert strike_run.get("strike") == "sngStrike"

    insight_label = _shape_for_text(root, "蓝海洞察")
    insight_fill = insight_label.find(f".//{{{DRAWING_NS}}}solidFill/{{{DRAWING_NS}}}srgbClr")
    assert insight_fill is not None
    assert insight_fill.get("val") in {"F5F2EC", "B8763D"}

    assert any(
        dash.get("val") in {"dash", "sysDash"}
        for dash in root.iter(f"{{{DRAWING_NS}}}prstDash")
    )

    card_copy = _shape_for_text(root, "卡片正文内容，用于验证文本框不会重复叠加 CSS 外边距。")
    assert card_copy.find(f".//{{{DRAWING_NS}}}spcAft") is None

    rotated_copy = _shape_for_text(root, "继承父级旋转")
    rotated_transform = rotated_copy.find(f".//{{{DRAWING_NS}}}xfrm")
    assert rotated_transform is not None
    assert rotated_transform.get("rot") in {"-120000", "2146800000"}

    tracked_label = _shape_for_text(root, "MANAGEMENT")
    tracked_transform = tracked_label.find(f".//{{{DRAWING_NS}}}xfrm")
    assert tracked_transform is not None
    assert tracked_transform.get("rot") in {"-120000", "2146800000"}

    hard_shadow_shapes = []
    for shape in root.iter(f"{{{PRESENTATION_NS}}}sp"):
        fill = shape.find(f".//{{{DRAWING_NS}}}solidFill/{{{DRAWING_NS}}}srgbClr")
        line = shape.find(f".//{{{DRAWING_NS}}}ln")
        if fill is not None and fill.get("val") == "123ABC" and line is not None:
            hard_shadow_shapes.append(shape)
    assert hard_shadow_shapes

    assert any(
        color.get("val") == "0A7C55"
        for color in root.iter(f"{{{DRAWING_NS}}}srgbClr")
    )

    gradient_border_shapes = []
    for shape in root.iter(f"{{{PRESENTATION_NS}}}sp"):
        line_color = shape.find(
            f".//{{{DRAWING_NS}}}ln/{{{DRAWING_NS}}}solidFill/{{{DRAWING_NS}}}srgbClr"
        )
        fill = shape.find(f".//{{{DRAWING_NS}}}solidFill")
        if (
            line_color is not None
            and line_color.get("val") == "0A7C55"
            and fill is None
        ):
            gradient_border_shapes.append(shape)
    assert gradient_border_shapes

    block_copy = _shape_for_text(root, "8/20+后续正文必须另起一行")
    block_paragraphs = block_copy.findall(f".//{{{DRAWING_NS}}}p")
    assert len(block_paragraphs) == 2
    assert _shape_text(block_paragraphs[0]) == "8/20+"
    assert _shape_text(block_paragraphs[1]) == "后续正文必须另起一行"

    flex_copy = _shape_for_text(root, "第一行较长文本，自动换行后仍然保持左对齐，而不是错误居中。")
    flex_paragraph = flex_copy.find(f".//{{{DRAWING_NS}}}pPr")
    assert flex_paragraph is not None
    assert flex_paragraph.get("algn") != "ctr"
