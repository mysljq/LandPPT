// NODE_PATH must point to a runtime containing playwright and jszip.
// Optional real-page check: --project <id> --slide-index <zero-based index>,
// with LANDPPT_TEST_PYTHON set to a Python executable with sqlite3.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

async function main() {
  const repo = path.resolve(__dirname, '..');
  const arg = (name) => process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : null;
  const project = arg('--project');
  const html = project ? execFileSync(process.env.LANDPPT_TEST_PYTHON, [
    '-X', 'utf8', '-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=?',(sys.argv[1],int(sys.argv[2]))).fetchone()[0])",
    project, arg('--slide-index') || '15',
  ], { cwd: repo, encoding: 'utf8' }) : fs.readFileSync(path.join(__dirname, 'fixtures/dom_to_pptx_custom_list.html'), 'utf8');
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    await page.setContent(html, { waitUntil: 'load' });
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const source = await page.evaluate(async () => {
      await document.fonts.ready;
      const root = document.querySelector('.suite-page');
      const rootRect = root.getBoundingClientRect();
      const box = (node) => {
        const r = node.getBoundingClientRect();
        return { x:r.left-rootRect.left, y:r.top-rootRect.top, w:r.width, h:r.height };
      };
      const badge = document.querySelector('.highlight-badge');
      const style = getComputedStyle(badge);
      const blob = await window.domToPptx.exportToPptx(root, { skipDownload:true, autoEmbedFonts:false });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i=0; i<bytes.length; i+=0x8000) binary += String.fromCharCode(...bytes.subarray(i,i+0x8000));
      return {
        rootWidth:rootRect.width, badge:box(badge), fontSize:parseFloat(style.fontSize),
        badgePadding:{ lIns:parseFloat(style.paddingLeft), rIns:parseFloat(style.paddingRight), tIns:parseFloat(style.paddingTop), bIns:parseFloat(style.paddingBottom) },
        listItems:Array.from(document.querySelectorAll('.card-left .card-list li')).map(box),
        pptx:btoa(binary), version:window.domToPptx.__landpptPatchVersion,
      };
    });
    const zip = await JSZip.loadAsync(Buffer.from(source.pptx, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const presentation = await zip.file('ppt/presentation.xml').async('string');
    const exported = await page.evaluate(({ xml, presentation }) => {
      const a = 'http://schemas.openxmlformats.org/drawingml/2006/main';
      const p = 'http://schemas.openxmlformats.org/presentationml/2006/main';
      const parse = (s) => new DOMParser().parseFromString(s, 'application/xml');
      const all = (node, ns, tag) => Array.from(node.getElementsByTagNameNS(ns, tag));
      const doc = parse(xml);
      const shapes = all(doc, p, 'sp').map((shape) => {
        const props = all(shape, p, 'spPr')[0];
        const off = all(props, a, 'off')[0], ext = all(props, a, 'ext')[0];
        const geometry = all(props, a, 'prstGeom')[0];
        const fill = Array.from(props.children).find((n) => n.localName === 'solidFill');
        const body = all(shape, a, 'bodyPr')[0];
        return {
          text:all(shape, a, 't').map((n) => n.textContent).join(''),
          x:Number(off?.getAttribute('x')), y:Number(off?.getAttribute('y')),
          w:Number(ext?.getAttribute('cx')), h:Number(ext?.getAttribute('cy')),
          geometry:geometry?.getAttribute('prst'), fill:fill && all(fill, a, 'srgbClr')[0]?.getAttribute('val'),
          padding:body && Object.fromEntries(['lIns','rIns','tIns','bIns'].map((key) => [key, Number(body.getAttribute(key))])),
          runs:all(shape, a, 'r').map((run) => {
            const props = all(run, a, 'rPr')[0];
            return { text:all(run, a, 't')[0]?.textContent, bold:props?.getAttribute('b'), size:Number(props?.getAttribute('sz')), color:props && all(props,a,'srgbClr')[0]?.getAttribute('val'), highlight:props && all(props,a,'highlight').length };
          }),
        };
      });
      return { shapes, slideWidth:Number(all(parse(presentation),p,'sldSz')[0].getAttribute('cx')), bullets:all(doc,a,'buChar').length, numbering:all(doc,a,'buAutoNum').length };
    }, { xml, presentation });
    const factor = exported.slideWidth / source.rootWidth;
    const dots = exported.shapes.filter((s) => s.geometry === 'ellipse' && s.fill === 'FF6B9D' && Math.abs(s.w/factor - 8) < 0.1 && Math.abs(s.h/factor - 8) < 0.1);
    const badge = exported.shapes.find((s) => s.text === '8次');
    console.log(JSON.stringify({ project:project || 'fixture', version:source.version, dots:dots.length, badge, bullets:exported.bullets, numbering:exported.numbering, errors }, null, 2));
    assert.deepEqual(errors, []);
    assert.equal(dots.length, 3, 'All CSS pseudo-element dots must be native ellipses');
    source.listItems.forEach((li) => assert.ok(dots.some((dot) => Math.abs(dot.x/factor-li.x) < 1 && Math.abs(dot.y/factor-(li.y+8)) < 1), 'Dot must retain its DOM position'));
    assert.ok(badge, 'Badge must remain a separate editable text shape');
    assert.equal(badge.geometry, 'roundRect');
    assert.equal(badge.fill, 'FFD93D');
    for (const key of ['x','y','w','h']) assert.ok(Math.abs(badge[key]/factor-source.badge[key]) < 1, `Badge ${key} must match DOM`);
    for (const key of ['lIns','rIns','tIns','bIns']) assert.ok(Math.abs(badge.padding[key]/factor-source.badgePadding[key]) < 0.1, `Badge padding ${key} must match DOM`);
    assert.ok(badge.runs.every((run) => run.bold === '1' && run.color === '2D2A32' && !run.highlight));
    const scale = factor / 9525;
    // Match the exporter's existing whole-point font-size conversion.
    assert.ok(badge.runs.every((run) => Math.abs(run.size-Math.floor(source.fontSize*.75*scale)*100)<1));
    assert.equal(exported.shapes.flatMap((s) => s.runs).filter((r) => r.text?.includes('8次')).length, 1, 'Badge text must not be duplicated');
    if (!project) { assert.ok(exported.bullets >= 2); assert.ok(exported.numbering >= 2); }
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
