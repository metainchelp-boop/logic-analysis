/**
 * 메타아이앤씨 순위 수집기 — 백그라운드 서비스 워커
 *
 * 왜 필요한가: 2026-07-31 네이버 '검색 > 쇼핑' API가 종료돼(404 SE05) 서버에서
 * 검색 결과를 못 받는다. 서버 IP 직접 요청은 봇으로 차단(418)된다.
 * 사무실 PC의 실제 브라우저는 정상 조회되므로, 이 확장이 새벽에 대신 모아 서버로 올린다.
 *
 * 동작
 *   1) 서버에서 오늘 수집할 키워드 목록을 받는다
 *   2) 키워드마다 검색 결과를 여러 페이지 받아 300위까지 모은다
 *   3) 키워드 1건이 끝날 때마다 즉시 서버로 올린다(중간에 꺼져도 거기까지는 남는다)
 *
 * 차단 방지 — 이 부분은 함부로 줄이지 말 것
 *   · 요청 간격을 사람 수준으로 둔다(기본 1.5~3초 랜덤)
 *   · 실패하면 점점 더 길게 쉰다(백오프), 연속 실패가 쌓이면 그날은 중단한다
 *   · 속도를 올리면 사무실 IP가 통째로 차단돼 직원들 네이버 접속까지 막힐 수 있다
 */

