// NODE_PATH: bundled playwright/jszip. --project <id> reads page 6.
const assert=require('node:assert/strict');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const JSZip=require('jszip');
async function main(){
  const repo=path.resolve(__dirname,'..'),arg=process.argv.indexOf('--project'),project=arg>=0?process.argv[arg+1]:null;
  const html=project?execFileSync(process.env.LANDPPT_TEST_PYTHON,['-X','utf8','-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=5',(sys.argv[1],)).fetchone()[0])",project],{cwd:repo,encoding:'utf8'}):
    `<style>*{box-sizing:border-box}body{margin:0}.canvas{width:1280px;height:720px;position:relative;background:white}
    .sample{position:absolute;left:40px;top:40px;width:240px;height:240px;border:2px solid transparent;padding:18px}
    .sample::before{content:'';position:absolute;left:0;top:14px;width:0;height:calc(100% - 28px);border-left:2px solid #b8763d}
    .contentbox{left:340px}.contentbox::before{box-sizing:content-box;border-color:#1122aa}
    .right{left:640px}.right::before{left:auto;right:0;border-left:0;border-right:4px solid #22aa11}
    .rotated{left:940px;transform:rotate(12deg)}.rotated::before{border-color:#aa1122}
    .horizontal{top:360px}.horizontal::before{border-left:0;border-top:3px solid #11aa22;width:100%;height:0}
    .after{left:340px;top:360px}.after::before{display:none}.after::after{content:'';position:absolute;left:0;bottom:0;width:100%;height:0;border-bottom:3px solid #aa2211}
    .filled{left:640px;top:360px}.filled::before{width:60px;border-left:5px solid #4411aa;background:#eeeeee}
    .transparent{left:940px;top:360px;opacity:.5}.transparent::before{border-left:4px solid rgba(34,51,68,.4);opacity:.5}
    </style><div class="canvas"><div class="sample"></div><div class="sample contentbox"></div><div class="sample right"></div><div class="sample rotated"></div><div class="sample horizontal"></div><div class="sample after" data-pseudo="::after"></div><div class="sample filled"></div><div class="sample transparent"></div></div>`;
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(html,{waitUntil:'load'});
    await page.addScriptTag({path:path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const result=await page.evaluate(async project=>{
      const root=document.querySelector('.canvas'),original=root.outerHTML,rr=root.getBoundingClientRect();
      const expected=Array.from(document.querySelectorAll(project?'.stage-left .card':'.sample')).map(node=>{
        const ps=getComputedStyle(node,node.dataset.pseudo||'::before'),probe=document.createElement('span');
        for(const key of ps)probe.style.setProperty(key,ps.getPropertyValue(key),'important');
        node.append(probe);
        const r=probe.getBoundingClientRect(),s=getComputedStyle(probe);
        const sides=['Top','Right','Bottom','Left'];
        const side=sides.find(k=>parseFloat(ps['border'+k+'Width'])>0&&ps['border'+k+'Color']!=='rgba(0, 0, 0, 0)');
        const vertical=side==='Left'||side==='Right', bw=parseFloat(ps['border'+side+'Width']);
        const size=(dim,sides)=>{const extras=sides.reduce((sum,k)=>sum+(parseFloat(s['border'+k+'Width'])||0)+(parseFloat(s['padding'+k])||0),0);return Math.max(extras,parseFloat(s[dim])+(s.boxSizing==='border-box'?0:extras));};
        const ow=size('width',['Left','Right']),oh=size('height',['Top','Bottom']);
        const w=vertical?bw:ow, h=vertical?oh:bw;
        let angle=0,current=probe;while(current){const s=getComputedStyle(current);if(s.transform!=='none'){const m=new DOMMatrix(s.transform);angle+=Math.atan2(m.b,m.a)*180/Math.PI;}if(current===root)break;current=current.parentElement;}
        const color=ps['border'+side+'Color'].match(/\d+/g).slice(0,3).map(n=>Number(n).toString(16).padStart(2,'0')).join('').toUpperCase();
        const dx=vertical?(side==='Left'?(w-ow)/2:(ow-w)/2):0;
        const dy=vertical?0:(side==='Top'?(h-oh)/2:(oh-h)/2);
        const rad=angle*Math.PI/180;
        let alpha=Number(ps.opacity),owner=node;while(owner){alpha*=Number(getComputedStyle(owner).opacity);owner=owner.parentElement;}
        const rgba=ps['border'+side+'Color'].match(/[\d.]+/g);if(rgba.length===4)alpha*=Number(rgba[3]);
        const item={color,x:r.left+r.width/2-rr.left+dx*Math.cos(rad)-dy*Math.sin(rad)-w/2,y:r.top+r.height/2-rr.top+dx*Math.sin(rad)+dy*Math.cos(rad)-h/2,w,h,angle,alpha,computedWidth:ps.width};
        probe.remove();return item;
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
          alpha:fill?(Number(all(fill,a,'alpha')[0]?.getAttribute('val')??100000)/100000):0,color:fill&&all(fill,a,'srgbClr')[0]?.getAttribute('val'),angle:Number(xf?.getAttribute('rot'))/60000};});
    },{xml,pres});
    for(const expected of result.expected){
      const candidates=shapes.filter(s=>s.color===expected.color&&Math.abs(s.x-expected.x)<.05&&Math.abs(s.y-expected.y)<.05&&Math.abs(s.w-expected.w)<.05&&Math.abs(s.h-expected.h)<.05);
      if(candidates.length!==1)console.log({expected,sameColor:shapes.filter(s=>s.color===expected.color)});
      assert.equal(candidates.length,1,'Expected exactly one native border per pseudo-element');const shape=candidates[0];
      console.log({expected,shape});assert.ok(shape,'Missing correctly sized native pseudo-element');
      for(const key of ['x','y','w','h','angle','alpha'])assert.ok(Math.abs(shape[key]-expected[key])<.05,`Pseudo ${expected.color} ${key} differs from live layout`);
    }
    console.log(`PASS ${result.version}: ${project||'fixture'} pseudo-element positioning`);
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
