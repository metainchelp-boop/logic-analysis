/* 📒 관측 봉투 + 부분 수집 — 회귀 시험 (v1.23.0 · 코덱스 1.22.0 이식 · 2026-09-22)
 *
 * 무엇을 막는 시험인가:
 *   ① 중간에 막히면 담은 것을 버리던 종전 동작 → 이제 partial 로 올린다(서버는 찾은 순위만 적는다).
 *   ② 목표를 다 찾아 조기 종료하면 target_complete(수집분 저장 + 찾은 순위만) — 「300위 밖」이 잘못 적히던 구멍.
 *   ③ 끝까지 봤으면 complete(DEPTH_REACHED · SHORT_PAGE · PAGE_CAP).
 *   ④ 페이지 증거(page·keyword·source·verified)와 상품의 sourcePage·nvMid 가 실린다.
 *   ⑤ uploadKeyword 가 봉투를 meta.observation 으로 싣고, runCollection 이 partial 을 따로 세며 막힘 뒤 쉼을 건다.
 *
 * ⚠️ 문구가 아니라 **실제 collectKeyword 를 꺼내 가짜 fetchPage 로 돌린다.**
 */
const fs = require('fs');
const path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
const RR = require('../rank_rules.js');
let pass = 0, fail = 0;
const ok = (name, cond) => { (cond ? pass++ : fail++); console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${name}`); };

function extract(name) {
  const head = `async function ${name}(`;
  const i = SRC.indexOf(head);
  if (i < 0) throw new Error(`${name} 을 못 찾았다`);
  let j = SRC.indexOf('{', i), depth = 0, k = j;
  for (; k < SRC.length; k++) {
    if (SRC[k] === '{') depth++;
    else if (SRC[k] === '}') { depth--; if (depth === 0) { k++; break; } }
  }
  return SRC.slice(i, k);
}
function fnSrc(name) { // non-async helper
  const head = `function ${name}(`;
  const i = SRC.indexOf(head);
  let j = SRC.indexOf('{', i), depth = 0, k = j;
  for (; k < SRC.length; k++) { if (SRC[k] === '{') depth++; else if (SRC[k] === '}') { depth--; if (depth === 0) { k++; break; } } }
  return SRC.slice(i, k);
}

function page(n, from) {
  const list = [];
  for (let i = 0; i < n; i++) list.push({ id: String(from + i), productTitle: 't' + (from + i), mallName: 'm', mallProductUrl: 'https://smartstore.naver.com/m/products/' + (from + i), price: 1 });
  return list;
}

/** collectKeyword 를 실제로 돌린다. pages = [{list, src, stopReason}|Error, …] */
async function run(pages, { targets = null, maxRank = 300, pagesPerKeyword = 8 } = {}) {
  const store = {};
  const chrome = { storage: { local: { get: async (k) => ({}), set: async (o) => Object.assign(store, o) } } };
  let call = 0;
  const deps = {
    chrome, RR,
    CFG: { maxRank, pagesPerKeyword, maxPages: 8, minGapMs: 0, maxGapMs: 0 },
    _navMode: { reported: false }, _clickedAt: 0, _staleReported: false, _lastClickBranch: '', _lastClickHow: '',
    EVIDENCE_SOURCES: new Set(['tap', 'router', 'nextdata']),
    targetsFor: () => targets, allTargetsFound: (products, want) => {
      const got = new Set(products.map((p) => String(p.nvMid || p.id || p.productId || '')));
      return want.every((w) => got.has(String(w)));
    },
    organicIds: (list) => list.map((p) => String(p.id)),
    sleep: async () => {}, jitter: () => 0,
    instanceId: async () => 'inst-1',
    crypto: { randomUUID: () => '11111111-1111-4111-8111-111111111111' },
    fetchPage: async () => { const p = pages[call++]; if (p instanceof Error) throw p; return Object.assign({ total: 500 }, p); },
  };
  const fn = new Function(...Object.keys(deps), `${extract('collectKeyword')}\nreturn collectKeyword;`)(...Object.values(deps));
  return fn('김치');
}

(async () => {
  console.log('📒 관측 봉투 시험');
  /* ① 막힘 → partial */
  let r = await run([{ list: page(40, 1), src: 'nextdata', href: 'https://search.shopping.naver.com/search/all?query=김치' },
                     new Error('BLOCKED:https://ncpt.naver.com/…')]);
  ok('🔴 2페이지에서 막히면 1페이지 40개를 버리지 않고 돌려준다', r.products.length === 40);
  ok('🔴 status=partial · stopReason=BLOCKED · blocked 사유 실림', r.observation.status === 'partial' && r.observation.stopReason === 'BLOCKED' && /^BLOCKED:/.test(r.blocked));
  ok('🔴 증거 1장(page 1 · keyword · source nextdata · verified) · pagesRead 1', r.observation.pageEvidence.length === 1 && r.observation.pageEvidence[0].page === 1
     && r.observation.pageEvidence[0].keyword === '김치' && r.observation.pageEvidence[0].source === 'nextdata' && r.observation.pageEvidence[0].verified === true && r.observation.pagesRead === 1);
  ok('🔴 상품에 sourcePage=1 · nvMid 가 찍힌다', r.products.every((p) => p.sourcePage === 1 && p.nvMid === p.productId));
  ok('organicCount·coveredThroughRank = 40 · observationId uuid · workerId', r.observation.organicCount === 40 && r.observation.coveredThroughRank === 40
     && r.observation.observationId === '11111111-1111-4111-8111-111111111111' && r.observation.workerId === 'inst-1' && r.observation.finishedAt);

  /* ② 조기 종료 → target_complete */
  r = await run([{ list: page(40, 1), src: 'tap' }], { targets: ['5', '7'] });
  ok('🔴 목표를 1페이지에서 다 찾으면 target_complete · TARGETS_FOUND · stoppedEarly', r.observation.status === 'target_complete' && r.observation.stopReason === 'TARGETS_FOUND' && r.stoppedEarly && r.stoppedEarly.page === 1);
  ok('targetIds 가 봉투에 실린다', JSON.stringify(r.observation.targetIds) === JSON.stringify(['5', '7']));

  /* ③ 끝까지 → complete */
  r = await run([{ list: page(40, 1), src: 'tap' }, { list: page(30, 41), src: 'router' }]);
  ok('🔴 마지막 장이 40개 미만이면 complete · SHORT_PAGE(결과가 여기서 끝)', r.observation.status === 'complete' && r.observation.stopReason === 'SHORT_PAGE' && r.products.length === 70);
  ok('두 장 증거 · 2페이지 상품은 sourcePage=2', r.observation.pageEvidence.length === 2 && r.observation.pageEvidence[1].source === 'router' && r.products[69].sourcePage === 2);
  const eight = []; for (let i = 0; i < 8; i++) eight.push({ list: page(40, i * 40 + 1), src: 'tap' });
  r = await run(eight);
  ok('🔴 300개 채우면 complete · DEPTH_REACHED', r.observation.status === 'complete' && r.observation.stopReason === 'DEPTH_REACHED' && r.products.length === 300);
  r = await run(eight, { maxRank: 400 });
  ok('8장 다 봤는데 300 미달이면 complete · PAGE_CAP', r.observation.status === 'complete' && r.observation.stopReason === 'PAGE_CAP');
  r = await run([{ list: page(40, 1), src: 'tap' }, { list: [], src: '', stopReason: 'STALE_PAGE' }]);
  ok('🔴 2페이지가 안 바뀌면(STALE_PAGE) partial · 1페이지는 살린다', r.observation.status === 'partial' && r.observation.stopReason === 'STALE_PAGE' && r.products.length === 40);
  r = await run([new Error('판독 실패(READ_FAILED) — 차단 아님')]);
  ok('0건이면 failed · READ_FAILED · error 문구', r.observation.status === 'failed' && r.observation.stopReason === 'READ_FAILED' && /판독 실패/.test(r.observation.error) && r.products.length === 0 && !r.blocked);

  /* ⑤ 배선 */
  const up = extract('uploadKeyword');
  ok('🔴 uploadKeyword 가 meta.observation 으로 봉투를 싣는다', /observation: payload\.observation \|\| undefined/.test(up));
  const rc = extract('runCollection');
  ok('🔴 runCollection — partial 을 따로 세고 상태에 싣는다', /partial\+\+/.test(rc) && /setState\(\{ done, failed, partial, current: kw/.test(rc));
  ok('🔴 runCollection — 담은 것이 있으면 올린 뒤 막힘 처리(throw → catch 가 6시간 쉼)', /await uploadKeyword\(token, kw, payload\);\s*\n\s*if \(payload\.blocked\) \{[\s\S]{0,300}throw new Error\(payload\.blocked\)/.test(rc));
  ok('runCollection — 0건인데 막힘이면 종전대로 즉시 막힘 처리', /if \(!payload\.products\.length\) \{\s*\n\s*if \(payload\.blocked\) throw new Error\(payload\.blocked\);/.test(rc));
  const od = extract('runOnDemand');
  ok('runOnDemand 도 같은 규칙(올린 뒤 막힘 처리)', /await uploadKeyword\(token, kw, payload\);\s*\n\s*if \(payload\.blocked\) throw new Error\(payload\.blocked\);/.test(od));
  const fp = extract('fetchPage');
  ok('🔴 fetchPage 가 근거(src·href)를 돌려주고 NO_PAGER·STALE_PAGE 는 stopReason 으로', /src: out\.src \|\| '', href: out\.href \|\| ''/.test(fp) && /stopReason: 'NO_PAGER'/.test(fp) && /stopReason: 'STALE_PAGE'/.test(fp));
  ok('manifest 1.23.0 이상', (() => { const [a, b] = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'manifest.json'), 'utf8')).version.split('.').map(Number); return a > 1 || (a === 1 && b >= 23); })());
  console.log(`\n${fail ? '🔴' : '✅'} 통과 ${pass} · 실패 ${fail}`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('시험 자체가 죽음:', e); process.exit(1); });
