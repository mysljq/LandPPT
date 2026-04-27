import importlib.util
import io
import logging
import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
EXPORT_SUPPORT_PATH = ROOT / "src" / "landppt" / "web" / "route_modules" / "export_support.py"
WEB_DIR = ROOT / "src" / "landppt" / "web"
ROUTE_MODULES_DIR = WEB_DIR / "route_modules"


def _load_export_support_module():
    import landppt

    web_pkg = types.ModuleType("landppt.web")
    web_pkg.__path__ = [str(WEB_DIR)]
    route_modules_pkg = types.ModuleType("landppt.web.route_modules")
    route_modules_pkg.__path__ = [str(ROUTE_MODULES_DIR)]
    support_module = types.ModuleType("landppt.web.route_modules.support")
    support_module.logger = logging.getLogger("test.export_support")

    original_web = sys.modules.get("landppt.web")
    original_route_modules = sys.modules.get("landppt.web.route_modules")
    original_support = sys.modules.get("landppt.web.route_modules.support")
    sys.modules["landppt.web"] = web_pkg
    sys.modules["landppt.web.route_modules"] = route_modules_pkg
    sys.modules["landppt.web.route_modules.support"] = support_module
    setattr(landppt, "web", web_pkg)

    module_name = "landppt.web.route_modules._export_support_test"
    spec = importlib.util.spec_from_file_location(module_name, EXPORT_SUPPORT_PATH)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        if original_web is not None:
            sys.modules["landppt.web"] = original_web
            setattr(landppt, "web", original_web)
        else:
            sys.modules.pop("landppt.web", None)
            if hasattr(landppt, "web"):
                delattr(landppt, "web")

        if original_route_modules is not None:
            sys.modules["landppt.web.route_modules"] = original_route_modules
        else:
            sys.modules.pop("landppt.web.route_modules", None)

        if original_support is not None:
            sys.modules["landppt.web.route_modules.support"] = original_support
        else:
            sys.modules.pop("landppt.web.route_modules.support", None)


def test_image_pptx_export_request_validates_after_model_rebuild():
    module = _load_export_support_module()
    payload = module.ImagePPTXExportRequest.model_validate(
        {
            "slides": [
                {
                    "index": 1,
                    "html_content": "<div>slide</div>",
                    "title": "封面",
                }
            ],
            "images": [
                {
                    "index": 1,
                    "data": "base64-data",
                    "width": 1280,
                    "height": 720,
                }
            ],
        }
    )

    assert payload.slides is not None
    assert payload.slides[0]["index"] == 1
    assert payload.images is not None
    assert payload.images[0]["width"] == 1280


def test_html_zip_export_keeps_interactive_slide_html_without_duplicate_viewers():
    module = _load_export_support_module()
    project = SimpleNamespace(
        topic="Demo Deck",
        slides_data=[
            {
                "title": "Interactive",
                "html_content": """
<!DOCTYPE html>
<html>
<head><title>Interactive</title></head>
<body>
    <a id="externalLink" href="https://example.com/path">Open</a>
    <button id="runButton" onclick="window.clicked = true">Run</button>
    <script>window.loaded = true;</script>
</body>
</html>
""",
            },
            {
                "title": "Second",
                "html_content": "<main><button onclick=\"window.second = true\">Second</button></main>",
            },
        ],
    )

    zip_bytes = module._generate_html_export_sync(project, "http://localhost:8000")

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
        names = archive.namelist()
        assert names == ["index.html", "slides/slide_1.html", "slides/slide_2.html"]
        assert "slide_1.html" not in names
        assert names.count("slides/slide_1.html") == 1

        index_html = archive.read("index.html").decode("utf-8")
        assert 'src="slides/slide_1.html"' in index_html
        assert ".stage-shield" in index_html
        assert "pointer-events: none" in index_html
        assert "function installSlideFrameWheelBridge()" in index_html
        assert "frameDocument.addEventListener('wheel', handleProjectorWheel" in index_html
        assert "slideFrame.addEventListener('load', installSlideFrameWheelBridge)" in index_html
        assert "window.addEventListener('message'" in index_html
        assert "landppt-projector-wheel" in index_html
        assert "landppt-projector-key" in index_html
        assert "function shouldRevealUiForKey(e)" in index_html
        assert "ArrowLeft: true" in index_html
        assert "if (navigationKeys[key]) return false;" in index_html
        assert "if (shouldRevealUiForKey(e)) revealUi();" in index_html
        assert "function handleProjectorKey(key)" in index_html
        assert "input, textarea, select" in index_html

        first_slide = archive.read("slides/slide_1.html").decode("utf-8")
        assert 'href="https://example.com/path"' in first_slide
        assert 'onclick="window.clicked = true"' in first_slide
        assert "<script>window.loaded = true;</script>" in first_slide
        assert "window.parent.postMessage({ type: 'landppt-projector-wheel'" in first_slide
        assert "window.parent.postMessage({ type: 'landppt-projector-key'" in first_slide
        assert "window.addEventListener('keydown'" in first_slide
        assert "if (e.defaultPrevented) return;" in first_slide
        assert "'button'" in first_slide
        assert "'a[href]'" in first_slide
        assert "'[tabindex]:not([tabindex=\"-1\"])" in first_slide

        second_slide = archive.read("slides/slide_2.html").decode("utf-8")
        assert 'onclick="window.second = true"' in second_slide
        assert "window.parent.postMessage({ type: 'landppt-projector-wheel'" in second_slide
        assert "window.parent.postMessage({ type: 'landppt-projector-key'" in second_slide


def test_html_slide_bridge_adds_keyboard_bridge_when_wheel_marker_already_exists():
    module = _load_export_support_module()
    html = """
<html>
<body>
    <script>window.marker = 'landppt-projector-wheel';</script>
</body>
</html>
"""

    enhanced = module._inject_projector_child_wheel_bridge(html)

    assert "landppt-projector-wheel" in enhanced
    assert "landppt-projector-key" in enhanced
    assert enhanced.count("landppt-projector-wheel") == 1
