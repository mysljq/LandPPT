const assert=require('node:assert/strict'),path=require('node:path'),{chromium}=require('playwright'),JSZip=require('jszip');
(async()=>{
  const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const p=await b.newPage({viewport:{width:1280,height:720}});
    await p.setContent(`<style>body{margin:0;width:1280px;height:720px}.num{font:800 120px/.85 'UnavailableCounterFixtureFont',sans-serif;position:absolute;left:30px;top:30px}.native{font-family:Arial;left:300px}.multi{left:600px}.gradient{background:linear-gradient(#111216,#6b6f7a);background-clip:text;-webkit-text-fill-color:transparent}</style><div class="num gradient">1</div><div class="num native">2</div><div class="num multi">33</div>`);
    const original=await p.locator('.num').evaluateAll(ns=>ns.map(n=>({html:n.outerHTML,rect:n.getBoundingClientRect().toJSON()})));
    await p.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const bytes=await p.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
    const z=await JSZip.loadAsync(Buffer.from(bytes)),xml=await z.file('ppt/slides/slide1.xml').async('string');
    const shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];
    const one=shapes.find(s=>s.includes('<a:t>1</a:t>'));
    assert.ok(one&&one.includes('prst="textPlain"')&&one.includes('fromWordArt="1"'),'Fallback single glyph remains native editable WordArt');
    assert.ok(one.includes('<a:gradFill'),'Native gradient remains on text');
    assert.ok(one.includes('wrap="none"'),'Counter stays unwrapped');
    for(const text of ['2','33']) assert.ok(!shapes.find(s=>s.includes(`<a:t>${text}</a:t>`)).includes('prstTxWarp'),'Installed fonts and multiple digits keep their previous text layout');
    assert.deepEqual(await p.locator('.num').evaluateAll(ns=>ns.map(n=>({html:n.outerHTML,rect:n.getBoundingClientRect().toJSON()}))),original,'Baseline probe leaves live DOM unchanged');
    console.log('PASS: fallback counter uses native ink geometry; ordinary counters and DOM remain unchanged');
  } finally {await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
