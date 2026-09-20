const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-18-pages61-62-layout-v166';

function readSlide(repo, slideIndex) {
  return execFileSync(process.execPath, ['-e',
    `const s=require('node:sqlite');const db=new s.DatabaseSync('landppt.db');` +
    `process.stdout.write(db.prepare("select html_content from slide_data where project_id=? and slide_index=?").get(process.argv[1],Number(process.argv[2])).html_content);`,
    PROJECT, String(slideIndex)], { cwd: repo, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
}

function shapeContaining(xml, text) {
  return (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || []).find((shape) => shape.includes(`<a:t>${text}</a:t>`));
}

function largestShapeContaining(xml, text) {
  return (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || [])
    .filter((shape) => shape.includes(`<a:t>${text}</a:t>`))
    .sort((left, right) => {
      const size = (shape) => Math.max(0, ...(shape.match(/\bsz="(\d+)"/g) || []).map((entry) => Number(entry.slice(4, -1))));
      return size(right) - size(left);
    })[0];
}

function yOffset(shape) {
  const match = shape && shape.match(/<a:off[^>]*\by="(\d+)"/);
  return match ? Number(match[1]) : NaN;
}

async function exportSlide(browser, repo, slideIndex) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  try {
    await page.setContent(readSlide(repo, slideIndex), { waitUntil: 'load' });
    if (process.env.LANDPPT_PAGES_OUTPUT_DIR) {
      fs.mkdirSync(process.env.LANDPPT_PAGES_OUTPUT_DIR, { recursive: true });
      await (await page.$('.slide') || await page.$('body')).screenshot({
        path: path.join(process.env.LANDPPT_PAGES_OUTPUT_DIR, `html-page-${slideIndex + 1}.png`),
      });
    }
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide') || document.body, {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let index = 0; index < bytes.length; index += 32768) {
        binary += String.fromCharCode(...bytes.subarray(index, index + 32768));
      }
      return {
        data: btoa(binary),
        version: domToPptx.__landpptPatchVersion,
        debug: window.__LANDPPT_PPTX_RISK_FALLBACK_DEBUG__ || [],
      };
    });
    assert.equal(result.version, VERSION);
    const buffer = Buffer.from(result.data, 'base64');
    if (process.env.LANDPPT_PAGES_OUTPUT_DIR) {
      fs.mkdirSync(process.env.LANDPPT_PAGES_OUTPUT_DIR, { recursive: true });
      fs.writeFileSync(path.join(process.env.LANDPPT_PAGES_OUTPUT_DIR, `page-${slideIndex + 1}.pptx`), buffer);
    }
    const zip = await JSZip.loadAsync(buffer);
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    return { result, buffer, xml };
  } finally {
    await page.close();
  }
}

async function main() {
  const repo = path.resolve(__dirname, '..');
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const numberOffsets = [];
    for (const [slideIndex, value] of [[52, '2'], [54, '1'], [55, '3']]) {
      const { xml } = await exportSlide(browser, repo, slideIndex);
      const shape = largestShapeContaining(xml, value);
      assert.ok(shape, `page ${slideIndex + 1} chapter number must remain editable`);
      numberOffsets.push(yOffset(shape));
    }
    assert.ok(numberOffsets.every(Number.isFinite), 'chapter-number y offsets are missing');
    assert.ok(Math.max(...numberOffsets) - Math.min(...numberOffsets) < 2000,
      `identical large-number boxes must receive identical baseline compensation: ${numberOffsets.join(', ')}`);
    assert.ok(numberOffsets.every((offset) => offset > 2_000_000),
      `large-number baseline compensation was not serialized: ${numberOffsets.join(', ')}`);

    const page54 = await exportSlide(browser, repo, 53);
    assert.ok(page54.result.debug.some((entry) =>
      entry.reasons?.includes('layered-gradient-shadow-surface') && entry.captured && entry.paddingPx >= 90
    ), 'ring-core must use one padded browser-composited gradient/shadow visual');

    const page57 = await exportSlide(browser, repo, 56);
    const painText = shapeContaining(page57.xml, '痛点');
    assert.ok(painText, 'card tag text must remain editable');
    assert.match(page57.xml, /<a:custGeom>[\s\S]*?<a:arcTo/,
      'flush card tag must inherit only the rounded top corners from its clipping parent');
    assert.match(page57.xml, /<a:gradFill\b/, 'card tag gradient must remain a native gradient shape');

    const page58 = await exportSlide(browser, repo, 57);
    for (const text of ['生成PPT不是终点，内容还可以', '修改', '导出', '演讲稿', '一份内容，能留下来的不应该', 'PPT。']) {
      assert.ok(page58.xml.includes(text), `page 58 is missing editable text: ${text}`);
    }
    const descShapes = (page58.xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || []).filter((shape) =>
      /生成PPT不是终点|<a:t>修改<|<a:t>导出<|<a:t>演讲稿<|一份内容，能留下来|<a:t>PPT。</.test(shape)
    );
    const descOffsets = descShapes.map(yOffset).filter(Number.isFinite);
    assert.ok(Math.max(...descOffsets) - Math.min(...descOffsets) > 700_000,
      `paragraph lines collapsed near one y coordinate: ${descOffsets.join(', ')}`);
    console.log(`PASS ${VERSION}: pages 53-58 baseline, shadow, rounded clip and inline layout`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
