const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const VERSION = '2026-09-21-pages75-76-stripes-v180';

async function main() {
  const repo = path.resolve(__dirname, '..');
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({
    ...(fs.existsSync(edge) ? { executablePath: edge } : {}),
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(`
      <div class="slide" style="position:relative;width:1280px;height:720px;overflow:hidden">
        <div style="position:absolute;right:60px;top:240px;font:500 10px Arial;letter-spacing:.24em;
          writing-mode:vertical-rl;transform:rotate(180deg)">PRESENTATION</div>
      </div>`);
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide'), {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let index = 0; index < bytes.length; index += 32768) {
        binary += String.fromCharCode(...bytes.subarray(index, index + 32768));
      }
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
    });
    assert.equal(result.version, VERSION);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const slideFile = Object.keys(zip.files).find((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
    const xml = await zip.file(slideFile).async('string');
    const shape = (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || []).find((entry) =>
      [...entry.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((match) => match[1]).join('').includes('PRESENTATION')
    );
    assert.ok(shape, 'Latin vertical label must remain editable text');
    assert.doesNotMatch(shape, /<a:xfrm[^>]*\bflipH="1"/, 'pure CSS rotation must not become a horizontal mirror');
    assert.doesNotMatch(shape, /<a:xfrm[^>]*\bflipV="1"/, 'pure CSS rotation must not become a vertical mirror');
    assert.doesNotMatch(shape, /<a:bodyPr[^>]*\bvert="eaVert"/, 'Latin vertical text must not use East-Asian vertical glyph orientation');
    assert.match(shape, /<a:xfrm[^>]*\brot="16200000"/, 'vertical-rl + rotate(180deg) must resolve to a counter-clockwise 90deg PPT rotation');
    assert.equal((shape.match(/<a:p>/g) || []).length, 1, 'Latin vertical text must remain one editable paragraph');
    console.log(`PASS ${VERSION}: Latin vertical-rl text keeps the browser bottom-to-top direction`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
