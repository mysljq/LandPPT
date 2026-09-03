const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const JSZip = require('jszip');

async function main() {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(`<style>*{box-sizing:border-box}body{margin:0}.slide{width:1280px;height:720px;padding:100px}.tags{display:flex;gap:12px}.tag{display:inline-block;padding:6px 14px;border-radius:999px;background:#E9F6EF;color:#197A4A;font:16px Arial}</style><div class="slide"><div class="tags"><span class="tag">日常训练</span></div></div>`);
    await page.addScriptTag({ path: path.join(process.cwd(), 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const data = await page.evaluate(async () => { const blob = await domToPptx.exportToPptx(document.querySelector('.slide'), { skipDownload: true, autoEmbedFonts: false }); const bytes = new Uint8Array(await blob.arrayBuffer()); let s=''; for(let i=0;i<bytes.length;i+=32768)s+=String.fromCharCode(...bytes.subarray(i,i+32768)); return { data:btoa(s), version:domToPptx.__landpptPatchVersion }; });
    const zip = await JSZip.loadAsync(Buffer.from(data.data, 'base64'));
    const xml = await zip.file(Object.keys(zip.files).find((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))).async('string');
    const shapes = [...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)].map((m) => m[0]).filter((s) => s.includes('<a:t>日常训练</a:t>'));
    assert.equal(shapes.length, 1);
    assert.match(shapes[0], /<a:prstGeom prst="roundRect"/);
    assert.match(shapes[0], /<a:bodyPr[^>]*wrap="none"/);
    console.log(`PASS ${data.version}: compact tag is one editable rounded text shape`);
  } finally { await browser.close(); }
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
