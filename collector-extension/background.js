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
  // ⚠️ 2026-08-06 플랜 B — API 호출을 폐기하고 **사람이 보는 검색 페이지**를 연다.
  //    그래서 한 페이지 개수도 화면 기본값(40)에 맞춘다. 300위 = 8페이지.
  //    종전 80(API 상한)은 사람이 안 만드는 모양이라, 모양을 맞추는 쪽을 택했다.
  //    ⇒ 페이지 이동 횟수가 4 → 8 로 늘어나므로 아래 간격으로 시간당 총량을 맞춘다.
  //      (페이지 이동은 그 자체로 ~3초가 걸려 API 호출보다 원래 느리다)
  pageSize: 40,          // 한 페이지 상품 수 (실제 화면과 동일)
  maxRank: 300,          // 300위까지 — 실제 받은 개수로 누적해 판단(고정 페이지 수 아님)
  maxPages: 10,          // 안전 상한(빈 페이지·무한 루프 방지)
  readTries: 12,         // 페이지 판독 재시도 횟수(값이 나올 때까지)
  readGapMs: 800,        // 되읽기 간격 — 12×0.8초 ≈ 10초까지 기다린다
  minGapMs: 1200,        // 페이지 사이 최소 간격
  maxGapMs: 3000,        // 페이지 사이 최대 간격 (이 사이 랜덤)
  // ── 24시간 분산 (2026-08-05 운영자 확정) ─────────────────────────────
  // 종전: 새벽 1시부터 6시간에 954개를 몰아침 → 분당 10.6회 → 네이버가 IP 차단
  //       (「쇼핑 서비스 접속이 일시적으로 제한되었습니다」 — 사유에 '짧은 시간 내에
  //        너무 많은 요청이 이루어진 IP' 명시).
  // 지금: 서버가 키워드를 24개 시간대로 나눠 주고, 확장은 **매시간 자기 몫만** 한다.
  //       시간당 ~40개 → 분당 2.7회. 맥북이 24시간 켜져 있으니 창을 넓게 쓰는 게 이득.
  keywordGapMs: 30000,   // 키워드 사이 휴식 30초 (페이지가 8장으로 늘어난 만큼 조정)
  // ⚠️ 온디맨드도 같은 규칙을 지켜야 한다(2026-08-11 실측 교훈).
  //    종전 온디맨드는 키워드 사이를 jitter(1.2~3초)만 쉬어서 10건×8페이지를 몰아쳤다
  //    = 분당 ~12회. 24시간 분산 설계 목표(분당 2.7회)의 4배 이상이라, 밀린 큐가
  //    쌓여 있던 8/8 에는 이게 하루 종일 돌며 시간대 슬롯 수집을 굶기기까지 했다.
  //    → 간격을 주고, 시간당 처리량에 상한을 둔다(직원이 방금 요청한 건은 여전히
  //      몇 분 안에 처리되지만, 큐가 밀려도 시간당 총량이 설계치를 못 넘는다).
  onDemandGapMs: 20000,  // 온디맨드 키워드 사이 휴식 20초
  onDemandHourCap: 12,   // 온디맨드는 시간당 최대 12키워드까지만(나머지는 다음 시간대)
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

/* ── 수집 경로 = 검색 페이지 이동 (2026-08-06 플랜 B) ──
 * 이력: ① 서비스워커에서 직접 fetch → 418 ② 페이지 안에서 fetch(ISOLATED) → 418
 *      ③ 페이지 안에서 fetch(MAIN) → 418. 즉 **`/api/search/all` 을 부르는 순간 막힌다.**
 *      우리 쪽 변수를 하나씩 바꿔 좁히려던 시도는 시도할 때마다 차단이 깊어져 실패했다.
 * → API 호출을 폐기하고, 작업 탭의 **주소를 검색 페이지로 옮겨 다니며** 화면에 이미
 *   그려진 데이터(__NEXT_DATA__)를 읽는다. 요청 1건 = 사람의 페이지 이동 1번.
 *   플레이스 추적기가 __APOLLO_STATE__ 로 매일 같은 구조로 성공하고 있다. */
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

