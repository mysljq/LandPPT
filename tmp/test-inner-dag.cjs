const fs=require('fs');
const JSZip=require('jszip');
(async()=>{
 const z=await JSZip.loadAsync(fs.readFileSync('tmp/inner-check.pptx'));
 let xml=await z.file('ppt/slides/slide1.xml').async('string');
 const effects=new Map();
 for(const s of xml.match(/<p:sp>[\s\S]*?<\/p:sp>/g)||[]){
  const m=s.match(/name="CSS inset shadow layer (\S+) (\d+)"/);
  if(m){const a=effects.get(m[1])||[];a.push(s.match(/<a:innerShdw[\s\S]*?<\/a:innerShdw>/)[0]);effects.set(m[1],a);}
 }
 xml=xml.replace(/<p:sp>[\s\S]*?<\/p:sp>/g,s=>{
  const m=s.match(/name="CSS inset shadow layer (\S+) (\d+)"/);
  if(!m)return s;
  if(m[2]!=='0')return '';
  return s.replace(/<a:alpha val="1000"\/>/,'<a:alpha val="100000"/>').replace(/<a:effectLst>[\s\S]*?<\/a:effectLst>/,`<a:effectDag type="tree">${effects.get(m[1]).reverse().join('')}</a:effectDag>`);
 });
 z.file('ppt/slides/slide1.xml',xml);
 fs.writeFileSync('tmp/inner-dag.pptx',await z.generateAsync({type:'nodebuffer'}));
})();
