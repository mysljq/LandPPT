import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_editor_slideshow_shield_does_not_block_slide_interactions():
    template = _read("src/landppt/web/templates/pages/project/project_slides_editor.html")
    css = _read("src/landppt/web/static/css/pages/project/slides_editor/projectSlidesEditor.css")

    assert 'id="slideshowShield"' in template
    assert re.search(
        r"\.slideshow-shield\s*\{[^}]*pointer-events\s*:\s*none",
        css,
        flags=re.DOTALL,
    )


def test_editor_slideshow_bridges_iframe_wheel_navigation():
    script = _read(
        "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.slideshow.js"
    )

    assert "function installSlideshowFrameWheelBridge(iframe)" in script
    assert "frameDoc.addEventListener('wheel', handleSlideshowFrameWheel" in script
    assert "installSlideshowFrameWheelBridge(iframe);" in script
    assert "function shouldPreserveSlideshowWheelTarget(target, deltaY)" in script
    assert "input, textarea, select" in script
