const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const JSZip = require('jszip');

(async () => {
  const browser = await chromium.launch({ executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless:true });
  try {
    const page = await browser.newPage({ viewport:{width:1280,height:720} });
    await page.setContent(`<style>
      body{margin:0;width:1280px;height:720px;font-family:'Segoe UI'}
      .eyebrow{display:inline-flex;align-items:center;gap:12px;font-size:11px;letter-spacing:.2em;text-transform:uppercase;font-weight:600}
      .eyebrow:before{content:'';width:36px;height:1px;background:black}
      .paragraph{width:100px;font-size:24px}
    </style><div class="eyebrow">Annual Presentation</div>
    <div class="paragraph">普通段落需要按照实际宽度自动换行</div>`);
    await page.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const bytes = await page.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
    const zip = await JSZip.loadAsync(Buffer.from(bytes));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const shapes = xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g) || [];
    const label = shapes.find(s=>s.includes('<a:t>ANNUAL PRESENTATION</a:t>'));
    assert.ok(label && label.includes('wrap="none"'), 'Single-line inline-flex label stays editable and unwrapped');
    assert.ok(/lIns="[1-9]\d*"/.test(label), 'Leading pseudo decoration keeps its inset');
    const paragraph = shapes.find(s=>s.includes('普通段落'));
    assert.ok(paragraph && paragraph.includes('wrap="square"'), 'Multiline block paragraphs retain wrapping');
    console.log('PASS: inline-flex pseudo label preserves one line; multiline paragraphs still wrap');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
