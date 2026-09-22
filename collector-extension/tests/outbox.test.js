/* 📤 미전송 보관함(outbox) — 회귀 시험 (v1.26.0 · 코덱스 1.22.0 이식 4차 · 2026-09-22)
 *
 * 무엇을 막는가:
 *   ① 서버가 잠깐 죽었을 때(회선 오류 · 5xx · 408 · 429) 모은 결과를 버리던 것 → 보관하고(queued) 회차는 계속.
 *   ② 서버가 「저장했다」(stored·observationId 일치)고 답할 때만 지운다 · 4xx·ACK 불일치는 격리(자동 재시도 없음).
 *   ③ 재시도 간격(30초×2^n · 최대 1시간) · 6회 후 검토 대기 · 「다시 보내기」는 검토 대기를 되살리되 격리는 안 건드림.
 *   ④ 상한(100건)을 넘으면 보관하지 않고 실패로(무한 증식 금지) · 요약(uploadSummary)에 본문·검색어가 없다.
 * ⚠️ 실제 함수(outboxAdd·flushOutbox·uploadKeyword·outboxSummary)를 꺼내 가짜 fetch·메모리 저장소로 돌린다(IndexedDB 없음 = 폴백 경로).
 */
const fs = require('fs');
const path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
const POPUP = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');
const HTML = fs.readFileSync(path.join(__dirname, '..', 'popup.html'), 'utf8');
let pass = 0, fail = 0;
const ok = (name, cond) => { (cond ? pass++ : fail++); console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${name}`); };
function block(startMarker, endMarker) {
  const i = SRC.indexOf(startMarker); const j = SRC.indexOf(endMarker, i);
  if (i < 0 || j < 0) throw new Error('블록을 못 찾았다: ' + startMarker);
  return SRC.slice(i, j);
}
// 보관함 블록(상수·Outbox·outboxAdd·flushOutbox) + uploadKeyword 를 통째로 꺼낸다(uploadKeyword 끝 = 'let running = false;')
const CODE = block("const OUTBOX_DB = 'metainc-collector-v2';", '\nlet running = false;');

function harness({ fetchImpl, token = 'tok' } = {}) {
  const logs = [], states = [];
  const deps = {
    CFG: { serverBase: 'http://t', pageSize: 40 },
    chrome: { runtime: { getManifest: () => ({ version: '1.26.0' }) } },
    crypto: globalThis.crypto, TextEncoder, indexedDB: undefined,
    setState: async (p) => { states.push(p); }, log: async (m) => { logs.push(m); },
    uploadSignature: () => '', _lastUp: { keyword: '', sig: '' }, reportBlocked: async () => {},
    _navMode: {}, _trustedNote: '', _entryNote: '', _entryVia: '',
    fetch: fetchImpl,
  };
  const api = new Function(...Object.keys(deps), `${CODE}\nreturn { Outbox, outboxAdd, flushOutbox, uploadKeyword, outboxSummary, outboxSync, _ackOk, canonicalJson, OUTBOX_MAX_ITEMS };`)(...Object.values(deps));
  return Object.assign(api, { logs, states, token });
}
const obs = (id) => ({ observationId: id, status: 'complete', finishedAt: '2026-09-22T01:00:00.000Z' });
const payload = (kw, id) => ({ total: 100, products: [{ rank: 1, productId: '9', title: 't', link: 'https://smartstore.naver.com/a/products/9' }], observation: obs(id) });
const SECRET = 'SECRET_KEYWORD_zz9';

(async () => {
  console.log('① 일시 장애 → 보관(queued) · 회차 계속');
  let calls = 0;
  let h = harness({ fetchImpl: async () => { calls++; throw new Error('ECONNREFUSED'); } });
  let r = await h.uploadKeyword('tok', SECRET, payload(SECRET, 'aaaaaaaa-0000-4000-8000-000000000001'));
  ok('🔴 회선 오류 → { queued: true } (예외 아님)', r && r.queued === true && calls === 1);
  let list = await h.Outbox.all();
  ok('보관함에 1건 · 본문·시도 0·격리 아님', list.length === 1 && list[0].attempts === 0 && list[0].quarantined === false && list[0].payload.keyword === SECRET);
  ok('상태 칸 outboxCount=1 갱신', h.states.some((s) => s.outboxCount === 1 && s.outboxReview === 0));
  h = harness({ fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }) });
  r = await h.uploadKeyword('tok', 'k2', payload('k2', 'aaaaaaaa-0000-4000-8000-000000000002'));
  ok('🔴 503 도 보관(queued)', r.queued === true && (await h.Outbox.all()).length === 1);
  h = harness({ fetchImpl: async () => ({ ok: false, status: 400, json: async () => ({ detail: '0건' }) }) });
  let threw = false;
  try { await h.uploadKeyword('tok', 'k3', payload('k3', 'aaaaaaaa-0000-4000-8000-000000000003')); } catch (e) { threw = /HTTP 400/.test(e.message); }
  ok('🔴 4xx(서버가 본문 거절)는 보관하지 않고 종전처럼 실패', threw && (await h.Outbox.all()).length === 0);
  h = harness({ fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ success: true, stored: true, observationId: 'aaaaaaaa-0000-4000-8000-000000000004', protocol: 2 }) }) });
  r = await h.uploadKeyword('tok', 'k4', payload('k4', 'AAAAAAAA-0000-4000-8000-000000000004'));
  ok('정상 ACK → 보관 없음 · 응답 그대로', r.stored === true && (await h.Outbox.all()).length === 0);
  h = harness({ fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ success: true, stored: true, observationId: 'ffffffff-0000-4000-8000-000000000009' }) }) });
  await h.uploadKeyword('tok', 'k5', payload('k5', 'aaaaaaaa-0000-4000-8000-000000000005'));
  list = await h.Outbox.all();
  ok('🔴 200 인데 관측 ID 가 다르면 사본을 격리 보관(검토 필요)', list.length === 1 && list[0].quarantined === true && list[0].error === 'ACK_MISMATCH');
  h = harness({ fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ success: true }) }) });
  await h.uploadKeyword('tok', 'k6', payload('k6', 'aaaaaaaa-0000-4000-8000-000000000006'));
  ok('구서버(stored 없음)는 격리하지 않는다(무회귀)', (await h.Outbox.all()).length === 0);

  console.log('\n② flush — ACK 때만 삭제 · 재시도 간격 · 격리 · 검토 대기');
  let mode = 'down';
  h = harness({ fetchImpl: async (url, opt) => {
    const body = JSON.parse(opt.body); const id = body.meta.observation.observationId;
    if (mode === 'down') throw new Error('down');
    if (mode === 'reject') return { ok: false, status: 422, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ stored: true, observationId: id }) };
  } });
  for (let i = 1; i <= 3; i++) await h.uploadKeyword('tok', 'kw' + i, payload('kw' + i, `bbbbbbbb-0000-4000-8000-00000000000${i}`));
  ok('3건 보관', (await h.Outbox.all()).length === 3);
  let f = await h.flushOutbox('tok', '시험');
  list = await h.Outbox.all();
  ok('🔴 서버가 계속 죽어 있으면 지우지 않고 시도 1·다음 시각 +30초', f.sent === 0 && f.left === 3 && list.every((it) => it.attempts === 1 && it.nextAttemptAt > Date.now() + 25000 && it.nextAttemptAt <= Date.now() + 31000));
  f = await h.flushOutbox('tok', '');
  ok('대기 시각 전이면 시도하지 않는다', f.sent === 0 && (await h.Outbox.all()).every((it) => it.attempts === 1));
  mode = 'up';
  f = await h.flushOutbox('tok', '', true);
  ok('🔴 force(다시 보내기) → 서버 복구 뒤 전부 전송·삭제', f.sent === 3 && f.left === 0 && (await h.Outbox.all()).length === 0);
  mode = 'down';
  await h.uploadKeyword('tok', 'kw9', payload('kw9', 'cccccccc-0000-4000-8000-000000000001'));
  mode = 'reject';
  f = await h.flushOutbox('tok', '', true);
  list = await h.Outbox.all();
  ok('🔴 422(거절) 응답이면 격리(quarantined) · 남는다', f.sent === 0 && list.length === 1 && list[0].quarantined === true && list[0].error === 'HTTP_422');
  mode = 'up';
  f = await h.flushOutbox('tok', '', true);
  ok('🔴 격리분은 「다시 보내기」로도 안 보낸다(검토 후 비우기만)', f.sent === 0 && (await h.Outbox.all()).length === 1);
  const it = (await h.Outbox.all())[0];
  await h.Outbox.put(Object.assign({}, it, { quarantined: false, attempts: 6, nextAttemptAt: 0 }));
  mode = 'down';
  f = await h.flushOutbox('tok', '');
  ok('🔴 6회 넘긴 것은 자동 재시도 안 함(검토 대기)', f.sent === 0 && (await h.Outbox.all())[0].attempts === 6);
  mode = 'up';
  f = await h.flushOutbox('tok', '', true);
  ok('검토 대기도 force 면 한 번 더 보내고 성공하면 삭제', f.sent === 1 && (await h.Outbox.all()).length === 0);
  await h.Outbox.put({ observationId: 'x', payloadHash: 'h', payload: { keyword: 'q', meta: {} }, bytes: 10, attempts: 2, nextAttemptAt: Date.now() + 5 * 3600e3, quarantined: false });
  f = await h.flushOutbox('', '');
  ok('토큰 없으면 보내지 않고 남긴다(NO_TOKEN)', f.error === 'NO_TOKEN' && f.left === 1);

  console.log('\n③ 요약·상한·배선');
  h = harness({ fetchImpl: async () => { throw new Error('down'); } });
  await h.uploadKeyword('tok', SECRET, payload(SECRET, 'dddddddd-0000-4000-8000-000000000001'));
  const sum = await h.outboxSummary();
  ok('🔴 요약에 건수·바이트·검토·가장 오래된 관측만 — 검색어·본문 없음', sum.schema === 1 && sum.count === 1 && sum.payloadBytes > 0 && sum.reviewRequiredCount === 0 && sum.oldestObservedAt === Math.floor(Date.parse('2026-09-22T01:00:00.000Z') / 1000) && !JSON.stringify(sum).includes(SECRET));
  ok('빈 보관함 요약 = count 0 · bytes 0 · oldest null', JSON.stringify(await h.outboxSummary([])) === JSON.stringify({ schema: 1, count: 0, payloadBytes: 0, reviewRequiredCount: 0, oldestObservedAt: null }));
  for (let i = 2; i <= h.OUTBOX_MAX_ITEMS; i++) await h.Outbox.put({ observationId: 'fill-' + i, payloadHash: '', payload: { keyword: 'x', meta: {} }, bytes: 1, attempts: 0, nextAttemptAt: 0, quarantined: false });
  let full = false;
  try { await h.uploadKeyword('tok', 'over', payload('over', 'eeeeeeee-0000-4000-8000-000000000001')); } catch (e) { full = /OUTBOX_FULL/.test(e.message); }
  ok('🔴 상한(100건)을 넘으면 보관하지 않고 실패(무한 증식 금지)', full && (await h.Outbox.all()).length === h.OUTBOX_MAX_ITEMS);
  const g = harness({ fetchImpl: async () => { throw new Error('d'); } });
  await g.uploadKeyword('tok', 'a', payload('a', 'ffffffff-0000-4000-8000-000000000001'));
  await g.uploadKeyword('tok', 'a', payload('a', 'ffffffff-0000-4000-8000-000000000001'));
  ok('같은 관측 ID 는 두 번 보관하지 않는다(멱등)', (await g.Outbox.all()).length === 1);
  ok('canonicalJson — 키 정렬 · undefined 제거', h.canonicalJson({ b: 1, a: { z: undefined, y: [1, 'x'] } }) === '{"a":{"y":[1,"x"]},"b":1}');
  ok('_ackOk — stored 없으면 거짓 · ID 다르면 거짓 · legacy 는 ID 비교 안 함', h._ackOk({ stored: true, observationId: 'A' }, 'a') && !h._ackOk({ success: true }, 'a') && !h._ackOk({ stored: true, observationId: 'b' }, 'a') && h._ackOk({ stored: true, observationId: 'legacy:zz' }, 'legacy:qq'));
  ok('🔴 회차 시작(runCollection·runOnDemand·runCoordinated) 전에 보관함을 먼저 비운다', (SRC.match(/await flushOutbox\(token, /g) || []).length >= 3);
  ok('🔴 5분 알람·브라우저 시작에서도 재전송', /HEARTBEAT_ALARM\) \{[\s\S]{0,200}flushOutbox\(await getToken\(\), ''\)/.test(SRC) && /onStartup[\s\S]{0,300}flushOutbox\(await getToken\(\), '브라우저 시작'\)/.test(SRC));
  ok('heartbeat 본문에 uploadSummary', /uploadSummary: await outboxSummary\(\),/.test(SRC));
  ok('팝업 — 미전송 줄 · 다시 보내기 · 검토 후 비우기(확인창)', /outboxCount/.test(POPUP) && /cmd: 'flushOutbox'/.test(POPUP) && /confirm\(/.test(POPUP) && /cmd: 'clearOutbox'/.test(POPUP) && /id="outboxFlush"/.test(HTML) && /id="outboxClear"/.test(HTML));
  console.log(`\n${fail ? '❌' : '✅'} 미전송 보관함 회귀 — ${pass} 통과 · ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('시험 자체가 죽음:', e); process.exit(1); });
