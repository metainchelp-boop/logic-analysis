/* 📡 살아있음 신호(heartbeat) — 회귀 시험 (v1.21.0 · 2026-09-22)
 *
 * 무엇을 막는 시험인가:
 *   2번 설정 노트북이 요청 0건으로 「조용히」 사라졌을 때 서버가 원인을 가를 수 없었다.
 *   이 신호는 **멈춰 있어도** 가야 하고(그 사실을 알리는 게 목적), 실패해도 수집을 넘어뜨리면 안 된다.
 *   소스 문구만 찾으면 주석에 걸리므로 **실제 sendHeartbeat 를 꺼내 가짜 의존으로 돌린다.**
 */
const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
const POPUP = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');
const HTML = fs.readFileSync(path.join(__dirname, '..', 'popup.html'), 'utf8');
const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'manifest.json'), 'utf8'));
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

/** sendHeartbeat 를 실제로 돌린다 — 저장소·fetch 를 가짜로. */
async function run({ token = 'tok', paused = false, blockedUntil = 0, fetchImpl, state = {} }) {
  const calls = [];
  const setStates = [];
  const store = { token, state, workerNo: 2, workerCount: 2, instanceId: 'abc-123' };
  const chrome = {
    storage: { local: { get: async (k) => {
      const keys = Array.isArray(k) ? k : [k];
      const o = {}; keys.forEach((x) => { if (store[x] !== undefined) o[x] = store[x]; }); return o;
    }, set: async (o) => Object.assign(store, o) } },
    runtime: { getManifest: () => ({ version: '9.9.9' }) },
    alarms: { getAll: async () => [{ name: 'daily', periodInMinutes: 1 }, { name: 'heartbeat', periodInMinutes: 5 }] },
  };
  const deps = {
    chrome,
    navigator: { userAgent: 'Mozilla/5.0 Chrome/140.0.1 Safari' },
    CFG: { serverBase: 'http://t', workerNo: 1, workerCount: 1 },
    running: false,
    getToken: async () => store.token,
    setState: async (p) => { setStates.push(p); },
    isLocalPaused: async () => paused,
    loadRemote: async () => {},                                   // ⚙ v1.27.0
    effectiveWorker: async () => ({ workerNo: store.workerNo, workerCount: store.workerCount }),
    serverPaused: () => false,
    receiveSettings: async (st, via) => { store.received = { st, via }; },
    getBlockedUntil: async () => blockedUntil,
    instanceId: async () => store.instanceId,
    alarmNames: async () => ['daily:1', 'heartbeat:5'],
    outboxSummary: async () => ({ schema: 1, count: 2, payloadBytes: 3000, reviewRequiredCount: 1, oldestObservedAt: 1790000000 }),   // 4차 — 미전송 요약 의존
    fetch: fetchImpl || (async (url, opt) => { calls.push({ url, opt }); return { ok: true, status: 200 }; }),
  };
  const fn = new Function(...Object.keys(deps), `${extract('sendHeartbeat')}\nreturn sendHeartbeat;`)(...Object.values(deps));
  const r = await fn('test');
  return { r, calls, setStates, store };
}

