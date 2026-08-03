// 팝업 — 토큰 저장 / 수동 실행 / 진행 상황 확인
const $ = (id) => document.getElementById(id);

async function render() {
  const { token = '', state = {}, logs = [] } = await chrome.storage.local.get(['token', 'state', 'logs']);
  $('token').value = token;
  const running = state.running ? '<span class="b ok">수집 중</span>' : '대기';
  $('stat').innerHTML =
    `상태: ${running}<br>` +
    `대상 <span class="b">${state.target ?? '-'}</span>개 · ` +
    `성공 <span class="b ok">${state.done ?? 0}</span> · ` +
    `실패 <span class="b bad">${state.failed ?? 0}</span><br>` +
    (state.current ? `진행 중: ${state.current}<br>` : '') +
    (state.finishedAt ? `마지막 완료: ${new Date(state.finishedAt).toLocaleString('ko-KR')}` : '아직 완료 기록 없음');
  $('logs').textContent = logs.join('\n');
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
