// Validates generic multi-layer/inset box-shadow export against project page 40.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-08-shadow-direction-fix-v104';

async function main() {
  const repo = path.resolve(__dirname, '..');
  const html = execFileSync(process.execPath, ['-e',
    `const s=require('node:sqlite');const db=new s.DatabaseSync('landppt.db');` +
    `process.stdout.write(db.prepare("select html_content from slide_data where project_id=? and slide_index=39").get(process.argv[1]).html_content);`,
    PROJECT], { cwd: repo, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(html, { waitUntil: 'load' });
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const shadowNodes = [...document.querySelectorAll('*')].filter((node) => {
        const value = getComputedStyle(node).boxShadow;
        return value && value !== 'none';
      });
      const stats = {
        total: shadowNodes.length,
        multi: shadowNodes.filter((node) => getComputedStyle(node).boxShadow.split(/,(?![^()]*\))/).length > 1).length,
        inset: shadowNodes.filter((node) => /\binset\b/i.test(getComputedStyle(node).boxShadow)).length,
      };
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide') || document.body, {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let index = 0; index < bytes.length; index += 32768) {
        binary += String.fromCharCode(...bytes.subarray(index, index + 32768));
      }
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion, stats };
    });

    assert.equal(result.version, VERSION);
    assert.ok(result.stats.total >= 12, `page fixture unexpectedly has only ${result.stats.total} shadows`);
    assert.ok(result.stats.multi >= 8, `page fixture unexpectedly has only ${result.stats.multi} multi-layer shadows`);
    assert.ok(result.stats.inset >= 5, `page fixture unexpectedly has only ${result.stats.inset} inset shadows`);

    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    if (process.env.LANDPPT_SHADOW_OUTPUT) fs.writeFileSync(process.env.LANDPPT_SHADOW_OUTPUT, Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const xmlError = await page.evaluate((source) =>
      new DOMParser().parseFromString(source, 'application/xml').querySelector('parsererror')?.textContent, xml);
    assert.equal(xmlError, undefined, `invalid DrawingML: ${xmlError}`);
    const mediaSvgs = await Promise.all(Object.values(zip.files)
      .filter((entry) => /^ppt\/media\/.*\.svg$/i.test(entry.name))
      .map((entry) => entry.async('string')));
    const inner = mediaSvgs.filter((svg) => svg.includes('landpptInnerShadow'));
    assert.equal(mediaSvgs.filter((svg) => svg.includes('landpptOuterShadow')).length, 0,
      'solid page-40 surfaces should use native PPT outer-shadow elements');
    assert.equal(inner.length, 0, 'page 40 inset shadows must be native');
    assert.ok((xml.match(/CSS outer shadow layer/g) || []).length >= 8,
      'multi-layer outer shadows were not emitted as separate native PPT elements');
    assert.ok((xml.match(/<a:outerShdw/g) || []).length >= 8,
      'native DrawingML outer-shadow effects are missing');
    assert.match(xml, /<a:outerShdw[^>]*dir="2700000"/,
      'outer shadow direction must follow the CSS offset direction');
    assert.match(xml, /<p:grpSp>[\s\S]*CSS outer shadow layer/,
      'shadow helper elements were not retained inside a PPT group');
    assert.ok(xml.includes('AEA394') && xml.includes('FFFDF7'),
      'the dark/light neumorphic outer-shadow colors were not preserved');
    assert.ok((xml.match(/<a:innerShdw/g) || []).length >= 14, 'missing native inner shadows');
    const insetSurfaces = (xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || [])
      .filter((shape) => shape.includes('CSS inset shadow surface'));
    assert.equal(insetSurfaces.length, result.stats.inset,
      'each inset owner must have one surface, not mutually occluding duplicates');
    for (const shape of insetSurfaces) {
      assert.match(shape, /<a:effectDag type="tree">/, 'missing sequential native effect tree');
      assert.equal((shape.match(/<a:innerShdw/g) || []).length, 2,
        'both dark and light inset layers must be present');
      assert.match(shape, /<a:blend blend="screen"><a:cont type="tree"><a:innerShdw/,
        'the light inset layer must be composited instead of being discarded by a serial effect tree');
      assert.ok(shape.indexOf('AEA394') < shape.indexOf('FFFDF7'),
        'CSS inset layer order must be retained');
      assert.match(shape, /<a:innerShdw[^>]*dir="(13500000|22500000)"/,
        'inner shadow direction must account for CSS inset clipping semantics');
      const fill = shape.match(/<a:solidFill>[\s\S]*?<\/a:solidFill>/)?.[0];
      assert.ok(fill && !fill.includes('val="1000"'), '99%-transparent inset surface would erase its shadow');
      for (const effect of shape.match(/<a:innerShdw\b[^>]*>/g) || []) {
        assert.doesNotMatch(effect, /rotWithShape|sx=|sy=|algn=/, 'innerShdw contains invalid outer-only attributes');
      }
    }
    assert.ok((xml.match(/CSS inset shadow/g) || []).length >= 4,
      'inset shadow layers are missing from the slide');
    assert.equal((xml.match(/CSS layered background/g) || []).length, 1,
      'the cover background should be isolated without flattening its descendants');
    assert.ok((xml.match(/<p:sp>/g) || []).length >= 15,
      'page content was unexpectedly flattened instead of retaining native shapes');
    console.log(`PASS ${VERSION}: page 40 layered outer and inset box shadows`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
