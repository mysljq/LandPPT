const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const PROJECT_ID = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';

function readSlideHtml(index) {
  const db = new DatabaseSync(path.join(process.cwd(), 'landppt.db'), { readOnly: true });
  try {
    return db.prepare(
      'select html_content from slide_data where project_id = ? and slide_index = ?'
    ).get(PROJECT_ID, index).html_content;
  } finally {
    db.close();
  }
}

async function exportPage(browser, html, selector) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  try {
  await page.setContent(html);
  const geometry = await page.evaluate((targetSelector) => {
    const root = document.querySelector('.suite-canvas') || document.body;
    const target = document.querySelector(targetSelector);
    const rootRect = root.getBoundingClientRect();
    const rect = target.getBoundingClientRect();
    const style = getComputedStyle(target);
    return {
      rootWidth: rootRect.width,
      x: rect.left - rootRect.left,
      y: rect.top - rootRect.top,
      width: rect.width,
      height: rect.height,
      opacity: Number(style.opacity),
      borderTopStyle: style.borderTopStyle,
    };
  }, selector);
  await page.addScriptTag({
    path: path.join(process.cwd(), 'src/landppt/web/static/js/dom-to-pptx.bundle.js'),
  });
  const result = await page.evaluate(async () => {
    const root = document.querySelector('.suite-canvas') || document.body;
    const blob = await domToPptx.exportToPptx(root, { skipDownload: true, autoEmbedFonts: false });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 32768) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
    }
    return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
  });
  const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
  const exported = {
    geometry,
    version: result.version,
    zip,
    xml: await zip.file('ppt/slides/slide1.xml').async('string'),
    presentation: await zip.file('ppt/presentation.xml').async('string'),
  };
  return exported;
  } finally {
    await page.close();
  }
}

function emuScale(result) {
  const width = Number(result.presentation.match(/<p:sldSz[^>]*cx="(\d+)"/)[1]);
  return width / result.geometry.rootWidth;
}

async function main() {
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({
    ...(fs.existsSync(edge) ? { executablePath: edge } : {}),
    headless: true,
  });
  try {
    console.log('checking page 35 gradient');
    const gradient = await exportPage(browser, readSlideHtml(34), '.deco-accent');
    assert.equal(gradient.version, '2026-09-08-shadow-direction-fix-v104');
    const scale = emuScale(gradient);
    const gradientShapes = [...gradient.xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)]
      .map((match) => match[0])
      .filter((shape) => shape.includes('<a:gradFill'));
    const accent = gradientShapes.find((shape) => {
      const extent = shape.match(/<a:ext cx="(\d+)" cy="(\d+)"/);
      return extent &&
        Math.abs(Number(extent[1]) - gradient.geometry.width * scale) < 2000 &&
        Math.abs(Number(extent[2]) - gradient.geometry.height * scale) < 2000;
    });
    assert.ok(accent, 'page 35 decorative gradient must remain a native gradient');
    const alphaValues = [...accent.matchAll(/<a:alpha val="(\d+)"/g)].map((match) => Number(match[1]));
    assert.ok(alphaValues.length >= 2, 'gradient must contain alpha-bearing stops');
    assert.ok(Math.max(...alphaValues) <= 40001, 'element opacity must multiply every gradient stop');
    assert.equal(Math.min(...alphaValues), 0, 'transparent gradient endpoint must remain transparent');

    console.log('checking page 36 dashed divider');
    const dashed = await exportPage(browser, readSlideHtml(35), '.works-list');
    assert.equal(dashed.geometry.borderTopStyle, 'dashed');
    const dashedShape = [...dashed.xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)]
      .map((match) => match[0])
      .find((shape) => shape.includes('CSS dashed border top'));
    assert.ok(dashedShape, 'page 36 top divider must be exported as a native line');
    assert.match(dashedShape, /<a:prstDash val="dash"\/>/, 'CSS dashed must remain dashed');
    const dashedExtent = dashedShape.match(/<a:ext cx="(\d+)" cy="(\d+)"/);
    assert.ok(dashedExtent && Math.abs(Number(dashedExtent[1]) - dashed.geometry.width * emuScale(dashed)) < 3000,
      'dashed divider width must match the live DOM');

    const styleFixture = `
      <style>
        *{box-sizing:border-box}body{margin:0}.suite-canvas{width:1280px;height:720px;padding:40px}
        .rule{width:300px;height:36px;margin-bottom:14px}
        .dash{border-top:2px dashed #123456}.dot{border-top:3px dotted #234567}
        .double{border-top:6px double #345678}.groove{border-top:6px groove #456789}
        .ridge{border-top:6px ridge #456789}.inset{border-top:6px inset #456789}
        .outset{border-top:6px outset #456789}
        .uniform-dash{border:2px dashed #56789A}.uniform-dot{border:3px dotted #6789AB}
        .uniform-double{border:6px double #789ABC}
        .rounded-mixed{border:4px solid #789ABC;border-top-style:dashed;border-right-style:dotted;
          border-bottom-style:double;border-radius:10px}
      </style>
      <div class="suite-canvas">
        <div class="rule dash"></div><div class="rule dot"></div><div class="rule double"></div>
        <div class="rule groove"></div><div class="rule ridge"></div><div class="rule inset"></div>
        <div class="rule outset"></div><div class="rule rounded-mixed"></div><div class="rule uniform-dash"></div>
        <div class="rule uniform-dot"></div><div class="rule uniform-double"></div>
      </div>`;
    console.log('checking general CSS border styles');
    const fixture = await exportPage(browser, styleFixture, '.dash');
    assert.match(fixture.xml, /CSS dashed border top/);
    assert.match(fixture.xml, /CSS dotted border top/);
    assert.equal((fixture.xml.match(/CSS double border top/g) || []).length, 4,
      'each double top border must use two parallel strokes');
    assert.match(fixture.xml, /<a:prstDash val="dash"\/>/);
    assert.match(fixture.xml, /<a:prstDash val="dot"\/>/);
    const svgMedia = Object.keys(fixture.zip.files).filter((name) => /^ppt\/media\/.*\.svg$/i.test(name));
    const svgText = (await Promise.all(svgMedia.map((name) => fixture.zip.file(name).async('string')))).join('\n');
    assert.match(svgText, /stroke="#[0-9A-F]{6}"/, '3D CSS border styles need a vector border fallback');
    assert.match(svgText, /stroke-width="3"/, 'groove border must retain its split stroke widths');
    assert.match(svgText, /stroke-dasharray="12 12"/, 'rounded mixed dashed borders must remain dashed');
    assert.match(svgText, /stroke-linecap="round"/, 'rounded mixed dotted borders must retain round dots');

    console.log(`PASS ${gradient.version}: page 35 gradient alpha and page 36/general CSS border styles`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
