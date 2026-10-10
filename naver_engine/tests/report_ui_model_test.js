'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const box = {window: {}};
vm.runInNewContext(fs.readFileSync('backend/naver_page/report-ui.js', 'utf8'), box);
const model = box.window.NaverReports.model;
assert.equal(model.query({kind:'weekly',anchor:'2026-09-21',q:'가게 & 123',page:2,pid:11}, 'me'),
  '/reports/accounts?selection=me&kind=weekly&anchor=2026-09-21&q=%EA%B0%80%EA%B2%8C%20%26%20123&page=2&possibility_id=11');
assert.equal(model.changeText({status:'ready',absolute:2.5,percent:20,unit:'percentage_point'}, 'ctr'), '+2.5%p');
assert.equal(model.changeText({status:'ready',absolute:100,percent:25,unit:'number'}, 'spend'), '+25%');
assert.equal(model.changeText({status:'scope_changed'}, 'spend'), '비교 범위 변경');
assert.equal(model.changeText({status:'insufficient_data'}, 'spend'), '비교 자료 부족');
assert.equal(model.changeText({status:'zero_denominator',absolute:100,percent:null}, 'spend'), '증감률 산출 불가');
const source = {report_id:1,revision_no:2,revision_fingerprint:'a',scope:{account_key:'x'},payload:{format_version:2,details:{daily:[]}}};
assert.equal(model.sameEdition(source, JSON.parse(JSON.stringify(source))), true);
assert.equal(model.sameEdition(source, {...source,revision_no:3}), false);
assert.equal(model.sameEdition(source, {...source,scope:{account_key:'company'}}), false);
assert.equal(model.sameEdition(source, {...source,payload:{...source.payload,totals:{spend:3}}}), false);
assert.equal(model.sameEdition({...source,company_name:'가게'}, {...source,company_name:'다른 이름'}), false);
assert.equal(model.sameEdition({...source,owner:{name:'직원1'}}, {...source,owner:{name:'직원2'}}), false);
assert.equal(model.sameEdition({...source,checked_at:'first'}, {...source,checked_at:'later'}), true);
assert.equal(model.metric({totals:{spend:0}}, 'spend'), 0);
assert.equal(model.metric({totals:{spend:null}}, 'spend'), null);
assert.equal(model.metric({totals:{}}, 'spend'), null);
console.log('report UI model: 16 assertions passed');

const test = require('node:test');
const appSource = fs.readFileSync('backend/naver_page/app.js', 'utf8');
const viewStart = appSource.indexOf('  var VIEW_FIELDS = ');
const viewEnd = appSource.indexOf('  // 변하지 않은 행은', viewStart);
assert.ok(viewStart > 0 && viewEnd > viewStart, '실제 화면 요청 모듈을 검사해야 합니다');

// 실제 앱의 요청/캐시/권한 경계와 보고서 모듈을 실행한다. DOM·전송만 메모리 어댑터로 대체한다.
// 브라우저, HTTP, 계정 자격정보, 실제 PDF 생성은 사용하지 않는다.
function harness(preference) {
  const nodes = new Map(), requests = [], applied = [], downloads = [], toasts = [];
  let day = '2026-10-04', routes = 0;
  function node(tag) {
    const classes = new Set();
    return {
      tag, children: [], attrs: {}, events: {}, hidden: false, disabled: false, value: '', _text: '',
      get firstChild() { return this.children[0] || null; },
      get textContent() { return this._text + this.children.map(child => child.textContent).join(''); },
      set textContent(value) { this._text = String(value); this.children = []; },
      appendChild(child) { this.children.push(child); return child; },
      removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
      setAttribute(key, value) {
        this.attrs[key] = String(value);
        if (key === 'id') nodes.set(String(value), this);
        if (key === 'class') String(value).split(/\s+/).forEach(item => classes.add(item));
        if (key === 'disabled') this.disabled = true;
        if (key === 'hidden') this.hidden = true;
      },
      addEventListener(name, listener) { this.events[name] = listener; },
      fire(name) { return this.events[name] && this.events[name].call(this, {preventDefault() {}}); },
      classList: {
        add(value) { classes.add(value); }, remove(value) { classes.delete(value); },
        contains(value) { return classes.has(value); },
        toggle(value, force) {
          const on = force === undefined ? !classes.has(value) : force;
          if (on) classes.add(value); else classes.delete(value);
          return on;
        }
      }
    };
  }
  function $(id) { if (!nodes.has(id)) nodes.set(id, node('div')); return nodes.get(id); }
  function add(parent, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(value => add(parent, value)); return; }
    if (typeof child !== 'object') { const text = node('#text'); text.textContent = child; child = text; }
    parent.appendChild(child);
  }
  function h(tag, attrs, ...children) {
    const element = node(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith('on')) element.addEventListener(key.slice(2), value);
      else element.setAttribute(key, value);
    }
    children.forEach(child => add(element, child));
    return element;
  }
  function put(element, ...children) {
    element.children = []; element._text = '';
    children.forEach(child => add(element, child));
    return element;
  }
  function api(method, path, body) {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    requests.push({method, path, body, promise, resolve, reject});
    return promise;
  }
  const context = {
    window: {sessionStorage:{getItem:()=>preference,setItem:(_key,value)=>{preference=value;}}}, document: {visibilityState: 'visible', createElementNS: (_namespace, tag) => node(tag)},
    state: {gen: 0, inventoryGen: 0, reportsGen: 0, linksGen: 0, bellGen: 0,
      selection: 'all', screen: 'reports', me: {idx: 1, scope: 'owner', narrowed: false}, session: {}},
    $, h, put, api, reportUI: null, automationUI: null, kstDay: () => day, closeModals() {}, closeBell() {},
    datedTime: value => value || '', errText: error => error.body && error.body.error || 'error',
    route() { routes++; }, loadReports() { throw new Error('예상하지 않은 페이지 복구'); },
    ApiError: class extends Error { constructor(status, body) { super(body.error); this.status = status; this.body = body; } },
    setTimeout, clearTimeout, AbortController
  };
  vm.createContext(context);
  vm.runInContext(appSource.slice(viewStart, viewEnd), context);
  context.syncContext();
  vm.runInContext(fs.readFileSync('backend/naver_page/report-ui.js', 'utf8'), context);
  context.window.NaverReportPDF = {print(report, options) {
    if (options.isCurrent()) downloads.push(report);
    return Promise.resolve({started:true});
  }};
  const ui = context.window.NaverReports.create({
    $, h, put, api, fetchList: (path, apply) => context.fetchView('reports', path, apply),
    context: () => context.viewEpoch + '|' + context.state.gen + '|' + context.state.selection,
    active: () => !!context.state.me && !!context.state.session && context.state.screen === 'reports' &&
      context.document.visibilityState !== 'hidden',
    selection: () => context.state.selection, onList: data => applied.push(data),
    onDetailVerified() {}, denied: context.viewDenied, purge: context.purgeViews,
    num: value => String(value), won: value => String(value) + '원',
    periodText: (start, end) => start + '~' + end, datedTime: value => value || '',
    validation: () => null, changes: () => null, toast: value => toasts.push(value), go() {}
  });
  context.reportUI = ui;
  return {context, ui, $, requests, applied, downloads, toasts,
    changeDay(value) { day = value; }, get routes() { return routes; }};
}