(async () => {
  console.log('📡 살아있음 신호 시험');
  /* ① 멈춰 있어도 보낸다 */
  let t = await run({ paused: true, blockedUntil: Date.now() + 3600e3 });
  ok('🔴 일시정지 + 캡차 쉼 상태에서도 서버에 보낸다(요청 1건)', t.calls.length === 1 && t.r === true);
  const body = JSON.parse(t.calls[0].opt.body);
  ok('🔴 보낸 값에 pausedByLocal=true · blockedUntil 이 그대로 실린다', body.pausedByLocal === true && body.blockedUntil > Date.now());
  ok('📤 4차 — 미전송 보관함 요약(uploadSummary)이 함께 실린다', body.uploadSummary && body.uploadSummary.count === 2 && body.uploadSummary.reviewRequiredCount === 1);
  ok('🔴 기계 번호 2/2 · 버전 · instanceId · 알람 목록이 실린다',
     body.workerNo === 2 && body.workerCount === 2 && body.extVersion === '9.9.9' && body.instanceId === 'abc-123' && Array.isArray(body.alarms) && body.alarms.length === 2);
  ok('경로·헤더 — /api/collector/heartbeat · X-Collector-Token', /\/api\/collector\/heartbeat$/.test(t.calls[0].url) && t.calls[0].opt.headers['X-Collector-Token'] === 'tok');
  ok('IP·개인정보 필드가 없다', !('ip' in body) && !('keyword' in body) && !('email' in body));
  ok('성공을 상태에 남긴다(lastHeartbeatOk=true)', t.setStates.some((p) => p.lastHeartbeatOk === true && p.lastHeartbeatAt));

  /* ② 실패해도 예외를 내지 않는다 */
  t = await run({ fetchImpl: async () => { throw new Error('네트워크 끊김'); } });
  ok('🔴 fetch 가 던져도 예외가 밖으로 안 나가고 false 를 돌려준다', t.r === false);
  ok('실패 사유를 상태에 남긴다', t.setStates.some((p) => p.lastHeartbeatOk === false && /네트워크/.test(p.lastHeartbeatNote || '')));
  t = await run({ fetchImpl: async () => ({ ok: false, status: 401 }) });
  ok('HTTP 401 이면 false + 「HTTP 401」 메모', t.r === false && t.setStates.some((p) => p.lastHeartbeatNote === 'HTTP 401'));
  t = await run({ token: '' });
  ok('토큰 없으면 보내지 않고 「토큰 없음」 메모', t.calls.length === 0 && t.setStates.some((p) => p.lastHeartbeatNote === '토큰 없음'));

  /* ③ 배선 — 알람·시작·버튼 */
  ok('🔴 armAlarms 가 heartbeat 알람을 5분 주기로 건다',
     /chrome\.alarms\.create\(HEARTBEAT_ALARM, \{ periodInMinutes: \(typeof RT === 'object' && RT \? RT\.heartbeatMin : HEARTBEAT_PERIOD_MIN\)/.test(SRC) && /const HEARTBEAT_PERIOD_MIN = 5;/.test(SRC));
  ok('🔴 onAlarm 이 heartbeat 를 받아 ensureAlarms → sendHeartbeat', /if \(a\.name === HEARTBEAT_ALARM\) \{\s*await ensureAlarms\([^)]*\);[\s\S]{0,200}?sendHeartbeat\('alarm'\); return;\s*\}/.test(SRC));
  ok('설치·브라우저 시작·회차 시작에서 신호를 보낸다', /sendHeartbeat\('installed'\)/.test(SRC) && /sendHeartbeat\('startup'\)/.test(SRC) && /sendHeartbeat\(manual \? 'run-manual' : 'run'\)/.test(SRC));
  ok('워커 깨어날 때 heartbeat 알람이 빠졌으면 다시 건다', /const h = await chrome\.alarms\.get\(HEARTBEAT_ALARM\);[\s\S]{0,120}\|\| !h\)/.test(SRC));
  ok('🔴 sendHeartbeat 는 isLocalPaused/getBlockedUntil 로 **거르지 않는다**(값을 읽기만)',
     !/if \(await isLocalPaused\(\)\)[^\n]*\n[^\n]*sendHeartbeat/.test(extract('sendHeartbeat')) && /pausedByLocal: await isLocalPaused\(\)/.test(extract('sendHeartbeat')));
  ok('팝업 버튼 → cmd heartbeat → ensureAlarms + sendHeartbeat', /msg\?\.cmd === 'heartbeat'/.test(SRC) && /cmd: 'heartbeat'/.test(POPUP) && /id="heartbeat"/.test(HTML));
  ok('팝업이 서버 보고 줄과 알람 점검 줄을 그린다', /lastHeartbeatAt/.test(POPUP) && /chrome\.alarms\.getAll\(\)/.test(POPUP) && /알람 빠짐/.test(POPUP));
  ok('🔴 manifest 버전 1.21.0 이상', (() => { const [a, b] = MANIFEST.version.split('.').map(Number); return a > 1 || (a === 1 && b >= 21); })());

  console.log(`\n${fail ? '🔴' : '✅'} 통과 ${pass} · 실패 ${fail}`);
  process.exit(fail ? 1 : 0);
})();
