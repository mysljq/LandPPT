// Optional --project reads page 23 from the local database without modifying it.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');
const sharp = require('sharp');
async function main() {
  const repo = path.resolve(__dirname, '..');
  const arg = process.argv.indexOf('--project'), project = arg < 0 ? null : process.argv[arg + 1];
  const html = project ? execFileSync(process.env.LANDPPT_TEST_PYTHON, ['-X', 'utf8', '-c',
    "import sqlite3,sys; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=22',(sys.argv[1],)).fetchone()[0])", project], { cwd: repo, encoding: 'utf8' }) :
    `<style>*{box-sizing:border-box}html,body{margin:0;width:1280px;height:720px;overflow:hidden;background:#f9f9f9}
    .trans-bg-left,.trans-bg-deco{position:absolute;left:0;top:0;width:45%;height:100%;clip-path:polygon(0 0,100% 0,85% 100%,0% 100%)}
    .trans-bg-left{background:#db0005}.trans-bg-deco{background:linear-gradient(135deg,rgba(255,193,7,.1),rgba(192,0,0,0))}
    .label{position:absolute;left:80px;top:50%;transform:translateY(-50%);font-size:220px;white-space:nowrap;color:#ffffff26}
    </style><div class="trans-bg-left"></div><div class="trans-bg-deco"></div><div class="label">Very long watermark exceeding slide width</div>`;
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.setContent(html, { waitUntil: 'load' });
    const source=fs.readFileSync(path.join(repo, 'src/landppt/web/static/js/dom-to-pptx.bundle.js'),'utf8');
    await page.addScriptTag({ content: source.replace('exports.__landpptPatchVersion =',
      'exports.__testPolygon = getNativeClipPolygonPoints; exports.__testRisk = analyzeRiskSubtree; exports.__landpptPatchVersion =') });
    const guards=await page.evaluate(()=>{
      const parse=domToPptx.__testPolygon;
      const host=document.createElement('div');host.style.cssText='position:absolute;width:100px;height:100px;overflow:hidden';
      const child=document.createElement('div');child.style.cssText='width:200px;height:30px;transform:translateY(1px)';child.textContent='Translated text';host.append(child);document.body.append(host);
      const plain=domToPptx.__testRisk(host).risky;
      child.style.background='red';const painted=domToPptx.__testRisk(host).risky;
      child.style.background='transparent';child.style.transform='rotate(12deg)';const rotated=domToPptx.__testRisk(host).risky;host.remove();
      return {plain,painted,rotated,triangle:parse('polygon(nonzero, 0 0, 100px 0, 50% 100%)',100,80,1),
        invalid:['polygon(evenodd,0 0,100% 0,0 100%)','polygon(0 0,calc(100% - 2px) 0,0 100%)','polygon(0 0,110% 0,0 100%)'].map(v=>parse(v,100,80,1))};
    });
    assert.equal(guards.plain,false);assert.equal(guards.painted,true);assert.equal(guards.rotated,true);
    assert.deepEqual(guards.triangle,[{x:0,y:0},{x:100,y:0},{x:50,y:80},{close:true}]);
    assert.ok(guards.invalid.every(v=>v===null));
    const result = await page.evaluate(async () => {
      const root = document.body, original = root.outerHTML;
      const blob = await domToPptx.exportToPptx(root, { skipDownload: true, autoEmbedFonts: false });
      const bytes = new Uint8Array(await blob.arrayBuffer()); let binary = '';
      for (let i=0;i<bytes.length;i+=32768) binary += String.fromCharCode(...bytes.subarray(i,i+32768));
      return { data: btoa(binary), unchanged: root.outerHTML === original, debug: window.__LANDPPT_PPTX_RISK_FALLBACK_DEBUG__, version: domToPptx.__landpptPatchVersion };
    });
    assert.ok(result.unchanged);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const xml = await zip.file('ppt/slides/slide1.xml').async('string');
    const pres = await zip.file('ppt/presentation.xml').async('string');
    const parsed = await page.evaluate(({xml,pres}) => {
      const p='http://schemas.openxmlformats.org/presentationml/2006/main',a='http://schemas.openxmlformats.org/drawingml/2006/main';
      const parse=s=>new DOMParser().parseFromString(s,'application/xml'),all=(n,ns,t)=>Array.from(n.getElementsByTagNameNS(ns,t));
      const doc=parse(xml); if(doc.querySelector('parsererror'))throw new Error('Invalid XML');
      const factor=Number(all(parse(pres),p,'sldSz')[0].getAttribute('cx'))/1280;
      return {pictures:all(doc,p,'pic').length,shapes:all(doc,p,'sp').map(n=>{
        const pr=all(n,p,'spPr')[0],off=all(pr,a,'off')[0],ext=all(pr,a,'ext')[0],geom=all(pr,a,'custGeom')[0];
        return {x:Number(off?.getAttribute('x'))/factor,y:Number(off?.getAttribute('y'))/factor,w:Number(ext?.getAttribute('cx'))/factor,h:Number(ext?.getAttribute('cy'))/factor,
          custom:!!geom,points:geom?all(geom,a,'pt').map(pt=>[Number(pt.getAttribute('x'))/factor,Number(pt.getAttribute('y'))/factor]):[],
          fill:all(pr,a,'solidFill')[0]?.textContent,colors:all(pr,a,'srgbClr').map(c=>c.getAttribute('val')),stops:all(pr,a,'gs').length};})};
    },{xml,pres});
    console.log(JSON.stringify({version:result.version,debug:result.debug,parsed}));
    const panels=parsed.shapes.filter(s=>Math.abs(s.x)<.05&&Math.abs(s.y)<.05&&Math.abs(s.w-576)<.05&&Math.abs(s.h-720)<.05);
    assert.equal(panels.length,2,'Both background layers must be separate native polygons');
    for(const panel of panels){
      assert.ok(panel.custom,'Polygon must not become a rectangle');
      const expected=[[0,0],[576,0],[489.6,720],[0,720]];
      assert.equal(panel.points.length,expected.length);
      panel.points.forEach((pt,i)=>pt.forEach((v,j)=>assert.ok(Math.abs(v-expected[i][j])<.05)));
    }
    assert.ok(panels.some(s=>s.colors.includes('DB0005')&&s.stops===0));
    assert.ok(panels.some(s=>s.stops>=2),'Transparent gradient overlay must retain native gradient');
    assert.ok(!result.debug.some(item=>item.tagName==='BODY'),'Translated watermark must not rasterize the slide');
    const native=await page.evaluate(panel=>{
      const canvas=document.createElement('canvas');canvas.width=576;canvas.height=720;
      const ctx=canvas.getContext('2d');ctx.fillStyle='#f9f9f9';ctx.fillRect(0,0,576,720);ctx.fillStyle='#db0005';
      ctx.beginPath();panel.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.fill();
      // Isolate only the source polygon for a pixel comparison, after verifying
      // that export itself did not mutate any source markup.
      for(const node of document.body.children)if(!node.matches('.trans-bg-left,style,script'))node.style.visibility='hidden';
      return canvas.toDataURL('image/png').split(',')[1];
    },panels[0]);
    const cssPixels=await sharp(await page.locator('.trans-bg-left').screenshot()).removeAlpha().raw().toBuffer();
    const pptPixels=await sharp(Buffer.from(native,'base64')).removeAlpha().raw().toBuffer();
    assert.equal(cssPixels.length,pptPixels.length);
    let difference=0;for(let i=0;i<cssPixels.length;i++)difference+=Math.abs(cssPixels[i]-pptPixels[i]);
    assert.ok(difference/cssPixels.length<.2,'Native polygon silhouette differs from CSS');
    console.log({meanPixelDifference:difference/cssPixels.length});
    console.log(`PASS ${project||'fixture'}: polygon background and gradient overlay`);
  } finally { await browser.close(); }
}
main().catch(e=>{console.error(e);process.exitCode=1;});
