/* 실제 app.js의 DOM/이벤트/API 계약 회귀. 브라우저·운영 서버는 호출하지 않는다. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const page = path.join(__dirname, '../backend/naver_page');
const html = fs.readFileSync(path.join(page, 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(page, 'app.js'), 'utf8');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.events = {};
    this.value = ''; this.disabled = false; this._text = '';
    const classes = new Set();
    this.classList = { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x) };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'value') this.value = String(v); if (k === 'disabled') this.disabled = true; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, fn) { (this.events[k] ||= []).push(fn); }
  dispatch(k) { if (k === 'click' && this.disabled) return; (this.events[k] || []).forEach(fn => fn.call(this, { currentTarget: this, target: this })); }
  appendChild(el) { this.children.push(el); }
  removeChild(el) { this.children.splice(this.children.indexOf(el), 1); }
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
  const requests = [], events = {};
  const location = new URL('https://watch.invalid/naver/' + (options.screen || 'transfers'));
  const window = { addEventListener: (k, fn) => { events[k] = fn; } };
  const document = { getElementById: id => elements.get(id), createElement: tag => new Element(tag),
    createTextNode: text => ({ textContent: String(text) }), addEventListener() {}, body: { contains: () => true },
    querySelectorAll: selector => selector === '.modal' ? [...elements].filter(([id]) => id.startsWith('m-')).map(([, el]) => el) : [],
    querySelector: () => null };
  const history = { pushState: (_, __, url) => { location.href = new URL(url, location).href; } };
  const context = vm.createContext({ window, document, location, history, URL, URLSearchParams,
    sessionStorage: { getItem: () => JSON.stringify({ token: 'synthetic', exp: Date.now() + 3600000 }) },
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    fetch: async (url, init) => {
      const req = { url, method: init.method, body: init.body ? JSON.parse(init.body) : null }; requests.push(req);
      let body;
      if (url.endsWith('/me')) body = options.me || { scope: 'ALL', owner_verification: true };
      else if (options.respond) body = await options.respond(req);
      else body = options.data || inventory();
      return { status: 200, ok: true, json: async () => body };
    } });
  vm.runInContext(app, context);
  return { elements, requests, text: id => elements.get(id).textContent,
    buttons: id => tree(elements.get(id)).filter(el => el.tagName === 'BUTTON'),
    scope(value) { const el = elements.get('scope'); el.value = value; el.dispatch('change'); },
    navigate(screen) { location.pathname = '/naver/' + screen; events.popstate(); } };
}
async function flush() { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); }

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
  const text = run.text('inventoryRows');
  assert.match(text, /재시도 대기/);
  assert.match(text, /비관리 · 일요일 7일 점검 대기/);
  assert.match(text, /이전 성공값.*2026-09-20 ~ 2026-09-26.*7,000원/);
  assert.match(text, /마지막 성공 2026.*09.*27.*06:50/);
  assert.match(text, /잔액 확인 2026.*09.*27.*06:50/);
  assert.match(text, /비관리 계정에 실적 있음 · 담당 확인/);
  assert.doesNotMatch(text, /어제|충전/);
});

test('비관리 잔액 변화는 이전 확인 시각과 비교하되 충전을 확정하지 않는다', async () => {
  const run = launch({data:inventory([fixture({management:{cadence:'weekly'},collection:{
    status:'ok',bizmoney:15000,bizmoney_at:'2026-10-04T09:00:00+09:00',
    previous_bizmoney:10000,previous_bizmoney_at:'2026-09-27T09:00:00+09:00',bizmoney_change:5000
  }})])});
  await flush();
  assert.match(run.text('inventoryRows'),/이전 조회 대비 잔액 증가 5,000원/);
  assert.match(run.text('inventoryRows'),/비교 기준 2026.*09.*27.*09:00/);
  assert.match(run.text('inventoryRows'),/잔액 변화만으로 충전을 확정하지 않습니다/);
  assert.equal(run.requests.filter(r=>r.method!=='GET').length,0);
});

test('허용된 관리 변경만 필수 사유와 단계 개정값을 보내며 중복 저장을 막는다', async () => {
  let resolveWrite;
  const data = inventory([fixture({ management: { cadence: 'daily', stage_revision: 'r1', excluded: false, can_manage: true, can_collect: true } }),
    fixture({ ad_account_no: 701, management: { cadence: 'blocked', can_manage: false, can_collect: false } }),
    fixture({ ad_account_no: 702, management: { cadence: 'daily', can_manage: 'true', can_collect: 1 } })]);
  const run = launch({ respond: req => req.method === 'GET' ? data : new Promise(resolve => { resolveWrite = resolve; }) });
  await flush();
  const actions = run.buttons('inventoryRows');
  assert.deepEqual(actions.map(x => x.textContent), ['관제 제외', '지금 조회']);
  actions[0].dispatch('click');
  run.elements.get('managementSave').dispatch('click');
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
  run.elements.get('managementReason').value = '휴면 확인';
  run.elements.get('managementSave').dispatch('click');
  run.elements.get('managementSave').dispatch('click');
  await flush();
  assert.deepEqual(run.requests.filter(r => r.method === 'POST'), [{ url: '/api/naver-auto/management/update', method: 'POST',
    body: { ad_account_no: '700', stage_revision: 'r1', included: false, reason: '휴면 확인' } }]);
  resolveWrite({}); await flush();
  assert.match(run.text('toast'), /관제 제외.*광고/);
});

test('보고서는 기간·부분합·누락·담당 검토를 표시하며 게시나 송신을 하지 않는다', async () => {
  const run = launch({ screen: 'reports', data: { schedule: { weekly: '월요일 10:00', monthly: '매월 3일 10:00', timezone: 'Asia/Seoul' }, rows: [{
    report_id: 9, company_name: '합성 보고 업체', status: 'partial', review_status: 'needs_staff_review', can_review: false,
    generated_at: '2026-10-03T10:00:00+09:00', payload: {
      period: { kind: 'monthly', start: '2026-09-01', end: '2026-09-30' }, totals: { spend: 123000, impressions: 1000, clicks: 20, conversions: null },
      ratios: { ctr: 2, cpc: 6150, roas: null }, coverage: { basic_complete: false, expected_account_days: 30, basic_complete_account_days: 29, conversion_complete_account_days: 0 },
      missing: [{ day: '2026-09-03', account_index: 1, reason: 'metrics_incomplete', metrics: ['spend'] }]
    }
  }] } });
  await flush();
  assert.ok(run.requests.some(r => r.url === '/api/naver-auto/reports?selection=all'));
  assert.match(run.text('reportsSchedule'), /월요일 10:00.*매월 3일 10:00.*Asia\/Seoul/);
  assert.match(run.text('reportsRows'), /합성 보고 업체.*2026-09-01 ~ 2026-09-30.*부분 집계/);
  assert.match(run.text('reportsRows'), /확인된 광고비.*123,000원/);
  assert.match(run.text('reportsRows'), /누락 1.*2026-09-03.*일부 지표 미수신.*광고비/);
  assert.match(run.text('reportsRows'), /담당 검토 필요/);
  assert.equal(run.buttons('reportsRows').length, 0);
  assert.equal(run.requests.filter(r => r.method !== 'GET').length, 0);
});

test('보고서 검토는 capability true와 필수 메모가 있어야 내부 승인만 저장한다', async () => {
  const data = { rows: [
    { report_id: 9, status: 'ready', can_review: true, payload: {} },
    { report_id: 10, status: 'partial', can_review: false, payload: {} },
    { report_id: 11, status: 'ready', can_review: 'true', payload: {} }
  ] };
  const run = launch({ screen: 'reports', respond: req => req.method === 'GET' ? data : {} });
  await flush();
  assert.deepEqual(run.buttons('reportsRows').map(x => x.textContent), ['검토 승인', '검토 보류']);
  run.buttons('reportsRows')[0].dispatch('click');
  run.elements.get('reviewSave').dispatch('click');
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
  run.elements.get('reviewNote').value = '기간과 누락을 확인함';
  run.elements.get('reviewSave').dispatch('click');
  await flush();
  assert.deepEqual(run.requests.filter(r => r.method === 'POST'), [{ url: '/api/naver-auto/reports/review', method: 'POST',
    body: { report_id: 9, decision: 'approved', note: '기간과 누락을 확인함' } }]);
  assert.match(run.text('toast'), /검토 승인.*전송하지 않았습니다/);
});

test('보고서 페이지는 담당 범위 안에서 이동하고 누락 전체 수를 잘라 표시하지 않는다', async () => {
  const run = launch({ screen: 'reports', respond: req => {
    const second = req.url.includes('&page=1');
    return { total: 21, page: second ? 1 : 0, page_size: 20, next_page: second ? null : 1,
      rows: [{ company_name: second ? '다음 보고 업체' : '처음 보고 업체', payload: {
        missing_count: 130, missing_truncated: true,
        missing: Array.from({ length: 100 }, () => ({ day: '2026-09-01', account_index: 1, reason: 'day_missing' }))
      } }] };
  } });
  await flush();
  assert.match(run.text('reportsRows'), /누락 130건.*앞 100건 표시 · 전체 누락 130건/);
  const next = run.buttons('reportsPages')[0]; next.dispatch('click'); await flush();
  assert.match(run.text('reportsRows'), /다음 보고 업체/);
  assert.match(run.text('reportsStatus'), /보고서 21건 · 2페이지/);
  assert.deepEqual(run.buttons('reportsPages').map(el => el.textContent), ['이전 보고서']);
  run.scope('person:2'); await flush();
  const count = run.requests.length; next.dispatch('click'); await flush();
  assert.equal(run.requests.length, count);
  assert.ok(run.requests.some(req => req.url === '/api/naver-auto/reports?selection=all&page=1'));
  assert.equal(run.requests.filter(req => req.method !== 'GET').length, 0);
});

test('관리 모달·버튼과 조회 응답은 담당 범위를 바꾸면 이전 대상을 저장하지 못한다', async () => {
  const pending = [];
  const row = fixture({ management: { cadence: 'weekly', stage_revision: 'r1', can_manage: true, can_collect: true } });
  const run = launch({ respond: req => req.url.includes('selection=all') ? inventory([row]) : new Promise(resolve => pending.push(resolve)) });
  await flush();
  const oldButtons = run.buttons('inventoryRows');
  oldButtons[0].dispatch('click');
  run.elements.get('managementReason').value = '담당 확인';
  run.scope('person:2');
  run.elements.get('managementSave').dispatch('click');
  oldButtons[1].dispatch('click');
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
  assert.doesNotMatch(run.text('inventoryRows'), /합성 계정/);
  run.scope('person:3');
  pending[1](inventory([fixture({ account_name: '새 담당 계정' })])); await flush();
  pending[0](inventory([fixture({ account_name: '옛 담당 계정' })])); await flush();
  assert.match(run.text('inventoryRows'), /새 담당 계정/);
  assert.doesNotMatch(run.text('inventoryRows'), /옛 담당 계정/);
});

test('보고서의 늦은 응답·기존 검토 모달은 범위 변경 뒤 복원되지 않는다', async () => {
  const pending = [];
  const data = { rows: [{ report_id: 1, company_name: '최초 보고서', can_review: true, status: 'ready', payload: {} }] };
  const run = launch({ screen: 'reports', respond: req => req.url.includes('selection=all') ? data : new Promise(resolve => pending.push(resolve)) });
  await flush();
  const oldButton = run.buttons('reportsRows')[0]; oldButton.dispatch('click');
  run.elements.get('reviewNote').value = '검토';
  run.scope('person:2'); run.elements.get('reviewSave').dispatch('click'); oldButton.dispatch('click');
  run.elements.get('reviewSave').dispatch('click');
  assert.equal(run.requests.filter(r => r.method === 'POST').length, 0);
  assert.equal(run.text('reportsRows'), '');
  run.scope('person:3');
  pending[1]({ rows: [{ company_name: '최신 보고서', payload: {} }] }); await flush();
  pending[0](data); await flush();
  assert.match(run.text('reportsRows'), /최신 보고서/);
  assert.doesNotMatch(run.text('reportsRows'), /최초 보고서/);
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
  assert.doesNotMatch(run.text('inventoryRows'), /이전 성공값|이전 잔액/);
  assert.match(run.text('inventoryRows'), /성공 실적 없음/);
  assert.doesNotMatch(run.text('inventorySummary'), /오늘 확인한 잔액/);
  assert.match(run.text('inventorySummary'), /계정별 확인 시각/);
});