const CFG = {
  serverBase: 'https://logic.metainc.co.kr',
  pageSize: 80,          // 한 요청당 상품 수 (네이버 허용 상한)
  maxRank: 300,          // 300위까지 = 80 × 4페이지
  minGapMs: 1500,        // 요청 간 최소 간격
  maxGapMs: 4000,        // 요청 간 최대 간격 (이 사이 랜덤 — 여유 확대 2026-08-04)
  // ── 24시간 분산 (2026-08-05 운영자 확정) ─────────────────────────────
  // 종전: 새벽 1시부터 6시간에 954개를 몰아침 → 분당 10.6회 → 네이버가 IP 차단
  //       (「쇼핑 서비스 접속이 일시적으로 제한되었습니다」 — 사유에 '짧은 시간 내에
  //        너무 많은 요청이 이루어진 IP' 명시).
  // 지금: 서버가 키워드를 24개 시간대로 나눠 주고, 확장은 **매시간 자기 몫만** 한다.
  //       시간당 ~40개 → 분당 2.7회. 맥북이 24시간 켜져 있으니 창을 넓게 쓰는 게 이득.
  keywordGapMs: 45000,   // 키워드 사이 휴식 45초 (시간당 40개 기준 여유 있게)
  hourBudgetMs: 50 * 60 * 1000,  // 한 회차는 50분 안에 끝낸다(다음 시간대와 겹치지 않게)
  maxConsecutiveFail: 5, // 연속 실패가 이만큼이면 이번 회차 중단(차단 의심)
  runHour: 1,            // (유지) 회차 날짜 계산용 — 수집은 이제 24시간 상시
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => CFG.minGapMs + Math.random() * (CFG.maxGapMs - CFG.minGapMs);

async function getToken() {
  const { token } = await chrome.storage.local.get('token');
  return token || '';
}

async function setState(patch) {
  const cur = (await chrome.storage.local.get('state')).state || {};
  await chrome.storage.local.set({ state: { ...cur, ...patch, updatedAt: new Date().toISOString() } });
}

async function log(line) {
  const { logs = [] } = await chrome.storage.local.get('logs');
  logs.unshift(`[${new Date().toLocaleTimeString('ko-KR')}] ${line}`);
  await chrome.storage.local.set({ logs: logs.slice(0, 200) });
}

/* ── 요청 경로 2단 구조 (2026-08-04 실측 후 개편) ──
 * 확장 백그라운드에서 보내는 직접 fetch 는 실제 페이지 요청과 헤더(Sec-Fetch-*)·쿠키가
 * 달라 네이버가 418 로 차단함을 현장에서 확인했다.
 * → 실제 네이버쇼핑 페이지를 백그라운드 고정 탭으로 하나 열어두고, '그 페이지 안에서'
 *   fetch 를 실행한다. 이는 사이트 자신의 페이지네이션 요청과 완전히 동일해 차단 불가.
 * 직접 fetch 를 1차로 시도하되(언젠가 풀릴 수 있음), 418 이 확인되면 그 세션 동안은
 * 페이지 경로로 영구 전환한다(차단당한 경로를 계속 두드리지 않기 위함). */
let fetchMode = 'direct';          // 'direct' | 'page'
let workTabId = null;

/* ⚠️ workTabId 는 메모리 변수라 MV3 서비스워커가 잠들었다 깨면 null 로 돌아간다.
 * 그러면 매번 새 작업 탭을 만들어 옛 탭이 영원히 쌓였다(2026-08-05 현장: 네이버쇼핑
 * 탭이 잔뜩 열린 채 자동입력 방지 페이지에 머물러 있었음).
 * 탭이 쌓이면 한 IP 에서 동시 요청이 늘어 봇 판정을 자초하고, 캡차에 걸리면
 * URL 이 바뀌어 「유효한 작업 탭 아님」으로 또 새 탭을 만드는 악순환이 된다.
 * → 탭 id 를 storage 에 남겨 재기동에도 이어 쓰고, 남은 탭은 정리하며,
 *   캡차가 뜨면 탭을 더 만들지 않고 즉시 멈춘다. */
const TAB_KEY = 'workTabId';
const BLOCK_KEY = 'blockedUntil';
const WORK_URL = 'https://search.shopping.naver.com/search/all?query=' + encodeURIComponent('쇼핑');
const BLOCK_COOLDOWN_MS = 6 * 60 * 60 * 1000;   // 캡차 확인 시 6시간 쉼(계속 두드리면 더 깊이 막힌다)

/** 캡차·차단 페이지로 넘어갔는지 — URL 이 검색 도메인을 벗어났으면 차단으로 본다. */
function isBlockedUrl(url) {
  const u = String(url || '');
  if (!u) return false;
  if (u.includes('search.shopping.naver.com')) return false;
  return /naver\.com/.test(u);   // ncpt·nid 등 네이버 안의 다른 페이지 = 캡차/로그인 유도
}

async function getBlockedUntil() {
  const o = await chrome.storage.local.get(BLOCK_KEY);
  return Number(o[BLOCK_KEY] || 0);
}

async function markBlocked(reason) {
  const until = Date.now() + BLOCK_COOLDOWN_MS;
  await chrome.storage.local.set({ [BLOCK_KEY]: until });
  await setState({ blocked: true, blockedUntil: until, blockedReason: reason });
  await log(`🧱 네이버 자동입력 방지(캡차) 확인 — ${reason}. 6시간 쉬었다 재개합니다.`);
  await log('   해제하려면: 크롬에서 네이버쇼핑을 직접 열어 캡차를 한 번 풀어주세요.');
  // 쌓인 작업 탭을 닫아 둔다 — 열어둘수록 봇 판정이 깊어지고 화면도 지저분해진다.
  await closeAllWorkTabs();
}

async function clearBlocked() {
  await chrome.storage.local.remove(BLOCK_KEY);
  await setState({ blocked: false, blockedUntil: 0, blockedReason: '' });
}

/** 네이버쇼핑 작업 탭 전부 닫기 — 누적분 청소용. */
async function closeAllWorkTabs() {
  try {
    const tabs = await chrome.tabs.query({ url: '*://search.shopping.naver.com/*' });
    const ids = tabs.map((t) => t.id).filter((id) => id !== undefined);
    if (ids.length) {
      await chrome.tabs.remove(ids);
      await log(`🧹 작업 탭 ${ids.length}개 정리`);
    }
  } catch (e) { /* 이미 닫힘 등 — 무시 */ }
  workTabId = null;
  await chrome.storage.local.remove(TAB_KEY);
}

function waitTabLoaded(tabId) {
  return new Promise((resolve) => {
    const iv = setInterval(async () => {
      try {
        const t = await chrome.tabs.get(tabId);
        if (t.status === 'complete') { clearInterval(iv); resolve(); }
      } catch (e) { clearInterval(iv); resolve(); }
    }, 500);
    setTimeout(() => { clearInterval(iv); resolve(); }, 20000);
  });
}

/** 네이버쇼핑 작업 탭 확보 — 항상 **한 개만** 유지한다.
 *
 *  ① 메모리 → ② storage → ③ 이미 열려 있는 탭 순으로 이어 쓰고, 남는 탭은 닫는다.
 *  ④ 그래도 없으면 새로 만드는데, **열린 크롬 창이 하나도 없으면**
 *     `chrome.tabs.create` 가 'No current window' 로 실패하므로(맥에서 창만 닫고
 *     크롬은 살아 있는 상태 — 2026-08-05 실사고) 최소화된 창을 먼저 만든다. */
async function ensureWorkTab() {
  // ① 메모리에 들고 있던 탭
  if (workTabId !== null) {
    try {
      const t = await chrome.tabs.get(workTabId);
      if (t && (t.url || '').includes('search.shopping.naver.com')) return workTabId;
      if (isBlockedUrl(t && t.url)) throw new Error('BLOCKED:' + (t.url || ''));
    } catch (e) {
      if (String(e.message || '').startsWith('BLOCKED:')) throw e;
      /* 닫힘 — 아래로 */
    }
  }
  // ② 지난 기동에서 남긴 탭
  try {
    const saved = (await chrome.storage.local.get(TAB_KEY))[TAB_KEY];
    if (saved) {
      const t = await chrome.tabs.get(saved);
      if (t && (t.url || '').includes('search.shopping.naver.com')) {
        workTabId = saved;
        return workTabId;
      }
      if (isBlockedUrl(t && t.url)) throw new Error('BLOCKED:' + (t.url || ''));
    }
  } catch (e) {
    if (String(e.message || '').startsWith('BLOCKED:')) throw e;
  }
  // ③ 이미 열려 있는 네이버쇼핑 탭 재사용 + 나머지 정리(누적 방지)
  try {
    const tabs = await chrome.tabs.query({ url: '*://search.shopping.naver.com/*' });
    if (tabs.length) {
      workTabId = tabs[0].id;
      const extra = tabs.slice(1).map((t) => t.id).filter((id) => id !== undefined);
      if (extra.length) {
        await chrome.tabs.remove(extra);
        await log(`🧹 중복 작업 탭 ${extra.length}개 정리 (1개만 유지)`);
      }
      await chrome.storage.local.set({ [TAB_KEY]: workTabId });
      return workTabId;
    }
  } catch (e) { /* 조회 실패 — 아래에서 새로 만든다 */ }

  // ④ 새로 만든다 — 창이 없으면 창부터
  let tab;
  let wins = [];
  try { wins = await chrome.windows.getAll({ windowTypes: ['normal'] }); } catch (e) { wins = []; }
  if (!wins.length) {
    // 창이 하나도 없는 상태(맥: 창만 닫고 크롬은 실행 중) — 최소화 창을 만들어 그 안에서 작업
    const w = await chrome.windows.create({ url: WORK_URL, focused: false, state: 'minimized' });
    tab = (w.tabs && w.tabs[0]) || null;
    if (!tab) throw new Error('작업 창 생성 실패');
    await log('🪟 열린 크롬 창이 없어 최소화 창을 만들어 진행합니다.');
  } else {
    tab = await chrome.tabs.create({
      url: WORK_URL,
      active: false,    // 화면을 뺏지 않게 백그라운드로
      pinned: true,     // 실수로 닫기 어렵게 고정
      windowId: wins[0].id,
    });
  }
  workTabId = tab.id;
  await chrome.storage.local.set({ [TAB_KEY]: workTabId });
  await waitTabLoaded(workTabId);
  await sleep(2500);               // 페이지 초기 스크립트·쿠키 정착 대기
  // 로딩 끝난 주소가 검색 도메인을 벗어났으면 캡차로 넘어간 것
  try {
    const t = await chrome.tabs.get(workTabId);
    if (isBlockedUrl(t && t.url)) throw new Error('BLOCKED:' + t.url);
  } catch (e) {
    if (String(e.message || '').startsWith('BLOCKED:')) throw e;
  }
  await log('🪟 네이버쇼핑 작업 탭 준비 완료 (1개만 유지 — 닫혀도 자동 재생성)');
  return workTabId;
}

/** 실제 페이지 컨텍스트에서 fetch — 사이트 자신의 요청과 동일(같은 출처·쿠키·Sec-Fetch)
 *
 *  ⚠️ 캡차에 걸리면 JSON 대신 HTML 이 돌아온다. 종전엔 `r.json()` 이 터진 것을
 *  평범한 실패로 세어 계속 재시도했고, 그 재시도가 차단을 더 깊게 만들었다.
 *  → 응답이 JSON 이 아니면 **차단으로 판정**하고 즉시 멈춘다. */
async function fetchViaPage(url) {
  const tabId = await ensureWorkTab();
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async (u) => {
      try {
        const r = await fetch(u, { credentials: 'include', headers: { 'Accept': 'application/json' } });
        const ct = r.headers.get('content-type') || '';
        if (!r.ok) return { err: 'HTTP ' + r.status, blocked: r.status === 418 || r.status === 429 };
        if (!ct.includes('json')) {
          // 캡차·안내 페이지가 HTML 로 돌아온 경우
          const head = (await r.text()).slice(0, 200);
          return { err: 'JSON 이 아닌 응답', blocked: true, head };
        }
        return { data: await r.json() };
      } catch (e) { return { err: String(e && e.message || e) }; }
    },
    args: [url],
  });
  const out = res && res.result;
  if (!out) throw new Error('페이지 주입 실패');
  if (out.blocked) throw new Error('BLOCKED:' + out.err);
  if (out.err) throw new Error(out.err);
  return out.data;
}

