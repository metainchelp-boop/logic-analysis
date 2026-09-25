/* 순위 읽기 도우미 — 팝업 */
const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function openUrl(kw) {
  // 사람이 누르는 링크 — 확장이 네이버를 부르는 것이 아니다(새 탭은 직원이 연다).
  return 'https://search.shopping.naver.com/search/all?query=' + encodeURIComponent(kw);
}

function describe(r) {
  if (r.busyPc) return `<span class="busy">PC ${esc(r.busyPc)}번이 방금 봄</span>`;
  if (r.covered > 0) return `1~${esc(r.covered)}위 확인 · ${esc(r.covered + 1)}위부터 필요`;
  if (r.tried) return '수집기가 1페이지까지 봄 · 2페이지부터 필요';
  return '아직 아무도 안 봄';
}

async function render() {
  $('ver').textContent = 'v' + chrome.runtime.getManifest().version;
  const s = await chrome.storage.local.get(['token', 'pc', 'enabled', 'counts', 'todo', 'lastError', 'lastNote', 'lastRead']);
  const linked = !!(s.token && s.pc);
  $('setup').classList.toggle('hidden', linked);
  $('main').classList.toggle('hidden', !linked);
  $('todoBox').classList.toggle('hidden', !linked);
  if (!linked) return;

  const on = s.enabled !== false;
  const st = $('state');
  st.className = 'state' + (on ? (s.lastError ? ' err' : '') : ' off');
  st.textContent = !on ? '꺼짐 — 아무것도 읽지 않습니다'
    : s.lastError ? `켜짐 · 문제: ${s.lastError}` : `켜짐 — 추적 키워드 화면만 읽는 중 · PC ${s.pc}번`;
  $('toggle').textContent = on ? '⏸ 잠시 끄기' : '▶ 다시 켜기';

  const c = s.counts && s.counts.date === new Date().toLocaleDateString('sv-SE') ? s.counts : null;
  $('nPages').textContent = c ? c.pages : 0;
  $('nKw').textContent = c ? c.keywords.length : 0;
  $('nFound').textContent = c ? (c.foundKeywords || []).length : 0;

  const lr = s.lastRead;
  $('last').textContent = s.lastNote ? s.lastNote
    : lr ? `마지막: 「${lr.keyword}」 1~${lr.covered}위 읽음 · 추적 대상 ${lr.found}/${lr.targets} 찾음` + (lr.status === 'complete' || lr.status === 'partial_all_found' ? ' · 완료' : '')
    : '';

  const t = s.todo;
  const ul = $('todo');
  if (!t) { ul.innerHTML = '<li><span class="kw"><span>목록을 받는 중…</span></span></li>'; return; }
  $('left').textContent = `남은 ${t.todo} / 전체 ${t.total}`;
  const rows = (t.keywords || []).slice(0, 40);
  ul.innerHTML = rows.length ? rows.map((r) => `
    <li><span class="kw"><b>${esc(r.keyword)}</b><span>${describe(r)}</span></span>
        <a class="open" href="${esc(openUrl(r.keyword))}" target="_blank" rel="noopener">${r.covered > 0 ? '이어서 보기' : '네이버에서 열기'}</a></li>`).join('')
    : '<li><span class="kw"><b>오늘 할 일이 없습니다</b><span>전부 끝났습니다.</span></span></li>';
}

$('save').addEventListener('click', async () => {
  const token = $('token').value.trim();
  const pc = parseInt($('pc').value, 10);
  if (!token || !(pc >= 1 && pc <= 99)) { $('saveMsg').textContent = '연결 코드와 PC 번호(1~99)를 넣어 주세요.'; return; }
  await chrome.storage.local.set({ token, pc, enabled: true, lastError: '' });
  chrome.runtime.sendMessage({ type: 'hv-refresh' }, () => { void chrome.runtime.lastError; render(); });
  render();
});
$('toggle').addEventListener('click', async () => {
  const { enabled } = await chrome.storage.local.get('enabled');
  await chrome.storage.local.set({ enabled: enabled === false });
  render();
});
$('reset').addEventListener('click', async () => {
  await chrome.storage.local.remove(['token', 'pc', 'todo']);
  render();
});

render();
chrome.runtime.sendMessage({ type: 'hv-refresh' }, () => { void chrome.runtime.lastError; render(); });
