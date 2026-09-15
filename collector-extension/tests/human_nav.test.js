/* 사람처럼 넘기기 — 회귀 시험 (2026-09-12, v1.11.0)
 *
 * 왜: 수집기가 페이지를 `chrome.tabs.update({url})` 로 넘겼다. 그건 **주소창에 붙여넣고
 *     엔터**와 같아서 출처(referrer)도 클릭도 없다. 2페이지를 주소창에 쳐서 여는 사람은 없는데
 *     우리는 그걸 시간당 160번 했다. 8/28 에 **새 IP 에서도 첫 요청부터** 막힌 것이 그 증거다.
 *
 * ⚠️ 이 시험은 실제 `pagerClick` 을 가짜 DOM 위에서 돌린다(구조 확인이 아니라 동작 확인).
 */
const fs = require('fs');
const path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'manifest.json'), 'utf8'));

let pass = 0, fail = 0;
const ok = (n, c) => { (c ? pass++ : fail++); console.log(`  ${c ? 'PASS' : 'FAIL'}  ${n}`); };

function grab(name, kind = 'function') {
  const head = kind === 'async' ? `async function ${name}(` : `function ${name}(`;
  const i = SRC.indexOf(head);
  if (i < 0) throw new Error(`${name} 없음`);
  let d = 0, k = SRC.indexOf('{', i);
  for (; k < SRC.length; k++) {
    if (SRC[k] === '{') d++;
    else if (SRC[k] === '}') { d--; if (d === 0) { k++; break; } }
  }
  return SRC.slice(i, k);
}

/** 아주 작은 가짜 DOM — 클릭됐는지만 본다. */
function fakeDom(spec) {
  const clicked = [];
  const mk = (tag, text, opts = {}) => ({
    tagName: tag.toUpperCase(), textContent: text, className: opts.cls || '',
    disabled: !!opts.disabled,
    getAttribute: (a) => (a === 'href' ? (opts.href ?? null)
                        : a === 'aria-label' ? (opts.aria ?? null)
                        : a === 'aria-disabled' ? (opts.ariaDisabled ?? null) : null),
    getBoundingClientRect: () => (opts.hidden ? { width: 0, height: 0 } : { width: 30, height: 20 }),
    click: () => clicked.push(text),
  });
  const scopes = (spec.scopes || []).map((items) => ({
    querySelectorAll: () => items,
  }));
  const doc = {
    querySelectorAll: (sel) => {
      if (/pagination|paging|navigation/.test(sel)) return scopes;
      if (sel === 'a') return spec.anchors || [];
      return [];
    },
  };
  return { doc, clicked, mk };
}

function runPager(spec, target) {
  const { doc, clicked, mk } = fakeDom(spec);
  spec.build && spec.build(mk);
  const fn = new Function('document', `${grab('pagerClick')}; return pagerClick;`)(doc);
  const how = fn(target);
  return { how, clicked };
}

console.log('\n[사람처럼 넘기기]');

// ① 숫자 버튼이 있으면 그걸 클릭한다
{
  let items = [];
  const spec = { scopes: [items], build: (mk) => {
    items.push(mk('a', '1'), mk('a', '2'), mk('a', '3'), mk('a', '다음'));
  } };
  const r = runPager(spec, 2);
  ok('① 2페이지 버튼을 클릭한다', r.how === 'num' && r.clicked[0] === '2');
}

// ② 숫자가 없으면 「다음」을 클릭한다
{
  let items = [];
  const spec = { scopes: [items], build: (mk) => { items.push(mk('button', '다음')); } };
  const r = runPager(spec, 2);
  ok('② 숫자가 없으면 「다음」으로 넘긴다', r.how === 'next' && r.clicked[0] === '다음');
}

// ③ 🔴 비활성 「다음」은 누르지 않는다(마지막 페이지에서 헛클릭 방지)
{
  let items = [];
  const spec = { scopes: [items], build: (mk) => {
    items.push(mk('button', '다음', { ariaDisabled: 'true' }));
  } };
  const r = runPager(spec, 2);
  ok('③ 비활성 「다음」은 안 누른다', r.how === '' && r.clicked.length === 0);
}

