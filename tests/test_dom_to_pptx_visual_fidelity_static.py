from pathlib import Path


BUNDLE = Path(__file__).parents[1] / "src" / "landppt" / "web" / "static" / "js" / "dom-to-pptx.bundle.js"


def test_visual_fidelity_guards_are_present():
    source = BUNDLE.read_text(encoding="utf-8")

    # Element opacity must affect native borders as well as fills.
    assert "function applyOpacityToLineOptions" in source
    assert "const borderLineOptions = hasUniformBorder" in source
    assert "function generateCompositeBorderSVG(w, h, radius, sides, opacity = 1)" in source
    assert "bgColorObj.opacity * safeOpacity" in source

    # SVG rings depend on dash geometry; dropping these properties turns an
    # 85% progress ring into a complete circle.
    assert "'stroke-dasharray'" in source
    assert "'stroke-dashoffset'" in source
    assert "target.style.setProperty(prop, val)" in source
    assert "const svgImageRotation = node.parentElement" in source
    assert "rotate: svgImageRotation" in source

    # Rounded items in flex rows are split into a visual shape and editable
    # text, preventing sibling tags from being flattened/stacked together.
    assert "const isFlexChip" in source
    assert "!isFlexChip" in source
    assert "Leaf chips/tags inside a flex row" in source
    assert "sanitizeTextRunHighlight(textOptions, style, true)" in source

    # A transformed decoration that is already clipped by a card must not make
    # the enclosing card grid one large raster image. Capture only that leaf.
    assert "function clipDescendantRectThroughIntermediateAncestors" in source
    assert "function isDecorativeTransformedLeaf" in source
    assert "function captureClippedDecorativeLeafVisual" in source
    assert "isolated-transformed-clipping" in source
