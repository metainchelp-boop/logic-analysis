'use strict';
// Real controller and backend templates; synthetic DOM and delayed endpoints only.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),cp=require('node:child_process');
const script=fs.readFileSync('backend/naver_page/learning-ui.js','utf8');
const templates=JSON.parse(cp.execFileSync('python3',['-c',"import json; from naver_engine.learning_assets import document_template; print(json.dumps({k:document_template(k) for k in ('performance','setting_change','experiment')}))"],{encoding:'utf8',env:{...process.env,PYTHONPATH:'backend:.'}}));
const clone=value=>JSON.parse(JSON.stringify(value));
const account=n=>({possibility_id:n,account_key:String(n).repeat(64)});
function asset(kind='performance',version=1,state='draft') {
  const document=clone(templates[kind]);document.title='합성 기록';
  if(kind!=='setting_change')Object.assign(document.evidence,{period_start:'2026-10-01',period_end:'2026-10-07'});
  return {asset_id:'fixture-'+kind,version,state,document,assessment:{outcome:'observation',reason_codes:['no_causal_control'],winner:null},author:{at:'2026-10-08T12:00:00+09:00'},reviewed_at:null};
}
function assets(items=[]) {return {version:1,items,templates:clone(templates),counts:{draft:items.filter(r=>r.state==='draft').length,reviewed:0,rejected:0},retrieval:{version:1,cases:[]},provenance_notice:'검수만으로 인과관계가 입증되지는 않습니다.'};}
function harness(initial=assets(),canEdit=true) {
  const calls=[],messages=[],events={};let context='current',active=true,guard=true,purged=0,refreshes=0,ui;
  const walk=n=>[n,...(n.children||[]).flatMap(walk)];
  class Element {
    constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.events={};this.value='';this.disabled=false;this.checked=false;this._text='';this.isConnected=true;}
    setAttribute(k,v){this.attrs[k]=String(v);if(k==='disabled')this.disabled=true;}
    addEventListener(k,v){this.events[k]=v;}
    appendChild(el){this.children.push(el);return el;}
    set textContent(v){this._text=String(v);this.children=[];}
    get textContent(){return this._text+this.children.map(n=>n.textContent||'').join('');}
    querySelector(selector){const name=selector.slice(1,-1);return walk(this).find(el=>Object.prototype.hasOwnProperty.call(el.attrs||{},name))||null;}
    dispatch(name){if(this.disabled)return;return this.events[name]?.call(this,{preventDefault(){}});}
  }
  const add=(el,value)=>{if(value==null||value===false)return;if(Array.isArray(value))value.forEach(v=>add(el,v));else el.appendChild(typeof value==='object'?value:{textContent:String(value)});};
  const h=(tag,attrs,...children)=>{const el=new Element(tag);for(const[k,v]of Object.entries(attrs||{})){if(v==null||v===false)continue;if(k.startsWith('on'))el.addEventListener(k.slice(2),v);else el.setAttribute(k,v);}children.forEach(v=>add(el,v));return el;};
  const put=(el,...children)=>{el.textContent='';children.forEach(v=>add(el,v));};
  const env={h,put,$:()=>null,num:n=>n==null?'—':String(n),won:n=>String(n)+'원',datedTime:t=>t||'확인 시각 없음',context:()=>context,active:()=>active,
    denied:e=>e.status===401||e.status===403,purge(){purged++;ui.reset();},toast:t=>messages.push(t),api(method,path,body){assert.equal(ui.capability(body),true,'write must hold current capability');let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});calls.push({method,path,body,resolve,reject});return promise;}};
  let uuid=0;const box={window:{addEventListener:(name,f)=>{events[name]=f;},crypto:{randomUUID:()=> '00000000-0000-4000-8000-'+String(++uuid).padStart(12,'0')}},Date};
  vm.runInNewContext(script,box);ui=box.window.NaverLearningAssets.create(env);
  let root;const run={ui,calls,messages,events,env,get root(){return root;},get purged(){return purged;},get refreshes(){return refreshes;},
    render(data=initial,edit=canEdit,selected=account(1)){if(root)root.isConnected=false;root=ui.render(data,selected,edit,()=>guard,()=>{refreshes++;return Promise.resolve();});return root;},
    all:()=>walk(root),button:label=>walk(root).find(el=>el.tag==='button'&&el.textContent===label),
    input:suffix=>walk(root).find(el=>el.attrs&&el.attrs.id&&el.attrs.id.endsWith('-'+suffix)),
    fill(suffix,value,event='input'){const el=this.input(suffix);assert.ok(el,suffix);el.value=value;el.dispatch(event);},
    context:value=>{context=value;},active:value=>{active=value;},guard:value=>{guard=value;}};
  run.render();return run;
}
async function flush(){await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));}

