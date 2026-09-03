const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const JSZip=require('jszip');
const sharp=require('sharp');
async function main(){
  const repo=path.resolve(__dirname,'..'),arg=process.argv.indexOf('--project');
  const project=arg<0?null:process.argv[arg+1];
  const fixtureStyle=`<style>*{margin:0;padding:0;box-sizing:border-box}body{margin:0}.canvas{position:relative;width:1280px;height:720px;overflow:hidden;background:#1a1b41;font-family:Arial}
    .corner{position:absolute;bottom:-60px;right:-40px;width:0;height:0;border-left:180px solid transparent;border-right:180px solid transparent;border-bottom:300px solid #ffb627;transform:rotate(20deg)}
    .chap-num{position:absolute;left:70px;top:110px;font-size:340px;font-weight:900;line-height:.85;letter-spacing:-12px;color:transparent;-webkit-text-stroke:3px #f5efe0}.fill{color:#ff5c5c;-webkit-text-stroke:0}
    .d-zigzag{position:absolute;left:850px;top:128px}.d-wave{position:absolute;left:972px;top:522px}.d-plus{position:absolute;left:1184px;top:210px}</style>`;
  const fixtureSvgs=`<svg class="d-zigzag" width="170" height="36" viewBox="0 0 170 36"><polyline points="0,28 17,8 34,28 51,8 68,28 85,8 102,28 119,8 136,28 153,8 170,28" stroke="#1A1B41" stroke-width="5" fill="none" stroke-linejoin="round" stroke-linecap="round"/></svg>
    <svg class="d-wave" width="220" height="50" viewBox="0 0 220 50"><path d="M0,25 Q27.5,0 55,25 T110,25 T165,25 T220,25" stroke="#FF6B9D" stroke-width="6" fill="none" stroke-linecap="round"/></svg>
    <div class="d-plus"><svg width="32" height="32"><line x1="16" y1="2" x2="16" y2="30" stroke="#1a1b41" stroke-width="5" stroke-linecap="round"/><line x1="2" y1="16" x2="30" y2="16" stroke="#1a1b41" stroke-width="5" stroke-linecap="round"/></svg></div>`;
  const pages=project?JSON.parse(execFileSync(process.env.LANDPPT_TEST_PYTHON,['-X','utf8','-c',
    "import sqlite3,sys,json; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(json.dumps(c.execute('select slide_index,html_content from slide_data where project_id=? and slide_index in (24,26) order by slide_index',(sys.argv[1],)).fetchall()))",project],{cwd:repo,encoding:'utf8'})):
    [24,26].map(i=>[i,`${fixtureStyle}<div class="canvas"><div class="corner"></div><div class="s-stripe" style="position:absolute;left:970px;top:560px;width:130px;height:12px;transform:rotate(-8deg);background:repeating-linear-gradient(90deg,#1a1b41 0 8px,transparent 8px 16px)"></div>${fixtureSvgs}${i===26?'<div class="chap-num" style="opacity:.5">1<span class="fill">.</span></div>':''}</div>`]);
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try{for(const [index,html] of pages){
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(html,{waitUntil:'load'});
    const source=fs.readFileSync(path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js'),'utf8');
    await page.addScriptTag({content:source.replace('exports.__landpptPatchVersion =','exports.__testStripes = parseNativeRepeatingStripes; exports.__landpptPatchVersion =')});
    const stripeGuards=await page.evaluate(()=>{
      const parse=domToPptx.__testStripes;
      return {left:parse('repeating-linear-gradient(to left,red 0% 25%,transparent 25% 50%)',100,20),
        down:parse('repeating-linear-gradient(180deg,red 0px 3px,transparent 3px 6px)',100,20),
        smooth:parse('repeating-linear-gradient(90deg,red 0px,blue 8px)',100,20),
        excessive:parse('repeating-linear-gradient(90deg,red 0px .001px,transparent .001px .002px)',100,20)};
    });
    assert.deepEqual(stripeGuards.left.map(s=>[s.start,s.end]).sort((a,b)=>a[0]-b[0]),[[25,50],[75,100]]);
    assert.deepEqual(stripeGuards.down.map(s=>[s.start,s.end]),[[0,3],[6,9],[12,15],[18,20]]);
    assert.equal(stripeGuards.smooth,null);assert.equal(stripeGuards.excessive,null);
    const result=await page.evaluate(async()=>{
      const root=document.querySelector('.canvas'),original=root.outerHTML;
      const rect=n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};};
      const svgs=Array.from(root.querySelectorAll('svg')).map(n=>({bounds:rect(n),html:n.outerHTML}));
      const number=root.querySelector('.chap-num');let digit=null;
      if(number){const range=document.createRange();range.selectNodeContents(number);const first=document.createRange();first.selectNode(number.firstChild);
        digit={bounds:rect(number),textBounds:rect(range),first:rect(first),font:getComputedStyle(number).fontFamily,opacity:Number(getComputedStyle(number).opacity)};}
      const stripeNode=root.querySelector('.s-stripe'),ss=getComputedStyle(stripeNode),sr=stripeNode.getBoundingClientRect();
      const sm=new DOMMatrix(ss.transform),stripe={w:stripeNode.offsetWidth,h:stripeNode.offsetHeight,cx:sr.x+sr.width/2,cy:sr.y+sr.height/2,angle:Math.atan2(sm.b,sm.a)*180/Math.PI,opacity:Number(ss.opacity)};
      const blob=await domToPptx.exportToPptx(root,{skipDownload:true,autoEmbedFonts:false});
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
      return{data:btoa(binary),svgs,digit,stripe,unchanged:root.outerHTML===original,debug:window.__LANDPPT_PPTX_RISK_FALLBACK_DEBUG__};
    });
    assert.ok(result.unchanged);
    const zip=await JSZip.loadAsync(Buffer.from(result.data,'base64'));
    const xml=await zip.file('ppt/slides/slide1.xml').async('string'),pres=await zip.file('ppt/presentation.xml').async('string');
    const parsed=await page.evaluate(({xml,pres})=>{
      const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main';
      const parse=s=>new DOMParser().parseFromString(s,'application/xml'),all=(n,ns,t)=>Array.from(n.getElementsByTagNameNS(ns,t));
      const doc=parse(xml);if(doc.querySelector('parsererror'))throw new Error('Invalid slide XML');
      const factor=Number(all(parse(pres),p,'sldSz')[0].getAttribute('cx'))/1280;
      const geometry=n=>{const pr=all(n,p,'spPr')[0],xf=all(pr,a,'xfrm')[0],off=all(xf,a,'off')[0],ext=all(xf,a,'ext')[0];return{x:Number(off?.getAttribute('x'))/factor,y:Number(off?.getAttribute('y'))/factor,w:Number(ext?.getAttribute('cx'))/factor,h:Number(ext?.getAttribute('cy'))/factor};};
      return{stripes:all(doc,p,'sp').filter(n=>(all(n,p,'cNvPr')[0]?.getAttribute('name')||'').startsWith('CSS stripe ')).map(n=>{const pr=all(n,p,'spPr')[0];return{...geometry(n),angle:Number(all(pr,a,'xfrm')[0]?.getAttribute('rot'))/60000,alpha:Number(all(pr,a,'alpha')[0]?.getAttribute('val')??100000)/100000};}),pictures:all(doc,p,'pic').map(geometry),text:all(doc,p,'sp').filter(n=>all(n,a,'t').length).map(n=>({bounds:geometry(n),text:all(n,a,'t').map(t=>t.textContent).join(''),
        body:all(n,a,'bodyPr')[0]?.outerHTML,runs:all(n,a,'r').map(r=>{const ln=all(r,a,'ln')[0];return{text:all(r,a,'t')[0]?.textContent,pr:all(r,a,'rPr')[0]?.outerHTML,
          outlineWidth:ln?Number(ln.getAttribute('w'))/factor:0,outlineAlpha:ln?Number(all(ln,a,'alpha')[0]?.getAttribute('val')??100000)/100000:0};})}))};
    },{xml,pres});
    console.log(JSON.stringify({page:index+1,debug:result.debug,svgs:result.svgs.map(s=>s.bounds),digit:result.digit,pictures:parsed.pictures,text:parsed.text.filter(n=>n.text==='1.'||n.text==='1'||n.text==='.')}));
    assert.ok(!result.debug.some(d=>d.reasons.includes('transformed-descendant-clipping')),'Decorative leaves must not rasterize the slide');
    const stripe=result.stripe,step=project&&index===26?7:8,rad=stripe.angle*Math.PI/180;
    const bands=[];for(let start=0;start<stripe.w;start+=step*2){const end=Math.min(start+step,stripe.w);bands.push({start,end});}
    assert.equal(parsed.stripes.length,bands.length,'All stripe bands must be native editable rectangles');
    for(const band of bands){const w=band.end-band.start,dx=(band.start+band.end)/2-stripe.w/2;
      const x=stripe.cx+dx*Math.cos(rad)-w/2,y=stripe.cy+dx*Math.sin(rad)-stripe.h/2;
      const found=parsed.stripes.find(s=>Math.abs(s.x-x)<.05&&Math.abs(s.y-y)<.05);assert.ok(found,'Rotated stripe center mismatch');
      assert.ok(Math.abs(found.w-w)<.05);assert.ok(Math.abs(found.h-stripe.h)<.05);assert.equal(found.alpha,stripe.opacity);
    }
    for(const svg of result.svgs){const found=parsed.pictures.filter(p=>['x','y','w','h'].every(k=>Math.abs(p[k]-svg.bounds[k])<.05));assert.equal(found.length,1,'Missing separately positioned SVG');}
    const pngs=[];
    for(const f of Object.values(zip.files).filter(f=>/^ppt\/media\/.*\.png$/.test(f.name))){
      const buffer=await f.async('nodebuffer');const data=await sharp(buffer).ensureAlpha().raw().toBuffer({resolveWithObject:true});
      let visible=0;for(let i=3;i<data.data.length;i+=4)if(data.data[i]>20)visible++;
      pngs.push({w:buffer.readUInt32BE(16),h:buffer.readUInt32BE(20),visible,buffer});
    }
    for(const svg of result.svgs)assert.ok(pngs.some(p=>p.w===svg.bounds.w*3&&p.h===svg.bounds.h*3&&p.visible>100),`SVG bitmap must contain visible strokes: ${JSON.stringify({bounds:svg.bounds,pngs:pngs.map(({w,h,visible})=>({w,h,visible}))})}`);
    const comparePage=await browser.newPage();
    try{for(const svg of result.svgs){
      const png=pngs.find(p=>p.w===svg.bounds.w*3&&p.h===svg.bounds.h*3);
      await comparePage.setContent(`<style>body{margin:0}</style>${svg.html}`);
      const css=await sharp(await comparePage.locator('svg').screenshot({omitBackground:true})).flatten({background:'white'}).raw().toBuffer();
      const exported=await sharp(png.buffer).resize(svg.bounds.w,svg.bounds.h).flatten({background:'white'}).raw().toBuffer();
      assert.equal(css.length,exported.length);let difference=0;for(let i=0;i<css.length;i++)difference+=Math.abs(css[i]-exported[i]);
      assert.ok(difference/css.length<4,'SVG strokes differ from browser rendering');
    }}finally{await comparePage.close();}
    if(result.digit){
      const cdp=await page.context().newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
      const {root}=await cdp.send('DOM.getDocument');const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.nodeId,selector:'.chap-num'});
      const {fonts}=await cdp.send('CSS.getPlatformFontsForNode',{nodeId});await cdp.detach();
      const label=parsed.text.find(n=>n.text==='1.');assert.ok(label,'Outlined chapter number must be editable, not a bitmap');
      const run=label.runs.find(r=>r.text==='1');assert.ok(run?.pr.includes('<a:ln'),'Outlined digit must have a native glyph outline');
      assert.ok(run.pr.includes(`typeface="${fonts[0].familyName}"`),'PPT must use the actual heavy font face');
      if(fonts[0].familyName==='Arial Black')assert.ok(!run.pr.includes(' b="1"'),'Black face must not be synthetically bolded again');
      assert.ok(Math.abs(run.outlineWidth-3)<.001);assert.equal(run.outlineAlpha,result.digit.opacity);
      assert.ok(run.pr.includes('F5EFE0'));assert.ok(run.pr.includes('<a:alpha val="0"'),'Digit fill must remain transparent');
      assert.ok(!label.runs.find(r=>r.text==='.')?.pr.includes('<a:ln'),'Colored dot must clear inherited outline');
      for(const key of ['x','y','h'])assert.ok(Math.abs(label.bounds[key]-result.digit.textBounds[key])<.05,'Outlined text must follow live glyph Range: '+key);
      assert.ok(label.body.includes('anchor="ctr"'));
    }
    console.log(`PASS page ${index+1}`);await page.close();
  }}finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
