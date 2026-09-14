const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const JSZip = require('jszip');

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true,
  });
  try {
    const projectMode = process.argv.includes('--project');
    let html = null;
    if (projectMode) {
      const { DatabaseSync } = require('node:sqlite');
      const db = new DatabaseSync(path.join(process.cwd(), 'landppt.db'), { readOnly: true });
      html = db.prepare(
        'select html_content from slide_data where project_id = ? and slide_index = 33'
      ).get('542faf1c-ba6e-4386-9be1-a79d4cf4cb80').html_content;
      db.close();
    }
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(html || `
      <style>
        * { box-sizing: border-box; }
        body { margin: 0; }
        .slide { width: 1280px; height: 720px; padding: 80px; background: #fffaf5; }
        .copy { width: 430px; color: #292735; font: 16px/1.75 Arial; }
        .highlight { display: inline-block; margin-right: 4px; padding: 2px 8px;
          border: 1px solid rgba(255,92,92,.35); border-radius: 4px;
          background: linear-gradient(90deg, rgba(255,92,92,.15), rgba(255,92,92,.05));
          color: #ff5c5c; font-weight: 700; font-size: 13px; }
      </style>
      <section class="slide">
        <p class="copy"><span class="highlight">书香门第</span>出身于浙江杭州的名门望族，父亲林长民是民国时期著名政治家、外交家与教育家。她自幼接受中西合璧的教育，拥有开阔的文化视野。</p>
      </section>
    `);
    const geometry = await page.evaluate((project) => {
      const target = project
        ? [...document.querySelectorAll('span')].find((element) => element.textContent.trim() === '书香门第')
        : document.querySelector('.highlight');
      const rect = target.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(target);
      const textRect = range.getBoundingClientRect();
      range.detach();
      return { width: rect.width, height: rect.height, leftInset: textRect.left - rect.left };
    }, projectMode);
    await page.addScriptTag({
      path: path.join(process.cwd(), 'src/landppt/web/static/js/dom-to-pptx.bundle.js'),
    });
    const result = await page.evaluate(async () => {
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide') || document.body, {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      }
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
    });

    assert.equal(result.version, '2026-09-14-cjk-kaiti-v154');
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const slideName = Object.keys(zip.files).find((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
    const xml = await zip.file(slideName).async('string');
    assert.match(xml, /<a:t>书香门第<\/a:t>/, 'highlight text must remain editable');
    assert.match(xml, /name="Inline visual gradient /, 'gradient background must be a separate visual layer');
    if (!projectMode) {
      assert.match(xml, /name="Inline visual border /, 'inline border must be retained');
    }

    const gradientPicture = [...xml.matchAll(/<p:pic>[\s\S]*?<\/p:pic>/g)]
      .map((match) => match[0])
      .find((picture) => picture.includes('Inline visual gradient'));
    assert.ok(gradientPicture, 'expected inline gradient picture');
    const extent = gradientPicture.match(/<a:ext cx="(\d+)" cy="(\d+)"/);
    const gradientOffset = gradientPicture.match(/<a:off x="(\d+)" y="(\d+)"/);
    assert.ok(extent, 'expected gradient picture extent');
    assert.ok(gradientOffset, 'expected gradient picture offset');
    const expectedCx = geometry.width * 9525 * 0.75;
    const expectedCy = geometry.height * 9525 * 0.75;
    assert.ok(Math.abs(Number(extent[1]) - expectedCx) < 2000, 'gradient width must match the live inline box');
    assert.ok(Math.abs(Number(extent[2]) - expectedCy) < 2000, 'gradient height must match the live inline box');

    const highlightShape = [...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)]
      .map((match) => match[0])
      .find((shape) => shape.includes('<a:t>书香门第</a:t>'));
    assert.ok(highlightShape, 'expected editable highlight text shape');
    const textOffset = highlightShape.match(/<a:off x="(\d+)" y="(\d+)"/);
    assert.ok(textOffset, 'expected highlight text offset');
    const expectedPadding = geometry.leftInset * 9525 * 0.75;
    assert.ok(
      Math.abs((Number(textOffset[1]) - Number(gradientOffset[1])) - expectedPadding) < 5000,
      'editable text must retain the inline element left padding'
    );

    const mediaNames = Object.keys(zip.files).filter((name) => /^ppt\/media\/.*\.svg$/i.test(name));
    const mediaText = (await Promise.all(mediaNames.map((name) => zip.file(name).async('string')))).join('\n');
    assert.match(mediaText, /stop-opacity="0\.15"/, 'CSS alpha gradient stop must be preserved');
    assert.match(mediaText, /rx="4"/, 'CSS rounded corner must be preserved');

    const editableShapes = [...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)]
      .map((match) => match[0])
      .filter((shape) => shape.includes('name="Inline editable text'));
    assert.ok(editableShapes.length >= 3, 'browser line/run geometry should be emitted as editable text layers');
    assert.ok(editableShapes.every((shape) => /<a:bodyPr[^>]*wrap="none"/.test(shape)),
      'Range-positioned text must not be reflowed by Office');

    console.log(`PASS ${result.version}: ${projectMode ? 'page 34 ' : ''}inline gradient/radius/padding retained with editable Range text`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