test('read only allows stored detail but rejects save, review and capture',()=>{
  const row=asset(),run=harness(assets([row]),false);run.button('상세 보기').dispatch('click');
  assert.equal(run.input('title').value,'합성 기록');assert.equal(run.input('title').disabled,true);
  assert.equal(run.button('성과 관측 등록').disabled,true);
  for(const action of ['capture','review','reject'])assert.equal(run.ui.capability({possibility_id:1,account_key:account(1).account_key,action,asset_id:row.asset_id,expected_version:1}),false);
  assert.equal(run.calls.length,0);
});
test('new performance uses human fields, preserves zero and unknown distinctly and exact scoped save',async()=>{
  const run=harness();run.button('성과 관측 등록').dispatch('click');assert.equal(run.ui.hasUnsaved(),true);assert.equal(run.button('자산 초안 저장').disabled,true);
  run.fill('title','실제 값 입력');run.fill('evidence-period_start','2026-10-01');run.fill('evidence-period_end','2026-10-07');run.fill('evidence-spend','0');run.fill('evidence-clicks','0');
  assert.equal(run.button('자산 초안 저장').disabled,false);run.button('자산 초안 저장').dispatch('click');
  const request=run.calls[0];assert.equal(request.path,'/automation/learning');assert.equal(request.body.action,'save');assert.equal(request.body.expected_version,0);
  assert.equal(request.body.document.evidence.spend,0);assert.equal(request.body.document.evidence.clicks,0);assert.equal(request.body.document.evidence.conversions,null);
  assert.equal(request.body.document.evidence.conversion_definition,'unknown');assert.equal(run.all().some(n=>n.tag==='textarea'),false);
  run.button('자산 초안 저장').dispatch('click');assert.equal(run.calls.length,1);
  request.resolve({});await flush();assert.equal(run.refreshes,1);assert.equal(run.ui.hasUnsaved(),false);assert.match(run.messages[0],/광고는 변경하지 않았습니다/);
});
test('capture has only account identity and capture action; extra payload and stale context are denied',()=>{
  const run=harness(),body={possibility_id:1,account_key:account(1).account_key,action:'capture'};
  assert.equal(run.ui.capability(body),true);for(const extra of [{expected_version:0},{document:{}},{possibility_id:2},{action:'execute'}])assert.equal(run.ui.capability({...body,...extra}),false);
  run.button('최신 저장 보고서 편입').dispatch('click');assert.deepEqual(Object.keys(run.calls[0].body).sort(),['account_key','action','possibility_id']);
  run.context('changed');assert.equal(run.ui.capability(body),false);
});
test('review uses displayed draft version and refuses dirty editor or wrong account',()=>{
  const row=asset(),run=harness(assets([row])),body={possibility_id:1,account_key:account(1).account_key,action:'review',asset_id:row.asset_id,expected_version:1};
  assert.equal(run.ui.capability(body),true);for(const change of [{expected_version:0},{account_key:account(2).account_key},{document:{}},{action:'approve'}])assert.equal(run.ui.capability({...body,...change}),false);
  run.button('상세 보기').dispatch('click');run.fill('title','미저장 변경');assert.equal(run.ui.capability(body),false);
  run.button('입력 초안 닫기·버리기').dispatch('click');run.button('검수 완료').dispatch('click');assert.equal(run.calls[0].body.expected_version,1);assert.equal(run.calls[0].body.document,undefined);
});
test('updated server version preserves typed draft and disables stale saving',()=>{
  const row=asset(),run=harness(assets([row]));run.button('상세 보기').dispatch('click');run.fill('title','보존할 내용');run.render(assets([asset('performance',2)]));
  assert.equal(run.input('title').value,'보존할 내용');assert.equal(run.input('title').disabled,true);assert.equal(run.button('자산 초안 저장').disabled,true);assert.match(run.root.textContent,/서버에 새 판/);
  run.button('A/B 실험 등록').dispatch('click');assert.equal(run.input('title').value,'보존할 내용');assert.match(run.root.textContent,/먼저 저장하거나/);
  let prevented=false;run.events.beforeunload({preventDefault(){prevented=true;}});assert.equal(prevented,true);
});
test('server report references stay immutable while review is permitted',()=>{
  const row=asset();row.document.source_refs={report_id:88,report_revision:'a'.repeat(64)};const run=harness(assets([row]));run.button('상세 보기').dispatch('click');
  assert.equal(run.input('evidence-spend').disabled,true);assert.equal(run.button('자산 초안 저장').disabled,true);assert.match(run.root.textContent,/원본 수치를 수정하지 않고 검수/);
  run.button('검수 완료').dispatch('click');assert.equal(run.calls[0].body.action,'review');
});
test('experiment editing keeps control and treatment observations separate and every backend field',()=>{
  const run=harness();run.button('A/B 실험 등록').dispatch('click');run.fill('title','사전 실험');run.fill('evidence-period_start','2026-10-12');run.fill('evidence-period_end','2026-10-25');
  run.fill('evidence-control-impressions','10000');run.fill('evidence-treatment-impressions','9000');run.fill('evidence-treatment-clicks','300');run.fill('evidence-baseline_rate','0.02');
  run.button('자산 초안 저장').dispatch('click');const evidence=run.calls[0].body.document.evidence;
  assert.equal(evidence.control.impressions,10000);assert.equal(evidence.treatment.impressions,9000);assert.equal(evidence.treatment.clicks,300);assert.equal(evidence.control.clicks,null);
  assert.equal(evidence.randomized,false);assert.deepEqual(Object.keys(evidence).sort(),Object.keys(templates.experiment.evidence).sort());assert.equal(evidence.status,'running');
  assert.match(run.root.textContent,/과거 결과를 사후 입력하면/);
});
test('setting comparison preserves before and after including disabled and zero',()=>{
  const row=asset('setting_change');row.document.evidence.before={bid:100,enabled:true};row.document.evidence.after={bid:90,enabled:false};
  const run=harness(assets([row]));run.button('상세 보기').dispatch('click');run.fill('evidence-after-bid','0');run.button('자산 초안 저장').dispatch('click');
  const e=run.calls[0].body.document.evidence;assert.equal(e.before.bid,100);assert.equal(e.after.bid,0);assert.equal(e.before.enabled,true);assert.equal(e.after.enabled,false);assert.equal(e.execution,'planned');
});
test('conflict preserves draft; permission denial purges; late success cannot refresh new authority',async()=>{
  const run=harness(assets([asset()]));run.button('상세 보기').dispatch('click');run.fill('title','보존 초안');run.button('자산 초안 저장').dispatch('click');run.calls[0].reject({status:409});await flush();
  assert.equal(run.input('title').value,'보존 초안');assert.match(run.root.textContent,/입력 초안은 보존/);
  run.button('자산 초안 저장').dispatch('click');run.calls[1].reject({status:403});await flush();assert.equal(run.purged,1);assert.equal(run.ui.hasUnsaved(),false);
  const late=harness();late.button('최신 저장 보고서 편입').dispatch('click');late.guard(false);late.calls[0].resolve({});await flush();assert.equal(late.refreshes,0);assert.equal(late.messages.length,0);
});
test('server outcome is displayed without inventing a winner and untrusted title remains text',()=>{
  const row=asset();row.document.title='<img src=x onerror=alert(1)>';row.assessment={outcome:'invalid',reason_codes:['sample_ratio_mismatch'],winner:null};const run=harness(assets([row]));
  assert.match(run.root.textContent,/<img src=x/);assert.match(run.root.textContent,/유효 조건 미충족/);assert.match(run.root.textContent,/표본 비율 불일치/);assert.doesNotMatch(run.root.textContent,/우수군/);assert.equal(run.all().some(n=>n.tag==='img'),false);
  run.root.isConnected=false;assert.equal(run.ui.capability({possibility_id:1,account_key:account(1).account_key,action:'capture'}),false);
});