// ④ 안 보이는 버튼은 누르지 않는다
{
  let items = [];
  const spec = { scopes: [items], build: (mk) => { items.push(mk('a', '2', { hidden: true })); } };
  const r = runPager(spec, 2);
  ok('④ 화면에 없는 버튼은 안 누른다', r.how === '' && r.clicked.length === 0);
}

// ⑤ 페이지네이션 영역을 못 찾아도 문서 전체에서 찾는다
{
  const spec = { scopes: [], anchors: [] };
  const { doc, clicked, mk } = fakeDom(spec);
  spec.anchors.push(mk('a', '2', { href: '/search/all?pagingIndex=2' }));
  const fn = new Function('document', `${grab('pagerClick')}; return pagerClick;`)(doc);
  ok('⑤ 영역이 없어도 pagingIndex 링크를 찾는다', fn(2) === 'loose' && clicked[0] === '2');
}

// ⑥ 🔴 아무것도 못 찾으면 false — 호출부가 옛 방식으로 폴백해야 한다
{
  const r = runPager({ scopes: [[]] }, 2);
  ok('⑥ 못 찾으면 빈 값을 돌려준다(폴백 신호)', r.how === '');
}

// ⑦ 호출부 계약 — 1장은 주소, 2장부터 클릭, 실패 시 폴백
const fp = grab('fetchPage', 'async');
ok('⑦ 1페이지는 주소로 연다', /pagingIndex <= 1/.test(fp));
ok('⑦ 1페이지 주소에 pagingSize 를 안 붙인다', !/pagingSize=\$\{CFG\.pageSize\}/.test(fp));
ok('⑦ 2페이지부터 클릭을 쓴다', /clickToPage\(tabId, pagingIndex\)/.test(fp));
const FPX = grab('fetchPage', 'async');
ok('⑦ 클릭 실패(버튼 못 찾음) 시에도 주소 이동은 하지 않는다 — 라우터 이동 시도 후 종료',
   /NO_PAGER/.test(FPX) && /주소 이동 안 함 — 라우터 이동 시도/.test(FPX) && !/tabs\.update\(tabId, \{ url \}\);\s*\n\s*await waitNavigated\(tabId, `pagingIndex=\$\{pagingIndex\}`\)/.test(FPX.slice(FPX.indexOf('NO_PAGER'))));
ok('⑦ 폴백을 서버에 한 번 알린다', /NO_PAGER/.test(fp) && /_navMode\.reported = true/.test(fp));

// ⑧ 400위 요구 — 설정값이 실제로 그만큼인가
const cfg = SRC.slice(SRC.indexOf('pageSize:'), SRC.indexOf('maxConsecutiveFail'));
const num = (k) => {
  const m = new RegExp(k + '\\s*:\\s*(\\d+)').exec(cfg);
  return m ? Number(m[1]) : -1;
};
ok('⑧ 깊이 목표가 400위다', num('maxRank') === 400);
ok('⑧ 한 페이지는 화면 기본값 40개다', num('pageSize') === 40);
ok('⑧ 페이지 수가 400위를 채운다 (40 × n ≥ 440)', num('pageSize') * num('pagesPerKeyword') >= 440);

// ⑨ 탭 가시성 — 최소화 창으로 만들지 않는다
const ewt = grab('ensureWorkTab', 'async');
ok('⑨ 전용 창을 normal 로 만든다', /state: 'normal'/.test(ewt));
ok('⑨ 최소화로 만들지 않는다', !/state: 'minimized'/.test(ewt));
ok('⑨ 사람 창을 가리지 않는다(focused:false)', /focused: false/.test(ewt));
ok('⑨ 전용 창 실패 시 종전 방식 폴백이 있다', /배경 탭으로 진행/.test(ewt));

// ⑩ 서버가 「어떻게 넘겼나」를 알 수 있다
ok('⑩ 이동 방식을 meta 로 올린다', /nav: \{ url: _navMode\.url, click: _navMode\.click/.test(SRC));
// v1.11.1(2026-09-15)에서 == 를 >= 로 — 버전이 오를 때마다 이 줄을 고치면 시험이 시험이 아니다.
const _ge = (a, b) => { const x = a.split('.').map(Number), y = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) { if ((x[i]||0) !== (y[i]||0)) return (x[i]||0) > (y[i]||0); } return true; };
ok('⑩ 버전이 올라갔다(1.11.0 이상)', _ge(MANIFEST.version, '1.11.0'));

