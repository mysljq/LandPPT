const assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {chromium}=require('playwright'),JSZip=require('jszip'),sharp=require('sharp');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  await page.setContent(`<style>*{margin:0;padding:0;box-sizing:border-box}html,body{width:1280px;height:720px;overflow:hidden}body{position:relative;background:#fafafa;font-family:Arial}.cursive{position:absolute;left:20px;top:10px;font:40px "Segoe Print","Comic Sans MS",cursive}.thin{position:absolute;left:20px;top:70px;font-family:"Segoe UI","Microsoft YaHei",sans-serif;font-size:40px;font-weight:300}.svgwrap{position:absolute;left:20px;top:150px;width:130px;height:130px}.svgwrap svg{width:130px;height:130px}.gradient{position:absolute;top:300px;left:20px;font-size:48px;font-weight:700;background:linear-gradient(90deg,#A78BFA,#3B82F6);background-clip:text;-webkit-background-clip:text;color:transparent}.outside{position:absolute;left:1100px;top:30px;transform:translateX(50px);width:200px;height:200px}.outside div{width:150px;height:150px;border:1px solid red;border-radius:50%}.gridbox{position:absolute;left:450px;top:30px;width:200px;height:150px;overflow:hidden}.grid{position:absolute;inset:0;background:linear-gradient(red 1px,transparent 1px),linear-gradient(90deg,red 1px,transparent 1px);background-size:40px 40px}.shadow{position:absolute;left:450px;top:300px;width:180px;height:80px;background:rgba(250,245,236,.7);border:2px solid #1A2B3D;box-shadow:4px 4px 0 #2D4A6B}.stack{position:absolute;left:450px;top:430px;width:180px;height:100px;background:#f7f8fc;border:2px solid black;border-radius:10px;box-shadow:14px 14px 0 #a06bff,14px 14px 0 3px #14121f}.blur{position:absolute;left:950px;top:410px;width:200px;height:200px;border-radius:50%;background:radial-gradient(circle,#A78BFA,transparent 70%);filter:blur(20px);opacity:.5}.clip{position:absolute;left:700px;top:100px;width:220px;height:90px;border:1px solid cyan;background:linear-gradient(135deg,rgba(0,240,255,.2),rgba(255,45,149,.1));clip-path:polygon(0 0,calc(100% - 14px) 0,100% 14px,100% 100%,14px 100%,0 calc(100% - 14px));display:flex;align-items:center;justify-content:center}</style><div class="cursive">部门年度工作报告</div><div class="thin">年度工作报告</div><div class="svgwrap"><svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="58" fill="#9D2933"/><text x="60" y="68" text-anchor="middle" fill="gold" font-size="28">福</text></svg></div><div class="gradient">Gradient title</div><div class="outside"><div></div></div><div class="gridbox"><div class="grid"></div></div><div class="shadow"></div><div class="stack"></div><div class="blur"></div><div class="clip"><span>EDITABLE</span></div>`);
  await page.evaluate(()=>document.body.insertAdjacentHTML('beforeend','<div style="position:absolute;left:20px;top:650px;width:600px;font-size:160px;color:rgba(0,0,0,.05)">DECORATION</div><div style="position:absolute;left:700px;top:500px;font-size:160px;color:rgba(0,0,0,.05)">1</div>'));
  await page.evaluate(()=>document.body.insertAdjacentHTML('beforeend','<div style="position:absolute;left:700px;top:600px;font:900 30px Georgia,serif">第2章</div>'));
  const source=fs.readFileSync(path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js'),'utf8').replace('exports.__landpptPatchVersion =','exports.__auditRisk=getRiskFallbackDebug;exports.__landpptPatchVersion =');
  await page.addScriptTag({content:source});
  const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
  const zip=await JSZip.loadAsync(Buffer.from(bytes)),xml=await zip.file('ppt/slides/slide1.xml').async('string');
  const shapes=xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[];
  const handwritten=shapes.find(s=>s.includes('部门年度工作报告'));
  assert.ok(handwritten&&/typeface="微软雅黑"/.test(handwritten),'Latin cursive chain follows actual linked Microsoft YaHei glyphs, not an assumed KaiTi');
  const thin=shapes.find(s=>s.includes('<a:t>年度工作报告</a:t>'));
  assert.ok(shapes.find(s=>s.includes('<a:t>第2章</a:t>')).includes('<a:latin typeface="Georgia"'),'CJK weight matching does not overwrite Latin/digit face in mixed runs');
  assert.ok(thin&&/<a:ea[^>]+typeface="微软雅黑 Light"/.test(thin),'Light CJK variant is applied to East Asian slot too');
  const gradient=shapes.find(s=>s.includes('Gradient title'));
  assert.ok(gradient&&gradient.includes('<a:gradFill'),'Gradient heading stays native and editable');
  const debug=await page.evaluate(()=>domToPptx.__auditRisk());
  assert.ok(!xml.includes('<a:t>DECORATION</a:t>')&&xml.includes('<a:t>1</a:t>'),'Only oversized faint decorative text is rasterized; standalone numbers remain editable');
  assert.ok(!debug.some(r=>r.tagName==='BODY'),'Translated empty decorative containers do not flatten unrelated text');
  assert.equal((xml.match(/<a:t>福<\/a:t>/g)||[]).length,1,'SVG text remains editable');
  const knockout=shapes.find(s=>s.includes('2D4A6B')&&s.includes('<a:custGeom>'));
  assert.ok(knockout&&knockout.includes('<a:moveTo>'),'Translucent card shadow excludes the original surface');
  const black=shapes.find(s=>s.includes('CSS outer shadow layer')&&s.includes('14121F'));
  const purple=shapes.find(s=>s.includes('CSS outer shadow layer')&&s.includes('A06BFF'));
  assert.ok(black&&purple&&xml.indexOf(black)<xml.indexOf(purple),'CSS first shadow paints in front');
  const width=s=>Number(s.match(/<a:ext cx="(\d+)"/)[1]);
  assert.ok(Math.abs(width(black)-width(purple)-6*7143.75)<2,'Hard-shadow spread is native geometry');
  assert.equal((xml.match(/<a:t>EDITABLE<\/a:t>/g)||[]).length,1,'Clipped card text is independent of its visual capture');
  const images=[];
  for(const n of Object.keys(zip.files).filter(n=>/^ppt\/media\/.*png$/.test(n))){const raw=await sharp(await zip.file(n).async('nodebuffer')).ensureAlpha().raw().toBuffer({resolveWithObject:true});images.push(raw);}
  const grid=images.find(r=>r.info.width===400&&r.info.height===300);
  assert.ok(grid&&grid.data.some((v,i)=>i%4===3&&v>0),'Grid inside square clipped container is nonempty');
  assert.ok(images.some(r=>r.info.width===390&&r.info.height===390&&r.data.some((v,i)=>i%4===3&&v===255)),'SVG artwork survives parent text classification');
  const blur=images.find(r=>r.info.width===640&&r.info.height===640);
  assert.ok(blur,'CSS blur includes three-sigma transparent padding');
  let max=0,index=0;for(let i=3;i<blur.data.length;i+=4)if(blur.data[i]>max){max=blur.data[i];index=i-3;}
  assert.ok(max>10&&blur.data[index+2]-blur.data[index]>50,'Purple gradient blur keeps chroma instead of gray/black interpolation');
  assert.ok(images.some(r=>r.info.width===488&&r.info.height===228&&r.data.some((v,i)=>i%4===3&&v>0)),'calc polygon visual capture is not empty');
  await page.close();
  const scene=await browser.newPage({viewport:{width:1280,height:720}});
  await scene.setContent(`<body><style>*{margin:0;padding:0;box-sizing:border-box}html,body{width:1280px;height:720px;overflow:hidden;background:#fafafa}.scene{position:absolute;left:50px;top:40px;width:1280px;height:720px;background:#ddeeff}.paint{position:absolute;inset:0;background:radial-gradient(circle at 30% 30%,#a78bfa,transparent 70%)}.noise{position:absolute;inset:0;background:#bbb;opacity:.1;mix-blend-mode:overlay}.decor{position:absolute;left:500px;top:150px;width:200px;height:200px;background:#123456;filter:url(#desaturate)}.glass{position:absolute;left:450px;top:100px;width:300px;height:300px;background:rgba(255,255,255,.3);backdrop-filter:blur(20px)}.glass p{position:absolute;left:20px;top:30px;color:black}</style><svg width="0" height="0"><defs><filter id="desaturate"><feColorMatrix type="saturate" values=".5"/></filter></defs></svg><div class="scene"><div class="paint"></div><div class="noise"></div><div class="decor"></div><div class="glass"><p>Native glass caption</p></div></div>`);
  await scene.addScriptTag({content:source});
  const sceneBytes=await scene.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
  const sceneZip=await JSZip.loadAsync(Buffer.from(sceneBytes)),sceneXml=await sceneZip.file('ppt/slides/slide1.xml').async('string');
  assert.ok(sceneXml.includes('CSS composed slide backdrop')&&sceneXml.includes('Native glass caption'),'Body STYLE and nested shifted backdrop retain editable foreground');
  const expected=await sharp(await scene.screenshot()).ensureAlpha().raw().toBuffer({resolveWithObject:true});
  let composed;
  for(const name of Object.keys(sceneZip.files).filter(n=>/^ppt\/media\/.*png$/.test(n))){const data=await sceneZip.file(name).async('nodebuffer'),meta=await sharp(data).metadata();if(meta.width===2560&&meta.height===1440)composed=await sharp(data).ensureAlpha().raw().toBuffer({resolveWithObject:true});}
  assert.ok(composed);
  for(const [x,y] of [[100,100],[600,220],[590,380],[775,230]]){
    const a=(y*1280+x)*4,b=((y-40)*2*2560+(x-50)*2)*4;
    for(let c=0;c<3;c++)assert.ok(Math.abs(expected.data[a+c]-composed.data[b+c])<=4,'Shifted backdrop, local SVG filter and partial glass pixels match live CSS');
  }
  console.log('PASS: browser CJK/Light, SVG text/art, native gradient and shadows, blur chroma/calc clip, body STYLE, shifted backdrop, local SVG filter and partial glass');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
