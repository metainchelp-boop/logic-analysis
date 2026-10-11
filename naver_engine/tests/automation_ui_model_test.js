'use strict';
// Actual UI controller with delayed synthetic replies; no server/ad/AI calls.
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const script = fs.readFileSync('backend/naver_page/automation-ui.js','utf8');
const account = (n=1) => ({possibility_id:n,account_key:String(n).repeat(64),company_name:'합성 업체 '+n,account_name:'개별 계정 '+n,ad_account_no:String(700+n),workflow:'진행중'});
const plan = () => ({goal:'cpa',target_value:100,daily_spend_cap:1000,absolute_bid_cap:200,experiment_days:7,loss_cap:500,notes:'합성 계획'});
function detail(a=account(),version=0,state='empty') {
  return {accounts:[a],selection:{possibility_id:a.possibility_id,account_key:a.account_key,workflow:a.workflow},
    plan:{version,state,metadata:{possibility_id:a.possibility_id,account_key:a.account_key},plan:version?plan():{},execution_status:'not_enabled',experiment_results:null},
    can_edit:true,can_approve:true,execution_enabled:false,setup_checks:{version:1,items:[{key:'time_targeting',label:'노출 시간',state:'unknown',summary:'원천 미수집',next_action:'자료 연결 후 확인'}],counts:{attention:0,unknown:1,verified:0,not_applicable:0},source:{structure:{checked_at:null},campaigns:{checked_at:null},projected_at:'2026-10-10T12:00:00+09:00',limitations:[]}}};
}
function harness() {
  const calls=[],toasts=[],events={}; let ctx='fresh',active=true,purges=0;
  class Element {
    constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.events={};this.disabled=false;this.value='';this._text='';}
    setAttribute(k,v){this.attrs[k]=String(v);if(k==='disabled')this.disabled=true;}
    getAttribute(k){return this.attrs[k];}
    addEventListener(k,f){this.events[k]=f;}
    appendChild(el){this.children.push(el);return el;}
    set textContent(v){this._text=String(v);this.children=[];}
    get textContent(){return this._text+this.children.map(n=>n.textContent||'').join('');}
    dispatch(name){if(name==='click'&&this.disabled)return;return this.events[name]?.call(this,{preventDefault(){}});}
  }
  const root=new Element('div'),reload=new Element('button');root.setAttribute('id','automationRoot');reload.setAttribute('id','automationReload');
  const all=n=>[n,...n.children.flatMap(el=>el.children?all(el):[])];
  const $=id=>[...all(root),reload].find(el=>el.attrs.id===id)||null;
  const add=(el,value)=>{if(value==null||value===false)return;if(Array.isArray(value))value.forEach(v=>add(el,v));else el.appendChild(typeof value==='object'?value:{textContent:String(value)});};
  const h=(tag,attrs,...children)=>{const el=new Element(tag);for(const[k,v]of Object.entries(attrs||{})){if(v==null||v===false)continue;if(k.startsWith('on'))el.addEventListener(k.slice(2),v);else el.setAttribute(k,v);}children.forEach(v=>add(el,v));return el;};
  const put=(el,...children)=>{el.textContent='';children.forEach(v=>add(el,v));return el;};
  const env={h,put,$,num:v=>v==null?'—':String(v),won:v=>v+'원',datedTime:v=>v||'확인 시각 없음',selection:()=> 'mine',context:()=>ctx,active:()=>active,
    api(method,path,body,signal){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});calls.push({method,path,body,signal,resolve,reject});return promise;},
    denied:e=>e.status===401||e.status===403,purge(){purges++;ui.reset();},toast:v=>toasts.push(v)};
  const box={window:{addEventListener:(name,f)=>{events[name]=f;}},AbortController,setTimeout,clearTimeout};vm.runInNewContext(script,box);
  const ui=box.window.NaverAutomation.create(env);
  return {ui,root,$,calls,toasts,events,model:box.window.NaverAutomation.model,get purges(){return purges;},
    button:label=>all(root).find(el=>el.tag==='button'&&el.textContent===label),
    context(value){ctx=value;},active(value){active=value;},async start(a=account(),value=detail(a)){
      ui.load();calls.at(-1).resolve({accounts:[a,account(2)],next_page:null,execution_enabled:false});await flush();
      const select=$('automationAccount');select.value=a.possibility_id+'|'+a.account_key;select.dispatch('change');calls.at(-1).resolve(value);await flush();return value;
    }};
}
async function flush(){await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));}

