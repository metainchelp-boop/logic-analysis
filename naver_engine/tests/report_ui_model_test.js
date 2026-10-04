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
function harness() {
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
  function api(method, path) {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    requests.push({method, path, promise, resolve, reject});
    return promise;
  }
  const context = {
    window: {}, document: {visibilityState: 'visible', createElementNS: (_namespace, tag) => node(tag)},
    state: {gen: 0, inventoryGen: 0, reportsGen: 0, linksGen: 0, bellGen: 0,
      selection: 'all', screen: 'reports', me: {idx: 1, scope: 'owner', narrowed: false}, session: {}},
    $, h, put, api, reportUI: null, kstDay: () => day, closeModals() {}, closeBell() {},
    datedTime: value => value || '', errText: error => error.body && error.body.error || 'error',
    route() { routes++; }, loadReports() { throw new Error('예상하지 않은 페이지 복구'); },
    ApiError: class extends Error { constructor(status, body) { super(body.error); this.status = status; this.body = body; } },
    setTimeout, clearTimeout
  };
  vm.createContext(context);
  vm.runInContext(appSource.slice(viewStart, viewEnd), context);
  context.syncContext();
  vm.runInContext(fs.readFileSync('backend/naver_page/report-ui.js', 'utf8'), context);
  context.window.NaverReportPDF = {download(report, options) {
    if (options.isCurrent()) downloads.push(report);
    return Promise.resolve();
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
  assert.match(section.textContent, /일부 지표 미수신 · 전환·전환 매출/);
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
