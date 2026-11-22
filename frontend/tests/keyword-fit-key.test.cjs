/* 회귀 — 보고서 화면의 키워드 적합도 판정 「다시 받기」(2026-11-21)
 *
 * 고친 것: 판정을 다시 받을지 정하는 열쇠가 판매자 태그·연관어의 「개수」만 봤다.
 *   개수가 같은 채 내용이 바뀌면(#다크초콜릿 → #밀크초콜릿 · 저장 보고서를 불러와 상태를 갈아 끼울 때)
 *   서버에 다시 묻지 않아 옛 판정(옛 「상품명 후보」)이 그대로 남았다.
 *   (11-22 보강) 열쇠를 본문의 해시로 줄였더니 길이가 같고 해시가 겹치는 다른 본문('Ab…' ↔ 'BA…')에서 같은 일이 났다.
 * 지키는 것:
 *   ① 열쇠 = 서버에 보내는 본문 문자열 그대로 — 해시로 줄이지 않는다. 내용이 같으면 객체가 새로 생겨도 같은 본문.
 *   ② 실제 컴포넌트 코드(AnalysisResults.jsx 의 판정 훅)를 작은 React 흉내로 돌려:
 *      태그 내용만 바뀌어도 다시 묻는다 · 새 답이 오기 전에는 옛 판정을 쓰지 않는다 · 같은 내용이면 다시 묻지 않는다 ·
 *      해시가 겹치는 본문끼리도 다시 묻는다.
 * 실행: node frontend/tests/keyword-fit-key.test.cjs   (의존성 없음)
 */
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync('frontend/js/components/AnalysisResults.jsx', 'utf8');
let passed = 0, failed = 0;
function ok(cond, msg) { if (cond) passed++; else { failed++; console.log('  ✗ ' + msg); } }

// ── 가짜 시계 · 가짜 서버 ──
let timers = [], tid = 0, calls = [], pending = [];
const ctx = {
  window: {}, API_BASE: '/api', _authHeaders: h => h,
  setTimeout: (fn) => { timers.push({ id: ++tid, fn }); return tid; },
  clearTimeout: (id) => { timers = timers.filter(t => t.id !== id); },
  fetch: (url, opt) => { calls.push({ url, body: JSON.parse(opt.body) }); return new Promise(res => pending.push(res)); },
  JSON, String, Object, Array, Math,
};
vm.createContext(ctx);

// ── ① 보내는 묶음 ──
const cut = src.indexOf('window.AnalysisResults = function');
vm.runInContext(src.slice(0, cut), ctx);
const build = ctx.window.buildKeywordFitPayload;
ok(typeof build === 'function', '묶음 함수가 있다');
ok(!/keywordFitKey|_fitKey/.test(src), '본문을 해시·지문으로 줄여 열쇠로 쓰지 않는다(충돌하면 옛 판정이 남는다)');
const rel = (names) => ({ related_keywords: names.map((k, i) => ({ keyword: k, totalVolume: 1000 - i })), golden_keywords: [], pool: [] });
const base = (tags, names) => ({ keyword: '파베초콜릿', companyName: '예시상점', relatedData: rel(names || ['생초콜릿', '수제초콜릿']),
  advertiserReport: { product_info: { product_name: '예시 생초콜릿' } }, analysisData: null,
  htmlDetail: { sellerTags: tags, reviewData: { category: '식품>과자>초콜릿' } }, shopProducts: [] });