test('account plans load only scoped stored replies and tabs preserve unsaved input without requests',async()=>{
  const run=harness();await run.start();assert.match(run.calls[0].path,/selection=mine/);assert.equal(run.calls.length,2);
  assert.equal(run.$('automationPlan-target_value').value,'');assert.equal(run.$('automationPlanApprove').disabled,true);
  assert.match(run.root.textContent,/노출 시간자료 미확인원천 미수집/);assert.doesNotMatch(run.root.textContent,/자동 실행 중|전체 세팅 완료됨/);
  const input=run.$('automationPlan-notes');input.value='보존할 초안 <img onerror=x>';input.dispatch('input');
  run.button('A/B 실험').dispatch('click');assert.match(run.root.textContent,/판정 자료가 없습니다/);run.button('AI 자동화 설정').dispatch('click');
  assert.equal(run.$('automationPlan-notes').value,'보존할 초안 <img onerror=x>');assert.equal(run.calls.length,2);assert.equal(run.ui.hasUnsaved(),true);
  assert.match(run.root.textContent,/실제 광고 자동 실행은 미연결/);
});
test('save and approve send exact account version and re-read the same scope',async()=>{
  const run=harness(),a=account();await run.start(a,detail(a,1,'draft'));
  run.$('automationPlan-notes').value='수정된 합성 계획';run.$('automationPlan-notes').dispatch('input');
  assert.equal(run.$('automationPlanApprove').disabled,true);run.$('automationPlanSave').dispatch('click');
  const request=run.calls.at(-1);assert.equal(request.method,'POST');assert.equal(request.path,'/automation/plans');assert.equal(request.body.expected_version,1);
  assert.equal(request.body.account_key,a.account_key);assert.equal(request.body.plan.notes,'수정된 합성 계획');
  run.$('automationPlanSave').dispatch('click');assert.equal(run.calls.filter(r=>r.method==='POST').length,1);
  request.resolve({});await flush();const saved=detail(a,2,'draft');saved.plan.plan.notes='수정된 합성 계획';run.calls.at(-1).resolve(saved);await flush();
  assert.equal(run.ui.hasUnsaved(),false);assert.equal(run.$('automationPlanApprove').disabled,false);run.$('automationPlanApprove').dispatch('click');
  const approval=run.calls.at(-1);assert.equal(approval.body.action,'approve');assert.equal(approval.body.expected_version,2);assert.equal(approval.body.plan,undefined);
  approval.resolve({});await flush();run.calls.at(-1).resolve(detail(a,3,'approved'));await flush();
  assert.match(run.root.textContent,/계획 승인 · 실행 미연결/);assert.match(run.toasts.at(-1),/실제 광고 실행은 연결되지 않았습니다/);
  assert.ok(run.calls.every(r=>r.method==='GET'||r.path==='/automation/plans'));
});
test('capability rejects wrong identity, revision, dirty approval and stale authority',async()=>{
  const run=harness(),data=await run.start(account(),detail(account(),1,'draft'));
  const body={possibility_id:1,account_key:account().account_key,expected_version:1,action:'approve'};
  assert.equal(run.ui.planCapability(body),true);
  for(const change of [{possibility_id:2},{account_key:account(2).account_key},{expected_version:0},{expected_version:'1'},{plan:plan()},{action:'execute'}])assert.equal(run.ui.planCapability({...body,...change}),false);
  run.$('automationPlan-notes').value='미저장';run.$('automationPlan-notes').dispatch('input');assert.equal(run.ui.planCapability(body),false);
  assert.equal(run.ui.planCapability({...body,action:'save',plan:plan()}),true);
  data.can_edit='true';assert.equal(run.ui.planCapability({...body,action:'save',plan:plan()}),false);
  data.can_approve=false;run.context('changed');assert.equal(run.ui.planCapability(body),false);
});
test('late account and hidden replies never restore fields; reset clears memory and cancels reads',async()=>{
  const run=harness();await run.start();const select=run.$('automationAccount');select.value='2|'+account(2).account_key;select.dispatch('change');
  const second=run.calls.at(-1);run.context('changed');second.resolve(detail(account(2),1,'draft'));await flush();assert.equal(run.$('automationPlan-notes'),null);
  run.ui.load();const list=run.calls.at(-1);run.ui.reset();assert.equal(list.signal.aborted,true);list.resolve({accounts:[account()],execution_enabled:false});await flush();assert.equal(run.root.textContent,'');
  run.context('new');await run.start();run.$('automationPlan-notes').value='draft';run.$('automationPlan-notes').dispatch('input');
  let prevented=false;run.events.beforeunload({preventDefault(){prevented=true;}});assert.equal(prevented,true);run.ui.reset();assert.equal(run.ui.hasUnsaved(),false);
});
test('conflicts keep drafts and permission denial after a local tab switch purges the view',async()=>{
  const run=harness();await run.start(account(),detail(account(),1,'draft'));
  run.$('automationPlan-notes').value='keep';run.$('automationPlan-notes').dispatch('input');run.$('automationPlanSave').dispatch('click');
  run.calls.at(-1).reject({status:409});await flush();assert.equal(run.$('automationPlan-notes').value,'keep');assert.match(run.root.textContent,/입력 초안은 보존/);
  run.$('automationPlanSave').dispatch('click');run.button('A/B 실험').dispatch('click');run.calls.at(-1).reject({status:403});await flush();
  assert.equal(run.purges,1);assert.equal(run.root.textContent,'');
});
test('incomplete, loss-exceeding and invalid numeric plans cannot be approved',async()=>{
  const run=harness(),valid=plan();assert.equal(run.model.complete(valid),true);
  for(const change of [{goal:null},{target_value:0},{target_value:Infinity},{daily_spend_cap:1e13},{experiment_days:1},{experiment_days:31},{experiment_days:2.5},{loss_cap:8000}])assert.equal(run.model.complete({...valid,...change}),false);
  const data=detail(account(),1,'draft');data.can_approve=false;await run.start(account(),data);assert.equal(run.$('automationPlanApprove').disabled,true);
  data.can_edit='true';run.button('캠페인 설계').dispatch('click');run.button('AI 자동화 설정').dispatch('click');assert.equal(run.$('automationPlanSave').disabled,true);
});
test('save errors after a local tab switch preserve drafts and show a safe visible message',async()=>{
  for(const status of [409,500]) {
    const run=harness();await run.start(account(),detail(account(),1,'draft'));
    run.$('automationPlan-notes').value='keep after tab';run.$('automationPlan-notes').dispatch('input');run.$('automationPlanSave').dispatch('click');
    run.button('변경 기록').dispatch('click');run.calls.at(-1).reject({status});await flush();
    assert.match(run.toasts.at(-1),status===409?/계획판이 바뀌었습니다/:/저장·승인하지 못했습니다/);
    run.button('AI 자동화 설정').dispatch('click');assert.equal(run.$('automationPlan-notes').value,'keep after tab');
  }
});