// ⑪⑫⑬ 2026-09-15 실사고 — 클릭은 됐는데 읽은 건 매번 1페이지(중복 제외 = 담긴 수 × 9).
//     __NEXT_DATA__ 는 SPA 이동으로 안 바뀐다. 라우터 현재 props 를 먼저 읽고, 내용이 바뀔 때까지 기다린다.
console.log('\n[클릭 뒤 내용이 실제로 바뀌었나]');
ok('⑪ pageExtract 가 라우터 현재 props(rt.components[rt.route].props) 를 먼저 본다',
   /rt\.components\s*&&\s*rt\.components\[rt\.route\]/.test(grab('pageExtract')) && /if \(rp\) roots\.push\(\['router', rp\]\);\s*roots\.push\(\['nextdata', nd\]\)/.test(grab('pageExtract')));
{
  // 실제 pageExtract 를 가짜 window 로 돌린다 — __NEXT_DATA__ 는 1페이지, 라우터는 2페이지.
  const pe = grab('pageExtract');
  const mkList = (ids) => ids.map((id) => ({ productTitle: 't' + id, mallName: 'm', id: String(id) }));
  const fakeWin = {
    __NEXT_DATA__: { props: { pageProps: { initialState: { products: { list: mkList([1, 2, 3]).map((item) => ({ item })), total: 999 } } } } },
    next: { router: { route: '/search/all', query: { pagingIndex: '2' },
                      components: { '/search/all': { props: { pageProps: { initialState: { products: { list: mkList([41, 42, 43]).map((item) => ({ item })), total: 999 } } } } } } } },
  };
  const run = new Function('window', 'location', 'document', pe + '\nreturn pageExtract();');
  const r = run(fakeWin, { href: 'https://search.shopping.naver.com/search/all?query=x&pagingIndex=2', search: '?query=x&pagingIndex=2' },
                { title: '네이버쇼핑', body: { innerText: '' } });
  ok('⑪ 라우터에 2페이지가 있으면 그것을 읽는다(첫 상품 41)', !!r && !r.err && r.list && String(r.list[0].id) === '41' && r.src === 'router');
  const fakeWin1 = { __NEXT_DATA__: fakeWin.__NEXT_DATA__ };   // 라우터 없음 → __NEXT_DATA__ 폴백
  const r1 = run(fakeWin1, { href: 'https://search.shopping.naver.com/search/all?query=x', search: '?query=x' },
                 { title: '네이버쇼핑', body: { innerText: '' } });
  ok('⑪ 라우터가 없으면 __NEXT_DATA__ 로 폴백(첫 상품 1 · pageIndex 1)', !!r1 && !r1.err && String(r1.list[0].id) === '1' && r1.pageIndex === 1 && r1.src === 'nextdata');
}
{
  const fio = grab('firstIdOf');
  const f = new Function(fio + '\nreturn firstIdOf;')();
  ok('⑫ firstIdOf — nvMid 우선, 없으면 id, 빈 목록은 빈 문자열',
     f([{ nvMid: 'N1', id: 'I1' }]) === 'N1' && f([{ id: 'I2' }]) === 'I2' && f([]) === '' && f(null) === '');
}
const FP = grab('fetchPage', 'async');
ok('⑫ fetchPage 가 이전 장 ID 집합(prevIds)을 받는다', /async function fetchPage\(keyword, pagingIndex, prevIds\)/.test(SRC));
ok('⑫ 광고 뺀 ID 집합이 이전 장 안에 다 들어 있으면 STALE_PAGE 로 다시 읽는다', /!pageChanged\(out\.list, prevIds\)/.test(FP) && /STALE_PAGE/.test(FP));
// v1.11.3 — 주소 이동 폴백은 **금지**다(v1.11.2 가 그 폴백을 탔다가 pagingIndex=2 주소를 연 1초 뒤 캡차).
{
  const stalePart = FP.slice(FP.indexOf('STALE_PAGE'));
  ok('⑫ 안 넘어가도 주소 이동(chrome.tabs.update)으로 되돌리지 않는다', !/chrome\.tabs\.update/.test(stalePart));
  ok('⑫ 대신 라우터 이동(routerPush)을 한 번 시도한다', /func: routerPush/.test(FP) && /triedRouterPush/.test(FP));
  ok('⑫ 끝내 안 바뀌면 그 키워드는 여기까지만 담고 끝낸다(빈 목록)', /lastErr === 'STALE_PAGE'/.test(FP) && /return \{ total: 0, list: \[\] \}/.test(FP) && /_navMode\.stale \+= 1/.test(FP));
  ok('⑫ 왜 안 넘어갔는지(navProbe)를 서버에 1회 남긴다', /func: navProbe/.test(FP) && /_staleReported/.test(FP) && /STALE_PAGE\(클릭·라우터 이동 뒤 내용 불변\)/.test(FP));
}
{
  // 실제 routerPush 를 가짜 window 로 돌린다 — 라우터가 있으면 pagingIndex 만 바꿔 push 한다.
  const rp = grab('routerPush');
  const calls = [];
  const fakeWin = { next: { router: { pathname: '/search/all', query: { query: 'x', pagingIndex: '1' }, push: (a) => calls.push(a) } } };
  const run = new Function('window', 'location', rp + '\nreturn routerPush(3);');
  const r = run(fakeWin, { pathname: '/search/all' });
  ok('⑫ routerPush — 라우터에 pagingIndex=3 으로 push 한다(주소창 이동 아님)',
     r === 'pushed' && calls.length === 1 && calls[0].pathname === '/search/all' && calls[0].query.pagingIndex === '3' && calls[0].query.query === 'x');
  const r0 = new Function('window', 'location', rp + '\nreturn routerPush(3);')({}, { pathname: '/x' });
  ok('⑫ routerPush — 라우터가 없으면 no-router 로 물러난다(아무 이동도 안 한다)', r0 === 'no-router');
}
ok('⑫ collectKeyword 가 장마다 prevIds 를 넘긴다', /fetchPage\(keyword, i, prevIds\)/.test(SRC) && /prevIds = organicIds\(list\)/.test(SRC));
ok('⑬ 서버 meta.nav 에 stale 이 실린다', /nav: \{ url: _navMode\.url, click: _navMode\.click, fallback: _navMode\.fallback, stale: _navMode\.stale(, src: _navMode\.src)? \}/.test(SRC));
ok('⑬ 버전 1.11.3 이상', _ge(MANIFEST.version, '1.11.3'));


