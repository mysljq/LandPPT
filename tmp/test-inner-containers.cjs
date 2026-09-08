const fs=require('fs');
const JSZip=require('jszip');
(async()=>{
 const source=fs.readFileSync('tmp/inner-fixed.pptx');
 for(const variant of ['root-sib','child-sib','children-tree']){
  const z=await JSZip.loadAsync(source);
  let xml=await z.file('ppt/slides/slide1.xml').async('string');
  xml=xml.replace(/<a:effectDag type="tree">([\s\S]*?<\/a:innerShdw>)([\s\S]*?<\/a:innerShdw>)<\/a:effectDag>/g,(_,one,two)=>{
   if(variant==='root-sib') return `<a:effectDag type="sib">${one}${two}</a:effectDag>`;
   if(variant==='child-sib') return `<a:effectDag type="tree"><a:cont type="sib">${one}${two}</a:cont></a:effectDag>`;
   return `<a:effectDag type="tree"><a:cont type="tree">${one}</a:cont><a:cont type="tree">${two}</a:cont></a:effectDag>`;
  });
  z.file('ppt/slides/slide1.xml',xml);
  fs.writeFileSync(`tmp/inner-${variant}.pptx`,await z.generateAsync({type:'nodebuffer'}));
 }
})();
