// NODE_PATH: bundled playwright/jszip. --project <id> reads page 15 only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');

async function main() {
  const repo = path.resolve(__dirname, '..');
  const project = process.argv.includes('--project') ? process.argv[process.argv.indexOf('--project')+1] : null;
  const html = project ? execFileSync(process.env.LANDPPT_TEST_PYTHON, ['-X','utf8','-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=14',(sys.argv[1],)).fetchone()[0])",project],
    {cwd:repo,encoding:'utf8'}) : `<!doctype html><style>
    *{box-sizing:border-box}body{margin:0}.suite-page{width:1280px;height:720px;background:#fff;position:relative}
    .feature-card{position:absolute;width:320px;height:400px;top:40px;left:40px;border:3px solid #FF6B9D;border-radius:28px;background:white;box-shadow:0 6px 0 #E85A87;transform:rotate(-1deg)}
    .feature-card:nth-child(2){left:420px;width:180px;height:80px;border-radius:20px;background:linear-gradient(90deg,#fff,#ffe8ef);transform:rotate(1deg)}
    .feature-card:nth-child(3){left:680px;width:400px;height:220px;border-radius:28px 0 28px 0;transform:rotate(-.5deg)}
    </style><div class="suite-page"><div class="feature-card"><div>Card one</div></div><div class="feature-card"><div>Small gradient</div></div><div class="feature-card"><div>Partial corners</div></div></div>`;
  const edge='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser=await chromium.launch({...(fs.existsSync(edge)?{executablePath:edge}:{}),headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(html,{waitUntil:'load'});
    const source=fs.readFileSync(path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js'),'utf8');
    await page.addScriptTag({content:source.replace('exports.__landpptPatchVersion =', 'exports.__testAnalyzeRisk = analyzeRiskSubtree; exports.__landpptPatchVersion =')});
    const classification=await page.evaluate(()=>{
      const cases=[
        {name:'direct rounded card',style:'',ignored:true},
        {name:'nested rounded card',nested:true,style:'',ignored:true},
        {name:'filter remains',style:'filter:blur(2px)',reason:'filter'},
        {name:'mask remains',style:'mask-image:linear-gradient(black,transparent)',reason:'mask'},
        {name:'clip-path remains',style:'clip-path:polygon(0 0,100% 0,80% 100%,0 100%)',reason:'complex-clip-path'},
        {name:'backdrop remains',style:'backdrop-filter:blur(3px)',reason:'backdrop-filter'},
        {name:'blend remains',style:'mix-blend-mode:multiply',reason:'mix-blend-mode'},
        {name:'multiple gradients remain',style:'background-image:linear-gradient(red,blue),linear-gradient(white,black)',reason:'multi-layer-gradient'},
        {name:'skew remains',style:'transform:skew(12deg)',clipped:true},
        {name:'scroll remains',overflow:'scroll',style:'',clipped:true},
        {name:'explicit force remains',style:'',forced:true,reason:'forced'},
      ];
      return cases.map(c=>{
        const host=document.createElement('div');
        host.style.cssText=`position:absolute;left:20px;top:20px;width:100px;height:100px;overflow:${c.overflow||'hidden'}`;
        const node=document.createElement('div');node.textContent='Editable rounded card';
        node.style.cssText='width:140px;height:120px;border:2px solid red;border-radius:20px;background:white;transform:rotate(8deg);'+c.style;
        if(c.forced)node.setAttribute('data-pptx-force-risk-raster','');
        if(c.nested){const inner=document.createElement('div');host.appendChild(inner);inner.appendChild(node);}else host.appendChild(node);
        document.body.appendChild(host);
        const parentRisk=domToPptx.__testAnalyzeRisk(host),cardRisk=domToPptx.__testAnalyzeRisk(node);
        host.remove();return {...c,parentRisk,cardRisk};
      });
    });
    for(const c of classification){
      if(c.ignored){assert.equal(c.parentRisk.risky,false,c.name);assert.equal(c.cardRisk.risky,false,c.name);}
      if(c.reason)assert.ok(c.cardRisk.reasons.includes(c.reason),c.name);
      if(c.clipped){assert.ok(c.parentRisk.reasons.includes('transformed-descendant-clipping'),c.name);assert.ok(c.cardRisk.reasons.includes('transformed-clipping'),c.name);}
    }
    const result=await page.evaluate(async()=>{
      const root=document.querySelector('.suite-page'),rr=root.getBoundingClientRect();
      const cards=Array.from(document.querySelectorAll('.feature-card')).map(n=>{
        const s=getComputedStyle(n),r=n.getBoundingClientRect();
        return {x:r.x+r.width/2-rr.x-n.offsetWidth/2,y:r.y+r.height/2-rr.y-n.offsetHeight/2,
          w:n.offsetWidth,h:n.offsetHeight,radius:parseFloat(s.borderTopLeftRadius),border:parseFloat(s.borderTopWidth),
          partial:parseFloat(s.borderTopRightRadius)===0,angle:Math.atan2(new DOMMatrix(s.transform).b,new DOMMatrix(s.transform).a)*180/Math.PI};
      });
      const original=root.outerHTML;
      const blob=await domToPptx.exportToPptx(root,{skipDownload:true,autoEmbedFonts:false});
      if(root.outerHTML!==original)throw new Error('Export changed the live HTML');
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';
      for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
      return {cards,data:btoa(binary),version:domToPptx.__landpptPatchVersion,risk:window.__LANDPPT_PPTX_RISK_FALLBACK_DEBUG__};
    });
    const zip=await JSZip.loadAsync(Buffer.from(result.data,'base64'));
    const xml=await zip.file('ppt/slides/slide1.xml').async('string');
    const pres=await zip.file('ppt/presentation.xml').async('string');
    const shapes=await page.evaluate(({xml,pres})=>{
      const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main';
      const parse=x=>new DOMParser().parseFromString(x,'application/xml'),all=(n,ns,t)=>Array.from(n.getElementsByTagNameNS(ns,t));
      const doc=parse(xml);if(doc.querySelector('parsererror'))throw new Error('Invalid XML');
      const factor=Number(all(parse(pres),p,'sldSz')[0].getAttribute('cx'))/1280;
      return all(doc,p,'sp').map((n,index)=>{
        const pr=all(n,p,'spPr')[0],off=all(pr,a,'off')[0],ext=all(pr,a,'ext')[0],xf=all(pr,a,'xfrm')[0];
        const fill=Array.from(pr.children).find(c=>c.localName==='solidFill'),line=all(pr,a,'ln')[0];
        const gd=all(pr,a,'gd').find(n=>n.getAttribute('name')==='adj'),geom=all(pr,a,'prstGeom')[0];
        return {index,x:Number(off?.getAttribute('x'))/factor,y:Number(off?.getAttribute('y'))/factor,w:Number(ext?.getAttribute('cx'))/factor,h:Number(ext?.getAttribute('cy'))/factor,
          angle:Number(xf?.getAttribute('rot'))/60000,fill:fill&&all(fill,a,'srgbClr')[0]?.getAttribute('val'),line:line&&all(line,a,'srgbClr')[0]?.getAttribute('val'),
          lineWidth:Number(line?.getAttribute('w'))/factor,geometry:geom?.getAttribute('prst')||'custGeom',adj:gd?Number(gd.getAttribute('fmla').split(' ')[1]):null,
          arcs:all(pr,a,'arcTo').map(n=>({rx:Number(n.getAttribute('wR'))/factor,ry:Number(n.getAttribute('hR'))/factor})),
          text:all(n,a,'t').map(n=>n.textContent).join('')};
      });
    },{xml,pres});
    if(process.env.LANDPPT_DEBUG) console.log(JSON.stringify(shapes));
    const near=(a,b)=>Math.abs(a-b)<.05;
    for(const card of result.cards){
      const border=shapes.find(s=>s.line&&near(s.x,card.x+card.border/2)&&near(s.y,card.y+card.border/2)&&near(s.w,card.w-card.border));
      const merged=border?.fill==='FFFFFF';
      const background=merged?border:shapes.find(s=>near(s.x,card.x)&&near(s.y,card.y)&&near(s.w,card.w)&&!s.line&&!s.text);
      const radians=card.angle*Math.PI/180;
      const shadow=shapes.find(s=>near(s.x,card.x-6*Math.sin(radians))&&near(s.y,card.y+6*Math.cos(radians))&&near(s.w,card.w)&&['E85A87','3AA8D8','9570CC'].includes(s.fill));
      console.log(JSON.stringify({card,border,background,shadow}));
      assert.ok(shadow,'Missing native hard shadow');
      const checks = [[border,card.radius-card.border/2],[background,merged?card.radius-card.border/2:card.radius],[shadow,card.radius]];
      assert.ok(border,'Missing inset CSS border');assert.ok(background,'Missing native background');
      for(const [shape,radius] of checks){
        assert.ok(near(((shape.angle-card.angle+540)%360)-180,0),'Rotation changed');
        if(card.partial){assert.equal(shape.geometry,'custGeom');assert.equal(shape.arcs.length,2);shape.arcs.forEach(a=>assert.ok(near(a.rx,radius)&&near(a.ry,radius)));}
        else{assert.equal(shape.geometry,'roundRect');assert.ok(near(shape.adj/100000*Math.min(shape.w,shape.h),radius),'CSS radius differs from PPT radius');}
      }
      assert.ok(near(border.lineWidth,card.border));assert.ok(shadow.index<background.index&&background.index<=border.index);
      if(project)assert.ok(merged,'Card fill and border should be one shape');
    }
    if(project){
      assert.ok(!result.risk.some(r=>r.reasons.some(reason=>reason==='transformed-descendant-clipping'||reason==='transformed-clipping')),'Rounded cards were merged by overflow fallback');
      for(const title of ['GUI到GenUI的转变','MCP-UI解决方案','A2UI协议'])assert.ok(shapes.some(s=>s.text.includes(title)),`Missing editable title: ${title}`);
      const pictures=await page.evaluate(xml=>{
        const doc=new DOMParser().parseFromString(xml,'application/xml');
        return Array.from(doc.getElementsByTagNameNS('http://schemas.openxmlformats.org/presentationml/2006/main','pic')).map(n=>{
          const ext=n.getElementsByTagNameNS('http://schemas.openxmlformats.org/drawingml/2006/main','ext')[0];
          return Number(ext?.getAttribute('cy'));
        });
      },xml);
      // All legitimate pictures on this page are small SVG icons/decorations;
      // a card-height image means the container was flattened again.
      assert.ok(pictures.every(height=>height<1000000),'Card-sized raster remains');
    }
    if(!project){
      // Compare CSS with a rasterization of the exported DrawingML geometry,
      // excluding editable text and the gradient sample (checked structurally).
      const raster=await page.evaluate(shapes=>{
        document.querySelectorAll('.feature-card > *').forEach(n=>n.style.visibility='hidden');
        document.querySelectorAll('.feature-card')[1].style.visibility='hidden';
        const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=720;
        const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,1280,720);
        for(const s of shapes){
          if(s.text||s.x>400&&s.x<620)continue;
          ctx.save();ctx.translate(s.x+s.w/2,s.y+s.h/2);ctx.rotate(s.angle*Math.PI/180);ctx.translate(-s.w/2,-s.h/2);
          const r=s.geometry==='roundRect'?s.adj/100000*Math.min(s.w,s.h):s.arcs[0]?.rx||0;
          ctx.beginPath();ctx.roundRect(0,0,s.w,s.h,s.geometry==='custGeom'?[r,0,r,0]:r);
          if(s.fill){ctx.fillStyle='#'+s.fill;ctx.fill();}
          if(s.line){ctx.lineWidth=s.lineWidth;ctx.strokeStyle='#'+s.line;ctx.stroke();}
          ctx.restore();
        }
        return canvas.toDataURL('image/png').split(',')[1];
      },shapes);
      const css=await sharp(await page.screenshot()).removeAlpha().raw().toBuffer();
      const native=await sharp(Buffer.from(raster,'base64')).removeAlpha().raw().toBuffer();
      assert.equal(css.length,native.length);
      let sum=0,bad=0;for(let i=0;i<css.length;i+=3){let max=0;for(let c=0;c<3;c++){const d=Math.abs(css[i+c]-native[i+c]);sum+=d;max=Math.max(max,d);}if(max>64)bad++;}
      const diff={mean:sum/css.length,badFraction:bad/(css.length/3)};
      console.log({pixelComparison:diff});
      assert.ok(diff.mean<.5&&diff.badFraction<.002,'CSS and exported rounded outline differ');
    }
    console.log(`PASS ${result.version}: ${result.cards.length} cards (native background, inset border, shadow, fractional rotation)`);
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
