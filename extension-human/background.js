/* 순위 읽기 도우미 — 확장 안쪽 (서비스 워커)
 *
 * 하는 일
 *   ① 오늘 할 일 목록(우리 추적 키워드 중 아직 안 끝난 것)을 서버에서 받아 둔다(10분마다 · 팝업 열 때).
 *   ② 화면이 읽은 목록이 오면 — 할 일 목록에 있는 검색어일 때만 — 1페이지부터 이어 본 만큼 순위를 매겨 서버로 보낸다.
 *   ③ 툴바 아이콘에 「읽음」·「완료」 표시.
 *
 * 하지 않는 것
 *   · 네이버에 요청하지 않는다(이 파일의 fetch 는 전부 logic.metainc.co.kr).
 *   · 할 일 목록에 없는 검색어는 **버린다** — 서버로 한 글자도 안 보낸다.
 *   · 방문 기록·다른 사이트·쿠키·계정 정보는 읽지 않는다(권한 자체가 없다).
 */
importScripts('rank_rules.js', 'hv_core.js');

const VERSION = chrome.runtime.getManifest().version;
const SERVER = 'https://logic.metainc.co.kr';
const TODO_TTL_MS = 10 * 60 * 1000;

async function cfg() {
  const c = await chrome.storage.local.get(['token', 'pc', 'enabled']);
  return { token: c.token || '', pc: c.pc || '', enabled: c.enabled !== false };
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function bump(fields) {
  const { counts } = await chrome.storage.local.get('counts');
  const c = counts && counts.date === today() ? counts : { date: today(), pages: 0, keywords: [], foundKeywords: [] };
  if (fields.page) c.pages += 1;
  if (fields.keyword && c.keywords.indexOf(fields.keyword) < 0) c.keywords.push(fields.keyword);
  if (fields.foundKeyword && c.foundKeywords.indexOf(fields.foundKeyword) < 0) c.foundKeywords.push(fields.foundKeyword);
  await chrome.storage.local.set({ counts: c });
}

async function refreshTodo(force) {
  const { token, pc } = await cfg();
  if (!token || !pc) return null;
  const { todo } = await chrome.storage.local.get('todo');
  if (!force && todo && Date.now() - (todo.fetchedAt || 0) < TODO_TTL_MS) return todo;
  try {
    const r = await fetch(`${SERVER}/api/human-view/todo`, { headers: { 'X-Human-Token': token, 'X-Human-Pc': String(pc) } });
    if (!r.ok) {
      await chrome.storage.local.set({ lastError: `할 일 목록 ${r.status}` });
      return todo || null;
    }
    const j = await r.json();
    const fresh = { fetchedAt: Date.now(), date: j.date, total: j.total, done: j.done, todo: j.todo, keywords: j.keywords || [] };
    await chrome.storage.local.set({ todo: fresh, lastError: '' });
    return fresh;
  } catch (e) {
    await chrome.storage.local.set({ lastError: '서버에 닿지 않음' });
    return todo || null;
  }
}

async function tabState(tabId) {
  const k = `tab:${tabId}`;
  const o = await chrome.storage.session.get(k);
  return o[k] || null;
}
async function setTabState(tabId, st) {
  await chrome.storage.session.set({ [`tab:${tabId}`]: st });
}

function badge(tabId, text, color) {
  try {
    chrome.action.setBadgeText({ tabId, text });
    chrome.action.setBadgeBackgroundColor({ tabId, color: color || '#16a34a' });
  } catch (e) {}
}

async function onPage(tabId, d) {
  const { token, pc, enabled } = await cfg();
  if (!enabled || !token || !pc) return;
  const todo = await refreshTodo(false);
  const set = new Set(((todo && todo.keywords) || []).map((r) => r.keyword));
  if (!HvCore.isTracked(set, d.keyword)) return;          // 추적 키워드가 아니다 — 버린다
  const prev = await tabState(tabId);
  const m = HvCore.mergePage(prev, d.keyword, d.page, d.list, Date.now());
  if (!m.ok) {
    badge(tabId, '1p?', '#f59e0b');                        // 1페이지부터 봐야 순위를 매길 수 있다
    await chrome.storage.local.set({ lastNote: '1페이지부터 이어서 봐 주셔야 순위가 적힙니다.' });
    return;
  }
  await setTabState(tabId, m.state);
  const b = HvCore.build(m.state, RankRules, d.total);
  if (!b.products.length) return;
  const products = b.products.map((p) => ({
    rank: p.rank, productId: p.productId, nvMid: p.nvMid || '', sourcePage: p.sourcePage || null,
    title: p.title, link: p.link, price: p.price, mallName: p.mallName, brand: p.brand,
    category1: p.category1, category2: p.category2, category3: p.category3, reviewCount: p.reviewCount,
  }));
  const body = { keyword: d.keyword, total: Number(d.total) || 0, products, pagesRead: b.pagesRead,
                 endOfResults: b.endOfResults, loggedIn: d.loggedIn || 'unknown', extVersion: VERSION };
  let res = null;
  for (let attempt = 0; attempt < 2 && !res; attempt++) {
    try {
      const r = await fetch(`${SERVER}/api/human-view/page`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Human-Token': token, 'X-Human-Pc': String(pc) },
        body: JSON.stringify(body),
      });
      if (r.ok) res = await r.json();
      else if (r.status < 500) { await chrome.storage.local.set({ lastError: `보내기 ${r.status}` }); break; }
    } catch (e) { /* 한 번 더 */ }
    if (!res && attempt === 0) await new Promise((ok) => setTimeout(ok, 3000));
  }
  if (!res) { badge(tabId, '!', '#dc2626'); return; }
  const found = (res.ranked && res.ranked.targets_found) || 0;
  const doneNow = res.status === 'complete' || res.status === 'partial_all_found';
  badge(tabId, doneNow ? '완료' : '읽음', doneNow ? '#16a34a' : '#3b82f6');
  await bump({ page: true, keyword: d.keyword, foundKeyword: found > 0 ? d.keyword : '' });
  await chrome.storage.local.set({ lastRead: { keyword: d.keyword, covered: b.covered, status: res.status,
                                               found, targets: (res.ranked && res.ranked.targets_total) || 0,
                                               at: Date.now() }, lastError: '', lastNote: '' });
  if (doneNow) await refreshTodo(true);
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === 'hv-page' && sender.tab && sender.tab.id != null) {
    onPage(sender.tab.id, msg.data).catch(() => {});
    reply({ ok: true });
    return false;
  }
  if (msg && msg.type === 'hv-refresh') {
    refreshTodo(true).then((t) => reply({ ok: !!t })).catch(() => reply({ ok: false }));
    return true;
  }
  return false;
});

chrome.tabs && chrome.tabs.onRemoved && chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`tab:${tabId}`).catch(() => {});
});