test('fourteen stored setup checks preserve unknowns without inventing setup errors',async()=>{
  const run=harness(),data=detail(account(),1,'draft');
  data.setup_checks.items=Array.from({length:14},(_,i)=>({key:'check_'+i,label:'설정 점검 '+i,state:i===0?'attention':'unknown',summary:'저장된 관측 '+i,next_action:'자료 확인 '+i}));
  data.setup_checks.counts={attention:1,unknown:13,verified:0,not_applicable:0};
  await run.start(account(),data);
  for(let i=0;i<14;i++)assert.ok(run.root.textContent.includes('설정 점검 '+i));
  assert.match(run.root.textContent,/확인 필요 1자료 미확인 13/);
  assert.match(run.root.textContent,/Claude는 키·모델 연결 설정 후 보고서에서 명시적으로 생성/);
  assert.equal(run.calls.filter(r=>r.method==='POST').length,0);
});
test('account pages are capped at 100 and next page requests keep the current selection',async()=>{
  const run=harness();run.ui.load();const accounts=Array.from({length:101},(_,i)=>account(i+1));
  run.calls.at(-1).resolve({accounts,next_page:1,execution_enabled:false});await flush();
  assert.equal(run.$('automationAccount').children.length,101);
  run.button('다음 계정 목록').dispatch('click');assert.match(run.calls.at(-1).path,/selection=mine&q=&page=1$/);
  run.calls.at(-1).resolve({accounts:[account(101)],next_page:null,execution_enabled:false});await flush();
  assert.equal(run.$('automationAccount').children.length,2);
  run.button('이전 계정 목록').dispatch('click');assert.match(run.calls.at(-1).path,/page=0$/);
});
test('suspend hides old authority, rejects delayed replies after visibility resumes, and preserves unsaved account draft',async()=>{
  const run=harness(),a=account();await run.start(a,detail(a,1,'draft'));
  run.$('automationPlan-notes').value='숨김 뒤 보존';run.$('automationPlan-notes').dispatch('input');
  run.ui.load();const old=run.calls.at(-1);run.ui.suspend();
  assert.equal(old.signal.aborted,true);assert.equal(run.root.textContent,'');assert.equal(run.ui.hasUnsaved(),true);
  const approval={possibility_id:a.possibility_id,account_key:a.account_key,expected_version:1,action:'approve'};
  assert.equal(run.ui.planCapability(approval),false);
  run.ui.load();const current=run.calls.at(-1);
  old.resolve({accounts:[account(2)],execution_enabled:false});await flush();assert.equal(run.$('automationAccount'),null);
  current.resolve({accounts:[a],next_page:null,execution_enabled:false});await flush();run.calls.at(-1).resolve(detail(a,1,'draft'));await flush();
  assert.equal(run.$('automationPlan-notes').value,'숨김 뒤 보존');assert.equal(run.$('automationPlanApprove').disabled,true);
});
test('unmatched detail identity or enabled executor is refused instead of rendering plan controls',async()=>{
  for(const transform of [data=>{data.selection.account_key=account(2).account_key;},data=>{data.execution_enabled=true;},data=>{data.plan.execution_status='enabled';}]){
    const run=harness(),data=detail(account(),1,'draft');transform(data);await run.start(account(),data);
    assert.equal(run.$('automationPlanSave'),null);assert.match(run.root.textContent,/계정별 계획을 확인하지 못했습니다/);
    assert.equal(run.calls.filter(r=>r.method==='POST').length,0);
  }
});
