/* 🧾 진단 파일(diagnostic_export.js) — 회귀 시험 (v1.25.0 · 코덱스 1.22.0 이식 3차 · 2026-09-22)
 *
 * 무엇을 막는가: 진단 파일에 **토큰·검색어·상품·기계 식별자·자유 문장(사유·오류·로그)** 이 실려 나가는 것.
 *   저장소 값 전부에 같은 비밀 표식(SECRET)을 심고, 결과 JSON 문자열에 그 표식이 **한 글자도** 없어야 한다.
 *   그리고 저장소를 고치지 않고(set 금지), 요청을 보내지 않으며(fetch 금지), 3초 안에 끝난다.
 */
const fs = require('fs');
const path = require('path');
const D = require('../diagnostic_export.js');
const HTML = fs.readFileSync(path.join(__dirname, '..', 'popup.html'), 'utf8');
const POP = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');
let pass = 0, fail = 0;
const ok = (name, cond) => { (cond ? pass++ : fail++); console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${name}`); };
const SECRET = 'SENTINEL_PRIVATE_TOKEN_KEYWORD_ID_ERROR_9f3a';
const forbidden = () => { throw new Error('저장소 변경·요청 금지'); };
const NOW = Date.parse('2026-09-22T05:00:00.000Z');

function local() {
  return {
    token: SECRET, workerNo: 2, workerCount: 2, coordinatedEnabled: true, instanceId: SECRET,
    logs: [SECRET], rawSample: { item: { productTitle: SECRET } }, readFail: { body: SECRET },
    state: { running: 'daily', pausedByLocal: false, pausedByScreen: true, blocked: SECRET, blockedUntil: NOW + 3600000,
      slowUntil: NOW + 120000, current: SECRET, error: SECRET, coordState: 'WAIT_BUDGET', coordReason: SECRET,
      coordNextAt: '2026-09-22T05:30:00.000Z', coordJobId: SECRET, lastHeartbeatAt: '2026-09-22T04:55:00.000Z',
      lastHeartbeatOk: true, lastHeartbeatNote: SECRET, startedAt: '2026-09-22T04:00:00.000Z', finishedAt: 'yesterday ' + SECRET,
      target: 12, done: 5, partial: 1, failed: 2, overdue: 3, dayTotal: 400, dayDone: 250, dayFailed: 7, extra: SECRET },
  };
}
const chromeApi = {
  runtime: { getManifest: () => ({ version: '1.25.0' }) },
  storage: { local: { get: async (keys) => { const o = local(); const out = {}; keys.forEach((k) => { if (o[k] !== undefined) out[k] = o[k]; }); return out; },
                      set: forbidden, remove: forbidden, clear: forbidden } },
  alarms: { getAll: (cb) => cb([{ name: 'daily' }, { name: 'heartbeat' }, { name: SECRET }]) },
};
globalThis.fetch = forbidden;

(async () => {
  console.log('① 허용 목록 요약 — 비밀 표식이 한 글자도 안 나간다');
  const s = D.summarizeLocal(local(), NOW);
  const text = JSON.stringify(s);
  ok('🔴 SECRET 이 결과에 없다(토큰·검색어·오류·사유·식별자·로그)', !text.includes(SECRET));
  ok('🔴 SECRET 의 일부(앞 8자)도 없다', !text.includes(SECRET.slice(0, 8)));
  ok('상태·건수는 실린다', s.availability === 'AVAILABLE' && s.coordState === 'WAIT_BUDGET' && s.counts.done === 5 && s.counts.dayTotal === 400);
  ok('값의 「있음/없음」만 — 검색어·오류·사유·차단 사유는 PRESENT', s.currentKeyword === 'PRESENT' && s.lastError === 'PRESENT' && s.coordReason === 'PRESENT' && s.blocked === 'PRESENT');
  ok('토큰은 저장 여부만', s.tokenSaved === 'ON' && !('token' in s));
  ok('쉼 시각은 남은 분만(원문 시각 아님)', s.blockedMinutesLeft === 60 && s.slowMinutesLeft === 2);
  ok('ISO 시각만 통과 · 자유 문자열 시각은 null', s.coordNextAt === '2026-09-22T05:30:00.000Z' && s.finishedAt === null);
  ok('허용 목록 밖 키(extra)는 안 나간다', !('extra' in s) && !text.includes('extra'));
  ok('running 은 daily/ondemand 도 ON', s.running === 'ON' && s.pausedByScreen === 'ON' && s.pausedByLocal === 'OFF');

  console.log('\n② 깨진 입력');
  ok('state 가 객체가 아니면 INVALID_STATE', D.summarizeLocal({ state: 'x' }).availability === 'INVALID_STATE' && D.summarizeLocal(null).availability === 'INVALID_STATE');
  ok('state 없음 → 빈 값으로 AVAILABLE', D.summarizeLocal({}).availability === 'AVAILABLE' && D.summarizeLocal({}).coordState === 'NONE');
  ok('모르는 coordState 는 UNKNOWN(원문 아님)', D.summarizeLocal({ state: { coordState: SECRET } }).coordState === 'UNKNOWN');
  ok('건수가 음수·실수·문자면 null', D.summarizeLocal({ state: { done: -1, failed: 1.5, target: '3' } }).counts.done === null
     && D.summarizeLocal({ state: { done: -1, failed: 1.5, target: '3' } }).counts.failed === null);

  console.log('\n③ collect — 실제 읽기(가짜 chrome)');
  const out = await D.collect({ chromeApi, now: NOW });
  const full = JSON.stringify(out);
  ok('🔴 전체 파일에도 SECRET 없음(알람 이름 포함)', !full.includes(SECRET) && out.alarms.names.join(',') === 'daily,heartbeat,OTHER');
  ok('버전·시각·스냅샷 표식', out.extensionVersion === '1.25.0' && out.exportedAt === '2026-09-22T05:00:00.000Z' && out.schemaVersion === 1);
  ok('저장소 set/clear 를 부르지 않았고 fetch 도 없다(예외 없이 끝남)', out.local.availability === 'AVAILABLE');
  const slow = { ...chromeApi, storage: { local: { get: () => new Promise(() => {}) } } };
  const t0 = Date.now(); const o2 = await D.collect({ chromeApi: slow, now: NOW });
  ok('읽기가 멈추면 3초 안에 READ_TIMEOUT', o2.local.availability === 'READ_TIMEOUT' && Date.now() - t0 < 4000);
  const bad = { ...chromeApi, runtime: { getManifest: () => { throw new Error('x'); } }, alarms: undefined };
  const o3 = await D.collect({ chromeApi: bad, now: NOW });
  ok('manifest·alarms 없어도 죽지 않는다', o3.extensionVersion === null && o3.alarms.availability === 'UNSUPPORTED');

  console.log('\n④ 팝업 배선');
  ok('버튼·상태 줄·스크립트 포함', /id="diagnosticExport"/.test(HTML) && /id="diagnosticStatus"/.test(HTML) && /<script src="diagnostic_export\.js"><\/script>/.test(HTML));
  ok('핸들러가 collect 를 부르고 JSON 으로 내려받는다', /CollectorDiagnosticExport\.collect\(\{ chromeApi: chrome \}\)/.test(POP) && /application\/json/.test(POP) && /link\.download = /.test(POP));
  console.log(`\n${fail ? '❌' : '✅'} 진단 파일 회귀 — ${pass} 통과 · ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('시험 자체가 죽음:', e); process.exit(1); });
