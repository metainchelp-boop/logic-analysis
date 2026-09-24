/* 🧭 서버 중앙 배정(runCoordinated) — 회귀 시험 (v1.24.0 · 코덱스 1.22.0 이식 2차 · 2026-09-22)
 *
 * 무엇을 막는 시험인가:
 *   ① 서버 스위치가 꺼져 있으면(INACTIVE · 구서버 404) **false** 를 돌려줘 호출자가 종전 경로(runCollection)로 간다 —
 *      코덱스 원안은 여기서 멈췄다(9/21 검토 B2). false 가 true 로 바뀌면 수집이 조용히 0건이 된다.
 *   ② 임대(LEASED)를 받으면 그 키워드를 모아 **meta.job 에 임대 계약을 실어** 올린다(서버가 완료 처리하는 유일한 열쇠).
 *   ③ 막히면 이 기계만 쉰다 — markBlocked + PAUSED_BLOCK 보고 + 임대 반납. 전역 정지 호출은 없다.
 *   ④ WAIT_BUDGET·IDLE 은 조용히 쉬고(true) 다음 회차를 기다린다 · 실패한 임대는 반납(WAIT_BUDGET) · 일시정지면 서버를 안 부른다.
 *
 * ⚠️ 문구가 아니라 **실제 runCoordinated 를 꺼내 가짜 coordRequest/collectKeyword 로 돌린다.**
 */
const fs = require('fs');
const path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
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

/** runCoordinated 를 실제로 돌린다.
 *  server = { register, claims:[…], … } — coordRequest(endpoint, body) 가 endpoint 별로 응답/예외를 돌려준다. */
async function run({ server, collect, paused = false, blockedUntil = 0, token = 'tok', manual = false }) {
  const calls = [];              // coordRequest 호출 기록
  const uploads = [];            // uploadKeyword 호출 기록
  const states = [];
  const logs = [];
  const flags = { markBlocked: 0, clearBlocked: 0 };
  let claimN = 0;
  const deps = {
    running: false,
    _targets: {},
    CFG: { hourBudgetMs: 50 * 60 * 1000, maxConsecutiveFail: 3, workerNo: 1, workerCount: 1 },
    chrome: { runtime: { getManifest: () => ({ version: '1.24.0' }) } },
    isLocalPaused: async () => paused,
    loadRemote: async () => {},          // ⚙ v1.27.0 서버 설정 — 이 시험에선 기본값 그대로
    serverPaused: () => false,
    getBlockedUntil: async () => blockedUntil,
    getToken: async () => token,
    setState: async (p) => { states.push(p); },
    log: async (m) => { logs.push(m); },
    hourKey: () => '2026-09-22T10',
    coordWho: async () => ({ protocol: 2, workerId: 'W1', sessionId: 'S1', workerNo: 1, workerCount: 1 }),
    coordRequest: async (endpoint, body) => {
      calls.push({ endpoint, body });
      if (endpoint === 'register') { if (server.register instanceof Error) throw server.register; return server.register; }
      if (endpoint === 'claim') { const r = server.claims[Math.min(claimN, server.claims.length - 1)]; claimN++; if (r instanceof Error) throw r; return r; }
      if (endpoint === 'report') return { ok: true };
      if (endpoint === 'release') return { ok: true };
      throw new Error('unknown ' + endpoint);
    },
    coordReport: async (state, reason) => { calls.push({ endpoint: 'report', body: { state, reason } }); },
    collectKeyword: async (kw) => collect(kw),
    uploadKeyword: async (tok, kw, payload, job) => { uploads.push({ tok, kw, payload, job }); if (payload.__uploadFail) throw new Error(payload.__uploadFail); },
    markBlocked: async () => { flags.markBlocked++; },
    clearBlocked: async () => { flags.clearBlocked++; },
    sleep: async () => {},
    jitter: () => 0,
    markDailyWaiting: async () => {},
  };
  const fn = new Function(...Object.keys(deps), `${extract('runCoordinated')}\nreturn runCoordinated;`)(...Object.values(deps));
  const r = await fn(manual);
  return { r, calls, uploads, states, logs, flags };
}

const REG_ON = { protocol: 2, state: 'READY', enabled: true, policy: { worker_hourly: 10 } };
const LEASE = (kw, extra = {}) => ({ protocol: 2, state: 'LEASED', job: { jobId: 'j-' + kw, leaseId: 'l-' + kw, keyword: kw, workerId: 'W1', sessionId: 'S1', targetIds: ['111'], requestedDepth: 300, ...extra } });
const okPayload = (kw, n = 40) => ({ products: Array.from({ length: n }, (_, i) => ({ id: String(i + 1), rank: i + 1 })), total: 999, observation: { status: 'complete', stopReason: 'DEPTH_REACHED' } });

