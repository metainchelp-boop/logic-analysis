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
  keywordGapMs: 8000,    // 키워드 사이 추가 휴식 (여유 확대 — 총 소요 ~6시간)
  maxConsecutiveFail: 5, // 연속 실패가 이만큼이면 그날 수집 중단(차단 의심)
  runHour: 1,            // 매일 새벽 1시 시작 → 아침 7시경 완료 (운영자 확정 2026-08-04:
                         // '당일' 데이터여야 하고 완료 데드라인은 오전 10시. 서버 순위 기록은 08:00)
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

/** 네이버쇼핑 작업 탭 확보 — 없으면 백그라운드(비활성)·고정 탭으로 생성.
 *  사용자가 닫아도 다음 요청 때 자동 재생성된다. */
async function ensureWorkTab() {
  if (workTabId !== null) {
    try {
      const t = await chrome.tabs.get(workTabId);
      if (t && (t.url || '').includes('search.shopping.naver.com')) return workTabId;
    } catch (e) { /* 닫힘 — 재생성 */ }
  }
  const tab = await chrome.tabs.create({
    url: 'https://search.shopping.naver.com/search/all?query=' + encodeURIComponent('쇼핑'),
    active: false,    // 화면을 뺏지 않게 백그라운드로
    pinned: true,     // 실수로 닫기 어렵게 고정
  });
  workTabId = tab.id;
  await waitTabLoaded(workTabId);
  await sleep(2500);               // 페이지 초기 스크립트·쿠키 정착 대기
  await log('🪟 네이버쇼핑 작업 탭 준비 완료 (고정 탭 — 닫혀도 자동 재생성)');
  return workTabId;
}

/** 실제 페이지 컨텍스트에서 fetch — 사이트 자신의 요청과 동일(같은 출처·쿠키·Sec-Fetch) */
async function fetchViaPage(url) {
  const tabId = await ensureWorkTab();
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async (u) => {
      try {
        const r = await fetch(u, { credentials: 'include', headers: { 'Accept': 'application/json' } });
        if (!r.ok) return { err: 'HTTP ' + r.status };
        return { data: await r.json() };
      } catch (e) { return { err: String(e && e.message || e) }; }
    },
    args: [url],
  });
  const out = res && res.result;
  if (!out) throw new Error('페이지 주입 실패');
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
  const token = await getToken();
  if (!token) { await log('❌ 토큰이 없습니다. 팝업에서 먼저 저장하세요.'); running = false; return; }

  await setState({ running: true, startedAt: new Date().toISOString(), done: 0, failed: 0 });
  await log(manual ? '▶ 수동 수집 시작' : '▶ 자동 수집 시작');

  try {
    const res = await fetch(`${CFG.serverBase}/api/collector/keywords`, {
      headers: { 'X-Collector-Token': token },
    });
    if (!res.ok) throw new Error(`키워드 조회 실패 HTTP ${res.status}`);
    const { keywords = [], done: already = 0, total = 0 } = await res.json();
    await log(`대상 ${keywords.length}개 (전체 ${total} · 오늘 완료 ${already})`);
    if (!keywords.length) {
      // 이번 회차 수집할 게 없음(이미 완료) — 회차 완료로 기록해 매시 헛돌지 않게
      await setState({ running: false, finishedCycle: cycleDate(), current: '' });
      await log('이번 회차 수집 대상 없음 — 완료 처리');
      return;
    }
    await setState({ target: keywords.length });

    let done = 0, failed = 0, streak = 0;
    for (const kw of keywords) {
      try {
        const payload = await collectKeyword(kw);
        if (!payload.products.length) throw new Error('상품 0건');
        await uploadKeyword(token, kw, payload);
        done++; streak = 0;
        await setState({ done, failed, current: kw });
        if (done % 25 === 0) await log(`… ${done}/${keywords.length} 진행 중`);
      } catch (e) {
        failed++; streak++;
        await log(`⚠️ [${kw}] 실패: ${e.message}`);
        await setState({ done, failed, current: kw });
        if (streak >= CFG.maxConsecutiveFail) {
          await log(`🛑 연속 ${streak}회 실패 — 차단 의심으로 오늘 수집 중단`);
          break;
        }
        await sleep(jitter() * (1 + streak));   // 실패할수록 더 길게 쉰다
      }
      await sleep(jitter() + CFG.keywordGapMs);
    }
    await log(`✅ 수집 종료 — 성공 ${done} · 실패 ${failed}`);
    // 성공 0 = 사실상 실패한 날 — finishedAt 을 남기지 않아 매시 만회 로직이 재시도하게 한다
    if (done > 0) {
      await setState({ running: false, finishedAt: new Date().toISOString(),
                       finishedCycle: cycleDate(), done, failed, current: '' });
    } else {
      await setState({ running: false, done, failed, current: '' });
      await log('⚠️ 성공 0건 — 완료로 기록하지 않음(다음 시각에 자동 재시도)');
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
        await log(`  ✅ [${kw}] 온디맨드 완료 (${payload.products.length}개)`);
      } catch (e) {
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
  chrome.alarms.create('daily', { periodInMinutes: 60 });
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

chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name === 'ondemand') { runOnDemand(); return; }
  if (a.name !== 'daily') return;
  // 새벽 1시 이전(자정~0시대)엔 시작하지 않는다 — 1시 이후 매시 확인에서
  // 이번 회차 미완료면 실행(놓친 날 자동 만회·이어받기는 서버 done 필터가 보장).
  const now = new Date();
  if (CFG.runHour < 13 && now.getHours() < CFG.runHour) return;
  const { state = {} } = await chrome.storage.local.get('state');
  if (state.finishedCycle === cycleDate()) return;   // 이번 회차 이미 완료
  runCollection(false);
});

chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.cmd === 'run') { runCollection(true); sendResponse({ ok: true }); }
  return true;
});
