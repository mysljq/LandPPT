const assert=require('node:assert/strict'),path=require('node:path'),{chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
(async()=>{
  const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const p=await b.newPage({viewport:{width:1280,height:720}});
    await p.setContent(`<style>body{margin:0;width:1280px;height:720px}.rays{width:160px;height:160px;background:repeating-conic-gradient(rgba(200,50,74,.13) 0deg 1.5deg,transparent 1.5deg 8deg);border-radius:50%;opacity:.5}.labels{width:32px;font:10px Arial;letter-spacing:1.8px;text-transform:uppercase}.lbl{display:block;margin-bottom:4px}</style><div class="rays"></div><div class="labels"><span class="lbl">Year</span><span>2026</span></div>`);
    await p.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const bytes=await p.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
    const z=await JSZip.loadAsync(Buffer.from(bytes)),xml=await z.file('ppt/slides/slide1.xml').async('string');
    const label=(xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[]).find(s=>s.includes('<a:t>YEAR</a:t>'));
    assert.ok(label&&label.includes('wrap="none"'),'Authored block labels do not wrap again');
    assert.equal((label.match(/<a:p>/g)||[]).length,2,'YEAR and 2026 retain separate paragraphs');
    const pic=(xml.match(/<p:pic>[\s\S]*?<\/p:pic>/g)||[]).find(s=>s.includes('CSS repeating conic gradient'));
    assert.ok(pic,'Conic decoration exists');
    const id=pic.match(/r:embed="([^"]+)"/)[1];
    const rels=await z.file('ppt/slides/_rels/slide1.xml.rels').async('string');
    const rel=rels.match(/<Relationship\b[^>]+\/>/g).find(s=>s.includes(`Id="${id}"`));
    const target=rel.match(/Target="([^"]+)"/)[1];
    assert.ok(target.endsWith('.png'),'WPS receives PNG instead of SVG clipping');
    const {data,info}=await sharp(await z.file(path.posix.normalize('ppt/slides/'+target)).async('nodebuffer')).raw().toBuffer({resolveWithObject:true});
    assert.equal(info.channels,4,'Alpha is preserved');
    let maxAlpha=0;
    for(let y=0;y<info.height;y++)for(let x=0;x<info.width;x++){
      const alpha=data[(y*info.width+x)*4+3];maxAlpha=Math.max(maxAlpha,alpha);
      if(Math.hypot(x+.5-info.width/2,y+.5-info.height/2)>info.width/2+1)assert.equal(alpha,0,'No rays outside circular clip');
    }
    assert.ok(maxAlpha>=15&&maxAlpha<=18,`CSS color alpha and element opacity apply exactly once (${maxAlpha})`);
    console.log('PASS: conic PNG has circular alpha and stacked labels retain authored lines');
  } finally {await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
