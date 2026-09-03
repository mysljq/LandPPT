// Regression check for page 30's narrow Chengdu welcome paragraph.
const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

async function main() {
  const repo = path.resolve(__dirname, '..');
  const project = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
  const html = execFileSync(process.env.LANDPPT_TEST_PYTHON, ['-X', 'utf8', '-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=29',(sys.argv[1],)).fetchone()[0])",
    project], { cwd: repo, encoding: 'utf8' });
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(html);
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const target = document.querySelector('.subtitle') || [...document.querySelectorAll('*')].find((el) => el.textContent.includes('成都，一座来了就不想走的城市') && el.children.length === 0);
      const range = document.createRange(); range.selectNodeContents(target);
      const browserLines = new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size;
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide') || document.body, { skipDownload: true, autoEmbedFonts: false });
      const bytes = new Uint8Array(await blob.arrayBuffer()); let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      return { browserLines, data: btoa(binary), version: domToPptx.__landpptPatchVersion };
    });
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const slideFile = Object.keys(zip.files).find((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
    if (!slideFile) { console.log(Object.keys(zip.files)); throw new Error('export must contain a slide XML'); }
    const xml = await zip.file(slideFile).async('string');
    const fullText = '成都，一座来了就不想走的城市。这里有悠久的历史、灿烂的文化、美味的美食、悠闲的生活。真诚欢迎各位朋友来到成都，感受天府之国的独特魅力！';
    const targets = [...xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)].filter((m) => m[1] === fullText);
    assert.ok(targets.length, 'Chengdu paragraph must remain editable text');
    const shapes = targets.map((target) => xml.slice(xml.lastIndexOf('<p:sp>', target.index), xml.indexOf('</p:sp>', target.index)));
    assert.ok(shapes.some((shape) => /<a:bodyPr[^>]*wrap="square"/.test(shape)));
    assert.ok(shapes.every((shape) => !/<a:normAutofit\/>/.test(shape)));
    console.log(`PASS ${result.version}: page30 browserLines=${result.browserLines}, editable wrapped text`);
  } finally { await browser.close(); }
}
main().catch((err) => { console.error(err); process.exitCode = 1; });
