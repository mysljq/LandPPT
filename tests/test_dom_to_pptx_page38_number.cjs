const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-21-pages75-76-stripes-v180';

async function main() {
  const repo = path.resolve(__dirname, '..');
  const html = execFileSync(process.execPath, ['-e',
    `const s=require('node:sqlite');const db=new s.DatabaseSync('landppt.db');` +
    `process.stdout.write(db.prepare("select html_content from slide_data where project_id=? and slide_index=37").get(process.argv[1]).html_content);`, PROJECT],
    { cwd: repo, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(require('node:fs').existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(html, { waitUntil: 'load' });
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const root = document.body;
      const blob = await domToPptx.exportToPptx(root, { skipDownload: true, autoEmbedFonts: false });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = ''; for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
    });
    assert.equal(result.version, VERSION);
    if (process.env.LANDPPT_PAGE38_OUTPUT) require('node:fs').writeFileSync(process.env.LANDPPT_PAGE38_OUTPUT, Buffer.from(result.data, 'base64'));
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    assert.match(xml, /<a:t>1<\/a:t>/, 'standalone chapter number must remain editable text');
    const numberShape = (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || []).find((shape) => shape.includes('<a:t>1</a:t>'));
    assert.ok(numberShape, 'standalone chapter number shape is missing');
    assert.match(numberShape, /<a:gradFill[\s\S]*?val="6A82FB"[\s\S]*?val="FC5C7D"/,
      'standalone chapter number must preserve its native gradient text fill');
    console.log(`PASS ${VERSION}: standalone page 38 numeric label remains editable`);
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
