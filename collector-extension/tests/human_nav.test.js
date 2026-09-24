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

/* ⚠️ **주석을 코드로 읽지 말 것** — 2026-09-16·17 에 이것 때문에 두 번 헛실패했다.
 *   우리 주석에는 「종전엔 이랬다」며 옛 코드를 그대로 적어 두는 관행이 있어서,
 *   `!/옛코드/.test(본문)` 류의 검사가 주석에 걸려 항상 실패한다.
 *   ⇒ 「무엇이 **없는지**」를 볼 때는 반드시 `code()` 로 감싼다. */
function code(src) {
  return String(src).replace(/\/\*[^]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
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
  // 🔴 v1.17.5 — 「그 좌표에 무엇이 있나」. spec.topAt 을 준 시험에서만 붙인다
  //    (안 주면 함수가 없어 pagerLocate 가 try 로 넘어가고, 옛 시험은 그대로 통과한다).
  if (spec.topAt) doc.elementFromPoint = (x, y) => spec.topAt(x, y);
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
   !/tabs\.update\([^)]*pagingIndex/.test(fp) && /return \{ total: 0, list: \[\], stopReason: 'NO_PAGER' \};   \/\/ 이 키워드는 여기까지/.test(fp) && !/func: routerPush/.test(fp));
ok('⑦ 폴백을 서버에 한 번 알린다', /NO_PAGER/.test(fp) && /_navMode\.reported = true/.test(fp));

// ⑧ 깊이 요구 — 설정값이 실제로 그만큼인가
// ⚠️ 2026-09-18 대표 확정으로 **400 → 300** 으로 내렸다. 근거는 추측이 아니라 실측이다
//    (진단 #301): 최근 14일 수집분에서 찾은 목표 462건 중 **301위 밖에서 발견된 것 0건**,
//    401위 밖도 0건. 목표를 다 찾은 364개 키워드가 끝난 페이지도 **최대 8** 이었다.
//    ⇒ 300 으로 줄여도 잃는 것이 없고, 요청은 11장 → 8장으로 27% 준다.
const cfg = SRC.slice(SRC.indexOf('pageSize:'), SRC.indexOf('maxConsecutiveFail'));
const num = (k) => {
  const m = new RegExp(k + '\\s*:\\s*(\\d+)').exec(cfg);
  return m ? Number(m[1]) : -1;
};
ok('⑧ 깊이 목표가 300위다(대표 확정 2026-09-18)', num('maxRank') === 300);
ok('⑧ 한 페이지는 화면 기본값 40개다', num('pageSize') === 40);
ok('⑧ 페이지 수가 300위를 채운다 (40 × n ≥ 320)', num('pageSize') * num('pagesPerKeyword') >= 320);
// ⚠️ 위로도 막는다 — 「깊이를 줄였다」가 조용히 되돌려지면 요청이 도로 늘어난다.
ok('⑧ 페이지 수가 8장을 넘지 않는다(요청이 도로 늘지 않게)', num('pagesPerKeyword') <= 8);
ok('⑧ 안전 상한도 8장이다', num('maxPages') <= 8);

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
  ok('⑫ 끝내 안 바뀌면 그 키워드는 여기까지만 담고 끝낸다(빈 목록)', /lastErr === 'STALE_PAGE'/.test(FP) && /return \{ total: 0, list: \[\], stopReason: 'STALE_PAGE' \}/.test(FP) && /_navMode\.stale \+= 1/.test(FP));
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
       /_clickedAt = Date\.now\(\);/.test(FP) && /func: pageExtract,\s*args: \[\{ page: pagingIndex, since: _clickedAt \}/.test(FP));
    // ⚙ v1.27.0 — 두 번째 인자로 서버가 준 차단 문구(더하기만)를 넘긴다. 없으면 빈 목록 = 종전 판정.
    ok('⚙ fetchPage 가 서버 차단 문구(extraBlockPhrases)를 pageExtract 에 넘긴다',
       /RT\.extraBlockPhrases : \[\]\)\]/.test(FP));
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
      ok('㉑ 탭 글자는 보조 문구를 떼고 본다(완전일치 금지 — v1.17.3 교훈)',
         /function tabText/.test(stl) && (stl.match(/tabText\((a|c\[j\])\) !== '쇼핑'/g) || []).length >= 2);
      /* v1.17.2 — 못 찾았을 때 **어디서 무엇을 봤는지** 남긴다.
       * ⚠️ v1.17.1 에서 두 키워드 다 `no-shop-tab` 이었는데, 「탭이 없다」인지 「아직 첫 화면」인지
       *    「규칙이 못 잡았다」인지 가를 수가 없었다. 추측 대신 찍게 한다. */
      ok('㉑ 못 찾으면 어디서 무엇을 봤는지 남긴다(폴백 신호 겸 진단)',
         /return \{ miss: true, host: location\.host/.test(stl)
         && /a: all2\.length, sc: scopes\.length, seen: seen/.test(stl));
      ok('㉑ 「쇼핑」으로 시작하는 링크를 최대 3개까지 표본으로 담는다',
         /seen\.length < 3/.test(stl) && /indexOf\('쇼핑'\) === 0/.test(stl));
      ok('㉑ 그 진단이 서버 보고에 실린다',
         /no-shop-tab@/.test(pe) && /\.slice\(0, 150\)/.test(pe));
      ok('㉑ 탭 줄이 늦게 그려질 수 있으니 한 번 더 본다(요청은 안 는다)',
         /tl\.result\.miss/.test(pe) && (pe.match(/func: shopTabLocate/g) || []).length === 2);
      // 가짜 화면으로 실제 판정을 돌려 본다 — 못 찾으면 miss 가 오고 표본이 담겨야 한다.
      {
        const mkA = (text, href) => ({
          textContent: text,
          getAttribute: (k) => (k === 'href' ? href : null),
          getBoundingClientRect: () => ({ width: 40, height: 16, left: 100, top: 50 }),
          scrollIntoView: () => {},
        });
        const anchors = [mkA('뉴스', '/news'), mkA('쇼핑', 'https://shopping.naver.com/home'),
                         mkA('지도', '/map')];
        const doc = { querySelectorAll: (s) => (s === 'a' ? anchors : []) };
        const fn = new Function('document', 'window', 'location',
          `${grab('shopTabLocate')}; return shopTabLocate;`)(
          doc, { innerWidth: 1280, innerHeight: 900 }, { host: 'www.naver.com', pathname: '/' });
        const r = fn();
        ok('㉑ 쇼핑 검색으로 안 가는 「쇼핑」 링크는 안 고른다(첫 화면 메뉴 오클릭 방지)', !!r && r.miss === true);
        ok('㉑ 그때 어디였는지·무엇을 봤는지 담긴다',
           r.host === 'www.naver.com' && r.a === 3 && r.seen.length === 1
           && r.seen[0].indexOf('쇼핑>') === 0);
      }
      {
        const mkA = (text, href) => ({
          textContent: text,
          getAttribute: (k) => (k === 'href' ? href : null),
          getBoundingClientRect: () => ({ width: 40, height: 16, left: 200, top: 80 }),
          scrollIntoView: () => {},
        });
        const anchors = [mkA('쇼핑', '/search.naver?where=shop&query=x')];
        const doc = { querySelectorAll: (s) => (s === 'a' ? anchors : []) };
        const fn = new Function('document', 'window', 'location',
          `${grab('shopTabLocate')}; return shopTabLocate;`)(
          doc, { innerWidth: 1280, innerHeight: 900 }, { host: 'search.naver.com', pathname: '/search.naver' });
        const r = fn();
        ok('㉑ 통합검색의 쇼핑 탭은 제대로 고른다', !!r && !r.miss && r.via === 'href' && r.x === 220 && r.y === 88);
      }
      /* 🔴 v1.17.3 — 2026-09-16 16:19 실측.
       *   진단이 남긴 것: `…|쇼핑새 창 >https://search.shopping.naver.com/`
       *   탭은 거기 있었는데 글자가 「쇼핑」이 아니라 **「쇼핑새 창」** 이었다(낭독기용 안내가 안에 있다).
       *   완전일치라 못 잡고 다섯 회차를 헛돌았다. **탭 글자는 완전일치로 보지 말 것.**
       */
      {
        const mkA = (text, href) => ({
          textContent: text,
          getAttribute: (k) => (k === 'href' ? href : null),
          getBoundingClientRect: () => ({ width: 40, height: 16, left: 300, top: 60 }),
          scrollIntoView: () => {},
        });
        const run = (anchors, host) => {
          const doc = { querySelectorAll: (s) => (s === 'a' ? anchors : []) };
          return new Function('document', 'window', 'location',
            `${grab('shopTabLocate')}; return shopTabLocate;`)(
            doc, { innerWidth: 1280, innerHeight: 900 }, { host, pathname: '/search.naver' })();
        };
        const real = run([mkA('쇼핑새 창', 'https://search.shopping.naver.com/')], 'search.naver.com');
        ok('🔴㉑ 「쇼핑새 창」처럼 낭독기 안내가 붙어도 잡는다(실제로 겪은 모양)',
           !!real && !real.miss && real.via === 'href');
        ok('🔴㉑ 「쇼핑 새창」·「쇼핑새창」도 잡는다',
           !run([mkA('쇼핑 새창', 'https://search.shopping.naver.com/')], 'search.naver.com').miss
           && !run([mkA('쇼핑새창', 'https://search.shopping.naver.com/')], 'search.naver.com').miss);
        /* 🔴 v1.17.4 — 대표 캡처로 확인한 **진짜 모양**:
         *   <a role="tab" class="tab" target="_blank"
         *      href="…/search/all?where=all&frm=NVSCTAB&query=…">쇼핑<span class="blind">새 창 열림</span></a>
         *   v1.17.3 은 끝의 「열림」 하나만 떼어 「쇼핑새 창」이 남았다 — 되풀이해 떼야 한다.
         */
        const REAL_HREF = 'https://search.shopping.naver.com/search/all?where=all&frm=NVSCTAB&query=%EC%83%9D';
        const realTab = run([mkA('쇼핑새 창 열림', REAL_HREF)], 'search.naver.com');
        ok('🔴㉑ 진짜 모양 「쇼핑새 창 열림」을 잡는다(v1.17.3 이 놓친 것)',
           !!realTab && !realTab.miss && realTab.via === 'href');
        ok('🔴㉑ frm=NVSCTAB 주소도 탭으로 인정한다', !!realTab && !realTab.miss);
        ok('🔴㉑ 「쇼핑라이브」처럼 다른 탭은 안 잡는다(앞글자만 같다고 고르면 안 된다)',
           run([mkA('쇼핑라이브', 'https://search.shopping.naver.com/')], 'search.naver.com').miss === true);
        ok('🔴㉑ 첫 화면 메뉴의 「쇼핑」(쇼핑 홈)은 여전히 안 고른다',
           run([mkA('쇼핑새 창', 'https://shopping.naver.com/home')], 'www.naver.com').miss === true);
      }

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
      // v1.17.2 에서 사유 문자열을 조립하게 바뀌었다 — 글자 그대로 박지 않는다(오늘 세 번째 같은 실수).
      // ⚠️ v1.17.4 부터 실패는 `return 0`(= 탭 번호 없음)이다. 「false」를 찾으면 여기서 헛실패한다.
      ok('㉑ 탭을 못 찾으면 폴백한다', /if \(!tab \|\| tab\.miss\)/.test(pe) && /return 0;/.test(pe));
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
      /* 🔴 v1.17.1 — 2026-09-16 15:07 실사고.
       *   `portalEntry` 가 연 네이버 첫 화면·통합검색을 옛 가드가 「캡차로 튕겼다」로 읽어
       *   6시간 쉼에 들어갔다(서버 보고 `REDIRECT(검색 도메인 이탈) · title=과실주 : 네이버 검색`).
       *   네이버는 아무것도 막지 않았다. **새 진입 경로를 더할 때 이 목록을 먼저 고쳐야 한다.**
       */
      const ibu = grab('isBlockedUrl');
      const oeh = grab('onEntryHost');
      // ⚠️ `ENTRY_HOSTS` 는 함수 **밖**에 있다 — isBlockedUrl 본문에서 찾으면 없다(방금 헛실패).
      ok('🔴㉑ 우리가 일부러 거치는 곳은 차단으로 읽지 않는다',
         /const ENTRY_HOSTS = \[/.test(SRC) && /onEntryHost\(u\)\) return false/.test(ibu));
      ok('🔴㉑ 그 목록에 네이버 첫 화면·통합검색이 들어 있다',
         /'search\.shopping\.naver\.com', 'www\.naver\.com', 'search\.naver\.com'/.test(SRC)
         && /ENTRY_HOSTS\.some/.test(oeh));
      ok('🔴㉑ ncpt·nid 같은 진짜 캡차 경로는 여전히 차단으로 본다',
         /return \/naver\\\.com\/\.test\(u\)/.test(ibu));
      ok('🔴㉑ 이동 대기도 같은 판정을 쓴다(한쪽만 고치면 또 헛차단)',
         /if \(u && !onEntryHost\(u\)\)/.test(grab('waitNavigated')));
      // 실제로 돌려 본다 — 사고 당시 그 주소가 이제 차단이 아니어야 한다.
      {
        const fn = new Function(`${grab('onEntryHost')}
          const ENTRY_HOSTS = ['search.shopping.naver.com', 'www.naver.com', 'search.naver.com'];
          ${grab('isBlockedUrl')}; return isBlockedUrl;`)();
        ok('🔴㉑ 사고 당시 주소(통합검색)가 이제 차단이 아니다',
           fn('https://search.naver.com/search.naver?where=nexearch&query=%EA%B3%BC%EC%8B%A4%EC%A3%BC') === false);
        ok('🔴㉑ 네이버 첫 화면도 차단이 아니다', fn('https://www.naver.com') === false);
        ok('🔴㉑ 쇼핑 결과는 그대로 차단 아님', fn('https://search.shopping.naver.com/search/all?query=x') === false);
        ok('🔴㉑ 캡차 경로는 그대로 차단', fn('https://ncpt.naver.com/v2/captcha') === true);
        ok('🔴㉑ 로그인 유도도 그대로 차단', fn('https://nid.naver.com/nidlogin.login') === true);
      }
      /* 🔴 v1.17.4 — 쇼핑 탭은 `target="_blank"` 라 **새 탭**으로 열린다.
       *   v1.17.3 까지는 누른 뒤 **원래 탭**만 보고 「결과 화면이 아니다」로 읽어 매번 폴백했다.
       *   ⇒ 진입 함수는 이제 **탭 번호**를 돌려주고(0 = 실패), 호출부가 그 탭으로 갈아탄다.
       *   ⚠️ 여기서 「true/false」를 기대하는 시험을 남겨 두면 다음 사람이 되돌려 놓는다.
       */
      ok('🔴㉑ 누르기 **전에** 탭 목록을 적어 둔다(새 탭을 가려내려면 기준이 필요하다)',
         /const before = \(await chrome\.tabs\.query\(\{ windowId: winId \}\)\)\.map/.test(pe)
         && pe.indexOf('const before') < pe.indexOf("'Input.dispatchMouseEvent'"));
      ok('🔴㉑ 새로 생긴 쇼핑 탭만 이어받는다(원래 있던 탭·다른 사이트 탭은 건드리지 않는다)',
         /before\.indexOf\(t\.id\) >= 0\) continue/.test(pe)
         && /indexOf\('search\.shopping\.naver\.com'\) < 0\) continue/.test(pe));
      ok('🔴㉑ 새 탭이 안 뜨면 **같은 탭에서 이동한 것**으로 보고 그대로 간다',
         /const me = await chrome\.tabs\.get\(tabId\)/.test(pe)
         && /break;\s*\/\/ 같은 탭에서 이동/.test(pe));
      ok('🔴㉑ 무한정 기다리지 않는다(최대 15초)',
         /for \(let i = 0; i < 30 && !adopted; i\+\+\)/.test(pe) && /await sleep\(500\)/.test(pe));
      ok('🔴㉑ 이어받은 탭을 작업 탭으로 삼고 저장한다(워커가 잠들었다 깨도 잃지 않게)',
         /workTabId = adopted/.test(pe) && /\[TAB_KEY\]: adopted/.test(pe));
      ok('🔴㉑ 옛 탭은 닫는다(회차마다 쌓이면 메모리가 샌다)',
         /chrome\.tabs\.remove\(tabId\)/.test(pe));
      ok('🔴㉑ 이어받은 탭이 결과 화면이 될 때까지 기다린 뒤 넘긴다',
         pe.indexOf("waitNavigated(adopted, 'search/all')") > 0
         && pe.indexOf("waitNavigated(adopted") < pe.indexOf('return adopted'));
      ok('🔴㉑ 진입 함수는 **탭 번호**를 돌려준다(성공 = 번호 · 실패 = 0)',
         /return adopted;/.test(pe) && /return tabId;/.test(pe)
         && !/return true;/.test(pe) && !/return false;/.test(pe));
      ok('🔴㉑ humanEntry 도 탭 번호를 돌려준다', /return use;/.test(he) && !/return true;/.test(he));
      ok('🔴㉑ 성공 여부는 「0 이 아닌가」로 본다(불리언 비교로 되돌리지 말 것)',
         /if \(!use\) return 0;/.test(he) && /let use = 0;/.test(he));
      ok('🔴㉑ 결과 화면 확인은 **이어받은 탭**을 본다(원래 탭이 아니라)',
         /chrome\.tabs\.get\(use\)/.test(he));
      ok('🔴㉑ 호출부가 그 탭으로 갈아탄다(안 갈아타면 통합검색을 읽는다)',
         /let tabId = await ensureWorkTab\(\)/.test(fp16) && /tabId = use;/.test(fp16));
      /* 🔴 v1.17.5 — 2026-09-16 17:23·17:33 실측.
       *   진입(portal)은 2/2 성공했는데 **2페이지 요청이 0건**이었다. 클릭은 오류 없이 나갔고
       *   번호 줄도 정상인데 화면이 반응을 안 했다. 「네이버가 막았다」가 아니라
       *   「클릭이 화면을 못 깨웠다」에 가깝다.
       *   대표 지시(「완전 실사용자 기반으로 움직이면 될 거 같은데」)로 셋을 넣는다.
       *   ⚠️ 셋 다 **재는 것**이고 동작을 바꾸지 않는다 — 네이버 요청은 0건 는다.
       */
      console.log('\n[㉒ 클릭이 헛나갔나 — v1.17.5]');
      const pl5 = grab('pagerLocate');
      const tc5 = grab('trustedClickToPage', 'async');
      const hsd = grab('humanScrollDown', 'async');
      const pst = grab('pagerState');
      const rps = grab('readPagerState', 'async');

      // ① 그 좌표에 무엇이 있는지 본다
      ok('🔴㉒ 누를 좌표에 실제로 무엇이 있는지 확인한다', /document\.elementFromPoint\(x, y\)/.test(pl5));
      ok('🔴㉒ 우리 버튼이 아니면 「덮였다」로 표시한다', /covered = mine \? 0 : 1/.test(pl5));
      ok('🔴㉒ 자기 자신·자기 자식은 덮인 것이 아니다',
         /top === el/.test(pl5) && /el\.contains\(top\)/.test(pl5));
      ok('🔴㉒ 무엇이 덮었는지 이름을 남긴다(태그·클래스·글자)',
         /top\.tagName/.test(pl5) && /top\.className/.test(pl5) && /top\.textContent/.test(pl5));
      ok('🔴㉒ 덮였다고 **클릭을 포기하지는 않는다**(판정이 틀릴 수 있다 — 찍기만 한다)',
         !/if \(covered\) return null/.test(pl5) && /return \{ branch: branch/.test(pl5));
      ok('🔴㉒ 보고 문자열 길이를 묶는다(서버가 500자에서 자른다)', /hit\.slice\(0, 40\)/.test(pl5));

      // 실제로 돌려 본다 — 덮인 경우와 안 덮인 경우
      {
        let btn = null;
        const base = () => ({
          build(mk) { btn = mk('a', '2', { href: '#', left: 400, top: 700 }); this.scopes[0].push(btn); },
          scopes: [[]],
        });
        const clean = base();
        clean.topAt = () => btn;                      // 좌표에 우리 버튼이 있다
        const r1 = runLocate(clean, 2);
        ok('🔴㉒ 가린 것이 없으면 cov=0', !!r1.spot && r1.spot.covered === 0);

        const veiled = base();
        veiled.topAt = () => ({ tagName: 'DIV', className: 'floating_ad sticky', textContent: '  광고  배너 ' });
        const r2 = runLocate(veiled, 2);
        ok('🔴㉒ 다른 것이 덮고 있으면 cov=1', !!r2.spot && r2.spot.covered === 1);
        ok('🔴㉒ 그때 무엇이 덮었는지가 적힌다',
           !!r2.spot && r2.spot.hit === 'div.floating_ad.sticky>광고 배너');

        const empty = base();
        empty.topAt = () => null;                     // 그 점에 아무것도 없다(화면 밖 등)
        const r3 = runLocate(empty, 2);
        ok('🔴㉒ 그 점이 비어 있어도 덮인 것으로 본다', !!r3.spot && r3.spot.covered === 1 && r3.spot.hit === 'none');

        const old = base();                           // elementFromPoint 자체가 없는 환경
        const r4 = runLocate(old, 2);
        ok('🔴㉒ 확인이 불가능한 환경에서도 좌표는 그대로 낸다(수집이 멈추지 않게)',
           !!r4.spot && r4.spot.hit === 'err');
      }

      /* 🔴 v1.17.5 — 대표 캡처(2026-09-16)로 확인한 **진짜 페이지 버튼**:
       *   <a href="#" class="pagination_btn_page__utqBz _nlog_click _nlog_impression_element"
       *      data-shp-area="prd_pgn.pgn" data-shp-contents-id="2" …>2</a>
       *   현재 페이지만 <span … active> 다. */
      ok('🔴㉒ 네이버 표식으로 정확히 지목한다', /data-shp-area="prd_pgn\.pgn"/.test(pl5));
      // ⚠️ 주석에는 실제 모양을 적어 뒀다(다음 사람이 알아보게) — **주석을 뺀 코드**로만 본다.
      //    이걸 안 해서 방금 헛실패했다. 오늘 네 번째 같은 실수다.
      const pl5code = code(pl5);
      ok('🔴㉒ 클래스 이름에는 걸지 않는다(빌드마다 바뀌는 해시다)',
         !/utqBz|pagination_btn_page__|_nlog_click/.test(pl5code));
      ok('🔴㉒ 표식과 글자가 **둘 다** 맞을 때만 쓴다(표식의 뜻을 단정하지 않는다)',
         /getAttribute\('data-shp-contents-id'\) !== want\) continue/.test(pl5)
         && /textContent \|\| ''\)\.trim\(\) !== want\) continue/.test(pl5));
      ok('🔴㉒ 그 규칙을 **맨 앞**에 둔다(가장 정확한 것부터)',
         pl5.indexOf('prd_pgn.pgn') < pl5.indexOf('[class*="pagination"]'));
      ok('🔴㉒ 못 찾으면 종전 규칙으로 내려간다(네이버가 표식을 떼도 안 죽게)',
         /\[class\*="pagination"\]/.test(pl5) && /'loose'/.test(pl5));
      {
        // 진짜 모양을 그대로 세워 돌려 본다
        const mkShp = (n, text) => ({
          tagName: 'A', textContent: text === undefined ? String(n) : text,
          className: 'pagination_btn_page__utqBz _nlog_click',
          getAttribute: (a) => (a === 'href' ? '#'
                              : a === 'data-shp-contents-id' ? String(n) : null),
          getBoundingClientRect: () => ({ width: 26, height: 26, left: 340, top: 420 }),
          scrollIntoView: () => {},
        });
        const runShp = (marked) => new Function('document', 'window',
          `${grab('pagerLocate')}; return pagerLocate;`)(
          { querySelectorAll: (s) => (/prd_pgn/.test(s) ? marked : []) },
          { innerWidth: 1280, innerHeight: 900 })(2);
        ok('🔴㉒ 진짜 모양의 2페이지 버튼을 잡는다',
           (runShp([mkShp(2), mkShp(3)]) || {}).branch === 'shp');
        ok('🔴㉒ 좌표는 그 버튼 한가운데다',
           (runShp([mkShp(2)]) || {}).x === 353 && (runShp([mkShp(2)]) || {}).y === 433);
        ok('🔴㉒ 표식은 2인데 글자가 다르면 안 쓴다(표식을 맹신하지 않는다)',
           runShp([mkShp(2, '다음')]) === null);
        ok('🔴㉒ 다른 번호는 안 고른다', runShp([mkShp(3), mkShp(4)]) === null);
      }

      // ② 사람처럼 나눠 내려간다
      ok('🔴㉒ 누르기 **전에** 훑어 내려간다', tc5.indexOf('humanScrollDown') < tc5.indexOf('pagerLocate'));
      ok('🔴㉒ 한 번에 순간이동하지 않고 여러 번에 나눈다',
         /for \(let i = 0; i < 8; i\+\+\)/.test(hsd) && /func: scrollStep/.test(hsd));
      // ⚙ v1.27.0 — 숫자가 서버 설정(RT)으로 옮겨졌다. 기본값(180~440ms · 500~820px)은 폴백과 remote_settings 기본값에 그대로.
      ok('🔴㉒ 사이에 잠깐씩 멈춘다(사람 손 간격)',
         /await sleep\(_sc\.scrollWaitMinMs \+ Math\.floor\(Math\.random\(\) \* \(_sc\.scrollWaitMaxMs - _sc\.scrollWaitMinMs\)\)\)/.test(hsd)
         && /scrollWaitMinMs: 180, scrollWaitMaxMs: 440/.test(hsd));
      ok('🔴㉒ 굴리는 폭도 매번 다르다',
         /_sc\.scrollPxMin \+ Math\.floor\(Math\.random\(\) \* \(_sc\.scrollPxMax - _sc\.scrollPxMin\)\)/.test(hsd)
         && /scrollPxMin: 500, scrollPxMax: 820/.test(hsd));
      ok('🔴㉒ 굴리기가 실패해도 수집은 계속한다', /catch \(e\) \{ \/\* 굴리기 실패는/.test(hsd));
      ok('🔴㉒ 굴리기는 화면만 움직인다(네이버 요청 0건)',
         /window\.scrollBy\(0, px\)/.test(grab('scrollStep')) && !/fetch|XMLHttpRequest|tabs\.update/.test(hsd));

      // ③ 누른 직후 현재 페이지를 찍는다
      ok('🔴㉒ 누른 **직후** 현재 페이지를 읽는다(29초 뒤가 아니라)',
         tc5.indexOf('mouseReleased') < tc5.indexOf('readPagerState')
         && tc5.indexOf('readPagerState') < tc5.indexOf("return spot.branch"));
      ok('🔴㉒ 「현재」 표식을 한 가지 모양에만 걸지 않는다',
         /aria-current/.test(pst) && /active\|current\|selected/.test(pst));
      ok('🔴㉒ 주소의 pagingIndex 도 함께 본다(표식이 없을 때의 두 번째 근거)',
         /pagingIndex=\(\\d\+\)/.test(pst));
      ok('🔴㉒ 얼마나 내려와 있는지도 같이 찍는다(굴리기가 먹었는지 확인용)', /window\.scrollY/.test(pst));
      ok('🔴㉒ 못 읽어도 수집을 멈추지 않는다', /_pagerAfter = 'read-error'/.test(rps));

      // 실제로 돌려 본다
      {
        const run = (els, search) => new Function('document', 'location', 'window',
          `${grab('pagerState')}; return pagerState;`)(
          { querySelectorAll: (s) => (/pagination|paging|navigation/.test(s)
              ? [{ querySelectorAll: () => els }] : []) },
          { search: search || '' }, { scrollY: 5600 })();
        const mkP = (t, cls, cur) => ({
          textContent: t, className: cls || '',
          getAttribute: (a) => (a === 'aria-current' ? (cur || null) : null),
        });
        ok('🔴㉒ aria-current 로 현재 페이지를 잡는다',
           run([mkP('1'), mkP('2', '', 'page')], '').cur === '2');
        ok('🔴㉒ 클래스 이름으로도 잡는다',
           run([mkP('1'), mkP('2', 'pageNum is-on')], '').cur === '2');
        /* 🔴 현재 페이지는 **span** 이다(대표 캡처). a,button 만 보면 영영 못 찾는다 —
         *   실제로 그렇게 짰다가 캡처를 보고 고쳤다. */
        ok('🔴㉒ 현재 페이지가 span 이어도 찾는다(진짜 모양)',
           /querySelectorAll\('a,button,span'\)/.test(pst));
        ok('🔴㉒ 표식이 하나도 없으면 빈 값이다(없는 것을 지어내지 않는다)',
           run([mkP('1'), mkP('2')], '').cur === '');
        ok('🔴㉒ 주소에 pagingIndex 가 있으면 함께 담는다',
           run([mkP('1')], '?query=x&pagingIndex=2').qp === '2');
        ok('🔴㉒ 스크롤 위치도 담긴다', run([mkP('1')], '').y === 5600);
      }

      // ④ 서버 보고에 실린다 — 잘리기 전 앞쪽에
      ok('🔴㉒ 세 값이 서버 보고에 실린다',
         /hit: _clickHit \|\| ''/.test(SRC) && /cov: _clickCovered/.test(SRC) && /after: _pagerAfter \|\| ''/.test(SRC));
      ok('🔴㉒ 500자에 잘리지 않게 앞쪽에 둔다',
         SRC.indexOf('hit: _clickHit') < SRC.indexOf('entry: _navMode.entry, enote:'));

      /* 🔴 v1.17.6 — 2026-09-16 18:08 실측. 내가 만든 계측이 「cur=현재페이」를 냈다.
       *   그 span 안에는 낭독기용 안내문(「현재페이지」)이 숫자 **앞에** 붙어 있어
       *   앞 4글자만 자르면 숫자가 영영 안 나온다. 글자를 자르지 말고 숫자를 뽑는다. */
      ok('🔴㉓ 글자를 자르지 않고 **숫자를** 뽑는다(「현재페이지2」 → 2)',
         /raw\.match\(\/\\d\+\/g\)/.test(pst) && !/slice\(0, 4\)/.test(pst));
      ok('🔴㉓ 숫자가 여러 개면 **마지막** 것을 쓴다(안내문에 섞인 숫자에 안 속게)',
         /digits\[digits\.length - 1\]/.test(pst));
      ok('🔴㉓ 원문도 남긴다(모양이 또 다르면 짐작하지 않고 눈으로 본다)',
         /raw: raw/.test(pst) && /slice\(0, 12\)/.test(pst));
      ok('🔴㉓ 클릭 직후 화면의 상품 ID 3개를 함께 찍는다(1페이지 것과 대조할 자)',
         /a\[href\*="nvMid="\]/.test(pst) && /first\.length < 3/.test(pst));
      ok('🔴㉓ 셋 다 보고 문자열에 실린다',
         /\/' \+ \(r\.raw \|\| '-'\)/.test(rps) && /\|f=' \+ \(\(r\.first \|\| \[\]\)/.test(rps));
      {
        const run6 = (els, search, links) => new Function('document', 'location', 'window',
          `${grab('pagerState')}; return pagerState;`)(
          { querySelectorAll: (s) => (/pagination|paging|navigation/.test(s)
              ? [{ querySelectorAll: () => els }]
              : (/nvMid/.test(s) ? (links || []) : [])) },
          { search: search || '' }, { scrollY: 7665 })();
        const mkP = (t, cls, cur) => ({
          textContent: t, className: cls || '',
          getAttribute: (a) => (a === 'aria-current' ? (cur || null) : null),
        });
        const mkL = (id) => ({ getAttribute: () => '/x?nvMid=' + id });
        ok('🔴㉓ 실제로 겪은 모양 「현재페이지2」에서 2를 뽑는다',
           run6([mkP('현재페이지2', 'active')], '').cur === '2');
        ok('🔴㉓ 원문이 그대로 담긴다', run6([mkP('현재페이지2', 'active')], '').raw === '현재페이지2');
        ok('🔴㉓ 숫자가 없으면 빈 값이다(지어내지 않는다)',
           run6([mkP('현재페이지', 'active')], '').cur === '');
        ok('🔴㉓ 상품 ID 3개까지만 담는다',
           JSON.stringify(run6([mkP('현재페이지1', 'active')], '',
             [mkL('11'), mkL('22'), mkL('33'), mkL('44')]).first) === '["11","22","33"]');
        ok('🔴㉓ 같은 ID 는 한 번만 담는다',
           JSON.stringify(run6([mkP('현재페이지1', 'active')], '',
             [mkL('11'), mkL('11'), mkL('22')]).first) === '["11","22"]');
      }

      /* 🔴🔴 v1.17.7 — 2026-09-16 18:22 경주빵 + 대표 실측(사람은 그 화면에서 2페이지가 넘어감).
       *   ⇒ 화면은 멀쩡하고 **우리 클릭만** 안 먹었다. 원인 후보 둘을 함께 고쳤다. */
      const tc7 = grab('trustedClickToPage', 'async');
      const ct7 = grab('clickToPage', 'async');
      ok('🔴㉔ **붙이고 나서** 굴리고 좌표를 잰다(띠가 뜨면 화면이 아래로 밀린다)',
         tc7.indexOf('dbgAttach') < tc7.indexOf('humanScrollDown')
         && tc7.indexOf('humanScrollDown') < tc7.indexOf('pagerLocate'));
      ok('🔴㉔ 띠가 자리 잡을 틈을 준다', /attached = true;\s*await sleep\(350\)/.test(tc7));
      ok('🔴㉔ 좌표를 잰 뒤에는 붙이지 않는다(옛 순서로 되돌리지 말 것)',
         tc7.indexOf('pagerLocate') > tc7.indexOf('dbgAttach'));
      ok('🔴㉔ 「눌렀다」를 「먹혔다」로 읽지 않는다 — 현재 페이지를 본다',
         /cur=\(\\d\+\)/.test(ct7) && /cur !== String\(target\)/.test(ct7));
      ok('🔴㉔ 안 움직였으면 합성 클릭으로 한 번 더 간다(폴백이 실제로 돌게)',
         ct7.indexOf("cur !== String(target)") < ct7.indexOf('func: pagerClick')
         && /no-move@/.test(ct7));
      ok('🔴㉔ 번호를 **못 읽으면** 폴백하지 않는다(이미 넘어갔는데 또 누르면 3페이지로 간다)',
         /if \(cur && cur !== String\(target\)\)/.test(ct7));
      ok('🔴㉔ 합성 클릭 뒤에도 같은 자로 현재 페이지를 남긴다(무엇이 먹었는지 보이게)',
         /await readPagerState\(tabId\); \}\s*\n\s*return !!\(res && res\.result\)/.test(ct7)
         || (/readPagerState/.test(ct7) && ct7.indexOf('func: pagerClick') < ct7.lastIndexOf('readPagerState')));
      ok('🔴㉔ 표준 입력이 먹었으면 합성 클릭은 하지 않는다(중복 클릭 금지)',
         /_navMode\.how\.trusted \+= 1;\s*return true;/.test(ct7));

      /* 🚨 v1.17.8 — 2026-09-17 오염 사고.
       *   00:00~11:00 에 서로 다른 12개 키워드가 **같은 상품 32개**를 올렸고,
       *   오류도 막힘 보고도 없이 9시간을 갔다. 원인은 검색창 진입이
       *   「주소에 키워드가 들어왔는가」를 안 본 것이고, 그물이 하나도 없었다.
       *   ⇒ 그물을 셋 넣는다. 아래 시험은 **셋이 다 살아 있는지**를 지킨다. */
      console.log('\n[㉔ 오염 방지 그물 셋 — v1.17.8]');
      const sbe8 = grab('shopBoxEntry', 'async');
      const he8 = grab('humanEntry', 'async');
      const uk8 = grab('uploadKeyword', 'async');
      const usig = grab('uploadSignature');

      // ① 검색창 진입은 **키워드가 주소에 들어올 때까지** 기다린다
      ok('🚨㉔ 검색창 진입이 키워드를 기다린다(search/all 만 기다리지 않는다)',
         /waitNavigated\(tabId, encodeURIComponent\(keyword\)\)/.test(sbe8)
         && !/waitNavigated\(tabId, 'search\/all'\)/.test(code(sbe8)));
      ok('🚨㉔ 종전 주소 열기 경로도 여전히 키워드를 기다린다(둘이 같아야 한다)',
         /waitNavigated\(tabId, encodeURIComponent\(keyword\)\)/.test(grab('fetchPage', 'async')));

      // ② 진입 뒤 「이 키워드의 결과인가」를 확인한다
      ok('🚨㉔ 주소에 그 키워드가 있는지 본다', /wrong-keyword@/.test(he8));
      ok('🚨㉔ 인코딩본·한글 둘 다 본다(주소 형태가 둘이다)',
         /encodeURIComponent\(keyword\)/.test(he8) && /decodeURIComponent\(u\)/.test(he8));
      ok('🚨㉔ 못 맞추면 실패로 떨어뜨린다(폴백이 받는다)',
         /_entryNote = 'wrong-keyword@'[^]*?return 0;/.test(he8));
      /* ⚠️ 위 검사는 「글자가 남아 있나」만 본다 — `if (false)` 로 조건만 죽이면 안 잡힌다
       *   (사보타주 검증에서 실제로 안 잡혔다). **조건 자체**를 지킨다. */
      ok('🚨㉔ 그 판정 조건이 살아 있다(조건만 죽이는 되돌림도 잡는다)',
         /if \(u\.indexOf\(enc\) < 0 && dec\.indexOf\(keyword\) < 0\)/.test(code(he8)));

      // ③ 직전 회차와 같은 결과면 올리지 않는다
      ok('🚨㉔ 직전 업로드와 상품 목록을 대조한다', /_lastUp\.sig === sig/.test(uk8));
      ok('🚨㉔ **키워드가 다를 때만** 막는다(같은 키워드 재측정은 정상)',
         /_lastUp\.keyword !== keyword/.test(uk8));
      ok('🚨㉔ 상품 0개는 비교하지 않는다(둘 다 0 은 흔하다)',
         /return ids\.length \? /.test(usig) && /if \(sig && /.test(uk8));
      ok('🚨㉔ 조용히 건너뛰지 않고 서버에 사유를 알린다',
         /SAME_AS_PREV/.test(uk8) && /reportBlocked/.test(uk8));
      ok('🚨㉔ 성공한 회차만 기준으로 기억한다(실패분이 기준이 되면 안 된다)',
         uk8.indexOf('업로드 실패 HTTP') < uk8.indexOf('_lastUp = { keyword, sig }'));

      // 실제로 돌려 본다 — 같은 목록/다른 키워드면 막히고, 같은 키워드면 안 막힌다
      {
        const sig = new Function(`${usig}; return uploadSignature;`)();
        ok('🚨㉔ 같은 상품 목록은 같은 지문이 된다',
           sig([{ nvMid: '1' }, { nvMid: '2' }]) === sig([{ nvMid: '1' }, { nvMid: '2' }]));
        ok('🚨㉔ 순서가 다르면 다른 지문이다(페이지가 바뀐 것을 오염으로 안 본다)',
           sig([{ nvMid: '1' }, { nvMid: '2' }]) !== sig([{ nvMid: '2' }, { nvMid: '1' }]));
        ok('🚨㉔ 빈 목록은 지문이 없다', sig([]) === '' && sig(null) === '');
        ok('🚨㉔ id·productId 로 와도 읽는다',
           sig([{ id: '7' }]) !== '' && sig([{ productId: '8' }]) !== '');
      }

      // 🔴 부르는 함수가 실제로 있는지 — 오늘 `pushLog` 를 부를 뻔했다(그 이름은 없다)
      {
        const names = (uk8.match(/await ([a-zA-Z_$][\w$]*)\(/g) || [])
          .map((m) => m.replace(/await |\($/g, ''));
        const missing = names.filter((n) => !['fetch'].includes(n)
          && SRC.indexOf('function ' + n + '(') < 0 && SRC.indexOf('const ' + n + ' =') < 0);
        ok('🔴㉔ 업로드 경로가 부르는 함수가 전부 실재한다(없는 이름은 실행 때 터진다)',
           missing.length === 0 || (console.log('     없는 이름:', missing.join(',')), false));
      }

      ok('㉑ 버전 1.18.0 이상', _ge(MANIFEST.version, '1.18.0'));

      /* 🎯 ㉕ 조기 종료 — 2026-09-18 대표 확정
       *   「찾을 상품을 다 찾으면 거기서 멈추고 다음 키워드로 간다」.
       *   ⚠️ 이 시험이 지키는 것은 「멈춘다」만이 아니라 **「함부로 안 멈춘다」** 쪽이다 —
       *      목표가 없을 때 멈춰 버리면 수집이 1페이지짜리로 조용히 쪼그라든다.
       */
      console.log('\n[㉕ 조기 종료 — 다 찾으면 멈춘다]');
      {
        const atf = grab('allTargetsFound', 'function');
        const tfor = grab('targetsFor', 'function');
        ok('㉕ 판정 함수 둘이 있다', !!atf && !!tfor);

        const fn = new Function(`${atf}; return allTargetsFound;`)();
        ok('㉕ 목표를 전부 담았으면 참',
           fn([{ nvMid: '11' }, { nvMid: '22' }], ['11', '22']) === true);
        ok('㉕ 하나라도 못 담았으면 거짓(그 키워드는 끝까지 간다)',
           fn([{ nvMid: '11' }], ['11', '22']) === false);
        ok('🔴㉕ **목표가 없으면 절대 멈추지 않는다**(빈 배열·null 둘 다)',
           fn([{ nvMid: '11' }], []) === false && fn([{ nvMid: '11' }], null) === false);
        ok('㉕ 담긴 것이 없으면 멈추지 않는다', fn([], ['11']) === false);
        ok('㉕ 숫자로 와도 읽는다(서버가 숫자로 줄 수 있다)',
           fn([{ nvMid: 11 }], [11]) === true);
        ok('㉕ id·productId 로 담겨도 읽는다',
           fn([{ id: '11' }], ['11']) === true && fn([{ productId: '22' }], ['22']) === true);

        const tf = new Function(`let _targets = { '갈비': ['1','2'], '감귤': [] };
                                 ${tfor}; return targetsFor;`)();
        ok('㉕ 목표가 있는 키워드는 목록을 준다', (tf('갈비') || []).length === 2);
        ok('🔴㉕ 목표가 빈 키워드는 **null** 을 준다(멈추지 않는다)', tf('감귤') === null);
        ok('🔴㉕ 서버가 안 준 키워드도 null 이다', tf('없는키워드') === null);

        // 순서 계약 — 페이지를 **다 담은 뒤**에 판정해야 한다.
        // 담기 전에 끊으면 그 페이지가 반만 들어가 순위·경쟁사가 어긋난다.
        const ck = grab('collectKeyword', 'async');
        const iTake = ck.indexOf('RR.takeOrganic(list, st)');
        const iStop = ck.indexOf('allTargetsFound(st.products');
        ok('🔴㉕ 판정이 takeOrganic **뒤**에 온다(페이지를 반만 담지 않는다)',
           iTake > 0 && iStop > iTake);
        ok('㉕ 깊이 도달 판정보다 앞에 온다(둘 다 break 지만 사유가 다르다)',
           iStop > 0 && iStop < ck.indexOf('st.products.length >= CFG.maxRank'));
        ok('㉕ 멈춘 사실을 서버에 싣는다(절감을 잴 수 있게)',
           /stoppedEarly/.test(ck) && /stoppedEarly: st\.stoppedEarly/.test(ck));

        // 서버가 안 줘도 종전대로 — 구버전 서버·구버전 응답 방어
        ok('🔴㉕ 서버가 targets 를 안 주면 빈 객체로 둔다(종전 동작)',
           /_targets = \(targets && typeof targets === 'object'\) \? targets : \{\}/.test(SRC));
      }
    }

    console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : '\n사람처럼 넘기기 시험 전부 통과');
    process.exit(fail ? 1 : 0);
  })();
}

