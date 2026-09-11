/* 작업 탭 정리가 **사람 창을 닫아 버리던 것** — 회귀 시험 (2026-09-11)
 *
 * 실사고: 대표가 「지금 수집 실행」을 눌렀더니 **크롬 창이 통째로 꺼졌다.**
 *   차단이 풀렸는지 확인하려고 사람이 직접 연 네이버쇼핑 탭이 그 창의 유일한 탭이었고,
 *   정리 코드가 그 탭을 지웠다. 크롬은 마지막 탭이 닫히면 창을 닫는다.
 *   ⚠️ 「네이버쇼핑을 직접 열어 확인하세요」라고 안내한 것이 이 충돌을 만들었다.
 *
 * ⚠️ 구조만 보는 시험은 이걸 못 잡는다 — 실제 함수를 가짜 chrome.tabs 위에서 돌린다.
 */
const fs = require('fs');
const path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c) => { (c ? pass++ : fail++); console.log(`  ${c ? 'PASS' : 'FAIL'}  ${n}`); };

function grab(name) {
  const head = `async function ${name}(`;
  const i = SRC.indexOf(head);
  if (i < 0) throw new Error(`${name} 없음`);
  let d = 0, k = SRC.indexOf('{', i);
  for (; k < SRC.length; k++) {
    if (SRC[k] === '{') d++;
    else if (SRC[k] === '}') { d--; if (d === 0) { k++; break; } }
  }
  return SRC.slice(i, k);
}

/** 가짜 크롬 — 창별 탭을 들고 있고, 크롬처럼 「마지막 탭이 닫히면 창도 닫힌다」를 흉내 낸다. */
function fakeChrome(windows) {
  const state = JSON.parse(JSON.stringify(windows));   // { winId: [{id,url,active}] }
  const closedWindows = [];
  return {
    state, closedWindows,
    api: {
      tabs: {
        query: async (q) => {
          const out = [];
          for (const [wid, tabs] of Object.entries(state)) {
            for (const t of tabs) {
              if (q.windowId !== undefined && Number(wid) !== q.windowId) continue;
              if (q.url && !String(t.url).includes('search.shopping.naver.com')) continue;
              out.push({ ...t, windowId: Number(wid) });
            }
          }
          return out;
        },
        remove: async (id) => {
          for (const [wid, tabs] of Object.entries(state)) {
            const i = tabs.findIndex((t) => t.id === id);
            if (i >= 0) {
              tabs.splice(i, 1);
              if (!tabs.length) { closedWindows.push(Number(wid)); delete state[wid]; }
              return;
            }
          }
          throw new Error('no tab');
        },
        update: async (id, props) => {
          for (const tabs of Object.values(state)) {
            const t = tabs.find((x) => x.id === id);
            if (t) { Object.assign(t, props); return; }
          }
        },
      },
    },
  };
}

function runner(fc) {
  const deps = { chrome: fc.api, log: async () => {} };
  const src = grab('removeTabsKeepWindows');
  return new Function('deps', `with (deps) { ${src}; return removeTabsKeepWindows; }`)(deps);
}

(async () => {
  console.log('\n[작업 탭 정리 — 사람 창을 없애지 않는다]');

  // ① 🔴 실사고 재현: 창 하나 + 네이버쇼핑 탭 하나 → 창이 닫히면 안 된다
  {
    const fc = fakeChrome({ 1: [{ id: 11, url: 'https://search.shopping.naver.com/search/all?query=김치', active: true }] });
    const fn = runner(fc);
    await fn(await fc.api.tabs.query({ url: '*://search.shopping.naver.com/*' }), '작업 탭');
    ok('① 창이 닫히지 않는다', fc.closedWindows.length === 0);
    ok('① 그 탭은 빈 페이지로 남는다', (fc.state[1] || [])[0]?.url === 'about:blank');
  }

  // ② 탭이 여러 장인 창에서는 종전대로 닫는다(무회귀)
  {
    const fc = fakeChrome({ 1: [
      { id: 11, url: 'https://search.shopping.naver.com/search/all?query=김치' },
      { id: 12, url: 'https://mail.google.com' },
    ] });
    const fn = runner(fc);
    await fn(await fc.api.tabs.query({ url: '*://search.shopping.naver.com/*' }), '작업 탭');
    ok('② 다른 탭이 있으면 그냥 닫는다', (fc.state[1] || []).length === 1);
    ok('② 남은 것은 사람 탭이다', fc.state[1][0].id === 12);
    ok('② 창은 그대로다', fc.closedWindows.length === 0);
  }

  // ③ 네이버쇼핑 탭만 여러 장인 창 — 하나만 남기고 닫는다(창 보존)
  {
    const fc = fakeChrome({ 1: [
      { id: 11, url: 'https://search.shopping.naver.com/search/all?query=a' },
      { id: 12, url: 'https://search.shopping.naver.com/search/all?query=b' },
      { id: 13, url: 'https://search.shopping.naver.com/search/all?query=c' },
    ] });
    const fn = runner(fc);
    await fn(await fc.api.tabs.query({ url: '*://search.shopping.naver.com/*' }), '작업 탭');
    ok('③ 누적분은 정리하되 한 장은 남는다', (fc.state[1] || []).length === 1);
    ok('③ 창은 살아 있다', fc.closedWindows.length === 0);
  }

  // ④ 창이 둘이면 각 창마다 따로 판단한다
  {
    const fc = fakeChrome({
      1: [{ id: 11, url: 'https://search.shopping.naver.com/search/all?query=a' }],
      2: [{ id: 21, url: 'https://search.shopping.naver.com/search/all?query=b' },
           { id: 22, url: 'https://naver.com' }],
    });
    const fn = runner(fc);
    await fn(await fc.api.tabs.query({ url: '*://search.shopping.naver.com/*' }), '작업 탭');
    ok('④ 단독 창은 지켜진다', (fc.state[1] || []).length === 1);
    ok('④ 여유 있는 창에서는 닫는다', (fc.state[2] || []).length === 1 && fc.state[2][0].id === 22);
    ok('④ 어느 창도 닫히지 않았다', fc.closedWindows.length === 0);
  }

  // ⑤ 사람이 보고 있는 탭을 작업 탭으로 뺏지 않는다(구조 확인 — 재사용 분기)
  const reuse = grab('ensureWorkTab');
  ok('⑤ 활성 탭은 재사용 후보에서 뺀다', /filter\(\(t\) => !t\.active\)/.test(reuse));
  ok('⑤ 쓸 탭이 없으면 새로 만든다고 알린다', /사람이 보고 있어 그대로 두고/.test(reuse));

  console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : '\n작업 탭 안전 시험 전부 통과');
  process.exit(fail ? 1 : 0);
})();
