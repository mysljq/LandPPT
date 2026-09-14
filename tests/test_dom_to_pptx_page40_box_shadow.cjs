// Validates generic multi-layer/inset box-shadow export against project page 40.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');
const { PNG } = require('pngjs');

const PROJECT = '542faf1c-ba6e-4386-9be1-a79d4cf4cb80';
const VERSION = '2026-09-14-cjk-kaiti-v154';

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
    assert.ok((xml.match(/<a:innerShdw/g) || []).length >= result.stats.inset, 'missing native inner shadows');
    const allShapes = xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || [];
    const compositeInsetShapes = allShapes.filter((shape) => shape.includes('CSS inset shadow composite'));
    const fallbackInsetShapes = allShapes.filter((shape) => shape.includes('CSS inset shadow layer'));
    assert.ok(compositeInsetShapes.length >= 5,
      'opaque multi-inset surfaces should use a picture-fill/native-shadow composite');
    assert.equal(compositeInsetShapes.reduce((count, shape) => count + (shape.match(/<a:innerShdw/g) || []).length, 0), compositeInsetShapes.length,
      'each inset composite must contain exactly one native inner shadow');
    for (const shape of compositeInsetShapes) {
      assert.match(shape, /<a:blipFill[^>]*>[\s\S]*?<a:blip r:embed="rId\d+"\/>/,
        'the baked bright inset must be the native shape picture fill');
      assert.doesNotMatch(shape, /<a:alphaModFix|<a:solidFill>/,
        'the composite source fill must be opaque and must not use a translucent solid surface');
    }
    const pictureFillPngs = await Promise.all(Object.values(zip.files)
      .filter((entry) => /^ppt\/media\/shape-fill-.*\.png$/i.test(entry.name))
      .map(async (entry) => PNG.sync.read(await entry.async('nodebuffer'))));
    assert.ok(pictureFillPngs.length >= 5, 'the baked bright inset picture fills are missing');
    for (const png of pictureFillPngs) {
      for (let offset = 3; offset < png.data.length; offset += 4) {
        assert.equal(png.data[offset], 255, 'inset picture fills must be fully opaque at every pixel');
      }
    }
    assert.equal(fallbackInsetShapes.reduce((count, shape) => count + (shape.match(/<a:innerShdw/g) || []).length, 0), fallbackInsetShapes.length,
      'each semi-transparent fallback shape must contain exactly one native inner shadow');
    assert.equal((xml.match(/<a:effectDag/g) || []).length, 0,
      'multi-layer inset shadows must not use an Office effect DAG');
    assert.ok(compositeInsetShapes.some((shape) => shape.includes('AEA394')),
      'the dark inset layer must remain the editable native effect');
    for (const shape of [...compositeInsetShapes, ...fallbackInsetShapes]) {
      assert.match(shape, /<a:innerShdw[^>]*dir="(?:13500000|2700000|22500000|4500000|31500000)"/,
        'inner shadow direction must account for CSS inset clipping semantics');
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
