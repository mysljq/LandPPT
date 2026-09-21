// NODE_PATH: bundled playwright/jszip. Validates page 37's gradient text and
// editable background surfaces without depending on project-specific classes.
const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-21-pages75-76-stripes-v180';

async function main() {
  const repo = path.resolve(__dirname, '..');
  const html = execFileSync(process.env.LANDPPT_TEST_PYTHON || process.execPath, ['-e',
    `const s=require('node:sqlite');const db=new s.DatabaseSync('landppt.db');` +
    `process.stdout.write(db.prepare("select html_content from slide_data where project_id=? and slide_index=36").get(process.argv[1]).html_content);`,
    PROJECT], { cwd: repo, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
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
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion, debug: domToPptx.__riskFallbackDebug || window.__LANDPPT_PPTX_RISK_FALLBACK_DEBUG__ || [] };
    });
    assert.equal(result.version, VERSION);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const mediaStats = [];
    for (const file of Object.values(zip.files).filter((entry) => /^ppt\/media\//.test(entry.name))) {
      const bytes = await file.async('nodebuffer');
      try {
        const { width, height, channels, hasAlpha } = await sharp(bytes).metadata();
        if (!hasAlpha) continue;
        const stats = await sharp(bytes).stats();
        const raw = await sharp(bytes).ensureAlpha().raw().toBuffer();
        let transparentPixels = 0;
        for (let index = 3; index < raw.length; index += 4) if (raw[index] === 0) transparentPixels++;
        mediaStats.push({ name: file.name, width, height, channels, alpha: stats.channels[3],
          transparentFraction: transparentPixels / (width * height) });
      } catch (_) { /* SVG and unsupported media are validated structurally. */ }
    }
    const titleVisual = mediaStats.find((item) => item.width > 2000 && item.height < 400);
    assert.ok(titleVisual, 'missing large gradient title visual');
    assert.ok(titleVisual.transparentFraction > 0.45,
      `gradient title background is not transparent: ${titleVisual.transparentFraction}`);
    const borderSvg = await Promise.all(Object.values(zip.files)
      .filter((entry) => /^ppt\/media\/.*\.svg$/i.test(entry.name))
      .map(async (entry) => entry.async('string')));
    assert.ok(borderSvg.some((svg) => svg.includes('borderGradient') &&
      svg.includes('#6A82FB') && svg.includes('#FC5C7D')),
      'border-image gradient colors were not exported');
    assert.match(xml, /<p:pic>/, 'gradient/filter visual should retain a visual image layer');
    assert.doesNotMatch(xml, /Risk subtree capture[^<]*cover-frame/i, 'cover frame must not be flattened as a large image');
    assert.ok((xml.match(/<p:sp>/g) || []).length > 8, 'background and text surfaces should remain native PPT shapes');
    console.log(`PASS ${VERSION}: page 37 gradient text and backdrop surface handling`);
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