// ⑭ 2026-09-15 v1.11.4 — 「보안 확인」 퍼즐 페이지를 차단으로 알아본다(못 알아보면 매 정시 퍼즐을 두드린다).
console.log('\n[보안 확인 퍼즐을 차단으로 알아보나]');
{
  const pe = grab('pageExtract');
  const run = new Function('window', 'location', 'document', pe + '\nreturn pageExtract();');
  const puzzle = 'NAVER 보안 확인을 완료해 주세요. 이 절차는 귀하가 실제 사용자임을 확인하여 계정을 안전하게 보호하고 스팸을 방지하는 데 도움이 됩니다. 영수증의 가게 위치는 광릉내로 [?] 입니다. (빈 칸을 채워주세요)';
  const r = run({}, { href: 'https://search.shopping.naver.com/search/all?query=x&pagingIndex=2', search: '?query=x&pagingIndex=2' },
                { title: '', body: { innerText: puzzle } });
  ok('⑭ 상품 데이터 없이 「보안 확인」 문구만 있으면 BLOCK_TEXT 로 판정한다', !!r && r.err === 'BLOCK_TEXT');
  const r2 = run({}, { href: 'https://search.shopping.naver.com/search/all?query=x', search: '?query=x' },
                 { title: '', body: { innerText: '아무 상품도 없는 빈 페이지' } });
  ok('⑭ 차단 문구가 없으면 여전히 판독 실패(NO_NEXT_DATA)다 — 과잉 판정 없음', !!r2 && r2.err === 'NO_NEXT_DATA');
  ok('⑭ 버전 1.11.4 이상', _ge(MANIFEST.version, '1.11.4'));
}