function listData() {
  return {selection: 'all', page: 0, total: 1, next_page: null, unlinked_companies: 0,
    period: {kind: 'weekly', start: '2026-09-21', end: '2026-09-27'},
    rows: [{possibility_id: 11, account_key: 'account-a', report_id: 7, company_name: '검증 업체',
      account_name: '검증 계정', ad_account_no: '12345', status: 'ready'}]};
}
function full(data = listData(), cursor = 'cursorA') {
  return {version: 1, mode: 'full', checked_at: '2026-10-04T10:00:00+09:00',
    cursor, base_cursor: null, rows: null, data};
}
function detailData() {
  return {report_id: 7, revision_no: 1, revision_fingerprint: 'fixed-source', possibility_id: 11,
    company_name: '검증 업체', generated_at: '2026-09-28T10:00:00+09:00',
    period_key: 'weekly:2026-09-21:2026-09-27', status: 'ready',
    scope: {kind: 'account', account_key: 'account-a', account_name: '검증 계정', ad_account_no: '12345'},
    payload: {format_version: 2, period: listData().period, totals: {spend: 12345},
      ratios: {}, coverage: {basic_complete: true, conversion_complete: true}, details: {daily: [], briefing: []}}};
}
function findButton(element, label) {
  if (element.tag === 'button' && element.textContent === label) return element;
  for (const child of element.children) { const found = findButton(child, label); if (found) return found; }
  return null;
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function findClass(element, name) {
  if (element.classList.contains(name)) return element;
  for (const child of element.children) { const found = findClass(child, name); if (found) return found; }
  return null;
}

async function renderReportFixture(report) {
  const fixture = harness();
  const first = fixture.ui.load();
  fixture.requests[0].resolve(full());
  await first;
  findButton(fixture.$('reportsRows'), '보고서 보기').fire('click');
  fixture.requests[1].resolve(report);
  await flush();
  return fixture;
}

test('누락 목록은 날짜·계정순번과 알려진 한국어 사유·지표만 최대 100건 표시한다', async () => {
  const report = detailData();
  report.payload.missing = Array.from({length: 120}, (_, index) => ({
    day: '2026-09-21', account_index: index + 1, reason: 'day_missing', metrics: ['imp', 'clk', 'spend']
  }));
  report.payload.missing[1].reason = 'source_unverified';
  report.payload.missing[2].reason = 'metrics_incomplete';
  report.payload.missing[2].metrics = ['conversions', 'conversion_value'];
  report.payload.missing[3].reason = 'PRIVATE_REASON_TOKEN';
  report.payload.missing[3].metrics = ['PRIVATE_METRIC_TOKEN'];
  report.payload.missing_count = 125;
  report.payload.missing_truncated = true;
  const fixture = await renderReportFixture(report);
  const section = findClass(fixture.$('reportDetail'), 'report-missing');
  assert.ok(section, '구체적인 누락 목록이 있어야 합니다');
  assert.match(section.textContent, /누락 125건/);
  assert.match(section.textContent, /2026-09-21 · 계정 순번 1 · 해당 날짜 미수집 · 노출·클릭·광고비/);
  assert.match(section.textContent, /원천 확인 전/);
  assert.match(section.textContent, /일부 지표 미수신 · 전환·광고 전환가치/);
  assert.match(section.textContent, /사유 미확인 · 지표 미확인/);
  assert.match(section.textContent, /앞 100건 표시 · 전체 누락 125건/);
  assert.doesNotMatch(section.textContent, /PRIVATE_|계정 순번 101/);
});

test('확인된 빈 누락 배열과 이전 판 미보관·상세 없는 양수 건수를 구분한다', async () => {
  const cases = [
    {patch: {missing: [], missing_count: 0}, knownZero: true},
    {patch: {missing: [], format_version: 1, details: {status: 'legacy_unavailable'}}, knownZero: true},
    {patch: {missing: [], missing_count: null, format_version: 1,
      details: {status: 'legacy_unavailable'}}, knownZero: false},
    {patch: {}, knownZero: false},
    {patch: {missing_count: 0}, knownZero: false},
    {patch: {missing: [], missing_count: 5}, knownZero: false, count: 5}
  ];
  for (const item of cases) {
    const report = detailData();
    Object.assign(report.payload, item.patch);
    const fixture = await renderReportFixture(report);
    const section = findClass(fixture.$('reportDetail'), 'report-missing');
    assert.ok(section);
    if (item.knownZero) {
      assert.match(section.textContent, /누락 0건/);
      assert.match(section.textContent, /서버가 보고한 누락이 없습니다/);
    } else {
      assert.doesNotMatch(section.textContent, /누락 0건|누락이 없습니다|누락 없음/);
      if (item.count) {
        assert.match(section.textContent, /전체 누락 5건/);
        assert.match(section.textContent, /누락 상세가 보관되지 않았거나 확인되지 않았습니다/);
      } else assert.match(section.textContent, /누락 상세 미보관·미확인/);
    }
  }
});

test('미생성 기간 상세에서 재진입하면 목록을 재검증한 뒤 신선도 게이트를 해제한다', async () => {
  for (const nextReportId of [null, 8]) {
    const fixture = harness();
    const first = fixture.ui.load();
    fixture.requests[0].resolve(full());
    await first;
    findButton(fixture.$('reportsRows'), '보고서 보기').fire('click');
    fixture.requests[1].resolve(detailData());
    await flush();

    const anchor = fixture.$('reportAnchor');
    anchor.value = '2026-09-28';
    anchor.fire('change');
    const pending = listData();
    pending.period = {kind: 'weekly', start: '2026-09-28', end: '2026-10-04'};
    pending.rows[0] = {...pending.rows[0], report_id: null, status: 'not_generated'};
    fixture.requests[2].resolve(pending);
    await flush();
    assert.match(fixture.$('reportDetail').textContent, /아직 생성되지 않았습니다/);

    fixture.context.state.screen = 'dashboard';
    fixture.context.state.gen++;
    fixture.context.gateView('reports');
    fixture.context.state.screen = 'reports';
    fixture.context.state.gen++;
    const returning = fixture.ui.load();
    assert.equal(fixture.requests.length, 4, '저장 판이 없으면 현재 기간 목록부터 다시 확인해야 합니다');
    assert.match(fixture.requests[3].path, /^\/reports\/accounts\?.*kind=weekly&anchor=2026-09-28/);
    assert.equal(fixture.$('s-reports').classList.contains('view-unverified'), true);

    const latest = {...pending, rows: [{...pending.rows[0], report_id: nextReportId,
      status: nextReportId ? 'ready' : 'not_generated'}]};
    fixture.requests[3].resolve(full(latest, 'periodB'));
    await returning;
    assert.equal(fixture.$('s-reports').classList.contains('view-unverified'), false);
    assert.equal(fixture.$('reportDetail').hidden, true);
    assert.equal(fixture.$('reportsRows').hidden, false);
    assert.equal(fixture.applied.at(-1).rows[0].report_id, nextReportId);
    const button = findButton(fixture.$('reportsRows'), nextReportId ? '보고서 보기' : '생성 대기');
    assert.ok(button);
    assert.equal(button.disabled, nextReportId === null);
  }
});

test('동일 key 대기 요청은 한 번 전송하고 마지막 apply만 실행한다', async () => {
  const fixture = harness(), calls = [];
  const first = fixture.context.fetchView('reports', '/reports/accounts?page=0', data => calls.push(['first', data]));
  const second = fixture.context.fetchView('reports', '/reports/accounts?page=0', data => calls.push(['latest', data]));
  assert.strictEqual(first, second);
  assert.equal(fixture.requests.length, 1);
  fixture.requests[0].resolve(full());
  await second;
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'latest');
  assert.equal(calls[0][1].rows[0].report_id, 7);
  assert.equal(fixture.context.viewCache.size, 1);
  assert.equal(fixture.context.viewRequests.reports, undefined);
});

test('실제 보고서 load가 중복되어도 마지막 epoch의 목록과 버튼이 살아 있다', async () => {
  const fixture = harness();
  const first = fixture.ui.load(), latest = fixture.ui.load();
  assert.strictEqual(first, latest);
  assert.equal(fixture.requests.length, 1);
  fixture.requests[0].resolve(full());
  await latest;
  assert.equal(fixture.applied.length, 1);
  const open = findButton(fixture.$('reportsRows'), '보고서 보기');
  assert.ok(open);
  open.fire('click');
  assert.equal(fixture.requests.length, 2);
  assert.match(fixture.requests[1].path, /report_id=7&account_key=account-a$/);
});

