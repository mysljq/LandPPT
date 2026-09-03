// Optional --project reads page 24, checking native run effects and editable text.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');
async function main() {
  const repo=path.resolve(__dirname,'..'),arg=process.argv.indexOf('--project'),project=arg<0?null:process.argv[arg+1];
  const html=project?execFileSync(process.env.LANDPPT_TEST_PYTHON,['-X','utf8','-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=23',(sys.argv[1],)).fetchone()[0])",project],{cwd:repo,encoding:'utf8'}):
    `<style>body{margin:0;width:1280px;height:720px;font-family:Arial,'Microsoft YaHei';background:white}
    .title{position:absolute;top:40px;left:60px;font-size:80px;color:#3b82f6;text-shadow:4px 4px 0 #fbbf24}
    .latin{top:180px}.rich{position:absolute;left:60px;top:310px;font-size:30px;text-shadow:-4px 0 2px rgba(10,20,30,.4);opacity:.5;background:#eee}
    .clear{ text-shadow:none }.zero{position:absolute;left:60px;top:400px;font-size:30px;text-shadow:0 0 6px #008800}
    .rotated{position:absolute;left:400px;top:400px;font-size:30px;transform:rotate(12deg);text-shadow:3px -4px 0 #112233}
    .no-shadow{position:absolute;left:60px;top:510px;font-size:30px}
    </style><div class="title">感谢聆听</div><div class="title latin">THANK YOU</div>
    <div class="rich"><span>Inherited shadow</span><span class="clear">Cleared shadow</span></div>
    <div class="zero">Zero offset</div><div class="rotated">Rotated shadow</div><div class="no-shadow">Plain text</div>`;
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent(html,{waitUntil:'load'});
    const source=fs.readFileSync(path.join(repo,'src/landppt/web/static/js/dom-to-pptx.bundle.js'),'utf8');
    await page.addScriptTag({content:source.replace('exports.__landpptPatchVersion =','exports.__testTextShadow = getNativeTextShadow; exports.__landpptPatchVersion =')});
    const result=await page.evaluate(async()=>{
      const original=document.body.outerHTML;
      const blob=await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false});
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
      const parse=domToPptx.__testTextShadow;
      return {data:btoa(binary),unchanged:document.body.outerHTML===original,version:domToPptx.__landpptPatchVersion,
        scaled:parse({textShadow:'4px 4px 0px #FBBF24',color:'black'},2),
        multiple:parse({textShadow:'red 1px 2px, blue 3px 4px'}),invalid:parse({textShadow:'red 1px bogus'}),
        none:parse({textShadow:'none'}),current:parse({textShadow:'0px 0px',color:'rgb(1, 2, 3)'})};
    });
    assert.ok(result.unchanged);assert.equal(result.scaled.blur,0);assert.equal(result.scaled.offset,Math.hypot(4,4)*1.5);
    assert.equal(result.scaled.color,'FBBF24');assert.equal(result.multiple,null);assert.equal(result.invalid,null);assert.equal(result.none,null);assert.equal(result.current.color,'010203');
    const zip=await JSZip.loadAsync(Buffer.from(result.data,'base64'));
    const xml=await zip.file('ppt/slides/slide1.xml').async('string');
    const pres=await zip.file('ppt/presentation.xml').async('string');
    const runs=await page.evaluate(({xml,pres})=>{
      const doc=new DOMParser().parseFromString(xml,'application/xml');if(doc.querySelector('parsererror'))throw new Error('Malformed PPTX XML');
      const a='http://schemas.openxmlformats.org/drawingml/2006/main',all=(n,t)=>Array.from(n.getElementsByTagNameNS(a,t));
      const size=new DOMParser().parseFromString(pres,'application/xml').getElementsByTagNameNS('http://schemas.openxmlformats.org/presentationml/2006/main','sldSz')[0];
      const emuPerPixel=Number(size.getAttribute('cx'))/1280;
      return all(doc,'r').map(run=>{
        const pr=all(run,'rPr')[0],shadow=pr&&all(pr,'outerShdw')[0];
        return {text:all(run,'t').map(n=>n.textContent).join(''),effects:pr?all(pr,'effectLst').length:0,
          childOrder:pr?Array.from(pr.children).map(n=>n.localName):[],shadow:shadow&&{color:all(shadow,'srgbClr')[0]?.getAttribute('val'),
            blur:Number(shadow.getAttribute('blurRad'))/emuPerPixel,offset:Number(shadow.getAttribute('dist'))/emuPerPixel,
            angle:Number(shadow.getAttribute('dir'))/60000,alpha:Number(all(shadow,'alpha')[0]?.getAttribute('val'))/100000,
            rotate:shadow.getAttribute('rotWithShape')}};
      });
    },{xml,pres});
    const check=(text,expected)=>{
      const found=runs.filter(r=>r.text===text);assert.equal(found.length,1,`Text must remain editable exactly once: ${text}`);
      const run=found[0];assert.ok(run.shadow,`Missing glyph shadow: ${text}`);assert.equal(run.effects,1);
      for(const [key,value] of Object.entries(expected))typeof value==='number'?assert.ok(Math.abs(run.shadow[key]-value)<.0001,`${text} ${key}: ${run.shadow[key]} != ${value}`):assert.equal(run.shadow[key],value);
      assert.ok(run.childOrder.indexOf('effectLst')>run.childOrder.indexOf('solidFill'));
      for(const child of ['highlight','latin','ea','cs'])if(run.childOrder.includes(child))assert.ok(run.childOrder.indexOf('effectLst')<run.childOrder.indexOf(child),'Invalid DrawingML child order');
      return run;
    };
    check('感谢聆听',{color:'FBBF24',blur:0,offset:Math.hypot(4,4),angle:45,alpha:1,rotate:'1'});
    if(!project){
      check('THANK YOU',{color:'FBBF24',blur:0,angle:45});
      check('Inherited shadow',{color:'0A141E',blur:2,offset:4,angle:180,alpha:.2});
      check('Zero offset',{color:'008800',blur:6,offset:0,angle:0});
      check('Rotated shadow',{color:'112233',blur:0,offset:5,angle:306.8699,rotate:'1'});
      for(const text of ['Cleared shadow','Plain text']){const run=runs.find(r=>r.text===text);assert.ok(run);assert.ok(!run.shadow);}
    }
    console.log(JSON.stringify({version:result.version,project:project||'fixture',runs:runs.filter(r=>r.shadow)}));
    console.log('PASS native editable text shadows');
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