// ⑮ v1.11.5 — 페이지마다 맨 위에 같은 광고가 있어도 「바뀜」을 맞게 본다
console.log('\n[바뀜 판정 — 광고 제외 ID 집합]');
{
  const src = grab('organicIds') + '\n' + grab('pageChanged');
  const mk = new Function('RR', src + '\nreturn { organicIds, pageChanged };');
  const RRfake = { isAdItem: (p) => !!p.ad };
  const { organicIds: oi, pageChanged: pc } = mk(RRfake);
  const ad = { id: 'AD1', ad: true };
  const p1 = [ad, { id: 'a' }, { id: 'b' }];
  const p2 = [ad, { id: 'c' }, { id: 'd' }];       // 맨 위 같은 광고 · 상품은 새것
  ok('⑮ 광고는 ID 집합에서 빠진다', oi(p1).join(',') === 'a,b');
  ok('⑮ 맨 위 광고가 같아도 상품이 새로우면 「바뀜」', pc(p2, oi(p1)) === true);
  ok('⑮ 상품이 전부 이전 장 것이면 「안 바뀜」', pc([ad, { id: 'a' }], oi(p1)) === false);
  ok('⑮ 광고뿐인 목록은 「안 바뀜」', pc([ad], oi(p1)) === false);
  ok('⑮ 1페이지(비교 대상 없음)는 항상 「바뀜」', pc(p1, []) === true);
  ok('⑮ 버전 1.11.5 이상', _ge(MANIFEST.version, '1.11.5'));
}


