/* 순위 읽기 도우미 — 확장 쪽 회귀 시험 (node · chrome 없이)
 *   ① 순위 규칙 파일이 수집기 것과 한 글자도 다르지 않다
 *   ② 1페이지부터 이어 본 것만 순위로 쓴다(중간 페이지·다른 검색어·오래된 세션은 거절)
 *   ③ 광고는 순번을 먹지 않고, 2페이지 순번은 1페이지 오가닉 수에 이어진다
 *   ④ 결과 끝은 확실할 때만(애매하면 끝 아님 — 「300위 밖」 오보 방지)
 *   ⑤ 추적 키워드가 아니면 보내지 않는다 · 목록이 없으면 아무것도 안 보낸다
 *   ⑥ 화면 쪽(human_tap.js)을 가짜 페이지에서 실제로 돌려 — 첫 화면·페이지 넘김·가격순 화면·요청 통과
 *   ⑦ 권한·요청 범위 — 네이버에 요청하는 코드가 없다
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.join(__dirname, '..');
const REPO = path.join(ROOT, '..');
let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); pass++; console.log('  ✓ ' + name); }
  catch (e) { fail++; console.log('  ✗ ' + name + '\n    ' + (e && e.message)); }
}

const RankRules = require(path.join(ROOT, 'rank_rules.js'));
const HvCore = require(path.join(ROOT, 'hv_core.js'));

function org(id, extra) { return Object.assign({ nvMid: String(id), productTitle: 'p' + id, mallName: 'm', mallProductUrl: 'https://smartstore.naver.com/x/products/' + id }, extra || {}); }
function ad(id) { return { nvMid: String(id), productTitle: 'ad' + id, mallName: 'm', adId: 'a' + id, adType: 'PRODUCT_AD', adcrUrl: 'https://ader.naver.com/v1/x', mallProductUrl: 'https://x/' + id }; }
function range(a, b, f) { const o = []; for (let i = a; i <= b; i++) o.push(f(i)); return o; }

console.log('① 순위 규칙 한 곳');
t('rank_rules.js 가 수집기 것과 바이트 단위로 같다', () => {
  const a = fs.readFileSync(path.join(ROOT, 'rank_rules.js'));
  const b = fs.readFileSync(path.join(REPO, 'collector-extension', 'rank_rules.js'));
  assert.ok(a.equals(b), '두 파일이 다르다 — 수집기 규칙을 고쳤으면 extension-human 에도 그대로 복사할 것');
});

console.log('② 이어 본 페이지만');
const NOW = 1_000_000_000;
t('1페이지는 언제나 새로 시작', () => {
  const m = HvCore.mergePage({ kw: '다른', pages: { 1: [org(1)], 2: [org(2)] }, at: NOW }, '캠핑의자', 1, [org(9)], NOW);
  assert.ok(m.ok); assert.deepStrictEqual(Object.keys(m.state.pages), ['1']); assert.strictEqual(m.state.kw, '캠핑의자');
});
t('1 → 2 → 3 차례로 이어진다', () => {
  let s = HvCore.mergePage(null, 'k', 1, [org(1)], NOW).state;
  let m = HvCore.mergePage(s, 'k', 2, [org(2)], NOW + 1000); assert.ok(m.ok);
  m = HvCore.mergePage(m.state, 'k', 3, [org(3)], NOW + 2000); assert.ok(m.ok);
  assert.deepStrictEqual(Object.keys(m.state.pages).map(Number), [1, 2, 3]);
});
t('처음 본 것이 2페이지면 거절(앞 오가닉 수를 모른다)', () => {
  const m = HvCore.mergePage(null, 'k', 2, [org(2)], NOW);
  assert.strictEqual(m.ok, false); assert.strictEqual(m.reason, 'need-page-1');
});
t('1페이지 뒤 바로 3페이지면 거절(2페이지 빠짐)', () => {
  const s = HvCore.mergePage(null, 'k', 1, [org(1)], NOW).state;
  const m = HvCore.mergePage(s, 'k', 3, [org(3)], NOW); assert.strictEqual(m.ok, false); assert.strictEqual(m.reason, 'gap');
});
t('다른 검색어의 2페이지는 거절', () => {
  const s = HvCore.mergePage(null, 'k', 1, [org(1)], NOW).state;
  assert.strictEqual(HvCore.mergePage(s, 'z', 2, [org(2)], NOW).ok, false);
});
t('30분이 넘은 세션은 이어지지 않는다', () => {
  const s = HvCore.mergePage(null, 'k', 1, [org(1)], NOW).state;
  assert.strictEqual(HvCore.mergePage(s, 'k', 2, [org(2)], NOW + HvCore.SESSION_MS + 1).ok, false);
});
t('3페이지까지 봤다가 2페이지로 돌아가면 3페이지는 버린다', () => {
  let s = HvCore.mergePage(null, 'k', 1, [org(1)], NOW).state;
  s = HvCore.mergePage(s, 'k', 2, [org(2)], NOW).state;
  s = HvCore.mergePage(s, 'k', 3, [org(3)], NOW).state;
  const m = HvCore.mergePage(s, 'k', 2, [org(22)], NOW);
  assert.ok(m.ok); assert.deepStrictEqual(Object.keys(m.state.pages).map(Number), [1, 2]);
  assert.strictEqual(m.state.pages[2][0].nvMid, '22');
});

console.log('③ 순번');
t('광고는 순번을 먹지 않고 2페이지는 1페이지 오가닉 수에 이어진다', () => {
  const p1 = [ad(900), ...range(1, 40, org), ad(901)];
  const p2 = [ad(902), ...range(41, 80, org)];
  let s = HvCore.mergePage(null, 'k', 1, p1, NOW).state;
  s = HvCore.mergePage(s, 'k', 2, p2, NOW).state;
  const b = HvCore.build(s, RankRules, 0);
  assert.strictEqual(b.products.length, 80);
  assert.strictEqual(b.products[40].rank, 41); assert.strictEqual(b.products[40].nvMid, '41');
  assert.strictEqual(b.products[40].sourcePage, 2);
  assert.strictEqual(b.adSkipped, 3);
  assert.strictEqual(b.pagesRead, 2);
  b.products.forEach((p, i) => assert.strictEqual(p.rank, i + 1));
});
t('앞 페이지에 나온 상품이 뒤에 또 나오면 한 번만(수집기와 같은 중복 규칙)', () => {
  let s = HvCore.mergePage(null, 'k', 1, range(1, 40, org), NOW).state;
  s = HvCore.mergePage(s, 'k', 2, [org(40), ...range(41, 79, org)], NOW).state;
  const b = HvCore.build(s, RankRules, 0);
  assert.strictEqual(b.products.length, 79);
  assert.strictEqual(new Set(b.products.map((p) => p.productId)).size, 79);
});
t('300위에서 멈춘다', () => {
  let s = HvCore.mergePage(null, 'k', 1, range(1, 40, org), NOW).state;
  for (let p = 2; p <= 9; p++) s = HvCore.mergePage(s, 'k', p, range((p - 1) * 40 + 1, p * 40, org), NOW).state;
  const b = HvCore.build(s, RankRules, 0);
  assert.strictEqual(b.covered, 300);
});

console.log('④ 결과 끝');
t('전체 수를 모르면 끝이 아니다', () => {
  const s = HvCore.mergePage(null, 'k', 1, range(1, 12, org), NOW).state;
  assert.strictEqual(HvCore.build(s, RankRules, 0).endOfResults, false);
});
t('전체 수만큼 다 담았을 때만 끝', () => {
  const s = HvCore.mergePage(null, 'k', 1, range(1, 12, org), NOW).state;
  assert.strictEqual(HvCore.build(s, RankRules, 12).endOfResults, true);
  assert.strictEqual(HvCore.build(s, RankRules, 13).endOfResults, false);
});

console.log('⑤ 추적 키워드만');
t('목록에 있는 검색어만 보낸다', () => {
  const set = new Set(['캠핑의자']);
  assert.strictEqual(HvCore.isTracked(set, '캠핑의자'), true);
  assert.strictEqual(HvCore.isTracked(set, ' 캠핑의자 '), true);
  assert.strictEqual(HvCore.isTracked(set, '개인 검색어'), false);
});
t('목록이 없으면(서버에 못 닿음) 아무것도 안 보낸다', () => {
  assert.strictEqual(HvCore.isTracked(null, '캠핑의자'), false);
  assert.strictEqual(HvCore.isTracked(undefined, '캠핑의자'), false);
});
t('background 가 isTracked 로 거른 뒤에야 서버로 보낸다', () => {
  const src = fs.readFileSync(path.join(ROOT, 'background.js'), 'utf8');
  const gate = src.indexOf('if (!HvCore.isTracked(set, d.keyword)) return;');
  const post = src.indexOf("/api/human-view/page");
  assert.ok(gate > 0 && post > gate, '추적 키워드 거름이 보내기보다 앞에 있어야 한다');
});

console.log('⑥ 화면 쪽 실제 실행');
function fakePage(href, nextData) {
  const events = [];
  const u = new URL(href);
  const doc = {
    readyState: 'complete',
    addEventListener() {},
    getElementById: () => null,
    dispatchEvent(ev) { events.push(JSON.parse(ev.detail)); return true; },
  };
  const calls = [];
  function fakeFetch(input) {
    calls.push(String(input));
    const url = String(input);
    const body = fakeFetch.bodies[url] || '{}';
    const res = { url, status: fakeFetch.status || 200,
                  clone() { return { text: () => Promise.resolve(body) }; } };
    return Promise.resolve(res);
  }
  fakeFetch.bodies = {};
  const win = { fetch: fakeFetch, __NEXT_DATA__: nextData, XMLHttpRequest: undefined };
  const ctx = { window: win, document: doc, location: { href, pathname: u.pathname, search: u.search },
                URL, CustomEvent: class { constructor(n, o) { this.type = n; this.detail = o.detail; } },
                Function, JSON, Date, Set, Object, Promise, String, Number, Array, setTimeout };
  win.window = win;
  vm.createContext(ctx);
  // 페이지 세계의 fetch 는 window.fetch — 전역 이름으로도 보이게
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'human_tap.js'), 'utf8'), ctx);
  return { events, calls, win, fakeFetch };
}
const ND = { props: { pageProps: { initialState: { products: { total: 5000, list: [
  { item: ad(900) }, ...range(1, 40, (i) => ({ item: org(i, { secret: { nested: 1 }, reviewCount: 3 }) })) ] } } } } };
t('첫 화면(서버가 그린 1페이지)을 읽어 넘긴다 · 필요한 칸만', () => {
  const pg = fakePage('https://search.shopping.naver.com/search/all?query=%EC%BA%A0%ED%95%91', ND);
  assert.strictEqual(pg.events.length, 1);
  const e = pg.events[0];
  assert.strictEqual(e.keyword, '캠핑'); assert.strictEqual(e.page, 1); assert.strictEqual(e.total, 5000);
  assert.strictEqual(e.list.length, 41);
  assert.strictEqual(e.list[1].secret, undefined, '필요 없는 칸은 버린다');
  assert.strictEqual(e.list[0].adId, 'a900', '광고 판별 칸은 남긴다');
});
t('가격순 화면은 읽지 않는다', () => {
  const pg = fakePage('https://search.shopping.naver.com/search/all?query=k&sort=price_asc', ND);
  assert.strictEqual(pg.events.length, 0);
});
(async () => {
  const pg = fakePage('https://search.shopping.naver.com/search/all?query=k', null);
  const u2 = 'https://search.shopping.naver.com/api/search/all?query=k&pagingIndex=2&pagingSize=40';
  pg.fakeFetch.bodies[u2] = JSON.stringify({ shoppingResult: { total: 5000, products: range(41, 80, (i) => org(i)) } });
  const uPrice = 'https://search.shopping.naver.com/api/search/all?query=k&pagingIndex=2&sort=price_asc';
  pg.fakeFetch.bodies[uPrice] = pg.fakeFetch.bodies[u2];
  const uOther = 'https://other.example.com/api/search/all?query=k&pagingIndex=2';
  pg.fakeFetch.bodies[uOther] = pg.fakeFetch.bodies[u2];
  const r1 = await pg.win.fetch(u2);
  await pg.win.fetch(uPrice);
  await pg.win.fetch(uOther);
  await new Promise((ok) => setTimeout(ok, 20));
  t('페이지 넘김 응답 1건만 읽힘(가격순·다른 주소는 버림)', () => {
    assert.strictEqual(pg.events.length, 1);
    assert.strictEqual(pg.events[0].page, 2); assert.strictEqual(pg.events[0].list.length, 40);
    assert.strictEqual(pg.events[0].src, 'tap');
  });
  t('감싼 fetch 는 원래 요청을 한 번씩만 그대로 보낸다(추가 요청 0)', () => {
    assert.deepStrictEqual(pg.calls, [u2, uPrice, uOther]);
    assert.strictEqual(r1.url, u2);
  });

  console.log('⑦ 권한·요청 범위');
  t('권한은 storage 하나 · 주소는 네이버쇼핑 검색과 우리 서버 둘뿐', () => {
    const m = JSON.parse(fs.readFileSync(path.join(ROOT, 'manifest.json'), 'utf8'));
    assert.deepStrictEqual(m.permissions, ['storage']);
    assert.deepStrictEqual(m.host_permissions.slice().sort(),
      ['https://logic.metainc.co.kr/*', 'https://search.shopping.naver.com/*']);
    assert.ok(!/debugger|cookies|history|webRequest|tabs"/.test(JSON.stringify(m)), '민감 권한이 없어야 한다');
  });
  t('background 의 요청은 전부 우리 서버', () => {
    const src = fs.readFileSync(path.join(ROOT, 'background.js'), 'utf8');
    const fetches = src.match(/fetch\(`[^`]*`/g) || [];
    assert.ok(fetches.length >= 2);
    fetches.forEach((f) => assert.ok(f.startsWith('fetch(`${SERVER}/api/human-view/'), f));
    assert.ok(/const SERVER = 'https:\/\/logic\.metainc\.co\.kr';/.test(src));
  });
  t('화면 쪽은 클릭·이동·스크롤을 하지 않는다', () => {
    const src = fs.readFileSync(path.join(ROOT, 'human_tap.js'), 'utf8') + fs.readFileSync(path.join(ROOT, 'human_view.js'), 'utf8');
    ['.click(', 'location.href =', 'location.assign', 'pushState', 'scrollTo', 'scrollBy', 'dispatchEvent(new MouseEvent', 'Input.dispatch']
      .forEach((bad) => assert.ok(src.indexOf(bad) < 0, bad));
  });
  t('로그인 여부는 링크만 본다(쿠키를 읽지 않는다)', () => {
    const src = fs.readFileSync(path.join(ROOT, 'human_view.js'), 'utf8') + fs.readFileSync(path.join(ROOT, 'human_tap.js'), 'utf8');
    assert.ok(src.indexOf('document.cookie') < 0);
  });

  console.log(`\n${pass} 통과 · ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})();