test('권한 문맥이 바뀐 옛 응답은 새 요청·캐시·화면을 덮지 않는다', async () => {
  const fixture = harness(), calls = [];
  const old = fixture.context.fetchView('reports', '/reports/accounts?page=0', () => calls.push('old'));
  fixture.context.state.me = {idx: 2, scope: 'staff', narrowed: true};
  const latest = fixture.context.fetchView('reports', '/reports/accounts?page=0', () => calls.push('current'));
  assert.equal(fixture.requests.length, 2);
  fixture.requests[0].resolve(full());
  await old;
  assert.deepEqual(calls, []);
  assert.equal(fixture.context.viewCache.size, 0);
  assert.strictEqual(fixture.context.viewRequests.reports.promise, latest);
  fixture.requests[1].resolve(full());
  await latest;
  assert.deepEqual(calls, ['current']);
});

test('화면 세대·로그인·가시성이 바뀌면 늦은 응답을 적용하거나 캐시하지 않는다', async () => {
  const mutations = {
    epoch: context => { context.viewEpoch++; },
    generation: context => { context.state.gen++; },
    screen: context => { context.state.screen = 'dashboard'; },
    identity: context => { context.state.me = null; },
    session: context => { context.state.session = null; },
    hidden: context => { context.document.visibilityState = 'hidden'; }
  };
  for (const [reason, mutate] of Object.entries(mutations)) {
    const fixture = harness(), calls = [];
    const pending = fixture.context.fetchView('reports', '/reports/accounts?page=0', () => calls.push('applied'));
    mutate(fixture.context);
    fixture.requests[0].resolve(full());
    await pending;
    assert.equal(calls.length, 0, reason);
    assert.equal(fixture.context.viewCache.size, 0, reason);
  }
});

test('다른 검색 key의 최신 요청보다 늦은 이전 응답은 무시한다', async () => {
  const fixture = harness(), calls = [];
  const old = fixture.context.fetchView('reports', '/reports/accounts?page=0&q=old', () => calls.push('old'));
  const latest = fixture.context.fetchView('reports', '/reports/accounts?page=0&q=new', () => calls.push('new'));
  fixture.requests[1].resolve(full());
  await latest;
  fixture.requests[0].resolve(full());
  await old;
  assert.deepEqual(calls, ['new']);
  assert.equal(fixture.context.viewCache.size, 1);
});

test('날짜 전환과 권한 거절은 이전 자료를 적용하지 않고 경계를 초기화한다', async () => {
  const fixture = harness(), calls = [];
  const pending = fixture.context.fetchView('reports', '/reports/accounts?page=0', () => calls.push('applied'));
  fixture.changeDay('2026-10-05');
  fixture.requests[0].resolve(full());
  await pending;
  assert.equal(fixture.routes, 1);
  assert.equal(calls.length, 0);
  assert.equal(fixture.context.viewCache.size, 0);
  const before = fixture.context.viewEpoch;
  const denied = fixture.context.fetchView('reports', '/reports/accounts?page=0', () => calls.push('denied'));
  fixture.requests[1].reject({status: 403, body: {error: 'not-visible'}});
  await denied;
  assert.ok(fixture.context.viewEpoch > before);
  assert.equal(calls.length, 0);
  assert.equal(fixture.$('reportsSync').attrs['data-status'], 'error');
});

test('같은 내용의 재확인 중에는 옛 버튼을 막고 unchanged 확인 후 다시 허용한다', async () => {
  const fixture = harness();
  const first = fixture.ui.load();
  fixture.requests[0].resolve(full());
  await first;
  const open = findButton(fixture.$('reportsRows'), '보고서 보기');
  assert.ok(open);
  const checking = fixture.ui.load();
  open.fire('click');
  assert.equal(fixture.requests.length, 2, '재확인 중 옛 버튼으로 상세 요청을 보내면 안 됩니다');
  fixture.requests[1].resolve({version: 1, mode: 'unchanged', checked_at: '2026-10-04T10:01:00+09:00',
    cursor: 'cursorB', base_cursor: 'cursorA', data: null, rows: null});
  await checking;
  assert.equal(fixture.applied.length, 2, 'unchanged여도 최신 load의 준비 상태는 갱신해야 합니다');
  assert.strictEqual(findButton(fixture.$('reportsRows'), '보고서 보기'), open);
  open.fire('click');
  assert.equal(fixture.requests.length, 3);
});

test('보고서 자체 reset 이후의 목록 응답은 현재 화면에 반영하지 않는다', async () => {
  const fixture = harness();
  const pending = fixture.ui.load();
  fixture.ui.reset();
  fixture.requests[0].resolve(full());
  await pending;
  assert.equal(fixture.applied.length, 0);
  assert.equal(fixture.$('reportsRows').firstChild, null);
});

test('다운로드 재검증 판이 다르거나 대기 중 reset되면 PDF를 만들지 않는다', async () => {
  for (const reset of [false, true]) {
    const fixture = harness();
    const list = fixture.ui.load();
    fixture.requests[0].resolve(full());
    await list;
    findButton(fixture.$('reportsRows'), '보고서 보기').fire('click');
    fixture.requests[1].resolve(detailData());
    await flush();
    const download = fixture.$('reportPdfDownload');
    download.fire('click');
    assert.equal(fixture.requests.length, 3);
    if (reset) fixture.ui.reset();
    fixture.requests[2].resolve(reset ? detailData() : {...detailData(), revision_no: 2});
    await flush();
    assert.equal(fixture.downloads.length, 0);
    assert.equal(fixture.toasts.length, reset ? 0 : 1);
    if (!reset) assert.match(fixture.toasts[0], /보고서 정보가 바뀌었습니다/);
  }
});

test('동일 판 검사는 범위·고정 내용·표시 소유자를 모두 비교하고 조회 시각만 무시한다', () => {
  const current = detailData();
  for (const changed of [
    {report_id: 8}, {revision_fingerprint: 'changed'}, {status: 'partial'}, {possibility_id: 12},
    {period_key: 'monthly:2026-09-01:2026-09-30'}, {generated_at: '2026-10-04T11:00:00+09:00'},
    {scope: {...current.scope, accounts: [{account_key: 'other'}]}},
    {payload: {...current.payload, details: {...current.payload.details, comparison: {totals: {spend: 3}}}}}
  ]) assert.equal(model.sameEdition(current, {...current, ...changed}), false);
  assert.equal(model.sameEdition(null, current), false);
  assert.equal(model.sameEdition(current, undefined), false);
  assert.equal(model.sameEdition(current, {...current, checked_at: '2026-10-04T11:00:00+09:00'}), true);
});