// ⑯ v1.11.6 — 2페이지부터는 내용이 바뀔 때까지 더 기다리고, 화면(DOM) 상품 신호를 프로브에 싣는다
console.log('\n[긴 대기 · DOM 프로브]');
{
  const FP6 = grab('fetchPage', 'async');
  ok('⑯ 2페이지부터 readTriesPaged 만큼 되읽는다', /pagingIndex > 1 \? \(CFG\.readTriesPaged/.test(FP6) && /readTriesPaged: 36/.test(SRC));
  ok('⑯ 라우터 이동은 약 10초(12회) 뒤에 건다', /staleTries >= 12 && !triedRouterPush/.test(FP6));
  const np = grab('navProbe');
  const fakeDoc = {
    querySelectorAll: (sel) => {
      if (sel.indexOf('nvMid=') >= 0) return [{ getAttribute: () => 'https://x/?nvMid=111' }, { getAttribute: () => 'https://x/?nvMid=222' }, { getAttribute: () => 'https://x/?nvMid=111' }];
      if (sel.indexOf('smartstore') >= 0) return [1, 2];
      if (sel.indexOf('/catalog/') >= 0) return [];
      return [];
    },
  };
  const run = new Function('window', 'location', 'document', np + '\nreturn navProbe();');
  const r = run({}, { href: 'https://search.shopping.naver.com/search/all?query=x' }, fakeDoc);
  ok('⑯ navProbe 가 화면 상품 링크 수(nvMid·smartstore·catalog)를 센다', r && r.dom && r.dom.nvMid === 3 && r.dom.smartstore === 2 && r.dom.catalog === 0);
  ok('⑯ navProbe 가 첫 상품 ID 조각을 중복 없이 최대 3개 싣는다', r && Array.isArray(r.domFirst) && r.domFirst.join(',') === '111,222');
  ok('⑯ 버전 1.11.6 이상', _ge(MANIFEST.version, '1.11.6'));
}



// ⑰ v1.13.0 — 화면이 받아 온 응답을 옆에서 읽는다(net_tap.js). 2페이지부터는 그 응답을 가장 먼저 본다.
//   9/15 21:30·21:39 실측: 클릭 뒤 라우터 props·__NEXT_DATA__ 가 29초를 기다려도 1페이지 그대로였다.
//   그 두 곳으로는 「화면이 2페이지를 받았나」를 가릴 수 없다 — 받은 응답 자체를 읽는다.
console.log('\n[응답 가로채기 — net_tap]');
{
  const TAP = fs.readFileSync(path.join(__dirname, '..', 'net_tap.js'), 'utf8');
  const cs = (MANIFEST.content_scripts || [])[0] || {};
  ok('⑰ manifest — net_tap.js 가 MAIN 세계 · document_start 로 네이버쇼핑에만 붙는다',
     (cs.js || []).indexOf('net_tap.js') >= 0 && cs.world === 'MAIN' && cs.run_at === 'document_start'
     && (cs.matches || []).length === 1 && /search\.shopping\.naver\.com/.test(cs.matches[0]));
  ok('⑰ net_tap 은 확장 API 를 쓰지 않는다(페이지 세계)', !/chrome\./.test(TAP));

  // 실제 net_tap.js 를 가짜 window 로 돌린다 — fetch 응답과 XHR 응답이 각각 복사되는지.
  const fetched = [];
  const mkRes = (status, ct, text) => ({
    status, headers: { get: (k) => (k === 'content-type' ? ct : null) },
    clone: () => ({ text: () => Promise.resolve(text) }),
  });
  const origFetch = function nativeFetch(u) { fetched.push(u); return Promise.resolve(origFetch.__next); };
  const xhrHandlers = {};
  class FakeXHR {
    constructor() { this.responseType = ''; this.status = 0; this.responseText = ''; this._h = []; }
    open(m, u) { this._u = u; }
    send() { this._sent = true; }
    addEventListener(ev, fn) { this._h.push([ev, fn]); }
    getResponseHeader() { return 'application/json'; }
    fire() { this._h.forEach(([ev, fn]) => ev === 'loadend' && fn()); }
  }
  const win = { fetch: origFetch, XMLHttpRequest: FakeXHR };
  const runTap = new Function('window', 'location', TAP);
  runTap(win, { href: 'https://search.shopping.naver.com/search/all?query=x' });
  ok('⑰ 설치되면 window.__mcTap 이 생긴다(items·misses 비어 있음)',
     win.__mcTap && Array.isArray(win.__mcTap.items) && win.__mcTap.items.length === 0 && win.__mcTap.misses.length === 0);
  ok('⑰ 감싼 fetch 의 toString 이 원본과 같다(감싼 흔적 없음)',
     win.fetch !== origFetch && win.fetch.toString() === Function.prototype.toString.call(origFetch));
  runTap(win, { href: 'https://search.shopping.naver.com/' });
  const wrappedOnce = win.fetch;
  ok('⑰ 두 번 들어와도 한 번만 감싼다', win.fetch === wrappedOnce && win.__mcTap.items.length === 0);

  const body2 = JSON.stringify({ shoppingResult: { total: 2265, products: [
    { nvMid: '9001', productTitle: 't1', mallName: 'm' }, { nvMid: '9002', productTitle: 't2', mallName: 'm' },
    { nvMid: '9001', productTitle: 'dup', mallName: 'm' }, { nvMid: '9003', productTitle: 't3', mallName: 'm' } ] } });
  origFetch.__next = mkRes(200, 'application/json;charset=utf-8', body2);
  (async () => {
    await win.fetch('https://search.shopping.naver.com/api/search/all?query=x&pagingIndex=2&sort=rel');
    await new Promise((r) => setTimeout(r, 5));
    const it = win.__mcTap.items[0];
    ok('⑰ 상품 표식이 있는 응답은 items 에 들어간다(경로·pagingIndex·상태·크기)',
       !!it && it.page === 2 && it.status === 200 && it.path === 'search.shopping.naver.com/api/search/all' && it.size === body2.length);
    ok('⑰ items 에 JSON 본문과 앞 3개 ID(중복 없음)가 남는다',
       !!it && it.json && it.json.shoppingResult.total === 2265 && it.ids.join(',') === '9001,9002,9003');
    ok('⑰ 원래 fetch 는 그대로 불렸다(요청을 더 보내지 않는다)', fetched.length === 1);

    origFetch.__next = mkRes(418, 'text/html', '<html>보안 확인</html>');
    await win.fetch('https://search.shopping.naver.com/api/search/all?query=x&pagingIndex=3');
    await new Promise((r) => setTimeout(r, 5));
    const ms = win.__mcTap.misses[0];
    ok('⑰ 상품이 없는 응답(차단 418 HTML)은 misses 에 상태·앞 80자만 남는다',
       win.__mcTap.items.length === 1 && !!ms && ms.status === 418 && ms.page === 3 && /보안 확인/.test(ms.head) && ms.json === undefined);

    origFetch.__next = mkRes(200, 'image/png', 'PNG"nvMid"');
    await win.fetch('https://x/img.png');
    await new Promise((r) => setTimeout(r, 5));
    ok('⑰ 글자 계열이 아닌 응답(image)은 아예 안 본다', win.__mcTap.items.length === 1 && win.__mcTap.misses.length === 1);

    const x = new win.XMLHttpRequest();
    x.open('GET', '/api/search/all?query=x&pagingIndex=4');
    x.send();
    x.status = 200; x.responseText = JSON.stringify({ products: [{ nvMid: '77', productTitle: 'a', mallName: 'b' }] });
    x.fire();
    ok('⑰ XHR 응답도 같은 규칙으로 복사된다', win.__mcTap.items.length === 2 && win.__mcTap.items[1].page === 4 && win.__mcTap.items[1].ids[0] === '77');
    ok('⑰ items 는 최근 6건만 남긴다', (() => { for (let i = 0; i < 10; i++) { const y = new win.XMLHttpRequest(); y.open('GET', '/a?pagingIndex=' + i); y.send(); y.status = 200; y.responseText = '{"nvMid":"1"}'; y.fire(); } return win.__mcTap.items.length === 6; })());

    // pageExtract — 2페이지를 원하면 tap 을 가장 먼저 읽는다. 1페이지는 종전 그대로.
    const pe = grab('pageExtract');
    const mkList = (ids) => ids.map((id) => ({ productTitle: 't' + id, mallName: 'm', id: String(id) }));
    const routerP1 = { pageProps: { initialState: { products: { list: mkList([1, 2, 3]).map((item) => ({ item })), total: 999 } } } };
    const fakeWin = {
      __NEXT_DATA__: { props: routerP1 },
      next: { router: { route: '/search/all', query: { pagingIndex: '2' }, components: { '/search/all': { props: routerP1 } } } },
      __mcTap: { items: [
        { at: 1000, page: 0, path: 'h/old', json: { products: mkList([501, 502]) } },
        { at: 5000, page: 2, path: 'search.shopping.naver.com/api/search/all', json: { shoppingResult: { total: 2265, products: mkList([41, 42, 43]) } } },
      ] },
    };
    const run = new Function('window', 'location', 'document', pe + '\nreturn pageExtract(WANT);'.replace('WANT', 'arguments[3]'));
    const loc = { href: 'https://search.shopping.naver.com/search/all?query=x', search: '?query=x' };
    const doc = { title: '네이버쇼핑', body: { innerText: '' } };
    const r2 = run(fakeWin, loc, doc, { page: 2, since: 4000 });
    ok('⑰ pageExtract — 2페이지를 원하면 tap 의 pagingIndex=2 응답을 읽는다(라우터가 1페이지여도)',
       !!r2 && !r2.err && r2.src === 'tap' && String(r2.list[0].id) === '41' && r2.total === 2265 && /api\/search\/all/.test(r2.tapPath));
    const fakeWinSince = { ...fakeWin, __mcTap: { items: [
      { at: 1000, page: 0, path: 'h/old', json: { products: mkList([501, 502]) } },
      { at: 5000, page: 0, path: 'h/new', json: { products: mkList([61, 62]) } } ] } };
    const r2b = run(fakeWinSince, loc, doc, { page: 2, since: 4000 });
    ok('⑰ pageExtract — 주소에 pagingIndex 가 없으면 「클릭 뒤 도착한 것」을 고른다', !!r2b && r2b.src === 'tap' && String(r2b.list[0].id) === '61');
    const r2c = run(fakeWinSince, loc, doc, { page: 2, since: 6000 });
    ok('⑰ pageExtract — 클릭 뒤 도착한 응답이 없으면 종전대로 라우터를 읽는다', !!r2c && r2c.src === 'router' && String(r2c.list[0].id) === '1');
    const r1 = run(fakeWin, loc, doc, { page: 1, since: 0 });
    ok('⑰ pageExtract — 1페이지는 tap 을 보지 않는다(종전 그대로 라우터/__NEXT_DATA__)', !!r1 && r1.src === 'router' && String(r1.list[0].id) === '1');
    const r0 = run({ __NEXT_DATA__: { props: routerP1 } }, loc, doc);
    ok('⑰ pageExtract — 인자 없이 불러도(회귀 시험·구버전 경로) 종전과 같다', !!r0 && r0.src === 'nextdata' && String(r0.list[0].id) === '1');
    const rBad = run({ ...fakeWin, __mcTap: { items: [{ at: 5000, page: 2, json: { foo: 'bar' } }] } }, loc, doc, { page: 2, since: 4000 });
    ok('⑰ pageExtract — tap 응답에 상품이 없으면 라우터로 넘어간다(막히지 않는다)', !!rBad && rBad.src === 'router');

    // fetchPage 배선
    const FP = grab('fetchPage', 'async');
    ok('⑰ fetchPage 가 클릭 시각(_clickedAt)을 적고 pageExtract 에 {page, since} 를 넘긴다',
       /_clickedAt = Date\.now\(\);/.test(FP) && /func: pageExtract, args: \[\{ page: pagingIndex, since: _clickedAt \}\]/.test(FP));
    ok('⑰ STALE 때 응답 요약(TAP_PROBE)을 따로 한 건 더 보낸다(서버 500자 한도)', /TAP_PROBE\(화면이 받은 응답 요약\)/.test(FP) && /delete probe\.tap/.test(FP));
    ok('⑰ STALE 보고는 짧은 값(click·push·prev·got·src)이 앞에 온다', /const front = \{ click: _lastClickBranch, push: _lastPushResult, prev:/.test(FP));
    ok('⑰ 2페이지부터 어느 출처(tap/router/nextdata)에서 읽었는지 meta.nav.src 로 센다', /_navMode\.src\[out\.src/.test(FP) && /src: _navMode\.src \}/.test(SRC));
    ok('⑰ 주소창 pagingIndex 이동은 여전히 0곳', (SRC.match(/pagingIndex=\$\{pagingIndex\}`;/g) || []).length === 0 && !/chrome\.tabs\.update\(tabId, \{ url: [^}]*pagingIndex/.test(SRC));

    // navProbe — tap 요약
    const np = grab('navProbe');
    const runNp = new Function('window', 'location', 'document', np + '\nreturn navProbe();');
    const fakeDoc = { querySelectorAll: () => [] };
    const pr = runNp({ __mcTap: { items: [{ at: Date.now() - 3000, page: 2, status: 200, size: 12345, path: 'search.shopping.naver.com/api/search/all', ids: ['1', '2'] }],
                                  misses: [{ at: Date.now() - 1000, page: 0, status: 418, size: 80, path: 'search.shopping.naver.com/x' }] } },
                     { href: 'https://search.shopping.naver.com/search/all?query=x' }, fakeDoc);
    ok('⑰ navProbe 가 tap 요약(건수·최근 항목 · 값 없이)을 싣는다',
       pr && pr.tap && pr.tap.n === 1 && pr.tap.m === 1 && /^\d+s\|p2\|200\|12345\|/.test(pr.tap.items[0]) && /\|1,2$/.test(pr.tap.items[0]) && /\|418\|80\|/.test(pr.tap.misses[0]));
    const pr0 = runNp({}, { href: 'https://x' }, fakeDoc);
    ok('⑰ net_tap 이 없는 탭(교체 전 열린 탭)은 tap: none 으로 밝힌다', pr0 && pr0.tap === 'none');
    ok('⑰ 버전 1.13.0 이상(안전 중지판 1.12.0 보다 위)', _ge(MANIFEST.version, '1.13.0'));

    console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : '\n사람처럼 넘기기 시험 전부 통과');
    process.exit(fail ? 1 : 0);
  })();
}

