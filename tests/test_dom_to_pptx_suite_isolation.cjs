const assert = require('node:assert/strict');
const fs = require('fs');
const {chromium} = require('playwright');
const Zip = require('jszip');
(async () => {
 const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  await page.setContent('<iframe style="width:1280px;height:720px;border:0"></iframe>');
  let source=fs.readFileSync('src/landppt/web/static/js/dom-to-pptx.bundle.js','utf8');
  if(process.argv.includes('--before')) source=source.replace('__hideSuitePrompt: true','__hideSuitePrompt: false').replace(/    const fontDocument = root.ownerDocument;[\s\S]*?\.forEach\(cache => cache.delete\(fontDocument\)\);/,'');
  await page.addScriptTag({content:source});
  const real=process.argv.includes('--project');
  const output=real?'tmp/suite-live-isolation':'tmp/suite-isolation';
  const payload=real?{templates:Object.fromEntries(['cover','catalog','transition','content','ending'].map(t=>[t,fs.readFileSync(`tmp/suite-only/${t}.html`,'utf8')])),pages:Array.from({length:25},(_,i)=>fs.readFileSync(`tmp/suite-only/page-${i+1}.html`,'utf8'))}:null;
  const results=[];
  for(const withSuite of [false,true]){
   const data=await page.evaluate(async ({withSuite,payload})=>{
    const frame=document.querySelector('iframe');
    let firstDoc;
    const load=async html=>{const doc=frame.contentDocument;doc.open();doc.write(html);doc.close();await doc.fonts.ready;if(firstDoc&&firstDoc!==doc)throw new Error('Test must reuse the same Document');firstDoc=doc;return doc.body;};
    const base='<style>body{margin:0;width:1280px;height:720px;background:white;font:32px "SuiteOnlyFace",Arial}h1{position:absolute;left:100px;top:100px}</style>';
    const templates=(async function*(){for(const type of ['cover','catalog','transition','content','ending']){const root=await load(payload?payload.templates[type]:base+'<style>@font-face{font-family:SuiteOnlyFace;src:local("Arial")}</style><h1 data-pptx-slot="cover_title">SUITE SAMPLE '+type+'</h1>');yield {type,root};}})();
    const actual=(async function*(){for(let i=0;i<(payload?payload.pages.length:2);i++){const root=await load(payload?payload.pages[i]:base+'<h1>ACTUAL '+i+'</h1>');root.setAttribute('data-pptx-page-type',i?'ending':'cover');yield root;}})();
    const blob=await domToPptx.exportToPptx(actual,{useSlideLayouts:withSuite,suiteTemplates:withSuite?templates:null,skipDownload:true,autoEmbedFonts:false});
    const bytes=new Uint8Array(await blob.arrayBuffer());let str='';for(let i=0;i<bytes.length;i+=32768)str+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(str);
   },{withSuite,payload});
   const bytes=Buffer.from(data,'base64');fs.mkdirSync(output,{recursive:true});fs.writeFileSync(`${output}/page-${withSuite?2:1}.pptx`,bytes);
   const zip=await Zip.loadAsync(bytes);const xml=await zip.file('ppt/slides/slide1.xml').async('string');
   const parsed=await page.evaluate(xml=>{const doc=new DOMParser().parseFromString(xml,'application/xml');return Array.from(doc.getElementsByTagNameNS('*','sp')).map(sp=>({hidden:sp.getElementsByTagNameNS('*','cNvPr')[0].getAttribute('hidden'),ph:sp.getElementsByTagNameNS('*','ph').length,text:Array.from(sp.getElementsByTagNameNS('*','t')).map(n=>n.textContent).join(''),body:sp.getElementsByTagNameNS('*','txBody')[0]?.outerHTML}));},xml);
   assert.ok(!parsed.some(sp=>sp.text.includes('SUITE SAMPLE')),'No suite sample text on actual pages');
   if(withSuite){const overrides=parsed.filter(sp=>sp.ph);assert.ok(overrides.length>0);assert.ok(overrides.every(sp=>sp.hidden==='1'&&!sp.text),'Empty prompt overrides are hidden in the editing view');}
   const allBodies=[];for(const file of Object.keys(zip.files).filter(f=>/^ppt\/slides\/slide\d+.xml$/.test(f)).sort()){const xml=await zip.file(file).async('string');allBodies.push(await page.evaluate(xml=>{const doc=new DOMParser().parseFromString(xml,'application/xml');return Array.from(doc.getElementsByTagNameNS('*','sp')).filter(sp=>!sp.getElementsByTagNameNS('*','ph').length).filter(sp=>sp.getElementsByTagNameNS('*','txBody').length).map(sp=>sp.getElementsByTagNameNS('*','spPr')[0]?.outerHTML+sp.getElementsByTagNameNS('*','txBody')[0]?.outerHTML);},xml));}results.push(allBodies);
  }
  assert.deepEqual(results[1],results[0],'Actual text geometry/run styles and resolved font stay identical after suite rendering in the same Document');
  console.log('PASS: reused iframe font isolation, identical actual text styles, hidden suite prompts, no leaked sample text');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
