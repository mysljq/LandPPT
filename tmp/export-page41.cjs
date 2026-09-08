const fs=require('fs'),path=require('path'),{execFileSync}=require('child_process'),{chromium}=require('playwright'),JSZip=require('jszip');
(async()=>{
 const repo=path.resolve('.');
 const html=execFileSync(process.execPath,['-e',`const s=require('node:sqlite');const d=new s.DatabaseSync('landppt.db');process.stdout.write(d.prepare('select html_content from slide_data where project_id=? and slide_index=40').get(process.argv[1]).html_content)`,'542faf1c-ba6e-4386-9be1-a79d4cf4cb80'],{encoding:'utf8'});
 const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true}),p=await b.newPage({viewport:{width:1280,height:720}});
 await p.setContent(html);await p.addScriptTag({path:path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js')});
 const result=await p.evaluate(async()=>{const blob=await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false});const a=new Uint8Array(await blob.arrayBuffer());let s='';for(let i=0;i<a.length;i+=32768)s+=String.fromCharCode(...a.subarray(i,i+32768));return btoa(s)});
 const bytes=Buffer.from(result,'base64');fs.writeFileSync('tmp/page41.pptx',bytes);const z=await JSZip.loadAsync(bytes);const xml=await z.file('ppt/slides/slide1.xml').async('string');
 const shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];console.log(shapes.filter(s=>s.includes('THANK YOU')).join('\n'));
 await b.close();
})();
