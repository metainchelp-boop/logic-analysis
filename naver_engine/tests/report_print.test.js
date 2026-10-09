'use strict';
// Synthetic DOM/platform boundaries only; no browser dialog, files, API, or network.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../backend/naver_page/report-pdf.js'), 'utf8');

function report() {
  return {report_id:17, revision_no:3, revision_fingerprint:'a'.repeat(64), generated_at:'2026-10-04T10:00:00+09:00',
    company_name:'합성 인쇄 검증 업체', scope:{kind:'account', account_key:'account-a'},
    payload:{format_version:2, status:'partial', period:{kind:'weekly',start:'2026-09-28',end:'2026-10-04'}},
    annotations:{version:1,state:'approved'}};
}
function platform() {
  const listeners = new Map(), timers = new Map(), mediaListeners = new Set(); let nextTimer = 0, prints = 0;
  const document = {fonts:{ready:Promise.resolve()}};
  class Element {
    constructor(tag) { this.nodeType=1; this.tagName=tag.toUpperCase(); this.ownerDocument=document; this.parentNode=null; this.children=[]; this.values=new Map(); }
    get attributes() { return Array.from(this.values,([name,value])=>({name,value})); }
    setAttribute(name,value) { this.values.set(name,String(value)); }
    getAttribute(name) { return this.values.get(name) ?? null; }
    get classList() { const node=this; return {contains:name=>(node.getAttribute('class')||'').split(/\s+/).includes(name),
      add(name){node.setAttribute('class',Array.from(new Set((node.getAttribute('class')||'').split(/\s+/).filter(Boolean).concat(name))).join(' '));},
      remove(name){node.setAttribute('class',(node.getAttribute('class')||'').split(/\s+/).filter(value=>value!==name).join(' '));}}; }
    get isConnected() { let node=this; while(node) {if(node===document.body)return true;node=node.parentNode;} return false; }
    appendChild(node) { node.remove(); this.children.push(node);node.parentNode=this;return node; }
    remove() {if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(node=>node!==this);this.parentNode=null;}
    querySelectorAll(selector) { assert.equal(selector,'*');return this.children.flatMap(node=>[node,...node.querySelectorAll('*')]); }
  }
  document.createElement=tag=>new Element(tag); document.body=new Element('body');
  document.querySelectorAll=selector=>{assert.equal(selector,'#naver-report-print-root');return document.body.querySelectorAll('*').filter(node=>node.getAttribute('id')==='naver-report-print-root');};
  const media={matches:false,addEventListener(name,handler){assert.equal(name,'change');mediaListeners.add(handler);},removeEventListener(name,handler){mediaListeners.delete(handler);}};
  const root={document,structuredClone,matchMedia:()=>media,print(){prints++;},addEventListener(name,handler){if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(handler);},
    removeEventListener(name,handler){listeners.get(name)?.delete(handler);}};
  const context={window:root,setTimeout(fn,ms){const id=++nextTimer;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},structuredClone,console};
  vm.runInNewContext(source,context);
  function paper(data=report(),layout='a') {
    const node=document.createElement('article'); node.setAttribute('class','nr-report-paper');
    for(const [key,value] of Object.entries({'data-layout':layout,'data-report-id':data.report_id,'data-revision-fingerprint':data.revision_fingerprint,'data-account-key':data.scope.account_key}))node.setAttribute(key,value);
    node.appendChild(document.createElement('h2')); return node;
  }
  return {root,document,paper,api:root.NaverReportPDF,get prints(){return prints;},timers,
    event(name){for(const fn of Array.from(listeners.get(name)||[]))fn();},
    mediaEvent(matches){media.matches=matches;for(const fn of Array.from(mediaListeners))fn({matches});},
    expire(ms){for(const [id,item] of Array.from(timers))if(item.ms===ms){timers.delete(id);item.fn();}}};
}