/** 네이버 검색 결과 1페이지 */
async function fetchPage(keyword, pagingIndex) {
  const url = 'https://search.shopping.naver.com/api/search/all'
    + `?sort=rel&pagingIndex=${pagingIndex}&pagingSize=${CFG.pageSize}`
    + `&query=${encodeURIComponent(keyword)}`;
  let data;
  if (fetchMode === 'direct') {
    try {
      const res = await fetch(url, {
        headers: { 'Accept': 'application/json', 'Referer': 'https://search.shopping.naver.com/' },
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (e) {
      // 직접 경로 차단 확인 → 이 세션은 페이지 경로로 전환(차단 경로 재타격 방지)
      fetchMode = 'page';
      await log(`↪ 직접 요청 차단(${e.message}) — 실제 페이지 경로로 전환`);
      data = await fetchViaPage(url);
    }
  } else {
    data = await fetchViaPage(url);
  }
  const node = data?.shoppingResult || {};
  return { total: node.total || 0, list: node.products || [] };
}

/** 네이버 응답 → 서버가 쓰는 형태로 정리 */
function toProduct(p, rank) {
  return {
    rank,
    productId: String(p.id || p.nvMid || ''),
    title: String(p.productTitle || p.productName || '').replace(/<[^>]*>/g, ''),
    link: String(p.mallProductUrl || p.adcrUrl || p.crUrl || ''),
    price: String(p.price || p.lowPrice || ''),
    mallName: String(p.mallName || p.mallNm || ''),
    brand: String(p.brand || p.maker || ''),
    category1: String(p.category1Name || ''),
    category2: String(p.category2Name || ''),
    category3: String(p.category3Name || ''),
    reviewCount: String(p.reviewCount || ''),
  };
}

/** 키워드 1건을 300위까지 수집 */
async function collectKeyword(keyword) {
  const products = [];
  let total = 0;
  const pages = Math.ceil(CFG.maxRank / CFG.pageSize);
  for (let i = 1; i <= pages; i++) {
    const { total: t, list } = await fetchPage(keyword, i);
    if (i === 1) total = t;
    if (!list.length) break;
    // ⚠️ 첫 키워드 첫 상품의 '원본 JSON'을 저장해 둔다. toProduct 의 필드명 가정
    //    (p.productTitle·p.category1Name 등)이 실제 네이버 응답과 맞는지 내일 첫 실행 때
    //    팝업에서 눈으로 검증하기 위함(맞으면 매핑 확정, 다르면 즉시 교정).
    if (i === 1 && list[0]) {
      chrome.storage.local.set({ rawSample: { keyword, at: new Date().toISOString(), item: list[0] } });
    }
    list.forEach((p, idx) => {
      const rank = (i - 1) * CFG.pageSize + idx + 1;
      if (rank <= CFG.maxRank) products.push(toProduct(p, rank));
    });
    if (list.length < CFG.pageSize) break;   // 더 이상 페이지 없음
    if (i < pages) await sleep(jitter());
  }
  return { total, products };
}

async function uploadKeyword(token, keyword, payload) {
  const res = await fetch(`${CFG.serverBase}/api/collector/serp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Collector-Token': token },
    body: JSON.stringify({ keyword, total: payload.total, products: payload.products }),
  });
  if (!res.ok) throw new Error(`업로드 실패 HTTP ${res.status}`);
  return res.json();
}

let running = false;

async function runCollection(manual = false) {
  if (running) { await log('이미 수집 중 — 중복 실행 무시'); return; }
  running = 'daily';   // ⚠️ 첫 await 이전에 '동기' 선점 — ondemand 와 알람이 겹쳐도 이중 진입 불가
  // 캡차 쉼 중이면 들어가지 않는다(계속 두드리면 차단이 깊어진다). 수동 실행은 사람이
  // 캡차를 풀고 눌렀을 수 있으므로 통과시킨다.
  const bu = await getBlockedUntil();
  if (!manual && bu > Date.now()) {
    await log(`⏸ 자동입력 방지 쉼 중 — ${new Date(bu).toLocaleTimeString('ko-KR')} 이후 재개`);
    running = false; return;
  }
  if (manual && bu) await clearBlocked();
  const token = await getToken();
  if (!token) { await log('❌ 토큰이 없습니다. 팝업에서 먼저 저장하세요.'); running = false; return; }

  await setState({ running: true, startedAt: new Date().toISOString(), done: 0, failed: 0 });
  await log(manual ? '▶ 수동 수집 시작' : '▶ 자동 수집 시작');

  const hourStart = Date.now();
  const hourTag = hourKey();
  try {
    // 이번 시간대 몫만 받아온다(24시간 분산). 서버가 슬롯 + 밀린 것을 함께 준다.
    const nowHour = new Date().getHours();
    const res = await fetch(`${CFG.serverBase}/api/collector/keywords?hour=${nowHour}`, {
      headers: { 'X-Collector-Token': token },
    });
    if (!res.ok) throw new Error(`키워드 조회 실패 HTTP ${res.status}`);
    const { keywords = [], done: already = 0, total = 0,
            slot = null, overdue = 0 } = await res.json();
    await log(`⏱ ${nowHour}시 몫 ${keywords.length}개`
      + (slot === null ? '' : ` (이 시간대 ${slot} · 밀린 것 ${overdue})`)
      + ` — 전체 ${total} · 오늘 완료 ${already}`);
    if (!keywords.length) {
      await setState({ running: false, finishedHour: hourTag, current: '' });
      await log('이번 시간대 수집 대상 없음');
      return;
    }
    await setState({ target: keywords.length });

    let done = 0, failed = 0, streak = 0;
    for (const kw of keywords) {
      // 다음 시간대와 겹치지 않게 — 남은 것은 서버가 '밀린 것'으로 다시 내려준다
      if (Date.now() - hourStart > CFG.hourBudgetMs) {
        await log(`⏱ 이번 시간대 시간 소진 — ${keywords.length - done - failed}개는 다음 회차로`);
        break;
      }
      try {
        const payload = await collectKeyword(kw);
        if (!payload.products.length) throw new Error('상품 0건');
        await uploadKeyword(token, kw, payload);
        done++; streak = 0;
        await setState({ done, failed, current: kw });
        if (done % 25 === 0) await log(`… ${done}/${keywords.length} 진행 중`);
      } catch (e) {
        // 캡차로 확인되면 더 두드리지 않고 즉시 접는다(재시도가 차단을 깊게 만든다)
        if (String(e.message || '').startsWith('BLOCKED:')) {
          await markBlocked(e.message.slice(8) || '수집 중 감지');
          break;
        }
        failed++; streak++;
        await log(`⚠️ [${kw}] 실패: ${e.message}`);
        await setState({ done, failed, current: kw });
        if (streak >= CFG.maxConsecutiveFail) {
          await log(`🛑 연속 ${streak}회 실패 — 차단 의심으로 이번 회차 중단`);
          break;
        }
        await sleep(jitter() * (1 + streak));   // 실패할수록 더 길게 쉰다
      }
      await sleep(jitter() + CFG.keywordGapMs);
    }
    if (done > 0) await clearBlocked();   // 값을 실제로 받았다 = 차단 풀림
    await log(`✅ ${new Date().getHours()}시 회차 종료 — 성공 ${done} · 실패 ${failed}`);
    // 못 한 키워드는 서버가 다음 시간대에 '밀린 것'으로 다시 내려주므로 여기서 표시만 남긴다
    if (done > 0) {
      await setState({ running: false, finishedAt: new Date().toISOString(),
                       finishedHour: hourTag, done, failed, current: '' });
    } else {
      await setState({ running: false, done, failed, current: '' });
      await log('⚠️ 성공 0건 — 다음 시간대에 자동 재시도');
    }
  } catch (e) {
    await log(`❌ 수집 중단: ${e.message}`);
    await setState({ running: false, error: e.message });
  } finally {
    if (running === 'daily') running = false;   // 내 락만 해제 (남의 락 오해제 방지)
  }
}

/** 낮 시간 온디맨드 — 직원이 새 키워드를 분석하면 서버 요청 큐에 쌓이고,
 *  1분 주기로 그걸 걷어 즉시 수집한다(한 번에 최대 10개 — 소량이라 IP 부하 미미).
 *  새벽 전체 수집이 도는 동안에는 건너뛴다. */
async function runOnDemand() {
  if (running) return;
  running = 'ondemand';   // ⚠️ 첫 await 이전에 '동기' 선점 — daily 와 알람이 겹쳐도 이중 진입 불가
  try {
    // 캡차 쉼 중이면 아예 들어가지 않는다(매분 재타격 = 차단 연장)
    if (await getBlockedUntil() > Date.now()) return;
    // 직전 회차가 전량 실패(차단 의심)였으면 10분 쉰다 — 차단 중 매분 재타격으로 차단을 연장시키지 않기 위함
    const { odBackoffUntil = 0 } = await chrome.storage.local.get('odBackoffUntil');
    if (Date.now() < odBackoffUntil) return;

    const token = await getToken();
    if (!token) return;
    let kws = [];
    try {
      const res = await fetch(`${CFG.serverBase}/api/collector/requests`, {
        headers: { 'X-Collector-Token': token },
      });
      if (!res.ok) return;
      kws = (await res.json()).keywords || [];
    } catch (e) { return; }
    if (!kws.length) return;

    await log(`🔎 온디맨드 수집 ${kws.length}건: ${kws.join(', ')}`);
    let ok = 0, fail = 0, streak = 0;
    for (const kw of kws) {
      try {
        const payload = await collectKeyword(kw);
        if (!payload.products.length) throw new Error('상품 0건');
        await uploadKeyword(token, kw, payload);
        ok++; streak = 0;
        if (ok === 1) await clearBlocked();   // 값을 실제로 받았다 = 차단 풀림
        await log(`  ✅ [${kw}] 온디맨드 완료 (${payload.products.length}개)`);
      } catch (e) {
        if (String(e.message || '').startsWith('BLOCKED:')) {
          await markBlocked(e.message.slice(8) || '온디맨드 중 감지');
          break;
        }
        fail++; streak++;
        await log(`  ⚠️ [${kw}] 온디맨드 실패: ${e.message}`);
        if (streak >= 3) { await log('  🛑 연속 3회 실패 — 이번 회차 중단(차단 의심)'); break; }
      }
      await sleep(jitter());
    }
    if (ok === 0 && fail > 0) {
      await chrome.storage.local.set({ odBackoffUntil: Date.now() + 10 * 60 * 1000 });
      await log('  ⏸ 전량 실패 — 온디맨드 10분 백오프');
    }
  } finally {
    if (running === 'ondemand') running = false;   // 내 락만 해제
  }
}

// 알람 2개 — 브라우저가 켜져 있어야 동작한다(맥북 절전 해제 필수)
//  · daily   : 매시 확인, 03시 이후 오늘 수집이 없으면 실행(새벽에 꺼져 있었어도 켜지면 자동 만회)
//  · ondemand: 1분 주기, 낮에 들어온 새 키워드 요청 즉시 수집
function armAlarms() {
  // 'daily' 는 이름만 남았고 실제로는 **매시간 자기 몫**을 수집하는 알람이다(24시간 분산).
  // when 을 1분 뒤로 둬 브라우저를 켜자마자 그 시간대 몫을 이어받는다.
  chrome.alarms.create('daily', { periodInMinutes: 60, when: Date.now() + 60000 });
  // 30초 오프셋 — daily 와 만기가 매시 정각에 겹치지 않게(동시 발화 자체를 회피)
  chrome.alarms.create('ondemand', { periodInMinutes: 1, when: Date.now() + 30000 });
}
chrome.runtime.onInstalled.addListener(() => { armAlarms(); log('설치됨 — 03시 자동 수집 + 1분 주기 온디맨드 대기.'); });
chrome.runtime.onStartup.addListener(() => { armAlarms(); log('브라우저 시작 — 알람 재장전.'); });

/** 수집 회차 날짜 — 서버 _effective_date 와 동일 규칙.
 *  21시 이후 수집은 '다음 날 04:30 배치'용이므로 다음 날짜 회차로 센다. */
function cycleDate() {
  const d = new Date();
  // 오후·저녁 시작(runHour>=13)일 때만 '다음 날 배치분'으로 날짜를 넘긴다.
  // 새벽 1시 시작 체계에서는 수집이 자정을 안 넘으므로 회차 = 그냥 그 달력 날짜.
  if (CFG.runHour >= 13 && d.getHours() >= CFG.runHour) d.setDate(d.getDate() + 1);
  // 로컬(KST) 날짜 — toISOString(UTC)을 쓰면 자정 부근에 하루 어긋난다
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** 이번 '시간대' 식별자 — 같은 시간에 두 번 돌지 않게 하는 표식. */
function hourKey() {
  const d = new Date();
  return `${cycleDate()}:${String(d.getHours()).padStart(2, '0')}`;
}

chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name === 'ondemand') { runOnDemand(); return; }
  if (a.name !== 'daily') return;
  // 24시간 분산 — 매시간 자기 시간대 몫만 수집한다(시각 제한 없음).
  // 같은 시간대를 이미 돌았으면 건너뛴다(알람이 시간당 두 번 뜨는 경우 방어).
  const { state = {} } = await chrome.storage.local.get('state');
  if (state.finishedHour === hourKey()) return;
  runCollection(false);
});

chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.cmd === 'run') { runCollection(true); sendResponse({ ok: true }); }
  return true;
});
