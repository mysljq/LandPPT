const assert=require('node:assert/strict'),path=require('node:path'),{chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    const pattern=`<svg style="width:100%;height:100%;opacity:.5" viewBox="0 0 400 180"><defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#e8e8e8" stroke-width=".5"/></pattern></defs><rect width="400" height="180" fill="url(#grid)"/></svg>`;
    await page.setContent(`<style>*{margin:0;padding:0;box-sizing:border-box}html,body{width:1280px;height:720px;overflow:hidden}body{font-family:Arial}.slide{position:relative;width:1280px;height:720px;overflow:hidden;background:radial-gradient(circle at 88% 18%,#5a3a2e 0%,#1a1d24 55%,#0d0f12 100%)}.corner{position:absolute;left:-15px;top:-10px;width:150px;height:150px;background:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0H100V100H0Z" fill="%23a3b8a1" transform="rotate(-30 50 50) scale(.8)" opacity=".6"/></svg>') no-repeat;background-size:contain}.box{position:absolute;left:1050px;top:430px;width:90px;height:90px;display:flex;align-items:center;justify-content:center;transform:rotate(-8deg);border:3px solid yellow}.box span{font-size:14px;line-height:1.4;text-align:center;color:yellow}.heading{position:absolute;left:60px;top:220px;width:392px;font-size:72px;font-weight:700;letter-spacing:8px;color:white}.paragraph{position:absolute;left:20px;top:600px;width:110px;font-size:20px;color:white}</style><div class="slide"><svg style="position:absolute;left:50%;top:-100px;transform:translateX(-50%);width:1400px;height:700px;opacity:.15" viewBox="0 0 1400 700"><g stroke="#ffd700" stroke-width="2"><line x1="700" y1="0" x2="50" y2="700"/><line x1="700" y1="0" x2="1350" y2="700"/></g></svg><div class="corner"></div><div class="box"><span>党政<br>学习</span></div><div class="heading">CONTENTS</div><div class="paragraph">Regular paragraph wraps normally</div><div style="position:absolute;top:400px;width:400px;height:180px;background:#fafafa">${pattern}</div><div style="position:absolute;top:400px;left:450px;width:400px;height:180px;background:linear-gradient(red,blue)">${pattern.replaceAll('id="grid"','id="grid2"').replaceAll('url(#grid)','url(#grid2)')}</div></div>`);
    const badge=await page.locator('.box span').evaluate(n=>n.getBoundingClientRect().toJSON());
    await page.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
    const zip=await JSZip.loadAsync(Buffer.from(bytes)),xml=await zip.file('ppt/slides/slide1.xml').async('string'),rels=await zip.file('ppt/slides/_rels/slide1.xml.rels').async('string');
    const shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];
    const heading=shapes.find(s=>s.includes('<a:t>CONTENTS</a:t>'));
    assert.ok(heading&&heading.includes('wrap="none"'),'Unbreakable browser Latin word remains native on one line');
    const paragraph=shapes.find(s=>s.includes('Regular'));
    assert.ok(paragraph&&paragraph.includes('wrap="square"'),'Ordinary multiline paragraphs retain wrapping');
    const label=shapes.find(s=>s.includes('<a:t>党政</a:t>'));
    assert.ok(label&&label.includes('<a:t>学习</a:t>'),'Rotated multiline badge remains one native textbox');
    const off=label.match(/<a:off x="([^"]+)" y="([^"]+)"/),ext=label.match(/<a:ext cx="([^"]+)" cy="([^"]+)"/);
    const unit=7143.75,w=Number(ext[1])/unit,h=Number(ext[2])/unit;
    assert.ok(w<80&&h<80,'Rotated label never inherits full-slide text width');
    assert.ok(Math.abs((Number(off[1])/unit+w/2)-(badge.x+badge.width/2))<2,'Rotated label x centre follows DOM');
    assert.ok(Math.abs((Number(off[2])/unit+h/2)-(badge.y+badge.height/2))<2,'Rotated label y centre follows DOM');
    const pictures=[];
    for(const pic of xml.match(/<p:pic>[\s\S]*?<\/p:pic>/g)||[]){
      const id=pic.match(/r:embed="([^"]+)"/)[1];
      const target=rels.match(/<Relationship\b[^>]+\/>/g).find(s=>s.includes(`Id="${id}"`)).match(/Target="([^"]+)"/)[1];
      if(!target.endsWith('.png'))continue;
      const buffer=await zip.file(path.posix.normalize('ppt/slides/'+target)).async('nodebuffer');
      const raster=await sharp(buffer).raw().toBuffer({resolveWithObject:true});
      let min=255,max=0,sum=0;
      for(let i=3;i<raster.data.length;i+=4){min=Math.min(min,raster.data[i]);max=Math.max(max,raster.data[i]);sum+=raster.data[i];}
      pictures.push({...raster,pic,min,max,sum});
    }
    const rays=pictures.find(p=>p.info.width===4200&&p.info.height===2100);
    assert.ok(rays&&rays.sum>0&&rays.max<=39,'Translated off-slide rays are a separate visible SVG raster with own opacity');
    assert.ok(rays.pic.includes('y="-714375"'),'SVG original off-slide geometry is retained');
    assert.ok(pictures.some(p=>p.info.width===300&&p.info.height===300&&p.sum>0),'CSS-escaped SVG background URL decodes and paints');
    const grids=pictures.filter(p=>p.info.width===1200&&p.info.height===540);
    assert.equal(grids.length,2);
    assert.ok(grids.some(p=>p.min===255),'Pattern over proven flat backdrop is safely matted for WPS');
    assert.ok(grids.some(p=>p.min===0&&p.max<255),'Pattern over nonuniform backdrop retains transparency');
    const background=pictures.find(p=>p.info.width===2560&&p.info.height===1440);
    assert.ok(background&&background.min===255,'Single radial container background is exported');
    const i=(Math.round(background.info.height*.18)*background.info.width+Math.round(background.info.width*.88))*4;
    assert.ok([90,58,46].every((v,c)=>Math.abs(background.data[i+c]-v)<=2),'Radial centre retains original CSS colour');
    assert.ok(background.data.every((v,i)=>i%4===3||v<=90),'Background raster excludes native text and child artwork');
    console.log('PASS: SVG rays/opacity, rotated badge, safe grid matte, escaped SVG URL, single Latin word and radial container');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