test('native print starts only the supplied public paper and retains it until afterprint',async()=>{
  const env=platform(), input=report(), original=JSON.stringify(input), paper=env.paper(input,'c');
  const result=await env.api.print(input,{layout:'c',paper,isCurrent:()=>true});
  assert.equal(result.started,true); assert.deepEqual(Object.keys(result),['started']);
  assert.equal(env.prints,1); assert.equal(JSON.stringify(input),original);
  assert.equal(env.document.body.classList.contains('nr-printing'),true);
  const roots=env.document.querySelectorAll('#naver-report-print-root');
  assert.equal(roots.length,1);assert.equal(roots[0].children[0],paper);
  assert.equal(roots[0].getAttribute('data-layout'),'c');
  env.event('afterprint');
  assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
  assert.equal(env.document.body.classList.contains('nr-printing'),false);
});

test('private controls, annotation history and active content cannot enter a printed paper',async()=>{
  for (const [tag,attrs] of [['textarea',{}],['button',{}],['input',{}],['form',{}],['iframe',{}],['script',{}],
    ['div',{class:'nr-annotations'}],['details',{class:'nr-note-history'}],['div',{'data-private':'true'}],
    ['div',{contenteditable:'false'}],['svg',{onload:'bad()'}],['a',{href:'https://example.invalid'}],
    ['div',{style:'background-image:url(https://example.invalid/secret)'}]]) {
    const env=platform(),paper=env.paper(),node=env.document.createElement(tag);
    for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);
    paper.appendChild(node);
    await assert.rejects(()=>env.api.print(report(),{layout:'a',paper,isCurrent:()=>true}),/REPORT_PRINT_PRIVATE/);
    assert.equal(env.prints,0);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
    assert.equal(paper.isConnected,false);
  }
});

test('layout, immutable report metadata and detached-paper identity are closed before print',async()=>{
  for(const layout of [undefined,null,'A','d',{},1]) {
    const env=platform();
    await assert.rejects(()=>env.api.print(report(),{layout,paper:env.paper(),isCurrent:()=>true}),/REPORT_PRINT_LAYOUT/);
    assert.equal(env.prints,0);
  }
  for(const field of ['data-layout','data-report-id','data-revision-fingerprint','data-account-key']) {
    const env=platform(),paper=env.paper(); paper.setAttribute(field,'wrong');
    await assert.rejects(()=>env.api.print(report(),{layout:'a',paper,isCurrent:()=>true}),/REPORT_PRINT_PAPER/);
    assert.equal(env.prints,0);
  }
  for(const mutate of [data=>{data.revision_fingerprint='invalid';},data=>{data.scope.account_key='';},data=>{data.payload.format_version=1;}]) {
    const env=platform(),data=report();mutate(data);
    await assert.rejects(()=>env.api.print(data,{layout:'a',paper:env.paper(data),isCurrent:()=>true}),/REPORT_PDF_DATA/);
  }
  const env=platform(),paper=env.paper();env.document.body.appendChild(paper);
  await assert.rejects(()=>env.api.print(report(),{layout:'a',paper,isCurrent:()=>true}),/REPORT_PRINT_PAPER/);
  assert.equal(env.prints,0);assert.equal(paper.parentNode,env.document.body);
});

test('fonts settle before print and stale authority during the wait cleans the paper without printing',async()=>{
  const env=platform();let release,allowed=true;
  env.document.fonts.ready=new Promise(resolve=>{release=resolve;});
  const pending=env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>allowed});
  assert.equal(env.prints,0);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,1);
  allowed=false;release();
  await assert.rejects(()=>pending,/REPORT_PDF_STALE/);
  assert.equal(env.prints,0);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
  assert.equal(env.document.body.classList.contains('nr-printing'),false);assert.equal(env.timers.size,0);
});

test('the frozen report identity is checked again after fonts settle',async()=>{
  const env=platform(),data=report(),paper=env.paper(data);let release;
  env.document.fonts.ready=new Promise(resolve=>{release=resolve;});
  const pending=env.api.print(data,{layout:'a',paper,isCurrent:()=>true});
  data.revision_fingerprint='b'.repeat(64);paper.setAttribute('data-revision-fingerprint',data.revision_fingerprint);release();
  await assert.rejects(()=>pending,/REPORT_PRINT_PAPER/);
  assert.equal(env.prints,0);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
});

