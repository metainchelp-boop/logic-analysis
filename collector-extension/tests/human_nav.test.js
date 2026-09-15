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
   /rt\.components\s*&&\s*rt\.components\[rt\.route\]/.test(grab('pageExtract')) && /roots = rp \?/.test(grab('pageExtract')));
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
ok('⑫ fetchPage 가 이전 장 첫 상품(prevFirstId)을 받는다', /async function fetchPage\(keyword, pagingIndex, prevFirstId\)/.test(SRC));
ok('⑫ 첫 상품이 이전 장과 같으면 STALE_PAGE 로 다시 읽는다', /fid === prevFirstId/.test(FP) && /STALE_PAGE/.test(FP));
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
ok('⑫ collectKeyword 가 장마다 prevFirstId 를 넘긴다', /fetchPage\(keyword, i, prevFirstId\)/.test(SRC) && /prevFirstId = firstIdOf\(list\)/.test(SRC));
ok('⑬ 서버 meta.nav 에 stale 이 실린다', /nav: \{ url: _navMode\.url, click: _navMode\.click, fallback: _navMode\.fallback, stale: _navMode\.stale \}/.test(SRC));
ok('⑬ 버전 1.11.3 이상', _ge(MANIFEST.version, '1.11.3'));


console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : '\n사람처럼 넘기기 시험 전부 통과');
process.exit(fail ? 1 : 0);
