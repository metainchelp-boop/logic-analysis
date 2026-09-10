// 팝업 — 토큰 저장 / 수동 실행 / 진행 상황 확인
const $ = (id) => document.getElementById(id);

async function render() {
  const { token = '', state = {}, logs = [], rawSample = null, rawSampleAd = null,
          lastAdStat = null, readFail = null, workerNo = 1, workerCount = 1 } =
    await chrome.storage.local.get(['token', 'state', 'logs', 'rawSample', 'rawSampleAd',
                                    'lastAdStat', 'readFail', 'workerNo', 'workerCount']);
  // ⚠️ 입력 중에는 덮어쓰지 않는다 — 3초마다 도는 render 가 타이핑을 지워 버린다.
  //    특히 토큰 칸은 새로 설치한 기계에서 저장값이 빈 문자열이라, 가드가 없으면
  //    한 글자 칠 때마다 지워져 사실상 입력이 불가능하다(2026-08-28 실사용 신고).
  //    붙여넣기로 3초 안에 끝내면 우연히 되던 것이라 여태 안 드러났다.
  if (document.activeElement !== $('token')) $('token').value = token;
  if (document.activeElement !== $('workerNo')) $('workerNo').value = workerNo;
  if (document.activeElement !== $('workerCount')) $('workerCount').value = workerCount;
  try {
    const v = chrome.runtime.getManifest().version;
    const ve = $('ver');
    if (ve) ve.textContent = `v${v} · 광고 제외 오가닉 순위`;
  } catch (e) { /* 무시 */ }
  // 캡차에 걸려 쉬는 중이면 그게 가장 중요한 정보다 — 맨 위에 눈에 띄게.
  const bu = Number(state.blockedUntil || 0);
  const blockedNow = state.blocked && bu > Date.now();
  // 캡차를 만난 뒤 하루 동안은 절반 속도로 돈다 — 그 사실이 화면에 보여야
  // 「왜 느리지?」를 고장으로 오해하지 않는다(2026-08-28).
  const slowUntil = Number(state.slowUntil || 0);
  const slowNow = slowUntil > Date.now();
  const running = blockedNow
    ? '<span class="b bad">자동입력 방지(캡차)로 쉬는 중</span>'
    : (state.running ? '<span class="b ok">수집 중</span>' : '대기');
  // ⭐ 오늘 전체 진척 (2026-08-28 대표 요청 「총 개수 / 추적 완료 / 추적 실패」).
  //    ⚠️ 아래 '이번 시간대' 숫자와 다른 축이다 — 그건 매시간 0 으로 돌아간다.
  //       여기 값은 서버가 알려 준 '오늘 재야 할 전체'와 '오늘까지 끝낸 수'다.
  const dTot = Number(state.dayTotal || 0);
  const dDone = Number(state.dayDone || 0);
  const dFail = Number(state.dayFailed || 0);
  const pct = dTot ? Math.min(100, Math.round((dDone / dTot) * 100)) : 0;
  const dayBlock = dTot
    ? `<div class="sec"><b>오늘 진척</b> ` +
      `<span class="b ok">${dDone.toLocaleString()}</span> / ${dTot.toLocaleString()}개 ` +
      `<span class="b">${pct}%</span>` +
      (dFail ? ` · 실패 <span class="b bad">${dFail.toLocaleString()}</span>` : '') +
      `<div class="bar"><i style="width:${pct}%"></i></div>` +
      `<span class="dim">남은 것 ${Math.max(0, dTot - dDone).toLocaleString()}개</span></div>`
    : '<div class="sec dim">오늘 진척 — 수집을 한 번 돌리면 표시됩니다</div>';

  $('stat').innerHTML =
    `상태: ${running}<br>` +
    (blockedNow
      ? `<span class="b bad">▸ ${new Date(bu).toLocaleTimeString('ko-KR')} 이후 자동 재개</span><br>` +
        '<span style="font-size:11px">네이버쇼핑을 직접 열어 캡차를 한 번 풀고 「지금 수집 실행」을 누르면 바로 재개됩니다.</span><br>'
      : '') +
    (slowNow && !blockedNow
      ? '<span class="b" style="color:#b45309">▸ 안전 속도로 돌리는 중</span>' +
        `<span style="font-size:11px"> — ${new Date(slowUntil).toLocaleString('ko-KR')}까지 (캡차를 만나서 절반 속도)</span><br>`
      : '') +
    dayBlock +
    `<div class="sec">이번 시간대 · 대상 <span class="b">${state.target ?? '-'}</span>개 · ` +
    `완료 <span class="b ok">${state.done ?? 0}</span> · ` +
    `실패 <span class="b bad">${state.failed ?? 0}</span>` +
    (Number(state.overdue || 0) ? ` · 밀린 것 ${Number(state.overdue).toLocaleString()}개` : '') +
    '</div>' +
    (state.current ? `진행 중: ${state.current}<br>` : '') +
    (state.finishedAt ? `마지막 완료: ${new Date(state.finishedAt).toLocaleString('ko-KR')}` : '아직 완료 기록 없음');
  $('logs').textContent = logs.join('\n');
  const rawEl = document.getElementById('raw');
  if (rawEl) rawEl.textContent = rawSample ? `[${rawSample.keyword}] ${rawSample.at}\n` + JSON.stringify(rawSample.item, null, 1) : '아직 없음 — 수집 1회 실행 후 표시';
  // 광고 제외가 실제로 돌고 있는지 + 광고 상품 원본(판별 규칙을 넓힐 때 근거로 쓴다)
  const adEl = document.getElementById('rawAd');
  if (adEl) {
    const head = lastAdStat
      ? `직전 키워드 [${lastAdStat.keyword}] ${lastAdStat.at}\n` +
        `  오가닉 ${lastAdStat.kept}개 기록 · 광고 ${lastAdStat.ads}개 순위 제외\n` +
        `  (광고 표식은 있는데 링크로 못 거른 상품 ${lastAdStat.hint}개)\n` +
        (lastAdStat.fp && Object.keys(lastAdStat.fp).length
          ? `  광고 필드 지문(원본 ${lastAdStat.raw}개 · L=첫링크adcr C=세필드 M=상품주소 I=adId T=adType A=adcr호스트 R=cr호스트):\n` +
            Object.entries(lastAdStat.fp).map(([k, v]) => `    ${v}개  ${k}`).join('\n') + '\n\n'
          : '\n')
      : '아직 없음 — 수집 1회 실행 후 표시\n\n';
    adEl.textContent = head + (rawSampleAd
      ? `[광고 상품 원본] ${rawSampleAd.keyword} ${rawSampleAd.at}\n` + JSON.stringify(rawSampleAd.item, null, 1)
      : '(광고 상품 원본 아직 없음)');
  }
  // 판독 실패 진단 — '차단'과 '못 읽음'을 가르기 위한 근거(제목·주소·본문 일부)
  const rfEl = document.getElementById('readFail');
  if (rfEl) rfEl.textContent = readFail
    ? `[${readFail.keyword}] ${readFail.pagingIndex}페이지 ${readFail.at}\n원인: ${readFail.err}\n제목: ${readFail.title}\n주소: ${readFail.href}\n본문: ${readFail.body}`
    : '없음 — 정상';
}

$('save').onclick = async () => {
  const wc = Math.min(9, Math.max(1, parseInt($('workerCount').value, 10) || 1));
  const no = Math.min(wc, Math.max(1, parseInt($('workerNo').value, 10) || 1));
  await chrome.storage.local.set({
    token: $('token').value.trim(),
    workerNo: no,
    workerCount: wc,
  });
  alert(wc > 1
    ? `저장했습니다. 이 기계는 ${wc}대 중 ${no}번 몫만 수집합니다.`
    : '저장했습니다. 이 기계가 전량을 수집합니다.');
  render();
};
// 토큰을 다른 기계에 옮겨 적을 때 — 눌러서 보고, 다시 누르면 가린다.
$('peek').onclick = () => {
  const el = $('token');
  const showing = el.type === 'text';
  el.type = showing ? 'password' : 'text';
  $('peek').textContent = showing ? '👁' : '🙈';
  if (!showing) { el.select(); }   // 바로 복사할 수 있게
};

$('run').onclick = () => chrome.runtime.sendMessage({ cmd: 'run' }, () => setTimeout(render, 600));
$('refresh').onclick = render;
render();
setInterval(render, 3000);