const k = (s) => JSON.stringify({ payload: build(s) });
ok(build({ keyword: '', relatedData: rel(['a']) }) === null && build({ keyword: 'x', relatedData: null }) === null, '검색어·연관어가 없으면 묶음 없음');
ok(k(base(['다크초콜릿'])) !== k(base(['밀크초콜릿'])), '태그 개수는 같고 내용만 달라도 본문이 달라진다');
ok(k(base(['다크초콜릿'])) === k(base(['다크초콜릿'])), '내용이 같으면 새로 만든 객체여도 본문이 같다');
ok(k(base(['a'], ['생초콜릿', '수제초콜릿'])) !== k(base(['a'], ['생초콜릿', '화이트초콜릿'])), '연관어 개수는 같고 내용만 달라도 본문이 달라진다');
const other = base(['a']); other.advertiserReport = { product_info: { product_name: '다른 상품' } };
ok(k(base(['a'])) !== k(other), '상품명이 바뀌면 본문이 달라진다');
const cat = base(['a']); cat.htmlDetail.reviewData.category = '식품>빵>베이글';
ok(k(base(['a'])) !== k(cat), '카테고리가 바뀌면 본문이 달라진다');
// 길이가 같고 흔한 문자열 해시(djb2: h*33+c)가 겹치는 두 본문 — 'Ab' 와 'BA' 는 65*33+98 = 66*33+65
const djb2 = (t) => { let h = 5381; for (let i = 0; i < t.length; i++) h = ((h << 5) + h + t.charCodeAt(i)) | 0; return h >>> 0; };
const HASH_REL = ['Ab초콜릿', 'BA초콜릿'];
const hA = k(base(['Ab초콜릿'], HASH_REL)), hB = k(base(['BA초콜릿'], HASH_REL));
ok(hA !== hB && hA.length === hB.length && djb2(hA) === djb2(hB), '시험 자료 — 길이·해시가 같은 서로 다른 두 본문');

// ── ② 실제 훅 코드 — 작은 React 흉내 ──
const end = src.indexOf('    /* 골든 키워드 카드 — 판정에서 빠진 말이면');
ok(cut > 0 && end > cut, '컴포넌트에서 판정 훅 구간을 찾았다');
let slots = [], cursor = 0, effects = [], rerender = null;
const sameDeps = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
ctx.React = {
  useState: (init) => { const i = cursor++; if (!(i in slots)) slots[i] = { v: init };
    return [slots[i].v, (nv) => { slots[i].v = nv; }]; },
  useMemo: (fn, deps) => { const i = cursor++; const s = slots[i];
    if (s && sameDeps(s.deps, deps)) return s.v; const v = fn(); slots[i] = { v, deps }; return v; },
  useEffect: (fn, deps) => { const i = cursor++; const s = slots[i];
    if (s && sameDeps(s.deps, deps)) return; effects.push(() => { if (s && s.cleanup) s.cleanup(); slots[i].cleanup = fn(); }); slots[i] = { deps, cleanup: s && s.cleanup }; },
};
vm.runInContext('window.__fitProbe = ' + src.slice(cut + 'window.AnalysisResults = '.length, end)
  + '    return { keywordFit: keywordFit, fitBody: _fitBody };\n};', ctx);
function render(props) { cursor = 0; effects = []; const out = ctx.window.__fitProbe(props); effects.forEach(e => e()); return out; }
function runTimers() { const t = timers; timers = []; t.forEach(x => x.fn()); }
async function answer(data) { const res = pending.shift(); res({ ok: true, json: () => Promise.resolve({ success: true, data }) }); await new Promise(r => setImmediate(r)); }
const propsOf = (s) => ({ searchedKeyword: s.keyword, companyName: s.companyName, relatedData: s.relatedData, advertiserReport: s.advertiserReport,
  analysisData: s.analysisData, htmlDetailResult: s.htmlDetail, shopProducts: s.shopProducts, searchedProductUrl: 'https://smartstore.naver.com/example/products/123' });

