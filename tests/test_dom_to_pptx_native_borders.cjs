// NODE_PATH: bundled playwright, jszip, sharp. Optional --project <id> uses
// LANDPPT_TEST_PYTHON to inspect local slide_index 15 without changing the DB.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');

async function main() {
  const repo = path.resolve(__dirname, '..');
  const index = process.argv.indexOf('--project');
  const project = index >= 0 ? process.argv[index+1] : null;
  const html = project ? execFileSync(process.env.LANDPPT_TEST_PYTHON, ['-X','utf8','-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=15',(sys.argv[1],)).fetchone()[0])",project],
    {cwd:repo,encoding:'utf8'}) : fs.readFileSync(path.join(__dirname,'fixtures/dom_to_pptx_native_borders.html'),'utf8');
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({...(fs.existsSync(edge)?{executablePath:edge}:{}),headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:720}});
    const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
    await page.setContent(html,{waitUntil:'load'});
    const source = fs.readFileSync(path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js'),'utf8');
    await page.addScriptTag({content:source.replace('exports.__landpptPatchVersion =',
      'exports.__testBorderItems = createNativeCompositeBorderItems; exports.__testBorderInfo = getBorderInfo; exports.__landpptPatchVersion =')});
    const selector = project ? '.card-right .data-comparison, .card-right .reason-group' : '.test-card';
    const result = await page.evaluate(async selector=>{
      const root=document.querySelector('.suite-page'), rr=root.getBoundingClientRect();
      const cards=Array.from(document.querySelectorAll(selector)).map(node=>{
        const s=getComputedStyle(node),r=node.getBoundingClientRect();
        return {x:r.x-rr.x,y:r.y-rr.y,w:r.width,h:r.height,text:node.textContent.replace(/\s/g,''),rotated:s.transform!=='none',allowBackgroundImage:!!node.dataset.backgroundImage};
      });
      const blob=await domToPptx.exportToPptx(root,{skipDownload:true,autoEmbedFonts:false});
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';
      for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
      return {cards,data:btoa(binary),version:domToPptx.__landpptPatchVersion};
    },selector);
    const zip=await JSZip.loadAsync(Buffer.from(result.data,'base64'));
    const xml=await zip.file('ppt/slides/slide1.xml').async('string');
    const pres=await zip.file('ppt/presentation.xml').async('string');
    const objects=await page.evaluate(({xml,pres})=>{
      const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main';
      const parse=x=>new DOMParser().parseFromString(x,'application/xml'),all=(n,ns,t)=>Array.from(n.getElementsByTagNameNS(ns,t));
      const doc=parse(xml),factor=Number(all(parse(pres),p,'sldSz')[0].getAttribute('cx'))/1280;
      const tree=all(doc,p,'spTree')[0];
      return Array.from(tree.getElementsByTagNameNS(p,'*')).filter(n=>['sp','pic'].includes(n.localName)).map((n,i)=>{
        const pr=all(n,p,'spPr')[0],off=all(pr,a,'off')[0],ext=all(pr,a,'ext')[0],xf=all(pr,a,'xfrm')[0];
        const fill=Array.from(pr.children).find(c=>c.localName==='solidFill');
        const alpha=fill&&all(fill,a,'alpha')[0];
        return {index:i,type:n.localName,name:all(n,p,'cNvPr')[0]?.getAttribute('name'),
          x:Number(off?.getAttribute('x'))/factor,y:Number(off?.getAttribute('y'))/factor,w:Number(ext?.getAttribute('cx'))/factor,h:Number(ext?.getAttribute('cy'))/factor,
          rot:Number(xf?.getAttribute('rot'))/60000,text:all(n,a,'t').map(t=>t.textContent).join('').replace(/\s/g,''),
          color:fill&&all(fill,a,'srgbClr')[0]?.getAttribute('val'),alpha:alpha?Number(alpha.getAttribute('val')):100000,
          custom:all(pr,a,'custGeom').length,curves:all(pr,a,'cubicBezTo').length,
        };
      });
    },{xml,pres});
    const borders=objects.filter(o=>o.name?.startsWith('CSS border '));
    console.log(JSON.stringify({project:project||'fixture',version:result.version,borders,errors},null,2));
    assert.deepEqual(errors,[]);
    assert.equal(borders.length,project?3:18);
    for(const border of borders){assert.equal(border.type,'sp');assert.equal(border.custom,1);assert.ok(Math.min(border.w,border.h)<=26,'Border selection box covers the card');}
    result.cards.filter(c=>!c.rotated).forEach(card=>{
      const edges=borders.filter(b=>b.x>=card.x-1&&b.y>=card.y-1&&b.x+b.w<=card.x+card.w+1&&b.y+b.h<=card.y+card.h+1);
      assert.ok(edges.length,'Missing native card edge');
      const texts=objects.filter(o=>o.text&&card.text.includes(o.text)&&o.x>=card.x-1&&o.x<card.x+card.w&&o.y>=card.y-1&&o.y<card.y+card.h);
      if(card.text)assert.ok(texts.length,'Card text disappeared');
      edges.forEach(edge=>texts.forEach(text=>assert.ok(edge.index<text.index,'Border covers text in stacking order')));
      if(!card.allowBackgroundImage)assert.ok(!objects.some(o=>o.type==='pic'&&Math.abs(o.x-card.x)<1&&Math.abs(o.y-card.y)<1&&o.w>card.w*.9&&o.h>card.h*.9),`Full-card border picture remains: ${card.text}`);
    });
    if(project){
      assert.deepEqual(borders.map(b=>b.color).sort(),['6BCF7F','B388FF','FF6B9D']);
      borders.forEach(b=>{assert.ok(b.w<=12.1);assert.ok(b.curves>0);});
    }else{
      assert.ok(borders.some(b=>Math.abs(b.rot-12)<.01));
      assert.ok(borders.some(b=>b.alpha===30000));
      const diffs=[];
      for(let i=0;i<result.cards.length;i++){
        if(result.cards[i].rotated)continue;
        const data=await page.evaluate(({selector,i})=>{
          const node=document.querySelectorAll(selector)[i];node.textContent='';node.style.background='white';
          const s=getComputedStyle(node),r=node.getBoundingClientRect();
          const items=domToPptx.__testBorderItems(s,domToPptx.__testBorderInfo(s,1).sides,{x:0,y:0,w:r.width/96,h:r.height/96,widthPx:r.width,heightPx:r.height,rotate:0},1,0,0,parseFloat(s.opacity));
          const canvas=document.createElement('canvas');canvas.width=r.width;canvas.height=r.height;const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,canvas.width,canvas.height);
          for(const {options:o} of items){ctx.save();ctx.translate(o.x*96,o.y*96);ctx.beginPath();o.points.forEach((p,index)=>{
            if(p.close)ctx.closePath();else if(p.curve)ctx.bezierCurveTo(p.curve.x1*96,p.curve.y1*96,p.curve.x2*96,p.curve.y2*96,p.x*96,p.y*96);else if(!index)ctx.moveTo(p.x*96,p.y*96);else ctx.lineTo(p.x*96,p.y*96);
          });ctx.globalAlpha=1-o.fill.transparency/100;ctx.fillStyle='#'+o.fill.color;ctx.fill();ctx.restore();}
          return canvas.toDataURL('image/png').split(',')[1];
        },{selector,i});
        const actual=await page.locator(selector).nth(i).screenshot();
        const css=await sharp(actual).removeAlpha().raw().toBuffer();
        const native=await sharp(Buffer.from(data,'base64')).removeAlpha().raw().toBuffer();
        assert.equal(css.length,native.length);
        let sum=0,bad=0;for(let k=0;k<css.length;k+=3){let max=0;for(let j=0;j<3;j++){const d=Math.abs(css[k+j]-native[k+j]);sum+=d;max=Math.max(max,d);}if(max>64)bad++;}
        const diff={i,mean:sum/css.length,badFraction:bad/(css.length/3)};diffs.push(diff);
        assert.ok(diff.mean<1.5&&diff.badFraction<.005,`CSS vs native border mismatch: ${JSON.stringify(diff)}`);
      }
      console.log(JSON.stringify({pixelComparisons:diffs}));
    }
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