function expandedData() {
  const report = detailData(), keys = ['spend','conversion_value','conversions','roas','cpa','cvr','impressions','clicks','ctr','cpc','cpm','value_per_conversion','spend_per_day','clicks_per_day','impressions_per_day','conversions_per_day','value_per_day'];
  report.payload.details.enrichment = {version: 1, metrics: keys.map((key, i) => ({key, label:key,
    unit: ['roas','ctr','cvr'].includes(key) ? 'percent' : ['spend','conversion_value','cpa','cpc','cpm','value_per_conversion','spend_per_day','value_per_day'].includes(key) ? 'money' : 'number',
    current: 20 + i, previous: i ? 10 + i : 0, absolute: i ? 10 : 20, percent: i ? 50 : null,
    percentage_points: ['roas','ctr','cvr'].includes(key), status:i ? 'ready' : 'zero_denominator', value_status:'ready',
    scope:{family:['roas','cpa','cvr'].includes(key)?'paired':'basic',account_days:7,expected_account_days:7,complete:true},
    comparison_reason:i ? null : '직전 값 0 · 상대 변화 산출 불가'})), quality:{expected_account_days:7,
      basic:{count:7,percent:100,complete:true}, conversion:{count:5,percent:71.43,complete:false}, paired:{count:5,percent:71.43,complete:false}},
    feedback:{facts:[{text:'고정 수치 사실',metric_keys:['spend'],evidence:{scope:'기본 성과',account_days:7,expected_account_days:7}}],
      hypotheses:[{text:'원인 가설',alternative:'다른 원인',required_evidence:['변경 기록'],verification:'기록 확인',metric_keys:['roas']}],
      actions:[{text:'확인할 계획',reason:'검증 필요',owner:'담당자 확인 필요',priority:'high',approval_status:'proposed',status:'proposed',metric_keys:['roas']}]}, period_caveats:['전환가치는 실제 주문매출과 별도']};
  report.annotations = {version:1,state:'draft',metadata:{report_id:7,account_key:'account-a',revision_fingerprint:'fixed-source',period:report.payload.period},
    document:{internal_note:'PRIVATE_MEMO',client_feedback:'PRIVATE_CLIENT',shared_comment:'검토할 공유 문안',next_plan:'실행 전 계획',plan_due:null,targets:{cpa:null,roas:null,spend_per_day:null,source:''}},
    shared:null,history:{items:[{version:1,state:'draft',created_at:'2026-09-28T10:01:00+09:00'}],next_before_version:null},can_edit:true,can_approve:true};
  return report;
}
function allNodes(element) { return [element,...element.children.flatMap(allNodes)]; }

test('17개 서버 지표·품질·기여·가설은 표시하되 임의 목표를 만들지 않는다', async () => {
  const report = expandedData(); report.scope.kind = 'company'; report.scope.account_key = 'company';
  report.scope.contributions = [{account_name:'포함 계정',ad_account_no:'123',metrics:report.payload.details.enrichment.metrics,shares:{spend:100,conversions:null}}];
  const fixture = await renderReportFixture(report), root = fixture.$('reportDetail');
  const table = findClass(root,'nr-metric-table');
  assert.equal(table.children[1].children.length,17);
  assert.match(table.textContent,/직전 값 0 · 상대 변화 산출 불가/);
  assert.match(table.textContent,/\+10%p/);
  assert.equal(findClass(root,'nr-quality-cards').children.length,3);
  assert.match(findClass(root,'nr-feedback').textContent,/고정 수치 사실.*원인 가설.*다른 원인.*확인할 계획.*검토 필요/s);
  assert.match(findClass(root,'nr-targets').textContent,/목표 미설정/);
  assert.match(findClass(root,'nr-contributions').textContent,/포함 계정/);
  assert.equal(fixture.$('reportTarget-cpa').value,'');
});

test('공유용 검토 전환은 요청 없이 승인 문안만 표시하고 내부 입력을 제거한다', async () => {
  const report = expandedData(); report.annotations.state = 'approved';
  report.annotations.shared = {version:1,state:'approved',metadata:report.annotations.metadata,shared_comment:'승인 공유문안 <img src=x onerror=alert(1)>',next_plan:'승인 계획',plan_due:null,targets:{},approved_at:'2026-09-28T11:00:00+09:00'};
  const fixture = await renderReportFixture(report), count = fixture.requests.length;
  fixture.$('reportSharePreview').fire('click');
  assert.equal(fixture.requests.length,count);
  const rendered = fixture.$('reportDetail'), nodes = allNodes(rendered);
  assert.match(rendered.textContent,/승인 공유문안 <img src=x onerror=alert\(1\)>/);
  assert.doesNotMatch(rendered.textContent,/담당자 내부 메모|광고주에게 받은 질문|검토할 공유 문안/);
  assert.equal(nodes.some(node => ['script','img','textarea'].includes(node.tag)),false);
  assert.equal(nodes.some(node => /PRIVATE/.test(node.value)),false);
});

test('문안 수정은 PDF와 승인 버튼을 막고 저장·승인 뒤 exact detail을 재조회한다', async () => {
  const report = expandedData(), fixture = await renderReportFixture(report);
  fixture.$('reportNote-shared_comment').value = '수정한 공유 문안'; fixture.$('reportNote-shared_comment').fire('input');
  assert.equal(fixture.ui.hasUnsaved(),true);
  assert.equal(fixture.$('reportPdfDownload').disabled,true);
  assert.equal(fixture.$('reportNotesApprove').disabled,true);
  fixture.$('reportNotesSave').fire('click');
  const request = fixture.requests[2];
  assert.equal(request.method,'POST'); assert.equal(request.path,'/reports/notes');
  assert.equal(request.body.expected_version,1); assert.equal(request.body.document.shared_comment,'수정한 공유 문안');
  request.resolve({version:2,state:'draft'}); await flush();
  assert.match(fixture.requests[3].path,/report_id=7&account_key=account-a$/);
  const saved = expandedData(); saved.annotations.version=2; saved.annotations.document.shared_comment='수정한 공유 문안';
  fixture.requests[3].resolve(saved); await flush();
  assert.equal(fixture.ui.hasUnsaved(),false); assert.equal(fixture.$('reportNotesApprove').disabled,false);
  fixture.$('reportNotesApprove').fire('click');
  assert.equal(fixture.requests[4].body.action,'approve'); assert.equal(fixture.requests[4].body.document,undefined);
  fixture.requests[4].resolve({version:3,state:'approved'}); await flush();
  assert.equal(fixture.requests[5].method,'GET');
  const approved=expandedData(); approved.annotations.version=3; approved.annotations.state='approved';
  approved.annotations.shared={version:3,state:'approved',metadata:approved.annotations.metadata,shared_comment:'확정 공유 문안',next_plan:'계획',targets:{},approved_at:'2026-09-28T11:00:00+09:00'};
  fixture.requests[5].resolve(approved); await flush();
  assert.match(fixture.$('reportDetail').textContent,/확정 공유 문안/);
});

test('목표 출처가 없는 입력과 늦은 저장 응답은 적용하지 않으며 권한은 서버 플래그를 따른다', async () => {
  const fixture = await renderReportFixture(expandedData());
  fixture.$('reportTarget-cpa').value='100'; fixture.$('reportTarget-cpa').fire('input');
  assert.equal(fixture.$('reportNotesSave').disabled,true);
  fixture.$('reportTarget-source').value='광고주 합의'; fixture.$('reportTarget-source').fire('input');
  assert.equal(fixture.$('reportNotesSave').disabled,false);
  fixture.$('reportNotesSave').fire('click'); fixture.context.state.gen++;
  fixture.requests[2].resolve({version:2,state:'draft'}); await flush();
  assert.equal(fixture.requests.length,3,'문맥이 바뀐 저장 응답으로 새 상세를 요청하지 않는다');
  assert.equal(fixture.toasts.length,0);
  const readonly=expandedData(); readonly.annotations.can_edit=false; readonly.annotations.can_approve=false;
  const limited=await renderReportFixture(readonly);
  assert.equal(limited.$('reportNote-shared_comment').disabled,true);
  assert.equal(limited.$('reportNotesApprove').disabled,true);
  assert.equal(model.sameEdition(readonly,{...readonly,annotations:{...readonly.annotations,version:2}}),false);
});

