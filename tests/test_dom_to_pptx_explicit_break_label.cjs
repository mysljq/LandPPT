const assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {DatabaseSync}=require('node:sqlite'),{chromium}=require('playwright'),JSZip=require('jszip');
(async()=>{const out=path.resolve('tmp/page20-wrap');fs.mkdirSync(out,{recursive:true});
 const html=new DatabaseSync('landppt.db').prepare('select html_content from slide_data where project_id=? and slide_index=19').get('c3a16489-7e3f-4b0f-b728-06e0b4318abc').html_content;
 const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{const p=await b.newPage({viewport:{width:1280,height:720}});await p.setContent(html);await p.screenshot({path:out+'/browser.png'});await p.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
 const bytes=await p.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
 fs.writeFileSync(out+'/page20.pptx',Buffer.from(bytes));const z=await JSZip.loadAsync(Buffer.from(bytes)),xml=await z.file('ppt/slides/slide1.xml').async('string');
 const shape=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g).find(s=>s.includes('<a:t>组主体变更</a:t>'));
 assert.ok(shape);assert.ok(shape.includes('wrap="none"'));assert.equal((shape.match(/<a:p>/g)||[]).length,2);assert.ok(shape.includes('<a:t>托管服务</a:t>'));
 // A paragraph that also wraps naturally must retain width-based wrapping.
 const second=await b.newPage();
 await second.setContent('<p id="wrapped" style="width:60px;font-size:20px">很长的第一段文字自动换行<br>第二行</p>');
 await second.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
 const more=await second.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.querySelector('#wrapped'),{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
 const mz=await JSZip.loadAsync(Buffer.from(more));assert.ok((await mz.file('ppt/slides/slide1.xml').async('string')).includes('wrap="square"'));
 console.log('PASS: explicit two-line label stays two paragraphs without secondary wrapping; naturally wrapped text remains wrappable');
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
