// Run with NODE_PATH pointing to bundled playwright/jszip.
// Optional --project <id> uses LANDPPT_TEST_PYTHON and slide_index=16 (page 17).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

async function main() {
  const repo = path.resolve(__dirname, '..');
  const projectArg = process.argv.indexOf('--project');
  const project = projectArg >= 0 ? process.argv[projectArg + 1] : null;
  const html = project ? execFileSync(process.env.LANDPPT_TEST_PYTHON, [
    '-X', 'utf8', '-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=?',(sys.argv[1],16)).fetchone()[0])", project,
  ], { cwd:repo, encoding:'utf8' }) : fs.readFileSync(path.join(__dirname, 'fixtures/dom_to_pptx_pseudo_radius.html'), 'utf8');
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath:edge } : {}), headless:true });
  try {
    const page = await browser.newPage({ viewport:{ width:1280, height:720 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    await page.setContent(html, { waitUntil:'load' });
    await page.addScriptTag({ path:path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async (realPage) => {
      const root = document.querySelector('.suite-page');
      const rootRect = root.getBoundingClientRect();
      const samples = Array.from(document.querySelectorAll(realPage ? '.content-card' : '.sample')).map((node) => {
        const rect = node.getBoundingClientRect();
        const pseudo = getComputedStyle(node, '::before');
        return {
          name:node.className, x:rect.x-rootRect.x, width:parseFloat(pseudo.width),
          geometry:realPage ? 'custGeom' : node.dataset.geometry,
          radius:realPage ? 6 : Number(node.dataset.radius),
          radiusY:realPage ? 6 : Number(node.dataset.radiusY || node.dataset.radius),
          arcs:realPage ? 2 : Number(node.dataset.arcs),
          angles:(realPage ? '90,180' : node.dataset.angles || '').split(',').filter(Boolean).map(Number),
        };
      });
      const blob = await window.domToPptx.exportToPptx(root, { skipDownload:true, autoEmbedFonts:false });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let text = '';
      for (let i=0; i<bytes.length; i+=0x8000) text += String.fromCharCode(...bytes.subarray(i,i+0x8000));
      return { samples, rootWidth:rootRect.width, data:btoa(text), version:window.domToPptx.__landpptPatchVersion };
    }, !!project);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const presentation = await zip.file('ppt/presentation.xml').async('string');
    const parsed = await page.evaluate(({ xml, presentation }) => {
      const a = 'http://schemas.openxmlformats.org/drawingml/2006/main';
      const p = 'http://schemas.openxmlformats.org/presentationml/2006/main';
      const all = (node, ns, tag) => Array.from(node.getElementsByTagNameNS(ns,tag));
      const read = (s) => new DOMParser().parseFromString(s,'application/xml');
      const doc = read(xml);
      return {
        parseErrors:doc.getElementsByTagName('parsererror').length,
        width:Number(all(read(presentation),p,'sldSz')[0].getAttribute('cx')),
        shapes:all(doc,p,'sp').map((shape) => {
          const props = all(shape,p,'spPr')[0];
          const off = all(props,a,'off')[0], ext = all(props,a,'ext')[0];
          const geometry = all(props,a,'prstGeom')[0];
          const custom = all(props,a,'custGeom')[0];
          const adj = all(props,a,'gd').find((n) => n.getAttribute('name') === 'adj');
          const fill = Array.from(props.children).find((n) => n.localName === 'solidFill');
          const path = custom && all(custom,a,'path')[0];
          return {
            geometry:geometry?.getAttribute('prst') || (custom ? 'custGeom' : null),
            x:Number(off?.getAttribute('x')), w:Number(ext?.getAttribute('cx')), h:Number(ext?.getAttribute('cy')),
            fill:fill && all(fill,a,'srgbClr')[0]?.getAttribute('val'),
            adj:adj ? Number(adj.getAttribute('fmla').split(' ')[1]) : null,
            path:path && { w:Number(path.getAttribute('w')), h:Number(path.getAttribute('h')), closed:all(path,a,'close').length,
              arcs:all(path,a,'arcTo').map((n) => Object.fromEntries(['wR','hR','stAng','swAng'].map((key) => [key,Number(n.getAttribute(key))]))),
              points:all(path,a,'pt').map((n) => [Number(n.getAttribute('x')),Number(n.getAttribute('y'))]),
            },
          };
        }),
      };
    }, { xml, presentation });
    const factor = parsed.width / result.rootWidth;
    console.log(JSON.stringify({ project:project || 'fixture', version:result.version, samples:result.samples.map((s) => {
      const shape = parsed.shapes.find((n) => ['4FC3F7','B388FF'].includes(n.fill) && Math.abs(n.x/factor-s.x)<1 && Math.abs(n.w/factor-s.width)<0.1);
      return { name:s.name, expected:s.geometry, shape };
    }), errors }, null, 2));
    assert.deepEqual(errors, []);
    assert.equal(parsed.parseErrors, 0);
    for (const sample of result.samples) {
      const shape = parsed.shapes.find((n) => ['4FC3F7','B388FF'].includes(n.fill) && Math.abs(n.x/factor-sample.x)<1 && Math.abs(n.w/factor-sample.width)<0.1);
      assert.ok(shape, `Missing native shape: ${sample.name}`);
      assert.equal(shape.geometry, sample.geometry, sample.name);
      if (shape.geometry === 'roundRect') {
        const effectiveRadius = shape.adj / 100000 * Math.min(shape.w, shape.h) / factor;
        assert.ok(Math.abs(effectiveRadius-sample.radius)<0.01, `Fixed radius changed: ${sample.name}`);
      }
      if (shape.geometry === 'custGeom') {
        assert.equal(shape.path.w, shape.w); assert.equal(shape.path.h, shape.h);
        assert.equal(shape.path.closed, 1); assert.equal(shape.path.arcs.length, sample.arcs);
        assert.deepEqual(shape.path.arcs.map((arc) => arc.stAng/60000), sample.angles);
        shape.path.arcs.forEach((arc) => {
          assert.ok(Math.abs(arc.wR/factor-sample.radius)<0.01);
          assert.ok(Math.abs(arc.hR/factor-sample.radiusY)<0.01);
          assert.equal(arc.swAng, 90*60000);
        });
        shape.path.points.forEach(([x,y]) => assert.ok(Number.isFinite(x) && Number.isFinite(y) && x>=0 && y>=0 && x<=shape.w && y<=shape.h));
      }
    }
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