test('native print-media exit cleans up even when afterprint is not delivered',async()=>{
  const env=platform();
  await env.api.print(report(),{layout:'b',paper:env.paper(report(),'b'),isCurrent:()=>true});
  env.mediaEvent(false);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,1);
  env.mediaEvent(true);env.mediaEvent(false);
  assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
  assert.equal(env.document.body.classList.contains('nr-printing'),false);
  await env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true});
  assert.equal(env.prints,2);env.event('afterprint');
});

test('unsettled or rejected fonts fail within the bound and release the print lock',async()=>{
  for(const kind of ['timeout','reject']) {
    const env=platform();
    env.document.fonts.ready=kind==='timeout'?new Promise(()=>{}):Promise.reject(new Error('font failed'));
    const pending=env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true});
    if(kind==='timeout')env.expire(5000);
    await assert.rejects(()=>pending,/REPORT_PRINT_FONTS/);
    assert.equal(env.prints,0);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
    assert.equal(env.document.body.classList.contains('nr-printing'),false);assert.equal(env.timers.size,0);
    env.document.fonts.ready=Promise.resolve();
    await env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true});env.event('afterprint');
  }
});

test('concurrent attempts are blocked during fonts and the native dialog; reset cancels waiting work',async()=>{
  const env=platform();let release;
  env.document.fonts.ready=new Promise(resolve=>{release=resolve;});
  const pending=env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true});
  await assert.rejects(()=>env.api.print(report(),{layout:'b',paper:env.paper(report(),'b'),isCurrent:()=>true}),/REPORT_PRINT_BUSY/);
  env.api.cancelPrint();await assert.rejects(()=>pending,/REPORT_PDF_STALE/);release();
  assert.equal(env.prints,0);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
  env.document.fonts.ready=Promise.resolve();
  await env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true});
  await assert.rejects(()=>env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true}),/REPORT_PRINT_BUSY/);
  assert.equal(env.prints,1);assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,1);
  env.api.cancelPrint();env.api.cancelPrint();
  assert.equal(env.document.body.classList.contains('nr-printing'),false);
});

test('native print failure, missing print and pagehide clean safely without claiming a save',async()=>{
  const env=platform(),native=env.root.print;
  env.root.print=undefined;
  await assert.rejects(()=>env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true}),/REPORT_PRINT_UNAVAILABLE/);
  env.root.print=()=>{throw new Error('native unavailable');};
  await assert.rejects(()=>env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true}),/native unavailable/);
  assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
  env.root.print=native;
  await env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent:()=>true});env.event('pagehide');
  assert.equal(env.document.querySelectorAll('#naver-report-print-root').length,0);
  assert.equal(env.document.body.classList.contains('nr-printing'),false);
});

test('stale authority at entry and private mutation during fonts never start print',async()=>{
  const env=platform();
  for(const isCurrent of [undefined,()=>false,()=>{throw new Error('stale');}])
    await assert.rejects(()=>env.api.print(report(),{layout:'a',paper:env.paper(),isCurrent}),/REPORT_PDF_STALE/);
  let release;env.document.fonts.ready=new Promise(resolve=>{release=resolve;});const paper=env.paper();
  const pending=env.api.print(report(),{layout:'a',paper,isCurrent:()=>true});paper.appendChild(env.document.createElement('textarea'));release();
  await assert.rejects(()=>pending,/REPORT_PRINT_PRIVATE/);assert.equal(env.prints,0);
});

test('leftover duplicate print roots are replaced with only the validated public paper',async()=>{
  const env=platform();
  for(let i=0;i<2;i++){const old=env.document.createElement('div');old.setAttribute('id','naver-report-print-root');old.appendChild(env.document.createElement('textarea'));env.document.body.appendChild(old);}
  const paper=env.paper();await env.api.print(report(),{layout:'a',paper,isCurrent:()=>true});
  const roots=env.document.querySelectorAll('#naver-report-print-root');assert.equal(roots.length,1);assert.equal(roots[0].children[0],paper);
  assert.equal(roots[0].querySelectorAll('*').some(node=>node.tagName==='TEXTAREA'),false);env.event('afterprint');
});
