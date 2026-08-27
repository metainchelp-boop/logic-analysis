// 팝업 — 토큰 저장 / 수동 실행 / 진행 상황 확인
const $ = (id) => document.getElementById(id);

async function render() {
  const { token = '', state = {}, logs = [], rawSample = null, rawSampleAd = null,
          lastAdStat = null, readFail = null, workerNo = 1, workerCount = 1 } =
    await chrome.storage.local.get(['token', 'state', 'logs', 'rawSample', 'rawSampleAd',
                                    'lastAdStat', 'readFail', 'workerNo', 'workerCount']);
  $('token').value = token;
  // ⚠️ 입력 중에는 덮어쓰지 않는다 — 3초마다 도는 render 가 타이핑을 지워 버린다.
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
  const running = blockedNow
    ? '<span class="b bad">자동입력 방지(캡차)로 쉬는 중</span>'
    : (state.running ? '<span class="b ok">수집 중</span>' : '대기');
  $('stat').innerHTML =
    `상태: ${running}<br>` +
    (blockedNow
      ? `<span class="b bad">▸ ${new Date(bu).toLocaleTimeString('ko-KR')} 이후 자동 재개</span><br>` +
        '<span style="font-size:11px">네이버쇼핑을 직접 열어 캡차를 한 번 풀고 「지금 수집 실행」을 누르면 바로 재개됩니다.</span><br>'
      : '') +
    `대상 <span class="b">${state.target ?? '-'}</span>개 · ` +
    `성공 <span class="b ok">${state.done ?? 0}</span> · ` +
    `실패 <span class="b bad">${state.failed ?? 0}</span><br>` +
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
        `  (광고 표식은 있는데 링크로 못 거른 상품 ${lastAdStat.hint}개)\n\n`
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
$('run').onclick = () => chrome.runtime.sendMessage({ cmd: 'run' }, () => setTimeout(render, 600));
$('refresh').onclick = render;
render();
setInterval(render, 3000);
