const fs=require('fs');
const JSZip=require('jszip');
(async()=>{
 const source=fs.readFileSync('tmp/inner-fixed.pptx');
 for(const variant of ['blend-over','blend-screen','blend-mult','reverse-screen','reverse-over']){
  const z=await JSZip.loadAsync(source);
  let xml=await z.file('ppt/slides/slide1.xml').async('string');
  xml=xml.replace(/<a:effectDag type="tree">([\s\S]*?<\/a:innerShdw>)([\s\S]*?<\/a:innerShdw>)<\/a:effectDag>/g,(_,one,two)=> {
    const reverse=variant.startsWith('reverse');
    const mode=variant.slice(variant.indexOf('-')+1);
    return `<a:effectDag type="tree">${reverse?two:one}<a:blend blend="${mode}"><a:cont type="tree">${reverse?one:two}</a:cont></a:blend></a:effectDag>`;
  });
  z.file('ppt/slides/slide1.xml',xml);
  fs.writeFileSync(`tmp/inner-${variant}.pptx`,await z.generateAsync({type:'nodebuffer'}));
 }
})();