(async () => {
  console.log('① 서버 스위치 꺼짐 → 종전 경로로 폴백(false)');
  let t = await run({ server: { register: { ...REG_ON, enabled: false }, claims: [] }, collect: okPayload });
  ok('🔴 register.enabled=false → false(호출자가 runCollection 으로)', t.r === false);
  ok('claim 을 부르지 않는다', !t.calls.some((c) => c.endpoint === 'claim'));
  ok('상태에 INACTIVE + 사유', t.states.some((s) => s.coordState === 'INACTIVE' && /종전 경로/.test(s.coordReason || '')));
  t = await run({ server: { register: Object.assign(new Error('서버 HTTP 404'), { code: 'NO_V2', status: 404 }), claims: [] }, collect: okPayload });
  ok('🔴 구서버(404 · NO_V2) → false(종전 경로)', t.r === false && t.states.some((s) => s.coordState === 'NO_V2'));
  t = await run({ server: { register: REG_ON, claims: [{ protocol: 2, state: 'INACTIVE', job: null }] }, collect: okPayload });
  ok('🔴 claim 이 INACTIVE 여도 false(종전 경로)', t.r === false);
  t = await run({ server: { register: Object.assign(new Error('서버 HTTP 500'), { code: 'HTTP_500', status: 500 }), claims: [] }, collect: okPayload });
  ok('서버 장애(500)는 true — 이번 분만 쉬고 종전 경로로 **가지 않는다**(두 경로가 동시에 돌면 안 된다)', t.r === true && t.states.some((s) => s.coordState === 'SERVER_UNREACHABLE'));

  console.log('\n② 임대 → 수집 → meta.job 실어 올리기');
  t = await run({ server: { register: REG_ON, claims: [LEASE('가리비'), { protocol: 2, state: 'IDLE', job: null }] }, collect: okPayload });
  ok('🔴 임대받은 키워드를 올리고 job 계약을 그대로 넘긴다', t.uploads.length === 1 && t.uploads[0].kw === '가리비' && t.uploads[0].job && t.uploads[0].job.leaseId === 'l-가리비');
  ok('토큰을 그대로 쓴다', t.uploads[0].tok === 'tok');
  ok('IDLE 이면 회차를 끝내고 true(종전 경로 안 감)', t.r === true && t.logs.some((m) => /오늘 몫이 없습니다/.test(m)));
  ok('성공 1 → clearBlocked · 종료 로그에 성공 1', t.flags.clearBlocked === 1 && t.logs.some((m) => /성공 1 · 부분 0 · 실패 0/.test(m)));
  ok('진행 상태에 current 키워드·jobId', t.states.some((s) => s.current === '가리비' && s.coordJobId === 'j-가리비'));
  const seq = t.calls.map((c) => c.endpoint).join('>');
  ok('호출 순서 register > claim > claim(IDLE)', seq === 'register>claim>claim');
  t = await run({ server: { register: REG_ON, claims: [LEASE('낙지'), { protocol: 2, state: 'IDLE', job: null }] },
                  collect: (kw) => ({ ...okPayload(kw, 12), observation: { status: 'partial', stopReason: 'STALE_PAGE' } }) });
  ok('부분 수집(partial)도 올리고 부분으로 센다', t.uploads.length === 1 && t.logs.some((m) => /부분 수집 12개 · STALE_PAGE/.test(m)) && t.logs.some((m) => /성공 0 · 부분 1 · 실패 0/.test(m)));

  console.log('\n③ 막힘 — 이 기계만 쉰다');
  t = await run({ server: { register: REG_ON, claims: [LEASE('오징어'), LEASE('문어')] }, collect: () => ({ products: [], total: 0, blocked: 'BLOCKED:보안 확인 퍼즐' }) });
  ok('🔴 markBlocked 1회(이 기계 6시간)', t.flags.markBlocked === 1);
  const rep = t.calls.find((c) => c.endpoint === 'report');
  ok('🔴 서버에 PAUSED_BLOCK 보고', !!rep && rep.body.state === 'PAUSED_BLOCK');
  const rel = t.calls.find((c) => c.endpoint === 'release');
  ok('🔴 임대 반납(release · PAUSED_BLOCK · job 계약 동봉)', !!rel && rel.body.state === 'PAUSED_BLOCK' && rel.body.job && rel.body.job.leaseId === 'l-오징어');
  ok('막힌 뒤 두 번째 임대를 받지 않는다(회차 중단)', t.calls.filter((c) => c.endpoint === 'claim').length === 1 && t.uploads.length === 0);
  ok('전역 정지(control) 호출 없음', !t.calls.some((c) => c.endpoint === 'control'));
  ok('반환은 true(종전 경로로 안 감)', t.r === true);
  t = await run({ server: { register: REG_ON, claims: [LEASE('가자미'), { protocol: 2, state: 'IDLE', job: null }] },
                  collect: (kw) => ({ ...okPayload(kw, 20), blocked: 'BLOCKED:2페이지 418' }) });
  ok('막히기 전까지 담은 것은 **올린 뒤** 쉰다(부분 보존)', t.uploads.length === 1 && t.flags.markBlocked === 1 && t.uploads[0].job.leaseId === 'l-가자미');

  console.log('\n④ 예산·유휴·실패·일시정지');
  t = await run({ server: { register: REG_ON, claims: [{ protocol: 2, state: 'WAIT_BUDGET', nextAllowedAt: 1_800_000_000, job: null }] }, collect: okPayload });
  ok('WAIT_BUDGET → 쉼(true) + 다음 시각 기록', t.r === true && t.states.some((s) => s.coordState === 'WAIT_BUDGET' && /2027|2026|20\d\d/.test(s.coordNextAt || '')) && t.uploads.length === 0);
  t = await run({ server: { register: REG_ON, claims: [{ protocol: 2, state: 'PAUSED_OPERATOR', reason: '화면 스위치 꺼짐', job: null }] }, collect: okPayload });
  ok('PAUSED_OPERATOR → 쉼(true) · 사유 기록', t.r === true && t.states.some((s) => s.coordState === 'PAUSED_OPERATOR' && s.coordReason === '화면 스위치 꺼짐'));
  t = await run({ server: { register: REG_ON, claims: [LEASE('전복'), { protocol: 2, state: 'IDLE', job: null }] }, collect: () => ({ products: [], total: 0, observation: { status: 'failed', error: 'NO_PAGER' } }) });
  ok('🔴 상품 0건 실패 → 임대 반납(WAIT_BUDGET) · 실패 1', t.calls.some((c) => c.endpoint === 'release' && c.body.state === 'WAIT_BUDGET' && c.body.job.leaseId === 'l-전복') && t.logs.some((m) => /실패 1$/.test(m)));
  t = await run({ server: { register: REG_ON, claims: [LEASE('굴'), { protocol: 2, state: 'IDLE', job: null }] }, collect: (kw) => ({ ...okPayload(kw), __uploadFail: '업로드 취소 — 직전 회차와 동일한 결과' }) });
  ok('업로드 실패도 임대 반납(서버가 다시 배정하게)', t.calls.some((c) => c.endpoint === 'release' && c.body.job.leaseId === 'l-굴'));
  t = await run({ server: { register: REG_ON, claims: [LEASE('가리비')] }, collect: okPayload, paused: true });
  ok('🔴 일시정지면 서버를 부르지 않는다(true)', t.r === true && t.calls.length === 0 && t.states.some((s) => s.pausedByLocal === true));
  t = await run({ server: { register: REG_ON, claims: [LEASE('가리비')] }, collect: okPayload, blockedUntil: Date.now() + 3600e3 });
  ok('캡차 쉼 중(자동)이면 서버를 부르지 않는다', t.r === true && t.calls.length === 0);
  t = await run({ server: { register: REG_ON, claims: [LEASE('가리비'), { protocol: 2, state: 'IDLE', job: null }] }, collect: okPayload, blockedUntil: Date.now() + 3600e3, manual: true });
  ok('사람이 누른 실행은 캡차 쉼을 건너뛴다(종전 runCollection 과 같은 규칙)', t.uploads.length === 1);
  t = await run({ server: { register: REG_ON, claims: [LEASE('가리비')] }, collect: okPayload, token: '' });
  ok('토큰 없으면 서버를 부르지 않고 안내(true)', t.r === true && t.calls.length === 0 && t.logs.some((m) => /토큰이 없습니다/.test(m)));

  console.log(`\n${fail ? '❌' : '✅'} 중앙 배정 회귀 — ${pass} 통과 · ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('시험 자체가 죽음:', e); process.exit(1); });
