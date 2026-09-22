// 팝업 — 토큰 저장 / 수동 실행 / 진행 상황 확인
const $ = (id) => document.getElementById(id);
let setupChecked = false;   // ⚙ 설정칸 자동 펼침은 처음 한 번만(render 3초 주기)

async function render() {
  const { token = '', state = {}, logs = [], rawSample = null, rawSampleAd = null,
          lastAdStat = null, readFail = null, workerNo = 1, workerCount = 1,
          trustedClick = undefined, searchEntry = undefined } =
    await chrome.storage.local.get(['token', 'state', 'logs', 'rawSample', 'rawSampleAd',
                                    'lastAdStat', 'readFail', 'workerNo', 'workerCount',
                                    'trustedClick', 'searchEntry']);
  // v1.16.0 — ⌨ 검색창에 쳐서 들어가기. 기본 켬(background 의 판정과 같아야 한다).
  const entryOn = searchEntry === undefined ? true : !!searchEntry;
  const eBtn = $('searchEntry');
  if (eBtn) {
    eBtn.textContent = entryOn ? '⌨ 네이버부터 검색해 들어가기 — 켬' : '⌨ 네이버부터 검색해 들어가기 — 끔';
    eBtn.style.background = entryOn ? '#dbeafe' : '';
    eBtn.style.color = entryOn ? '#1d4ed8' : '';
  }
  // v1.15.0 — 🖱 진짜 입력으로 클릭. 저장값이 없으면 **켬**이 기본(background 판정과 같아야 한다).
  //   ⚠️ 여기 기본값을 끔으로 바꾸면 background 와 어긋나 화면과 실제가 달라진다.
  const trustedOn = trustedClick === undefined ? true : !!trustedClick;
  const tBtn = $('trusted');
  if (tBtn) {
    tBtn.textContent = trustedOn ? '🖱 진짜 입력으로 클릭 — 켬' : '🖱 진짜 입력으로 클릭 — 끔';
    tBtn.style.background = trustedOn ? '#dbeafe' : '';
    tBtn.style.color = trustedOn ? '#1d4ed8' : '';
  }
  // ⚠️ 입력 중에는 덮어쓰지 않는다 — 3초마다 도는 render 가 타이핑을 지워 버린다.
  //    특히 토큰 칸은 새로 설치한 기계에서 저장값이 빈 문자열이라, 가드가 없으면
  //    한 글자 칠 때마다 지워져 사실상 입력이 불가능하다(2026-08-28 실사용 신고).
  //    붙여넣기로 3초 안에 끝내면 우연히 되던 것이라 여태 안 드러났다.
  if (document.activeElement !== $('token')) $('token').value = token;
  // ⚙ 설정칸은 기본으로 접혀 있다(팝업 600px 상한 안에 들어가게).
  //    처음 열 때만 — 토큰이 없거나 여러 대로 나눠 돌리는 중이면 펼쳐 준다.
  //    ⚠️ 매번 열면 3초마다 사용자가 접은 것을 다시 여는 꼴이 된다(render 는 3초 주기다).
  if (!setupChecked) {
    setupChecked = true;
    const sp = $('setup');
    if (sp && (!token || Number(workerCount) > 1 || Number(workerNo) > 1)) sp.open = true;
  }
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
  // 버튼 하나로 켜고 끈다 — 지금 어느 쪽인지 글자로 보이게 한다.
  const slowBtn = $('slow');
  if (slowBtn) {
    slowBtn.textContent = slowNow ? '🐢 안전 속도 끄기' : '🐢 안전 속도';
    slowBtn.style.background = slowNow ? '#fef3c7' : '';
    slowBtn.style.color = slowNow ? '#b45309' : '';
  }
  // ⏸ 이 기계에서 사람이 누른 일시정지(v1.20.0) — 사람이 직접 멈춘 것이라 가장 먼저 본다.
  const pausedByLocal = state.pausedByLocal === true;
  const pauseBtn = $('localPause');
  if (pauseBtn) {
    pauseBtn.textContent = pausedByLocal ? '▶ 재개 (지금 일시정지됨)' : '⏸ 일시정지';
    pauseBtn.style.background = pausedByLocal ? '#dc2626' : '#0f172a';
    pauseBtn.style.color = '#fff';
  }
  // 🛑 화면에서 꺼 둔 상태 — 그게 가장 중요한 정보라 캡차 다음으로 먼저 본다(2026-09-18).
  const pausedByScreen = !!state.pausedByScreen;
  const running = pausedByLocal
    ? '<span class="b bad">⏸ 일시정지됨 (이 수집기에서 · ▶ 재개를 누르세요)</span>'
    : (blockedNow
    ? '<span class="b bad">자동입력 방지(캡차)로 쉬는 중</span>'
    : (pausedByScreen ? '<span class="b bad">🛑 화면에서 꺼 둠 (로직분석 화면에서 켜세요)</span>'
      : (state.running ? '<span class="b ok">수집 중</span>' : '대기')));
  // ⭐ 오늘 전체 진척 (2026-08-28 대표 요청 「총 개수 / 추적 완료 / 추적 실패」).
  //    ⚠️ 아래 '이번 시간대' 숫자와 다른 축이다 — 그건 매시간 0 으로 돌아간다.
  //       여기 값은 서버가 알려 준 '오늘 재야 할 전체'와 '오늘까지 끝낸 수'다.
  // 📡 v1.21.0 — 서버 보고(살아있음 신호) + 알람 점검. 2번 노트북처럼 「조용히 안 도는」 기계를
  //    팝업만 열어도 알 수 있게 한다. 알람이 빠졌으면 빨갛게 — 「📡 지금 상태 보내기」가 다시 건다.
  const hbAt = state.lastHeartbeatAt ? new Date(state.lastHeartbeatAt) : null;
  const hbLine = hbAt
    ? `📡 서버 보고 ${hbAt.toLocaleTimeString('ko-KR')} ` +
      (state.lastHeartbeatOk ? '<span class="b ok">성공</span>' : '<span class="b bad">실패</span>') +
      (state.lastHeartbeatNote ? ` · ${state.lastHeartbeatNote}` : '')
    : '📡 서버 보고 — 아직 없음 (설치 후 15초 · 이후 5분마다)';
  let alarmLine = '';
  try {
    const names = (await chrome.alarms.getAll()).map((a) => a.name);
    const miss = ['daily', 'ondemand', 'heartbeat'].filter((n) => names.indexOf(n) === -1);
    alarmLine = miss.length
      ? `<span class="b bad">⚠ 알람 빠짐: ${miss.join(', ')}</span> — 「📡 지금 상태 보내기」를 누르면 다시 겁니다`
      : '<span class="dim">⏰ 알람 3종 정상(수집 1분 · 밀린 요청 1분 · 신호 5분)</span>';
  } catch (e) { alarmLine = '<span class="dim">⏰ 알람 상태를 읽지 못함</span>'; }
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
        `<span style="font-size:11px"> — ${new Date(slowUntil).toLocaleString('ko-KR')}까지 절반 속도</span><br>`
      : '') +
    `<div class="sec">${hbLine}<br>${alarmLine}</div>` +
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
// 🐢 안전 속도 — 누르면 켜지고, 켜진 상태에서 누르면 꺼진다. 24시간 뒤 스스로 풀린다.
$('slow').onclick = async () => {
  const { state = {} } = await chrome.storage.local.get('state');
  const on = Number(state.slowUntil || 0) > Date.now();
  chrome.runtime.sendMessage({ cmd: on ? 'slowOff' : 'slowOn' }, () => setTimeout(render, 400));
};
// 🔍 v1.14.0 — 사람이 연 화면이 받은 응답을 같은 자로 재서 서버에 보낸다(네이버 요청 0건).
$('humanProbe').onclick = () =>
  chrome.runtime.sendMessage({ cmd: 'humanProbe' }, () => setTimeout(render, 800));
