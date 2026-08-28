from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_risk_subtree_smoke.html"
EXPECTED_PATCH_VERSION = "2026-08-28-risk-subtree-v22"
EXPECTED_ASSET_VERSION = "20260828-risk-subtree-v22"


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
        assert "2026-04-25-layer-clip-v21" not in content, relative_path

    for relative_path in asset_version_files:
        content = (project_root / relative_path).read_text(encoding="utf-8")
        assert EXPECTED_ASSET_VERSION in content, relative_path
        assert "20260425-layer-clip-v21" not in content, relative_path


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
    assert result["svgTextLineCount"] >= 2
    assert result["allCapturesSucceeded"] is True
    assert result["riskCaptureCount"] >= 7
    assert result["rootWasRasterized"] is False
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
