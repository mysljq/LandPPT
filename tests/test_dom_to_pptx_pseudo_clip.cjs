// Full export regression: oversized gradients must keep their colors and be
// clipped to the owner's rounded padding edge, including the PNG fallback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');

async function main() {
  const repo = path.resolve(__dirname, '..');
  const project = process.argv.includes('--project');
  const html = project ? execFileSync(process.env.LANDPPT_TEST_PYTHON, ['-X', 'utf8', '-c',
    "import sqlite3; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=31',('542faf1c-ba6e-4386-9be1-a79d4cf4cb80',)).fetchone()[0])"], { cwd: repo, encoding: 'utf8' }) :
    `<style>*{box-sizing:border-box}body{margin:0;width:1280px;height:720px}.fixture{position:absolute;top:60px;width:300px;height:200px;border:2px solid #555;overflow:hidden;border-radius:40px;background:#fff}.fixture::before{content:"";position:absolute;left:0;top:0;width:100%;height:3px;background:linear-gradient(90deg,#b8763d,#d4a574)}.two{left:370px;border-radius:30px 60px 20px 40px}.three{left:720px;border-radius:20% 10%}.three::before{left:-10px;top:-1px;width:calc(100% + 20px);height:8px}</style><div class="fixture"></div><div class="fixture two"></div><div class="fixture three"></div>`;
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.setContent(html);
    if (!project) await page.locator('.fixture').evaluateAll(nodes=>nodes.forEach(n=>{const label=document.createElement('span');label.textContent='Card';n.appendChild(label);}));
    await page.addScriptTag({ path: path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async () => {
      const fields = ['width','height','borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth',
        'borderTopLeftRadius','borderTopRightRadius','borderBottomRightRadius','borderBottomLeftRadius'];
      const pseudoFields = ['position','left','top','right','bottom','width','height','boxSizing','backgroundColor','backgroundImage','borderRadius'];
      const cards = [...document.querySelectorAll('*')].filter(el => {
        const s = getComputedStyle(el), p = getComputedStyle(el,'::before');
        return s.overflow === 'hidden' && p.backgroundImage.includes('linear-gradient');
      }).map(el => {
        const s = getComputedStyle(el), p = getComputedStyle(el,'::before'), r=el.getBoundingClientRect();
        return { x:r.x, y:r.y, w:r.width, h:r.height,
          owner:Object.fromEntries(fields.map(f => [f,s[f]])), pseudo:Object.fromEntries(pseudoFields.map(f => [f,p[f]])) };
      });
      const blob = await domToPptx.exportToPptx(document.querySelector('.suite-page') || document.body, { skipDownload:true, autoEmbedFonts:false });
      const bytes = new Uint8Array(await blob.arrayBuffer()); let binary='';
      for(let i=0;i<bytes.length;i+=32768) binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
      return { cards, data:btoa(binary), version:domToPptx.__landpptPatchVersion };
    });
    assert.equal(result.cards.length,3);
    assert.deepEqual(errors,[]);
    const zip = await JSZip.loadAsync(Buffer.from(result.data,'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const rels = await zip.file('ppt/slides/_rels/slide1.xml.rels').async('string');
    const pres = await zip.file('ppt/presentation.xml').async('string');
    const pictures = await page.evaluate(({xml,rels,pres}) => {
      const parse=s=>new DOMParser().parseFromString(s,'application/xml');
      const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main',r='http://schemas.openxmlformats.org/officeDocument/2006/relationships';
      const all=(n,ns,t)=>[...n.getElementsByTagNameNS(ns,t)];
      const relationships=Object.fromEntries([...parse(rels).documentElement.children].map(n=>[n.getAttribute('Id'),n.getAttribute('Target').replace('../','ppt/')]));
      const factor=Number(all(parse(pres),p,'sldSz')[0].getAttribute('cx'))/1280;
      return all(parse(xml),p,'pic').map(n=>{
        const xfrm=all(n,a,'xfrm')[0], off=all(xfrm,a,'off')[0],ext=all(xfrm,a,'ext')[0];
        return { x:Number(off.getAttribute('x'))/factor,y:Number(off.getAttribute('y'))/factor,
          w:Number(ext.getAttribute('cx'))/factor,h:Number(ext.getAttribute('cy'))/factor,
          media:[...n.getElementsByTagName('*')].filter(e=>e.hasAttributeNS(r,'embed')).map(e=>relationships[e.getAttributeNS(r,'embed')]) };
      });
    },{xml,rels,pres});
    const clips=[];
    for(const pic of pictures) for(const name of pic.media.filter(n=>n.endsWith('.svg'))) {
      const svg=await zip.file(name).async('string');
      if(svg.includes('data-landppt-owner-clip')) clips.push({pic,svg});
    }
    if (clips.length !== 3) console.log({pictures, media:Object.keys(zip.files).filter(n=>n.startsWith('ppt/media/'))});
    assert.equal(clips.length,3,'Each card strip must contain an actual SVG clipPath, not a rounded picture box');
    const visual = await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:4});
    for(let i=0;i<result.cards.length;i++) {
      const card=result.cards[i];
      const match=clips.find(c=>Math.abs(c.pic.y-card.y-parseFloat(card.owner.borderTopWidth)-parseFloat(card.pseudo.top))<.1 && Math.abs(c.pic.x-card.x)<15);
      assert.ok(match,'Clipped strip must retain its measured position');
      assert.ok((match.svg.match(/<stop\b/g)||[]).length>=2,'Gradient must not be replaced with its first color');
      const pngName=match.pic.media.find(n=>n.endsWith('.png'));
      assert.ok(pngName,'Office PNG fallback must exist');
      const preview=await sharp(await zip.file(pngName).async('nodebuffer')).ensureAlpha().raw().toBuffer();
      assert.ok(preview.some((v,j)=>j%4===3&&v>128),'PNG fallback must not be blank');
      assert.ok(preview[3]<32,'PNG fallback must preserve the transparent corner');
      const clip={x:0,y:0,width:Math.ceil(card.w),height:Math.max(12,Math.ceil(parseFloat(card.pseudo.height)+4))};
      await visual.setContent('<style>html,body{margin:0;background:transparent}</style><div id="owner"></div>');
      await visual.evaluate(card=>{
        const el=document.querySelector('#owner');Object.assign(el.style,card.owner,{position:'absolute',left:'0px',top:'0px',boxSizing:'border-box',overflow:'hidden',borderStyle:'solid',borderColor:'transparent'});
        const deco=document.createElement('div');Object.assign(deco.style,card.pseudo);el.appendChild(deco);
      },card);
      const source=await visual.screenshot({clip,omitBackground:true});
      await visual.setContent('<style>html,body{margin:0;background:transparent}</style><img id="exported">');
      await visual.evaluate(({card,pic,svg})=>{
        const el=document.querySelector('#exported');Object.assign(el.style,{position:'absolute',left:`${pic.x-card.x}px`,top:`${pic.y-card.y}px`,width:`${pic.w}px`,height:`${pic.h}px`});
        el.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);return el.decode();
      },{card,pic:match.pic,svg:match.svg});
      const exported=await visual.screenshot({clip,omitBackground:true});
      const a=await sharp(source).ensureAlpha().raw().toBuffer(),b=await sharp(exported).ensureAlpha().raw().toBuffer();
      let alphaError=0,visible=0,spill=0;
      for(let j=3;j<a.length;j+=4){alphaError+=Math.abs(a[j]-b[j]);if(a[j]>128)visible++;if(a[j]===0&&b[j]>32)spill++;}
      assert.ok(visible>30,'Reference strip must be visible');
      assert.ok(alphaError/(a.length/4)<2,`Card ${i}: alpha mismatch ${alphaError/(a.length/4)}`);
      assert.ok(spill<20,`Card ${i}: ${spill} visible pixels outside CSS rounded clip`);
      if(process.env.LANDPPT_CLIP_QA_DIR){fs.mkdirSync(process.env.LANDPPT_CLIP_QA_DIR,{recursive:true});await sharp({create:{width:Math.ceil(card.w)*4,height:clip.height*8,channels:4,background:'#ffffff'}}).composite([{input:source,top:0,left:0},{input:exported,top:clip.height*4,left:0}]).png().toFile(path.join(process.env.LANDPPT_CLIP_QA_DIR,`card-${i}.png`));}
      console.log({card:i,alphaError:alphaError/(a.length/4),spill,visible});
    }
    console.log(`PASS ${result.version}: ${project?'page32':'fixture'} three visible, gradient-preserving rounded intersections`);
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
