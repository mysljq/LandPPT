const assert=require('node:assert/strict'),path=require('node:path'),{chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const p=await browser.newPage({viewport:{width:1280,height:720}});
    await p.setContent(`<style>*{margin:0;padding:0}body{width:1280px;height:720px;background:white}h1{position:absolute;top:126px;width:1280px;text-align:center;font:700 76px/1.1 'Arial Black';color:black}.ordinary{position:absolute;top:300px;font:700 76px/1.1 Arial}.multiline{position:absolute;top:420px;width:260px;font:700 76px/1.1 'Arial Black'}</style><h1>Thank You</h1><div class="ordinary">Regular Title</div><div class="multiline">Thank<br>You</div>`);
    const original=await p.locator('h1').evaluate(n=>({html:n.outerHTML,rect:n.getBoundingClientRect().toJSON()}));
    const {data,info}=await sharp(await p.screenshot()).raw().toBuffer({resolveWithObject:true});
    let top=240,bottom=0;
    for(let y=80;y<240;y++)for(let x=300;x<1000;x++)if(data[(y*info.width+x)*info.channels]<40){top=Math.min(top,y);bottom=Math.max(bottom,y);}
    await p.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const bytes=await p.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
    const z=await JSZip.loadAsync(Buffer.from(bytes)),xml=await z.file('ppt/slides/slide1.xml').async('string'),shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];
    const heading=shapes.find(s=>s.includes('<a:t>Thank You</a:t>'));
    assert.ok(heading&&heading.includes('prst="textPlain"'),'Tall-metric single-line heading remains editable native WordArt');
    assert.ok(heading.includes('typeface="Arial Black"'),'Original font is preserved');
    const y=Number(heading.match(/<a:off x="[^"]+" y="([^"]+)"/)[1])/7143.75;
    const h=Number(heading.match(/<a:ext cx="[^"]+" cy="([^"]+)"/)[1])/7143.75;
    assert.ok(Math.abs(y-top)<=1,'Native top follows browser glyph ink');
    assert.ok(Math.abs(y+h-(bottom+1))<=1,'Native bottom follows browser glyph ink');
    for(const shape of shapes.filter(s=>!s.includes('<a:t>Thank You</a:t>')))assert.ok(!shape.includes('prstTxWarp'),'Ordinary and multiline text keep existing layout');
    assert.deepEqual(await p.locator('h1').evaluate(n=>({html:n.outerHTML,rect:n.getBoundingClientRect().toJSON()})),original,'Measurement does not alter live heading layout');
    console.log('PASS: tall-metric heading uses live ink bounds; ordinary and multiline text remain unchanged');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
