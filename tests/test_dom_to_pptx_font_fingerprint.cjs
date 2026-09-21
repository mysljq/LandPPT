const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const VERSION = '2026-09-21-pages75-76-stripes-v180';

(async () => {
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(require('node:fs').existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 800, height: 400 } });
    await page.setContent('<div id="latin" style="font-family:__LandPptMissingLatin, sans-serif">1</div><div id="cjk" style="font-family:__LandPptMissingCjk, sans-serif">中文标题</div>');
    await page.addScriptTag({ path: path.join(__dirname, '..', 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(() => ({
      version: domToPptx.__landpptPatchVersion,
      latin: domToPptx.__landpptResolveFontFace(getComputedStyle(document.querySelector('#latin')).fontFamily, document.querySelector('#latin'), '1'),
      cjk: domToPptx.__landpptResolveFontFace(getComputedStyle(document.querySelector('#cjk')).fontFamily, document.querySelector('#cjk'), '中文标题'),
    }));
    assert.equal(result.version, VERSION);
    assert.notEqual(result.latin, '__LandPptMissingLatin');
    assert.notEqual(result.cjk, '__LandPptMissingCjk');
    console.log(`PASS ${VERSION}: missing CSS families resolve through render fingerprint`);
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
