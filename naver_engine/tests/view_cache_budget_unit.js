'use strict';
// Actual route/fetchView source, controlled API promises, no browser/network/business data.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sourcePath = process.argv[2] || path.join(__dirname, '../../backend/naver_page/app.js');
const source = fs.readFileSync(sourcePath, 'utf8');
function block(begin, end) {
  const start = source.indexOf(begin), finish = source.indexOf(end, start);
  assert.ok(start >= 0 && finish > start, 'actual screen source seam must exist');
  return source.slice(start, finish);
}
const snippets = [
  block('  var SCREEN = ', '\n\n  // ── 작은 도구'),
  block('  var VIEW_FIELDS = ', '  // 변하지 않은 행은'),
  block('  var SCREENS = ', '\n  // ── 위 띠'),
  block('  function openDashboard()', '\n  // ── 🛰 관제'),
  block('  function openWatch()', '\n  var INVENTORY_MAPPING'),
  block('  function loadInventory()', '\n  function knownBalance')
].join('\n');
class Classes {
  constructor() { this.names = new Set(); }
  add(name) { this.names.add(name); }
  remove(name) { this.names.delete(name); }
  contains(name) { return this.names.has(name); }
  toggle(name, force) { if (force) this.add(name); else this.remove(name); }
}
class ApiError extends Error {
  constructor(status, body) { super(body.error); this.status = status; this.body = body; }
}
function fixture() {
  const nodes = new Map(), requests = [], renders = {dashboard:0, transfers:0, watch:0};
  let day = '2026-10-09', tick = Date.parse('2026-10-09T10:00:00+09:00');
  class Clock extends Date { static now() { return tick; } }
  function $(id) {
    if (!nodes.has(id)) nodes.set(id, {classList:new Classes(), hidden:false,
      setAttribute(name,value) {this[name]=value;}, scrollIntoView() {}, textContent:'', value:''});
    return nodes.get(id);
  }
  const context = {
    $, reportUI:null, automationUI:null, ApiError, AbortController, URLSearchParams, Map, Set,
    Date:Clock, isFinite, setTimeout, document:{visibilityState:'visible',querySelectorAll:()=>[]},
    window:{addEventListener() {}}, location:{pathname:'/naver/dashboard',search:''},
    history:{pushState() {}}, put(){}, h(){return {};}, datedTime:value=>value,
    kstDay:()=>day, closeModals(){}, closeBell(){}, renderLinks(){},
    errText:error=>error.body.error, endedAccountsFilter(){}, openClient(){}, openSettings(){},
    loadReports(){}, loadLinks(){},
    renderDashboard(){renders.dashboard++;}, renderWatch(){renders.watch++;},
    renderInventory(){renders.transfers++;},
    api(method, url, body, signal) {
      return new Promise((resolve,reject)=>requests.push({method,url,signal,resolve,reject}));
    }
  };
  vm.createContext(context);
  vm.runInContext(snippets, context, {filename:sourcePath});
  context.state.me={idx:1,scope:'ALL',narrowed:false};
  context.state.session={narrowed:false};
  return {context, requests, renders, $, advance:ms=>{tick+=ms;}, setDay:value=>{day=value;},
    navigate(name) {context.location.pathname='/naver/'+name; return context.route();},
    gated:name=>$('s-'+name).classList.contains('view-unverified')};
}
function payload(name, size=0, selection='all') {
  const common={selection, padding:'x'.repeat(size)};
  if(name==='dashboard') return {...common,period:{},accounts:{},coverage:{}};
  if(name==='watch') return {...common,band:{},counts:{},rows:[{possibility_id:11,verdict:{},owner:{}}]};
  return {...common,rows:[{ad_account_no:'12345'}],counts:{}};
}
function full(data, cursor='synthetic_cursor_a') {
  return {version:1,mode:'full',cursor,base_cursor:null,
    checked_at:'2026-10-09T10:00:00+09:00',data,rows:null};
}
function unchanged(cursor='synthetic_cursor_a') {
  return {version:1,mode:'unchanged',cursor,base_cursor:cursor,
    checked_at:'2026-10-09T10:00:01+09:00',data:null,rows:null};
}
function cursorSent(request) {return new URL('http://offline'+request.url).searchParams.has('view_cursor');}
async function loaded(f,name,size=0,cursor='synthetic_cursor_a') {
  const promise=f.navigate(name), request=f.requests.at(-1);
  request.resolve(full(payload(name,size),cursor)); await promise;
}
function retainedBytes(f) {
  return Array.from(f.context.viewCache.values()).reduce((sum,entry)=>sum+entry.bytes,0);
}

test('operating-sized accounts retain cursor on tab reentry, hidden until fresh acknowledgement', async()=>{
  const f=fixture();
  // An observed 2.55M-character wire body exceeds the former 4MiB UTF16 estimate.
  // Use synthetic padding only; production account data is never copied into this test.
  await loaded(f,'transfers',2546000);
  const prior=f.context.state.inventory;
  await loaded(f,'dashboard',128,'synthetic_cursor_b');
  const renders=f.renders.transfers, promise=f.navigate('transfers'), request=f.requests.at(-1);
  assert.equal(cursorSent(request),true,'cached accounts must request changes instead of full data again');
  assert.equal(f.gated('transfers'),true,'a cursor never substitutes for current authority');
  assert.equal(f.renders.transfers,renders,'no repaint before fresh authority acknowledgement');
  request.resolve(unchanged()); await promise;
  assert.equal(f.gated('transfers'),false);
  assert.equal(f.context.state.inventory===prior,true,'unchanged preserves the successful payload object');
  assert.ok(retainedBytes(f)<=8*1024*1024,'retained serialized estimate remains bounded');
});

