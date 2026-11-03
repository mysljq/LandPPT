const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    let page;
    async function exportHtml(html) {
      if (page) await page.close();
      page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
      await page.setContent(html);
      await page.addScriptTag({ path: path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js') });
      const bytes = await page.evaluate(async () => Array.from(new Uint8Array(await (await domToPptx.exportToPptx(document.body, { skipDownload: true, autoEmbedFonts: false })).arrayBuffer())));
      const zip = await JSZip.loadAsync(Buffer.from(bytes));
      const xml = await zip.file('ppt/slides/slide1.xml').async('string');
      const rasters = [];
      for (const name of Object.keys(zip.files).filter(n => /^ppt\/media\/.*\.png$/.test(n))) {
        const data = await zip.file(name).async('nodebuffer');
        const raw = await sharp(data).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
        rasters.push({ name, ...raw });
      }
      return { xml, rasters, shapes: xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || [] };
    }
    const base = '*{margin:0;padding:0;box-sizing:border-box}html,body{width:1280px;height:720px;overflow:hidden}body{position:relative;font-family:Arial}';
    const result = await exportHtml(`<style>${base}html{background:#0a0a1a}.label{position:absolute;top:20px;left:20px;font-size:14px;letter-spacing:2px}.chip{position:absolute;top:70px;left:20px;display:flex;gap:10px;align-items:center;padding:12px 24px;background:#123;border-radius:30px;color:white;font-size:15px}.dot{display:block;width:6px;height:6px;background:green;border-radius:50%}.seal{position:absolute;top:140px;left:20px;width:78px;height:78px;padding:10px;display:flex;align-items:center;justify-content:center;writing-mode:vertical-rl;font-size:15px;letter-spacing:3px;line-height:1.3;background:linear-gradient(135deg,red,maroon)}.glow{position:absolute;left:200px;top:140px;color:white;font-size:80px;text-shadow:0 0 28px rgba(0,240,255,.55),0 0 56px rgba(0,240,255,.28)}.wrap{position:absolute;left:20px;top:300px;width:95px;font-size:20px}.tile{position:absolute;top:430px;left:20px;width:240px;height:180px;background-image:linear-gradient(45deg,rgba(255,255,255,.03) 25%,transparent 25%,transparent 50%,rgba(255,255,255,.03) 50%,rgba(255,255,255,.03) 75%,transparent 75%,transparent);background-size:60px 60px}.planet{position:absolute;left:360px;top:430px;width:180px;height:180px;border-radius:50%;opacity:.35;background:radial-gradient(circle at 35% 35%,#3a4a6c,#0e1a35);box-shadow:inset -20px -20px 40px rgba(0,0,0,.6),0 0 60px rgba(232,192,105,.12)}.curve{position:absolute;top:640px;left:20px;width:150px;height:15px;background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 15"><path d="M0,8 Q35,0 75,8 T150,8" stroke="%237b9e89" fill="none" stroke-width="2"/></svg>');background-repeat:no-repeat}</style><div class="label">2026 · DEPARTMENT WORK REPORT</div><div class="chip"><span class="dot"></span>联系方式：contact@example.com
  欢迎关注后续分享</div><div class="seal">青花<br>瓷韵</div><div class="glow">感谢聆听</div><p class="wrap">Regular paragraph keeps natural wrapping</p><div class="tile"></div><div class="planet"></div><div class="curve"></div>`);
    console.log('Exported native text and decorative surface fixture');
    const label = result.shapes.find(s => s.includes('2026 · DEPARTMENT'));
    assert.ok(label.includes('wrap="none"'), 'Browser single-line DIV remains unwrapped');
    const contact = result.shapes.find(s => s.includes('contact@'));
    assert.equal((contact.match(/<a:p>/g) || []).length, 1, 'Normal HTML source newlines are not PPT paragraphs');
    assert.ok(contact.includes('wrap="none"') && contact.includes('欢迎关注后续分享'));
    const seal = result.shapes.find(s => s.includes('青花'));
    assert.ok(seal.includes('vert="eaVert"') && seal.includes('瓷韵'), 'Vertical BR preserves native CJK columns');
    const glow = result.shapes.find(s => s.includes('感谢聆听'));
    assert.ok(glow && glow.includes('<a:glow ') && glow.includes('<a:outerShdw'), 'Two CSS halos map to native glow plus one shadow');
    assert.equal((glow.match(/<a:outerShdw/g) || []).length, 1);
    assert.ok(result.xml.includes('<p:bg>') && result.xml.includes('0A0A1A'), 'HTML canvas background survives transparent body');
    assert.ok(result.shapes.find(s => s.includes('Regular')).includes('wrap="square"'));
    const tile = result.rasters.find(r => r.info.width === 480 && r.info.height === 360);
    assert.ok(tile, 'Tiled linear gradient becomes one isolated browser surface');
    const alpha = (r, x, y) => r.data[(y * r.info.width + x) * 4 + 3];
    for (let y = 10; y < 180; y += 17) for (let x = 10; x < 240; x += 19)
      assert.ok(Math.abs(alpha(tile, x, y) - alpha(tile, x + 120, y)) <= 1, '60px CSS tile period retained');
    const planet = result.rasters.find(r => r.info.width > 360 && r.info.width === r.info.height);
    assert.ok(planet, 'Radial surface and shadows are composed together');
    let maxAlpha = 0;
    for (let i = 3; i < planet.data.length; i += 4) maxAlpha = Math.max(maxAlpha, planet.data[i]);
    assert.ok(maxAlpha > 70 && maxAlpha <= 90, 'Opacity applies once to the entire shadow/surface stack');
    const curve = result.rasters.find(r => r.info.width === 300 && r.info.height === 30);
    assert.ok(curve && Array.from({ length: 20 }, (_, y) => alpha(curve, 280, y)).some(a => a > 0), 'ViewBox-only SVG is sized to the CSS area, including its right end');

    const backdrop = await exportHtml(`<style>${base}html{background:#0a0a1a}body::before{content:'';position:absolute;inset:0;background:radial-gradient(circle at 20% 80%,rgba(0,110,255,.4),transparent 70%),radial-gradient(circle at 75% 30%,rgba(180,50,255,.4),transparent 70%);filter:blur(20px)}.glass{position:relative;width:100%;height:100%;backdrop-filter:saturate(180%) blur(20px);background:rgba(10,10,30,.1)}.glass p{position:absolute;top:200px;left:300px;color:white;font-size:40px}</style><div class="glass"><p>Editable foreground</p></div>`);
    console.log('Exported backdrop fixture');
    assert.ok(backdrop.xml.includes('CSS composed slide backdrop'));
    assert.ok(backdrop.shapes.some(s => s.includes('Editable foreground')), 'Backdrop composition excludes foreground text');
    const raster = backdrop.rasters.find(r => r.info.width === 2560 && r.info.height === 1440);
    assert.ok(raster);
    const expected = await sharp(await page.screenshot()).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    for (const [x, y] of [[100,100],[800,100],[1100,500]]) {
      const a = (y * expected.info.width + x) * 4, b = ((y * 2) * raster.info.width + x * 2) * 4;
      for (let c = 0; c < 3; c++) assert.ok(Math.abs(expected.data[a+c] - raster.data[b+c]) <= 4, 'Browser backdrop blur/saturation matches exported pixels');
    }
    console.log('PASS: ending suite native text/vertical/glow, whitespace, tiled gradient, shadow opacity, SVG intrinsic size and browser backdrop composition');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