test('대표 ID 0 승인과 author.at 이력을 표시하고 내부 이력 원문은 공유 화면에서 제거한다', async () => {
  const report=expandedData(); report.annotations.state='approved'; report.annotations.author={actor:0,at:'2026-09-28T10:01:00+09:00'};
  report.annotations.approved_by=0; report.annotations.approved_at='2026-09-28T10:30:00+09:00';
  report.annotations.history.items=[{version:1,state:'approved',author:report.annotations.author,approved_by:0,approved_at:report.annotations.approved_at,document:{internal_note:'HISTORY_PRIVATE',client_feedback:'QUESTION_PRIVATE',shared_comment:'HISTORY_SHARED',targets:{cpa:3000,source:'과거 합의'}}}];
  const fixture=await renderReportFixture(report), history=findClass(fixture.$('reportDetail'),'nr-note-history');
  assert.match(history.textContent,/작성자 ID 0.*2026-09-28T10:01:00.*승인자 ID 0/s);
  assert.match(history.textContent,/HISTORY_PRIVATE.*QUESTION_PRIVATE.*HISTORY_SHARED.*과거 합의/s);
  assert.match(findClass(fixture.$('reportDetail'),'nr-annotations').textContent,/승인자 ID 0/);
  fixture.$('reportSharePreview').fire('click');
  assert.doesNotMatch(fixture.$('reportDetail').textContent,/HISTORY_|QUESTION_PRIVATE|작성자 ID 0/);
});

test('전환·ROAS 차트는 부분 날짜를 끊고 탭 전환으로 서버 요청을 만들지 않는다', async () => {
  const report=expandedData(); report.payload.details.daily=[1,2,3].map(n=>({day:'2026-09-'+(20+n),totals:{spend:100,clicks:20,impressions:500,conversions:10},ratios:{roas:500},coverage:{basic_complete:true,conversion_complete:n!==2}}));
  const fixture=await renderReportFixture(report), count=fixture.requests.length;
  findButton(fixture.$('reportChart'),'ROAS').fire('click');
  const nodes=allNodes(fixture.$('reportChart'));
  assert.equal(nodes.filter(node=>node.classList.contains('nr-dot')).length,2);
  assert.equal(nodes.filter(node=>node.tag==='polyline').length,2);
  findButton(fixture.$('reportChart'),'전환수').fire('click');
  assert.equal(fixture.requests.length,count);
  assert.equal(allNodes(fixture.$('reportChart')).filter(node=>node.classList.contains('nr-dot')).length,2);
});

test('notes capability는 현재 상세의 판·범위·문안판·권한·화면 문맥만 허용한다', async () => {
  const report=expandedData(), fixture=await renderReportFixture(report);
  const save={report_id:7,account_key:'account-a',revision_fingerprint:'fixed-source',expected_version:1,action:'save',document:{shared_comment:'검토 초안'}};
  assert.equal(fixture.ui.notesCapability(save),true);
  const approve={...save,action:'approve'}; delete approve.document;
  assert.equal(fixture.ui.notesCapability(approve),true);
  for (const patch of [{report_id:8},{account_key:'company'},{revision_fingerprint:'other'},{expected_version:0},{expected_version:true},{action:'unknown'},{document:[]}]) {
    assert.equal(fixture.ui.notesCapability({...save,...patch}),false,JSON.stringify(patch));
  }
  fixture.$('reportNote-shared_comment').value='입력 중'; fixture.$('reportNote-shared_comment').fire('input');
  assert.equal(fixture.ui.notesCapability(approve),false,'미저장 입력을 승인할 수 없다');
  assert.equal(fixture.ui.notesCapability(save),true,'입력된 초안 저장은 가능하다');
  fixture.context.state.gen++;
  assert.equal(fixture.ui.notesCapability(save),false,'화면 세대가 바뀐 상세는 허용하지 않는다');
  fixture.ui.reset(); assert.equal(fixture.ui.notesCapability(save),false);
  const limited=expandedData(); limited.annotations.can_edit=false; limited.annotations.can_approve=false;
  const denied=await renderReportFixture(limited);
  assert.equal(denied.ui.notesCapability(save),false); assert.equal(denied.ui.notesCapability(approve),false);
  const approved=expandedData(); approved.annotations.state='approved';
  assert.equal((await renderReportFixture(approved)).ui.notesCapability(approve),false);
});

test('A/B/C 배치는 다른 구조로 같은 판을 읽고 미저장 입력·권한을 보존한다', async () => {
  const report=expandedData(), original=JSON.stringify(report), fixture=await renderReportFixture(report);
  fixture.$('reportNote-shared_comment').value='보존할 초안'; fixture.$('reportNote-shared_comment').fire('input');
  fixture.$('reportNote-internal_note').value='PRIVATE_CHANGED'; fixture.$('reportNote-internal_note').fire('input');
  fixture.$('reportTarget-cpa').value='100'; fixture.$('reportTarget-cpa').fire('input');
  const count=fixture.requests.length;
  for (const layout of ['b','c','a']) {
    fixture.$('reportLayout-'+layout).fire('click');
    const paper=findClass(fixture.$('reportDetail'),'nr-report-paper');
    assert.equal(paper.attrs['data-layout'],layout);
    assert.ok(findClass(paper,layout==='a'?'nr-a-review-grid':layout==='b'?'nr-analysis-grid':'nr-strategy-grid'));
    assert.equal(findClass(paper,'nr-metric-table').children[1].children.length,17);
    assert.equal(fixture.$('reportNote-shared_comment').value,'보존할 초안');
    assert.equal(fixture.$('reportNote-internal_note').value,'PRIVATE_CHANGED');
    assert.equal(fixture.ui.hasUnsaved(),true); assert.equal(fixture.$('reportPdfDownload').disabled,true);
    assert.equal(fixture.$('reportNotesApprove').disabled,true); assert.equal(fixture.$('reportNotesSave').disabled,true,'출처 없는 목표는 전환 후에도 저장 금지');
    assert.equal(fixture.ui.notesCapability({report_id:7,account_key:'account-a',revision_fingerprint:'fixed-source',expected_version:1,action:'save',document:{shared_comment:'검토'}}),true);
    assert.doesNotMatch(paper.textContent,/PRIVATE|보존할 초안|100원/);
  }
  assert.equal(fixture.requests.length,count); assert.equal(JSON.stringify(report),original);
});

test('세 공개 인쇄 배치는 승인 판만 읽고 0·누락·부분 범위와 빈 문안을 구분한다', async () => {
  const report=expandedData(); report.status='partial';
  report.payload.details.enrichment.metrics[0].current=0;
  report.payload.details.enrichment.metrics[1].current=null;
  report.annotations.state='approved';
  report.annotations.shared={version:1,state:'approved',metadata:report.annotations.metadata,shared_comment:'APPROVED_TEXT',next_plan:'APPROVED_PLAN',targets:{cpa:100,source:'APPROVED_SOURCE'},approved_at:'2026-09-28T11:00:00+09:00'};
  report.annotations.history.items=[{document:{internal_note:'HISTORY_PRIVATE'}}];
  const fixture=await renderReportFixture(report), count=fixture.requests.length;
  for(const layout of ['a','b','c']) {
    const paper=fixture.ui.makePaper(report,{layout,print:true}), nodes=allNodes(paper);
    assert.equal(paper.attrs['data-report-id'],'7'); assert.equal(paper.attrs['data-account-key'],'account-a');
    assert.equal(paper.attrs['data-revision-fingerprint'],'fixed-source');
    const rows=findClass(paper,'nr-metric-table').children[1].children;
    assert.equal(rows.length,17); assert.equal(rows[0].children[1].textContent,'0원'); assert.equal(rows[1].children[1].textContent,'—');
    assert.match(paper.textContent,/부분 집계|APPROVED_TEXT/); assert.match(paper.textContent,/APPROVED_PLAN.*APPROVED_SOURCE/s);
    assert.doesNotMatch(paper.textContent,/PRIVATE|검토할 공유 문안|당시 내부 메모/);
    assert.equal(nodes.some(node=>['button','input','textarea','select','form','script'].includes(node.tag)),false);
    assert.equal(nodes.some(node=>node.attrs.id==='reportChart'),false);
    assert.equal(nodes.filter(node=>node.tag==='details').every(node=>Object.hasOwn(node.attrs,'open')),true);
    for(const mutate of [r=>r.annotations.state='draft',r=>r.annotations.shared.version=2,r=>r.annotations.shared.metadata.revision_fingerprint='other']) {
      const stale=JSON.parse(JSON.stringify(report)); mutate(stale);
      const text=fixture.ui.makePaper(stale,{layout,print:true}).textContent;
      assert.doesNotMatch(text,/APPROVED_TEXT|APPROVED_PLAN|APPROVED_SOURCE/); assert.match(text,/승인된 공유 문안이 없습니다/);
    }
  }
  assert.equal(fixture.requests.length,count);
});

