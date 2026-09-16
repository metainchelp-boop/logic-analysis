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
  const scrolled = [];
  const mk = (tag, text, opts = {}) => ({
    tagName: tag.toUpperCase(), textContent: text, className: opts.cls || '',
    disabled: !!opts.disabled,
    getAttribute: (a) => (a === 'href' ? (opts.href ?? null)
                        : a === 'aria-label' ? (opts.aria ?? null)
                        : a === 'aria-disabled' ? (opts.ariaDisabled ?? null) : null),
    // ⚠️ left·top 은 v1.15.0 의 pagerLocate 가 좌표를 내려면 필요하다. 기존 시험은 width·height 만
    //    보므로 값을 더해도 영향이 없다(일부러 더하기만 했다).
    getBoundingClientRect: () => (opts.hidden ? { width: 0, height: 0, left: 0, top: 0 }
                                              : { width: 30, height: 20, left: opts.left ?? 100, top: opts.top ?? 200 }),
    scrollIntoView: () => { scrolled.push(text); },
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
  return { doc, clicked, scrolled, mk };
}

function runPager(spec, target) {
  const { doc, clicked, mk } = fakeDom(spec);
  spec.build && spec.build(mk);
  const fn = new Function('document', `${grab('pagerClick')}; return pagerClick;`)(doc);
  const how = fn(target);
  return { how, clicked };
}

/** v1.15.0 — 실제 `pagerLocate` 를 같은 가짜 DOM 위에서 돌린다(찾기만 하고 누르지 않아야 한다). */
function runLocate(spec, target, win) {
  const { doc, clicked, scrolled, mk } = fakeDom(spec);
  spec.build && spec.build(mk);
  const fn = new Function('document', 'window',
    `${grab('pagerLocate')}; return pagerLocate;`)(doc, win || { innerWidth: 1280, innerHeight: 900 });
  const spot = fn(target);
  return { spot, clicked, scrolled };
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
ok('⑦ 클릭 실패(버튼 못 찾음) 시에도 주소 이동은 하지 않는다 — 키워드 종료(v1.13.1: 라우터 이동도 없음)',
   !/tabs\.update\([^)]*pagingIndex/.test(fp) && /return \{ total: 0, list: \[\] \};   \/\/ 이 키워드는 여기까지/.test(fp) && !/func: routerPush/.test(fp));
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
  // v1.13.1 — routerPush 는 삭제됐다(그 이동이 주소창 이동으로 되돌아가 퍼즐을 불렀다 · 22:02 실측).
  ok('⑫ 라우터 이동(routerPush)을 걸지 않는다(v1.13.1 에서 삭제)', !/func: routerPush/.test(SRC) && !/triedRouterPush/.test(SRC));
  ok('⑫ 끝내 안 바뀌면 그 키워드는 여기까지만 담고 끝낸다(빈 목록)', /lastErr === 'STALE_PAGE'/.test(FP) && /return \{ total: 0, list: \[\] \}/.test(FP) && /_navMode\.stale \+= 1/.test(FP));
  ok('⑫ 왜 안 넘어갔는지(navProbe)를 서버에 1회 남긴다', /func: navProbe/.test(FP) && /_staleReported/.test(FP) && /STALE_PAGE\(클릭 뒤 내용 불변\)/.test(FP));
}
{
  // v1.13.1 — routerPush 함수 자체가 없어야 한다(되살리면 여기서 걸린다).
  ok('⑫ routerPush 함수가 소스에 없다(v1.13.1 삭제 · 되살리기 금지)', !/function routerPush\(/.test(SRC) && !/rt\.push\(/.test(SRC));
}
ok('⑫ collectKeyword 가 장마다 prevIds 를 넘긴다', /fetchPage\(keyword, i, prevIds\)/.test(SRC) && /prevIds = organicIds\(list\)/.test(SRC));
// ⚠️ 2026-09-16 — 이 줄은 원래 `nav: { … }` 를 **글자 그대로** 박아 두어, 필드를 하나 더할 때마다
//    코드가 멀쩡한데도 실패했다(v1.15.0·v1.17.0 에서 두 번). 지금은 **뜻**만 본다 — nav 안에 stale 이 있는가.
ok('⑬ 서버 meta.nav 에 stale 이 실린다', /nav: \{[\s\S]{0,500}?stale: _navMode\.stale/.test(SRC));
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
  ok('⑯ 클릭 뒤엔 기다리기만 한다(라우터 이동 없음 · v1.13.1)', !/staleTries >= 12/.test(FP6) && /staleTries \+= 1; lastErr = 'STALE_PAGE'/.test(FP6));
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
    ok('⑰ STALE 때 응답 요약(TAP_PROBE)을 따로 한 건 더 보낸다(서버 500자 한도)', /TAP_PROBE\(화면이 받은 응답 요약\)/.test(SRC) && /delete probe\.tap/.test(FP));
    // ⚠️ 위 ⑬ 과 같은 이유로 글자 그대로 박지 않는다 — front 맨 앞이 click 이고 prev 가 그 안에 있으면 된다.
    ok('⑰ STALE 보고는 짧은 값(click·prev·got·src)이 앞에 온다',
       /const front = \{ click: _lastClickBranch,[\s\S]{0,300}?prev: \(prevIds \|\| \[\]\)\.length/.test(FP));
    ok('⑰ 2페이지부터 어느 출처(tap/router/nextdata)에서 읽었는지 meta.nav.src 로 센다',
       /_navMode\.src\[out\.src/.test(FP) && /src: _navMode\.src/.test(SRC));
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

    // ⑱ v1.13.1 — 22:02 실측: v1.13.0 첫 회차가 2페이지에서 퍼즐. 주소 `?query=…&pagingIndex=2` 는 routerPush 가 만드는 모양이고
    //   Next 가 그 데이터를 못 받으면 주소창 이동으로 되돌린다. 퍼즐 세 건(21:17·21:18·22:02) 전부 그 모양 = 주소 이동과 같은 표식.
    //   ⇒ routerPush 삭제. 그리고 tap 요약을 STALE 만이 아니라 BLOCK_TEXT·판독 실패·NO_PAGER 에서도 남긴다(22:02 는 tap 이 안 남았다).
    console.log('\n[v1.13.1 — 라우터 이동 삭제 · 네 갈래 tap 보고]');
    const TR = grab('tapReport', 'async');
    ok('⑱ tapReport 가 navProbe 를 돌려 TAP_PROBE 로 why·q·tap 을 보낸다', /func: navProbe/.test(TR) && /TAP_PROBE\(화면이 받은 응답 요약\)/.test(TR) && /why: why, q: probe\.q/.test(TR));
    const blockPart = FP.slice(FP.indexOf("out.err === 'BLOCK_TEXT'"), FP.indexOf('throw new Error(`BLOCKED:${out.title'));
    ok('⑱ BLOCK_TEXT(퍼즐·차단 문구) 직전에 tap 요약을 남긴다', /await tapReport\(tabId, keyword, pagingIndex, 'BLOCK_TEXT'\)/.test(blockPart));
    ok('⑱ STALE 끝에도 tap 요약을 남긴다', /await tapReport\(tabId, keyword, pagingIndex, 'STALE'\)/.test(FP));
    const failPart = FP.slice(FP.indexOf("note: '판독 실패(차단 아님)'"));
    ok('⑱ 판독 실패에도 tap 요약을 남긴다', /await tapReport\(tabId, keyword, pagingIndex, lastErr\)/.test(failPart));
    ok('⑱ NO_PAGER 는 라우터 이동 없이 키워드를 끝내고 tap 요약을 남긴다', /NO_PAGER\(페이지 버튼 못 찾음\)/.test(FP) && /await tapReport\(tabId, keyword, pagingIndex, 'NO_PAGER'\)/.test(FP) && !/_lastPushResult/.test(SRC));
    ok('⑱ 주소창·라우터 어느 쪽으로도 pagingIndex 이동을 만들지 않는다', !/rt\.push/.test(SRC) && !/tabs\.update\([^)]*pagingIndex/.test(SRC) && (SRC.match(/pagingIndex=\$\{pagingIndex\}`;/g) || []).length === 0);
    ok('⑱ 버전 1.13.1 이상', _ge(MANIFEST.version, '1.13.1'));


    // ⑲ v1.14.0 — 9/16 실측(p2 418)을 반박 검증한 뒤 드러난 두 구멍을 메운다.
    //   ⑴ 418 본문을 못 봐서 「퍼즐인가 차단문인가 오류인가」를 못 갈랐다(net_tap 은 head 를 갖고 있었는데 버렸다).
    //   ⑵ 창·문서 상태(포커스·가시성·사용자 입력·자동화 표식·직전 주소)를 한 번도 안 쟀다 — 전부 코드 추론이었다.
    //   ⑶ 사람 시험은 확장이 꺼져 있어 net_tap 이 안 돌았다 ⇒ 같은 자로 잰 값이 0건이었다.
    console.log('\n[v1.14.0 — 418 본문 · 창 상태 · 사람 화면 같은 자로 재기]');
    {
      const np = grab('navProbe');
      const runNp = new Function('window', 'location', 'document', 'navigator', np + '\nreturn navProbe();');
      const emptyDoc = { querySelectorAll: () => [], hasFocus: () => false, visibilityState: 'visible', referrer: '' };

      // env — 다섯 값이 11글자로
      const r1 = runNp({}, { href: 'https://x' },
        { querySelectorAll: () => [], hasFocus: () => true, visibilityState: 'visible', referrer: 'https://search.shopping.naver.com/' },
        { userActivation: { hasBeenActive: true, isActive: false }, webdriver: false });
      ok('⑲ navProbe env — 사람 창 모양(f1 v1 a10 w0 r1)', r1 && r1.env === 'f1v1a10w0r1');
      const r0 = runNp({}, { href: 'https://x' },
        { querySelectorAll: () => [], hasFocus: () => false, visibilityState: 'hidden', referrer: '' },
        { userActivation: { hasBeenActive: false, isActive: false }, webdriver: true });
      ok('⑲ navProbe env — 배경·무입력·자동화 모양(f0 v0 a00 w1 r0)', r0 && r0.env === 'f0v0a00w1r0');
      const rNoUA = runNp({}, { href: 'https://x' }, emptyDoc, {});
      ok('⑲ navProbe env — userActivation 이 없는 크롬에서도 죽지 않는다', rNoUA && rNoUA.env === 'f0v1a00w0r0');

      // 거절 응답 본문 앞머리 + 4xx 우선
      const mk = (at, page, status, size, path, head) => ({ at, page, status, size, path, head });
      const T = { items: [], misses: [
        mk(1000, 0, 200, 88379, 'x/api/modules/gnb/category/list'),
        mk(1000, 0, 200, 16910, 'nam.veta.naver.com/gfp/v1'),
        mk(1000, 0, 200, 30024, 'nam.veta.naver.com/gfp/v1'),
        mk(1000, 0, 200, 102, 'ncpt.naver.com/v2/tokens'),
        mk(1000, 0, 418, 2657, 'shopping.naver.com/api/product-zzim/products', 'NAVER 보안 확인을 완료해   주세요.\n이 절차는'),
        mk(2000, 2, 418, 2657, 'search.shopping.naver.com/api/search/all', '쇼핑 서비스 접속이 일시적으로 제한되었습니다'),
      ] };
      const r2 = runNp({ __mcTap: T }, { href: 'https://x' }, emptyDoc, {});
      // 거절 3건 + 나머지 3건 상한이라 6건 중 5건이 실린다(418 두 건 + 200 세 건).
      const bad2 = r2 ? r2.tap.misses.filter((x) => /\|4\d\d\|/.test(x)) : [];
      const rest2 = r2 ? r2.tap.misses.filter((x) => !/\|4\d\d\|/.test(x)) : [];
      ok('⑲ 거절(4xx) 응답이 목록 맨 앞에 온다(서버 500자 절단에서 먼저 살아남게)',
         r2 && r2.tap.misses.length === 5 && bad2.length === 2 && rest2.length === 3
            && r2.tap.misses.slice(0, 2).every((x) => /\|4\d\d\|/.test(x)));
      ok('⑲ 418 항목에 본문 앞머리가 붙고 줄바꿈·연속공백은 한 칸으로 접힌다',
         bad2.some((x) => /\|쇼핑 서비스 접속이 일시적으로 제한되었습니다$/.test(x))
         && bad2.some((x) => /\|NAVER 보안 확인을 완료해 주세요\. 이 절차는$/.test(x)));
      ok('⑲ 200 항목에는 본문을 안 싣는다(칸 5개 그대로)',
         rest2.length === 3 && rest2.every((x) => x.split('|').length === 5));
      const rLong = runNp({ __mcTap: { items: [], misses: [mk(1000, 2, 418, 99, 'h/p', 'ㄱ'.repeat(200))] } },
                          { href: 'https://x' }, emptyDoc, {});
      ok('⑲ 본문 앞머리는 40자에서 자른다', rLong && rLong.tap.misses[0].split('|')[5].length === 40);
      ok('⑲ m 은 자르기 전 전체 건수를 그대로 센다', r2 && r2.tap.m === 6);

      // tapReport — env 를 싣고 이름표를 받는다
      const TR = grab('tapReport', 'async');
      ok('⑲ tapReport 가 env 를 본문에 싣는다', /env: probe\.env \|\| ''/.test(TR));
      ok('⑲ tapReport 가 err 이름표를 받아 쓴다(기본값은 종전 그대로)',
         /async function tapReport\(tabId, keyword, pagingIndex, why, errLabel\)/.test(TR)
         && /err: errLabel \|\| 'TAP_PROBE\(화면이 받은 응답 요약\)'/.test(TR));
      ok('⑲ 기존 네 갈래 호출은 이름표를 안 넘긴다(종전 동작 무변경)',
         (SRC.match(/tapReport\(tabId, keyword, pagingIndex, '(BLOCK_TEXT|STALE|NO_PAGER)'\)/g) || []).length === 3
         && /tapReport\(tabId, keyword, pagingIndex, lastErr\)/.test(SRC));

      // 🔍 사람 화면 버튼 — 세 파일이 이어져 있나
      const POPUP_HTML = fs.readFileSync(path.join(__dirname, '..', 'popup.html'), 'utf8');
      const POPUP_JS = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');
      ok('⑲ 팝업에 「이 화면 응답 보내기」 버튼이 있다', /id="humanProbe"/.test(POPUP_HTML) && /이 화면 응답 보내기/.test(POPUP_HTML));
      ok('⑲ 팝업 스크립트가 그 버튼을 humanProbe 로 배선한다', /\$\('humanProbe'\)\.onclick/.test(POPUP_JS) && /cmd: 'humanProbe'/.test(POPUP_JS));
      const hp = SRC.slice(SRC.indexOf("msg?.cmd === 'humanProbe'"), SRC.indexOf("msg?.cmd === 'slowOff'"));
      ok('⑲ 배경이 humanProbe 를 받아 사람이 보는 탭을 골라 잰다',
         /chrome\.tabs\.query\(\{ url: '\*:\/\/search\.shopping\.naver\.com\/\*' \}\)/.test(hp)
         && /tabs\.find\(\(x\) => x\.active\) \|\| tabs\[0\]/.test(hp)
         && /tapReport\(t\.id, '\(사람 시험\)', 0, 'HUMAN', 'HUMAN_PROBE\(사람이 연 화면\)'\)/.test(hp));
      ok('⑲ 화면이 안 열려 있으면 알려 주고 아무것도 안 한다', /검색 결과 화면이 안 열려 있습니다/.test(hp));
      ok('⑲ 이 버튼은 네이버에 요청을 더 보내지 않는다(이미 받은 응답만 읽는다)',
         !/fetch\(/.test(hp) && !/tabs\.update/.test(hp) && !/windows\.create/.test(hp));

      ok('⑲ 주소창·라우터 pagingIndex 이동은 여전히 0곳', !/rt\.push/.test(SRC) && (SRC.match(/pagingIndex=\$\{pagingIndex\}`;/g) || []).length === 0);
      ok('⑲ 버전 1.14.0 이상', _ge(MANIFEST.version, '1.14.0'));

      /* ⑳ v1.15.0 — 페이지 넘김을 브라우저 표준 입력 경로(chrome.debugger + CDP)로.
       *
       * 왜 이 시험이 필요한가: 찾는 규칙이 **두 벌**이 됐다
       *   (pagerClick = 찾아서 누름 / pagerLocate = 찾아서 좌표만).
       *   한쪽만 고치면 두 경로가 **서로 다른 버튼**을 누르게 되어 비교가 무의미해진다.
       *   ⭐ 이 저장소가 반복해 온 함정이 정확히 그것이다 — 「같은 일을 하는 파일·경로가 둘」.
       */
      console.log('\n[⑳ 표준 입력 클릭 — v1.15.0]');
      const PH = fs.readFileSync(path.join(__dirname, '..', 'popup.html'), 'utf8');
      const PJ = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');

      // — 찾기 규칙이 pagerClick 과 **같은 답**을 내는가(세 갈래 전부) —
      {
        // ⚠️ 두 규칙을 **각각 새 spec 으로** 돌린다. 하나를 나눠 쓰면 `build` 가 같은 배열에
        //    두 번 밀어 넣어, 뒤 호출이 앞 호출이 만든 가짜 요소를 집는다(2026-09-16 실제로 겪음).
        const mkSpec = () => {
          const items = [];
          return { scopes: [items], build: (mk) => {
            items.push(mk('a', '1'), mk('a', '2'), mk('a', '3'), mk('a', '다음'));
          } };
        };
        const c = runPager(mkSpec(), 2);
        const l = runLocate(mkSpec(), 2);
        ok('⑳ 숫자 갈래 — 두 규칙이 같은 가지를 고른다', c.how === 'num' && l.spot && l.spot.branch === 'num');
        ok('⑳ 좌표는 그 버튼의 가운데다', l.spot.x === 115 && l.spot.y === 210);
        ok('⑳ 찾기만 하고 누르지는 않는다', l.clicked.length === 0);
        ok('⑳ 화면 밖일 수 있으니 먼저 가운데로 끌어온다', l.scrolled[0] === '2');
      }
      {
        let items = [];
        const spec = { scopes: [items], build: (mk) => { items.push(mk('button', '다음')); } };
        ok('⑳ 「다음」 갈래 — 두 규칙이 같은 가지를 고른다',
           runPager(spec, 2).how === 'next' && (runLocate(spec, 2).spot || {}).branch === 'next');
      }
      {
        const spec = { scopes: [[]], anchors: [] };
        const { doc, mk } = fakeDom(spec);
        spec.anchors.push(mk('a', '2', { href: '/search/all?pagingIndex=2' }));
        const fnL = new Function('document', 'window', `${grab('pagerLocate')}; return pagerLocate;`)(
          doc, { innerWidth: 1280, innerHeight: 900 });
        ok('⑳ 느슨한 갈래 — pagingIndex 링크도 같게 찾는다', (fnL(2) || {}).branch === 'loose');
      }
      // — 안 눌러야 할 것은 여기서도 안 찾는다 —
      {
        let items = [];
        const spec = { scopes: [items], build: (mk) => { items.push(mk('button', '다음', { ariaDisabled: 'true' })); } };
        ok('⑳ 비활성 「다음」은 좌표를 안 준다', runLocate(spec, 2).spot === null);
      }
      {
        let items = [];
        const spec = { scopes: [items], build: (mk) => { items.push(mk('a', '2', { hidden: true })); } };
        ok('⑳ 안 보이는 버튼은 좌표를 안 준다', runLocate(spec, 2).spot === null);
      }
      ok('⑳ 못 찾으면 null — 호출부가 합성 클릭으로 폴백한다', runLocate({ scopes: [[]] }, 2).spot === null);
      {
        let items = [];
        const spec = { scopes: [items], build: (mk) => { items.push(mk('a', '2', { left: 5000, top: 200 })); } };
        ok('⑳ 창 밖 좌표면 포기한다(엉뚱한 곳 클릭 방지)',
           runLocate(spec, 2, { innerWidth: 1280, innerHeight: 900 }).spot === null);
      }

      // — 배선: 표준 입력을 먼저 쓰고, 실패하면 반드시 폴백 —
      const ctp = grab('clickToPage', 'async');
      ok('⑳ clickToPage 가 표준 입력을 먼저 시도한다',
         /await trustedEnabled\(\)/.test(ctp) && /await trustedClickToPage\(tabId, target\)/.test(ctp));
      ok('⑳ 실패하면 종전 합성 클릭으로 폴백한다(수집이 통째로 죽지 않게)',
         /func: pagerClick/.test(ctp) && ctp.indexOf('trustedClickToPage') < ctp.indexOf('func: pagerClick'));
      ok('⑳ 어느 쪽으로 눌렀는지 기록한다', /_lastClickHow = 'trusted'/.test(ctp) && /_lastClickHow = 'synth'/.test(ctp));

      const tcp = grab('trustedClickToPage', 'async');
      ok('⑳ 누를 때만 붙고 **반드시** 뗀다(띠가 남지 않게)',
         /finally \{\s*if \(attached\) await dbgDetach\(tabId\);/.test(tcp));
      ok('⑳ 사람 손과 같은 순서 — 움직임·누름·뗌',
         tcp.indexOf("'mouseMoved'") < tcp.indexOf("'mousePressed'")
         && tcp.indexOf("'mousePressed'") < tcp.indexOf("'mouseReleased'"));
      ok('⑳ 떼자마자 detach 하지 않는다(화면이 처리할 틈을 준다)',
         /mouseReleased'[^]*?await sleep\(200\)/.test(tcp));
      ok('⑳ 실패 사유를 남겨 서버에서 보이게 한다', /_trustedNote = String\(/.test(tcp));
      ok('⑳ debugger API 가 없으면 조용히 폴백한다', /if \(!chrome\.debugger\)/.test(tcp));

      ok('⑳ manifest 에 debugger 권한이 있다', (MANIFEST.permissions || []).includes('debugger'));
      ok('⑳ 버전 1.15.0 이상', _ge(MANIFEST.version, '1.15.0'));

      // — 끌 수 있어야 한다 · 기본값이 팝업과 배경에서 **같아야** 한다 —
      ok('⑳ 팝업에 끄고 켜는 버튼이 있다', /id="trusted"/.test(PH) && /진짜 입력으로 클릭/.test(PH));
      ok('⑳ 팝업이 그 버튼을 저장값 trustedClick 에 배선한다',
         /\$\('trusted'\)\.onclick/.test(PJ) && /trustedClick: !on/.test(PJ));
      ok('⑳ 기본값이 양쪽 다 「켬」이다(화면과 실제가 어긋나지 않게)',
         /trustedClick === undefined \? true/.test(grab('trustedEnabled', 'async'))
         && /trustedClick === undefined \? true/.test(PJ));

      // — 서버가 집계로 갈라 볼 수 있어야 한다 —
      ok('⑳ 업로드 meta 에 how(표준/합성)를 싣는다', /how: _navMode\.how/.test(SRC));
      ok('⑳ STALE 보고에도 how 를 싣는다', /const front = \{ click: _lastClickBranch, how: _lastClickHow/.test(SRC));
      ok('⑳ 키워드마다 how 를 0으로 되돌린다', (SRC.match(/how: \{ trusted: 0, synth: 0 \}/g) || []).length >= 2);

      // — 🔴 넘지 않기로 한 선 —
      ok('⑳ CDP 는 입력(마우스·키보드)만 쓴다 — 통신·화면 가로채기 명령 0곳',
         (SRC.match(/'(Input|Network|Fetch|Emulation|Page|Security|Target)\.[A-Za-z]+'/g) || [])
           .every((m) => m.startsWith("'Input.")));
      ok('⑳ UA·헤더·쿠키를 손대지 않는다(권한에도 없다)',
         !/declarativeNetRequest|webRequest|cookies/.test(JSON.stringify(MANIFEST)));
      ok('⑳ 주소창·라우터 이동은 여전히 0곳(v1.11.3·v1.13.1 교훈 유지)',
         !/rt\.push/.test(SRC) && (SRC.match(/pagingIndex=\$\{pagingIndex\}`;/g) || []).length === 0);

      /* ㉑ v1.16.0 — 검색창에 쳐서 들어가기.
       *
       * 왜: 9/16 실측에서 **사람은 `/api/search/all` 200, 기계는 `_next/data/….json` 418** 이었다.
       *   같은 기계·회선·크롬인데 부르는 주소가 달랐고, 다른 것은 **1페이지에 어떻게 들어갔는가**
       *   하나였다(사람=검색창, 기계=주소 직접 열기). 그 차이를 없앤다.
       * 🔴 여기서도 넘지 않는 선 — **퍼즐 칸에는 아무것도 입력하지 않는다.**
       */
      console.log('\n[㉑ 사람 경로로 들어가기 — v1.17.0]');
      const sbl = grab('searchBoxLocate');
      const stl = grab('shopTabLocate');
      const tae = grab('typeAndEnter', 'async');
      const pe = grab('portalEntry', 'async');
      const sbe = grab('shopBoxEntry', 'async');
      const he = grab('humanEntry', 'async');
      const fp16 = grab('fetchPage', 'async');

      // — 검색창 찾기 —
      ok('㉑ 검색창을 여러 모양으로 찾는다(클래스명이 바뀌어도 죽지 않게)',
         (sbl.match(/'[^']*'/g) || []).length >= 5 && /input\[name="query"\]/.test(sbl));
      ok('㉑ 숨은 칸·아이콘은 고르지 않는다', /r\.width > 40 && r\.height > 10/.test(sbl));
      ok('㉑ 화면 밖 좌표면 건너뛴다', /x < w && y < h/.test(sbl));

      // — 「쇼핑」 탭 찾기 —
      ok('㉑ 쇼핑 탭은 **주소로 먼저** 가른다(첫 화면 메뉴의 「쇼핑」과 헷갈리지 않게)',
         /where=shop/.test(stl) && /ssc=tab\.shop/.test(stl)
         && stl.indexOf('where=shop') < stl.indexOf('role="tablist"'));
      ok('㉑ 글자가 정확히 「쇼핑」인 것만 본다', (stl.match(/!== '쇼핑'/g) || []).length >= 2);
      ok('㉑ 못 찾으면 null(폴백 신호)', /return null;\s*\}\s*$/.test(stl.trim()));

      // — 치는 동작 —
      ok('㉑ 사람 순서대로 — 누르고 · 치고 · 엔터',
         tae.indexOf("'Input.dispatchMouseEvent'") < tae.indexOf("'Input.insertText'")
         && tae.indexOf("'Input.insertText'") < tae.lastIndexOf("'Input.dispatchKeyEvent'"));
      ok('㉑ 한글은 insertText 로 한 번에 넣는다(글자 단위 키로는 조합이 깨진다)',
         /'Input\.insertText', \{ text: String\(keyword\) \}/.test(tae));
      ok('㉑ 엔터를 실제 키 이벤트로 보낸다', /key: 'Enter'[^]*windowsVirtualKeyCode: 13/.test(tae));
      ok('㉑ 전 키워드 잔상을 지우고 덮어쓴다', /modifiers: 2/.test(tae));

      // — 포털 경로(대표 지시) —
      ok('㉑ 네이버 첫 화면부터 연다', /NAVER_HOME/.test(pe) && /'https:\/\/www\.naver\.com'/.test(SRC));
      ok('㉑ 검색 → 통합검색 → 쇼핑 탭 순서다',
         pe.indexOf('typeAndEnter') < pe.indexOf('search.naver.com')
         && pe.indexOf('search.naver.com') < pe.indexOf('shopTabLocate'));
      ok('㉑ 쇼핑 탭은 **눌러서** 넘어간다(주소를 직접 열지 않는다)',
         /shopTabLocate/.test(pe) && !/tabs\.update\(tabId, \{ url: '[^']*shopping/.test(pe));
      ok('㉑ 탭을 못 찾으면 폴백한다', /_entryNote = 'no-shop-tab'/.test(pe));
      ok('㉑ 실패해도 **반드시** 뗀다(포털)', /finally \{\s*if \(attached\) await dbgDetach\(tabId\);/.test(pe));
      ok('㉑ 이동 동안에는 떼어 둔다(띠를 짧게)', (pe.match(/await dbgDetach\(tabId\); attached = false;/g) || []).length >= 2);

      // — 두 번째부터는 쇼핑 검색창 —
      ok('㉑ 쇼핑 안에서는 그 검색창을 쓴다(매번 네이버로 되돌아가지 않는다)',
         /findBox\(tabId\)/.test(sbe) && /typeAndEnter/.test(sbe));
      ok('㉑ 이미 쇼핑이면 쇼핑 검색창을 먼저 쓴다',
         /inShop && await shopBoxEntry/.test(he) && he.indexOf('shopBoxEntry') < he.indexOf('portalEntry'));
      ok('㉑ 쇼핑 결과 화면이 아니면 폴백한다',
         /indexOf\('search\.shopping\.naver\.com'\) < 0/.test(he) && /indexOf\('\/search\/all'\) < 0/.test(he));
      ok('㉑ 어느 길로 들어갔는지 남긴다', /_entryVia = 'shopbox'/.test(he) && /_entryVia = 'portal'/.test(he));

      // — 호출부 배선 —
      ok('㉑ 1페이지에서 사람 경로를 먼저 시도한다',
         /await searchEntryEnabled\(\)/.test(fp16) && /await humanEntry\(tabId, keyword\)/.test(fp16));
      ok('㉑ 실패하면 종전 주소 열기로 폴백한다(수집이 통째로 멈추지 않게)',
         /if \(!entered\) \{/.test(fp16) && /chrome\.tabs\.update\(tabId, \{ url \}\)/.test(fp16));
      ok('㉑ 어느 길로 들어갔는지 센다',
         /_navMode\.entry\[_entryVia\] \+= 1/.test(fp16) && /_navMode\.entry\.url \+= 1/.test(fp16));
      ok('㉑ 서버 meta 에 진입 방식을 싣는다', /entry: _navMode\.entry/.test(SRC) && /via: _entryVia/.test(SRC));
      ok('㉑ 세 갈래를 따로 센다', (SRC.match(/entry: \{ portal: 0, shopbox: 0, url: 0 \}/g) || []).length >= 2);
      ok('㉑ 네이버·통합검색 호스트 권한이 있다',
         (MANIFEST.host_permissions || []).some((h) => h.indexOf('www.naver.com') >= 0)
         && (MANIFEST.host_permissions || []).some((h) => h.indexOf('search.naver.com') >= 0));

      ok('㉑ 끌 수 있다(팝업 토글)', /id="searchEntry"/.test(PH) && /\$\('searchEntry'\)\.onclick/.test(PJ));
      ok('㉑ 기본값이 양쪽 다 「켬」이다',
         /searchEntry === undefined \? true/.test(grab('searchEntryEnabled', 'async'))
         && /searchEntry === undefined \? true/.test(PJ));

      // 🔴 퍼즐 가드 — 글자를 넣는 곳은 **한 곳뿐**이어야 한다.
      ok('🔴㉑ 글자 입력은 검색창에 치는 한 곳에서만 쓴다(퍼즐 칸에 쓰지 않는다)',
         (SRC.match(/'Input\.insertText'/g) || []).length === 1 && tae.includes("'Input.insertText'"));
      ok('🔴㉑ 차단·퍼즐 처리 경로에는 입력 명령이 없다',
         !/Input\.(insertText|dispatchKeyEvent)/.test(grab('markBlocked', 'async') || ''));
      ok('㉑ 버전 1.17.0 이상', _ge(MANIFEST.version, '1.17.0'));
    }

    console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : '\n사람처럼 넘기기 시험 전부 통과');
    process.exit(fail ? 1 : 0);
  })();
}

