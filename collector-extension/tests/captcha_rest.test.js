/* 캡차 6시간 쉼이 스스로 취소되던 것 — 회귀 시험 (2026-09-10)
 *
 * 무엇을 막는 시험인가:
 *   회차 도중 캡차를 만나면 markBlocked() 가 6시간 쉼을 건다. 그런데 회차가 끝난 뒤
 *   `if (done > 0) await clearBlocked()` 가 무조건 돌아, **앞부분 몇 개가 성공했다는 이유로
 *   방금 건 쉼을 지워 버렸다.** 그러면 다음 시간대에 차단된 채로 또 두드려 차단이 깊어진다.
 *   ("나는 이 확장 프로그램이 막히면 안 돼" — 대표, 2026-09-10)
 *
 * ⚠️ 소스에서 값을 읽어 쓰는 시험은 그 값이 망가진 것을 못 잡는다(2026-09-09 교훈).
 *    그래서 여기서는 **실제 runCollection 을 꺼내 돌린다** — 호출 순서를 그대로 재현한다.
 */
const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
let pass = 0, fail = 0;
const ok = (name, cond) => { (cond ? pass++ : fail++); console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${name}`); };

/** 이름으로 함수 하나를 중괄호 짝을 세어 통째로 떼어 온다. */
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

/** 껍데기(가짜 의존)를 채워 runCollection 을 실제로 돌린다. */
function makeRunner({ blockAt }) {
  const store = { blockedUntil: 0, marked: 0, cleared: 0 };
  const logs = [];
  const deps = {
    running: false,
    dailyDue: false,
    store,
    CFG: { serverBase: 'http://t', hourBudgetMs: 50 * 60 * 1000,
           maxConsecutiveFail: 5, keywordGapMs: 1, onDemandGapMs: 1 },
    log: async (l) => { logs.push(String(l)); },
    markDailyWaiting: async () => {},
    setState: async () => {},
    getToken: async () => 'tok',
    hourKey: () => '2026-09-10T18',
    cycleDate: () => '2026-09-10',
    workerParams: async () => '',
    jitter: () => 0,
    sleep: async () => {},
    gapFor: async () => 0,
    getBlockedUntil: async () => store.blockedUntil,
    markBlocked: async () => { store.blockedUntil = 9e15; store.marked++; },
    clearBlocked: async () => { store.blockedUntil = 0; store.cleared++; },
    closeAllWorkTabs: async () => {},
    uploadKeyword: async () => {},
    collectKeyword: async (kw) => {
      if (kw === blockAt) throw new Error('BLOCKED:캡차 페이지');
      return { products: [{ rank: 1 }], adSkipped: 0 };
    },
    fetch: async () => ({
      ok: true,
      json: async () => ({ keywords: ['가', '나', '다'], done: 0, total: 3, slot: 3, overdue: 0 }),
    }),
    chrome: { storage: { local: { get: async () => ({}), set: async () => {}, remove: async () => {} } } },
  };
  const src = extract('runCollection');
  // sloppy mode 라 with 가 쓰인다 — deps 의 값을 읽고, 대입도 deps 로 간다.
  const factory = new Function('deps', `with (deps) { ${src}; return runCollection; }`);
  return { run: factory(deps), store, logs, deps };
}

(async () => {
  console.log('\n[캡차 쉼 유지 — 실제 runCollection 을 돌린다]');

  // ① 캡차를 만난 회차: 앞에서 1건 성공한 뒤 캡차 → 쉼이 살아 있어야 한다
  {
    const { run, store, logs } = makeRunner({ blockAt: '나' });
    await run(false);
    ok('① 캡차를 만나면 쉼을 건다', store.marked === 1);
    ok('① 앞 키워드가 성공해도 쉼을 지우지 않는다', store.cleared === 0);
    ok('① 회차가 끝나도 쉼이 살아 있다', store.blockedUntil > Date.now());
    if (store.cleared !== 0) console.log('     로그:', logs.join(' | '));
  }

  // ② 캡차가 없는 평범한 회차: 종전 동작(쉼 해제)이 그대로여야 한다 — 무회귀
  {
    const { run, store } = makeRunner({ blockAt: null });
    store.blockedUntil = 0;
    await run(false);
    ok('② 캡차가 없으면 종전대로 쉼을 해제한다(무회귀)', store.cleared === 1);
    ok('② 그때는 쉼을 걸지 않는다', store.marked === 0);
  }

  // ③ 쉼 중에는 자동 회차가 아예 안 들어간다(종전 동작 유지)
  {
    const { run, store, logs } = makeRunner({ blockAt: null });
    store.blockedUntil = Date.now() + 60 * 60 * 1000;
    await run(false);
    ok('③ 쉼 중이면 자동 회차는 들어가지 않는다', store.cleared === 0 && store.marked === 0);
    ok('③ 그 사실을 로그로 남긴다', logs.some((l) => l.includes('쉼 중')));
  }

  // ④ 사람이 「지금 수집 실행」을 누르면 쉼을 풀고 들어간다(종전 동작 유지)
  {
    const { run, store } = makeRunner({ blockAt: null });
    store.blockedUntil = Date.now() + 60 * 60 * 1000;
    await run(true);
    ok('④ 수동 실행은 쉼을 풀고 들어간다', store.cleared >= 1);
  }

  // ⑤ 온디맨드 경로에도 같은 표식이 걸려 있다(코드가 바뀌어도 규칙이 남게)
  {
    const od = extract('runOnDemand');
    ok('⑤ 온디맨드도 캡차 표식을 세운다', /blockedThisRound = true/.test(od));
    ok('⑤ 온디맨드의 쉼 해제도 표식을 본다', /ok === 1 && !blockedThisRound/.test(od));
  }

  console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : '\n캡차 쉼 시험 전부 통과');
  process.exit(fail ? 1 : 0);
})();
