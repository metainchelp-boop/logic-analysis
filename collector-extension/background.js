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
  maxGapMs: 3000,        // 요청 간 최대 간격 (이 사이 랜덤)
  keywordGapMs: 4000,    // 키워드 사이 추가 휴식
  maxConsecutiveFail: 5, // 연속 실패가 이만큼이면 그날 수집 중단(차단 의심)
  runHour: 3,            // 매일 03시에 자동 시작 (서버 배치 04:30보다 먼저)
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

/** 네이버 검색 결과 1페이지 — 브라우저(실제 IP·헤더)로 요청 */
async function fetchPage(keyword, pagingIndex) {
  const url = 'https://search.shopping.naver.com/api/search/all'
    + `?sort=rel&pagingIndex=${pagingIndex}&pagingSize=${CFG.pageSize}`
    + `&query=${encodeURIComponent(keyword)}`;
  const res = await fetch(url, {
    headers: { 'Accept': 'application/json', 'Referer': 'https://search.shopping.naver.com/' },
    credentials: 'omit',   // 개인 네이버 계정과 엮지 않는다(계정 정지 위험 차단)
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
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
    await setState({ running: false, finishedAt: new Date().toISOString(), done, failed, current: '' });
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

chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name === 'ondemand') { runOnDemand(); return; }
  if (a.name !== 'daily') return;
  const now = new Date();
  // 03시 정각을 놓쳤어도(새벽에 크롬이 꺼져 있었다면) 그날 처음 켜진 시점에 만회한다.
  // 요청 속도는 시간대와 무관하게 사람 수준이라 낮에 돌아도 차단 위험은 같다.
  if (now.getHours() < CFG.runHour) return;
  const { state = {} } = await chrome.storage.local.get('state');
  const today = now.toISOString().slice(0, 10);
  if ((state.finishedAt || '').slice(0, 10) === today) return;   // 오늘 이미 완료
  runCollection(false);
});

chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.cmd === 'run') { runCollection(true); sendResponse({ ok: true }); }
  return true;
});