/** 페이지 안에서 실행 — 화면에 이미 그려진 검색 결과 데이터를 그대로 읽어온다.
 *
 *  ⚠️ 이 함수는 문자열로 직렬화돼 페이지 세계(MAIN)로 주입된다.
 *     바깥 변수를 참조하면 안 되고, 반환값은 JSON 으로 옮겨진다.
 *
 *  판독 규칙 — 경로를 고정하지 않는다.
 *     `props.pageProps.initialState.products.list` 같은 경로는 네이버가 자주 바꾼다.
 *     그래서 __NEXT_DATA__ 전체를 훑어 **'상품처럼 생긴 객체들의 배열'**(productTitle·
 *     mallName 등을 가진) 중 가장 긴 것을 고른다. 구조가 바뀌어도 계속 읽힌다.
 *     플레이스 추적기가 __APOLLO_STATE__ 를 같은 방식으로 판독해 매일 성공 중이다. */
function pageExtract() {
  function looksProduct(o) {
    if (!o || typeof o !== 'object') return false;
    var hasTitle = typeof o.productTitle === 'string' || typeof o.productName === 'string';
    if (!hasTitle) return false;
    return o.mallName !== undefined || o.nvMid !== undefined || o.id !== undefined
        || o.mallProductUrl !== undefined || o.crUrl !== undefined;
  }
  function unwrap(el) {
    if (looksProduct(el)) return el;
    if (el && typeof el === 'object' && looksProduct(el.item)) return el.item;
    return null;
  }
  var nd = null;
  try { nd = window.__NEXT_DATA__ || null; } catch (e) { nd = null; }
  var href = '';
  try { href = String(location.href); } catch (e) { href = ''; }
  var title = '';
  try { title = String(document.title || '').slice(0, 120); } catch (e) { title = ''; }
  var body = '';
  try { body = String((document.body && document.body.innerText) || '').slice(0, 3000); } catch (e) { body = ''; }

  // ⚠️ 순서가 핵심 — **데이터부터 찾고, 못 찾았을 때만 차단을 의심한다.**
  //    (2026-08-11 실사고: 차단 문구 검사를 먼저 해서, 상품 데이터가 바로 옆에 있는
  //     정상 페이지도 낱말 하나만 스치면 차단으로 단정했다. 상품을 실제로 읽어냈다면
  //     네이버가 우리에게 필요한 걸 내준 것이므로 그건 차단일 수 없다.)
  var best = null, total = 0;
  var seen = new Set();
  var stack = [nd], guard = 0;
  while (stack.length && guard++ < 300000) {
    var cur = stack.pop();
    if (!cur || typeof cur !== 'object') continue;
    if (seen.has(cur)) continue;
    seen.add(cur);
    if (Array.isArray(cur)) {
      var got = [];
      for (var i = 0; i < cur.length; i++) {
        var u = unwrap(cur[i]);
        if (u) got.push(u);
      }
      // 절반 이상이 상품이어야 '상품 목록'으로 인정(광고·배너가 섞인 배열도 통과)
      if (got.length && got.length * 2 >= cur.length) {
        if (!best || got.length > best.length) best = got;
      }
      for (var j = 0; j < cur.length; j++) {
        if (cur[j] && typeof cur[j] === 'object') stack.push(cur[j]);
      }
    } else {
      for (var k in cur) {
        var v = cur[k];
        if (typeof v === 'number' && v > total && (k === 'total' || k === 'totalCount' || k === 'productCount')) total = v;
        if (v && typeof v === 'object') stack.push(v);
      }
    }
  }
  // 상품을 읽어냈으면 무조건 성공 — 차단 검사조차 하지 않는다
  if (best && best.length) return { total: total, list: best.slice(0, 200), href: href };

  // 여기부터는 '못 읽은' 경우. 이제서야 차단인지 본다.
  var blocked = /일시적으로 제한|자동입력 방지|비정상적인 접근|접근이 차단/.test(body);
  if (blocked) return { err: 'BLOCK_TEXT', href: href, title: title, body: body.slice(0, 300) };
  return { err: nd ? 'NO_LIST' : 'NO_NEXT_DATA', href: href, title: title, body: body.slice(0, 300) };
}

/** 탭이 목표 주소로 이동을 끝낼 때까지 대기 */
function waitNavigated(tabId, needle) {
  return new Promise((resolve) => {
    const started = Date.now();
    const iv = setInterval(async () => {
      try {
        const t = await chrome.tabs.get(tabId);
        const u = String(t.url || '');
        // 캡차로 튕겼으면 더 기다릴 것 없이 즉시 반환(호출부가 판정한다)
        if (u && !u.includes('search.shopping.naver.com')) { clearInterval(iv); resolve(); return; }
        // 주소가 목표와 맞고 로딩이 끝났으면 바로 진행.
        // ⚠️ 네이버가 주소를 정규화해 needle 이 안 보일 수도 있다 — 그때 25초를 통째로
        //    기다리면 회차 예산(50분)이 날아간다. 로딩만 끝났으면 6초 뒤 진행한다.
        if (t.status === 'complete' && (u.includes(needle) || Date.now() - started > 6000)) {
          clearInterval(iv); resolve(); return;
        }
      } catch (e) { clearInterval(iv); resolve(); return; }
      if (Date.now() - started > 25000) { clearInterval(iv); resolve(); }
    }, 400);
  });
}

