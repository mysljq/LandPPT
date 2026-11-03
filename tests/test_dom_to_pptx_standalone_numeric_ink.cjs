const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1280,height:720}});
 await page.setContent(`<style>*{margin:0;padding:0}body{width:1280px;height:720px;background:white}.digit{position:absolute;top:180px;color:#f00;letter-spacing:-.02em}.a{left:80px;font:300 160px Georgia;line-height:1}.b{left:400px;font:700 200px 'Times New Roman';line-height:.85}.c{left:800px;font:120px Arial;line-height:1.3}.a::after{content:'';position:absolute;bottom:18px;right:-12px;width:10px;height:10px;background:green;border-radius:50%}</style><div class="digit a">2</div><div class="digit b">3</div><div class="digit c">4</div>`);
 await page.evaluate(()=>document.fonts.ready);
 const pixels=await sharp(await page.screenshot()).raw().toBuffer({resolveWithObject:true});
 const boxes=[{text:'2',left:50,right:300},{text:'3',left:350,right:650},{text:'4',left:750,right:1050}].map(region=>{
  let x0=1280,y0=720,x1=-1,y1=-1;const {data,info}=pixels;
  for(let y=100;y<500;y++)for(let x=region.left;x<region.right;x++){let i=(y*info.width+x)*info.channels;if(data[i]>240&&data[i+1]<239&&data[i+2]<239){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y)}}
  return{...region,x:x0,y:y0,w:x1-x0+1,h:y1-y0+1};
 });
 await page.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
 const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
 const zip=await JSZip.loadAsync(Buffer.from(bytes)),xml=await zip.file('ppt/slides/slide1.xml').async('string');
 // DOM subpixel painting and integer Canvas rasterization can differ by two antialiased edge pixels.
 for(const box of boxes){const shape=(xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[]).find(s=>s.includes(`<a:t>${box.text}</a:t>`));assert.ok(shape&&shape.includes('prst="textPlain"'),'Counter remains native editable text');const off=shape.match(/<a:off x="(-?\d+)" y="(-?\d+)"/),ext=shape.match(/<a:ext cx="(\d+)" cy="(\d+)"/);const actual={x:+off[1]/7143.75,y:+off[2]/7143.75,w:+ext[1]/7143.75,h:+ext[2]/7143.75};for(const key of ['x','y','w','h'])assert.ok(Math.abs(actual[key]-box[key])<=2.1,`${box.text} ${key}: PPT ${actual[key]}, browser ink ${box[key]}`)}
 console.log('PASS: available-font counters match actual browser pixel bounds across fonts, weights and line heights; pseudo decoration stays separate');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});

