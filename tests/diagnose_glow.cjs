const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {DatabaseSync}=require('node:sqlite');
const {chromium}=require('playwright');
const JSZip=require('jszip');
(async()=>{
 const html=new DatabaseSync('landppt.db').prepare('select html_content from slide_data where project_id=? and slide_index=15').get('c3a16489-7e3f-4b0f-b728-06e0b4318abc').html_content;
 const out=path.resolve('tmp/glow-check');fs.mkdirSync(out,{recursive:true});
 const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{const p=await b.newPage({viewport:{width:1280,height:720}});await p.setContent(html);await p.screenshot({path:out+'/browser.png'});
 const source=fs.readFileSync('src/landppt/web/static/js/dom-to-pptx.bundle.js','utf8');
 await p.addScriptTag({content:source.replace('function generateRepeatingRadialPatternSVG(', 'window.__testDot = generateRepeatingRadialPatternSVG; function generateRepeatingRadialPatternSVG(')});
 const data=await p.evaluate(async()=>{const blob=await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false});return Array.from(new Uint8Array(await blob.arrayBuffer()));});
 fs.writeFileSync(out+'/page16.pptx',Buffer.from(data));const z=await JSZip.loadAsync(Buffer.from(data));
 for(const f of Object.values(z.files).filter(f=>/^ppt\/media\//.test(f.name)&&!f.dir)){fs.writeFileSync(out+'/'+path.basename(f.name),await f.async('nodebuffer'));}
 const xml=await z.file('ppt/slides/slide1.xml').async('string');fs.writeFileSync(out+'/slide.xml',xml);
 const yearRun=(xml.match(/<a:r>[\s\S]*?<\/a:r>/g)||[]).find(run=>run.includes('<a:t>2026</a:t>'));
 assert.ok(yearRun && yearRun.includes('typeface="Arial"'), 'Missing Helvetica Neue must fall through to installed Arial for 2026');
 assert.ok(!xml.includes('CSS radial pattern'), 'Full-size multilayer glow must not be exported as a dot pattern');
 const sharp=require('sharp');
 const glow=await z.file('ppt/media/image-1-2.png').async('nodebuffer');
 const stats=await sharp(glow).ensureAlpha().stats();
 assert.ok(stats.channels[3].max>0 && stats.channels[3].max<100, 'Glow must preserve subtle transparency');
 const dots=await p.evaluate(()=>window.__testDot(120,120,'radial-gradient(circle,#123456 1px,transparent 2px)','12px 12px',1));
 assert.ok(dots && dots.includes('base64'), 'Real tiled pixel dots must retain their existing export');
 console.log('PASS: page16 glow PNG transparency and true dot-pattern export');
 }finally{await b.close();}
})();
