import base64
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_risk_subtree_smoke.html"
EXPECTED_PATCH_VERSION = "2026-09-01-premultiplied-gradient-v49"
EXPECTED_ASSET_VERSION = "20260901-premultiplied-gradient-v49"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _shape_text(shape):
    return "".join(node.text or "" for node in shape.iter(f"{{{DRAWING_NS}}}t"))


def _shape_geometry(shape):
    transform = shape.find(f"./{{{PRESENTATION_NS}}}spPr/{{{DRAWING_NS}}}xfrm")
    assert transform is not None
    offset = transform.find(f"{{{DRAWING_NS}}}off")
    extent = transform.find(f"{{{DRAWING_NS}}}ext")
    assert offset is not None and extent is not None
    return tuple(int(value) for value in (
        offset.get("x"), offset.get("y"), extent.get("cx"), extent.get("cy")
    ))


def test_dom_to_pptx_version_is_consistent_across_loaders():
    project_root = Path(__file__).parent.parent
    patch_version_files = [
        "src/landppt/web/static/js/dom-to-pptx.bundle.js",
        "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.exportRender.js",
        "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.exportBase.js",
        "src/landppt/web/static/js/pages/template/global_master/globalMasterTemplates.exportHelpers.js",
        "src/landppt/web/templates/project_slides_editor.html",
    ]
    asset_version_files = [
        "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.exportRender.js",
        "src/landppt/web/static/js/pages/template/global_master/globalMasterTemplates.exportHelpers.js",
        "src/landppt/web/static/js/pages/template/global_master/globalMasterTemplates.js",
        "src/landppt/web/templates/pages/project/project_slides_editor.html",
        "src/landppt/web/templates/pages/template/global_master_templates.html",
        "src/landppt/web/templates/project_slides_editor.html",
    ]

    for relative_path in patch_version_files:
        content = (project_root / relative_path).read_text(encoding="utf-8")
        assert EXPECTED_PATCH_VERSION in content, relative_path
        assert "2026-08-28-risk-subtree-v22" not in content, relative_path

    for relative_path in asset_version_files:
        content = (project_root / relative_path).read_text(encoding="utf-8")
        assert EXPECTED_ASSET_VERSION in content, relative_path
        assert "20260828-risk-subtree-v22" not in content, relative_path


def test_dom_to_pptx_risk_subtree_smoke():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local dependency install
        pytest.skip(f"Playwright is not installed: {exc}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as chromium_exc:  # pragma: no cover - depends on local browser install
            edge_path = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
            if not edge_path.exists():
                pytest.skip(f"Chromium is not available for Playwright: {chromium_exc}")
            try:
                browser = p.chromium.launch(executable_path=str(edge_path))
            except Exception as edge_exc:
                pytest.skip(f"Neither Playwright Chromium nor system Edge is available: {edge_exc}")

        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page_errors = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        try:
            page.goto(FIXTURE_PATH.resolve().as_uri(), wait_until="load")
            page.wait_for_function("window.domToPptx && window.runRiskSubtreePptxSmokeTest")
            result = page.evaluate("() => window.runRiskSubtreePptxSmokeTest()")
        finally:
            browser.close()

    assert not page_errors
    assert result["patchVersion"] == EXPECTED_PATCH_VERSION
    assert result["blobSize"] > 10_000
    assert result["editableLineCount"] >= 2
    assert result["editableHasHighlight"] is False
    assert result["svgTextLineCount"] >= 2
    assert result["allCapturesSucceeded"] is True
    assert result["riskCaptureCount"] >= 7
    assert result["hardShadowOverlayCount"] >= 1
    assert result["rootWasRasterized"] is False
    assert result["editableGridRisky"] is False
    assert result["editableCardRisky"] is False
    assert result["isolatedDecorationCount"] >= 1

    with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["pptxBase64"]))) as pptx:
        slide_xml = pptx.read("ppt/slides/slide1.xml")
    root = ET.fromstring(slide_xml)
    shapes = list(root.iter(f"{{{PRESENTATION_NS}}}sp"))
    tag_labels = {"高可用", "可扩展", "易维护", "故障自愈"}
    tag_text_shapes = [shape for shape in shapes if _shape_text(shape) in tag_labels]
    assert len(tag_text_shapes) == 4
    assert {_shape_text(shape) for shape in tag_text_shapes} == tag_labels
    tag_point_shapes = [shape for shape in shapes if _shape_text(shape) == "◆"]
    assert len(tag_point_shapes) == 4

    tag_background_shapes = []
    for shape in shapes:
        color = shape.find(
            f"./{{{PRESENTATION_NS}}}spPr/{{{DRAWING_NS}}}solidFill/"
            f"{{{DRAWING_NS}}}srgbClr"
        )
        if color is not None and color.get("val") == "21416B":
            tag_background_shapes.append(shape)
    assert len(tag_background_shapes) == 4

    # Every editable tag text box must sit inside exactly one native background
    # shape; duplicated screenshot/highlight layers used to break this relation.
    background_rects = [_shape_geometry(shape) for shape in tag_background_shapes]
    for text_shape in tag_text_shapes:
        tx, ty, tw, th = _shape_geometry(text_shape)
        matches = [
            (bx, by, bw, bh)
            for bx, by, bw, bh in background_rects
            if bx <= tx and by <= ty and bx + bw >= tx + tw and by + bh >= ty + th
        ]
        assert len(matches) == 1

    for point_shape, text_shape in zip(
        sorted(tag_point_shapes, key=lambda shape: _shape_geometry(shape)[0]),
        sorted(tag_text_shapes, key=lambda shape: _shape_geometry(shape)[0]),
    ):
        px, py, pw, ph = _shape_geometry(point_shape)
        tx, ty, tw, th = _shape_geometry(text_shape)
        assert px + pw <= tx
        assert abs((py + ph / 2) - (ty + th / 2)) <= 80_000
        matches = [
            (bx, by, bw, bh)
            for bx, by, bw, bh in background_rects
            if bx <= px and by <= py and bx + bw >= tx + tw and by + bh >= max(py + ph, ty + th)
        ]
        assert len(matches) == 1
    assert set(result["detectedReasons"]) >= {
        "mask",
        "complex-clip-path",
        "filter",
        "backdrop-filter",
        "mix-blend-mode",
        "multi-layer-gradient",
        "transformed-descendant-clipping",
        "complex-svg",
    }
    assert abs(result["mattePixel"][3] - 128) <= 2
    assert abs(result["mattePixel"][0] - 200) <= 3
    assert abs(result["mattePixel"][1] - 100) <= 3
    assert abs(result["mattePixel"][2] - 50) <= 3
