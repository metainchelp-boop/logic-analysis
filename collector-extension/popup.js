// 팝업 — 토큰 저장 / 수동 실행 / 진행 상황 확인
const $ = (id) => document.getElementById(id);

async function render() {
  const { token = '', state = {}, logs = [], rawSample = null } = await chrome.storage.local.get(['token', 'state', 'logs', 'rawSample']);
  $('token').value = token;
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
}

$('save').onclick = async () => {
  await chrome.storage.local.set({ token: $('token').value.trim() });
  alert('토큰을 저장했습니다.');
  render();
};
$('run').onclick = () => chrome.runtime.sendMessage({ cmd: 'run' }, () => setTimeout(render, 600));
$('refresh').onclick = render;
render();
setInterval(render, 3000);
