const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const VERSION = '2026-09-14-unicode-core-v156';

async function main() {
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(`<!doctype html><style>
      #slide{position:relative;width:1280px;height:720px;background:#fff}
      #emoji{position:absolute;left:100px;top:80px;width:64px;height:64px;
        display:flex;align-items:center;justify-content:center;font:48px "Segoe UI Emoji"}
    </style><div id="slide"><span id="emoji">⚡</span></div>`);
    await page.addScriptTag({ path: path.resolve(__dirname, '..', 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const before = document.querySelector('#emoji');
      const blob = await domToPptx.exportToPptx(document.querySelector('#slide'), {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      return {
        data: btoa(binary),
        version: domToPptx.__landpptPatchVersion,
        sameNode: before === document.querySelector('#emoji'),
        debug: window.__LANDPPT_PPTX_RISK_FALLBACK_DEBUG__ || [],
      };
    });
    assert.equal(result.version, VERSION);
    assert.equal(result.sameNode, true, 'core Unicode rasterization must not replace the source DOM node');
    assert.ok(result.debug.some((entry) => entry.reasons?.includes('unicode-symbol-raster') && entry.captured));
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    assert.ok((xml.match(/<p:pic>/g) || []).length >= 1, 'Unicode symbol should be emitted as a picture');
    assert.ok(!xml.includes('⚡'), 'Unicode symbol must not also be emitted as editable duplicate text');
    console.log(`PASS ${VERSION}: Unicode symbol rasterized in core without DOM replacement`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
