/**
 * 로그 도배 방지 시험 — 표준 node 만 (2026-09-09)
 *
 * ## 왜 이 시험이 있나
 * 캡차로 쉬는 동안 `daily` 알람(1분 주기)이 매분 같은 안내를 한 줄씩 찍었다.
 * 보관은 200줄이라 3.3시간이면 그 전 기록이 통째로 밀린다.
 * 2026-09-09 에 실제로 그 일이 나서 **그날 오전에 무엇이 멈췄는지 증거가 사라졌고
 * 원인을 못 갈랐다.** 이 시험은 「그 아래 기록이 살아남는가」를 지킨다.
 *
 * ## 어떻게 검사하나
 * 확장은 chrome API 에 묶여 있어 통째로 못 부른다. 그래서 background.js 소스에서
 * **log() 함수만 그대로 떼어** 가짜 chrome.storage 위에서 돌린다(복사본이 아니라 진짜 코드다).
 */
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'background.js');
const src = fs.readFileSync(SRC, 'utf8');

let failed = 0;
function check(name, cond, detail) {
  if (cond) console.log(`  PASS  ${name}`);
  else { console.log(`  FAIL  ${name}  ${detail || ''}`); failed++; }
}

/* ── 소스에서 LOG_KEEP 과 log() 만 떼어낸다 ── */
function loadLog() {
  const keepM = /const LOG_KEEP = (\d+);/.exec(src);
  if (!keepM) throw new Error('LOG_KEEP 을 소스에서 못 찾았다');
  const start = src.indexOf('async function log(line) {');
  if (start < 0) throw new Error('log() 를 소스에서 못 찾았다');
  // 중괄호 균형으로 함수 끝을 찾는다
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
  }
  const body = src.slice(start, end);

  const store = { logs: [] };
  let clock = 0;
  const chrome = {
    storage: { local: {
      async get(k) { return { [k]: store[k] } },
      async set(o) { Object.assign(store, o) },
    } },
  };
  // 시각은 부를 때마다 1초씩 흐르게 — 최신 시각으로 갱신되는지 보려는 것
  const Date_ = class extends Date {
    constructor() { super(2026, 8, 9, 14, 0, clock++); }
    toLocaleTimeString() { return `T${String(clock - 1).padStart(3, '0')}` }
  };
  const fn = new Function('chrome', 'Date', `const LOG_KEEP = ${keepM[1]};\n${body}\nreturn log;`);
  return { log: fn(chrome, Date_), store, keep: Number(keepM[1]) };
}

async function main() {
  console.log('로그 도배 방지 시험');

  // ① 서로 다른 줄은 종전대로 쌓인다(무회귀)
  {
    const { log, store } = loadLog();
    await log('첫 줄'); await log('둘째 줄'); await log('셋째 줄');
    check('① 서로 다른 줄은 그대로 쌓인다', store.logs.length === 3, `실제 ${store.logs.length}줄`);
    check('① 최신이 맨 위', /셋째 줄$/.test(store.logs[0]), store.logs[0]);
    check('① 접힘 표시가 안 붙는다', !store.logs.some(l => l.includes('(×')), store.logs.join(' | '));
  }

  // ② 같은 줄이 이어지면 줄이 안 늘고 횟수가 오른다
  {
    const { log, store } = loadLog();
    await log('⏸ 자동입력 방지 쉼 중 — 오후 8:08:21 이후 재개');
    for (let i = 0; i < 9; i++) await log('⏸ 자동입력 방지 쉼 중 — 오후 8:08:21 이후 재개');
    check('② 열 번 찍어도 한 줄', store.logs.length === 1, `실제 ${store.logs.length}줄`);
    check('② 횟수가 10 으로 보인다', store.logs[0].includes('(×10)'), store.logs[0]);
    check('② 시각이 최신으로 갱신된다', store.logs[0].startsWith('[T009]'), store.logs[0]);
  }

  // ③ ⭐ 핵심 — 도배 중에도 그 아래 기록이 살아남는다
  {
    const { log, store, keep } = loadLog();
    await log('🔍 오전에 무슨 일이 있었나 (이 줄이 살아남아야 한다)');
    await log('▶ 자동 수집 시작');
    // 캡차 쉼이 6시간(=360분) 이어진 상황 — 종전 코드면 360줄이 쌓여 위 두 줄이 밀린다
    for (let i = 0; i < 360; i++) await log('⏸ 자동입력 방지 쉼 중 — 오후 8:08:21 이후 재개');
    check('③ 도배가 한 줄로 접힌다', store.logs.length === 3, `실제 ${store.logs.length}줄`);
    check('③ ⭐ 그 전 기록이 살아 있다',
      store.logs.some(l => l.includes('오전에 무슨 일이 있었나')), store.logs.join(' | ').slice(0, 200));
    check('③ 횟수가 360', store.logs[0].includes('(×360)'), store.logs[0]);
    check('③ 보관 상한을 안 넘는다', store.logs.length <= keep);
  }

  // ④ 도배가 끝나고 새 줄이 오면 다시 쌓인다
  {
    const { log, store } = loadLog();
    for (let i = 0; i < 5; i++) await log('같은 줄');
    await log('▶ 자동 수집 시작');
    await log('같은 줄');
    check('④ 새 줄이 오면 다시 쌓인다', store.logs.length === 3, `실제 ${store.logs.length}줄`);
    check('④ 접힌 줄은 그대로 남는다', store.logs[2].includes('(×5)'), store.logs[2]);
    check('④ 떨어진 같은 줄은 새로 쌓인다', !store.logs[0].includes('(×'), store.logs[0]);
  }

  // ⑤ 보관 상한은 종전대로 지켜진다
  {
    const { log, store, keep } = loadLog();
    for (let i = 0; i < keep + 50; i++) await log(`줄 ${i}`);
    check('⑤ 보관 상한 유지', store.logs.length === keep, `실제 ${store.logs.length}줄`);
  }

  // ⑥ 소스 표식 — 알람 주기와 차단 안내가 그대로 있는지(원인 재확인용)
  check('⑥ daily 알람이 1분 주기인 것은 그대로', /alarms\.create\('daily',\s*\{\s*periodInMinutes:\s*1/.test(src));
  check('⑥ 차단 안내 문구를 없애지 않았다', src.includes('자동입력 방지 쉼 중'));
  check('⑥ 보관 상한이 상수로 빠졌다', /const LOG_KEEP = \d+;/.test(src));
  // ⚠️ 접기만으로는 부족하다 — 보관 줄 수를 줄이면 도배가 없어도 기록이 밀린다.
  //    (사보타주 3 에서 200→20 으로 줄였더니 위 시험들이 전부 통과해 버렸다.
  //     시험이 소스에서 LOG_KEEP 을 읽어 스스로 맞춰 주기 때문이다 — 그 구멍을 막는다.)
  {
    const keep = Number(/const LOG_KEEP = (\d+);/.exec(src)[1]);
    check(`⑥ 보관 줄 수가 200 밑으로 안 내려간다 (지금 ${keep})`, keep >= 200,
      '줄이면 도배를 접어도 원인 추적이 다시 불가능해진다');
  }

  console.log();
  if (failed) { console.log(`❌ 실패 ${failed}건`); process.exit(1); }
  console.log('로그 도배 방지 시험 전부 통과');
}
main();
