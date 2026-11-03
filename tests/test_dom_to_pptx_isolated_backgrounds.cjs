const assert=require('node:assert/strict'),path=require('node:path'),{chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(`<style>*{margin:0;padding:0;box-sizing:border-box}html,body{width:1280px;height:720px;overflow:hidden}body{background:white}.decoration{position:absolute;inset:0;overflow:hidden;opacity:.5}.a{position:absolute;top:-100px;right:-120px;width:500px;height:500px;border-radius:50%;opacity:.8;background:radial-gradient(circle at 30% 30%,rgba(123,97,255,.1),transparent 62%)}.b{position:absolute;bottom:-120px;left:-100px;width:450px;height:450px;border-radius:50%;background:radial-gradient(circle at 70% 70%,rgba(255,95,162,.08),transparent 62%)}.mesh{position:absolute;inset:0;background-image:linear-gradient(rgba(17,19,24,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(17,19,24,.02) 1px,transparent 1px);background-size:80px 80px;mask-image:linear-gradient(transparent,#000 28%,#000 72%,transparent)}h1{position:absolute;top:200px;left:80px;font:700 80px 'Microsoft YaHei';background:linear-gradient(red,blue);background-clip:text;color:transparent}</style><div class="decoration"><div class="a"></div><div class="b"></div><div class="mesh"></div></div><h1>感谢聆听</h1>`);
    const original=await page.locator('.decoration').evaluate(n=>n.outerHTML);
    await page.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
    const zip=await JSZip.loadAsync(Buffer.from(bytes)),xml=await zip.file('ppt/slides/slide1.xml').async('string');
    const pics=(xml.match(/<p:pic>[\s\S]*?<\/p:pic>/g)||[]).filter(s=>s.includes('CSS isolated decorative background'));
    assert.equal(pics.length,3,'Both off-slide radial gradients and masked grid are exported');
    const rels=await zip.file('ppt/slides/_rels/slide1.xml.rels').async('string');
    const rasters=[];
    for(const pic of pics){
      const id=pic.match(/r:embed="([^"]+)"/)[1];
      const target=rels.match(/<Relationship\b[^>]+\/>/g).find(s=>s.includes(`Id="${id}"`)).match(/Target="([^"]+)"/)[1];
      const png=await zip.file(path.posix.normalize('ppt/slides/'+target)).async('nodebuffer');
      const raster=await sharp(png).raw().toBuffer({resolveWithObject:true});
      assert.equal(raster.info.channels,4,'Decorations retain transparent pixels');
      let max=0,sum=0;for(let i=3;i<raster.data.length;i+=4){max=Math.max(max,raster.data[i]);sum+=raster.data[i];}
      assert.ok(sum>0,'Transparent decorations are not empty PNGs');rasters.push({...raster,max});
    }
    const glow=rasters.find(r=>r.info.width===1000);
    assert.ok(glow.max>=9&&glow.max<=11,'Ancestor/element opacity applies once to the radial glow');
    assert.equal(glow.data[3],0,'Circular clipping retains transparent corners');
    const grid=rasters.find(r=>r.info.width===2560);
    const rowAlpha=y=>{let sum=0;for(let x=0;x<grid.info.width;x++)sum+=grid.data[(y*grid.info.width+x)*4+3];return sum;};
    assert.equal(rowAlpha(0),0,'Top mask fades fully transparent');
    assert.equal(rowAlpha(grid.info.height-1),0,'Bottom mask fades fully transparent');
    assert.ok(rowAlpha(Math.floor(grid.info.height/2))>0,'Middle grid remains visible');
    const heading=(xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[]).find(s=>s.includes('<a:t>感谢聆听</a:t>'));
    assert.ok(heading&&heading.includes('<a:gradFill'),'Chinese gradient text stays native and editable');
    assert.equal(await page.locator('.decoration').evaluate(n=>n.outerHTML),original,'Capture does not mutate live decorations');
    console.log('PASS: off-slide radial backgrounds and masked grid retain paint, alpha, and mask; text stays native');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
