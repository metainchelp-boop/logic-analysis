/* 실제 app.js의 DOM/이벤트/API 계약 회귀. 브라우저·운영 서버는 호출하지 않는다. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');
const test = require('node:test');
const vm = require('node:vm');
const page = path.join(__dirname, '../backend/naver_page');
const html = fs.readFileSync(path.join(page, 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(page, 'app.js'), 'utf8');
const reportUI = fs.readFileSync(path.join(page, 'report-ui.js'), 'utf8');

class Element {
  constructor(tag = 'div', registerId) {
    this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.events = {};
    this.registerId = registerId;
    this.value = ''; this.disabled = false; this._text = '';
    const classes = new Set();
    this.classList = { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x) };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'value') this.value = String(v); if (k === 'disabled') this.disabled = true;
    if (k === 'id' && this.registerId) this.registerId(String(v), this); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, fn) { (this.events[k] ||= []).push(fn); }
  dispatch(k) { if (k === 'click' && this.disabled) return; const event = {currentTarget:this,target:this,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};
    (this.events[k] || []).forEach(fn => fn.call(this, event)); return event; }
  appendChild(el) { return this.insertBefore(el, null); }
  insertBefore(el, before) {
    if (el === before) return el;
    if (el.parentNode) el.parentNode.removeChild(el);
    const index = before === null ? this.children.length : this.children.indexOf(before);
    assert.ok(index >= 0, 'insertBefore 기준 노드는 부모에 있어야 한다');
    this.children.splice(index, 0, el); el.parentNode = this; return el;
  }
  removeChild(el) {
    const index = this.children.indexOf(el); assert.ok(index >= 0);
    this.children.splice(index, 1); el.parentNode = null; return el;
  }
  get childNodes() { return this.children; }
  get firstChild() { return this.children[0]; }
  focus() {}
  scrollIntoView() {}
  contains(el) { return this === el || this.children.some(x => x.contains && x.contains(el)); }
  querySelectorAll() { return []; }
}
function tree(el) { return [el, ...el.children.flatMap(x => x.children ? tree(x) : [x])]; }
function fixture(overrides = {}) {
  return Object.assign({ ad_account_no: '700', account_name: '합성 계정', company_name: '합성 업체', possibility_id: 1,
    mapping: 'matched', workflow: '진행중', owner: { name: '합성 담당자' }, collection: {},
    management: { cadence: 'daily', reason: 'active_stage', stage_revision: 'r1', excluded: false, can_manage: false, can_collect: false } }, overrides);
}
function inventory(rows = [], coverage) {
  return { rows, total: rows.length, counts: { matched: rows.length, no_erp_record: 0, unclassified: 0 },
    accounts_current: true, matching_ready: true, catalog_status: 'accepted',
    managed_coverage: coverage || { ready: true, total: 1, matched: 1, missing: 0, items: [] } };
}
function launch(options = {}) {
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const requests = [], events = {}, opened = [];
  const location = new URL('https://watch.invalid/naver/' + (options.screen || 'transfers'));
  const window = { addEventListener: (k, fn) => { events[k] = fn; }, open: (...args) => {opened.push(args); return null;} };
  const createElement = tag => new Element(tag, (id, element) => elements.set(id, element));
  const document = { visibilityState: 'visible', getElementById: id => elements.get(id), createElement,
    createElementNS: (_namespace, tag) => createElement(tag),
    createTextNode: text => ({ textContent: String(text) }), addEventListener() {}, body: { contains: () => true },
    querySelectorAll: selector => selector === '.modal' ? [...elements].filter(([id]) => id.startsWith('m-')).map(([, el]) => el) : [],
    querySelector: () => null };
  const history = { pushState: (_, __, url) => { location.href = new URL(url, location).href; } };
  const context = vm.createContext({ window, document, location, history, URL, URLSearchParams, AbortController, performance,
    sessionStorage: { getItem: () => JSON.stringify({ token: 'synthetic', exp: Date.now() + 3600000 }) },
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    fetch: async (url, init) => {
      const req = { url, method: init.method, body: init.body ? JSON.parse(init.body) : null }; requests.push(req);
      let body;
      if (url.endsWith('/me')) body = options.me || { scope: 'ALL', owner_verification: true };
      // 상태 조회는 업무 응답/보류 큐와 분리하되 실제 요청 기록과 AbortSignal 검사는 유지한다.
      else if (url === '/api/naver-auto/health?runtime=1') {
        assert.equal(init.method, 'GET');
        assert.ok(init.signal instanceof AbortSignal);
        body = {runtime:{state:'unavailable', indicator:'red', reason_code:'UNAVAILABLE',
          verified_at:null, valid_for_seconds:0, retry_at:null}};
      }
      else if (options.respond) body = await options.respond(req, init);
      else body = options.data || inventory();
      // HTTP JSON 응답은 호출마다 새 객체다. fixture 참조 공유로 옛 범위의 행을 되살리지 않는다.
      const status = options.status ? options.status(req) : 200;
      return { status, ok: status >= 200 && status < 300, json: async () => {
        const response = JSON.parse(JSON.stringify(body));
        if (options.freezeRows && response.rows) Object.freeze(response.rows);
        return response;
      } };
    } });
  vm.runInContext(reportUI, context);
  vm.runInContext(app, context);
  return { elements, requests, opened, location, text: id => elements.get(id).textContent,
    buttons: id => tree(elements.get(id)).filter(el => el.tagName === 'BUTTON'),
    scope(value) { const el = elements.get('scope'); el.value = value; el.dispatch('change'); },
    navigate(screen) { location.href = new URL('/naver/' + screen, location).href; events.popstate(); } };
}
async function flush() { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); }
async function showAccounts(run) {
  run.elements.get('inventoryAccountsTab').dispatch('click');
  await flush();
  assert.equal(run.elements.get('inventoryCard').hidden, false);
  assert.equal(run.elements.get('managedCoverage').hidden, true);
  assert.equal(run.elements.get('s-transfers').classList.contains('view-unverified'), false);
}

test('이관 목록은 비즈머니 높은 순으로 정렬하고 동률·0·음수·미확인을 보존한다', async () => {
  const values = [null, 0, -3, 10.5, 10.5, '900', true, 20, Number.MAX_SAFE_INTEGER + 1];
  const run = launch({freezeRows:true,data:inventory(values.map((value, index) => fixture({
    ad_account_no:String(700 + index), collection:{bizmoney:value}
  })))});
  await flush(); await showAccounts(run);
  assert.deepEqual(run.elements.get('inventoryRows').children.map(row => row.getAttribute('data-account')),
    ['707','703','704','701','702','700','705','706','708']);
  assert.match(html, /id="inventorySort">비즈머니 높은 순/);
  assert.equal(run.requests.filter(request => request.method !== 'GET').length, 0);
});

test('상세 점검 책갈피 상한·손상 사유는 오늘 계정만 쉽게 설명하고 과거 사유는 재표시하지 않는다', async () => {
  const today = new Date(Date.now() + 9 * 3600000).toISOString().slice(0,10);
  const client = {possibility_id:11,name:'합성 업체',stage:'진행중',managed:true,link:'listed',
    verdict:{color:'white',white_reason:'partial'},days:[],issues:[],yday_spend:null,
    accounts:[{tail:'1111',state:'auto',history:[{day:today,status:'partial',rules_not_run:[
      ['D1','checkpoint-too-large'],['D2','checkpoint-too-large'],['D3','<img src=x>']]}]},
      {tail:'2222',state:'auto',history:[{day:today,status:'partial',rules_not_run:[['D1','checkpoint-invalid']]}]},
      {tail:'3333',state:'auto',history:[{day:'2000-01-01',status:'partial',rules_not_run:[['D1','checkpoint-too-large']]}]}]};
  const run = launch({screen:'clients/11',respond:req => req.url.includes('/clients/11') ? client :
    {rows:[],decisions:[],source_state:'accepted'}});
  await flush();
  const text = run.text('p-now');
  assert.match(text,/1111.*광고 자료가 커서 상세 점검을 보류/);
  assert.match(text,/2222.*읽던 위치의 기록을 확인할 수 없어 새로 점검/);
  assert.equal((text.match(/광고 자료가 커서 상세 점검을 보류/g)||[]).length,1);
  assert.doesNotMatch(text,/3333|<img/);
  assert.equal(run.requests.filter(req => req.method !== 'GET').length,0);
});

test('현재 목록 합계는 검색과 서버 필터 이후의 잔액을 십진 합산한 뒤 한 번 절사한다', async () => {
  const rows = [fixture({account_name:'대상 하나', collection:{bizmoney:0.29}}),
    fixture({ad_account_no:'701',account_name:'대상 둘',collection:{bizmoney:0.71,stale:true}}),
    fixture({ad_account_no:'702',account_name:'다른 계정',collection:{bizmoney:5}}),
    fixture({ad_account_no:'703',account_name:'대상 미확인',collection:{bizmoney:null}})];
  const run = launch({respond:request => inventory(request.url.includes('mapping=matched') ? rows.slice(0,1) : rows)});
  await flush(); await showAccounts(run);
  assert.match(run.text('inventoryBalance'), /확인된 잔액 합계 : 6원.*확인 3 \/ 4계정 · 미확인 1.*계정별 확인 시각 기준.*이전 확인값 포함/);
  const search = run.elements.get('inventorySearch'); search.value = '대상'; search.dispatch('input');
  assert.match(run.text('inventoryBalance'), /확인된 잔액 합계 : 1원.*확인 2 \/ 3계정 · 미확인 1/);
  const mapping = run.elements.get('inventoryMapping'); mapping.value = 'matched'; mapping.dispatch('change'); await flush();
  assert.match(run.text('inventoryBalance'), /확인된 잔액 합계 : 0원.*확인 1 \/ 1계정/);
  assert.equal(run.requests.filter(request => request.method !== 'GET').length, 0);
});

test('담당 범위 교체는 이전 목록 합계를 즉시 지우고 늦은 응답을 되살리지 않는다', async () => {
  const waiting = [];
  const run = launch({respond:request => request.url.includes('selection=all') ? inventory([fixture({collection:{bizmoney:1234}})]) :
    new Promise(resolve => waiting.push(resolve))});
  await flush(); assert.match(run.text('inventoryBalance'), /1,234원/);
  run.scope('person:2');
  assert.equal(run.text('inventoryBalance'), '');
  run.scope('person:3');
  waiting[1](inventory([fixture({collection:{bizmoney:5}})])); await flush();
  waiting[0](inventory([fixture({collection:{bizmoney:900}})])); await flush();
  assert.match(run.text('inventoryBalance'), /합계 : 5원/);
});

test('목록 합계는 대상 없음·확인 없음·원천 보류·비정상값·표시 범위 초과를 구분한다', async () => {
  for (const [values, changes, expected] of [
    [[], {}, /합계 : 0원.*대상 계정 없음/],
    [[null,'4',true,Number.MAX_SAFE_INTEGER+1], {}, /합계 : —.*확인 잔액 없음.*확인 0 \/ 4계정/],
    [[3], {matching_ready:false}, /합계 : —.*집계 보류/],
    [[3], {summary:{ready:false}}, /합계 : —.*집계 보류/],
    [[Number.MAX_SAFE_INTEGER,1], {}, /합계 : —.*안전한 표시 범위 초과/],
    [[-0.29,-0.71], {}, /합계 : -1원/],
    [[1e-7,0.9999999], {}, /합계 : 1원/],
    [[null], {view:'lost'}, /합계 : —.*확인 잔액 없음/]
  ]) {
    const data = Object.assign(inventory(values.map((value,index) => fixture({ad_account_no:String(700+index),collection:{bizmoney:value}}))),changes);
    const run = launch({data}); await flush();
    assert.match(run.text('inventoryBalance'), expected);
  }
});

test('누락 대조 검색은 업체·단계·담당자 공백과 대소문자를 정리하며 계정 검색과 독립 유지된다', async () => {
  const coverage = {ready:true,total:3,matched:1,missing:2,items:[
    {possibility_id:1,company_name:'Alpha   업체',workflow:'전략관리',owner:{name:'Kim   담당'}},
    {possibility_id:2,company_name:'Beta 업체',workflow:'진행중',owner:{name:'Lee 담당'}},
    {possibility_id:3,company_name:'Gamma 업체',workflow:'사후관리',owner:{name:'Park 담당'}}]};
  const run = launch({data:inventory([fixture()],coverage)}); await flush();
  const search = run.elements.get('coverageSearch');
  for (const query of ['  ALPHA 업체 ', '전략관리', 'kim 담당']) {
    search.value = query; search.dispatch('input');
    assert.match(run.text('coverageRows'), /Alpha/); assert.doesNotMatch(run.text('coverageRows'), /Beta|Gamma/);
    assert.equal(run.text('coverageSearchStatus'), '검색 결과 1 / 3업체');
    assert.match(run.text('coverageStatus'), /실관리 3.*연결 확인 1.*확인 필요 2/);
  }
  await showAccounts(run);
  const accountSearch = run.elements.get('inventorySearch'); accountSearch.value = '계정없음'; accountSearch.dispatch('input');
  run.elements.get('inventoryCoverageTab').dispatch('click'); await flush();
  assert.equal(search.value, 'kim 담당'); assert.match(run.text('coverageRows'), /Alpha/);
  run.elements.get('inventoryReload').dispatch('click'); await flush();
  assert.equal(run.text('coverageSearchStatus'), '검색 결과 1 / 3업체');
  search.value = '없는업체'; search.dispatch('input');
  assert.match(run.text('coverageRows'), /검색 조건에 맞는 실관리 업체가 없습니다/);
  run.scope('me'); await flush();
  assert.equal(search.value, ''); assert.equal(run.text('coverageSearchStatus'), '검색 결과 3 / 3업체');
});

test('ID 미입력 후보는 정확한 전산 업체 URL을 분리해 열며 안전한 대체 링크와 재진입 안내를 제공한다', async () => {
  const run = launch({data:inventory([], {ready:true,total:2,matched:0,missing:2,items:[
    {possibility_id:51,company_name:'합성 업체 A',state:'candidate_pending',codes:['ID_MISSING']},
    {possibility_id:52,company_name:'합성 업체 B',state:'id_missing',codes:[]}]})});
  await flush();
  const buttons = run.buttons('coverageRows').filter(button => button.textContent === '광고 계정 ID 입력');
  assert.equal(buttons.length, 1); buttons[0].dispatch('click');
  const url = 'http://metainc.co.kr/metapos/advertiser-setup?company=51&panel=credentials&vendor=naver';
  assert.deepEqual(run.opened, [[url, '_blank', 'noopener,noreferrer']]);
  const link = tree(run.elements.get('coverageRows')).find(el => el.tagName === 'A');
  assert.equal(link.getAttribute('href'), url); assert.equal(link.getAttribute('target'), '_blank');
  assert.equal(link.getAttribute('rel'), 'noopener noreferrer');
  assert.match(run.text('coverageRows'), /전산 로그인 뒤 관제로 돌아와.*광고 계정 ID 입력.*다시/);
  assert.doesNotMatch(run.text('toast'), /저장 완료|연결 완료/);
  assert.equal(run.requests.filter(request => !request.url.includes('/me') && !request.url.includes('/accounts?') &&
    request.url !== '/api/naver-auto/health?runtime=1').length, 0);
  assert.equal(run.requests.filter(request => request.url === '/api/naver-auto/health?runtime=1').length, 1);
});

test('전산 입력은 원천 보류·잘못된 업체 번호·현재 검색 제외·교체된 자료·권한 확인 전에서 열리지 않는다', async () => {
  function data(pid=51) { return inventory([], {ready:true,total:1,matched:0,missing:1,items:[
    {possibility_id:pid,company_name:'대상',codes:['ID_MISSING'],state:'candidate_pending'}]}); }
  for (const pid of ['51','51&vendor=other',0,-1,1.5,Number.MAX_SAFE_INTEGER+1]) {
    const run = launch({data:data(pid)}); await flush();
    assert.equal(run.buttons('coverageRows').filter(button => button.textContent === '광고 계정 ID 입력').length,0);
  }
  for (const mode of ['source','scope','search','snapshot','unverified','navigate']) {
    const value = data(); if (mode === 'source') value.managed_coverage.ready=false;
    const run = launch({data:value}); await flush();
    const button = run.buttons('coverageRows').find(button => button.textContent === '광고 계정 ID 입력');
    if (mode === 'source') { assert.equal(button,undefined); continue; }
    const link = tree(run.elements.get('coverageRows')).find(el => el.tagName === 'A');
    if (mode === 'scope') { run.scope('me'); await flush(); }
    if (mode === 'search') { const input=run.elements.get('coverageSearch');input.value='다른업체';input.dispatch('input'); }
    if (mode === 'snapshot') { run.elements.get('inventoryReload').dispatch('click');await flush(); }
    if (mode === 'unverified') run.elements.get('s-transfers').classList.add('view-unverified');
    if (mode === 'navigate') run.navigate('dashboard');
    button.dispatch('click');
    assert.equal(link.dispatch('click').defaultPrevented,true,mode);
    assert.equal(link.dispatch('auxclick').defaultPrevented,true,mode);
    assert.equal(run.opened.length,0,mode);
  }
});

function linkFixture(overrides = {}) {
  return Object.assign({ ref: 'synthetic-ref-1', pair_key: 'synthetic-pair-1', possibility_id: 1,
    name: '목표 업체', state: 'auto', code: 'same', can_confirm: true, detail_available: false }, overrides);
}
function pending(rows = [], decisions = [], overrides = {}) {
  return Object.assign({ source: 'catalog', source_state: 'accepted', pairing_at: '2026-10-02T08:00:00+09:00',
    pairing_today: true, rows, decisions }, overrides);
}
function linkResponse(data, request) {
  if (request.url.includes('/board?')) return { selection: new URL(request.url, 'https://watch.invalid').searchParams.get('selection'), band: { runs: [] }, counts: {}, rows: [], done_rows: [] };
  if (request.url.startsWith('/api/naver-auto/links/pending')) return data;
  return {};
}

test('접힌 짝 확인 카드는 확정 권한이 있어도 초기 이관 조회에 pending을 섞지 않는다', async () => {
  for (const me of [{scope:'ALL'}, {scope:'ALL',owner_verification:true,verified_linking:true}]) {
    let finishAccounts;
    const run = launch({me,respond:request => request.url.includes('/accounts?') ?
      new Promise(resolve => { finishAccounts = resolve; }) : pending([linkFixture()])});
    await flush();
    assert.equal(run.requests.filter(request => request.url.includes('/accounts?')).length,1);
    assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
    finishAccounts(inventory()); await flush();
    assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
  }
});

test('짝 확인 펼치기는 진행 중 이관 조회 뒤 한 번만 시작하고 같은 범위의 성공 자료를 재사용한다', async () => {
  let finishAccounts, finishLinks;
  const run = launch({me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request => {
    if (request.url.includes('/accounts?')) return new Promise(resolve => { finishAccounts = resolve; });
    return new Promise(resolve => { finishLinks = resolve; });
  }});
  await flush();
  const toggle = run.elements.get('linksToggle');
  toggle.dispatch('click'); toggle.dispatch('click'); toggle.dispatch('click'); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
  assert.equal(toggle.getAttribute('aria-expanded'),'true');
  finishAccounts(inventory()); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,1);
  toggle.dispatch('click'); toggle.dispatch('click'); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,1);
  finishLinks(pending([linkFixture()])); await flush();
  assert.match(run.text('linksBody'),/목표 업체/);
  toggle.dispatch('click'); toggle.dispatch('click'); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,1);
  assert.equal(run.elements.get('linksBody').hidden,false);
});

test('이관 응답을 기다리다 접으면 보류한 짝 조회를 보내지 않는다', async () => {
  let finishAccounts;
  const run = launch({me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request =>
    request.url.includes('/accounts?') ? new Promise(resolve => { finishAccounts = resolve; }) : pending()});
  await flush();
  run.elements.get('linksToggle').dispatch('click'); run.elements.get('linksToggle').dispatch('click');
  finishAccounts(inventory()); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
  assert.equal(run.elements.get('linksToggle').getAttribute('aria-expanded'),'false');
  run.elements.get('linksToggle').dispatch('click'); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,1);
});

test('업체 짝 주소도 이관 완료 뒤 조회하며 보류 중 범위 변경은 최신 담당 범위만 요청한다', async () => {
  const accounts = [];
  const run = launch({screen:'links?possibility_id=1',me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request => {
    if (request.url.includes('/accounts?')) return new Promise(resolve => { accounts.push(resolve); });
    return pending([linkFixture(),linkFixture({possibility_id:2,name:'범위 밖 업체',ref:'out'})]);
  }});
  await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
  run.scope('me'); await flush();
  accounts[0](inventory()); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
  accounts[1](inventory()); await flush();
  assert.deepEqual(run.requests.filter(request => request.url.includes('/links/pending')).map(request => request.url),
    ['/api/naver-auto/links/pending?selection=me']);
  assert.match(run.text('linksBody'),/목표 업체/);
  assert.doesNotMatch(run.text('linksBody'),/범위 밖 업체/);
});

test('이관 완료를 기다리는 짝 조회는 다른 화면으로 이동하면 시작하지 않는다', async () => {
  let finishAccounts;
  const run = launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request =>
    request.url.includes('/accounts?') ? new Promise(resolve => { finishAccounts = resolve; }) : linkResponse(pending(),request)});
  await flush(); run.navigate(''); await flush();
  finishAccounts(inventory()); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
  assert.equal(run.text('linksBody'),'');
});

test('짝 조회 대기 중 하위 표를 바꾸면 새 이관 확인 뒤 열린 카드 조회를 이어간다', async () => {
  const accounts=[];
  const run=launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request =>
    request.url.includes('/accounts?') ? new Promise(resolve => accounts.push(resolve)) : pending([linkFixture()])});
  await flush(); run.elements.get('inventoryAccountsTab').dispatch('click'); await flush();
  accounts[0](inventory()); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,0);
  accounts[1](inventory()); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/links/pending')).length,1);
  assert.match(run.text('linksBody'),/목표 업체/);
});

test('펼친 짝 조회의 실패는 수동 재시도로 회복하며 이관 권한 거절 뒤 보류 조회는 취소한다', async () => {
  let tries = 0;
  const run = launch({me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request => {
    if (request.url.includes('/accounts?')) return inventory();
    if (++tries === 1) throw new Error('synthetic network only');
    return pending([linkFixture()]);
  }});
  await flush(); run.elements.get('linksToggle').dispatch('click'); await flush();
  assert.match(run.text('linksBody'),/짝 목록을 불러오지 못했습니다/);
  run.buttons('linksBody').find(button => button.textContent === '다시 불러오기').dispatch('click'); await flush();
  assert.equal(tries,2); assert.match(run.text('linksBody'),/목표 업체/);
  const denied = launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},
    status:request => request.url.includes('/accounts?') ? 403 : 200,respond:request =>
      request.url.includes('/accounts?') ? {error:'not-visible'} : pending([linkFixture()])});
  await flush();
  assert.equal(denied.requests.filter(request => request.url.includes('/links/pending')).length,0);
  assert.equal(denied.text('linksBody'),'');
});

test('이관 두 표는 활성 영역만 100행을 만들고 전체 검색·정렬·잔액과 독립 페이지를 유지한다', async () => {
  const rows = Array.from({length:205}, (_, index) => fixture({ad_account_no:String(700+index),account_name:'합성 계정 '+index,
    collection:{bizmoney:index+1}}));
  const coverage = {ready:true,total:121,matched:121,missing:0,items:Array.from({length:121},(_,index) =>
    ({possibility_id:index+1,company_name:'대조 업체 '+index,workflow:'진행중',state:'matched'}))};
  const run = launch({data:inventory(rows,coverage)}); await flush();
  assert.equal(run.elements.get('inventoryRows').children.length,0);
  assert.equal(run.elements.get('coverageRows').children.length,100);
  assert.match(run.text('coveragePages'),/현재 1~100 \/ 총 121업체/);
  run.buttons('coveragePages').find(button => button.textContent === '다음').dispatch('click');
  assert.equal(run.elements.get('coverageRows').children.length,21);
  assert.match(run.text('coveragePages'),/현재 101~121 \/ 총 121업체/);
  const coverageSearch = run.elements.get('coverageSearch'); coverageSearch.value='대조 업체 120'; coverageSearch.dispatch('input');
  assert.match(run.text('coverageRows'),/대조 업체 120/);
  assert.equal(run.text('coverageSearchStatus'),'검색 결과 1 / 121업체');
  assert.match(run.text('coveragePages'),/현재 1~1 \/ 총 1업체/);
  coverageSearch.value=''; coverageSearch.dispatch('input');
  await showAccounts(run);
  assert.equal(run.elements.get('coverageRows').children.length,0);
  assert.equal(run.elements.get('inventoryRows').children.length,100);
  assert.match(run.text('inventoryPages'),/현재 1~100 \/ 총 205계정/);
  assert.match(run.text('inventoryBalance'),/합계 : 21,115원.*확인 205 \/ 205계정/);
  assert.equal(run.elements.get('inventoryRows').children[0].getAttribute('data-account'),'904');
  const first = run.elements.get('inventoryRows').children[0];
  const detail = tree(first).find(element => element.tagName === 'DETAILS'); detail.open = true;
  run.buttons('inventoryPages').find(button => button.textContent === '다음').dispatch('click');
  assert.match(run.text('inventoryPages'),/현재 101~200 \/ 총 205계정/);
  assert.equal(run.elements.get('inventoryRows').children[0].getAttribute('data-account'),'804');
  run.buttons('inventoryPages').find(button => button.textContent === '이전').dispatch('click');
  assert.equal(run.elements.get('inventoryRows').children[0],first);
  assert.equal(detail.open,true);
  const search = run.elements.get('inventorySearch'); search.value='700'; search.dispatch('input');
  assert.equal(run.elements.get('inventoryRows').children.length,1);
  assert.equal(run.elements.get('inventoryRows').children[0].getAttribute('data-account'),'700');
  assert.match(run.text('inventoryBalance'),/합계 : 1원.*확인 1 \/ 1계정/);
  assert.match(run.text('inventoryPages'),/현재 1~1 \/ 총 1계정/);
  assert.equal(run.requests.filter(request => request.url.includes('/accounts?')).length,2,'검색과 페이지 이동은 서버를 추가 조회하지 않는다');
  assert.equal(run.requests.filter(request => request.method !== 'GET').length,0);
});

test('동일 범위 새 조회는 마지막 페이지를 줄인 총수에 맞추고 서버 필터·범위 변경은 첫 페이지로 돌아간다', async () => {
  let count = 205;
  const run = launch({respond:request => inventory(Array.from({length:request.url.includes('workflow=all') ? count : 115},
    (_,index) => fixture({ad_account_no:String(700+index),collection:{bizmoney:1}})))});
  await flush(); await showAccounts(run);
  run.buttons('inventoryPages').find(button => button.textContent === '다음').dispatch('click');
  run.buttons('inventoryPages').find(button => button.textContent === '다음').dispatch('click');
  assert.match(run.text('inventoryPages'),/현재 201~205 \/ 총 205계정/);
  count=105; run.elements.get('inventoryReload').dispatch('click'); await flush();
  assert.match(run.text('inventoryPages'),/현재 101~105 \/ 총 105계정/);
  const workflow=run.elements.get('inventoryWorkflow'); workflow.value='진행중'; workflow.dispatch('change'); await flush();
  assert.match(run.text('inventoryPages'),/현재 1~100 \/ 총 115계정/);
  run.buttons('inventoryPages').find(button => button.textContent === '다음').dispatch('click');
  run.scope('me');
  assert.equal(run.text('inventoryPages'),'');
  await flush(); assert.match(run.text('inventoryPages'),/현재 1~100 \/ 총 115계정/);
});

test('검색 전 보관한 페이지 버튼은 두 표의 새 검색 결과를 이동시키지 않는다', async () => {
  const rows=Array.from({length:205},(_,index) => fixture({ad_account_no:String(700+index),
    account_name:(index<121?'GroupA':'GroupB')+' '+index}));
  const coverage={ready:true,total:205,matched:205,missing:0,items:rows.map((row,index) =>
    ({possibility_id:index+1,company_name:row.account_name,state:'matched'}))};
  const run=launch({data:inventory(rows,coverage)}); await flush();
  for (const panel of ['coverage','inventory']) {
    if (panel==='inventory') await showAccounts(run);
    const stale=run.buttons(panel+'Pages').find(button => button.textContent==='다음');
    const search=run.elements.get(panel+'Search'); search.value='GroupA'; search.dispatch('input');
    stale.dispatch('click');
    assert.match(run.text(panel+'Pages'),/현재 1~100 \/ 총 121/);
    run.buttons(panel+'Pages').find(button => button.textContent==='다음').dispatch('click');
    assert.match(run.text(panel+'Pages'),/현재 101~121 \/ 총 121/);
  }
});

test('같은 snapshot unchanged 재검증으로 하위 표를 바꿔도 활성 표를 처음 생성한다', async () => {
  const data=inventory([fixture()],{ready:true,total:1,matched:1,missing:0,items:[{possibility_id:1,company_name:'대조 합성 업체',state:'matched'}]});
  const run=launch({respond:request => ({version:1,mode:request.url.includes('view_cursor=')?'unchanged':'full',
    cursor:'synthetic_cursor',base_cursor:request.url.includes('view_cursor=')?'synthetic_cursor':null,
    checked_at:new Date().toISOString(),data:request.url.includes('view_cursor=')?null:data,rows:null})});
  await flush(); assert.equal(run.elements.get('inventoryRows').children.length,0);
  await showAccounts(run); assert.match(run.text('inventoryRows'),/합성 계정/);
  assert.equal(run.elements.get('coverageRows').children.length,0);
  run.elements.get('inventoryCoverageTab').dispatch('click'); await flush();
  assert.match(run.text('coverageRows'),/대조 합성 업체/);
  assert.equal(run.elements.get('inventoryRows').children.length,0);
});

test('실관리 대조의 짝 확인은 선택 업체만 열고 전체보기로 제한을 해제한다', async () => {
  const data = pending([linkFixture(), linkFixture({ref:'other-ref', possibility_id:2, name:'다른 업체'})], [
    {decision_id: 1, possibility_id: 1, name: '목표 업체', decision: 'confirmed', detail_available: false},
    {decision_id: 2, possibility_id: 2, name: '다른 업체', decision: 'confirmed', detail_available: false}
  ]);
  const run = launch({ me: {scope:'ALL', owner_verification:true, verified_linking:true}, respond: request => {
    if (request.url.includes('/accounts?')) return inventory([], {ready:true,total:1,matched:0,missing:1,items:[
      {possibility_id:1,company_name:'목표 업체',state:'candidate_pending',candidate_count:1}
    ]});
    return linkResponse(data, request);
  } });
  await flush();
  run.buttons('coverageRows').find(button => button.textContent === '짝 확인 열기').dispatch('click');
  await flush();
  assert.equal(run.location.pathname + run.location.search, '/naver/links?possibility_id=1');
  assert.match(run.text('linksBody'), /목표 업체/);
  assert.doesNotMatch(run.text('linksBody'), /다른 업체/);
  assert.equal(run.text('links-n'), '1건');
  assert.match(run.text('confirmAuto'), /1곳/);
  assert.equal(run.buttons('linksBody').filter(button => button.textContent === '목표 업체').length, 0);
  run.elements.get('linksShowAll').dispatch('click');
  await flush();
  assert.equal(run.location.search, '');
  assert.match(run.text('linksBody'), /다른 업체/);
  assert.equal(run.text('links-n'), '2건');
});

test('원천 미수락과 선택 업체 누락은 확정 불가 이유를 표시하고 전체 업체로 넓히지 않는다', async () => {
  for (const [sourceState, label] of [['missing', /수락된 원천 자료가 없습니다/], ['stale', /원천 자료가 오래되어/],
    ['failed', /원천 자료 수신 실패/], ['accepted', /선택한 업체의 확인할 짝·판단이 없습니다/]]) {
    const data = pending([linkFixture({possibility_id:2, name:'다른 업체'})], [], {source_state:sourceState});
    const run = launch({screen:'links?possibility_id=1', me:{scope:'ALL',owner_verification:true,verified_linking:true},
      respond: request => linkResponse(data, request)});
    await flush();
    assert.match(run.text('linksBody'), label);
    assert.doesNotMatch(run.text('linksBody'), /다른 업체|아직 짝 맞추기를 받지/);
    assert.equal(run.elements.get('confirmAuto').hidden, true);
    run.elements.get('confirmAuto').dispatch('click');
    assert.equal(run.requests.filter(request => request.method === 'POST').length, 0);
  }
});

test('업체 제한 일괄확정은 50건 뒤 최신 ref로 남은 최초 동의 pair만 확정한다', async () => {
  const original = Array.from({length:53}, (_, index) => linkFixture({ref:'old-'+index, pair_key:'pair-'+index}));
  let writes = 0;
  const run = launch({screen:'links?possibility_id=1',me:{scope:'ALL',owner_verification:true,verified_linking:true},
    respond: request => {
      if (request.method === 'POST') { writes++; return {decided:request.body.refs.length}; }
      const rows = writes === 0 ? original.concat(linkFixture({ref:'out-of-filter',pair_key:'other',possibility_id:2})) :
        writes === 1 ? original.slice(50).map((row,index) => Object.assign({},row,{ref:'fresh-'+index})).concat(
          linkFixture({ref:'newcomer',pair_key:'newcomer'})) : [];
      return linkResponse(pending(rows), request);
    }});
  await flush();
  run.elements.get('confirmAuto').dispatch('click');
  run.elements.get('confirmAuto').dispatch('click');
  await flush();
  assert.equal(run.requests.filter(request => request.method === 'POST').length, 0, '확인창의 「확정」 전에는 보내지 않는다(D5)');
  assert.match(run.text('ca-sub'), /53곳/);
  run.elements.get('ca-ok').dispatch('click');
  run.elements.get('ca-ok').dispatch('click');
  await flush();
  const posts = run.requests.filter(request => request.method === 'POST');
  assert.equal(posts.length, 2);
  assert.equal(posts[0].body.refs.length, 50);
  assert.deepEqual(posts[1].body.refs, ['fresh-0','fresh-1','fresh-2']);
  assert.match(run.text('toast'), /53곳 연결을 확정/);
});

test('일괄확정 중 남은 pair·권한·원천이 바뀌거나 pair 키가 없으면 첫 묶음 뒤 중단한다', async () => {
  for (const change of ['pair', 'permission', 'state', 'source', 'legacy']) {
    const original = Array.from({length:51}, (_, index) => linkFixture({ref:'old-'+index,
      pair_key:change === 'legacy' ? undefined : 'pair-'+index}));
    let writes = 0;
    const run = launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request => {
      if (request.method === 'POST') { writes++; return {decided:50}; }
      const fresh = Object.assign({}, original[50], {ref:'fresh-50'});
      if (change === 'pair') fresh.pair_key = 'changed-account';
      if (change === 'permission') fresh.can_confirm = false;
      if (change === 'state') fresh.state = 'candidate';
      return linkResponse(pending(writes ? [fresh] : original, [],
        {source_state:writes && change === 'source' ? 'stale' : 'accepted'}), request);
    }});
    await flush(); run.elements.get('confirmAuto').dispatch('click'); run.elements.get('ca-ok').dispatch('click'); await flush();
    assert.equal(run.requests.filter(request => request.method === 'POST').length, 1, change);
    assert.match(run.text('toast'), /50곳 확정 후 중단.*최신 목록/);
  }
});

test('선택 업체의 일괄·개별 확정은 상단 담당 범위를 같은 계약으로 보낸다', async () => {
  const run = launch({screen:'links?possibility_id=1',me:{scope:'ALL',owner_verification:true,verified_linking:true},
    respond:request => linkResponse(pending([linkFixture(),linkFixture({possibility_id:2,ref:'other-ref'})]), request)});
  await flush(); run.scope('me'); await flush();
  assert.ok(run.requests.some(request => request.url === '/api/naver-auto/links/pending?selection=me'));
  run.elements.get('confirmAuto').dispatch('click'); run.elements.get('ca-ok').dispatch('click'); await flush();
  assert.deepEqual(run.requests.filter(request => request.method === 'POST').map(request => request.body),
    [{refs:['synthetic-ref-1'],selection:'me'}]);
  run.buttons('linksBody').find(button => button.textContent === '이 계정 맞음').dispatch('click'); await flush();
  assert.deepEqual(run.requests.filter(request => request.method === 'POST')[1].body,
    {refs:['synthetic-ref-1'],selection:'me'});
});

test('일반 모드의 담당 범위별 확정·거절은 기존 refs 전용 저장 계약을 유지한다', async () => {
  const run = launch({screen:'links',me:{scope:'ALL'},respond:request => linkResponse(pending([
    linkFixture({can_reject:true,detail_available:true})],[],{source:'legacy'}),request)});
  await flush(); run.scope('me'); await flush();
  run.buttons('linksBody').find(button => button.textContent === '이 계정 맞음').dispatch('click'); await flush();
  run.buttons('linksBody').find(button => button.textContent === '아님').dispatch('click'); await flush();
  assert.deepEqual(run.requests.filter(request => request.method === 'POST').map(request => request.body),
    [{refs:['synthetic-ref-1']},{refs:['synthetic-ref-1']}]);
});

test('범위·페이지 이동 뒤 늦은 짝 응답과 기존 버튼은 화면이나 확정 대상을 되살리지 않는다', async () => {
  let release, calls = 0;
  const run = launch({screen:'links?possibility_id=1',me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request => {
    if (request.url.includes('/links/pending')) {
      calls++;
      if (calls === 2) return new Promise(resolve => { release = resolve; });
      return pending([linkFixture()]);
    }
    return linkResponse({},request);
  }});
  await flush();
  const old = run.buttons('linksBody').find(button => button.textContent === '이 계정 맞음');
  run.scope('me'); await flush();
  old.dispatch('click');
  run.navigate('links?possibility_id=2'); await flush();
  release(pending([linkFixture({name:'늦은 업체'})])); await flush();
  old.dispatch('click');
  run.elements.get('confirmAuto').dispatch('click');
  assert.equal(run.requests.filter(request => request.method === 'POST').length,0);
  assert.doesNotMatch(run.text('linksBody'),/늦은 업체|목표 업체/);
});

test('일괄확정 재조회 중 페이지가 바뀌면 다음 묶음과 늦은 화면 갱신을 보내지 않는다', async () => {
  const rows = Array.from({length:51},(_,index) => linkFixture({ref:'old-'+index,pair_key:'pair-'+index}));
  let release, writes = 0;
  const run = launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},respond:request => {
    if (request.method === 'POST') { writes++; return {decided:50}; }
    if (request.url.includes('/links/pending') && writes) return new Promise(resolve => {release=resolve;});
    if (request.url.includes('/accounts?')) return inventory();
    return linkResponse(pending(rows),request);
  }});
  await flush(); run.elements.get('confirmAuto').dispatch('click'); run.elements.get('ca-ok').dispatch('click'); await flush();
  run.navigate(''); await flush();   // 짝 확인은 이관 현황 안 — 다른 페이지 = 관제 첫 화면
  release(pending([Object.assign({},rows[50],{ref:'fresh-50'})])); await flush();
  assert.equal(writes,1);
  assert.equal(run.text('linksBody'),'');
  assert.doesNotMatch(run.text('toast'),/확정/);
});

test('일괄 확정 확인창은 취소하면 보내지 않고, 창을 연 뒤 범위가 바뀌면 확정하지 않는다(D5)', async () => {
  const run = launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},
    respond:request => linkResponse(pending([linkFixture()]),request)});
  await flush();
  assert.equal(run.elements.get('s-transfers').classList.contains('on'), true, '/naver/links 는 이관 현황 화면');
  run.elements.get('confirmAuto').dispatch('click');
  assert.equal(run.elements.get('m-confirm-auto').classList.contains('on'), true);
  assert.match(run.text('ca-sub'), /1곳을 한 번에/);
  run.elements.get('m-confirm-auto').dispatch('click', {target: run.elements.get('m-confirm-auto')});
  run.elements.get('ca-ok').dispatch('click'); await flush();
  assert.equal(run.requests.filter(request => request.method === 'POST').length, 0, '닫은 창의 확정은 보내지 않는다');
  run.elements.get('confirmAuto').dispatch('click');
  run.scope('me'); await flush();
  run.elements.get('ca-ok').dispatch('click'); await flush();
  assert.equal(run.requests.filter(request => request.method === 'POST').length, 0, '범위가 바뀐 뒤의 확정은 보내지 않는다');
  // 화면 이동 없이 창을 연 동안 짝 목록이 새로 오면(한 줄 확정 뒤 다시 받음 · 늦은 응답) 일괄 확정은 보내지 않는다
  const moved = launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},
    respond:request => request.method === 'POST' ? {decided:1} :
      linkResponse(pending([linkFixture(), linkFixture({ref:'second-ref',pair_key:'pair-2',possibility_id:2,name:'다른 업체'})]),request)});
  await flush();
  moved.elements.get('confirmAuto').dispatch('click');
  moved.buttons('linksBody').find(button => button.textContent === '이 계정 맞음').dispatch('click'); await flush();
  moved.elements.get('ca-ok').dispatch('click'); await flush();
  assert.equal(moved.requests.filter(request => request.method === 'POST').length, 1, '한 줄 확정만 보내고 일괄 확정은 보내지 않는다');
  assert.match(moved.text('toast'), /짝 목록이 바뀌었습니다/);
});

test('실사용 판의 짝 판단 「거두기」는 대표에게만 보이고 사유를 실어 보낸다(D5)', async () => {
  const decisions = [{decision_id: 7, possibility_id: 1, name: '목표 업체', decision: 'confirmed', tail: '1234', decided_by: '직원가', decided_at: '2026-10-02T09:00:00+09:00', detail_available: false}];
  for (const [scope, visible] of [['ALL', true], ['MINE', false]]) {
    const run = launch({screen:'links',me:{scope,owner_verification:true,verified_linking:true,owner_actions:true},
      respond:request => request.method === 'POST' ? {revoked: 7} : linkResponse(pending([], decisions), request)});
    await flush();
    const revoke = run.buttons('linksBody').filter(button => button.textContent === '거두기');
    assert.equal(revoke.length, visible ? 1 : 0, scope);
    if (!visible) continue;
    revoke[0].dispatch('click');
    run.elements.get('mr-ok').dispatch('click'); await flush();
    assert.equal(run.requests.filter(request => request.method === 'POST').length, 0, '사유가 없으면 보내지 않는다');
    revoke[0].dispatch('click');
    run.elements.get('mr-why').value = '광고주 계정이 바뀜';
    run.elements.get('mr-ok').dispatch('click'); await flush();
    assert.deepEqual(run.requests.filter(request => request.method === 'POST').map(request => [request.url, request.body]),
      [['/api/naver-auto/links/revoke', {decision_id: 7, reason: '광고주 계정이 바뀜'}]]);
  }
  const ro = launch({screen:'links',me:{scope:'ALL',owner_verification:true,verified_linking:true},
    respond:request => linkResponse(pending([], decisions), request)});
  await flush();
  assert.equal(ro.buttons('linksBody').filter(button => button.textContent === '거두기').length, 0, '손길이 닫힌 판은 대표도 거두기 없음');
});

test('옛 📦 주소는 이관 현황 「계약만료」 거르기로, 바로 보기 단추도 같은 거르기로 연다(D9)', async () => {
  const run = launch({screen:'ended'});
  await flush();
  assert.equal(run.elements.get('s-transfers').classList.contains('on'), true);
  assert.equal(run.elements.get('inventoryCard').hidden, false);
  assert.equal(run.elements.get('inventoryWorkflow').value, '계약만료');
  assert.ok(run.requests.some(request => request.url.includes('/accounts?') &&
    request.url.includes('workflow=' + encodeURIComponent('계약만료')) && request.url.includes('view=current')));
  assert.ok(!run.requests.some(request => request.url.includes('/ended')), '옛 📦 목록 경로는 부르지 않는다');
  run.elements.get('inventoryWorkflow').value = 'all'; run.elements.get('inventoryWorkflow').dispatch('change'); await flush();
  run.elements.get('inventoryEnded').dispatch('click'); await flush();
  assert.equal(run.elements.get('inventoryWorkflow').value, '계약만료');
});

test('잘못된 업체 제한 주소는 전체 업체 자동확정으로 확대되지 않는다', async () => {
  for (const query of ['possibility_id=0','possibility_id=1&possibility_id=2','possibility_id=9007199254740992','other=1']) {
    const run = launch({screen:'links?'+query,me:{scope:'ALL',owner_verification:true,verified_linking:true},
      respond:request => linkResponse(pending([linkFixture()]),request)});
    await flush();
    assert.match(run.text('linksFilter'), /주소를 확인/);
    assert.doesNotMatch(run.text('linksBody'), /목표 업체/);
    run.elements.get('confirmAuto').dispatch('click');
    assert.equal(run.requests.filter(request => request.method === 'POST').length,0);
  }
});

test('좁은 화면의 이관 계정 카드도 원래 아홉 항목명을 보존한다', async () => {
  const run = launch({ data: inventory([fixture()]) });
  await flush();
  await showAccounts(run);
  const cells = tree(run.elements.get('inventoryRows')).filter(el => el.tagName === 'TD');
  assert.deepEqual(cells.map(el => el.getAttribute('data-label')), [
    '광고 계정 · ID', '전산 업체', '매칭 상태', '업무 단계', '담당', '수집 결과',
    '확인된 실적 · 기간', '비즈머니 · 확인 시각', '관제 관리'
  ]);
  assert.match(cells[0].textContent, /합성 계정.*ID 700/);
});

test('수집 시각은 10시 목표와 이후 계속 수집을 기존 이상 점검과 구분한다', async () => {
  const run = launch({ screen: 'settings', data: { deadline: '08:00' } });
  await flush();
  assert.match(run.text('sp-time'), /전일 실적.*00:01.*10:00.*미완료.*계속 수집/);
  assert.match(run.text('sp-time'), /기존 이상 점검.*06:30.*08:00.*별도/);
  assert.doesNotMatch(run.text('sp-time'), /10:00 까지 끝납니다/);
});

test('실관리 대조는 계정이 없는 업체와 전체 후보 수를 별도로 표시한다', async () => {
  const run = launch({ data: inventory([], { ready: true, total: 2, matched: 0, missing: 2, items: [
    { possibility_id: 1, company_name: '번호 없는 업체', workflow: '진행중', state: 'id_missing', codes: ['ID_MISSING'], candidate_count: 0, matched_account_count: 0 },
    { possibility_id: 2, company_name: '후보 일곱 업체', workflow: '사후관리', state: 'multiple_candidates', codes: ['MULTIPLE_CANDIDATES'], candidate_count: 7, matched_account_count: 0 }
  ] }) });
  await flush();
  assert.match(run.text('coverageStatus'), /실관리 2.*연결 확인 0.*확인 필요 2/);
  assert.match(run.text('coverageRows'), /번호 없는 업체.*번호 미입력/);
  assert.match(run.text('coverageRows'), /후보 일곱 업체.*후보 여러 개.*7/);
  assert.equal(run.requests.filter(r => r.method !== 'GET').length, 0);
});

test('주간 조회는 재시도와 이전 성공 기간·잔액 확인 시각을 구분한다', async () => {
  const run = launch({ data: inventory([fixture({ management: { cadence: 'weekly', excluded: true }, collection: {
    status: 'retry', stale: true, checked_at: '2026-10-02T08:30:00+09:00', last_success_at: '2026-09-27T06:50:00+09:00',
    period_start: '2026-09-20', period_end: '2026-09-26', spend: 7000, imp: 90, clk: 3,
    bizmoney: 12000, bizmoney_at: '2026-09-27T06:50:00+09:00', activity_observed: true
  } }), fixture({ ad_account_no: 701, management: { cadence: 'weekly' }, collection: { status: 'pending' } })]) });
  await flush();
  await showAccounts(run);
  const text = run.text('inventoryRows');
  assert.match(text, /재시도 대기/);
  assert.match(text, /비관리 · 일요일 7일 점검 대기/);
  assert.match(text, /이전 성공값.*2026-09-20 ~ 2026-09-26.*7,000원/);
  assert.match(text, /마지막 성공 2026.*09.*27.*06:50/);
  assert.match(text, /잔액 확인 2026.*09.*27.*06:50/);
  assert.match(text, /비관리 계정에 실적 있음 · 담당 확인/);
  assert.doesNotMatch(text, /어제|충전/);
});

test('전산 미등록·비관리와 업체 확인 필요는 수집 실패와 다른 칸에 표시한다', async () => {
  const run = launch({data:inventory([
    fixture({mapping:'no_erp_record',company_name:null,possibility_id:null,management:{cadence:'weekly'},collection:{status:'ok'}}),
    fixture({ad_account_no:'701',mapping:'unclassified',collection:{status:'failed'}})
  ])});
  await flush(); await showAccounts(run);
  const rows = run.elements.get('inventoryRows').children;
  assert.equal(rows[0].children[2].textContent, '전산 미등록 · 비관리');
  assert.equal(rows[0].children[5].textContent.startsWith('수집 완료'), true);
  assert.equal(rows[1].children[2].textContent, '업체 확인 필요');
  assert.equal(rows[1].children[5].textContent.startsWith('수집 실패'), true);
  assert.equal(run.requests.filter(request => request.method !== 'GET').length, 0);
});

test('비관리 잔액 변화는 이전 확인 시각과 비교하되 충전을 확정하지 않는다', async () => {
  const run = launch({data:inventory([fixture({management:{cadence:'weekly'},collection:{
    status:'ok',bizmoney:15000,bizmoney_at:'2026-10-04T09:00:00+09:00',
    previous_bizmoney:10000,previous_bizmoney_at:'2026-09-27T09:00:00+09:00',bizmoney_change:5000
  }})])});
  await flush();
  await showAccounts(run);
  assert.match(run.text('inventoryRows'),/이전 조회 대비 잔액 증가 5,000원/);
  assert.match(run.text('inventoryRows'),/비교 기준 2026.*09.*27.*09:00/);
  assert.match(run.text('inventoryRows'),/잔액 변화만으로 충전을 확정하지 않습니다/);
  assert.equal(run.requests.filter(r=>r.method!=='GET').length,0);
});

test('기간 재확인 상태와 정정된 원천 확인 시각은 기존 일일 수집과 분리한다', async () => {
  const run = launch({data:inventory([fixture({collection:{status:'ok',spend:50,
    period_start:'2026-10-01',period_end:'2026-10-01',checked_at:'2026-10-02T00:30:00+09:00',
    source_rechecked_at:'2026-10-02T11:00:00+09:00',revalidation:{kind:'manual_period',status:'source_wait',
      period_start:'2026-09-01',period_end:'2026-09-30',checked_at:'2026-10-02T11:05:00+09:00',
      error_code:'SOURCE_AGGREGATING'}}})])});
  await flush();
  await showAccounts(run);
  assert.match(run.text('inventoryRows'),/수동 기간 재확인 · 네이버 집계 대기/);
  assert.match(run.text('inventoryRows'),/2026-09-01 ~ 2026-09-30/);
  assert.match(run.text('inventoryRows'),/표시 실적 원천 확인 2026.*10.*02.*11:00/);
});

test('수집 중단 상태와 마지막 실제 실패 원인은 일일 조회와 재확인에서 따로 표시한다', async () => {
  const run = launch({data:inventory([fixture({collection:{status:'limited',error_code:'STATS_METRIC_MISSING',
    revalidation:{kind:'manual_period',status:'limited',error_code:'STATS_CYCLE_INVALID'}}})])});
  await flush();
  await showAccounts(run);
  const text = run.text('inventoryRows');
  assert.match(text,/수집 중단 · 관리자 확인 필요.*원인: 필수 통계 지표 확인 불가/);
  assert.match(text,/수동 기간 재확인 · 수집 중단 · 관리자 확인 필요.*원인: 통계 기준 시각 확인 불가/);
  assert.doesNotMatch(text,/네이버 통계 일부 미수신|STATS_METRIC_MISSING|STATS_CYCLE_INVALID/);
});

test('알 수 없는 수집 코드는 본문과 툴팁에 노출하지 않는다', async () => {
  for (const code of ['PRIVATE_ACCOUNT_ERROR_123', 'https://private.invalid/key', '__proto__', 'constructor']) {
    const run = launch({data:inventory([fixture({collection:{status:'limited',error_code:code,
      revalidation:{kind:'recent',status:'retry',error_code:code}}})])});
    await flush();
    await showAccounts(run);
    assert.match(run.text('inventoryRows'),/상세 원인 미확인 · 관리자 확인 필요/);
    const rendered = tree(run.elements.get('inventoryRows')).map(el => el.textContent + JSON.stringify(el.attrs || {})).join('');
    assert.equal(rendered.includes(code), false);
    assert.equal(run.requests.filter(request => request.method !== 'GET').length, 0);
  }
});

test('수집 실패 코드는 원인별 한국어 설명이며 옛 기록을 네이버 미수신으로 단정하지 않는다', async () => {
  const cases = [
    ['STATS_SHAPE_UNKNOWN', /통계 응답 형식 확인 불가/],
    ['STATS_NUMERIC_INVALID', /통계 숫자 형식 확인 불가/],
    ['STATS_ROW_ID_INVALID', /통계 캠페인 식별값 확인 불가/],
    ['STATS_DATE_INVALID', /통계 날짜 형식 확인 불가/],
    ['STATS_METRIC_MISSING', /필수 통계 지표 확인 불가/],
    ['STATS_METRIC_INVALID', /통계 지표 값 범위 확인 필요/],
    ['STATS_DATE_INCOMPLETE', /요청 기간의 날짜별 통계 확인 불가/],
    ['STATS_CYCLE_INVALID', /통계 기준 시각 확인 불가/],
    ['STATS_CYCLE_FUTURE', /통계 기준 시각이 현재보다 미래/],
    ['STATS_CAMPAIGNS_INVALID', /캠페인 목록 확인 불가/],
    ['STATS_PERIOD_OPEN', /아직 닫히지 않은 조회 기간/],
    ['REQUEST_BUDGET', /회차 호출·시간 한도 도달/],
    ['REQUEST_CALL_CAP', /회차 호출 횟수 한도 도달/],
    ['REQUEST_DEADLINE', /회차 조회 시간 한도 도달/],
    ['RATE', /조회 요청 제한 응답/],
    ['NETWORK', /통신 연결 실패/],
    ['SERVER', /조회 서버 오류 응답/],
    ['BAD_REQUEST', /조회 요청 형식 확인 필요/],
    ['NOT_FOUND', /조회 대상 확인 불가/],
    ['BAD_RESPONSE', /조회 응답 확인 불가/],
    ['MISMATCH', /조회 대상과 응답 대상 불일치/],
    ['OTHER', /조회 오류 분류 확인 필요/],
    ['STATS_INCOMPLETE', /통계 완결성 확인 불가 · 상세 원인 미분류/],
    ['STATS_SHAPE', /통계 응답 형식 확인 필요/],
    ['RETRY_EXHAUSTED', /연속 재시도 4회 소진 · 기존 기록에 상세 원인 없음/]
  ];
  const run = launch({data:inventory(cases.map(([code], index) => fixture({ad_account_no:String(700 + index),
    collection:{status:'limited',error_code:code}})))});
  await flush();
  await showAccounts(run);
  const rows = tree(run.elements.get('inventoryRows')).filter(el => el.tagName === 'TR');
  cases.forEach(([code, expected], index) => {
    assert.match(rows[index].textContent, expected);
    assert.doesNotMatch(rows[index].textContent, /네이버 통계 일부 미수신|상세 원인 미확인/);
    assert.equal(rows[index].textContent.includes(code), false);
    assert.match(rows[index].textContent, /관리자|재시도 상태/);
  });
});

test('직원 관제는 관리 상태만 표시하고 포함·제외·수동조회 업무 버튼을 만들지 않는다', async () => {
  const data = inventory([fixture({ management: { cadence: 'daily', stage_revision: 'r1', excluded: false, can_manage: true, can_collect: true } }),
    fixture({ ad_account_no: 701, management: { cadence: 'blocked', can_manage: false, can_collect: false } }),
    fixture({ ad_account_no: 702, management: { cadence: 'daily', can_manage: 'true', can_collect: 1 } })]);
  const run = launch({ me: {scope:'MINE',owner_verification:true,verified_linking:true}, data });
  await flush();
  await showAccounts(run);
  const actions = run.buttons('inventoryRows');
  assert.deepEqual(actions.map(x => x.textContent), []);
  assert.match(run.text('inventoryRows'), /실관리 · 일일 점검.*자동 수집/);
  run.elements.get('managementSave').dispatch('click');
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
  run.elements.get('managementReason').value = '휴면 확인';
  run.elements.get('managementSave').dispatch('click');
  await flush();
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
});

test('기간 재확인은 닫힌 날짜 최대 31일과 현재 계정 권한을 검사하고 한 번만 요청한다', async () => {
  let release;
  const data = inventory([fixture({ management: { cadence: 'daily', can_collect: true } }),
    fixture({ ad_account_no: '701', management: { cadence: 'daily', can_collect: false } }),
    fixture({ ad_account_no: '702', possibility_id: null, management: { cadence: 'daily', can_collect: true } })]);
  const run = launch({ me:{scope:'ALL',owner_verification:true,verified_linking:true},
    respond: request => request.method === 'GET' ? data : new Promise(resolve => { release = resolve; }) });
  await flush();
  await showAccounts(run);
  const buttons = run.buttons('inventoryRows').filter(button => button.textContent === '기간 재확인');
  assert.equal(buttons.length, 1);
  const recovery = tree(run.elements.get('inventoryRows')).find(el => el.tagName === 'DETAILS' && el.className === 'collection-recovery');
  assert.ok(recovery);
  assert.notEqual(recovery.getAttribute('open'), '');
  assert.equal(run.buttons('inventoryRows').some(button => /관제 포함|관제 제외/.test(button.textContent)), false);
  buttons[0].dispatch('click');
  assert.match(run.text('periodDescription'), /합성 업체.*700/);
  const start = run.elements.get('periodStart'), end = run.elements.get('periodEnd'), save = run.elements.get('periodSave');
  for (const [a, b] of [['', '2026-01-01'], ['2026-02-30', '2026-03-01'], ['2026-01-02', '2026-01-01'],
    ['2026-01-01', '2026-02-01'], ['9999-01-01', '9999-01-02']]) {
    start.value = a; end.value = b; save.dispatch('click');
    assert.equal(run.requests.filter(request => request.method === 'POST').length, 0);
  }
  start.value = '2026-01-01'; end.value = '2026-01-31'; save.dispatch('click'); save.dispatch('click'); await flush();
  assert.deepEqual(run.requests.filter(request => request.method === 'POST'), [{ url: '/api/naver-auto/management/collect', method: 'POST',
    body: { ad_account_no: '700', possibility_id: 1, period_start: '2026-01-01', period_end: '2026-01-31' } }]);
  release({}); await flush();
  assert.match(run.text('toast'), /기간 재확인 요청.*완료.*수집 결과/);
  assert.equal(run.elements.get('m-period-recheck').classList.contains('on'), false);
});

test('범위가 바뀌면 기간 재확인 창과 이전 계정 버튼은 요청할 수 없다', async () => {
  const run = launch({ me:{scope:'ALL',owner_verification:true,verified_linking:true},
    data: inventory([fixture({ management: { cadence: 'weekly', can_collect: true } })]) });
  await flush();
  await showAccounts(run);
  const button = run.buttons('inventoryRows').find(item => item.textContent === '기간 재확인');
  assert.ok(button); button.dispatch('click');
  run.elements.get('periodStart').value = '2026-01-01'; run.elements.get('periodEnd').value = '2026-01-03';
  run.scope('person:2'); await flush();
  run.elements.get('periodSave').dispatch('click'); button.dispatch('click'); await flush();
  assert.equal(run.elements.get('m-period-recheck').classList.contains('on'), false);
  assert.equal(run.requests.filter(request => request.method === 'POST').length, 0);
});

function reportFixture(overrides = {}) {
  const period = {kind:'monthly',start:'2026-09-01',end:'2026-09-30'};
  const base = {report_id:9,revision_no:1,revision_fingerprint:'fixed-report',possibility_id:1,
    period_key:'monthly:2026-09-01:2026-09-30',company_name:'합성 보고 업체',status:'ready',
    generated_at:'2026-10-03T10:00:00+09:00',checked_at:'2026-10-04T10:00:00+09:00',owner:{name:'합성 담당자'},
    scope:{kind:'account',account_key:'account-1',ad_account_no:'700',account_name:'합성 계정',
      accounts:[{account_key:'account-1',ad_account_no:'700',account_name:'합성 계정'}]},
    payload:{format_version:2,period,totals:{},ratios:{},coverage:{},missing:[],missing_count:0,
      details:{status:'available',daily:[],briefing:[]}}};
  const payload = {...base.payload,...overrides.payload};
  if (Array.isArray(overrides.payload?.missing) && !Object.hasOwn(overrides.payload,'missing_count')) payload.missing_count = payload.missing.length;
  return {...base,...overrides,payload};
}
function reportList(reports, request, overrides = {}) {
  const query = new URL(request.url,'https://watch.invalid').searchParams;
  return {selection:query.get('selection') || 'all',period:reports[0]?.payload.period || reportFixture().payload.period,
    total:reports.length,page:0,page_size:20,next_page:null,unlinked_companies:0,
    schedule:{weekly:'월요일 10:00',monthly:'매월 3일 10:00',timezone:'Asia/Seoul'},
    rows:reports.map(report => ({report_id:report.report_id,revision_no:report.revision_no,
      possibility_id:report.possibility_id,company_name:report.company_name,status:report.status,
      generated_at:report.generated_at,owner:report.owner,workflow:'진행중',...report.scope})),...overrides};
}
function reportResponse(reports, request, overrides = {}) {
  if (request.url.includes('/reports/detail?')) {
    const id = Number(new URL(request.url,'https://watch.invalid').searchParams.get('report_id'));
    assert.ok(reports.some(report => report.report_id === id), '저장된 판만 상세로 요청해야 합니다');
    return reports.find(report => report.report_id === id);
  }
  assert.match(request.url,/\/reports\/accounts\?/);
  return reportList(reports,request,overrides);
}
async function showReport(run, index = 0) {
  await flush();
  run.elements.get('reportMonthly').dispatch('click'); await flush();
  const button = run.buttons('reportsRows').filter(item => item.textContent === '보고서 보기')[index];
  assert.ok(button, '계정 목록에서 저장된 보고서 상세를 열 수 있어야 합니다');
  button.dispatch('click'); await flush();
  assert.equal(run.elements.get('reportDetail').hidden,false);
  assert.equal(run.elements.get('s-reports').classList.contains('view-unverified'),false);
}

test('보고서는 계정 목록에서 기간·부분합·누락 상세를 열며 게시나 송신을 하지 않는다', async () => {
  const report = reportFixture({
    report_id: 9, company_name: '합성 보고 업체', status: 'partial', review_status: 'needs_staff_review', can_review: false,
    generated_at: '2026-10-03T10:00:00+09:00', payload: {
      period: { kind: 'monthly', start: '2026-09-01', end: '2026-09-30' }, totals: { spend: 123000, impressions: 1000, clicks: 20, conversions: null },
      ratios: { ctr: 2, cpc: 6150, roas: null }, coverage: { basic_complete: false, expected_account_days: 30, basic_complete_account_days: 29, conversion_complete_account_days: 0 },
      missing: [{ day: '2026-09-03', account_index: 1, reason: 'metrics_incomplete', metrics: ['spend'] }]
    }
  });
  const run = launch({screen:'reports',respond:req => reportResponse([report],req)});
  await flush();
  assert.ok(run.requests.some(r => r.url === '/api/naver-auto/reports/accounts?selection=all&kind=weekly&page=0&view_sync=1'));
  assert.match(run.text('reportsSchedule'), /월요일 10:00.*매월 3일 10:00.*한국시간/);
  assert.match(run.text('reportsRows'), /합성 보고 업체.*2026-09-01 ~ 2026-09-30.*부분 집계/);
  await showReport(run);
  assert.ok(run.requests.some(r => r.url === '/api/naver-auto/reports/detail?report_id=9&account_key=account-1'));
  assert.match(run.text('reportDetail'), /월간 보고서.*2026-09-01 ~ 2026-09-30/);
  assert.match(run.text('reportDetail'), /광고비.*123,000원.*확인된 범위 · 전체 수치 아님/);
  assert.match(run.text('reportDetail'), /누락 1.*2026-09-03.*일부 지표 미수신.*광고비/);
  assert.match(run.text('reportDetail'), /다운로드는 발송이 아닙니다/);
  assert.ok(!run.buttons('reportDetail').some(button => /검토 승인|검토 보류|게시|발송/.test(button.textContent)));
  assert.equal(run.requests.filter(r => r.method !== 'GET').length, 0);
});

test('보고서 정정판은 감소·명시적 0·대조 대기를 표시하고 내부 원천 지문을 노출하지 않는다', async () => {
  const report = reportFixture({
    report_id: 12, revision_no: 3, status: 'ready', can_review: true,
    validation: { status: 'pending', last_attempt_at: '2026-10-03T09:00:00+09:00',
      last_checked_at: '2026-10-02T11:00:00+09:00', pending_account_days: 2, source_snapshot_fingerprint: 'PRIVATE_FINGERPRINT' },
    change_summary: { previous_report_id: 11, changed_metrics: ['spend', 'conversions'],
      metric_deltas: { spend: -1000, conversions: 0 }, changed_days: ['2026-09-30'], completeness_changed: true, comparison_changed: true },
    payload: { totals: { spend: 0 }, period: { kind: 'monthly', start: '2026-09-01', end: '2026-09-30' } }
  });
  const run = launch({screen:'reports',respond:req => reportResponse([report],req)});
  await showReport(run);
  assert.match(run.text('reportDetail'), /3판.*원천 재확인 대기/);
  assert.match(run.text('reportDetail'), /광고비.*0원/);
  assert.match(run.text('reportDetail'), /광고비.*-1,000원.*전환.*0/);
  assert.match(run.text('reportDetail'), /2026-09-30.*완결 상태 변경/);
  assert.match(run.text('reportDetail'), /전주·전월 비교 자료 변경 · 선택 기간의 합계가 같아도 비교 수치는 달라질 수 있습니다\./);
  assert.match(run.text('reportDetail'), /남은 계정×일 2/);
  assert.doesNotMatch(run.text('reportDetail'), /PRIVATE_FINGERPRINT/);
  assert.ok(!run.buttons('reportDetail').some(button => /검토 승인|검토 보류/.test(button.textContent)));
  assert.equal(run.requests.filter(request => request.method !== 'GET').length, 0);
});

test('이전 판은 요청할 때만 페이지별 조회하며 담당 범위가 바뀐 뒤의 늦은 이력을 폐기한다', async () => {
  let release;
  const row = reportFixture({report_id:12,revision_no:3,company_name:'현재 보고 업체'});
  const run = launch({ screen: 'reports', respond: request => {
    if (request.url.includes('/reports/history?')) {
      if (request.url.includes('before_report_id=10')) return new Promise(resolve => { release = resolve; });
      return { items: [{ ...row, report_id: 10, revision_no: 2, company_name: '이전 보고 업체', can_review: true }], next_before_report_id: 10 };
    }
    return reportResponse([row],request);
  } });
  await showReport(run);
  assert.equal(run.requests.filter(request => request.url.includes('/reports/history?')).length, 0);
  const history = tree(run.elements.get('reportDetail')).find(el => el.tagName === 'DETAILS' && el.className === 'report-history');
  assert.ok(history);
  history.open = true; history.dispatch('toggle'); history.dispatch('toggle'); await flush();
  assert.equal(run.requests.filter(request => request.url.includes('/reports/history?')).length, 1);
  assert.match(run.text('reportDetail'), /당시 저장된 업체 합산 이력.*2판/);
  assert.ok(!run.buttons('reportDetail').some(button => button.textContent === '검토 승인'));
  const older = run.buttons('reportDetail').find(button => button.textContent === '더 이전 판');
  older.dispatch('click'); await flush();
  assert.ok(run.requests.some(request => request.url.includes('period_key=monthly%3A2026-09-01%3A2026-09-30') && request.url.includes('limit=20')));
  run.scope('person:2'); await flush();
  release({ items: [{ ...row, company_name: '폐기할 과거 담당 자료' }], next_before_report_id: null }); await flush();
  assert.doesNotMatch(run.text('reportsRows') + run.text('reportDetail'), /폐기할 과거 담당 자료/);
  const count = run.requests.length; older.dispatch('click'); await flush();
  assert.equal(run.requests.length, count);
  assert.equal(run.requests.filter(request => request.method !== 'GET').length, 0);
});

test('모니터링 보고서는 서버 검토 권한이 있어도 검토 상태만 읽고 승인·보류 입력을 만들지 않는다', async () => {
  for (const can_review of [true,false,'true']) {
    const report = reportFixture({can_review});
    const run = launch({screen:'reports',respond:req => reportResponse([report],req)});
    await showReport(run);
    assert.equal(run.buttons('reportDetail').some(button => /검토 승인|검토 보류/.test(button.textContent)),false);
    run.elements.get('reviewSave').dispatch('click');
    assert.equal(run.requests.filter(r => r.method === 'POST').length,0);
    run.elements.get('reviewNote').value = '기간과 누락을 확인함';
    run.elements.get('reviewSave').dispatch('click'); await flush();
    assert.equal(run.requests.filter(r => r.method !== 'GET').length,0);
    assert.match(run.text('reportDetail'),/다운로드는 발송이 아닙니다/);
  }
});

test('보고서 페이지는 담당 범위 안에서 이동하고 누락 전체 수를 잘라 표시하지 않는다', async () => {
  const run = launch({ screen: 'reports', respond: req => {
    const second = req.url.includes('&page=1');
    const report = reportFixture({company_name:second ? '다음 보고 업체' : '처음 보고 업체',payload:{
        missing_count: 130, missing_truncated: true,
        missing: Array.from({ length: 100 }, () => ({ day: '2026-09-01', account_index: 1, reason: 'day_missing' }))
      }});
    return reportResponse([report],req,{total:21,page:second ? 1 : 0,next_page:second ? null : 1});
  } });
  await showReport(run);
  assert.match(run.text('reportDetail'), /누락 130건.*앞 100건 표시 · 전체 누락 130건/);
  run.buttons('reportDetail').find(button => button.textContent === '← 보고서 목록').dispatch('click'); await flush();
  const next = run.buttons('reportsPages')[0]; next.dispatch('click'); await flush();
  assert.match(run.text('reportsRows'), /다음 보고 업체/);
  assert.match(run.text('reportsStatus'), /관리 중인 광고 계정 21개/);
  assert.match(run.text('reportsPages'), /2페이지/);
  assert.deepEqual(run.buttons('reportsPages').map(el => el.textContent), ['이전']);
  run.scope('person:2'); await flush();
  const count = run.requests.length; next.dispatch('click'); await flush();
  assert.equal(run.requests.length, count);
  // 이 fixture는 구버전 전체 응답이므로 다음 페이지부터는 기존 GET 계약으로 호환한다.
  assert.ok(run.requests.some(req => /\/reports\/accounts\?selection=all&kind=monthly&page=1$/.test(req.url)));
  assert.equal(run.requests.filter(req => req.method !== 'GET').length, 0);
});

test('관리 입력은 노출되지 않으며 범위 변경 뒤 늦은 조회 응답을 되살리지 않는다', async () => {
  const pending = [];
  const row = fixture({ management: { cadence: 'weekly', stage_revision: 'r1', can_manage: true, can_collect: true } });
  const run = launch({ respond: req => req.url.includes('selection=all') ? inventory([row]) : new Promise(resolve => pending.push(resolve)) });
  await flush();
  await showAccounts(run);
  const oldButtons = run.buttons('inventoryRows');
  assert.deepEqual(oldButtons, []);
  run.elements.get('managementReason').value = '담당 확인';
  run.scope('person:2');
  run.elements.get('managementSave').dispatch('click');
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
  assert.doesNotMatch(run.text('inventoryRows'), /합성 계정/);
  run.scope('person:3');
  pending[1](inventory([fixture({ account_name: '새 담당 계정' })])); await flush();
  pending[0](inventory([fixture({ account_name: '옛 담당 계정' })])); await flush();
  assert.match(run.text('inventoryRows'), /새 담당 계정/);
  assert.doesNotMatch(run.text('inventoryRows'), /옛 담당 계정/);
});

test('보고서의 늦은 응답은 범위 변경 뒤 복원되지 않으며 검토 입력은 동작하지 않는다', async () => {
  const pending = [];
  const report = reportFixture({report_id:1,company_name:'최초 보고서',can_review:true});
  const run = launch({ screen: 'reports', respond: req => req.url.includes('selection=all') ? reportList([report],req) : new Promise(resolve => pending.push({resolve,request:req})) });
  await flush();
  assert.deepEqual(run.buttons('reportsRows').map(button => button.textContent), ['보고서 보기']);
  run.elements.get('reviewNote').value = '검토';
  run.scope('person:2'); run.elements.get('reviewSave').dispatch('click');
  run.elements.get('reviewSave').dispatch('click');
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
  assert.equal(run.text('reportsRows'), '');
  run.scope('person:3');
  pending[1].resolve(reportList([reportFixture({company_name:'최신 보고서'})],pending[1].request)); await flush();
  pending[0].resolve(reportList([report],pending[0].request)); await flush();
  assert.match(run.text('reportsRows'), /최신 보고서/);
  assert.doesNotMatch(run.text('reportsRows'), /최초 보고서/);
  assert.equal(run.requests.filter(r => r.method !== 'GET').length, 0);
});

test('원천이 낡으면 기존 연결 숫자를 완료로 표시하지 않고 문자열은 텍스트로만 표시한다', async () => {
  const run = launch({ data: inventory([], { ready: false, total: 10, matched: 10, missing: 0, items: [
    { company_name: '<script>합성 문자열</script>', state: 'matched', codes: ['NEW_CODE'], matched_account_count: 9, candidate_count: 9 }
  ] }) });
  await flush();
  assert.match(run.text('coverageStatus'), /확정 집계 보류/);
  assert.doesNotMatch(run.text('coverageStatus'), /연결 확인 10/);
  assert.match(run.text('coverageRows'), /SOURCE_UNAVAILABLE/);
  assert.doesNotMatch(run.text('coverageRows'), /9 \/ 9/);
  assert.match(run.text('coverageRows'), /<script>합성 문자열<\/script>/);
  assert.ok(!tree(run.elements.get('coverageRows')).some(el => el.tagName === 'SCRIPT'));
});

test('관리 직원은 허용된 본인 연결만 확정하며 대표 전용 전체 조회는 호출하지 못한다', async () => {
  const links = { pairing_at: '2026-10-02T08:00:00+09:00', pairing_today: true, rows: [
    { ref: 'own-ref', possibility_id: 1, name: '본인 업체', state: 'auto', code: 'same', can_confirm: true },
    { ref: 'blocked-ref', possibility_id: 2, name: '차단 업체', state: 'blocked', can_confirm: false }
  ] };
  const run = launch({ screen: 'links', me: { scope: 'MINE', owner_verification: true, verified_linking: true }, respond: req => {
    if (req.url.includes('/board?')) return { selection: 'all', band: { runs: [] }, counts: {}, rows: [], done_rows: [] };
    if (req.url.endsWith('/links/pending')) return links;
    return {};
  } });
  await flush();
  assert.equal(run.elements.get('collectionControls').hidden, true);
  run.elements.get('collectNow').dispatch('click');
  const confirms = run.buttons('linksBody').filter(x => x.textContent === '이 계정 맞음');
  assert.equal(confirms.length, 1);
  confirms[0].dispatch('click'); await flush();
  assert.deepEqual(run.requests.filter(r => r.method === 'POST'), [{ url: '/api/naver-auto/links/confirm', method: 'POST', body: { refs: ['own-ref'] } }]);
  assert.ok(!run.requests.some(r => r.url.includes('/collection/')));
});

test('광고 사유는 계층별 원문·뜻·시각을 보존하며 미조회와 미확인 코드를 정상으로 만들지 않는다', async () => {
  const parent = { entity: 'campaign', entity_id: 'campaign-1', checked_at: '2026-10-01T07:30:00+09:00',
    status: { code: 'ELIGIBLE', meaning: '노출 가능한 상태', code_state: 'known' },
    reason: { code: 'CAMPAIGN_LIMITED_BY_BUDGET', meaning: '캠페인 예산 한도 도달', code_state: 'known' }, parents: [] };
  const items = [{
    entity: 'ad', entity_id: 'ad-1', checked_at: '2026-10-02T08:00:00+09:00',
    status: { code: ' New_Status ', meaning: '해석 미확인', code_state: 'unknown' },
    reason: { code: 'AD_DISAPPROVED', meaning: '소재 검수 보류 또는 반려', code_state: 'known' }, parents: [parent]
  }];
  const data = inventory([fixture({ structure_status: 'partial', structure_checked_at: '2026-10-02T08:00:00+09:00', ad_reason_count: 1 }),
    fixture({ ad_account_no: '701', structure_status: 'pending', ad_reason_count: 0 })]);
  const run = launch({ respond: req => req.url.includes('/accounts/reasons?') ?
    { items, total: 1, page: 0, page_size: 50, next_page: null, checked_at: '2026-10-02T08:00:00+09:00', status: 'partial' } : data });
  await flush();
  await showAccounts(run);
  assert.ok(!run.requests.some(r => r.url.includes('/accounts/reasons?')));
  const details = tree(run.elements.get('inventoryRows')).filter(el => el.tagName === 'DETAILS');
  details[0].open = true; details[0].dispatch('toggle'); await flush();
  assert.equal(run.requests.filter(r => r.url.includes('/accounts/reasons?')).length, 1);
  const text = run.text('inventoryRows');
  assert.match(text, /구조 일부 조회.*미조회 항목은 정상 판정 아님/);
  assert.match(text, /소재.*ad-1.*2026-10-02 08:00 KST.* New_Status .*해석 미확인.*알 수 없는 코드/);
  assert.match(text, /AD_DISAPPROVED.*소재 검수 보류 또는 반려/);
  assert.match(text, /상위 캠페인.*campaign-1.*2026-10-01 07:30 KST.*CAMPAIGN_LIMITED_BY_BUDGET/);
  assert.match(text, /구조 미조회.*미조회 항목은 정상 판정 아님/);
  assert.doesNotMatch(text, /STATUS_FROM_AUDIT/);
});

test('광고 사유는 50건씩 탐색하며 범위를 바꾼 뒤 늦은 응답을 되살리지 않는다', async () => {
  let pending;
  const data = inventory([fixture({ ad_reason_count: 51 })]);
  const run = launch({ respond: req => {
    if (!req.url.includes('/accounts/reasons?')) return data;
    if (req.url.includes('&page=1&')) return new Promise(resolve => { pending = resolve; });
    return { items: [], total: 51, page: 0, page_size: 50, next_page: 1 };
  } });
  await flush();
  await showAccounts(run);
  const detail = tree(run.elements.get('inventoryRows')).find(el => el.tagName === 'DETAILS');
  detail.open = true; detail.dispatch('toggle'); detail.dispatch('toggle'); await flush();
  assert.equal(run.requests.filter(r => r.url.includes('/accounts/reasons?')).length, 1);
  run.buttons('inventoryRows').find(el => el.textContent === '다음 사유').dispatch('click'); await flush();
  run.scope('person:2'); await flush();
  pending({ items: [{ entity: 'ad', entity_id: 'OLD_PRIVATE_REASON' }], total: 51, page: 1, next_page: null }); await flush();
  assert.doesNotMatch(run.text('inventoryRows'), /OLD_PRIVATE_REASON/);
  detail.dispatch('toggle'); await flush();
  assert.equal(run.requests.filter(r => r.url.includes('/accounts/reasons?')).length, 2);
  assert.equal(run.requests.filter(r => r.method !== 'GET').length, 0);
});

test('성공 기록 없는 대기를 이전 성공값이라 하지 않고 잔액 합계에 오늘 값이라고 붙이지 않는다', async () => {
  const data = inventory([fixture({ collection: { status: 'pending', stale: true, last_success_at: null, spend: null, bizmoney: null } })]);
  data.summary = { ready: true, current_total: 1, lost_count: 0, balance: { complete: true, known_sum: 12000, known_count: 1, total_count: 1 } };
  const run = launch({ data }); await flush();
  await showAccounts(run);
  assert.doesNotMatch(run.text('inventoryRows'), /이전 성공값|이전 잔액/);
  assert.match(run.text('inventoryRows'), /성공 실적 없음/);
  assert.doesNotMatch(run.text('inventorySummary'), /오늘 확인한 잔액/);
  assert.match(run.text('inventorySummary'), /계정별 확인 시각/);
});