(async () => {
  // 첫 화면 — 태그 #다크초콜릿
  const A = propsOf(base(['다크초콜릿']));
  let v = render(A);
  ok(v.keywordFit === null && calls.length === 0, '답이 오기 전에는 판정 없음(종전 화면)');
  runTimers();
  ok(calls.length === 1 && calls[0].url === '/api/keywords/fit', '판정을 한 번 묻는다');
  ok(JSON.stringify(calls[0].body.payload.htmlDetail.sellerTags) === '["다크초콜릿"]', '보낸 태그 = 다크초콜릿');
  await answer({ passed: ['다크초콜릿'], nameCandidates: [{ keyword: '다크초콜릿', total: 10 }] });
  v = render(A);
  ok(v.keywordFit && v.keywordFit.nameCandidates[0].keyword === '다크초콜릿', '답이 오면 그 판정을 쓴다');

  // 같은 내용 · 새 객체(부모가 다시 그림) — 다시 묻지 않는다
  v = render(propsOf(base(['다크초콜릿'])));
  runTimers();
  ok(calls.length === 1 && v.keywordFit && v.keywordFit.nameCandidates[0].keyword === '다크초콜릿', '내용이 같으면 다시 묻지 않고 판정 유지');

  // 태그 개수는 그대로, 내용만 #밀크초콜릿 — 옛 판정을 쓰지 않고 다시 묻는다
  const B = propsOf(base(['밀크초콜릿']));
  v = render(B);
  ok(v.keywordFit === null, '내용이 바뀌면 새 답이 오기 전까지 옛 판정(다크초콜릿 후보)을 쓰지 않는다');
  runTimers();
  ok(calls.length === 2 && JSON.stringify(calls[1].body.payload.htmlDetail.sellerTags) === '["밀크초콜릿"]', '바뀐 태그로 다시 묻는다');
  await answer({ passed: ['밀크초콜릿'], nameCandidates: [{ keyword: '밀크초콜릿', total: 9 }] });
  v = render(B);
  ok(v.keywordFit && v.keywordFit.nameCandidates[0].keyword === '밀크초콜릿', '새 판정으로 바뀐다');

  // 저장 보고서 불러오기 — 연관어 개수는 같고 내용이 다른 다른 보고서로 상태를 갈아 끼움
  const C = propsOf(base(['밀크초콜릿'], ['말차초콜릿', '카카오닙스']));
  v = render(C);
  ok(v.keywordFit === null, '다른 보고서를 불러오면 앞 보고서의 판정을 쓰지 않는다');
  runTimers();
  ok(calls.length === 3 && calls[2].body.payload.related.related_keywords[0].keyword === '말차초콜릿', '불러온 보고서의 연관어로 다시 묻는다');

  // 늦게 온 옛 답 — 지금 내용의 답이 아니면 쓰지 않는다
  const D = propsOf(base(['화이트초콜릿'], ['말차초콜릿', '카카오닙스']));
  v = render(D);            // C 의 답이 아직 안 왔는데 내용이 또 바뀜
  await answer({ passed: ['C의답'], nameCandidates: [{ keyword: 'C의답', total: 1 }] });
  v = render(D);
  ok(v.keywordFit === null, '앞 내용으로 물은 답이 늦게 와도 쓰지 않는다');

  // 길이·해시가 같은 다른 본문 — 그래도 다시 묻고 옛 판정을 쓰지 않는다(교차검증 재현: Ab초콜릿 → BA초콜릿)
  const HA = propsOf(base(['Ab초콜릿'], HASH_REL));
  v = render(HA); runTimers();
  const n0 = calls.length;
  await answer({ passed: ['Ab초콜릿'], nameCandidates: [{ keyword: 'Ab초콜릿', total: 5 }] });
  v = render(HA);
  ok(v.keywordFit && v.keywordFit.nameCandidates[0].keyword === 'Ab초콜릿', '(해시 겹침) 첫 판정 = Ab초콜릿');
  const HB = propsOf(base(['BA초콜릿'], HASH_REL));
  v = render(HB);
  ok(v.keywordFit === null, '(해시 겹침) 내용이 바뀌면 옛 판정(Ab초콜릿 후보)을 쓰지 않는다');
  runTimers();
  ok(calls.length === n0 + 1 && JSON.stringify(calls[calls.length - 1].body.payload.htmlDetail.sellerTags) === '["BA초콜릿"]', '(해시 겹침) 바뀐 태그로 다시 묻는다');
  await answer({ passed: ['BA초콜릿'], nameCandidates: [{ keyword: 'BA초콜릿', total: 4 }] });
  v = render(HB);
  ok(v.keywordFit && v.keywordFit.nameCandidates[0].keyword === 'BA초콜릿', '(해시 겹침) 새 판정으로 바뀐다');

  // 연관어가 사라지면 판정도 비운다
  v = render(Object.assign({}, HB, { relatedData: null }));
  ok(v.keywordFit === null && v.fitBody === '', '연관어가 없으면 판정 없음');

  console.log('keyword_fit_key: ' + passed + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
