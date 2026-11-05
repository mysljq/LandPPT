const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
const cases=[
 {text:'1',size:180,ratio:.85,family:'"Microsoft YaHei"',weight:900,spacing:-7,gradient:true},
 {text:'72%',size:72,ratio:1,family:'"Microsoft YaHei"',weight:900,spacing:-2},
 {text:'08/20',size:28,ratio:1.25,family:'"Microsoft YaHei"',weight:800},
 {text:'93.2%',size:28,ratio:1.25,family:'"Microsoft YaHei"',weight:800},
 {text:'25项',size:28,ratio:1.25,family:'"Microsoft YaHei"',weight:800},
 {text:'99.12%',size:28,ratio:1.25,family:'"Microsoft YaHei"',weight:800},
 {text:'486',size:80,ratio:.85,family:'Arial',weight:700},
 {text:'2',size:160,ratio:1,family:'Georgia',weight:300},
 {text:'3',size:160,ratio:.6,family:'"Times New Roman"',weight:700},
 {text:'2026',size:48,ratio:'normal',family:'Consolas',weight:700},
 {text:'8/20+',size:40,ratio:1.3,family:'Arial',weight:400},
 {text:'804万',size:28,ratio:1.2,family:'"Microsoft YaHei"',weight:700}
];
(async()=>{const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const p=await b.newPage({viewport:{width:1280,height:720}});
 await p.setContent(`<style>*{margin:0;padding:0}body{width:1280px;height:720px;background:white}.slot{position:absolute;width:280px;display:flex;align-items:flex-end}.digit{color:#f00}</style>`+cases.map((c,i)=>`<div class="slot" style="left:${20+(i%4)*315}px;top:${20+Math.floor(i/4)*235}px"><div class="digit" id="n${i}" style='font-family:${c.family};font-size:${c.size}px;font-weight:${c.weight};line-height:${c.ratio};letter-spacing:${c.spacing||0}px;${c.gradient?'background:linear-gradient(90deg,#f00,#ff5050);background-clip:text;color:transparent':''}'>${c.text}</div></div>`).join(''));
 await p.evaluate(()=>document.fonts.ready);
 const before=await p.evaluate(()=>[...document.querySelectorAll('.digit')].map(n=>({html:n.outerHTML,rect:n.getBoundingClientRect().toJSON()})));
 const {data,info}=await sharp(await p.screenshot()).raw().toBuffer({resolveWithObject:true});
 const bounds=cases.map((c,i)=>{let left=20+(i%4)*315,top=Math.floor(i/4)*235,x0=1280,y0=720,x1=-1,y1=-1;for(let y=top;y<top+235;y++)for(let x=left;x<left+280;x++){let k=(y*1280+x)*info.channels;if(data[k]>240&&data[k+1]<239&&data[k+2]<239){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y)}}return{x:x0,y:y0,w:x1-x0+1,h:y1-y0+1}});
 await p.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
 const bytes=await p.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
 const after=await p.evaluate(()=>[...document.querySelectorAll('.digit')].map(n=>({html:n.outerHTML,rect:n.getBoundingClientRect().toJSON()})));
 assert.deepEqual(after,before,'Measuring must restore source DOM and preserve layout');
 const z=await JSZip.loadAsync(Buffer.from(bytes)),xml=await z.file('ppt/slides/slide1.xml').async('string'),shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];
 cases.forEach((c,i)=>{let shape=shapes.find(s=>s.includes(`<a:t>${c.text}</a:t>`));assert.ok(shape&&shape.includes('prst="textPlain"'),c.text+' uses editable measured glyphs');if(c.gradient)assert.ok(shape.includes('<a:gradFill'),'Native gradient remains editable');let off=shape.match(/<a:off x="(-?\d+)" y="(-?\d+)"/),ext=shape.match(/<a:ext cx="(\d+)" cy="(\d+)"/),actual={x:+off[1]/7143.75,y:+off[2]/7143.75,w:+ext[1]/7143.75,h:+ext[2]/7143.75};for(let k of ['x','y','w','h'])assert.ok(Math.abs(actual[k]-bounds[i][k])<=2.1,`${c.text} ${k}: exported ${actual[k]}, browser ${bounds[i][k]}`)});
 console.log('PASS: 12 numeric formats/fonts/line heights (including flex shrink-wrap, gradient, percent, ratios and units) match browser ink within 2px and leave DOM unchanged');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
