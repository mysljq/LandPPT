// NODE_PATH: bundled playwright/jszip/sharp. Optional --project reads page 15.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const JSZip=require('jszip');
const sharp=require('sharp');
async function main(){
  const repo=path.resolve(__dirname,'..');
  const index=process.argv.indexOf('--project'),project=index>=0?process.argv[index+1]:null;
  const colors=['FF6B9D','FFD93D','6BCF7F','4FC3F7','B388FF'];
  const gradient=`linear-gradient(to right,${colors.map(c=>'#'+c).join(',')})`;
  const html=project?execFileSync(process.env.LANDPPT_TEST_PYTHON,['-X','utf8','-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=14',(sys.argv[1],)).fetchone()[0])",project],{cwd:repo,encoding:'utf8'}):
    `<style>body{margin:0}.suite-page{width:1280px;height:720px;position:relative;background:white}.suite-header-line{position:absolute;left:60px;top:120px;width:1160px;height:3px;border-radius:999px;background:${gradient}}</style><div class="suite-page"><div class="suite-header-line"></div></div>`;
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(html,{waitUntil:'load'});
    const source=fs.readFileSync(path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js'),'utf8');
    await page.addScriptTag({content:source.replace('exports.__landpptPatchVersion =','exports.__testGradient = parseNativeLinearGradient; exports.__testGradientSvg = generateGradientSVG; exports.__landpptPatchVersion =')});
    const result=await page.evaluate(async()=>{
      const root=document.querySelector('.suite-page'),node=document.querySelector('.suite-header-line'),r=node.getBoundingClientRect();
      const blob=await domToPptx.exportToPptx(root,{skipDownload:true,autoEmbedFonts:false});
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
      const parse=domToPptx.__testGradient;
      return {data:btoa(binary),bounds:{x:r.x,y:r.y,w:r.width,h:r.height},version:domToPptx.__landpptPatchVersion,
        implicit:parse('linear-gradient(red,green,blue)'),mixed:parse('linear-gradient(to right,red 10%,green,blue 70%,white)'),
        hard:parse('linear-gradient(to right,red 70%,green 30%,blue)'),alpha:parse('linear-gradient(to right,#ffff,#0000,#ffff)'),
        invalid:parse('linear-gradient(to right,red 5px,green,blue)'),
        fallback:domToPptx.__testGradientSvg(1160,3,getComputedStyle(node).backgroundImage,999,null)};
    });
    assert.deepEqual(result.implicit.stops.map(s=>s.pos),[0,50000,100000]);
    assert.deepEqual(result.mixed.stops.map(s=>s.pos),[10000,40000,70000,100000]);
    assert.deepEqual(result.hard.stops.map(s=>s.pos),[70000,70000,100000]);
    assert.ok(result.alpha.stops.length>3);assert.ok(result.alpha.stops.every(s=>s.color==='FFFFFF'));assert.equal(result.invalid,null);
    const zip=await JSZip.loadAsync(Buffer.from(result.data,'base64'));
    const xml=await zip.file('ppt/slides/slide1.xml').async('string'),pres=await zip.file('ppt/presentation.xml').async('string');
    const strip=await page.evaluate(({xml,pres,bounds})=>{
      const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main';
      const parse=s=>new DOMParser().parseFromString(s,'application/xml'),all=(n,ns,t)=>Array.from(n.getElementsByTagNameNS(ns,t));
      const doc=parse(xml);if(doc.querySelector('parsererror'))throw new Error('Invalid PPT XML');
      const factor=Number(all(parse(pres),p,'sldSz')[0].getAttribute('cx'))/1280;
      const shapes=all(doc,p,'sp').map(n=>{
        const pr=all(n,p,'spPr')[0],off=all(pr,a,'off')[0],ext=all(pr,a,'ext')[0],geom=all(pr,a,'prstGeom')[0],adj=all(pr,a,'gd').find(n=>n.getAttribute('name')==='adj');
        return {x:Number(off?.getAttribute('x'))/factor,y:Number(off?.getAttribute('y'))/factor,w:Number(ext?.getAttribute('cx'))/factor,h:Number(ext?.getAttribute('cy'))/factor,
          geometry:geom?.getAttribute('prst'),adj:adj&&Number(adj.getAttribute('fmla').split(' ')[1]),angle:Number(all(pr,a,'lin')[0]?.getAttribute('ang'))/60000,
          stops:all(pr,a,'gs').map(s=>({pos:Number(s.getAttribute('pos')),color:all(s,a,'srgbClr')[0]?.getAttribute('val')}))};
      });
      return shapes.find(s=>Math.abs(s.x-bounds.x)<.05&&Math.abs(s.y-bounds.y)<.05&&Math.abs(s.w-bounds.w)<.05&&Math.abs(s.h-bounds.h)<.05);
    },{xml,pres,bounds:result.bounds});
    assert.ok(strip,'Rainbow strip must be a native shape, not a picture');assert.equal(strip.geometry,'roundRect');assert.equal(strip.angle,0);
    assert.ok(Math.abs(strip.adj/100000*Math.min(strip.w,strip.h)-1.5)<.01);
    assert.deepEqual(strip.stops.map(s=>s.color),colors);assert.deepEqual(strip.stops.map(s=>s.pos),[0,25000,50000,75000,100000]);
    const payload=result.fallback.split(',').slice(1).join(',');
    const fallback=result.fallback.includes(';base64,')?Buffer.from(payload,'base64').toString('utf8'):decodeURIComponent(payload);
    assert.match(fallback,/rx="1.5" ry="1.5"/);
    // Native geometry reconstructed from XML versus the browser's CSS strip.
    const raster=await page.evaluate(strip=>{
      const canvas=document.createElement('canvas');canvas.width=Math.round(strip.w);canvas.height=Math.round(strip.h);
      const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,canvas.width,canvas.height);
      const gradient=ctx.createLinearGradient(0,0,strip.w,0);strip.stops.forEach(s=>gradient.addColorStop(s.pos/100000,'#'+s.color));
      ctx.fillStyle=gradient;ctx.beginPath();ctx.roundRect(0,0,strip.w,strip.h,strip.adj/100000*Math.min(strip.w,strip.h));ctx.fill();
      return canvas.toDataURL('image/png').split(',')[1];
    },strip);
    if(!project){
      const css=await sharp(await page.locator('.suite-header-line').screenshot()).removeAlpha().raw().toBuffer();
      const native=await sharp(Buffer.from(raster,'base64')).removeAlpha().raw().toBuffer();
      let diff=0;for(let i=0;i<css.length;i++)diff+=Math.abs(css[i]-native[i]);
      assert.ok(diff/css.length<1,'Rainbow strip differs from CSS');
    }
    console.log(JSON.stringify({version:result.version,project:project||'fixture',strip,passed:true}));
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
