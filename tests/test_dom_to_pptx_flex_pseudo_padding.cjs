// Compare native PPT marker geometry against the browser's painted pixels.
// --project reads page 31 from the local SQLite database without modifying it.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');

async function main() {
  const project = process.argv.includes('--project');
  let html;
  if (project) {
    const { DatabaseSync } = require('node:sqlite');
    const db = new DatabaseSync(path.resolve('landppt.db'), { readOnly: true });
    html = db.prepare('select html_content from slide_data where project_id=? and slide_index=30')
      .get('542faf1c-ba6e-4386-9be1-a79d4cf4cb80').html_content;
    db.close();
  } else {
    html = `<style>
      *{box-sizing:border-box}body{margin:0}.slide{width:1280px;height:720px;position:relative;background:white}
      .bar{position:absolute;left:66.67px;top:93.33px;width:500px;height:57.33px;display:flex;
        align-items:flex-start;gap:12px;padding:9.33px 14.67px;background:#f2f2f2;border-radius:5.33px}
      .bar::before{content:'';flex:0 0 6.67px;height:38.67px;background:#c2c2c2}
      .bar-label{font:700 20px/1.2 Arial}
      .center{top:200px;align-items:center;justify-content:center;border:3px solid #444}
      .center::before{background:#a12345;margin:2px 5px;height:20px}
      .reverse{top:300px;flex-direction:row-reverse;justify-content:space-between}
      .reverse::before{background:#12a345;height:25px}
      .column{left:650px;top:60px;width:220px;height:200px;flex-direction:column;align-items:flex-end}
      .column::before{background:#1234ab;width:35px;flex-basis:12px;height:auto}
      .after{left:650px;top:330px;width:450px;justify-content:flex-end;align-items:center}
      .after::before{content:none}.after::after{content:'';flex:0 0 15px;height:20px;background:#b123cd}
      .absolute{top:440px;padding:20px;border:4px solid #333}
      .absolute::before{position:absolute;left:0;top:0;width:8px;height:35px;background:#cd8312}
    </style><section class='slide'>${['', 'center', 'reverse', 'column', 'after', 'absolute'].map(c =>
      `<div class='bar ${c}'><span class='bar-label'>第一章</span></div>`).join('')}</section>`;
  }
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.route('**/*', route => route.abort());
    await page.setContent(html);
    if (project) await page.evaluate(() => {
      const root = document.querySelector('.slide');
      root.style.background = '#fff';
      // Isolate the real header; external assets and the moon chart are not under test.
      for (const child of [...root.children]) if (!child.matches('.bar')) child.remove();
    });
    await page.addScriptTag({ path: path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    await page.evaluate(() => document.fonts.ready);
    const before = await page.screenshot();
    const result = await page.evaluate(async () => {
      const original = document.documentElement.outerHTML;
      const blob = await domToPptx.exportToPptx(document.querySelector('.slide'), { skipDownload: true, autoEmbedFonts: false });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      return { data: btoa(binary), unchanged: original === document.documentElement.outerHTML };
    });
    assert.ok(result.unchanged, 'Export must restore the DOM after measuring flex pseudo-elements');
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const pres = await zip.file('ppt/presentation.xml').async('string');
    const shapes = await page.evaluate(({ xml, pres }) => {
      const parse = text => new DOMParser().parseFromString(text, 'application/xml');
      const doc = parse(xml);
      if (doc.querySelector('parsererror')) throw new Error('Invalid slide XML');
      const factor = Number(parse(pres).getElementsByTagName('p:sldSz')[0].getAttribute('cx')) / 1280;
      return [...doc.getElementsByTagName('p:sp')].map(sp => {
        const pr = sp.getElementsByTagName('p:spPr')[0];
        const off = pr.getElementsByTagName('a:off')[0], ext = pr.getElementsByTagName('a:ext')[0];
        const fill = [...pr.children].find(n => n.localName === 'solidFill');
        return { color: fill?.getElementsByTagName('a:srgbClr')[0]?.getAttribute('val'),
          x: Number(off?.getAttribute('x')) / factor, y: Number(off?.getAttribute('y')) / factor,
          w: Number(ext?.getAttribute('cx')) / factor, h: Number(ext?.getAttribute('cy')) / factor };
      });
    }, { xml, pres });
    const { data, info } = await sharp(before).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    const colors = project ? ['C2C2C2'] : ['C2C2C2', 'A12345', '12A345', '1234AB', 'B123CD', 'CD8312'];
    for (const color of colors) {
      const rgb = [0, 2, 4].map(i => parseInt(color.slice(i, i + 2), 16));
      let left = Infinity, top = Infinity, right = -1, bottom = -1;
      for (let y = 0; y < info.height; y++) for (let x = 0; x < info.width; x++) {
        const i = (y * info.width + x) * 4;
        if (rgb.every((v, c) => data[i + c] === v)) {
          left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y);
        }
      }
      assert.ok(Number.isFinite(left), `Missing browser marker ${color}`);
      const matches = shapes.filter(s => s.color === color);
      assert.equal(matches.length, 1, `Expected one editable marker ${color}`);
      const shape = matches[0], expected = { x: left, y: top, w: right - left + 1, h: bottom - top + 1 };
      for (const key of ['x', 'y', 'w', 'h']) assert.ok(Math.abs(shape[key] - expected[key]) <= 1.1,
        `${color} ${key}: PPT=${shape[key]}, browser painted=${expected[key]}`);
      console.log({ color, shape, browser: expected });
    }
    assert.ok(xml.includes('<a:t>第一章</a:t>'), 'Label must remain editable');
    console.log(`PASS ${project ? 'real page 31' : 'flex padding/alignment and absolute-position regression'}`);
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
