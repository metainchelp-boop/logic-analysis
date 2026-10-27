const fs=require('fs'), vm=require('vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('frontend/js/utils.js','utf8');
const context={window:{}}; vm.createContext(context);vm.runInContext(source.slice(source.indexOf('window.ReportFacts =')),context);
const f=context.window.ReportFacts;
f.begin('same-keyword','product-A');const a=f.ticket('same-keyword','product-A');f.put(a,'seo',{score:11});
assert.equal(f.get('same-keyword','product-A').seo.score,11);
f.begin('same-keyword','product-B');const b=f.ticket('same-keyword','product-B');
assert.equal(Object.keys(f.get('same-keyword','product-B')).length,0);
f.put(a,'seo',{score:99});assert.equal(Object.keys(f.get('same-keyword','product-B')).length,0);
assert.equal(f.ticket('same-keyword','product-A'),null);
f.put(b,'seo',{score:22});assert.equal(f.get('same-keyword','product-B').seo.score,22);
f.begin('same-keyword','product-B');f.put(b,'ai',{text:'old'});assert.equal(Object.keys(f.get('same-keyword','product-B')).length,0);
f.reset();assert.equal(f.ticket('same-keyword','product-B'),null);
// Exercise the actual SEO component handler with a tiny React hook harness.
const seo=fs.readFileSync('frontend/js/components/SeoDiagnosisSection.jsx','utf8');
const states=['product-A',null,false], calls=[];let cursor=0;
Object.assign(context,{React:{useState:()=>{const i=cursor++;return [states[i],v=>{states[i]=v;}];},useEffect:()=>{},useRef:v=>({current:v}),createElement:(type,props,...children)=>({type,props:props||{},children})},toast:{warn:()=>{}},api:{post:async(path,body)=>{calls.push(body);return {success:true,data:{score:body.product_url==='product-A'?11:99}};}}});
vm.runInContext(seo.slice(0,seo.indexOf('    return ('))+'return {handleAnalyze};};',context);
function render(){cursor=0;return context.window.SeoDiagnosisSection({keyword:'same-keyword',productUrl:'product-A'});}
function nodes(n){return n&&typeof n==='object'?[n,...n.children.flat(Infinity).flatMap(nodes)]:[];}
(async()=>{
 f.begin('same-keyword','product-A');
 let view=render();
 await view.handleAnalyze();assert.equal(f.get('same-keyword','product-A').seo.score,11);
 states[0]='product-B';states[1]=null;view=render();
 await view.handleAnalyze();assert.equal(calls.at(-1).product_url,'product-B');assert.equal(f.get('same-keyword','product-A').seo.score,11);
 console.log('proposal facts scope: 10 passed (actual SEO URL edit included)');
})().catch(e=>{console.error(e);process.exit(1);});
