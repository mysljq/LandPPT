const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright'),JSZip=require('jszip');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  await page.setContent(`<style>*{margin:0;padding:0;box-sizing:border-box}html,body{width:1280px;height:720px;overflow:hidden}.pair{position:absolute;top:100px;font-weight:700;line-height:1;color:transparent;-webkit-text-stroke:2px #c00000}.offset{position:absolute;color:rgba(192,0,0,.12);-webkit-text-stroke:0;line-height:inherit;font:inherit}.a{left:50px;font-family:"Times New Roman";font-size:260px}.a .offset{left:6px;top:6px}.b{left:300px;font-family:Georgia;font-size:180px}.b .offset{left:-4px;top:8px}.c{left:550px;font-family:Arial;font-size:120px}.c .offset{left:9px;top:-3px}.clipped{left:800px;font-family:"Times New Roman";font-size:200px}.clipped .offset{left:0;top:0;clip-path:inset(50% 0 0 0)}.plain{position:absolute;left:1080px;top:100px;font:80px Arial;line-height:.85}.sibling{position:absolute;font:900 340px Impact;line-height:.85;letter-spacing:-12px}.back{top:340px;left:60px;color:transparent;-webkit-text-stroke:2px rgba(239,230,212,.15)}.front{top:320px;left:40px;color:#c8324a}</style><div class="sibling back">5</div><div class="sibling front">5</div><div class="pair a">2<div class="offset">2</div></div><div class="pair b">3<div class="offset">3</div></div><div class="pair c">4<div class="offset">4</div></div><div class="pair clipped">9<div class="offset">9</div></div><div class="plain">486</div>`);
  await page.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
  const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
  const zip=await JSZip.loadAsync(Buffer.from(bytes)),xml=await zip.file('ppt/slides/slide1.xml').async('string');
  const shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];
  const off=s=>{const m=s.match(/<a:off x="(-?\d+)" y="(-?\d+)"/);return{x:Number(m[1])/7143.75,y:Number(m[2])/7143.75}};
  for(const [text,dx,dy] of [['2',6,6],['3',-4,8],['4',9,-3],['5',-20,-20]]){
   const pair=shapes.filter(s=>s.includes(`<a:t>${text}</a:t>`));assert.equal(pair.length,2,'Both layers remain native editable text');
   const outline=pair.find(s=>/<a:rPr[\s\S]*?<a:ln /.test(s)),fill=pair.find(s=>s!==outline);
   assert.ok(outline&&fill);
   assert.ok(pair.every(s=>s.includes('prst="textPlain"')),'Both layers use the same measured glyph geometry');
   const a=off(outline),b=off(fill);
   assert.ok(Math.abs(b.x-a.x-dx)<.02,`${text}: actual horizontal offset retained`);
   assert.ok(Math.abs(b.y-a.y-dy)<.02,`${text}: actual vertical offset retained without fixed downshift`);
  }
  const clipped=shapes.find(s=>s.includes('<a:t>9</a:t>'));
  assert.ok(clipped&&!clipped.includes('prst="textPlain"'),'Clipped overlay continues using its existing alignment policy');
  const plain=shapes.find(s=>s.includes('<a:t>486</a:t>'));
  assert.ok(plain&&plain.includes('prst="textPlain"')&&plain.includes('val="85000"'),'Multi-digit counters share measured geometry while preserving numeric leading');
  console.log('PASS: editable outline/fill digits share browser ink geometry across fonts/sizes/offsets; clipped and plain counters retain existing behavior');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
