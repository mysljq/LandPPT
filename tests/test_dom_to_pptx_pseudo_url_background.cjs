const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-18-cursive-font-resolution-v165';

function readSlide(repo, index) {
  return execFileSync(process.execPath, ['-e',
    `const s=require('node:sqlite');const db=new s.DatabaseSync('landppt.db');` +
    `process.stdout.write(db.prepare("select html_content from slide_data where project_id=? and slide_index=?").get(process.argv[1],Number(process.argv[2])).html_content);`,
    PROJECT, String(index)], { cwd: repo, encoding: 'utf8', maxBuffer: 12 * 1024 * 1024 });
}

async function main() {
  const repo = path.resolve(__dirname, '..');
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    for (const [index, marker] of [[58, 'cover-left ::before'], [59, 'slide-container ::before']]) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
      await page.setContent(readSlide(repo, index), { waitUntil: 'load' });
      await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
      const result = await page.evaluate(async () => {
        const blob = await domToPptx.exportToPptx(document.querySelector('.slide') || document.body, { skipDownload: true, autoEmbedFonts: false });
        const bytes = new Uint8Array(await blob.arrayBuffer());
        let binary = '';
        for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
        return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
      });
      assert.equal(result.version, VERSION);
      const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
      const slideFile = Object.keys(zip.files).find((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
      const xml = await zip.file(slideFile).async('string');
      assert.match(xml, /CSS pseudo background/, `slide ${index + 1} pseudo URL background missing`);
      assert.ok(Object.keys(zip.files).some((name) => /^ppt\/media\//.test(name)), `slide ${index + 1} has no rasterized pseudo media`);
      await page.close();
    }
    console.log(`PASS ${VERSION}: URL-backed ::before decorations on pages 59/60`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
