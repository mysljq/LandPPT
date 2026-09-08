const fs=require('fs');
const path=require('path');
const {execFileSync}=require('child_process');
const {chromium}=require('playwright');
(async()=>{
 const html=execFileSync(process.execPath,['-e',`const s=require('node:sqlite');const d=new s.DatabaseSync('landppt.db');process.stdout.write(d.prepare("select html_content from slide_data where project_id=? and slide_index=39").get(process.argv[1]).html_content)`,'542faf1c-ba6e-4386-9be1-a79d4cf4cb80'],{encoding:'utf8'});
 const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const p=await b.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});await p.setContent(html,{waitUntil:'load'});await p.screenshot({path:'tmp/page40-html.png'});await b.close();
})();