/** 네이버 검색 결과 1페이지 — **실제 검색 페이지를 열어서** 읽는다(플랜 B, 2026-08-06)
 *
 *  왜 바꿨나: 종전엔 `/api/search/all` 을 (페이지 안에서라도) 직접 불렀다. 8/4 이후
 *  이 경로는 418 로 막혔고, 파라미터 모양·MAIN 세계 실행 등 우리 쪽 변수를 바꿔가며
 *  좁히려던 시도가 전부 실패했다(찔러볼 때마다 차단이 깊어지기만 했다).
 *  → API 호출을 **완전히 폐기**하고, 사람이 보는 검색 페이지를 그대로 열어
 *    이미 렌더된 데이터(__NEXT_DATA__)를 읽는다. 요청 한 건 = 사람의 페이지 이동 한 번.
 *    플레이스 추적기가 매일 이 구조로 성공하고 있고, 실측(2026-08-06)에서
 *    pagingIndex=2 페이지에 40개 상품과 필요한 필드가 전부 들어 있음을 확인했다. */
async function fetchPage(keyword, pagingIndex) {
  const q = encodeURIComponent(keyword);
  // 사람이 페이지를 넘길 때와 같은 주소(pagingSize 도 화면 기본값 40 그대로)
  const url = 'https://search.shopping.naver.com/search/all'
    + `?query=${q}&origQuery=${q}&adQuery=${q}`
    + `&pagingIndex=${pagingIndex}&pagingSize=${CFG.pageSize}`
    + '&productSet=total&viewType=list&sort=rel&iq=&eq=&xq=';

  const tabId = await ensureWorkTab();
  await chrome.tabs.update(tabId, { url });
  await waitNavigated(tabId, `pagingIndex=${pagingIndex}`);

  // ⚠️ 고정 시간만 기다리고 한 번 읽던 것을 **값이 나올 때까지 되읽기**로 바꾼다
  //    (2026-08-11 실사고: 정상 페이지를 3초 만에 읽어 '데이터 없음' → 차단으로 오판 →
  //     60개 회차 전멸 + 6시간 정지. 서버 통계의 '5개·9개 수집' 키워드도 같은 원인).
  //    기다리는 대상이 '시간'이 아니라 '데이터'라, 페이지가 느린 날에도 성립한다.
  let out = null, lastErr = '';
  for (let attempt = 0; attempt < CFG.readTries; attempt++) {
    let cur;
    try { cur = await chrome.tabs.get(tabId); } catch (e) { throw new Error('작업 탭이 사라졌습니다'); }
    // 주소가 검색 도메인을 벗어났으면 그건 진짜 차단(캡차·로그인 유도)
    if (isBlockedUrl(cur && cur.url)) throw new Error('BLOCKED:' + cur.url);

    const [res] = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: pageExtract });
    out = res && res.result;
    if (out && !out.err) return { total: out.total || 0, list: out.list || [] };
    // 차단 '문구'를 실제로 본 경우에만 차단으로 단정한다.
    // ⚠️ 이때도 무엇을 봤는지 반드시 남긴다 — 종전엔 차단 분기가 증거를 안 남겨
    //    팝업 진단칸이 정작 필요할 때 비어 있었다(2026-08-11).
    if (out && out.err === 'BLOCK_TEXT') {
      chrome.storage.local.set({
        readFail: { keyword, pagingIndex, at: new Date().toISOString(), err: 'BLOCK_TEXT(차단 문구 확인)',
                    title: out.title || '', href: out.href || '', body: out.body || '' },
      });
      throw new Error(`BLOCKED:${out.title || out.href}`);
    }
    lastErr = (out && out.err) || '주입 실패';
    await sleep(CFG.readGapMs);
  }

  // 여기까지 왔으면 '차단'이 아니라 '판독 실패'다 — 6시간 정지시키지 않고 다음 회차에 재시도한다.
  // 무엇을 봤는지 남겨 둬야 다음에 사람 손 안 빌리고 원인을 가른다.
  chrome.storage.local.set({
    readFail: { keyword, pagingIndex, at: new Date().toISOString(),
                err: lastErr, title: (out && out.title) || '', href: (out && out.href) || '',
                body: (out && out.body) || '' },
  });
  throw new Error(`판독 실패(${lastErr}) — 차단 아님, 다음 회차 재시도`);
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

