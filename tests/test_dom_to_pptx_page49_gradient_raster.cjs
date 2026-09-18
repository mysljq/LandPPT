// NODE_PATH: bundled playwright/jszip/sharp. Verifies that a complex CSS
// gradient is exported as one browser-rendered image, not many PPT shapes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-18-cursive-font-resolution-v165';

async function main() {
  const repo = path.resolve(__dirname, '..');
  const html = execFileSync(process.env.LANDPPT_TEST_PYTHON || process.execPath, ['-e',
    `const s=require('node:sqlite');const db=new s.DatabaseSync('landppt.db');` +
    `process.stdout.write(db.prepare("select html_content from slide_data where project_id=? and slide_index=48").get(process.argv[1]).html_content);`,
    PROJECT], { cwd: repo, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
    await page.setContent(html, { waitUntil: 'load' });
    const slide = page.locator('.slide');
    const reference = await slide.screenshot({ type: 'png' });
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide'), {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
    });
    assert.equal(result.version, VERSION);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    assert.equal((xml.match(/<p:pic>/g) || []).length, 1, 'complex gradient must be one picture');
    assert.equal((xml.match(/<p:sp>/g) || []).length, 0, 'complex gradient must not expand into native ellipses');

    const images = Object.values(zip.files).filter((entry) => /^ppt\/media\/.*\.png$/i.test(entry.name));
    assert.equal(images.length, 1, 'complex gradient should create exactly one PNG');
    const exported = await images[0].async('nodebuffer');
    const refRaw = await sharp(reference).resize(320, 180).removeAlpha().raw().toBuffer();
    const outRaw = await sharp(exported).resize(320, 180).removeAlpha().raw().toBuffer();
    let error = 0;
    for (let i = 0; i < refRaw.length; i++) error += Math.abs(refRaw[i] - outRaw[i]);
    const meanAbsoluteError = error / refRaw.length;
    assert.ok(meanAbsoluteError < 8, `browser/PPT image color error is too high: ${meanAbsoluteError.toFixed(2)}`);

    // A filtered gradient must use the same direct transparent browser raster
    // path, preserving the partially transparent pixels around the blur.
    const blurPage = await browser.newPage({ viewport: { width: 400, height: 300 }, deviceScaleFactor: 1 });
    await blurPage.setContent(`<div class="slide" style="position:relative;width:400px;height:300px;background:#fff">
      <div style="position:absolute;left:80px;top:70px;width:240px;height:160px;
        background:linear-gradient(90deg,rgba(255,40,90,.8),rgba(30,100,255,.25));filter:blur(12px)"></div>
    </div>`);
    await blurPage.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const blurData = await blurPage.evaluate(async () => {
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide'), { skipDownload: true, autoEmbedFonts: false });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      return btoa(binary);
    });
    await blurPage.close();
    const blurZip = await JSZip.loadAsync(Buffer.from(blurData, 'base64'));
    const blurPngs = Object.values(blurZip.files).filter((entry) => /^ppt\/media\/.*\.png$/i.test(entry.name));
    assert.equal(blurPngs.length, 1, 'filtered gradient should create one PNG visual');
    const blurStats = await sharp(await blurPngs[0].async('nodebuffer')).ensureAlpha().stats();
    assert.equal(blurStats.channels[3].min, 0, 'blur padding should retain transparent pixels');
    assert.ok(blurStats.channels[3].max >= 170, 'blur center should retain substantial source gradient alpha');
    assert.ok(blurStats.channels[3].stdev > 40, 'blur alpha falloff was not preserved');
    console.log(`PASS ${VERSION}: one browser-native gradient image (MAE ${meanAbsoluteError.toFixed(2)}) and CSS blur alpha`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
