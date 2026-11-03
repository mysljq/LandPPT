const assert=require('node:assert/strict'),path=require('node:path'),{chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1280,height:720}});
 await page.setContent(`<style>*{margin:0;padding:0}body{width:1280px;height:720px;background:#111}.digit{position:absolute;top:172px;left:50px;font:800 300px Consolas;line-height:.85;letter-spacing:-8px}.outline{z-index:5;color:transparent;-webkit-text-stroke:2px rgba(124,58,237,.4)}.glow{z-index:4;color:rgba(124,58,237,.06);filter:blur(4px)}.second{left:450px;top:190px;font:700 180px Georgia;line-height:1.1}</style><div class="digit glow">2</div><div class="digit outline">2</div><div class="digit second glow">3</div><div class="digit second outline">3</div>`);
 await page.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
 const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
 const zip=await JSZip.loadAsync(Buffer.from(bytes)),xml=await zip.file('ppt/slides/slide1.xml').async('string');
 const shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];
 for(const number of ['2','3']){const digits=shapes.filter(s=>s.includes(`<a:t>${number}</a:t>`));assert.equal(digits.length,1,'Glow does not create a second unfiltered text run');assert.ok(digits[0].includes('prst="textPlain"'),'Outline remains editable measured WordArt');assert.ok(digits[0].includes('val="40000"'),'Outline retains alpha')}
 const pictures=xml.match(/<p:pic>[\s\S]*?<\/p:pic>/g)||[];assert.equal(pictures.length,2,'Each glow has its own isolated effect image');
 for(const [i,top] of [172,190].entries()){const off=pictures[i].match(/<a:off x="(-?\d+)" y="(-?\d+)"/);assert.ok(Math.abs(+off[2]/7143.75-(top-12))<.01,'Glow uses CSS origin with blur padding, without legacy numeric shift')}
 const media=Object.values(zip.files).filter(f=>/^ppt\/media\/.*\.png$/.test(f.name));assert.equal(media.length,2);
 for(const file of media){const {data,info}=await sharp(await file.async('nodebuffer')).ensureAlpha().raw().toBuffer({resolveWithObject:true});let max=0,partial=0;for(let i=3;i<data.length;i+=info.channels){max=Math.max(max,data[i]);if(data[i]>0&&data[i]<14)partial++}assert.ok(max>0&&max<=16,'Faint glow is visible and retains 6% alpha');assert.ok(partial>100,'Blur produces softly varying alpha')}
 console.log('PASS: blurred numeric siblings align to CSS origin, preserve soft alpha and keep one editable outline per number');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
