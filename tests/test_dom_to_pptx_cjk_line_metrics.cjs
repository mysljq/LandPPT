const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const JSZip = require('jszip');

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(`<style>
      body { margin:0; width:1280px; height:720px }
      p { margin:0; width:650px; font-size:60px; line-height:1.08 }
      .tall { font-family:'Segoe Print',KaiTi }
      .regular { font-family:Arial,KaiTi }
    </style>
    <p class="tall">测试标题中文</p>
    <p class="regular">中文标题测试</p>
    <p class="tall">测试 Latin</p>`);
    await page.addScriptTag({ path: path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const bytes = await page.evaluate(async () => Array.from(new Uint8Array(await (await domToPptx.exportToPptx(document.body, { skipDownload:true, autoEmbedFonts:false })).arrayBuffer())));
    const zip = await JSZip.loadAsync(Buffer.from(bytes));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const shapes = xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || [];
    const leading = text => {
      const shape = shapes.find(s => s.includes(`<a:t>${text}</a:t>`));
      assert.ok(shape, `${text} remains native text`);
      assert.ok(shape.includes('<a:ea typeface="楷体"'), 'CJK uses KaiTi');
      return Number(shape.match(/<a:spcPct val="(\d+)"/)[1]);
    };
    const chinese = leading('测试标题中文');
    assert.equal(chinese, leading('中文标题测试'), 'Unused Latin font does not alter Chinese leading');
    assert.ok(chinese >= 89000 && chinese <= 91000, 'KaiTi leading compensates its native single spacing');
    assert.ok(leading('测试 Latin') < chinese, 'Mixed text still accounts for taller Latin metrics');
    console.log('PASS: Chinese-only leading ignores unused Latin metrics; mixed text retains them');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