/** 키워드 1건을 300위까지 수집
 *
 *  ⚠️ 순위는 **실제로 받은 개수로 누적**한다(종전엔 `(페이지-1)×pageSize+1` 로 계산).
 *     페이지가 요청한 개수를 그대로 주지 않는 경우(광고 제외·마지막 페이지 등)
 *     고정 계산은 순위를 통째로 어긋나게 만든다. 누적이면 어떤 경우에도 맞다. */
async function collectKeyword(keyword) {
  const products = [];
  let total = 0;
  const pages = CFG.maxPages;
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
    for (let idx = 0; idx < list.length; idx++) {
      const rank = products.length + 1;
      if (rank > CFG.maxRank) break;
      const mapped = toProduct(list[idx], rank);
      // ⚠️ 스토어명(mallName)이 13.3% 비어 있다(2026-08-11 서버 실측). 판독 원천이
      //    API 응답 → 페이지 데이터로 바뀌면서 일부 상품(가격비교 추정)이 다른 필드에
      //    스토어명을 싣는 것으로 보이는데, **필드 이름을 추측해서 붙이면 안 된다**
      //    (틀린 값이 들어가면 순위 매칭 보조 축이 오염된다).
      //    → 값이 빈 상품의 '원본'을 하나 남겨 팝업에서 실제 키 이름을 확인한 뒤 붙인다.
      if (!mapped.mallName) {
        chrome.storage.local.get('rawSampleNoMall').then((o) => {
          if (!o.rawSampleNoMall) {
            chrome.storage.local.set({
              rawSampleNoMall: { keyword, rank, at: new Date().toISOString(), item: list[idx] },
            });
          }
        });
      }
      products.push(mapped);
    }
    if (products.length >= CFG.maxRank) break;   // 목표 깊이 도달
    if (list.length < CFG.pageSize) break;       // 마지막 페이지
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
/* 시간대 슬롯 수집이 대기 중임을 온디맨드에게 알리는 깃발.
 * 온디맨드가 락을 계속 쥐면 시간대 경로가 굶는다(2026-08-08 실사고). */
let dailyDue = false;

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

    // 시간당 상한 — 밀린 큐가 아무리 커도 이 시간대에 정해진 양만 한다.
    // (남은 것은 서버 큐에 그대로 있으니 다음 시간대에 이어서 처리된다)
    const hourTag = hourKey();
    const { odHour = {} } = await chrome.storage.local.get('odHour');
    const usedThisHour = odHour.hour === hourTag ? Number(odHour.n || 0) : 0;
    const room = CFG.onDemandHourCap - usedThisHour;
    if (room <= 0) return;

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
    const skipped = Math.max(0, kws.length - room);
    if (skipped) kws = kws.slice(0, room);

    await log(`🔎 온디맨드 수집 ${kws.length}건: ${kws.join(', ')}`
      + (skipped ? ` (시간당 상한 — ${skipped}건은 다음 시간대로)` : ''));
    let ok = 0, fail = 0, streak = 0, done = 0;
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
      // 시도한 건 성공·실패 상관없이 시간당 상한에 센다(실패도 요청은 나갔으므로)
      done++;
      await chrome.storage.local.set({ odHour: { hour: hourTag, n: usedThisHour + done } });
      // 시간대 슬롯 수집이 대기 중이면 여기서 양보한다 — 온디맨드가 락을 계속 쥐고 있어
      // 시간대 경로가 하루 종일 굶던 사고(2026-08-08)를 막는다.
      if (dailyDue) { await log('  ↩ 시간대 수집 차례 — 온디맨드 양보'); break; }
      await sleep(jitter() + CFG.onDemandGapMs);
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
  if (running === 'ondemand') {
    // 온디맨드가 돌고 있으면 한 건 끝나는 대로 비켜달라고 표시하고, 비면 이어받는다.
    // (종전엔 그냥 return 이라 온디맨드가 계속 도는 동안 시간대 수집이 영영 안 돌았다)
    dailyDue = true;
    await log('⏳ 시간대 수집 대기 — 온디맨드가 끝나는 대로 시작합니다');
    for (let i = 0; i < 60 && running; i++) await sleep(5000);
    dailyDue = false;
  }
  runCollection(false);
});

chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.cmd === 'run') { runCollection(true); sendResponse({ ok: true }); }
  return true;
});
