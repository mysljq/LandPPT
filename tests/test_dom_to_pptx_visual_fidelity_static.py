from pathlib import Path


BUNDLE = Path(__file__).parents[1] / "src" / "landppt" / "web" / "static" / "js" / "dom-to-pptx.bundle.js"


def test_visual_fidelity_guards_are_present():
    source = BUNDLE.read_text(encoding="utf-8")

    # Element opacity must affect native borders as well as fills.
    assert "function applyOpacityToLineOptions" in source
    assert "const borderLineOptions = hasUniformBorder" in source
    assert "function generateCompositeBorderSVG(w, h, radius, sides, opacity = 1)" in source
    assert "safeOpacity * bgColorObj.opacity" in source

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

    # Native PowerPoint gradients need extra stops to emulate CSS's
    # premultiplied-alpha interpolation rather than fading through gray.
    assert "function expandPremultipliedAlphaGradientStops" in source
    assert "startValue * startAlpha * (1 - t)" in source

    # Direct text nodes split from visual flex chips inherit CSS transforms and
    # use the pre-rotation dimensions rather than the transformed Range bbox.
    assert "function recoverUnrotatedSizeFromBoundingBox" in source
    assert "const rotation = getCumulativeTextRotation(parent, config.root)" in source

    # Display-text rasterization must use the resolved DrawingML font so a CSS
    # fallback such as PingFang SC -> Microsoft YaHei remains editable.
    assert "const resolvedFont = resolveExportFontFace(style.fontFamily, node, text)" in source
    assert "resolvedFontIsEditable" in source
    assert "/api/export/fonts/manifest" not in source
    assert "__LANDPPT_PPTX_FONT_MANIFEST__" not in source

    # html2canvas measures font baselines in the host document. Its temporary
    # img/span probes must be isolated from Tailwind's global reset rules.
    assert "host.setAttribute('data-html2canvas-font-metrics', '')" in source
    assert "host.attachShadow({ mode: 'closed' })" in source
    assert "element.style.setProperty('all', 'initial', 'important')" in source
    assert "body.removeChild(host)" in source

    # Markerless CSS lists need element traversal so generated dots and inline
    # badges are not flattened by the native bullet-paragraph optimization.
    assert "if (s.listStyleType === 'none') return true;" in source

    # Pseudo-element corner radii must preserve fixed lengths and each corner;
    # a long strip with large px radii must not be classified as an ellipse.
    assert "function getNativeCssCornerGeometry" in source
    assert "rectRadius: tl.rx * pxToInchScale" in source
    assert "function getNativeUniformBorderGeometry" in source
    assert "const safeRadius = Math.min(Math.max(0, Number(radius) || 0), w / 2, h / 2)" in source
    assert "const segment = expandPremultipliedAlphaGradientStops" in source
    assert "stops[fillIndex].pos = stops[anchor].pos" in source
    assert "function canIgnoreRoundedCardOverflow" in source
    assert "canIgnoreRoundedCardOverflow(child, childStyle, boundaryStyle)" in source
    assert "canIgnoreRoundedCardOverflow(node, style, parentStyle)" in source
    assert "...uniformBorderGeometry.options" in source
    assert "options.points = shapeOptions.points.map" in source
    assert "minDimension < 100" not in source
    assert "return { shapeType: 'custGeom', options: { points } };" in source
    assert "pseudoRadiusPx >= pseudoMinDimension / 2" not in source

    # Composite solid borders are tightly bounded native paths beneath text,
    # not full-card SVG pictures which intercept selection in PowerPoint.
    assert "function createNativeCompositeBorderItems" in source
    assert "items.push(...nativeCompositeBorders)" in source
    assert "objectName: `CSS border ${name} ${domOrder}`" in source
    assert "domOrder: domOrder + (nativeCompositeBorders ? 0.2 : 0)" in source
