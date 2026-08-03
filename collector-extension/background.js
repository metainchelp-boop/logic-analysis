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
  const token = await getToken();
  if (!token) { await log('❌ 토큰이 없습니다. 팝업에서 먼저 저장하세요.'); return; }

  running = true;
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
    running = false;
  }
}

// 매일 03시 자동 실행 — 브라우저가 켜져 있어야 동작한다(PC 절전 해제 필수)
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('daily', { periodInMinutes: 60 });
  log('설치됨 — 매시 정각에 03시인지 확인해 자동 수집합니다.');
});
chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name !== 'daily') return;
  const now = new Date();
  if (now.getHours() !== CFG.runHour) return;
  const { state = {} } = await chrome.storage.local.get('state');
  const today = now.toISOString().slice(0, 10);
  if ((state.finishedAt || '').slice(0, 10) === today) return;   // 오늘 이미 완료
  runCollection(false);
});

chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.cmd === 'run') { runCollection(true); sendResponse({ ok: true }); }
  return true;
});
