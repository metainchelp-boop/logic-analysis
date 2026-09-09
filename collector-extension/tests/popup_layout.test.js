/**
 * 팝업 높이 시험 — 표준 node 만 (2026-09-09)
 *
 * ## 왜 이 시험이 있나
 * 크롬 확장 팝업은 **높이 상한이 600px** 이다(브라우저가 정한 값 — CSS 로 못 늘린다).
 * 넘으면 팝업 전체에 세로 스크롤이 생겨 아래 칸(진단용 접이식 3종)이 잘린다.
 * 2026-09-09 대표 지적 — 실제로 잘려 있었다.
 *
 * ## 어떻게 검사하나
 * 브라우저 없이 픽셀을 정확히 잴 수는 없다. 그래서 **높이를 결정하는 구조 규칙**을 지킨다:
 *   ⑴ 한 번 설정하고 안 건드리는 것(토큰·여러 대)은 접혀 있어야 한다
 *   ⑵ 로그창 높이가 커지지 않아야 한다
 *   ⑶ 자동 펼침이 3초마다 반복되면 안 된다(사용자가 접은 것을 다시 여는 꼴)
 * 이 셋이 깨지면 스크롤이 다시 생긴다.
 */
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'popup.html'), 'utf8');
const js = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');

let failed = 0;
const check = (n, c, d) => c ? console.log(`  PASS  ${n}`)
  : (console.log(`  FAIL  ${n}  ${d || ''}`), failed++);

console.log('팝업 높이 시험');

/* ── ⑴ 설정이 접혀 있는가 ── */
const setup = /<details[^>]*id="setup"[^>]*>([\s\S]*?)<\/details>/.exec(html);
check('① ⚙ 설정 칸이 details 로 접혀 있다', !!setup);
check('① 기본이 닫힘이다(open 이 안 박혀 있다)',
  setup && !/<details[^>]*id="setup"[^>]*\sopen[\s>]/.test(setup[0]),
  'open 을 박으면 늘 펼쳐져 스크롤이 생긴다');
check('① 토큰칸이 그 안에 있다', setup && setup[1].includes('id="token"'));
check('① 여러 대 설정이 그 안에 있다',
  setup && setup[1].includes('id="workerCount"') && setup[1].includes('id="workerNo"'));
check('① 저장·토큰보기 버튼도 함께 들어갔다',
  setup && setup[1].includes('id="save"') && setup[1].includes('id="peek"'));

/* ── 매일 보는 것은 접히면 안 된다 ── */
const outside = html.replace(setup ? setup[0] : '', '');
for (const [name, id] of [['상태', 'stat'], ['로그창', 'logs'],
                          ['지금 수집 실행', 'run'], ['새로고침', 'refresh']]) {
  check(`② ${name} 은 접히지 않고 그대로 보인다`, outside.includes(`id="${id}"`),
    '매일 보는 것을 접으면 팝업의 쓸모가 준다');
}

/* ── ⑵ 로그창 높이 ── */
const lh = /#logs\{[^}]*height:(\d+)px/.exec(html);
check('③ 로그창 높이를 읽을 수 있다', !!lh);
check(`③ 로그창이 130px 를 안 넘는다 (지금 ${lh ? lh[1] : '?'}px)`,
  lh && Number(lh[1]) <= 130, '키우면 팝업이 600px 를 넘어 스크롤이 생긴다');
check('③ 로그창은 자체 스크롤을 유지한다(200줄을 담아야 한다)',
  /#logs\{[^}]*overflow:auto/.test(html));

/* ── ⑶ 자동 펼침이 한 번만 도는가 ── */
check('④ 자동 펼침에 한 번만 도는 잠금이 있다', /let setupChecked = false/.test(js));
check('④ 그 잠금을 실제로 건다', /setupChecked = true/.test(js));
check('④ 토큰이 없거나 여러 대면 펼친다',
  /!token \|\| Number\(workerCount\) > 1 \|\| Number\(workerNo\) > 1/.test(js));
check('④ render 는 3초 주기 그대로(무회귀)', /setInterval\(render, 3000\)/.test(js));

/* ── 대략의 높이 어림 — 정확한 값이 아니라 「눈에 띄게 커졌나」를 본다 ── */
{
  // 펼쳐진 채로 남은 블록 수를 세어 급격한 증가를 잡는다
  const details = (html.match(/<details/g) || []).length;
  check(`⑤ 접이식 칸이 4개다(설정 1 + 진단 3) — 지금 ${details}개`, details === 4,
    '펼쳐진 블록이 늘면 높이가 늘어난다');
  check('⑤ 본문 좌우 여백이 12px 로 조여 있다', /body\{[^}]*padding:12px/.test(html));
}

console.log();
if (failed) { console.log(`❌ 실패 ${failed}건`); process.exit(1); }
console.log('팝업 높이 시험 전부 통과');
