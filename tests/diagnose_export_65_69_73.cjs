const fs=require('node:fs'),path=require('node:path'),{DatabaseSync}=require('node:sqlite'),{chromium}=require('playwright'),JSZip=require('jszip');
(async()=>{const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
  const db=new DatabaseSync('landppt.db');
  for(const [n,selector] of [[65,'.tr-num,.tr-num-bg'],[69,'.sunburst'],[73,'.f-right .lbl']]){
    const p=await b.newPage({viewport:{width:1280,height:720}});
    await p.setContent(db.prepare('select html_content from slide_data where project_id=? and slide_index=?').get('542faf1c-ba6e-4386-9be1-a79d4cf4cb80',n-1).html_content);
    await p.evaluate(()=>document.fonts.ready);
    const cdp=await p.context().newCDPSession(p);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
    const root=await cdp.send('DOM.getDocument');const nodes=await cdp.send('DOM.querySelectorAll',{nodeId:root.root.nodeId,selector});
    for(const nodeId of nodes.nodeIds)console.log(n,await cdp.send('CSS.getPlatformFontsForNode',{nodeId}));
    console.log(n,await p.locator(selector).evaluateAll(ns=>ns.map(n=>({cls:n.className,text:n.textContent,rect:n.getBoundingClientRect().toJSON(),font:getComputedStyle(n).font,spacing:getComputedStyle(n).letterSpacing,display:getComputedStyle(n).display}))));
    fs.mkdirSync(`tmp/page${n}`,{recursive:true});await p.screenshot({path:`tmp/page${n}/browser.png`});
    await p.addScriptTag({path:path.resolve('src/landppt/web/static/js/dom-to-pptx.bundle.js')});
    console.log('resolved',n,await p.locator(selector).evaluateAll(ns=>ns.map(n=>domToPptx.__landpptResolveFontFace(getComputedStyle(n).fontFamily,n))));
    const bytes=await p.evaluate(async()=>Array.from(new Uint8Array(await(await domToPptx.exportToPptx(document.body,{skipDownload:true,autoEmbedFonts:false})).arrayBuffer())));
    fs.writeFileSync(`tmp/page${n}/page${n}.pptx`,Buffer.from(bytes));const z=await JSZip.loadAsync(Buffer.from(bytes));fs.writeFileSync(`tmp/page${n}/slide.xml`,await z.file('ppt/slides/slide1.xml').async('string'));await p.close();
  }
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
