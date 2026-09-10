/* 🐢 안전 속도(절반 속도) — 사람이 켜는 스위치 회귀 시험 (2026-09-10)
 *
 * 왜 필요한가: 회선이 막 시끄러웠던 직후(예: 자동입찰을 방금 끈 날)에 평소 속도로
 * 재개하면 캡차를 다시 부를 수 있다. 캡차를 만나면 자동으로 켜지던 「절반 속도」를
 * **사람이 미리 켤 수 있게** 한 것. 24시간 뒤 스스로 풀린다(끄는 것을 잊어도 원복).
 *
 * ⚠️ 구조만 보는 시험은 값이 망가진 것을 못 잡는다 — 그래서 실제 gapFor/isSlow 를 돌린다.
 */
const fs = require('fs');
const path = require('path');
const BG = fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8');
const HTML = fs.readFileSync(path.join(__dirname, '..', 'popup.html'), 'utf8');
const POPUP = fs.readFileSync(path.join(__dirname, '..', 'popup.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c) => { (c ? pass++ : fail++); console.log(`  ${c ? 'PASS' : 'FAIL'}  ${n}`); };

function grab(name) {
  const head = `async function ${name}(`;
  const i = BG.indexOf(head);
  if (i < 0) throw new Error(`${name} 없음`);
  let j = BG.indexOf('{', i), d = 0, k = j;
  for (; k < BG.length; k++) {
    if (BG[k] === '{') d++;
    else if (BG[k] === '}') { d--; if (d === 0) { k++; break; } }
  }
  return BG.slice(i, k);
}

/** 실제 isSlow / gapFor 를 가짜 저장소 위에서 돌린다. */
function speedRunner(slowUntil) {
  const deps = {
    SLOW_KEY: 'slowUntil',
    chrome: { storage: { local: { get: async () => ({ slowUntil }) } } },
  };
  const src = `${grab('isSlow')}\n${grab('gapFor')}`;
  return new Function('deps', `with (deps) { ${src}; return { isSlow, gapFor }; }`)(deps);
}

(async () => {
  console.log('\n[안전 속도 — 실제 gapFor 로 재 본다]');

  // ① 켜져 있으면 키워드 사이 휴식이 2배가 된다 = 시간당 처리량 절반
  {
    const { isSlow, gapFor } = speedRunner(Date.now() + 60 * 60 * 1000);
    ok('① 켜진 상태로 판정된다', (await isSlow()) === true);
    ok('① 휴식이 2배가 된다 (18초 → 36초)', (await gapFor(18000)) === 36000);
  }

  // ② 시각이 지나면 스스로 풀린다 — 끄는 것을 잊어도 원복된다
  {
    const { isSlow, gapFor } = speedRunner(Date.now() - 1000);
    ok('② 시각이 지나면 꺼진 것으로 본다', (await isSlow()) === false);
    ok('② 휴식이 평소대로 돌아간다', (await gapFor(18000)) === 18000);
  }

  // ③ 값이 아예 없어도 안전하게 꺼진 쪽으로 판정한다
  {
    const { isSlow } = speedRunner(undefined);
    ok('③ 저장값이 없으면 꺼진 것으로 본다', (await isSlow()) === false);
  }

  // ④ 창은 24시간이다 (짧게 줄여 놓으면 안전장치가 무의미해진다)
  {
    const m = /SLOW_WINDOW_MS\s*=\s*([^;]+);/.exec(BG);
    const val = m ? Function(`return (${m[1]})`)() : 0;
    ok('④ 절반 속도 창이 24시간이다', val === 24 * 60 * 60 * 1000);
  }

  // ⑤ 팝업에 사람이 누를 스위치가 있고, 양방향으로 동작한다
  ok('⑤ 팝업에 안전 속도 버튼이 있다', /id="slow"/.test(HTML));
  ok('⑤ 켜기·끄기를 한 버튼으로 보낸다', /cmd: on \? 'slowOff' : 'slowOn'/.test(POPUP));
  ok('⑤ 지금 상태를 버튼 글자로 보여 준다', /안전 속도 끄기/.test(POPUP));

  // ⑥ 배경이 두 명령을 실제로 받는다
  ok('⑥ slowOn 을 처리한다', /msg\?\.cmd === 'slowOn'/.test(BG));
  ok('⑥ slowOff 를 처리한다', /msg\?\.cmd === 'slowOff'/.test(BG));
  ok('⑥ slowOn 이 캡차 자동 감속과 같은 열쇠를 쓴다', /\[SLOW_KEY\]: until/.test(BG));

  // ⑦ 캡차 자동 감속(무회귀) — markBlocked 는 여전히 절반 속도를 켠다
  ok('⑦ 캡차를 만나면 여전히 자동으로 켜진다', /_slowUntil = Date\.now\(\) \+ SLOW_WINDOW_MS/.test(BG));

  console.log(fail ? `\n❌ 실패 ${fail}건 / 전체 ${pass + fail}` : '\n안전 속도 시험 전부 통과');
  process.exit(fail ? 1 : 0);
})();
