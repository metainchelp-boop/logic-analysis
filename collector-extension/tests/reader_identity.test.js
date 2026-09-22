/* 판독 조각(코덱스 1.22.0 이식 3차 · v1.25.0 · 2026-09-22) — 회귀 시험
 *   ① rank_rules — productId 는 nvMid 우선 · 식별값 없는 행은 담지 않고 invalidSkipped 로 센다 · sourcePage · productIdentity 규칙
 *   ② net_tap — 요청 범위(keyword·page·scopeVerified·sourceKnown)와 응답 대응(responseMatched)이 기록에 실린다 · 요청은 안 늘린다
 */
const fs = require('fs');
const path = require('path');
const RR = require('../rank_rules.js');
const TAP = fs.readFileSync(path.join(__dirname, '..', 'net_tap.js'), 'utf8');
let pass = 0, fail = 0;
const ok = (name, cond) => { (cond ? pass++ : fail++); console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${name}`); };

console.log('① rank_rules');
ok('productIdentity — 문자열 다듬기 · 양의 정수만 · 그 밖은 빈 값', RR.productIdentity(' 12 ') === '12' && RR.productIdentity(77) === '77'
   && RR.productIdentity(0) === '' && RR.productIdentity(-3) === '' && RR.productIdentity({}) === '' && RR.productIdentity(1.5) === '');
const p1 = RR.toProduct({ nvMid: '9001', id: 'row-1', productTitle: 't' }, 1);
ok('🔴 nvMid 가 있으면 productId = nvMid(행 id 아님) · nvMid 칸도 실림', p1.productId === '9001' && p1.nvMid === '9001');
const p2 = RR.toProduct({ id: 'row-2', productTitle: 't' }, 1);
ok('nvMid 없으면 id 로(종전) · nvMid 칸은 빈 값', p2.productId === 'row-2' && p2.nvMid === '');
const st = { products: [], seenIds: new Set(), maxRank: 300, adSkipped: 0, dupSkipped: 0, adHintMissed: 0, sourcePage: 2 };
RR.takeOrganic([{ nvMid: '1', productTitle: 'a' }, { productTitle: 'no-id' }, { nvMid: '1', productTitle: 'dup' }, { id: 'r9', productTitle: 'b' }], st);
ok('🔴 식별값 없는 행은 담지 않고 invalidSkipped=1 · 중복은 dupSkipped=1 · 순번은 담긴 것만', st.products.length === 2 && st.invalidSkipped === 1 && st.dupSkipped === 1
   && st.products.map((p) => p.rank).join(',') === '1,2' && st.products[1].productId === 'r9');
ok('sourcePage 가 있으면 담긴 상품에 찍힌다', st.products.every((p) => p.sourcePage === 2));
const st2 = { products: [], seenIds: new Set(), maxRank: 300, adSkipped: 0, dupSkipped: 0, adHintMissed: 0 };
RR.takeOrganic([{ id: '5', productTitle: 'a' }], st2);
ok('sourcePage 없으면 종전 모양 그대로(칸 없음)', !('sourcePage' in st2.products[0]) && st2.invalidSkipped === undefined);

console.log('\n② net_tap 요청 범위');
const fetched = [];
const mkRes = (status, ct, body, url) => ({ status, url, headers: { get: (k) => (k === 'content-type' ? ct : '') }, clone() { return { text: async () => body }; } });
const origFetch = function (input) { fetched.push(String(input)); return Promise.resolve(origFetch.__next); };
const win = { fetch: origFetch, XMLHttpRequest: undefined };
new Function('window', 'location', TAP)(win, { href: 'https://search.shopping.naver.com/search/all?query=x' });
const body = JSON.stringify({ shoppingResult: { products: [{ nvMid: '1', productTitle: 't', mallName: 'm' }] } });
(async () => {
  const u = 'https://search.shopping.naver.com/api/search/all?query=%EA%B9%80%EC%B9%98&pagingIndex=2&sort=rel&productSet=total';
  origFetch.__next = mkRes(200, 'application/json', body, u);
  await win.fetch(u); await new Promise((r) => setTimeout(r, 5));
  const it = win.__mcTap.items[0];
  ok('🔴 아는 검색 요청 — keyword·page·sourceKnown·scopeVerified·responseMatched 전부 실림', !!it && it.keyword === '김치' && it.page === 2 && it.sourceKnown === true && it.scopeVerified === true && it.responseMatched === true && typeof it.requestId === 'string');
  ok('요청은 한 번만 나갔다(추가 요청 0)', fetched.length === 1);
  const u2 = 'https://search.shopping.naver.com/api/search/all?query=x&pagingIndex=3&sort=review';
  origFetch.__next = mkRes(200, 'application/json', body, u2);
  await win.fetch(u2); await new Promise((r) => setTimeout(r, 5));
  ok('🔴 정렬이 rel 이 아니면 scopeVerified=false(그 응답을 순위로 읽으면 안 된다)', win.__mcTap.items[1].scopeVerified === false && win.__mcTap.items[1].sourceKnown === true);
  const u3 = 'https://search.shopping.naver.com/api/search/all?query=x&pagingIndex=4&pagingSize=80';
  origFetch.__next = mkRes(200, 'application/json', body, u3);
  await win.fetch(u3); await new Promise((r) => setTimeout(r, 5));
  ok('pagingSize 가 40 이 아니면 scopeVerified=false', win.__mcTap.items[2].scopeVerified === false);
  const u4 = 'https://search.shopping.naver.com/api/search/all?query=x&pagingIndex=5';
  origFetch.__next = mkRes(200, 'application/json', body, 'https://search.shopping.naver.com/api/search/all?query=x&pagingIndex=1');
  await win.fetch(u4); await new Promise((r) => setTimeout(r, 5));
  ok('🔴 응답 주소가 요청과 다르면(재사용·리다이렉트) responseMatched=false', win.__mcTap.items[3].responseMatched === false && win.__mcTap.items[3].page === 5);
  origFetch.__next = mkRes(200, 'application/json', body, 'https://other.example/x');
  await win.fetch(new URL('https://other.example/x?query=x&pagingIndex=6'), { method: 'POST' }); await new Promise((r) => setTimeout(r, 5));
  ok('다른 호스트·POST 는 sourceKnown=false(기록은 남는다)', win.__mcTap.items[4].sourceKnown === false && win.__mcTap.items[4].page === 6);
  console.log(`\n${fail ? '❌' : '✅'} 판독 조각 회귀 — ${pass} 통과 · ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('시험 자체가 죽음:', e); process.exit(1); });