// 🖱 v1.15.0 — 진짜 입력으로 클릭. 누를 때마다 켜고 끈다(background 가 같은 저장값을 읽는다).
$('trusted').onclick = async () => {
  const { trustedClick } = await chrome.storage.local.get('trustedClick');
  const on = trustedClick === undefined ? true : !!trustedClick;
  await chrome.storage.local.set({ trustedClick: !on });
  render();
};
// ⌨ v1.16.0 — 검색창에 쳐서 들어가기. 끄면 종전처럼 주소를 직접 연다.
$('searchEntry').onclick = async () => {
  const { searchEntry } = await chrome.storage.local.get('searchEntry');
  const on = searchEntry === undefined ? true : !!searchEntry;
  await chrome.storage.local.set({ searchEntry: !on });
  render();
};
// ⏸ v1.20.0 — 이 수집기를 즉시 멈추고/재개한다(이 기계에서만 · 화면 스위치와 별개 · 자동으로 안 풀림).
$('localPause').onclick = async () => {
  const { state = {} } = await chrome.storage.local.get('state');
  const on = state.pausedByLocal === true;   // 지금 멈춰 있으면 재개, 아니면 멈춤
  chrome.runtime.sendMessage({ cmd: 'setLocalPause', on: !on }, () => setTimeout(render, 300));
};
// 📡 v1.21.0 — 지금 상태를 서버에 보낸다(+ 빠진 알람 재장전). 네이버 요청 0건.
$('heartbeat').onclick = () =>
  chrome.runtime.sendMessage({ cmd: 'heartbeat' }, () => setTimeout(render, 900));
$('refresh').onclick = render;
render();
setInterval(render, 3000);