test('디자인 선택은 유효한 세 값만 이 세션에 보관하고 기본 A로 돌아간다', async () => {
  for(const preference of [undefined,'b','c','UNKNOWN','<img src=x>']) {
    const fixture=harness(preference), list=fixture.ui.load(); fixture.requests[0].resolve(full()); await list;
    findButton(fixture.$('reportsRows'),'보고서 보기').fire('click'); fixture.requests[1].resolve(expandedData()); await flush();
    assert.equal(findClass(fixture.$('reportDetail'),'nr-report-paper').attrs['data-layout'],['b','c'].includes(preference)?preference:'a');
    fixture.$('reportLayout-b').fire('click'); fixture.ui.reset();
    const next=fixture.ui.load(); fixture.requests[2].resolve(full()); await next;
    findButton(fixture.$('reportsRows'),'보고서 보기').fire('click'); fixture.requests[3].resolve(expandedData()); await flush();
    assert.equal(findClass(fixture.$('reportDetail'),'nr-report-paper').attrs['data-layout'],'b');
  }
});

test('인쇄용 상세 재검증 중 디자인 왕복 전환·초안·권한 변화는 인쇄 시작을 막는다', async () => {
  for(const change of ['layout','dirty','context']) {
    const report=expandedData(), fixture=await renderReportFixture(report);
    fixture.$('reportPdfDownload').fire('click');
    if(change==='layout') {fixture.$('reportLayout-b').fire('click');fixture.$('reportLayout-a').fire('click');}
    if(change==='dirty') {fixture.$('reportNote-shared_comment').value='변경 초안';fixture.$('reportNote-shared_comment').fire('input');}
    if(change==='context') fixture.context.state.gen++;
    fixture.requests[2].resolve(JSON.parse(JSON.stringify(report))); await flush();
    assert.equal(fixture.downloads.length,0); assert.equal(fixture.toasts.length,0);
  }
});

test('인쇄 호출은 선택 디자인과 공개 DOM을 고정하고 저장 완료를 주장하지 않는다', async () => {
  const report=expandedData(), fixture=await renderReportFixture(report); fixture.$('reportLayout-c').fire('click');
  let options, finish;
  fixture.context.window.NaverReportPDF.print=(verified,passed)=>{options=passed; assert.equal(model.sameEdition(report,verified),true);return new Promise(resolve=>{finish=resolve;});};
  fixture.$('reportPdfDownload').fire('click'); fixture.requests[2].resolve(JSON.parse(JSON.stringify(report))); await flush();
  assert.equal(options.layout,'c'); assert.equal(options.paper.attrs['data-layout'],'c'); assert.equal(options.isCurrent(),true);
  assert.doesNotMatch(options.paper.textContent,/PRIVATE|검토할 공유 문안/);
  finish({started:true}); await flush();
  assert.match(fixture.toasts[0],/인쇄창을 열었습니다/); assert.doesNotMatch(fixture.toasts[0],/내려받았습니다|저장했습니다/);
  assert.equal(fixture.$('reportPdfDownload').textContent,'PDF 저장');
  fixture.$('reportPdfDownload').fire('click'); fixture.requests[3].resolve(JSON.parse(JSON.stringify(report))); await flush();
  fixture.$('reportLayout-a').fire('click'); assert.equal(options.isCurrent(),false); finish({started:true}); await flush();
  assert.equal(fixture.toasts.length,1,'늦게 열린 이전 디자인의 인쇄는 완료 안내하지 않는다');
});

test('인쇄 재확인 중 디자인·초안 변경 후 도착한 권한 거절도 이전 자료를 제거한다', async () => {
  for(const change of ['layout','dirty']) {
    const fixture=await renderReportFixture(expandedData());
    fixture.$('reportPdfDownload').fire('click');
    if(change==='layout') fixture.$('reportLayout-b').fire('click');
    else { fixture.$('reportNote-shared_comment').value='입력'; fixture.$('reportNote-shared_comment').fire('input'); }
    fixture.requests[2].reject(new fixture.context.ApiError(403,{error:'forbidden'})); await flush();
    assert.equal(fixture.$('reportDetail').children.length,0,'권한 거절은 변경된 디자인의 상세도 제거한다');
    assert.equal(fixture.downloads.length,0);
  }
});

test('보고서 상태는 기본 누락과 전환 미확인을 구분하고 수집·대조·판 생성 시각을 각각 표시한다', async () => {
  const fixture=harness(); fixture.ui.load();
  const data=listData();
  data.rows=[
    {...data.rows[0],status:'partial',collection_status:'conversion_unconfirmed',generated_at:'판생성-10시',refresh:{scope:'current',source_collected_at:'수집-11시',last_success_at:null,status:'failed'}},
    {...data.rows[0],account_key:'account-b',status:'partial',collection_status:'basic_incomplete'},
    {...data.rows[0],account_key:'account-c',status:'ready',collection_status:'complete'}
  ];
  fixture.requests[0].resolve(full(data)); await flush();
  const text=fixture.$('reportsRows').textContent;
  assert.match(text,/기본 자료 완결 · 전환 산정 근거 미확인/);
  assert.match(text,/기본 자료 누락/);
  assert.match(text,/기본·전환 자료 완결/);
  assert.match(text,/성과 수집 수집-11시/);
  assert.match(text,/기본·전환 전체 재대조 성공 미확인/);
  assert.match(text,/재대조 실패 · 확인 필요/);
  assert.match(text,/수치판 생성 판생성-10시/);
  assert.equal(fixture.requests.length,1,'상태 표시는 수집을 시작하지 않는다');
  findButton(fixture.$('reportsRows'),'보고서 보기').fire('click');
  const report=detailData(); report.status='partial'; report.collection_status='conversion_unconfirmed';
  report.refresh={scope:'current',source_collected_at:'수집-11시',last_success_at:'대조-10시',last_attempt_at:'시도-12시',status:'pending'};
  fixture.requests[1].resolve(report); await flush();
  const detail=fixture.$('reportDetail').textContent;
  assert.match(detail,/최근 성과 수집 수집-11시/);
  assert.match(detail,/기본·전환 전체 재대조 성공 대조-10시/);
  assert.match(detail,/최근 재대조 시도 시도-12시/);
  assert.match(detail,/현재판의 최신 확인 상태 · 재대조 대기/);
  assert.match(detail,/수치판 생성 2026-09-28T10:00:00/);
  assert.equal(fixture.requests.length,2);
});

