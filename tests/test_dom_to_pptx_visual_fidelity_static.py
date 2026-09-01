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

    # Inline ::before/::after glyphs (for example tag bullets) are anchored to
    # the live text Range instead of the element's outer top-left corner.
    assert "function getNodeContentRangeRects" in source
    assert "anchorContentRect.left - nodeRect.left - pseudoMarginRight" in source
    assert "anchorTop + (anchorContentRect.height - renderedHeight) / 2" in source

    # Native tables must materialize CSS row/section backgrounds on each PPT
    # cell and pass borders using PptxGenJS's [top, right, bottom, left] form.
    assert "function getEffectiveTableCellBackground" in source
    assert "getTableCellRelativeOpacity" in source
    assert "borderTop || { type: 'none' }" in source
    assert "type: dash" in source

    # SVG pictures inherit opacity from their HTML ancestors. The SVG's own
    # opacity is already represented in the raster and must not be doubled.
    assert "function getAncestorOpacityMultiplier" in source
    assert "function applyOpacityToImageOptions" in source
    assert "svgAncestorOpacity" in source
    assert "function shouldBakeComplexSvgAncestorOpacity" in source
    assert "ctx.globalAlpha = opacityMultiplier" in source
