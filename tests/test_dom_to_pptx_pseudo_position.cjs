// NODE_PATH: bundled playwright/jszip. --project <id> reads page 17.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const JSZip=require('jszip');
async function main(){
  const repo=path.resolve(__dirname,'..'),arg=process.argv.indexOf('--project'),project=arg>=0?process.argv[arg+1]:null;
  const html=project?execFileSync(process.env.LANDPPT_TEST_PYTHON,['-X','utf8','-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=16',(sys.argv[1],)).fetchone()[0])",project],{cwd:repo,encoding:'utf8'}):
    `<style>*{box-sizing:border-box}body{margin:0}.suite-page{width:1280px;height:720px;position:relative;background:white}
    .sample{position:absolute;left:40px;top:40px;width:240px;height:240px;border:4px solid #222;padding:28px;background:white;border-radius:20px}
    .sample::before{content:'';position:absolute;left:0;top:0;bottom:0;width:6px;background:#4FC3F7;border-radius:20px 0 0 20px}
    .right{left:340px;border-width:8px 12px 16px 6px}.right::before{left:auto;right:0;background:#B388FF}
    .percent{left:640px}.percent::before{left:10%;top:20%;bottom:auto;width:15%;height:50%;background:#11AA22}
    .rotated{left:940px;transform:rotate(12deg)}.rotated::before{background:#AA1122}
    .bar{top:370px}.bar::before{left:0;right:0;top:auto;bottom:0;width:auto;height:6px;background:#22AA11}
    .contentbox{left:340px;top:370px}.contentbox::before{box-sizing:content-box;width:6px;padding:2px;border:1px solid transparent;background:#AA2211}
    .ancestor{position:absolute;left:640px;top:370px;width:260px;height:260px;border:7px solid #222;padding:20px}
    .static{position:static;width:100px;height:100px}.static::before{content:'';position:absolute;left:0;top:0;bottom:0;width:6px;background:#1122AA}
    </style><div class="suite-page"><div class="sample"></div><div class="sample right"></div><div class="sample percent"></div><div class="sample rotated"></div><div class="sample bar"></div><div class="sample contentbox"></div><div class="ancestor"><div class="static"></div></div></div>`;
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(html,{waitUntil:'load'});
    await page.addScriptTag({path:path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const result=await page.evaluate(async project=>{
      const root=document.querySelector('.suite-page'),original=root.outerHTML,rr=root.getBoundingClientRect();
      const expected=Array.from(document.querySelectorAll(project?'.content-card':'.sample,.static')).map(node=>{
        const ps=getComputedStyle(node,'::before'),probe=document.createElement('span');
        for(const key of ps)probe.style.setProperty(key,ps.getPropertyValue(key),'important');
        node.append(probe);
        const r=probe.getBoundingClientRect(),s=getComputedStyle(probe);
        const w=parseFloat(s.width)+(s.boxSizing==='border-box'?0:['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((v,k)=>v+(parseFloat(s[k])||0),0));
        const h=parseFloat(s.height)+(s.boxSizing==='border-box'?0:['paddingTop','paddingBottom','borderTopWidth','borderBottomWidth'].reduce((v,k)=>v+(parseFloat(s[k])||0),0));
        let angle=0,current=probe;while(current){const s=getComputedStyle(current);if(s.transform!=='none'){const m=new DOMMatrix(s.transform);angle+=Math.atan2(m.b,m.a)*180/Math.PI;}if(current===root)break;current=current.parentElement;}
        const color=ps.backgroundColor.match(/\d+/g).slice(0,3).map(n=>Number(n).toString(16).padStart(2,'0')).join('').toUpperCase();
        const item={color,x:r.left+r.width/2-rr.left-w/2,y:r.top+r.height/2-rr.top-h/2,w,h,angle};probe.remove();return item;
      });
      const blob=await domToPptx.exportToPptx(root,{skipDownload:true,autoEmbedFonts:false});
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
      return {expected,data:btoa(binary),unchanged:root.outerHTML===original,version:domToPptx.__landpptPatchVersion};
    },!!project);
    assert.ok(result.unchanged);
    const zip=await JSZip.loadAsync(Buffer.from(result.data,'base64'));
    const xml=await zip.file('ppt/slides/slide1.xml').async('string'),pres=await zip.file('ppt/presentation.xml').async('string');
    const shapes=await page.evaluate(({xml,pres})=>{
      const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main';
      const parse=s=>new DOMParser().parseFromString(s,'application/xml'),all=(n,ns,t)=>Array.from(n.getElementsByTagNameNS(ns,t));
      const doc=parse(xml),factor=Number(all(parse(pres),p,'sldSz')[0].getAttribute('cx'))/1280;
      if(doc.querySelector('parsererror'))throw new Error('Invalid PPT XML');
      return all(doc,p,'sp').map(n=>{const pr=all(n,p,'spPr')[0],off=all(pr,a,'off')[0],ext=all(pr,a,'ext')[0],xf=all(pr,a,'xfrm')[0],fill=Array.from(pr.children).find(n=>n.localName==='solidFill');
        return {x:Number(off?.getAttribute('x'))/factor,y:Number(off?.getAttribute('y'))/factor,w:Number(ext?.getAttribute('cx'))/factor,h:Number(ext?.getAttribute('cy'))/factor,
          color:fill&&all(fill,a,'srgbClr')[0]?.getAttribute('val'),angle:Number(xf?.getAttribute('rot'))/60000};});
    },{xml,pres});
    for(const expected of result.expected){
      const shape=shapes.find(s=>s.color===expected.color&&Math.abs(s.w-expected.w)<.05&&Math.abs(s.h-expected.h)<.05);
      console.log({expected,shape});assert.ok(shape,'Missing correctly sized native pseudo-element');
      for(const key of ['x','y','w','h','angle'])assert.ok(Math.abs(shape[key]-expected[key])<.05,`Pseudo ${expected.color} ${key} differs from live layout`);
    }
    console.log(`PASS ${result.version}: ${project||'fixture'} pseudo-element positioning`);
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
