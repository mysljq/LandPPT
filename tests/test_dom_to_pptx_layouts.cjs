const fs = require('fs'), path = require('path'), assert = require('node:assert/strict');
const { chromium } = require('playwright');
const Zip = require('jszip');
const types = ['cover','catalog','transition','content','ending'];
const fixture = (label, accent='#2ec4b6') => `<style>body{margin:0;width:1280px;height:720px;background:#f5efe0;font:24px Arial}.accent{position:absolute;left:20px;top:20px;width:200px;height:200px;background:${accent};border-radius:50%}h1{position:absolute;left:300px;top:100px;font-family:Georgia;font-size:48px;color:#9b1234;font-weight:bold;font-style:italic}</style><div class="accent"></div><div style="position:absolute;left:50px;top:650px">FIXED BRAND</div><h1 ${label.startsWith('Suite')?'data-pptx-slot="cover_title"':''}>${label}</h1>`;
(async () => {
 const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try {
  const host = await browser.newPage({viewport:{width:1280,height:720}});
  await host.setContent('<body></body>');
  await host.addScriptTag({path:'src/landppt/web/static/js/dom-to-pptx.bundle.js'});
  const real = process.argv.includes('--project');
  const dir = real ? 'tmp/suite-only' : 'tmp/suite-layout-regression';
  fs.mkdirSync(dir,{recursive:true});
  const outlines = real ? JSON.parse(fs.readFileSync(dir+'/metadata.json','utf8')).outline.slides : [];
  const count = real ? 25 : 12;
  const pageType = i => i===0?'cover':i===count-1?'ending':real?({agenda:'catalog',outline:'catalog'}[outlines[i]?.type||outlines[i]?.slide_type]||outlines[i]?.type||outlines[i]?.slide_type||'content'):types[i%5];
  for (const enabled of [false,true]) {
   await host.evaluate(() => { window.suiteRoots=[]; window.actualRoots=[]; });
   // Separate iframes keep template and page CSS isolated.
   for (const type of (enabled ? types : [])) {
    const html = real ? fs.readFileSync(`${dir}/${type}.html`,'utf8') : fixture('Suite '+type);
    await host.evaluate(async ({html,type}) => {const frame=document.createElement('iframe');frame.style.cssText='width:1280px;height:720px;border:0';document.body.append(frame);frame.contentDocument.open();frame.contentDocument.write(html);frame.contentDocument.close();await frame.contentDocument.fonts.ready;window.suiteRoots.push({type,root:frame.contentDocument.body});},{html,type});
   }
   for(let i=0;i<count;i++) {
    const html=real?fs.readFileSync(`${dir}/page-${i+1}.html`,'utf8'):fixture('Actual page '+i,i===6?'#ffd700':'#2ec4b6');
    await host.evaluate(async ({html,type})=>{const f=document.createElement('iframe');f.style.cssText='width:1280px;height:720px;border:0';document.body.append(f);f.contentDocument.open();f.contentDocument.write(html);f.contentDocument.close();await f.contentDocument.fonts.ready;f.contentDocument.body.setAttribute('data-pptx-page-type',type);window.actualRoots.push(f.contentDocument.body);},{html,type:pageType(i)});
   }
   const encoded=await host.evaluate(async enabled=>{const blob=await domToPptx.exportToPptx(window.actualRoots,{useSlideLayouts:enabled,suiteTemplates:enabled?window.suiteRoots:null,skipDownload:true,autoEmbedFonts:false});const bytes=new Uint8Array(await blob.arrayBuffer());let s='';for(let i=0;i<bytes.length;i+=32768)s+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(s)},enabled);
   fs.writeFileSync(`${dir}/page-${enabled?2:1}.pptx`,Buffer.from(encoded,'base64'));
   await host.evaluate(()=>document.querySelectorAll('iframe').forEach(f=>f.remove()));
  }
  const zip=await Zip.loadAsync(fs.readFileSync(dir+'/page-2.pptx'));
  const layouts=Object.keys(zip.files).filter(name=>/^ppt\/slideLayouts\/slideLayout\d+.xml$/.test(name));
  assert.equal(layouts.length,5,'Only the five suite templates become layouts');
  const labels=['封面','目录页','章节过渡页','内容页','结束页'];
  for(let i=0;i<5;i++){const xml=await zip.file(layouts[i]).async('string');assert.ok(xml.includes('套件·'+labels[i]));assert.ok(!xml.includes('Actual page'),'Actual pages never populate layouts');assert.ok(xml.includes('<p:ph'),'Suite slots become editable placeholders');const errors=await host.evaluate(xml=>{const d=new DOMParser().parseFromString(xml,'application/xml'),errors=[];for(const sp of d.getElementsByTagNameNS('*','sp')){if(!sp.getElementsByTagNameNS('*','ph').length)continue;const r=sp.getElementsByTagNameNS('*','rPr')[0],def=sp.getElementsByTagNameNS('*','defRPr')[0];if(!r||!def){errors.push('missing run defaults');continue;}for(const key of ['sz','b','i','spc'])if(r.hasAttribute(key)&&r.getAttribute(key)!==def.getAttribute(key))errors.push('default '+key);if(r.getElementsByTagNameNS('*','gradFill').length&&!def.getElementsByTagNameNS('*','gradFill').length)errors.push('missing default gradient');}return errors;},xml);assert.deepEqual(errors,[],'New slide slot styles inherit prompt formatting');if(!real){assert.ok(xml.includes('FIXED BRAND'));assert.ok(/<a:defRPr[^>]*sz="2700"/.test(xml),'Slot default preserves browser font size');assert.ok(xml.includes('9B1234'),'Slot default preserves browser color');}}
  for(let i=0;i<count;i++){const rel=await zip.file(`ppt/slides/_rels/slide${i+1}.xml.rels`).async('string');const typeIndex=types.indexOf(pageType(i));assert.ok(rel.includes(`slideLayout${typeIndex+1}.xml`),`Page ${i+1} references suite ${pageType(i)}`);}
  if (!real) {assert.ok(!(await zip.file('ppt/slides/slide1.xml').async('string')).includes('showMasterSp="0"'),'Matching suite paint is inherited');assert.ok((await zip.file('ppt/slides/slide7.xml').async('string')).includes('showMasterSp="0"'),'Edited artwork uses safe page rendering');}
  console.log(`PASS: ${count} actual pages reference exactly five suite-only layouts (${dir})`);
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
