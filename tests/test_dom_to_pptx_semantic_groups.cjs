// NODE_PATH: bundled playwright/jszip. --project <id> reads page 15.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const JSZip=require('jszip');
async function main(){
  const repo=path.resolve(__dirname,'..'),arg=process.argv.indexOf('--project'),project=arg>=0?process.argv[arg+1]:null;
  const html=project?execFileSync(process.env.LANDPPT_TEST_PYTHON,['-X','utf8','-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=14',(sys.argv[1],)).fetchone()[0])",project],{cwd:repo,encoding:'utf8'}):
    `<style>*{box-sizing:border-box}body{margin:0}.suite-page{width:1280px;height:720px;position:relative;background:white;font:20px Arial}
    .feature-card{position:absolute;left:40px;top:60px;width:350px;height:400px;background:white;border:3px solid #FF6B9D;border-radius:28px;padding:28px 24px;transform:rotate(-1deg);display:flex;flex-direction:column;box-shadow:0 6px 0 #E85A87}
    .feature-card:nth-child(2){left:440px;transform:rotate(1deg);border-color:#4FC3F7}.feature-card:nth-child(3){left:840px;transform:rotate(-.5deg);border-color:#B388FF}
    .tag{position:absolute;right:20px;top:-10px;border-radius:999px;background:#FF6B9D;color:white;padding:4px 12px;font-size:11px;font-weight:bold}
    .title{margin-top:30px}.nested{margin-top:20px;padding:10px;background:#eee;border:2px solid gray;border-radius:8px}
    .simple{position:absolute;top:520px;left:40px;width:300px;height:80px;padding:10px 20px;border:4px solid #123456;background:#eee;border-radius:12px}
    </style><div class="suite-page">
    <div class="feature-card"><div class="tag" style="z-index:100">01</div><div class="title">Card one</div><div>Body one</div><div class="nested"><div>Nested title</div><div>Nested body</div></div></div>
    <div class="feature-card"><div class="tag">02</div><div class="title">Card two</div><div>Body two</div></div>
    <div class="feature-card"><div class="tag">03</div><div class="title">Card three</div><div>Body three</div></div>
    <div class="simple">Simple <b>bold</b> text</div></div>`;
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(html,{waitUntil:'load'});
    await page.addScriptTag({path:path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    const result=await page.evaluate(async()=>{
      const root=document.querySelector('.suite-page'),original=root.outerHTML;
      const encode=async blob=>{let s='';const b=new Uint8Array(await blob.arrayBuffer());for(let i=0;i<b.length;i+=32768)s+=String.fromCharCode(...b.subarray(i,i+32768));return btoa(s);};
      const grouped=await domToPptx.exportToPptx([root,root],{skipDownload:true,autoEmbedFonts:false,slideNotes:['first','second']});
      const flat=await domToPptx.exportToPptx(root,{skipDownload:true,autoEmbedFonts:false,semanticGrouping:false});
      return {grouped:await encode(grouped),flat:await encode(flat),unchanged:root.outerHTML===original,version:domToPptx.__landpptPatchVersion};
    });
    assert.ok(result.unchanged,'Grouping modified live HTML');
    const zip=await JSZip.loadAsync(Buffer.from(result.grouped,'base64'));
    const flatZip=await JSZip.loadAsync(Buffer.from(result.flat,'base64'));
    const flatXml=await flatZip.file('ppt/slides/slide1.xml').async('string');
    for(let slideNumber=1;slideNumber<=2;slideNumber++){
      const xml=await zip.file(`ppt/slides/slide${slideNumber}.xml`).async('string');
      const details=await page.evaluate(({xml,flatXml})=>{
        const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main';
        const parse=s=>new DOMParser().parseFromString(s,'application/xml'),all=(n,ns,t)=>Array.from(n.getElementsByTagNameNS(ns,t));
        const doc=parse(xml),flat=parse(flatXml),serialize=n=>new XMLSerializer().serializeToString(n);
        const shape=n=>{
          const pr=all(n,p,'spPr')[0],fill=Array.from(pr.children).find(c=>c.localName==='solidFill'),ln=all(pr,a,'ln')[0],body=all(n,a,'bodyPr')[0];
          return {text:all(n,a,'t').map(n=>n.textContent).join(''),fill:fill&&all(fill,a,'srgbClr')[0]?.getAttribute('val'),line:ln&&all(ln,a,'srgbClr')[0]?.getAttribute('val'),
            margins:body&&['lIns','rIns','tIns','bIns'].map(k=>Number(body.getAttribute(k))),bold:all(n,a,'rPr').some(n=>n.getAttribute('b')==='1')};
        };
        const groups=all(doc,p,'grpSp').map(n=>{
          const children=Array.from(n.children),nv=children[0],props=children[1],xf=all(props,a,'xfrm')[0];
          return {name:all(nv,p,'cNvPr')[0].getAttribute('name'),order:children.slice(0,2).map(n=>n.localName),
            topLevel:n.parentElement.localName==='spTree',nested:all(n,p,'grpSp').length,
            off:serialize(all(xf,a,'off')[0]).replace('off','pos'),chOff:serialize(all(xf,a,'chOff')[0]).replace('chOff','pos'),
            ext:serialize(all(xf,a,'ext')[0]).replace('ext','size'),chExt:serialize(all(xf,a,'chExt')[0]).replace('chExt','size'),
            shapes:all(n,p,'sp').map(shape)};
        });
        const geometry=d=>all(d,p,'sp').map(n=>{
          // Compare geometry and text content, ignoring object IDs/names/order.
          return [serialize(all(n,p,'spPr')[0]),all(n,a,'t').map(n=>n.textContent).join('')].join('|');
        }).sort();
        return {errors:doc.querySelectorAll('parsererror').length,ids:all(doc,p,'cNvPr').map(n=>n.getAttribute('id')),groups,
          sameGeometry:JSON.stringify(geometry(doc))===JSON.stringify(geometry(flat)),flatGroups:all(flat,p,'grpSp').length,
          simple:all(doc,p,'sp').map(shape).find(s=>s.text==='Simple bold text'),
          refs:all(doc,a,'blip').map(n=>n.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships','embed'))};
      },{xml,flatXml});
      assert.equal(details.errors,0);assert.equal(details.ids.length,new Set(details.ids).size,'Duplicate DrawingML IDs');
      assert.equal(details.flatGroups,0);assert.ok(details.sameGeometry,'Grouping changed object geometry');
      const cards=details.groups.filter(g=>g.topLevel);assert.equal(cards.length,3,'Each card must be a separate group');
      details.groups.forEach(g=>{assert.deepEqual(g.order,['nvGrpSpPr','grpSpPr']);assert.equal(g.off,g.chOff);assert.equal(g.ext,g.chExt);});
      cards.forEach((g,i)=>{
        const body=g.shapes.find(s=>s.fill==='FFFFFF'&&s.line),badge=g.shapes.find(s=>s.text===`0${i+1}`);
        assert.ok(body,'Missing combined card fill and border');assert.ok(badge?.fill,'Badge background and text were split');
        assert.ok(g.shapes.indexOf(body)<g.shapes.indexOf(badge),'Badge sits below parent border');
        assert.ok(badge.margins.every(n=>n>0),'Badge lost its text padding');
      });
      if(!project){
        assert.equal(details.groups.length,4,'Nested group missing');
        assert.ok(details.simple?.fill&&details.simple.line&&details.simple.bold,'Rich text container was not combined');
        // 20/10px CSS padding + half of 4px border, scaled 0.75 into PPT EMU.
        assert.deepEqual(details.simple.margins,[157163,157163,85725,85725]);
      }
      const rels=await zip.file(`ppt/slides/_rels/slide${slideNumber}.xml.rels`).async('string');
      details.refs.forEach(id=>assert.ok(rels.includes(`Id="${id}"`),'Broken media relationship'));
      assert.ok(zip.file(`ppt/notesSlides/notesSlide${slideNumber}.xml`),'Lost slide notes');
      console.log(JSON.stringify({slide:slideNumber,groups:details.groups.map(g=>({name:g.name,shapes:g.shapes.length,nested:g.nested})),sameGeometry:details.sameGeometry}));
    }
    console.log(`PASS ${result.version}: ${project||'fixture'} semantic grouping, layers, padding, IDs, relationships, two-slide export`);
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
