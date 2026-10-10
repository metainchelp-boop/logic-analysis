/* Synthetic-only sales UI DOM contracts. No browser, network, storage or Store. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../backend/naver_page/sales-ui.js'), 'utf8');
let checks = 0;
const check = (value, message) => { assert.ok(value, message); checks++; };

function harness() {
  const calls = [], errors = [], prints = [], listeners = new Map();
  class El {
    constructor(tag) {
      this.tag = tag; this.children = []; this.events = {}; this.attrs = {}; this.value = ''; this._text = '';
      this._classes = new Set(); this.disabled = false; this.parentNode = null;
      this.classList = {add: x => this._classes.add(x), remove: x => this._classes.delete(x), contains: x => this._classes.has(x)};
    }
    set className(s) { this._classes = new Set(String(s).split(/\s+/).filter(Boolean)); }
    get className() { return [...this._classes].join(' '); }
    set textContent(s) { this._text = String(s); this.replaceChildren(); }
    get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
    get childNodes() { return this.children; }
    appendChild(child) {
      child.parentNode = this; this.children.push(child);
      if (this.tag === 'select' && this.children.length === 1) this.value = child.value;
      return child;
    }
    replaceChildren() { this.children.forEach(x => x.parentNode = null); this.children = []; }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    addEventListener(k, v) { this.events[k] = v; }
    fire(k) { if (!this.disabled && this.events[k]) return this.events[k]({preventDefault() {}}); }
    remove() {
      if (this.parentNode) { const a = this.parentNode.children; a.splice(a.indexOf(this), 1); this.parentNode = null; }
    }
  }
  const doc = {title: '기존 화면 제목', body: new El('body'), createElement: tag => new El(tag)};
  const root = new El('main'); doc.body.appendChild(root);
  const win = {
    addEventListener(k, v) { if (!listeners.has(k)) listeners.set(k, new Set()); listeners.get(k).add(v); },
    removeEventListener(k, v) { listeners.get(k)?.delete(v); },
    print() { prints.push({title: doc.title, text: doc.body.textContent, wrapper: doc.body.children.find(n => n.className === 'ns-print-root')}); },
    matchMedia() { return {addEventListener() {}, removeEventListener() {}}; }
  };
  const api = (requestedPath, query, options) => new Promise((resolve, reject) => calls.push({path: requestedPath, query, options, resolve, reject}));
  vm.runInNewContext(source, {window: win, document: doc, AbortController, console});
  const mount = () => win.NaverSalesUI.mount({root, api, me: {scope: 'SALES_READ'}, onError: error => errors.push(error)});
  const all = (el = root) => [el, ...el.children.flatMap(x => all(x))];
  const button = label => all().find(x => x.tag === 'button' && x.textContent === label);
  const flush = async () => { for (let n = 0; n < 10; n++) await Promise.resolve(); };
  const firePrint = () => [...(listeners.get('afterprint') || [])].forEach(fn => fn());
  return {doc, win, root, api, calls, errors, prints, mount, all, button, flush, firePrint};
}

const key = 'a'.repeat(64), key2 = 'b'.repeat(64);
const period = {kind: 'weekly', start: '2026-09-28', end: '2026-10-04'};
const account = (k = key) => ({account_key: k, account_name: '계정 ' + k[0], ad_account_no: '1234', status: 'conversion_unconfirmed', report_id: 12,
  metrics: {impressions: 1000, clicks: 0, cost: 0, conversions: null, revenue: null}});
const company = (id = 7, name = '업체 <img src=x onerror=boom()>') => ({possibility_id: id, company_name: name, stage: '진행중', connection_status: 'connected', accounts: [account(), account(key2)]});
const listing = (items = [company(), {possibility_id: 8, company_name: '연결 대기 업체', stage: '진행중', connection_status: 'pending', accounts: []}], over = {}) =>
  ({items, total: 101, page: 1, page_size: 100, period, source_as_of: '2026-10-10T10:00:00+09:00', ...over});
const report = () => ({possibility_id: 7, account_key: key, approval_version: 2, company_name: '승인 업체', account_name: '광고 계정', period,
  metrics: {impressions: 1000, clicks: 5, cost: 5000, conversions: 0, revenue: 0, ctr: 0.5, cpc: 1000, cvr: 0, cpa: null, roas: 0},
  comment: {shared_comment: '승인 문안 <svg onload=boom()>', next_plan: '승인된 다음 계획', plan_due: '2026-10-20', targets: {cpa: 1200, roas: 300}, internal_note: 'PRIVATE_NOTE'},
  internal_note: 'NEVER_RENDER', history: [{note: 'PRIVATE_HISTORY'}], comparison: null});

async function run() {
  const h = harness(); h.mount(); await h.flush();
  check(h.calls[0].path === '/sales/clients' && h.calls[0].query.kind === 'weekly' && h.calls[0].query.page === 1 && !('anchor' in h.calls[0].query), '초기 전용 GET 계약');
  h.calls[0].resolve(listing()); await h.flush();
  check(h.all().filter(n => n.className === 'ns-company').length === 2, '업체별 분리');
  check(h.all().filter(n => n.className === 'ns-account').length === 2, '동일 업체 복수 계정 분리');
  check(h.root.textContent.includes('0원') && h.root.textContent.includes('미확인'), '명시0과 미확인 구분');
  check(h.all().find(n => n.className === 'ns-company' && n.textContent.includes('연결 대기 업체')).children.every(n => n.className !== 'ns-metrics'), '미연결 수치 없음');
  check(!h.all().some(n => n.tag === 'img' || n.tag === 'svg') && h.root.textContent.includes('<img'), '문자열 XSS 비실행');
  h.button('다음').fire('click'); await h.flush();
  check(h.calls[1].query.page === 2 && !h.root.textContent.includes('연결 대기 업체'), '100곳 페이지 전환에서 이전 자료 제거');
  h.calls[1].resolve(listing([company()], {page: 2})); await h.flush();
  h.button('진행 상태 보기').fire('click'); await h.flush();
  check(h.calls[2].path === '/sales/detail' && h.calls[2].query.pid === 7 && h.calls[2].query.anchor === period.start, '상세 조회 기간 유지');
  h.calls[2].resolve({...company(), period, source_as_of: '2026-10-10T10:00:00+09:00'}); await h.flush();
  h.button('공유 보고서 확인').fire('click'); await h.flush();
  check(h.calls[3].path === '/sales/report' && h.calls[3].query.account_key === key, '계정별 승인 공유본 조회');
  h.calls[3].resolve(report()); await h.flush();
  check(h.root.textContent.includes('승인된 다음 계획') && !/PRIVATE_|NEVER_RENDER/.test(h.root.textContent), '내부 메모와 이력 미투영');
  check(h.root.textContent.includes('0건') && !h.all().some(n => n.tag === 'svg'), '전환0표시와 공유문안 XSS 비실행');
  check(h.all().filter(n => n.className === 'ns-metric').length === 12, '10개 성과지표와 승인목표만 표시');
  h.button('승인 보고서 PDF 저장').fire('click'); await h.flush();
  check(h.calls.length === 5 && h.prints.length === 0, 'PDF 직전 서버 재확인');
  h.calls[4].resolve({...report(), comment: {...report().comment, shared_comment: '최신 승인 문안'}}); await h.flush();
  check(h.prints.length === 1 && h.prints[0].wrapper.textContent.includes('최신 승인 문안') && !h.prints[0].wrapper.textContent.includes('PRIVATE_'), '출력은 최신 승인 응답만');
  check(h.doc.title === '승인 업체_주간보고서_2026-09-28_2026-10-04' && h.doc.body.classList.contains('ns-printing'), '업체명 주간 기간 출력 이름');
  h.firePrint(); h.firePrint();
  check(h.doc.title === '기존 화면 제목' && !h.doc.body.classList.contains('ns-printing') && !h.doc.body.children.some(n => n.className === 'ns-print-root'), '인쇄 취소와 중복이벤트 정리');
  h.button('승인 보고서 PDF 저장').fire('click'); await h.flush();
  const denied = h.calls.at(-1); denied.reject({status: 503}); await h.flush();
  check(!h.root.textContent.includes('최신 승인 문안') && !h.root.textContent.includes('승인 업체') && h.errors.length === 1 && denied.options.signal.aborted, '원천 오류에서 전부 제거와 요청 취소');

  const j = harness(); j.mount(); await j.flush(); j.calls[0].resolve(listing()); await j.flush();
  j.button('공유 보고서 확인').fire('click'); await j.flush(); j.calls[1].reject({status: 404}); await j.flush();
  check(j.errors.length === 0 && j.root.textContent.includes('승인된 공유 보고서가 아직 없습니다.') && !!j.button('← 업체 목록'), '미승인404는 정상 빈 보고서 안내');

  const r = harness(); r.mount(); await r.flush(); const old = r.calls[0];
  r.all().find(n => n.tag === 'input' && n.type === 'search').value = '새 검색'; r.all().find(n => n.tag === 'form').fire('submit'); await r.flush();
  check(old.options.signal.aborted && r.calls[1].query.q === '새 검색', '새 검색 시 기존 요청 취소');
  r.calls[1].resolve(listing([company(9, '새 권한 화면')], {total: 1})); await r.flush();
  old.resolve(listing([company(10, '낡은 화면')])); await r.flush();
  check(r.root.textContent.includes('새 권한 화면') && !r.root.textContent.includes('낡은 화면'), '늦은 응답이 새 화면을 덮지 않음');
  r.all().find(n => n.tag === 'form').fire('submit'); await r.flush(); const late = r.calls.at(-1); r.win.NaverSalesUI.reset();
  late.resolve(listing()); await r.flush();
  check(r.root.textContent === '' && late.options.signal.aborted, 'reset 후 응답 무효화');

  const m = harness(); m.mount(); await m.flush(); m.calls[0].resolve(listing([company()], {total: 1})); await m.flush();
  const kind = m.all().find(n => n.tag === 'select'); kind.value = 'monthly'; kind.fire('change'); await m.flush();
  const monthly = {kind: 'monthly', start: '2026-09-01', end: '2026-09-30'};
  m.calls[1].resolve(listing([company()], {total: 1, period: monthly})); await m.flush(); m.button('진행 상태 보기').fire('click'); await m.flush();
  check(m.calls[2].query.kind === 'monthly' && m.calls[2].query.anchor === '2026-09-01', '월간 상세 기간 보존');
  m.calls[2].resolve({...company(), stage: '사후관리'}); await m.flush();
  check(m.errors.length === 1 && !m.root.textContent.includes('업체 <img'), '허용 단계 이탈 응답 거절');

  const n = harness(); n.mount(); await n.flush();
  n.calls[0].resolve(listing(Array.from({length: 100}, (_, i) => ({...company(i + 1, '업체' + i), accounts: []})), {total: 100})); await n.flush();
  check(n.all().filter(e => e.className === 'ns-company').length === 100 && n.button('다음').disabled, '100개 업체 페이지 상한');
  const paths = [...h.calls, ...j.calls, ...r.calls, ...m.calls, ...n.calls].map(c => c.path);
  check(paths.every(p => ['/sales/clients', '/sales/detail', '/sales/report'].includes(p)), '전용 조회 API 외 호출 없음');
  check(!/innerHTML|insertAdjacentHTML|localStorage|sessionStorage|fetch\(|XMLHttpRequest/.test(source), 'HTML삽입·저장소·직접네트워크 미사용');

  // Explicit auth/source failures must also clear a previously approved report.
  for (const status of [401, 403]) {
    const auth = harness(); auth.mount(); await auth.flush(); auth.calls[0].resolve(listing()); await auth.flush();
    auth.button('공유 보고서 확인').fire('click'); await auth.flush(); auth.calls[1].resolve(report()); await auth.flush();
    auth.button('승인 보고서 PDF 저장').fire('click'); await auth.flush(); auth.calls[2].reject({status}); await auth.flush();
    check(auth.errors.length === 1 && !auth.root.textContent.includes('승인 업체') && auth.prints.length === 0 && auth.calls[2].options.signal.aborted, status + ' 권한 오류에서 자료와 출력 제거');
  }
  const p = harness(); p.mount(); await p.flush(); p.calls[0].resolve(listing()); await p.flush();
  p.button('공유 보고서 확인').fire('click'); await p.flush(); p.calls[1].resolve(report()); await p.flush();
  p.button('승인 보고서 PDF 저장').fire('click'); await p.flush(); const pendingPrint = p.calls[2]; p.win.NaverSalesUI.reset();
  pendingPrint.resolve(report()); await p.flush();
  check(p.prints.length === 0 && p.root.textContent === '' && pendingPrint.options.signal.aborted, '출력 재확인 중 reset은 늦은 인쇄도 차단');
  const wrong = harness(); wrong.mount(); await wrong.flush(); wrong.calls[0].resolve(listing()); await wrong.flush();
  wrong.button('공유 보고서 확인').fire('click'); await wrong.flush(); wrong.calls[1].resolve({...report(), account_key: key2}); await wrong.flush();
  check(wrong.errors.length === 1 && !wrong.root.textContent.includes('승인 업체') && wrong.prints.length === 0, '다른 계정 보고서 응답 거절');
  console.log(JSON.stringify({suite: 'sales-ui-memory-dom', checks, passed: checks, network_calls: 0, browser_calls: 0, files_written: 0}));
}
run().catch(error => { console.error(error); process.exitCode = 1; });
