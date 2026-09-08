const fs=require('fs');
const JSZip=require('jszip');
(async()=>{for(const which of ['dark','light']){
 const z=await JSZip.loadAsync(fs.readFileSync('tmp/inner-fixed.pptx'));
 let xml=await z.file('ppt/slides/slide1.xml').async('string');
 xml=xml.replace(/<a:effectDag[\s\S]*?<\/a:effectDag>/g,s=>s.replace(/<a:innerShdw[\s\S]*?<\/a:innerShdw>/g,e=>e.includes(which==='dark'?'AEA394':'FFFDF7')?e:''));
 z.file('ppt/slides/slide1.xml',xml);
 fs.writeFileSync(`tmp/inner-${which}.pptx`,await z.generateAsync({type:'nodebuffer'}));
}})();
