const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-18-pages61-62-layout-v166';
const TEXT = '大美成都：公园城市，幸福生活';

function readSlide(repo) {
  return execFileSync(process.execPath, ['-e',
    `const s=require('node:sqlite');const db=new s.DatabaseSync('landppt.db');` +
    `process.stdout.write(db.prepare("select html_content from slide_data where project_id=? and slide_index=58").get(process.argv[1]).html_content);`,
    PROJECT], { cwd: repo, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
}

async function main() {
  const repo = path.resolve(__dirname, '..');
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(readSlide(repo), { waitUntil: 'load' });
    const live = await page.$eval('.cover-topic', (node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return { writingMode: style.writingMode, width: rect.width, height: rect.height, kaiAvailable: document.fonts.check('16px KaiTi') || document.fonts.check('16px STKaiti') };
    });
    assert.equal(live.writingMode, 'vertical-rl');
    assert.ok(live.height > live.width * 5, `expected a narrow/tall vertical DOM box: ${JSON.stringify(live)}`);

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
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion, debug: window.__LANDPPT_PPTX_FONT_EXPORT_DEBUG__ };
    });
    assert.equal(result.version, VERSION);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const slideFile = Object.keys(zip.files).find((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
    assert.ok(slideFile, `PPTX slide XML is missing: ${Object.keys(zip.files).filter((name) => name.includes('slide')).join(', ')}`);
    const xml = await zip.file(slideFile).async('string');
    const textValues = [...xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((match) => match[1]);
    const shape = (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || []).find((entry) => entry.includes(TEXT));
    if (!shape) {
      console.log('page59 text values:', textValues.slice(-20));
      console.log('page59 large text shape:', (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || []).find((entry) => entry.includes('<a:t>大</a:t>'))?.slice(0, 900));
    }
    assert.ok(shape, 'cover-topic must remain editable text');
    assert.match(shape, /<a:bodyPr[^>]*\bvert="eaVert"/, 'vertical-rl must use native East-Asian vertical text');
    assert.doesNotMatch(shape, /<a:xfrm[^>]*\brot="(?:5400000|-5400000)"/, 'native vertical text must not be rotated as a horizontal line');
    const ext = shape.match(/<a:ext[^>]*\bcx="(\d+)"[^>]*\bcy="(\d+)"/);
    assert.ok(ext && Number(ext[2]) > Number(ext[1]) * 5, `PPT textbox must remain narrow/tall: ${ext && ext.slice(1).join(',')}`);
    const titleShapes = (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || []).filter((entry) => entry.includes('大美成都'));
    assert.ok(titleShapes.length > 0, 'cover title must remain editable text');
    if (live.kaiAvailable) {
      assert.ok(titleShapes.some((entry) => /typeface="(?:KaiTi|楷体|STKaiti|Kaiti SC)"/.test(entry)), 'cursive CJK text must resolve to a Kai-style font when KaiTi is installed');
    }
    console.log(`PASS ${VERSION}: page 59 cover-topic uses native editable vertical text`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
