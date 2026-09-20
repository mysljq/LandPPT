const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const VERSION = '2026-09-18-pages61-62-layout-v166';

function readPage25() {
  const db = new DatabaseSync(path.join(process.cwd(), 'landppt.db'), { readOnly: true });
  try {
    return db.prepare(
      'select html_content from slide_data where project_id = ? and slide_index = 24'
    ).get('542faf1c-ba6e-4386-9be1-a79d4cf4cb80').html_content;
  } finally {
    db.close();
  }
}

async function exportHtml(browser, html, rootSelector) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  try {
    await page.setContent(html);
    await page.addScriptTag({
      path: path.join(process.cwd(), 'src/landppt/web/static/js/dom-to-pptx.bundle.js'),
    });
    const result = await page.evaluate(async (selector) => {
      const blob = await domToPptx.exportToPptx(document.querySelector(selector), {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      }
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
    }, rootSelector);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    return { version: result.version, xml: await zip.file('ppt/slides/slide1.xml').async('string') };
  } finally {
    await page.close();
  }
}

function findGroup(xml, name) {
  return [...xml.matchAll(/<p:grpSp>[\s\S]*?<\/p:grpSp>/g)]
    .map((match) => match[0])
    .find((group) => group.includes(`name="${name}"`));
}

function assertCoordinateSpaceIsStable(group) {
  const transform = group.match(/<p:grpSpPr><a:xfrm>([\s\S]*?)<\/a:xfrm><\/p:grpSpPr>/);
  assert.ok(transform, 'group transform is required');
  const off = transform[1].match(/<a:off x="(-?\d+)" y="(-?\d+)"\/>/);
  const ext = transform[1].match(/<a:ext cx="(\d+)" cy="(\d+)"\/>/);
  const childOff = transform[1].match(/<a:chOff x="(-?\d+)" y="(-?\d+)"\/>/);
  const childExt = transform[1].match(/<a:chExt cx="(\d+)" cy="(\d+)"\/>/);
  assert.deepEqual(childOff && childOff.slice(1), off && off.slice(1), 'grouping must not shift children');
  assert.deepEqual(childExt && childExt.slice(1), ext && ext.slice(1), 'grouping must not rescale children');
}

async function main() {
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({
    ...(fs.existsSync(edge) ? { executablePath: edge } : {}),
    headless: true,
  });
  try {
    const actual = await exportHtml(browser, readPage25(), '.canvas');
    assert.equal(actual.version, VERSION);
    const dots = findGroup(actual.xml, 'Decoration group: d-dots');
    assert.ok(dots, 'page 25 dot matrix must be one DrawingML group');
    assert.equal((dots.match(/<p:sp>/g) || []).length, 15, 'all 15 dots must remain child shapes');
    assert.equal((dots.match(/<a:prstGeom prst="ellipse"/g) || []).length, 15,
      'each dot must remain an editable ellipse');
    assert.equal((dots.match(/<a:srgbClr val="1A1B41"/g) || []).length, 8);
    assert.equal((dots.match(/<a:srgbClr val="FF5C5C"/g) || []).length, 4);
    assert.equal((dots.match(/<a:srgbClr val="2EC4B6"/g) || []).length, 3);
    assertCoordinateSpaceIsStable(dots);
    const stripe = findGroup(actual.xml, 'Decoration group: s-stripe');
    assert.ok(stripe, 'repeating stripe decoration must be one DrawingML group');
    assert.ok((stripe.match(/<p:sp>/g) || []).length >= 2, 'stripe bands must remain native child shapes');
    assertCoordinateSpaceIsStable(stripe);

    const classlessFixture = `
      <style>
        *{box-sizing:border-box}body{margin:0}.slide{width:1280px;height:720px;position:relative}
        #marks{position:absolute;left:100px;top:100px;display:grid;grid-template-columns:repeat(3,12px);gap:8px}
        #marks span{display:block;width:12px;height:12px;border-radius:50%;background:#345678}
      </style>
      <div class="slide"><div id="marks"><span></span><span></span><span></span><span></span><span></span><span></span></div></div>`;
    const generic = await exportHtml(browser, classlessFixture, '.slide');
    const marks = findGroup(generic.xml, 'Decoration group: marks');
    assert.ok(marks, 'structural detection must work without a class name');
    assert.equal((marks.match(/<p:sp>/g) || []).length, 6);
    assertCoordinateSpaceIsStable(marks);

    console.log(`PASS ${actual.version}: repeated decorative leaves are editable children in one PPT group`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