test('현재 전환 숫자 응답 완료는 저장판의 전환 근거·지표를 바꾸지 않고 과거판에 붙지 않는다', async () => {
  const fixture=harness(); fixture.ui.load();
  const data=listData();
  const response={status:'complete',expected_account_days:7,received_account_days:7,zero_account_days:7,positive_account_days:0,missing_or_null_account_days:0,source_unverified_account_days:0,basic_incomplete_account_days:0};
  data.rows[0].collection_status='conversion_unconfirmed';
  data.rows[0].refresh={scope:'current',status:'pending',conversion_response:response};
  fixture.requests[0].resolve(full(data)); await flush();
  assert.match(fixture.$('reportsRows').textContent,/현재 원천 전환 수치 응답 7\/7 계정×일/);
  assert.match(fixture.$('reportsRows').textContent,/수치 응답 대조 완료 · 전환 산정 근거 확인 필요/);
  findButton(fixture.$('reportsRows'),'보고서 보기').fire('click');
  const report=detailData(); report.collection_status='conversion_unconfirmed';
  report.refresh={scope:'current',status:'pending',conversion_response:response};
  const saved=JSON.stringify(report.payload);
  fixture.requests[1].resolve(report); await flush();
  const text=fixture.$('reportDetail').textContent;
  assert.match(text,/0 응답 7 · 양수 응답 0 · 미제공·유효하지 않은 값 0/);
  assert.match(text,/전환 추적 설치·정상 동작을 뜻하지 않습니다/);
  assert.equal(JSON.stringify(report.payload),saved);
  assert.equal(fixture.requests.length,2,'응답 범위 표시가 수집·문안 저장을 시작하지 않는다');
  const history=harness(); history.ui.load(); history.requests[0].resolve(full(listData())); await flush();
  findButton(history.$('reportsRows'),'보고서 보기').fire('click');
  const old=detailData(); old.refresh={scope:'saved',status:'pending',conversion_response:response};
  history.requests[1].resolve(old); await flush();
  assert.doesNotMatch(history.$('reportDetail').textContent,/현재 원천 전환 수치 응답/);
});

function strategyReport(state='approved',version=1) {
  const report=expandedData(), metadata={report_id:report.report_id,account_key:report.scope.account_key,revision_fingerprint:report.revision_fingerprint,strategy_version:1};
  const document={diagnosis:'승인 진단 <img onerror=alert(1)>',direction:'승인 방향',appeal_points:[],competitive_response:'경쟁 자료 미연결',
    weekly_plan:[{action:'주간 확인',reason:'근거 대조',criterion:'자료 완결 확인'}],monthly_plan:[{action:'월간 검토',reason:'추이 확인',criterion:'같은 범위 비교'}],funnel_comment:'광고 관측 범위',ab_comment:'통제된 A/B 자료 미연결',shared_comment:'승인된 마케터 코멘트'};
  report.marketing_strategy={version,state,metadata,source:'staff',document,can_edit:true,can_approve:true,provider_status:{configured:false},
    shared:state==='approved'?{version,state,metadata:{...metadata},document:JSON.parse(JSON.stringify(document)),source:'staff',approved_at:'2026-10-10T12:00:00+09:00'}:null};
  return report;
}
test('세 공개 배치는 exact 승인 전략만 표시하고 불일치·초안·내부 필드는 제외한다',async()=>{
  for(const layout of ['a','b','c']) {
    const report=strategyReport(), fixture=await renderReportFixture(report);
    report.marketing_strategy.document.shared_comment='PRIVATE_STRATEGY_CURRENT';
    report.marketing_strategy.shared.document.internal_note='PRIVATE_STRATEGY_EXTRA';
    const paper=fixture.ui.makePaper(report,{layout,print:true});
    assert.match(paper.textContent,/승인 진단 <img onerror=alert\(1\)>/);assert.match(paper.textContent,/승인된 마케터 코멘트/);
    assert.doesNotMatch(paper.textContent,/PRIVATE|담당자 검토|초안 저장/);
    assert.equal(allNodes(paper).filter(node=>node.tag==='img'||node.tag==='textarea').length,0);
    for(const mutate of [r=>r.marketing_strategy.state='draft',r=>r.marketing_strategy.shared.version=0,
      r=>r.marketing_strategy.shared.metadata.account_key='other',r=>r.marketing_strategy.metadata.revision_fingerprint='other']) {
      const changed=strategyReport();mutate(changed);const publicText=fixture.ui.makePaper(changed,{layout}).textContent;
      assert.doesNotMatch(publicText,/승인 진단|승인된 마케터 코멘트/);assert.equal(allNodes(fixture.ui.makePaper(changed,{layout})).filter(node=>node.classList.contains('nr-marketing-strategy')).length,0);
    }
  }
});
test('전략 dirty 입력은 디자인·공유 미리보기 전환 후 보존되며 PDF·승인을 차단한다',async()=>{
  const fixture=await renderReportFixture(strategyReport('draft'));
  fixture.$('reportStrategy-direction').value='저장하지 않은 방향';fixture.$('reportStrategy-direction').fire('input');
  assert.equal(fixture.$('reportPdfDownload').disabled,true);assert.equal(fixture.$('reportStrategyApprove').disabled,true);
  fixture.$('reportLayout-c').fire('click');assert.equal(fixture.$('reportStrategy-direction').value,'저장하지 않은 방향');
  fixture.$('reportSharePreview').fire('click');assert.doesNotMatch(fixture.$('reportDetail').textContent,/저장하지 않은 방향/);
  fixture.$('reportSharePreview').fire('click');assert.equal(fixture.$('reportStrategy-direction').value,'저장하지 않은 방향');
  assert.equal(fixture.requests.length,2);assert.equal(fixture.ui.hasUnsaved(),true);
});
test('전략 capability는 동일 수치판·계정·현재 버전과 서버 권한을 요구한다',async()=>{
  const report=strategyReport('draft'),fixture=await renderReportFixture(report),body={report_id:report.report_id,account_key:report.scope.account_key,revision_fingerprint:report.revision_fingerprint,expected_version:1,action:'approve'};
  assert.equal(fixture.ui.strategyCapability(body),true);
  for(const change of [{report_id:99},{account_key:'other'},{revision_fingerprint:'other'},{expected_version:0},{expected_version:'1'},{document:{}},{action:'execute'}])assert.equal(fixture.ui.strategyCapability({...body,...change}),false);
  fixture.$('reportStrategy-direction').value='입력';fixture.$('reportStrategy-direction').fire('input');assert.equal(fixture.ui.strategyCapability(body),false);
  assert.equal(fixture.ui.strategyCapability({...body,action:'save',document:report.marketing_strategy.document}),true);
  report.marketing_strategy.can_edit='true';assert.equal(fixture.ui.strategyCapability({...body,action:'save',document:{}}),false);
  fixture.context.state.gen++;assert.equal(fixture.ui.strategyCapability(body),false);
});
test('규칙 초안 생성·승인은 명시 클릭으로만 요청하고 같은 상세를 다시 읽는다',async()=>{
  const initial=strategyReport('empty',0);initial.marketing_strategy.document=null;const fixture=await renderReportFixture(initial);
  assert.equal(fixture.requests.filter(r=>r.method==='POST').length,0);fixture.$('reportStrategyGenerate').fire('click');
  assert.equal(fixture.requests[2].path,'/reports/strategy');assert.equal(fixture.requests[2].body.action,'generate');assert.equal(fixture.requests[2].body.expected_version,0);
  fixture.requests[2].resolve({});await flush();assert.match(fixture.requests[3].path,/\/reports\/detail\?/);
  const generated=strategyReport('draft',1);generated.marketing_strategy.source='rule_based';fixture.requests[3].resolve(generated);await flush();
  assert.match(fixture.toasts.at(-1),/AI API는 호출하지 않았습니다/);fixture.$('reportStrategyApprove').fire('click');
  assert.equal(fixture.requests[4].body.action,'approve');assert.equal(fixture.requests[4].body.document,undefined);fixture.requests[4].resolve({});await flush();
  fixture.requests[5].resolve(strategyReport('approved',2));await flush();assert.match(fixture.$('reportDetail').textContent,/승인된 마케터 코멘트/);
});
test('전략 변경은 동일판 비교와 진행 중 PDF 검증을 무효화한다',async()=>{
  const report=strategyReport(),fixture=await renderReportFixture(report),changed=JSON.parse(JSON.stringify(report));changed.marketing_strategy.can_approve=false;
  assert.equal(model.sameEdition(report,changed),false);fixture.$('reportPdfDownload').fire('click');fixture.requests[2].resolve(changed);await flush();
  assert.equal(fixture.downloads.length,0);assert.match(fixture.toasts.at(-1),/보고서 정보가 바뀌었습니다/);
});
test('전략 저장 대기 중 모든 입력을 잠그고 실패하면 초안을 다시 편집할 수 있다',async()=>{
  const report=strategyReport('draft'),fixture=await renderReportFixture(report);
  fixture.$('reportStrategy-direction').value='저장할 방향';fixture.$('reportStrategy-direction').fire('input');fixture.$('reportStrategySave').fire('click');
  assert.equal(fixture.$('reportStrategy-direction').disabled,true);assert.equal(fixture.$('reportStrategySave').disabled,true);
  fixture.$('reportStrategy-direction').value='대기 중 입력';fixture.$('reportStrategy-direction').fire('input');
  fixture.requests[2].reject(new fixture.context.ApiError(500,{error:'failed'}));await flush();
  assert.equal(fixture.$('reportStrategy-direction').value,'저장할 방향');assert.equal(fixture.$('reportStrategy-direction').disabled,false);assert.equal(fixture.ui.hasUnsaved(),true);
});
test('미승인·불일치 전략은 공개 ABC DOM에 빈 안내나 배치를 추가하지 않는다',async()=>{
  const baseline=strategyReport(),fixture=await renderReportFixture(baseline);
  delete baseline.marketing_strategy;
  function publicTree(node) {return {tag:node.tag,attrs:node.attrs,text:node._text,children:node.children.map(publicTree)};}
  for(const layout of ['a','b','c']) {
    const expected=publicTree(fixture.ui.makePaper(baseline,{layout,print:true}));
    for(const mutate of [r=>r.marketing_strategy.state='draft',r=>r.marketing_strategy.shared.version=9,
      r=>r.marketing_strategy.metadata.report_id=99,r=>r.marketing_strategy.shared.metadata.account_key='foreign']) {
      const unapproved=strategyReport();mutate(unapproved);
      assert.deepEqual(publicTree(fixture.ui.makePaper(unapproved,{layout,print:true})),expected);
    }
  }
});
test('전략 저장은 현재 expected_version만 전송하며 충돌·권한거절 응답을 구분한다',async()=>{
  const report=strategyReport('draft'),fixture=await renderReportFixture(report);
  fixture.$('reportStrategy-direction').value='보존할 충돌 초안';fixture.$('reportStrategy-direction').fire('input');fixture.$('reportStrategySave').fire('click');
  const sent=fixture.requests[2];
  assert.equal(sent.body.expected_version,1);assert.equal(sent.body.document.direction,'보존할 충돌 초안');
  assert.equal(sent.body.account_key,report.scope.account_key);assert.equal(sent.body.revision_fingerprint,report.revision_fingerprint);
  sent.reject(new fixture.context.ApiError(409,{error:'conflict'}));await flush();
  assert.equal(fixture.$('reportStrategy-direction').value,'보존할 충돌 초안');assert.match(fixture.$('reportStrategyStatus').textContent,/입력 초안은 보존됩니다/);
  assert.equal(fixture.requests.length,3,'충돌을 자동 재시도하지 않는다');
  fixture.$('reportStrategySave').fire('click');fixture.requests[3].reject(new fixture.context.ApiError(403,{error:'denied'}));await flush();
  assert.equal(fixture.$('reportDetail').textContent,'');assert.equal(fixture.ui.hasUnsaved(),false);
});
test('초기화 뒤 늦은 전략 응답은 새 화면이나 새 저장 잠금을 해제하지 않는다',async()=>{
  const report=strategyReport('draft'),fixture=await renderReportFixture(report);
  fixture.$('reportStrategy-direction').value='옛 초안';fixture.$('reportStrategy-direction').fire('input');fixture.$('reportStrategySave').fire('click');
  const oldSave=fixture.requests[2];fixture.ui.reset();
  const list=fixture.ui.load();fixture.requests[3].resolve(full());await list;
  findButton(fixture.$('reportsRows'),'보고서 보기').fire('click');fixture.requests[4].resolve(strategyReport('draft'));await flush();
  fixture.$('reportStrategy-direction').value='새 초안';fixture.$('reportStrategy-direction').fire('input');fixture.$('reportStrategySave').fire('click');
  oldSave.resolve({});await flush();
  assert.equal(fixture.requests.length,6,'옛 응답은 상세 재조회도 시작하지 않는다');
  assert.equal(fixture.$('reportStrategy-direction').value,'새 초안');assert.equal(fixture.$('reportStrategy-direction').disabled,true);
  assert.equal(fixture.$('reportPdfDownload').disabled,true);assert.equal(fixture.toasts.length,0);
  fixture.requests[5].reject(new fixture.context.ApiError(500,{error:'failed'}));await flush();
  assert.equal(fixture.$('reportStrategy-direction').disabled,false);assert.equal(fixture.$('reportStrategy-direction').value,'새 초안');
});