test('large accounts plus another cached screen fit; over-limit LRU entries still evict', async()=>{
  const f=fixture();
  await loaded(f,'transfers',2546000);
  await loaded(f,'dashboard',1200000,'synthetic_cursor_b');
  const promise=f.navigate('transfers'), request=f.requests.at(-1);
  assert.equal(cursorSent(request),true,'combined data below 8MiB must retain accounts cursor');
  request.resolve(unchanged()); await promise;
  await loaded(f,'watch',1200000,'synthetic_cursor_c');
  assert.ok(retainedBytes(f)<=8*1024*1024);
  // Dashboard is the oldest of three views; 9.8MiB of estimates cannot all remain.
  const reentry=f.navigate('dashboard'), fresh=f.requests.at(-1);
  assert.equal(cursorSent(fresh),false,'least recently used over-budget view must be dropped');
  fresh.resolve(full(payload('dashboard'))); await reentry;
});

test('one oversized payload remains uncached and count stays limited to eight entries', async()=>{
  const f=fixture();
  await loaded(f,'transfers',4300000);
  await loaded(f,'dashboard');
  const promise=f.navigate('transfers'), request=f.requests.at(-1);
  assert.equal(cursorSent(request),false,'over 8MiB estimate must not be retained');
  request.resolve(full(payload('transfers'))); await promise;
  f.context.viewCache.clear();
  for(let i=0;i<9;i++) f.context.cacheView('synthetic-'+i,{data:payload('dashboard'),cursor:'cursor_'+i});
  assert.equal(f.context.viewCache.size,8);
  assert.equal(f.context.viewCache.has('synthetic-0'),false);
  assert.ok(retainedBytes(f)<=8*1024*1024);
});

test('age expiry and a new KST day discard cursor', async()=>{
  for(const change of [f=>f.advance(10*60*1000+1),f=>f.setDay('2026-10-10')]) {
    const f=fixture(); await loaded(f,'transfers'); await loaded(f,'dashboard'); change(f);
    const promise=f.navigate('transfers'), request=f.requests.at(-1);
    assert.equal(cursorSent(request),false);
    assert.equal(f.gated('transfers'),true);
    request.resolve(full(payload('transfers'))); await promise;
  }
});

test('duplicate clicks share one request and one pending promise', async()=>{
  const f=fixture(), first=f.navigate('transfers'), duplicate=f.navigate('transfers');
  assert.equal(first,duplicate);
  assert.equal(f.requests.length,1);
  f.requests[0].resolve(full(payload('transfers'))); await first;
});

test('403, 401 and stale organization purge earlier business data', async()=>{
  for(const error of [new ApiError(403,{error:'not-visible'}),new ApiError(401,{error:'unauthorized'}),
    new ApiError(503,{error:'org-stale'})]) {
    const f=fixture(); await loaded(f,'transfers'); await loaded(f,'dashboard');
    const promise=f.navigate('transfers'); f.requests.at(-1).reject(error); await promise;
    assert.equal(f.gated('transfers'),true);
    assert.equal(f.context.state.inventory,null);
    assert.equal(f.context.viewCache.size,0);
  }
});

test('scope and narrowed-session changes reject delayed old responses', async()=>{
  for(const change of [f=>{f.context.state.selection='person:100';},
    f=>{f.context.state.session.narrowed=true;}]) {
    const f=fixture(); await loaded(f,'transfers'); await loaded(f,'dashboard');
    const older=f.navigate('transfers'), oldRequest=f.requests.at(-1);
    change(f); const newer=f.navigate('transfers'), newRequest=f.requests.at(-1);
    assert.equal(oldRequest.signal.aborted,true);
    assert.equal(cursorSent(newRequest),false);
    oldRequest.resolve(unchanged()); await older;
    assert.equal(f.gated('transfers'),true,'obsolete success must not reveal current scope');
    assert.equal(f.context.state.inventory,null);
    newRequest.resolve(full(payload('transfers',0,f.context.state.selection))); await newer;
    assert.equal(f.gated('transfers'),false);
  }
});

test('visible refresh may show stale verified data; hidden reentry network failure stays hidden', async()=>{
  const f=fixture(); await loaded(f,'transfers');
  const data=f.context.state.inventory, visible=f.navigate('transfers');
  f.requests.at(-1).reject(new ApiError(0,{error:'network'})); await visible;
  assert.equal(f.gated('transfers'),false);
  assert.equal(f.$('inventorySync')['data-status'],'stale');
  assert.equal(f.context.state.inventory===data,true);
  await loaded(f,'dashboard'); const hidden=f.navigate('transfers');
  f.requests.at(-1).reject(new ApiError(0,{error:'network'})); await hidden;
  assert.equal(f.gated('transfers'),true);
  assert.equal(f.$('inventorySync')['data-status'],'error');
});