test('Claude 초안은 설정된 개별 계정에서 명시 클릭할 때만 요청하고 저장판을 다시 읽는다',async()=>{
  const report=strategyReport('empty',0);report.marketing_strategy.document=null;
  report.marketing_strategy.provider_status={configured:true};
  const fixture=await renderReportFixture(report),button=fixture.$('reportStrategyClaude');
  assert.equal(button.disabled,false);assert.equal(fixture.requests.filter(r=>r.method==='POST').length,0);
  const body={report_id:report.report_id,account_key:report.scope.account_key,revision_fingerprint:report.revision_fingerprint,expected_version:0,action:'generate_claude'};
  assert.equal(fixture.ui.strategyCapability(body),true);
  button.fire('click');assert.equal(fixture.requests[2].path,'/reports/strategy');assert.deepEqual(JSON.parse(JSON.stringify(fixture.requests[2].body)),body);
  assert.equal(fixture.$('reportStrategyClaude').disabled,true);button.fire('click');assert.equal(fixture.requests.length,3,'생성 중 중복 호출을 거부한다');
  fixture.requests[2].resolve({saved:true});await flush();assert.match(fixture.requests[3].path,/\/reports\/detail\?/);
  const generated=strategyReport('draft',1);generated.marketing_strategy.source='claude';generated.marketing_strategy.provider_status={configured:true};
  generated.marketing_strategy.provenance={plan_version:2,case_refs:[{asset_id:'anonymized-case',version:3}],model:'synthetic-model'};
  fixture.requests[3].resolve(generated);await flush();
  assert.match(fixture.toasts.at(-1),/Claude 초안을 작성/);assert.equal(fixture.$('reportStrategyApprove').disabled,false);
  assert.equal(fixture.requests.filter(r=>r.method==='POST').length,1);
});

test('Claude 미설정·읽기 전용·통합 계정·dirty·오래된 화면은 생성 요청을 보내지 않는다',async()=>{
  for(const mode of ['unconfigured','readonly','company','dirty','stale']) {
    const report=strategyReport('draft');report.marketing_strategy.provider_status={configured:mode!=='unconfigured'};
    if(mode==='readonly')report.marketing_strategy.can_edit=false;
    if(mode==='company'){report.scope.account_key='company';report.marketing_strategy.metadata.account_key='company';}
    const fixture=await renderReportFixture(report),button=fixture.$('reportStrategyClaude');
    const body={report_id:report.report_id,account_key:report.scope.account_key,revision_fingerprint:report.revision_fingerprint,expected_version:1,action:'generate_claude'};
    if(mode==='dirty'){fixture.$('reportStrategy-direction').value='미저장 전략';fixture.$('reportStrategy-direction').fire('input');}
    if(mode==='stale')fixture.context.state.gen++;
    else assert.equal(button.disabled,true,mode);
    assert.equal(fixture.ui.strategyCapability(body),false,mode);button.fire('click');await flush();
    assert.equal(fixture.requests.filter(r=>r.method==='POST').length,0,mode);
  }
});
