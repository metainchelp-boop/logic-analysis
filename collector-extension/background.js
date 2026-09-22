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

// ⭐ 순위 규칙은 rank_rules.js 한 곳에만 있다(신고 #253 후속, 2026-09-02) —
//    chrome 의존이 없어 node 회귀 테스트가 같은 파일을 검사한다.
importScripts('rank_rules.js');
// ⚠️ rank_rules.js 는 전역에 RankRules 객체 하나만 내놓는다(IIFE) — 개별 함수 이름을
//    여기서 다시 선언하거나 전역으로 받지 말 것. 'already been declared' 워커 등록
//    사망이 2026-09-02 맥미니 적용에서 실제로 두 번 났다. 호출은 RR.takeOrganic 식으로.
const RR = globalThis.RankRules;

const CFG = {
  serverBase: 'https://logic.metainc.co.kr',
  // ⚠️ 2026-08-06 플랜 B — API 호출을 폐기하고 **사람이 보는 검색 페이지**를 연다.
  //    그래서 한 페이지 개수도 화면 기본값(40)에 맞춘다. 300위 = 8페이지.
  //    종전 80(API 상한)은 사람이 안 만드는 모양이라, 모양을 맞추는 쪽을 택했다.
  //    ⇒ 페이지 이동 횟수가 4 → 8 로 늘어나므로 아래 간격으로 시간당 총량을 맞춘다.
  //      (페이지 이동은 그 자체로 ~3초가 걸려 API 호출보다 원래 느리다)
  // pagingSize=80 은 화면의 「80개씩 보기」 옵션과 같은 모양이라 사람 범위 안이다.
  //    300위 = 8페이지 → 4페이지로 **이동 횟수 절반**(2026-08-11, 총량이 차단 원인으로
  //    확정된 뒤의 감축). 페이지가 80을 안 받아주고 40씩만 그려도 아래 수집 루프가
  //    '실제 받은 개수 누적'이라 그대로 8페이지로 자동 적응한다(어느 쪽이든 순위 무손상).
  // ⚠️ 2026-09-12 — **주소에 pagingSize 를 붙이지 않는다.** 화면 기본값(40개)을 그대로 쓴다.
  //    8/11 에 페이지 이동을 줄이려고 40→80 으로 올렸는데, 그 값이 사람 주소에는 잘 안 붙는
  //    모양이라 **자동화 표식**이 됐을 가능성이 크다(9/12 대표 A/B: 짧은 주소는 캡차를 주는데
  //    pagingSize 가 붙은 긴 주소는 캡차조차 없이 즉시 차단).
  //    ⇒ 깊이는 **페이지 수**로 벌고, 그 페이지 이동은 아래 「클릭으로 넘기기」가 감당한다.
  pageSize: 40,          // 화면 기본값 — 주소에는 안 붙이고, 마지막 페이지 판정에만 쓴다
  // ⚠️ 2026-09-18 대표 확정 — **400 → 300**. 실측(진단 #301)상 잃는 것이 0 이다:
  //    최근 14일 수집분에서 찾은 목표 462건 중 **301위 밖에서 발견된 것 0건**(401위 밖도 0).
  //    요청은 11장 → 8장으로 27% 줄어 418 위험도 같이 준다.
  //    ⚠️ 화면·보고서의 「300위 밖」 표기가 **비로소 사실과 맞는다**(그동안 400까지 보면서
  //       300위 밖이라 적고 있었다).
  maxRank: 300,          // 300위까지 (대표 확정 2026-09-18) — 실제 받은 개수로 누적해 판단
  // ⚠️ 광고를 순위에서 빼면(2026-08-12) 같은 4페이지에서 모이는 '오가닉' 개수가 300에
  //    못 미쳐, 종전 조건(300개 채울 때까지)만으로는 루프가 5페이지째로 넘어간다
  //    = 페이지 이동 +25%. 지금 이 IP 는 하루 986개 중 205개밖에 못 도는 상태라
  //    총량을 늘리는 선택은 할 수 없다. 실측(2026-08-12, 오늘 수집분 205키워드 전수):
  //      · 지금 저장되는 300개 중 광고가 중앙값 23개 → 실질 오가닉 ≈ 277
  //      · 광고를 빼고 같은 4페이지를 돌면 오가닉 ≈ 274~295
  //    ⇒ 깊이는 사실상 그대로다. 그래서 페이지 수를 4로 못박아 총량을 유지한다.
  //    수집 여력이 늘면 이 값만 5로 올리면 오가닉 300위가 채워진다.
  // ⚠️ 400위 = 40개 × 11장. 종전에는 「페이지를 늘리면 위험도 같이 는다」라 4장으로 못박았는데,
  //    이제 2장째부터는 **주소창 이동이 아니라 화면 안 클릭**이라 그 사슬이 끊겼다.
  //    키워드당 주소창 이동은 **1회**다(종전 4회). 깊이를 더 원하면 이 값만 올리면 된다.
  // ⚠️ 2026-09-18 — 11 → 8. 실측상 목표를 다 찾은 364개 키워드 **전부가 8페이지 안**에서
  //    끝났다(중앙값 1 · 최대 8). 40개 × 8 = 320 → 광고 제외 ≈ 300위.
  pagesPerKeyword: 8,    // 키워드당 페이지 수 상한 (40개 × 8 = 320 → 광고 제외 ≈ 300위)
  maxPages: 8,           // 안전 상한(빈 페이지·무한 루프 방지)
  readTries: 12,         // 페이지 판독 재시도 횟수(값이 나올 때까지)
  // v1.11.6 — 2페이지부터는 **내용이 바뀔 때까지** 더 오래 기다린다(36×0.8초 ≈ 29초).
  //   9/15 21:30 실측(갈비살 p2): 클릭도 되고 페이지네이션도 2가 현재인데 10초 안에 데이터가 안 바뀌어
  //   멈췄다. 같은 날 21:22(갈릭버터새우 p2)는 10초 안에 바뀌었다 — 회선(VPN) 지연이 오락가락한다.
  readTriesPaged: 36,
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
  // ── 여러 대로 나눠 돌리기 (2026-08-27 대표 지시) ──────────────────────
  // 기본값은 1대(workerCount 1) = 전량을 혼자 맡는다. 지금 도는 기계는 안 바뀐다.
  // 2대로 늘릴 때만 팝업에서 「몇 번 기계 / 총 몇 대」를 지정한다.
  // ⚠️ 순위 목록만 나누면 안 된다 — 밀린 요청 큐도 같은 규칙으로 나눠야 한다.
  //    두 대가 같은 큐를 보면 5회 재시도 한도를 2.5회 만에 태운다.
  workerNo: 1,           // 이 기계가 몇 번인가 (1부터)
  workerCount: 1,        // 전부 몇 대인가
};

const _rawSleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** ⭐ 잠들지 않고 쉬는 대기 (2026-08-28 — 수집이 시간당 2~3개로 굶던 원인).
 *
 * 크롬 확장의 배경 스크립트(서비스 워커)는 **30초 동안 확장 API 를 한 번도 부르지
 * 않으면 브라우저가 꺼 버린다.** 그냥 setTimeout 으로 30초를 쉬면 그 사이 아무
 * API 도 안 부르므로 워커가 죽고, **회차가 첫 키워드에서 통째로 끊긴다.**
 *
 * 실측(2026-08-28)이 이걸 그대로 보여줬다:
 *   · 온디맨드 간격 20초 → 30초 미만이라 살아남는다 → 시간당 상한 12건을 다 채웠다
 *   · 시간대 몫 간격 30초 → 죽는다              → 시간당 2~3개만 하고 끊겼다
 *   그 결과 하루 345개 중 288개가 밀린 큐 몫이고 순위 추적은 57개뿐이었다.
 *
 * 그래서 긴 대기는 잘게 쪼개고 사이사이 확장 API(storage 읽기)를 한 번씩 부른다.
 * 그 호출이 유휴 타이머를 되돌려 워커가 깨어 있는다.
 *
 * ⚠️ 이 함수를 다시 단순 setTimeout 으로 되돌리지 말 것. 간격을 20초 위로 올리는
 *    순간 같은 사고가 조용히 재발한다(에러도 로그도 안 남는다 — 그냥 안 한다).
 */
const KEEPALIVE_TICK_MS = 15000;   // 30초 한도의 절반 — 여유를 두고 깨운다
async function sleep(ms) {
  let left = Number(ms) || 0;
  while (left > 0) {
    const step = Math.min(left, KEEPALIVE_TICK_MS);
    await _rawSleep(step);
    left -= step;
    if (left > 0) {
      // 확장 API 호출 = 유휴 타이머 리셋. 값은 쓰지 않는다(깨우는 것이 목적).
      try { await chrome.storage.local.get('__keepalive__'); } catch (e) { /* 무시 */ }
    }
  }
}

/** 팝업에서 지정한 기계 번호를 URL 파라미터로 만든다(1대면 빈 문자열 = 종전 요청 그대로). */
async function workerParams() {
  try {
    const { workerNo = CFG.workerNo, workerCount = CFG.workerCount } =
      await chrome.storage.local.get(['workerNo', 'workerCount']);
    const wc = Math.max(1, parseInt(workerCount, 10) || 1);
    if (wc <= 1) return '';
    const no = Math.min(wc, Math.max(1, parseInt(workerNo, 10) || 1));
    return `&worker=${no - 1}&workers=${wc}`;   // 서버는 0부터 센다
  } catch (e) {
    return '';
  }
}
const jitter = () => CFG.minGapMs + Math.random() * (CFG.maxGapMs - CFG.minGapMs);

async function getToken() {
  const { token } = await chrome.storage.local.get('token');
  return token || '';
}

async function setState(patch) {
  const cur = (await chrome.storage.local.get('state')).state || {};
  await chrome.storage.local.set({ state: { ...cur, ...patch, updatedAt: new Date().toISOString() } });
}

const LOG_KEEP = 200;

/** 막힌 근거를 **서버로도** 보낸다 (2026-09-12 신설).
 *
 * ⚠️ 왜 필요한가 — 2026-09-09~11 에 수집이 멈췄을 때, 네이버가 무엇을 돌려줬는지가
 *    **이 기계 팝업에만** 남아 있었다. 사람이 그 칸을 열어 읽어 주기 전에는
 *    「IP 차단」인지 「확장 감지」인지 가릴 수 없었고, 그렇게 사흘을 썼다.
 *    ⇒ 이제 막히면 확장이 스스로 이유를 서버에 남긴다.
 * ⚠️ **절대 예외를 밖으로 내지 않는다.** 보고가 수집을 넘어뜨리면 본말전도다.
 * ⚠️ 개인정보를 담지 않는다 — 우리가 만든 검색 주소·페이지 제목·본문 앞 500자뿐.
 */
async function reportBlocked(info) {
  try {
    const token = await getToken();
    if (!token) return;
    let ver = '';
    try { ver = chrome.runtime.getManifest().version; } catch (e) { /* 무시 */ }
    await fetch(`${CFG.serverBase}/api/collector/blocked`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Collector-Token': token },
      body: JSON.stringify({
        keyword: info.keyword || '',
        pagingIndex: info.pagingIndex || 0,
        err: info.err || '',
        title: (info.title || '').slice(0, 200),
        href: (info.href || '').slice(0, 500),
        body: (info.body || '').slice(0, 500),
        extVersion: ver,
        note: info.note || '',
      }),
    });
  } catch (e) { /* 보고 실패는 무시한다 — 수집이 우선이다 */ }
}

/** 로그 한 줄 남기기.
 *
 *  ⭐ 같은 문장이 연달아 오면 **줄을 늘리지 않고 맨 윗줄을 갱신**한다(2026-09-09).
 *  왜 — 캡차로 쉬는 동안 `daily` 알람(1분 주기, :781)이 매분 차단 안내를 한 줄씩 찍었다.
 *       보관은 200줄이라 **1분당 1줄 × 200 = 3.3시간**이면 그 전 기록이 통째로 밀린다.
 *       2026-09-09 에 실제로 그 일이 났다 — 14:08 캡차 → 18:00 조회 시점(3.9시간 뒤)에
 *       로그가 전부 같은 줄이었고, **그날 오전에 무엇이 왜 멈췄는지 증거가 사라져 원인을 못 갈랐다.**
 *  ⚠️ 안내를 없애지 않는다 — 없애면 「쉬는 중」인 것 자체가 로그에서 안 보인다.
 *     대신 **한 줄로 접고 (×N) 과 최신 시각**을 보여 준다. 그 아래 기록이 살아남는 것이 핵심이다.
 *  ⚠️ 접히는 것은 **바로 앞줄과 완전히 같은 문장**뿐이다. 키워드·건수가 들어간 줄은
 *     문장이 서로 달라 접히지 않는다(진행 기록은 종전 그대로 쌓인다).
 */
async function log(line) {
  const { logs = [] } = await chrome.storage.local.get('logs');
  const stamp = `[${new Date().toLocaleTimeString('ko-KR')}]`;
  const prev = logs[0] || '';
  const prevBody = prev.replace(/^\[[^\]]*\]\s*/, '').replace(/\s*\(×\d+\)$/, '');
  if (logs.length && prevBody === line) {
    const m = /\(×(\d+)\)$/.exec(prev);
    logs[0] = `${stamp} ${line} (×${m ? Number(m[1]) + 1 : 2})`;
  } else {
    logs.unshift(`${stamp} ${line}`);
  }
  await chrome.storage.local.set({ logs: logs.slice(0, LOG_KEEP) });
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

/** v1.17.1 — 사람 경로로 들어가느라 **일부러** 거치는 곳.
 *
 * 🔴 2026-09-16 15:07 실사고 — 이 목록이 없어서 `portalEntry` 가 연 **네이버 첫 화면과
 *    통합검색**을 「캡차로 튕겼다」로 오판하고 6시간 쉼에 들어갔다.
 *    서버 보고: `REDIRECT(검색 도메인 이탈) · title=과실주 : 네이버 검색`.
 *    **네이버는 아무것도 막지 않았다. 우리 가드가 우리 발을 건 것이다.**
 * ⚠️ 새 진입 경로를 더할 때는 **이 목록을 먼저 고칠 것.** 안 그러면 잘 돌던 회차가
 *    「차단」으로 기록돼 6시간이 날아가고, 그 기록이 다음 진단을 통째로 오염시킨다.
 */
const ENTRY_HOSTS = ['search.shopping.naver.com', 'www.naver.com', 'search.naver.com'];
function onEntryHost(url) {
  const u = String(url || '');
  return ENTRY_HOSTS.some((h) => u.includes(h));
}

/** 캡차·차단 페이지로 넘어갔는지 — 우리가 쓰는 화면을 벗어났으면 차단으로 본다. */
function isBlockedUrl(url) {
  const u = String(url || '');
  if (!u) return false;
  if (onEntryHost(u)) return false;
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
  // ⭐ 복귀할 때 같은 속도로 돌아가면 또 막힌다 — 하루 동안 절반 속도로 간다(2026-08-28).
  //    사람이 아무것도 안 해도 스스로 안전한 속도를 찾아간다. 하루 지나면 자동 원복.
  const _slowUntil = Date.now() + SLOW_WINDOW_MS;
  await chrome.storage.local.set({ [SLOW_KEY]: _slowUntil });
  await setState({ slowUntil: _slowUntil });      // 팝업이 「안전 속도」 표시를 읽는다
  await log(`🧱 네이버 캡차·보안 확인 페이지 확인 — ${reason}. 6시간 쉬었다 재개합니다.`);
  await log('   재개 뒤 하루 동안은 절반 속도로 돌립니다(또 막히지 않도록).');
  await log('   해제하려면: 크롬에서 네이버쇼핑을 직접 열어 캡차를 한 번 풀어주세요.');
  // 쌓인 작업 탭을 닫아 둔다 — 열어둘수록 봇 판정이 깊어지고 화면도 지저분해진다.
  await closeAllWorkTabs();
}

const SLOW_KEY = 'slowUntil';
const SLOW_WINDOW_MS = 24 * 60 * 60 * 1000;   // 한 번 막히면 하루 동안 느리게 간다

/** 지금 '느리게 가기' 상태인가 — 캡차를 만난 뒤 하루 동안 켜진다. */
async function isSlow() {
  try {
    const o = await chrome.storage.local.get(SLOW_KEY);
    return Number(o[SLOW_KEY] || 0) > Date.now();
  } catch (e) { return false; }
}

/** 이번에 쓸 키워드 사이 휴식(ms). 느리게 가기 상태면 2배. */
async function gapFor(base) {
  return (await isSlow()) ? base * 2 : base;
}

// ⏸ 이 기계에서 사람이 누른 '일시정지'(v1.20.0). 화면(서버) 스위치와 별개로
//    수집기 앞에서 즉시 멈추기 위한 로컬 스위치다 — 이 기계에서만 적용된다.
//    ⚠️ 자동으로 풀리지 않는다(🐢 안전 속도와 다르다). 사람이 ▶ 재개를 눌러야 다시 돈다.
const LOCAL_PAUSE_KEY = 'localPaused';
async function isLocalPaused() {
  try {
    const o = await chrome.storage.local.get(LOCAL_PAUSE_KEY);
    return o[LOCAL_PAUSE_KEY] === true;
  } catch (e) { return false; }   // 조회 실패는 '멈춤'이 아니라 '돎'(fail-open)
}

/* ─────────────────────────────────────────────────────────────────────────
 * 2026-09-18 대표 확정 — 간격을 들쭉날쭉하게 (Ⓒ 간격 가변)
 *
 * 종전: 키워드마다 **고정 30초** 쉼 → 조기 종료로 회차가 6분에 끝나 몰아쳤다.
 *       네이버 눈엔 「조용하다 갑자기 몰아치는」 패턴이라 로그인 화면에 걸렸다(9/18).
 * 지금: **남은 시간 ÷ 남은 개수** 를 평균으로, 거기에 **랜덤 0.4~1.8배**.
 *       → 대표가 그린 모양(2~3분·1~2분·3~4분…) 그대로인데 매 회차 무늬가 다르다.
 *
 * 🔴 넘지 않는 선:
 *   · 못 채우면 **서두르지 않고 남긴다** — 밀린 것은 다음 시간대가 이어받는다.
 *     (따라잡으려 몰아치면 지금 문제가 그대로 재발한다)
 *   · **최소 40초** — 아무리 개수가 많아도 그 밑으로는 안 내려간다.
 *   · 느리게 가기 상태면 그대로 2배.
 * ───────────────────────────────────────────────────────────────────────── */
const SPREAD_MIN_MS = 40 * 1000;    // 최소 간격
async function spreadGap(msLeftInBudget, keywordsLeft) {
  var left = Number(keywordsLeft) || 1;
  if (left < 1) left = 1;
  var budget = Number(msLeftInBudget) || 0;
  // 이번이 마지막이면 굳이 오래 쉴 필요 없다(다음이 없다).
  var avg = left <= 1 ? SPREAD_MIN_MS : budget / left;
  // 랜덤 0.4~1.8배 — 사람처럼 들쭉날쭉.
  var g = avg * (0.4 + Math.random() * 1.4);
  if (g < SPREAD_MIN_MS) g = SPREAD_MIN_MS;
  return (await isSlow()) ? g * 2 : g;
}

async function clearBlocked() {
  await chrome.storage.local.remove(BLOCK_KEY);
  await setState({ blocked: false, blockedUntil: 0, blockedReason: '' });
}

/** 탭을 닫되 **창은 절대 없애지 않는다** (2026-09-11 실사고).
 *
 * ⚠️ 대표가 「지금 수집 실행」을 눌렀더니 **크롬 창이 통째로 꺼졌다.**
 *    원인: 창에 네이버쇼핑 탭 하나만 열려 있었는데(차단 확인하려고 사람이 직접 연 탭)
 *    정리 코드가 그 탭을 지웠고, 크롬은 **마지막 탭이 닫히면 창을 닫는다.**
 * ⇒ 창별로 세어, 그 창의 마지막 탭이 되는 것은 **닫지 않고 빈 페이지로 돌려 둔다.**
 *    사람이 보던 창이 사라지는 것보다 탭 하나가 남는 편이 훨씬 낫다.
 */
async function removeTabsKeepWindows(tabs, why) {
  let closed = 0, spared = 0;
  // 창별 전체 탭 수를 먼저 센다(우리가 지울 것 말고 남는 게 있는지).
  const perWindow = {};
  for (const t of tabs) {
    if (t.windowId === undefined) continue;
    perWindow[t.windowId] = (perWindow[t.windowId] || 0) + 1;
  }
  const total = {};
  for (const wid of Object.keys(perWindow)) {
    try {
      const all = await chrome.tabs.query({ windowId: Number(wid) });
      total[wid] = all.length;
    } catch (e) { total[wid] = 99; }   // 못 세면 안전한 쪽(닫아도 창이 남는다고 보지 않음)
  }
  const left = { ...perWindow };
  for (const t of tabs) {
    if (t.id === undefined) continue;
    const wid = t.windowId;
    const willEmpty = wid !== undefined && (total[wid] || 0) - left[wid] < 1;
    if (willEmpty) {
      // 이 창의 마지막 한 장 — 닫지 말고 빈 페이지로 비켜 둔다.
      try { await chrome.tabs.update(t.id, { url: 'about:blank' }); spared++; } catch (e) { /* 무시 */ }
      left[wid] -= 1;
      continue;
    }
    try { await chrome.tabs.remove(t.id); closed++; } catch (e) { /* 이미 닫힘 */ }
    if (wid !== undefined) { left[wid] -= 1; total[wid] -= 1; }
  }
  if (closed || spared) {
    await log(`🧹 ${why} ${closed}개 정리`
      + (spared ? ` (창이 사라지지 않게 ${spared}개는 빈 페이지로 두었습니다)` : ''));
  }
}

/** 네이버쇼핑 작업 탭 전부 닫기 — 누적분 청소용. */
async function closeAllWorkTabs() {
  try {
    const tabs = await chrome.tabs.query({ url: '*://search.shopping.naver.com/*' });
    if (tabs.length) await removeTabsKeepWindows(tabs, '작업 탭');
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
      // ⚠️ **사람이 지금 보고 있는 탭은 뺏지 않는다**(2026-09-11).
      //    차단이 풀렸는지 확인하려고 사람이 직접 연 탭을 작업 탭으로 삼으면,
      //    보고 있던 화면이 키워드마다 제멋대로 넘어간다. 그런 탭밖에 없으면
      //    재사용을 포기하고 아래에서 새 탭을 만든다.
      const usable = tabs.filter((t) => !t.active);
      if (usable.length) {
        workTabId = usable[0].id;
        const extra = tabs.filter((t) => t.id !== workTabId && !t.active);
        if (extra.length) await removeTabsKeepWindows(extra, '중복 작업 탭');
        await chrome.storage.local.set({ [TAB_KEY]: workTabId });
        return workTabId;
      }
      await log('👀 열려 있는 네이버쇼핑 탭을 사람이 보고 있어 그대로 두고, 새 탭을 씁니다.');
    }
  } catch (e) { /* 조회 실패 — 아래에서 새로 만든다 */ }

  // ④ 새로 만든다 — **전용 창**을 쓴다 (2026-09-12 변경)
  //
  // ⚠️ 종전엔 남의 창에 `active:false` 배경 탭으로 만들었다. 배경 탭은 페이지가
  //    `document.visibilityState === 'hidden'` 으로 읽는다 —
  //    **「사람이 안 보는 탭에서 검색만 계속 도는 것」**은 판별하기 쉬운 신호다.
  // ⇒ 우리 전용 창을 하나 만들고, 그 창의 **활성 탭**으로 둔다.
  //    창은 `focused:false` 라 사람이 쓰던 창을 가리지 않으면서,
  //    최소화가 아니므로 페이지는 자기를 **보이는 상태**로 읽는다.
  // ⚠️ 최소화(state:'minimized')로 만들면 다시 hidden 이 된다 — 그래서 최소화하지 않는다.
  let tab = null;
  try {
    const w = await chrome.windows.create({
      url: WORK_URL, focused: false, state: 'normal', width: 1280, height: 900,
    });
    tab = (w.tabs && w.tabs[0]) || null;
    if (tab) await log('🪟 수집 전용 창에서 진행합니다(사람 창을 가리지 않습니다).');
  } catch (e) { tab = null; }
  if (!tab) {
    // 전용 창을 못 만들면 종전 방식으로 — 수집이 멈추는 것보다 낫다.
    let wins = [];
    try { wins = await chrome.windows.getAll({ windowTypes: ['normal'] }); } catch (e2) { wins = []; }
    if (!wins.length) throw new Error('작업 창 생성 실패');
    tab = await chrome.tabs.create({
      url: WORK_URL, active: false, pinned: true, windowId: wins[0].id,
    });
    await log('⚠️ 전용 창을 못 만들어 배경 탭으로 진행합니다(차단 위험이 조금 더 높습니다).');
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
function pageExtract(want) {
  // v1.13.0 — want = { page, since }: 2페이지부터는 **화면이 받아 온 응답**(net_tap.js 가 복사해 둔 것)을
  //   가장 먼저 읽는다. 라우터 props·__NEXT_DATA__ 가 1페이지 그대로여도, 화면이 2페이지 데이터를
  //   받았다면 그 응답은 __mcTap.items 에 있다. 인자 없이 부르면(회귀 시험·1페이지) 종전과 같다.
  want = want || {};
  var wantPage = parseInt(want.page, 10) || 0, since = parseInt(want.since, 10) || 0;
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
  // ⭐ 2026-09-15 실사고 — 클릭으로 넘긴 뒤에도 __NEXT_DATA__ 는 **1페이지 것 그대로**다
  //    (서버가 렌더한 초기값이라 SPA 이동으로는 안 바뀐다). v1.11.0·v1.11.1 세 회차 모두
  //    「중복 제외 = 담긴 수 × 9」 — 9번 클릭해 9번 같은 페이지를 읽었다.
  //    ⇒ Next 라우터가 들고 있는 **현재 페이지 props** 를 먼저 읽고, 없을 때만 __NEXT_DATA__ 로 간다.
  var rp = null, pageIndex = 0;
  try {
    var rt = window.next && window.next.router;
    if (rt) {
      var comp = rt.components && rt.components[rt.route];
      rp = (comp && comp.props) || null;
      pageIndex = parseInt((rt.query || {}).pagingIndex, 10) || 0;
    }
  } catch (e) { rp = null; }
  if (!pageIndex) {
    try { var pm = /[?&]pagingIndex=(\d+)/.exec(location.search); pageIndex = pm ? parseInt(pm[1], 10) : 1; }
    catch (e) { pageIndex = 0; }
  }
  var tap = null, tapPath = '';
  if (wantPage > 1) {
    try {
      var T = window.__mcTap;
      var items = (T && T.items) || [];
      for (var ti = items.length - 1; ti >= 0; ti--) {
        var it = items[ti];
        if (!it || !it.json) continue;
        // 주소에 pagingIndex 가 있으면 그것으로, 없으면 「클릭 뒤에 도착한 것」으로 고른다
        if (it.page === wantPage || (!it.page && since && it.at >= since)) { tap = it.json; tapPath = it.path || ''; break; }
      }
    } catch (e) { tap = null; }
  }
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
  var best = null, total = 0, src = '';
  var roots = [];
  if (tap) roots.push(['tap', tap]);
  if (rp) roots.push(['router', rp]);
  roots.push(['nextdata', nd]);
  for (var ri = 0; ri < roots.length && !(best && best.length); ri++) {
  src = roots[ri][0];
  var seen = new Set();
  var stack = [roots[ri][1]], guard = 0;
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
  }
  // 상품을 읽어냈으면 무조건 성공 — 차단 검사조차 하지 않는다
  if (best && best.length) return { total: total, list: best.slice(0, 200), href: href, pageIndex: pageIndex, src: src, tapPath: tapPath };

  // 여기부터는 '못 읽은' 경우. 이제서야 차단인지 본다.
  // ⚠️ 2026-09-15 v1.11.4 — 새 IP·새 크롬의 첫 회차에서 네이버가 **「보안 확인」 퍼즐**(영수증 문제)을 냈다.
  //    문구가 종전 차단문과 달라 「판독 실패 · 다음 회차 재시도」로 넘어가 매 정시마다 퍼즐 페이지를
  //    두드릴 뻔했다. 퍼즐도 차단과 같이 다룬다 — 멈추고, 쉬고, 서버에 원문을 남긴다(사람이 풀어야 풀린다).
  var blocked = /일시적으로 제한|자동입력 방지|비정상적인 접근|접근이 차단|보안 확인을 완료|실제 사용자임을 확인|빈 칸을 채워주세요/.test(body);
  if (blocked) return { err: 'BLOCK_TEXT', href: href, title: title, body: body.slice(0, 300) };
  return { err: nd ? 'NO_LIST' : 'NO_NEXT_DATA', href: href, title: title, body: body.slice(0, 300) };
}

/** 페이지 목록의 첫 상품 식별자 — 「페이지가 실제로 바뀌었나」를 이걸로 판정한다(2026-09-15). */
function firstIdOf(list) {
  var p = (list && list[0]) || null;
  if (!p) return '';
  return String(p.nvMid || p.id || p.productId || p.mallProductUrl || p.productTitle || '');
}

/** v1.11.5 — 「바뀌었나」를 첫 상품 하나가 아니라 **광고를 뺀 상품 ID 집합**으로 본다.
 *  2026-09-15 21:22 실측: 2페이지는 클릭으로 실제로 넘어갔는데(담긴 69 · 중복 3) 3페이지에서
 *  STALE 로 멈췄다. 라우터는 이미 3페이지(q=3)였고 페이지네이션도 3이 현재였다 —
 *  네이버가 **페이지마다 맨 위에 같은 광고**를 놓으면 첫 상품 ID 만 보는 판정이 「안 바뀜」으로 속는다.
 *  ⇒ 광고를 뺀 ID 들 중 이전 장에 없던 것이 하나라도 있으면 「바뀐 것」. */
function organicIds(list) {
  var out = [];
  var arr = list || [];
  for (var i = 0; i < arr.length; i++) {
    var p = arr[i];
    if (!p || typeof p !== 'object') continue;
    try { if (RR && typeof RR.isAdItem === 'function' && RR.isAdItem(p)) continue; } catch (e) {}
    var id = String(p.nvMid || p.id || p.productId || '');
    if (id) out.push(id);
  }
  return out;
}
function pageChanged(list, prevIds) {
  if (!prevIds || !prevIds.length) return true;      // 1페이지 · 비교 대상 없음
  var prev = new Set(prevIds);
  var ids = organicIds(list);
  if (!ids.length) return false;                        // 광고뿐인 목록은 「바뀐 것」으로 안 본다
  for (var i = 0; i < ids.length; i++) if (!prev.has(ids[i])) return true;
  return false;
}

/** 이번 회차에 어떤 방식으로 페이지를 넘겼나 — 서버 meta 로 올려 현장에서 판명되게 한다.
 *  stale = 클릭은 됐는데 내용이 이전 페이지 그대로라 주소 이동으로 되돌린 횟수(2026-09-15). */
let _navMode = { url: 0, click: 0, fallback: 0, stale: 0, reported: false, src: {},
                 // v1.15.0 — 그 클릭이 **진짜 입력**이었는지 합성이었는지. 서버 집계로 갈린다.
                 how: { trusted: 0, synth: 0 },
                 // v1.17.0 — 1페이지로 **어떻게 들어갔나**.
                 //   portal = 네이버 → 검색 → 쇼핑 탭 / shopbox = 쇼핑 검색창 / url = 주소를 직접 엶(폴백)
                 entry: { portal: 0, shopbox: 0, url: 0 } };
let _clickedAt = 0;          // v1.13.0 — 마지막 페이지 클릭 시각(이 뒤에 도착한 응답만 그 장의 답으로 본다)

/** 화면 안에서 실행돼 **페이지 버튼을 실제로 클릭**한다.
 *
 * ⚠️ 네이버 화면 구조는 우리가 정하는 게 아니라 바뀔 수 있다. 그래서 **여러 모양을 차례로**
 *    시도하고, 하나도 못 찾으면 `false` 를 돌려 호출부가 옛 방식으로 폴백하게 한다.
 *    「못 찾으면 수집을 멈춘다」로 만들면 화면이 조금만 바뀌어도 전량이 죽는다.
 * ⚠️ 이 함수는 페이지 안(MAIN world)에서 돈다 — 바깥 변수를 쓸 수 없다.
 */
function pagerClick(target) {
  var want = String(target);
  function vis(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  // ① 페이지네이션 영역 안에서 숫자가 정확히 맞는 링크·버튼
  var scopes = document.querySelectorAll('[class*="pagination"],[class*="paging"],[role="navigation"]');
  for (var s = 0; s < scopes.length; s++) {
    var cands = scopes[s].querySelectorAll('a,button');
    for (var i = 0; i < cands.length; i++) {
      var el = cands[i];
      if (!vis(el)) continue;
      if ((el.textContent || '').trim() === want) { el.click(); return 'num'; }
    }
  }
  // ② 「다음」 버튼 (한 장씩 넘어갈 때만 옳다 — 호출부가 순서대로 부르므로 성립)
  for (var s2 = 0; s2 < scopes.length; s2++) {
    var c2 = scopes[s2].querySelectorAll('a,button');
    for (var j = 0; j < c2.length; j++) {
      var e2 = c2[j];
      if (!vis(e2)) continue;
      var t = (e2.textContent || '').trim();
      var aria = e2.getAttribute('aria-label') || '';
      if (t === '다음' || /다음/.test(aria) || /next/i.test(e2.className || '')) {
        if (e2.getAttribute('aria-disabled') === 'true' || e2.disabled) continue;
        e2.click(); return 'next';
      }
    }
  }
  // ③ 영역을 못 찾았을 때 — 문서 전체에서 숫자가 정확히 맞는 링크
  var all = document.querySelectorAll('a');
  for (var k = 0; k < all.length; k++) {
    var e3 = all[k];
    if (!vis(e3)) continue;
    if ((e3.textContent || '').trim() !== want) continue;
    var href = e3.getAttribute('href') || '';
    if (href.indexOf('pagingIndex') < 0 && href !== '#') continue;
    e3.click(); return 'loose';
  }
  return '';
}

/** 화면 안에서 실행 — 페이지 버튼을 **찾기만** 하고 누르지는 않는다(가운데 좌표를 돌려준다).
 *
 * ⚠️ `pagerClick` 과 **같은 순서·같은 조건**으로 찾아야 한다. 한쪽만 고치면 두 경로가
 *    서로 다른 버튼을 누르게 되어 비교 자체가 무의미해진다(회귀 시험이 이를 지킨다).
 * ⚠️ 이 함수는 페이지 안(MAIN world)에서 돈다 — 바깥 변수를 쓸 수 없다.
 */
function pagerLocate(target) {
  var want = String(target);
  function vis(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function at(el, branch) {
    // 화면 밖이면 좌표가 음수라 엉뚱한 곳이 눌린다 — 가운데로 끌어온 뒤 다시 잰다.
    try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) { /* 무시 */ }
    var r = el.getBoundingClientRect();
    var x = r.left + r.width / 2, y = r.top + r.height / 2;
    var w = window.innerWidth || 0, h = window.innerHeight || 0;
    if (!(x > 0 && y > 0 && x < w && y < h)) return null;   // 그래도 밖이면 포기(합성 클릭으로 폴백)
    /* 🔴 v1.17.5 — **그 좌표에 정말 이 버튼이 있는가.**
     *   좌표로 보내는 클릭은 브라우저가 「그 점에서 맨 위에 있는 것」에 꽂는다.
     *   떠 있는 띠·광고·덮개가 가리고 있으면 클릭은 그쪽으로 가고, 우리 눈엔
     *   「오류 없이 눌렀는데 아무 일도 안 일어남」으로 보인다 — 9/16 17:23·17:33 회차가
     *   정확히 그 모양이었다(요청 0건). 여태 한 번도 확인한 적이 없어서 여기 넣는다.
     *   ⚠️ 가려졌다고 클릭을 포기하지는 않는다 — 판정이 틀릴 수도 있으니 **찍기만** 하고
     *      그대로 눌러 본다. 무엇이 덮었는지는 사유 문자열로 남는다. */
    var hit = '', covered = 0;
    try {
      var top = document.elementFromPoint(x, y);
      if (top) {
        var cls = String(top.className || '').split(/\s+/).filter(Boolean).slice(0, 2).join('.');
        hit = (top.tagName || '?').toLowerCase() + (cls ? '.' + cls : '')
            + '>' + String(top.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 10);
        var mine = (top === el) || (el.contains && el.contains(top)) || (top.contains && top.contains(el));
        covered = mine ? 0 : 1;
      } else {
        hit = 'none';
        covered = 1;
      }
    } catch (e) { hit = 'err'; }
    return { branch: branch, x: Math.round(x), y: Math.round(y), hit: hit.slice(0, 40), covered: covered };
  }
  /* ⓪ 🔴 v1.17.5 — 네이버가 직접 붙여 둔 표식으로 **정확히** 지목한다.
   *   대표 캡처(2026-09-16)로 확인한 실제 모양:
   *     <a href="#" class="pagination_btn_page__utqBz _nlog_click _nlog_impression_element"
   *        data-shp-area="prd_pgn.pgn" data-shp-contents-id="2" …>2</a>
   *   ⚠️ **클래스 이름에는 걸지 않는다** — `__utqBz` 는 빌드마다 바뀌는 해시다.
   *      거기 걸면 네이버가 배포하는 날 조용히 죽는다.
   *   ⚠️ 표식 숫자와 **글자가 둘 다** 맞을 때만 쓴다 — 표식의 뜻을 우리가 단정하지 않는다.
   *      어긋나면 아래 종전 규칙으로 그냥 내려간다. */
  var marked = document.querySelectorAll('[data-shp-area="prd_pgn.pgn"][data-shp-contents-id]');
  for (var m = 0; m < marked.length; m++) {
    var em = marked[m];
    if (!vis(em)) continue;
    if (em.getAttribute('data-shp-contents-id') !== want) continue;
    if ((em.textContent || '').trim() !== want) continue;
    return at(em, 'shp');
  }
  /* ① 페이지네이션 영역 안에서 숫자가 정확히 맞는 링크·버튼
   * ⚠️ 이 영역은 **겹쳐 있다**(대표 캡처) — `pagination_pagination__…` 안에 `pagination_num__…`.
   *    그래서 같은 버튼이 두 번 세어진다. 먼저 맞는 것을 쓰므로 동작에는 지장이 없다. */
  var scopes = document.querySelectorAll('[class*="pagination"],[class*="paging"],[role="navigation"]');
  for (var s = 0; s < scopes.length; s++) {
    var cands = scopes[s].querySelectorAll('a,button');
    for (var i = 0; i < cands.length; i++) {
      var el = cands[i];
      if (!vis(el)) continue;
      if ((el.textContent || '').trim() === want) return at(el, 'num');
    }
  }
  // ② 「다음」 버튼
  for (var s2 = 0; s2 < scopes.length; s2++) {
    var c2 = scopes[s2].querySelectorAll('a,button');
    for (var j = 0; j < c2.length; j++) {
      var e2 = c2[j];
      if (!vis(e2)) continue;
      var t = (e2.textContent || '').trim();
      var aria = e2.getAttribute('aria-label') || '';
      if (t === '다음' || /다음/.test(aria) || /next/i.test(e2.className || '')) {
        if (e2.getAttribute('aria-disabled') === 'true' || e2.disabled) continue;
        return at(e2, 'next');
      }
    }
  }
  // ③ 영역을 못 찾았을 때 — 문서 전체에서 숫자가 정확히 맞는 링크
  var all = document.querySelectorAll('a');
  for (var k = 0; k < all.length; k++) {
    var e3 = all[k];
    if (!vis(e3)) continue;
    if ((e3.textContent || '').trim() !== want) continue;
    var href = e3.getAttribute('href') || '';
    if (href.indexOf('pagingIndex') < 0 && href !== '#') continue;
    return at(e3, 'loose');
  }
  return null;
}

/** 화면 안에서 실행 — **검색창**을 찾아 가운데 좌표를 돌려준다(v1.16.0).
 *
 * ⚠️ 네이버가 검색창 클래스명을 수시로 바꾼다. 그래서 **여러 모양을 차례로** 보고,
 *    하나도 못 찾으면 null 을 돌려 호출부가 종전 주소 열기로 폴백하게 한다.
 * ⚠️ 이 함수는 페이지 안(MAIN world)에서 돈다 — 바깥 변수를 쓸 수 없다.
 */
function searchBoxLocate() {
  var sels = [
    'input#input_search',
    'input[name="query"]',
    'form input[type="text"]',
    'input[type="search"]',
    '[role="searchbox"]',
    'input[placeholder*="검색"]',
  ];
  for (var s = 0; s < sels.length; s++) {
    var list = document.querySelectorAll(sels[s]);
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (el.disabled || el.readOnly) continue;
      var r = el.getBoundingClientRect();
      if (!(r.width > 40 && r.height > 10)) continue;              // 숨은 칸·아이콘 제외
      var x = r.left + r.width / 2, y = r.top + r.height / 2;
      var w = window.innerWidth || 0, h = window.innerHeight || 0;
      if (!(x > 0 && y > 0 && x < w && y < h)) continue;
      return { sel: sels[s], x: Math.round(x), y: Math.round(y) };
    }
  }
  return null;
}

/* ───────────────────────────────────────────────────────────────────────────
 * v1.16.0 — **검색창에 쳐서 들어간다** (2026-09-16 실측 근거 · 대표 지시)
 *
 * 무엇을 고치나: 지금까지 1페이지를 `chrome.tabs.update({url:'…/search/all?query=X'})`
 *   로 **직접 열었다**. 9/16 같은 자로 사람·기계를 나란히 재 보니 **그 뒤가 갈렸다**:
 *
 *     사람(검색창으로 들어옴 · 주소 `?adQuery=…&origQuery=…`)
 *       2페이지 클릭 → `/api/search/all` → **200** (312KB · 399KB · 425KB, 3/3)
 *     기계(주소를 직접 엶 · 주소 `?query=X`)
 *       2페이지 클릭 → `/_next/data/<빌드ID>/search/all.json` → **418** (재시도까지 두 번)
 *
 *   같은 기계·같은 회선·같은 크롬·15분 차이인데 **부르는 주소 자체가 다르다.**
 *   주소를 직접 열면 화면이 「페이지를 통째로 다시 받는」 길로 가고,
 *   검색창으로 들어가면 「목록만 갈아 끼우는」 길로 간다.
 *
 * 그래서: 사람과 같은 순서로 간다 — **쇼핑 홈을 열고 · 검색창을 누르고 · 키워드를 치고 · 엔터.**
 *   ⭐ 이것은 사이트를 **원래 쓰는 대로 쓰는 것**이다. 무엇을 위장하거나 속이지 않는다.
 *
 * v1.17.0 (대표 지시 2026-09-16) — **포털부터 사람 경로 전체를 밟는다.**
 *   「크롬창 열고 네이버 주소 입력 → 추적할 키워드 입력 → 쇼핑 탭 클릭 → 페이지 이동.
 *    그 뒤로는 쇼핑 페이지 검색창에서 순차적으로 키워드 검색」
 *   ⇒ 첫 키워드 = `portalEntry`(네이버 → 검색 → 「쇼핑」 탭 클릭)
 *      그 뒤 키워드 = `shopBoxEntry`(쇼핑 검색창에 이어서 친다 — 사람도 매번 되돌아가지 않는다)
 *   ⚠️ 첫 키워드만 페이지 로드가 2건 는다(네이버 첫 화면 · 통합검색). 그 뒤는 종전과 같다.
 *
 * 🔴 넘지 않는 선 (바꾸지 말 것)
 *   · **퍼즐은 사람이 푼다.** 퍼즐 칸에는 아무것도 입력하지 않는다(아래 가드).
 *   · IP 세탁·지문 위조 없음 · UA/헤더/쿠키 무접촉 · 상한과 감속 그대로.
 *
 * ⚠️ 요청이 한 건 는다 — 키워드마다 쇼핑 홈 1회. 그래서 **홈은 회차마다 한 번만** 열고
 *    그 뒤 키워드들은 검색창만 다시 쓴다(아래 `_homeAt`).
 * ⚠️ 실패하면 **반드시 종전 주소 열기로 폴백한다.** 검색창 모양이 바뀌어도 수집이 멈추지 않게.
 * ─────────────────────────────────────────────────────────────────────────── */
/** 화면 안에서 실행 — 검색 결과 위쪽 **「쇼핑」 탭 링크**를 찾아 좌표를 돌려준다(v1.17.0). */
function shopTabLocate() {
  function at(el) {
    try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) { /* 무시 */ }
    var r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return null;
    var x = r.left + r.width / 2, y = r.top + r.height / 2;
    var w = window.innerWidth || 0, h = window.innerHeight || 0;
    if (!(x > 0 && y > 0 && x < w && y < h)) return null;
    return { x: Math.round(x), y: Math.round(y) };
  }
  /* 🔴 v1.17.3 — 탭 글자를 **완전일치로 보면 안 된다**(2026-09-16 16:19 실측).
   *   진단이 남긴 것: `no-shop-tab@search.naver.com/search.naver|a650|sc32|쇼핑새 창 >https://search.shopping.naver.com/`
   *   탭은 **거기 있었다.** 다만 글자가 「쇼핑」이 아니라 **「쇼핑새 창」** 이었다 —
   *   `<a>쇼핑<span>새 창</span></a>` 처럼 화면 낭독기용 안내가 안에 들어 있어
   *   `textContent` 가 둘을 붙여 준다. 완전일치라 못 잡고 다섯 회차를 헛돌았다.
   * ⚠️ 그래서 **보조 문구를 떼고 비교**한다. 네이버가 그 문구를 바꿔도 앞글자가 「쇼핑」이면 잡힌다.
   */
  /* 실제 모양(2026-09-16 대표 캡처):
   *   <a role="tab" class="tab" target="_blank" href="…/search/all?where=all&frm=NVSCTAB&query=…">
   *     "쇼핑"<span class="blind">새 창 열림</span>
   *   </a>
   * ⚠️ v1.17.3 은 끝의 「열림」 **하나만** 떼서 「쇼핑새 창」이 남았다. 한 번만 떼면 안 된다.
   *    그래서 ① 낭독기 전용(.blind 등)을 아예 지우고 ② 그래도 남으면 되풀이해 떼어 낸다.
   */
  function tabText(el) {
    var t = '';
    try {
      var c = el.cloneNode(true);
      var hid = c.querySelectorAll('.blind,.sr-only,.screen_out,.a11y,[aria-hidden="true"]');
      for (var i = 0; i < hid.length; i++) { if (hid[i].remove) hid[i].remove(); }
      t = String(c.textContent || '');
    } catch (e) { t = String((el && el.textContent) || ''); }
    t = t.replace(/\s+/g, ' ').trim();
    for (var k = 0; k < 4; k++) {
      var n = t.replace(/\s*(새\s*창\s*열림?|새\s*창|새창|열림|열기|link|new\s*window)\s*$/i, '').trim();
      if (n === t) break;
      t = n;
    }
    return t;
  }
  var as = document.querySelectorAll('a');
  // ① 주소가 실제로 쇼핑 검색으로 가는 「쇼핑」 링크 — 이게 우리가 원하는 탭이다.
  //    ⚠️ 첫 화면 맨 위 메뉴에도 「쇼핑」이 있다. 주소로 갈라야 엉뚱한 데로 안 간다.
  for (var i = 0; i < as.length; i++) {
    var a = as[i];
    if (tabText(a) !== '쇼핑') continue;
    var h = a.getAttribute('href') || '';
    if (h.indexOf('where=shop') >= 0 || h.indexOf('ssc=tab.shop') >= 0
        || h.indexOf('frm=NVSCTAB') >= 0 || h.indexOf('search.shopping.naver.com') >= 0) {
      var p = at(a);
      // 새 창으로 열리는 탭인지 미리 알려 준다 — 호출부가 새 탭을 받아 이어 쓴다.
      if (p) { p.via = 'href'; p.blank = (a.getAttribute('target') || '') === '_blank'; return p; }
    }
  }
  // ② 주소로 못 가르면 — 탭 줄(role=tab·nav) 안에서 글자가 정확히 「쇼핑」인 것
  var scopes = document.querySelectorAll('[role="tablist"],[role="navigation"],nav,[class*="tab"]');
  for (var s = 0; s < scopes.length; s++) {
    var c = scopes[s].querySelectorAll('a');
    for (var j = 0; j < c.length; j++) {
      if (tabText(c[j]) !== '쇼핑') continue;
      // ⚠️ 여기서도 주소를 본다 — 첫 화면 메뉴의 「쇼핑」(shopping.naver.com 홈)을 누르면
      //    결과 화면이 아니라 쇼핑 첫 화면으로 가서 회차를 한 번 버린다.
      var h2 = c[j].getAttribute('href') || '';
      if (h2.indexOf('shopping.naver.com') < 0 && h2.indexOf('where=shop') < 0
          && h2.indexOf('ssc=tab.shop') < 0) continue;
      var q = at(c[j]);
      if (q) { q.via = 'tab'; return q; }
    }
  }
  // ③ v1.17.2 — 못 찾았으면 **어디서 무엇을 봤는지** 남긴다.
  //    ⚠️ v1.17.1 에서 두 키워드 다 `no-shop-tab` 이었는데, 그게 「통합검색에 탭이 없다」인지
  //       「아직 첫 화면이었다」인지 「탭은 있는데 내 규칙이 못 잡았다」인지 가를 수가 없었다.
  //       추측하지 말고 찍는다(오늘만 추측으로 네 번 틀렸다).
  var seen = [], all2 = document.querySelectorAll('a');
  for (var m = 0; m < all2.length && seen.length < 3; m++) {
    var t2 = (all2[m].textContent || '').trim();
    if (t2 === '쇼핑' || t2.indexOf('쇼핑') === 0) {
      seen.push(t2.slice(0, 6) + '>' + String(all2[m].getAttribute('href') || '-').slice(0, 34));
    }
  }
  return { miss: true, host: location.host, path: location.pathname,
           a: all2.length, sc: scopes.length, seen: seen };
}

const NAVER_HOME = 'https://www.naver.com';
let _entryNote = '';         // 진입이 실패한 사유(진단 보고용)
let _entryVia = '';          // 'portal'(네이버부터) · 'shopbox'(쇼핑 검색창) · ''(실패)

/** 검색창을 누르고 · 키워드를 치고 · 엔터. 사람 손과 같은 순서.
 *  ⚠️ 부르는 쪽이 이미 `dbgAttach` 해 둔 상태여야 한다(띠를 한 번만 띄우려고 밖에서 관리한다). */
async function typeAndEnter(tabId, box, keyword) {
  const at = { x: box.x, y: box.y, button: 'left' };
  await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...at, type: 'mouseMoved', buttons: 0, clickCount: 0 });
  await sleep(40 + Math.floor(Math.random() * 60));
  await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...at, type: 'mousePressed', buttons: 1, clickCount: 1 });
  await sleep(30 + Math.floor(Math.random() * 50));
  await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...at, type: 'mouseReleased', buttons: 0, clickCount: 1 });
  await sleep(120 + Math.floor(Math.random() * 180));
  // 이미 적혀 있는 것(전 키워드 잔상)을 전체 선택해 덮어쓴다.
  for (const type of ['keyDown', 'keyUp']) {
    await dbgSend(tabId, 'Input.dispatchKeyEvent', {
      type, key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2,
    });
  }
  // ⚠️ 한글은 글자 단위 키 이벤트로 못 넣는다(조합 입력) — insertText 로 한 번에 넣는다.
  //    ⛔ 이 호출은 **검색창에만** 쓴다. 퍼즐 칸에는 절대 쓰지 않는다(회귀 시험이 지킨다).
  await dbgSend(tabId, 'Input.insertText', { text: String(keyword) });
  await sleep(250 + Math.floor(Math.random() * 350));   // 자동완성이 뜨는 틈 — 사람도 잠깐 멈춘다
  for (const type of ['keyDown', 'keyUp']) {
    await dbgSend(tabId, 'Input.dispatchKeyEvent', {
      type, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13, text: type === 'keyDown' ? '\r' : undefined,
    });
  }
}

/** 화면 안에서 검색창을 찾는다(없으면 null). */
async function findBox(tabId) {
  const [loc] = await chrome.scripting.executeScript({
    target: { tabId }, world: 'MAIN', func: searchBoxLocate,
  });
  return (loc && loc.result) || null;
}

/** ㉮ 포털부터 — 네이버 → 검색창에 키워드 → 「쇼핑」 탭 클릭 → 쇼핑 결과.
 *  대표 지시(2026-09-16): 「크롬창 열고 네이버 주소 입력 → 키워드 입력 → 쇼핑 탭 → 페이지 이동」. */
async function portalEntry(tabId, keyword) {
  let attached = false;
  try {
    await chrome.tabs.update(tabId, { url: NAVER_HOME });
    await waitNavigated(tabId, 'naver.com');
    await sleep(900 + Math.floor(Math.random() * 900));
    const box = await findBox(tabId);
    if (!box) { _entryNote = 'portal-no-searchbox'; return 0; }

    await dbgAttach(tabId); attached = true;
    await typeAndEnter(tabId, box, keyword);
    await dbgDetach(tabId); attached = false;      // 이동 동안에는 떼어 둔다(띠를 짧게)
    await waitNavigated(tabId, 'search.naver.com');
    // ⚠️ v1.17.2 — 통합검색 탭 줄은 늦게 그려진다. 1초로는 짧아 「탭이 없다」로 오판할 수 있어
    //    2~3초로 늘리고, 그래도 없으면 한 번 더 본다(요청은 안 는다 — 화면만 다시 읽는다).
    await sleep(2000 + Math.floor(Math.random() * 1200));

    // 「쇼핑」 탭을 눌러 넘어간다 — 주소를 직접 열지 않는다.
    let [tl] = await chrome.scripting.executeScript({
      target: { tabId }, world: 'MAIN', func: shopTabLocate,
    });
    if (tl && tl.result && tl.result.miss) {       // 아직 안 그려졌을 수 있다 — 한 번 더
      await sleep(1500 + Math.floor(Math.random() * 900));
      [tl] = await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN', func: shopTabLocate,
      });
    }
    const tab = tl && tl.result;
    if (!tab || tab.miss) {
      // v1.17.2 — 어디서 무엇을 봤는지까지 남긴다(위 ③ 참조).
      const d = tab || {};
      _entryNote = ('no-shop-tab@' + (d.host || '?') + (d.path || '')
                    + '|a' + (d.a || 0) + '|sc' + (d.sc || 0)
                    + '|' + ((d.seen || []).join(' ') || '쇼핑링크0')).slice(0, 150);
      return 0;
    }
    /* 🔴 v1.17.4 — 이 탭은 `target="_blank"` 다. **새 창(탭)으로 열린다.**
     *   그래서 누른 뒤에도 우리가 보던 탭은 통합검색 그대로 남고, 결과는 **다른 탭**에 뜬다.
     *   v1.17.3 까지는 그것을 「결과 화면이 아니다」로 읽고 폴백했다(2026-09-16 대표 캡처로 확인).
     *   ⇒ 누르기 전 탭 목록을 적어 두고, 새로 생긴 쇼핑 탭을 **이어받아** 그 뒤를 진행한다.
     *     사람도 새 탭이 뜨면 그 탭에서 계속 본다 — 같은 순서다.
     */
    const self0 = await chrome.tabs.get(tabId);
    const winId = self0.windowId;
    const before = (await chrome.tabs.query({ windowId: winId })).map((t) => t.id);

    await dbgAttach(tabId); attached = true;
    const at = { x: tab.x, y: tab.y, button: 'left' };
    await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...at, type: 'mouseMoved', buttons: 0, clickCount: 0 });
    await sleep(40 + Math.floor(Math.random() * 70));
    await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...at, type: 'mousePressed', buttons: 1, clickCount: 1 });
    await sleep(30 + Math.floor(Math.random() * 60));
    await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...at, type: 'mouseReleased', buttons: 0, clickCount: 1 });
    await dbgDetach(tabId); attached = false;

    // 새 탭이 떴는지 최대 15초 동안 본다(안 뜨면 같은 탭에서 이동한 것 — 그대로 진행).
    let adopted = 0;
    for (let i = 0; i < 30 && !adopted; i++) {
      await sleep(500);
      const now = await chrome.tabs.query({ windowId: winId });
      for (const t of now) {
        if (before.indexOf(t.id) >= 0) continue;
        if (String(t.url || '').indexOf('search.shopping.naver.com') < 0) continue;
        adopted = t.id;
        break;
      }
      if (!adopted) {
        const me = await chrome.tabs.get(tabId).catch(() => null);
        if (me && String(me.url || '').indexOf('search.shopping.naver.com') >= 0) break;  // 같은 탭에서 이동
      }
    }
    if (adopted) {
      // 새 탭을 작업 탭으로 이어받고 옛 탭은 닫는다(탭이 회차마다 쌓이면 메모리가 샌다).
      await waitNavigated(adopted, 'search/all');
      workTabId = adopted;
      try { await chrome.storage.local.set({ [TAB_KEY]: adopted }); } catch (e) { /* 무시 */ }
      try { await chrome.tabs.remove(tabId); } catch (e) { /* 무시 */ }
      return adopted;
    }
    await waitNavigated(tabId, 'shopping.naver.com');
    return tabId;
  } catch (e) {
    _entryNote = String((e && e.message) || e).slice(0, 60);
    return 0;
  } finally {
    if (attached) await dbgDetach(tabId);
  }
}

/** ㉯ 쇼핑 안에서 — 쇼핑 페이지 검색창에 다음 키워드를 친다(사람도 두 번째부터는 이렇게 한다). */
async function shopBoxEntry(tabId, keyword) {
  let attached = false;
  try {
    const box = await findBox(tabId);
    if (!box) { _entryNote = 'shop-no-searchbox'; return false; }
    await dbgAttach(tabId); attached = true;
    await typeAndEnter(tabId, box, keyword);
    await dbgDetach(tabId); attached = false;
    /* 🔴🔴 v1.17.8 — **키워드가 주소에 들어올 때까지** 기다린다. 이게 2026-09-17 오염의 원인이다.
     *   종전엔 `waitNavigated(tabId, 'search/all')` 이었다. 그런데 우리는 **이미 쇼핑 결과 화면**에
     *   서 있으므로 주소에 `search/all` 이 처음부터 있다 ⇒ **검색이 안 돌아도 즉시 통과**한다.
     *   그 결과 9/17 00:00~11:00 에 서로 다른 12개 키워드가 **같은 화면 하나**를 읽어
     *   같은 상품 32개를 담았고, 오류도 막힘 보고도 없이 조용히 오염됐다.
     *   ⭐ 종전 주소 열기 경로는 처음부터 `waitNavigated(tabId, encodeURIComponent(keyword))` 로
     *      **키워드를 기다린다.** 같은 일을 하는 경로가 둘인데 하나만 확인하던 것 — 이 저장소가
     *      반복해 온 함정이고, 내가 그 함정을 문서에 적어 둔 그 날 거기 빠졌다. */
    await waitNavigated(tabId, encodeURIComponent(keyword));
    return true;
  } catch (e) {
    _entryNote = String((e && e.message) || e).slice(0, 60);
    return false;
  } finally {
    if (attached) await dbgDetach(tabId);
  }
}

/** 사람과 같은 길로 1페이지에 들어간다.
 *  성공하면 **그 뒤를 진행할 탭 id**(새 탭을 이어받았으면 그 id), 실패하면 0(주소 열기로 폴백).
 *  ⚠️ v1.17.4 — 쇼핑 탭이 `target="_blank"` 라 **탭이 바뀔 수 있다.** 그래서 true/false 가 아니라
 *     탭 id 를 돌려준다. 호출부가 이 id 로 이어서 읽지 않으면 엉뚱한 탭(통합검색)을 읽는다. */
async function humanEntry(tabId, keyword) {
  _entryVia = '';
  if (!chrome.debugger) { _entryNote = 'no-debugger-api'; return 0; }
  try {
    // 이미 쇼핑 안에 있으면 그 검색창을 쓴다 — 사람도 매번 네이버로 되돌아가지 않는다.
    const t = await chrome.tabs.get(tabId);
    const inShop = String(t.url || '').indexOf('search.shopping.naver.com') >= 0;
    let use = 0;
    if (inShop && await shopBoxEntry(tabId, keyword)) { use = tabId; _entryVia = 'shopbox'; }
    else {
      use = await portalEntry(tabId, keyword);
      if (use) _entryVia = 'portal';
    }
    if (!use) return 0;
    // 정말 그 키워드의 쇼핑 결과 화면인가 — 아니면 폴백한다.
    const t2 = await chrome.tabs.get(use);
    const u = String(t2.url || '');
    if (u.indexOf('search.shopping.naver.com') < 0 || u.indexOf('/search/all') < 0) {
      _entryNote = _entryNote || ('not-result-page@' + u.slice(0, 60));
      _entryVia = '';
      return 0;
    }
    /* 🔴🔴 v1.17.8 — **그 화면이 「이 키워드」의 결과인가.** 두 번째 그물이다.
     *   위 두 줄은 「쇼핑 결과 화면인가」만 본다. 그런데 9/17 오염 때 우리는 **남의 키워드**
     *   결과 화면에 서 있었고, 그 화면도 이 조건을 통과했다.
     *   ⚠️ 주소는 인코딩된 형태(%EA%B0%88…)일 수도, 디코딩된 한글일 수도 있다 — 둘 다 본다.
     *   ⚠️ 못 맞추면 **실패로 떨어뜨린다**(0 반환). 그러면 호출부가 종전 주소 열기로 폴백하고,
     *      그 경로는 처음부터 키워드를 기다리므로 안전하다. */
    const enc = encodeURIComponent(keyword);
    let dec = u;
    try { dec = decodeURIComponent(u); } catch (e) { /* 잘못된 인코딩은 원문으로 본다 */ }
    if (u.indexOf(enc) < 0 && dec.indexOf(keyword) < 0) {
      _entryNote = 'wrong-keyword@' + u.slice(0, 70);
      _entryVia = '';
      return 0;
    }
    _entryNote = '';
    return use;
  } catch (e) {
    _entryNote = String((e && e.message) || e).slice(0, 60);
    _entryVia = '';
    return 0;
  }
}

/* ───────────────────────────────────────────────────────────────────────────
 * v1.15.0 — 페이지 넘김을 **브라우저 표준 입력 경로**로 보낸다 (2026-09-16)
 *
 * 무엇이 문제였나: `el.click()` 이 만드는 클릭은 브라우저가 `isTrusted=false` 로 표시한다.
 *   9/16 같은 자(net_tap)로 사람·기계를 각각 재 보니 **같은 탭·문서·세션·IP·확장 ON** 에서
 *   기계 3/3 은 `/api/search/all` 이 418, 사람 2/2 는 200(312KB·399KB)이었다.
 *   후보 여덟(IP 평판·세션/쿠키·확장 유무·2페이지 자체·총량·경과 시간·탭 나이·주소 모양)이
 *   전부 실측으로 닫혔다.
 *
 * 어떻게: `chrome.debugger`(크롬 공식 API)로 붙어 CDP `Input.dispatchMouseEvent` 를 보낸다.
 *   ⭐ 이것은 **Playwright·Puppeteer 가 클릭하는 바로 그 방식**이다. 수집기를 처음부터
 *      Playwright 로 짰으면 기본 동작이 이랬다. 없던 위장을 새로 입히는 것이 아니라
 *      확장 안에서 쓰던 비표준 클릭(`el.click()`)을 표준 경로로 되돌리는 것이다.
 *
 * 🔴 넘지 않는 선 (바꾸지 말 것)
 *   · **퍼즐은 사람이 푼다.** 자동 해제·솔버 없음. 캡차를 만나면 종전대로 쉰다.
 *   · **IP 세탁 없음** — 프록시·VPN 없음. 같은 회선 그대로.
 *   · **지문 위조 없음** — UA·헤더·쿠키 손대지 않는다(확장 권한에 그 항목이 아예 없다).
 *   · **양은 늘리지 않는다** — 시간당 상한·캡차 후 감속 그대로.
 *
 * ⚠️ 대가 — 붙어 있는 동안 그 창에 「…이(가) 이 브라우저를 디버깅하고 있습니다」 띠가 뜬다.
 *    그래서 **누를 때만 붙고 바로 뗀다**(회차 내내 붙어 있지 않는다).
 * ⚠️ 실패하면 **반드시 옛 방식(합성 클릭)으로 폴백한다.** 개발자 도구가 그 탭에 열려 있으면
 *    attach 가 거부되는데, 그때 수집이 통째로 죽으면 고장이 하나 더 느는 셈이다.
 * ⚠️ 끌 수 있다 — 팝업의 「🖱 진짜 입력으로 클릭」. 저장값 `trustedClick`(없으면 켬).
 * ─────────────────────────────────────────────────────────────────────────── */
let _trustedNote = '';       // 마지막 실패 사유(진단 보고용 · 60자)
// 🔴 v1.17.5 — 누를 때 잰 것. 진단 보고에만 쓰고 동작은 바꾸지 않는다.
let _clickHit = '';          // 그 좌표에 실제로 있던 것(태그.클래스>글자)
let _clickCovered = 0;       // 1 = 우리 버튼이 아니라 다른 것이 덮고 있었다
let _pagerAfter = '';        // 누른 직후의 현재 페이지 표식 — 'cur=2|qp=2|y=5600'

/* 🔴 v1.17.5 — 화면 안에서 한 칸 굴린다(요청 0건). 사람처럼 나눠 내려가려고 따로 뺐다. */
function scrollStep(px) {
  try { window.scrollBy(0, px); } catch (e) { /* 무시 */ }
  return Math.round(window.scrollY || window.pageYOffset || 0);
}

/* 🔴 v1.17.5 — 누른 직후의 페이지네이션 상태. '현재' 표식을 여러 모양으로 찾는다.
 *   ⚠️ 클래스 이름 한 가지에 걸면 네이버가 바꾸는 순간 죽는다 — 여러 모양을 함께 본다. */
function pagerState() {
  var cur = '', raw = '';
  var scopes = document.querySelectorAll('[class*="pagination"],[class*="paging"],[role="navigation"]');
  for (var s = 0; s < scopes.length && !cur; s++) {
    /* 🔴 v1.17.5 — **span 을 꼭 넣는다.** 대표 캡처로 확인: 현재 페이지만 `<a>` 가 아니라
     *   `<span class="pagination_btn_page__utqBz active">` 다. 나머지 번호는 `<a href="#">`.
     *   ⚠️ `a,button` 만 보면 「현재 페이지」를 영영 못 찾는다 — 이 함수를 만들 때 실제로
     *      그렇게 짰다가 캡처를 보고 고쳤다. 우리 옛 `pager` 목록에 1이 빠져 있던 것도 같은 이유다. */
    var c = scopes[s].querySelectorAll('a,button,span');
    for (var i = 0; i < c.length; i++) {
      var el = c[i];
      var ac = el.getAttribute('aria-current') || '';
      var cls = String(el.className || '');
      if (ac === 'page' || ac === 'true'
          || /active|current|selected|_on\b|--on\b|is-on/i.test(cls)) {
        /* 🔴 v1.17.6 — 2026-09-16 18:08 실측. 앞 4글자만 잘랐더니 `cur=현재페이` 가 나왔다.
         *   그 span 안에는 낭독기용 안내문(「현재페이지」)이 숫자 **앞에** 붙어 있다.
         *   ⇒ 글자를 자르지 말고 **숫자만** 뽑는다. 원문도 12자까지 같이 남겨,
         *      다음에 모양이 또 다르면 짐작하지 않고 눈으로 확인한다. */
        raw = String(el.textContent || '').replace(/\s+/g, '').slice(0, 12);
        var digits = raw.match(/\d+/g);
        cur = digits ? digits[digits.length - 1] : '';
        break;
      }
    }
  }
  var m = String(location.search || '').match(/pagingIndex=(\d+)/);
  /* 🔴 v1.17.6 — 클릭 **직후** 화면에 그려진 상품 ID 3개.
   *   종전 `domFirst` 는 29초 뒤 프로브 값이라 그 사이에 무슨 일이 있었는지 섞인다.
   *   이 셋이 1페이지 것과 다르면 **화면은 넘어간 것**이고, 우리가 읽는 자리(라우터)만 안 바뀐 것이다.
   *   ⇒ 그게 이 회차의 판가름이다. 요청은 0건 는다(이미 그려진 것을 읽을 뿐). */
  var first = [];
  try {
    var mids = document.querySelectorAll('a[href*="nvMid="]');
    for (var k = 0; k < mids.length && first.length < 3; k++) {
      var mm = /nvMid=(\d+)/.exec(String(mids[k].getAttribute('href') || ''));
      if (mm && first.indexOf(mm[1]) < 0) first.push(mm[1]);
    }
  } catch (e) { /* 무시 */ }
  return { cur: cur, raw: raw, qp: m ? m[1] : '',
           y: Math.round(window.scrollY || window.pageYOffset || 0), first: first };
}

/* 사람처럼 훑어 내려간다 — 여덟 번에 나눠 굴리고 사이에 잠깐 멈춘다. */
async function humanScrollDown(tabId) {
  try {
    for (let i = 0; i < 8; i++) {
      await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN', func: scrollStep,
        args: [500 + Math.floor(Math.random() * 320)],
      });
      await sleep(180 + Math.floor(Math.random() * 260));
    }
  } catch (e) { /* 굴리기 실패는 치명적이지 않다 — 그대로 진행한다 */ }
}

/* 누른 직후 상태를 읽어 진단 문자열로 담아 둔다(실패해도 무시). */
async function readPagerState(tabId) {
  try {
    const [ps] = await chrome.scripting.executeScript({
      target: { tabId }, world: 'MAIN', func: pagerState,
    });
    const r = (ps && ps.result) || {};
    // v1.17.6 — 숫자·원문·직후 상품 ID 3개를 함께 남긴다(서버 500자 한도 안에 들도록 짧게).
    _pagerAfter = 'cur=' + (r.cur || '-') + '/' + (r.raw || '-')
                + '|qp=' + (r.qp || '-') + '|y=' + (r.y || 0)
                + '|f=' + ((r.first || []).join(',') || '-');
  } catch (e) { _pagerAfter = 'read-error'; }
}

function dbgAttach(tabId) {
  return new Promise((res, rej) => {
    try {
      chrome.debugger.attach({ tabId }, '1.3', () => {
        const e = chrome.runtime.lastError;
        e ? rej(new Error(e.message || 'attach')) : res();
      });
    } catch (e) { rej(e); }
  });
}
function dbgSend(tabId, method, params) {
  return new Promise((res, rej) => {
    try {
      chrome.debugger.sendCommand({ tabId }, method, params, (r) => {
        const e = chrome.runtime.lastError;
        e ? rej(new Error(e.message || method)) : res(r);
      });
    } catch (e) { rej(e); }
  });
}
function dbgDetach(tabId) {
  return new Promise((res) => {
    try {
      chrome.debugger.detach({ tabId }, () => { void chrome.runtime.lastError; res(); });
    } catch (e) { res(); }
  });
}

/** 표준 입력 경로로 페이지 버튼을 누른다. 눌렀으면 가지 이름, 못 눌렀으면 ''(폴백하라는 뜻). */
async function trustedClickToPage(tabId, target) {
  let attached = false;
  try {
    if (!chrome.debugger) { _trustedNote = 'no-debugger-api'; return ''; }
    /* 🔴 v1.17.5 — 대표 지시(「완전 실사용자 기반으로 움직이면 될 거 같은데」).
     *   사람은 상품을 훑어 **내려가서** 아래쪽 번호 줄에 닿는다. 우리는 여태
     *   `scrollIntoView` 로 버튼을 화면 한가운데로 **순간이동**시킨 뒤 그 점을 눌렀다.
     *   ⚠️ 네이버에 보내는 요청은 0건 는다 — 화면을 굴리는 것뿐이다.
     *   ⚠️ 게으르게 그려지는 부분이 있으면 이 동안에 그려진다(그 자체가 이득). */
    /* 🔴🔴 v1.17.7 — **순서를 뒤집는다. 이것이 이번 실패의 유력한 범인이다.**
     *
     *   종전 순서: 굴리고 → **좌표를 재고** → `dbgAttach` → 그 좌표를 누른다.
     *   그런데 `dbgAttach` 하는 순간 크롬이 **「디버깅하고 있습니다」 띠**를 화면 맨 위에 붙인다.
     *   띠가 붙으면 **콘텐츠 영역 전체가 그 높이만큼 아래로 밀린다.**
     *   ⇒ 우리가 잰 좌표는 **띠가 없던 때의 좌표**다. 버튼 높이는 26px 인데 띠는 그보다 두껍다.
     *     그래서 **정확히 빗나간다** — 2026-09-16 18:22 경주빵 회차가 그 모양이었다
     *     (`hit` 은 그 버튼인데 `cur` 이 1 그대로 · 상품 ID 도 불변).
     *   ⚠️ `hit`/`cov` 는 **좌표를 잰 시점**의 확인이지 **누른 시점**의 확인이 아니다.
     *      그래서 「cov=0 이니 안 덮였다」가 「잘 눌렀다」를 뜻하지 않는다. 내가 그렇게 읽었다.
     *   ⇒ **붙이고 나서 굴리고 재고 누른다.** 띠가 이미 떠 있는 화면의 좌표를 쓴다.
     */
    await dbgAttach(tabId);
    attached = true;
    await sleep(350);                 // 띠가 붙고 화면이 자리를 잡을 틈
    await humanScrollDown(tabId);
    const [loc] = await chrome.scripting.executeScript({
      target: { tabId }, world: 'MAIN', func: pagerLocate, args: [target],
    });
    const spot = loc && loc.result;
    if (!spot) { _trustedNote = 'no-spot'; return ''; }   // 버튼을 못 찾음 — 합성 클릭도 못 찾는다
    _clickHit = spot.hit || '';
    _clickCovered = spot.covered ? 1 : 0;
    const base = { x: spot.x, y: spot.y, button: 'left' };
    // 사람 손과 같은 순서 — 움직이고, 누르고, 뗀다.
    await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...base, type: 'mouseMoved', buttons: 0, clickCount: 0 });
    await sleep(40 + Math.floor(Math.random() * 70));
    await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...base, type: 'mousePressed', buttons: 1, clickCount: 1 });
    await sleep(30 + Math.floor(Math.random() * 60));
    await dbgSend(tabId, 'Input.dispatchMouseEvent', { ...base, type: 'mouseReleased', buttons: 0, clickCount: 1 });
    // ⚠️ 떼자마자 detach 하지 않는다 — 화면이 그 클릭을 처리할 틈을 준다.
    await sleep(200);
    /* 🔴 v1.17.5 — **누른 직후 「지금 몇 페이지인가」를 찍는다.**
     *   여태 보고에는 번호 줄 목록(pager)만 있고 「현재」 표식이 없어,
     *   「눌렸는데 화면이 안 움직였다」와 「클릭이 헛나갔다」를 가를 수 없었다.
     *   ⚠️ 여기서 재는 것이 핵심이다 — 29초 뒤 프로브에서 재면 이미 두 축이 섞인다. */
    await readPagerState(tabId);
    _trustedNote = '';
    return spot.branch || 'num';
  } catch (e) {
    _trustedNote = String((e && e.message) || e).slice(0, 60);
    return '';
  } finally {
    if (attached) await dbgDetach(tabId);
  }
}

/** 표준 입력 경로를 쓸지 — 저장값이 없으면 **켬**이 기본이다. */
async function trustedEnabled() {
  try {
    const { trustedClick } = await chrome.storage.local.get('trustedClick');
    return trustedClick === undefined ? true : !!trustedClick;
  } catch (e) { return true; }
}

/** 검색창으로 들어갈지 — 저장값이 없으면 **켬**이 기본이다(v1.16.0 의 목적). */
async function searchEntryEnabled() {
  try {
    const { searchEntry } = await chrome.storage.local.get('searchEntry');
    return searchEntry === undefined ? true : !!searchEntry;
  } catch (e) { return true; }
}

/** 작업 탭에서 페이지 버튼을 누른다. 눌렀으면 true. */
let _staleReported = false;  // 키워드당 1회만 보고
let _lastClickBranch = '';   // 어느 가지('num'·'next'·'loose')로 눌렀나 — 진단 보고에 싣는다
let _lastClickHow = '';      // v1.15.0 — 'trusted'(표준 입력) · 'synth'(합성) · ''(못 누름)
async function clickToPage(tabId, target) {
  // v1.15.0 — 먼저 표준 입력 경로, 안 되면 종전 합성 클릭으로 폴백.
  //   ⚠️ 폴백을 지우지 말 것 — 개발자 도구가 그 탭에 열려 있으면 attach 가 거부된다.
  /* 🔴🔴 v1.17.7 — **「눌렀다」를 「먹혔다」로 읽지 않는다.**
   *   종전에는 표준 입력 이벤트를 **보내기만 하면** 성공으로 보고 그대로 끝냈다.
   *   그래서 화면이 1페이지 그대로인데도 합성 클릭 폴백이 **한 번도 돌지 않았다**
   *   (2026-09-16 18:22 경주빵: `cur=1` 인데 성공 처리). 폴백을 만들어 두고 못 쓴 셈이다.
   *   ⇒ 이제 누른 직후 **현재 페이지 번호**를 보고, 그것이 목표와 다르면 합성 클릭을 한 번 더 한다.
   *   ⚠️ 번호를 **읽지 못한 화면에서는 폴백하지 않는다** — 이미 넘어간 뒤 또 누르면
   *      3페이지로 가 버린다. 모를 때는 건드리지 않는 쪽이 안전하다.
   *   ⭐ 합성 클릭은 종전 경로에서 **화면을 실제로 깨운 실적이 있다**(요청이 나가 418 을 맞았다).
   *      「진짜 입력이 언제나 낫다」는 가정은 이번 측정으로 흔들렸다.
   */
  if (await trustedEnabled()) {
    const br = await trustedClickToPage(tabId, target);
    if (br) {
      const cur = (/cur=(\d+)/.exec(_pagerAfter || '') || [])[1] || '';
      if (cur && cur !== String(target)) {
        _trustedNote = (_trustedNote ? _trustedNote + '|' : '') + 'no-move@' + cur;
        // 아래 합성 클릭으로 떨어진다(일부러 return 하지 않는다).
      } else {
        _lastClickBranch = br;
        _lastClickHow = 'trusted';
        _navMode.how.trusted += 1;
        return true;
      }
    }
  }
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId }, world: 'MAIN', func: pagerClick, args: [target],
    });
    _lastClickBranch = (res && res.result) || '';
    if (res && res.result) { _lastClickHow = 'synth'; _navMode.how.synth += 1; }
    // v1.17.7 — 합성 클릭 뒤의 현재 페이지도 같은 자로 남긴다(둘 중 무엇이 먹었는지 보이게).
    if (res && res.result) { await sleep(300); await readPagerState(tabId); }
    return !!(res && res.result);
  } catch (e) {
    _lastClickBranch = '';
    _lastClickHow = '';
    return false;   // 주입 실패도 폴백 대상
  }
}

/* ⛔ routerPush 는 v1.13.1 에서 **삭제**했다(2026-09-15 22:02 실측).
 *   `라우터.push(query+pagingIndex)` 는 네이버가 쓰는 주소 모양(adQuery·origQuery·pagingSize…)이 아니라
 *   `?query=키워드&pagingIndex=2` 를 만들고, Next 가 그 데이터를 못 받으면 **주소창 이동으로 되돌린다**(하드 내비게이션).
 *   그래서 퍼즐(보안 확인)이 뜬 세 건(21:17·21:18·22:02)의 주소가 전부 그 모양이었다 = 주소 이동과 같은 표식.
 *   클릭이 만든 주소(adQuery…)는 29초를 기다려도 퍼즐이 안 떴다. ⇒ 클릭 뒤엔 **기다리기만** 한다. 되살리지 말 것. */

/** 화면 안에서 실행 — 「왜 안 넘어갔나」를 서버에 남기기 위한 상태 조각(값 없음 · 구조만). */
function navProbe() {
  var out = {};
  // v1.13.0 — 화면이 주고받은 응답 요약(net_tap.js). 값은 안 싣는다 — 경로 끝·상태·크기·페이지·ID 앞 3개.
  try {
    var T = window.__mcTap;
    if (!T) out.tap = 'none';
    else {
      var now = Date.now();
      var one = function (e) {
        var s = [Math.round((now - (e.at || now)) / 1000) + 's', 'p' + (e.page || 0), e.status, e.size,
                 String(e.path || '').slice(-28)].join('|');
        if (e.ids) s += '|' + e.ids.join(',');
        // v1.14.0 — 거절 응답은 **본문 앞머리 40자**를 함께 싣는다.
        //   9/16 실측에서 `p2|418|2657` 을 받고도 그 2,657자가 「보안 확인」 퍼즐인지 차단 안내문인지
        //   그냥 오류인지 가를 수 없었다. net_tap 은 이미 head 를 갖고 있었는데(net_tap.js) 여기서 버렸다.
        if (e.status >= 400 && e.head) s += '|' + String(e.head).replace(/\s+/g, ' ').slice(0, 40);
        return s;
      };
      // v1.14.0 — 서버가 본문을 500자에서 자르므로(collector.py) **거절 응답이 먼저 살아남게** 고른다.
      //   종전엔 slice(-6) 이라 200 응답이 자리를 먹고 정작 볼 4xx 가 밀릴 수 있었다.
      var ms = T.misses || [];
      var bad = ms.filter(function (e) { return (e.status | 0) >= 400; }).slice(-3);
      var rest = ms.filter(function (e) { return (e.status | 0) < 400; }).slice(-3);
      out.tap = { n: (T.items || []).length, m: ms.length,
                  items: (T.items || []).slice(-4).map(one), misses: bad.concat(rest).map(one) };
    }
  } catch (e) { out.tap = 'err'; }
  // v1.14.0 — **그 순간의 창·문서 상태**. 지금까지 전부 코드 추론이었고 한 번도 잰 적이 없다
  //   (9/16 반박 검증 지적). 다섯 값을 11글자로 압축해 싣는다 — 값이 아니라 예/아니오다.
  //   f=창이 앞에 있었나 · v=화면에 보였나 · a=사람 입력(있었던 적/지금) · w=자동화 표식 · r=직전 주소
  try {
    var uact = navigator.userActivation || {};
    out.env = 'f' + (document.hasFocus() ? 1 : 0)
            + 'v' + (document.visibilityState === 'visible' ? 1 : 0)
            + 'a' + (uact.hasBeenActive ? 1 : 0) + (uact.isActive ? 1 : 0)
            + 'w' + (navigator.webdriver ? 1 : 0)
            + 'r' + (document.referrer ? 1 : 0);
  } catch (e) { out.env = 'err'; }
  try { out.href = String(location.href).slice(0, 100); } catch (e) {}
  try {
    var rt = window.next && window.next.router;
    out.router = !!rt;
    if (rt) { out.route = rt.route; out.q = (rt.query || {}).pagingIndex || ''; }
  } catch (e) { out.router = 'err'; }
  try {
    var scopes = document.querySelectorAll('[class*="pagination"],[class*="paging"],[role="navigation"]');
    out.scopes = scopes.length;
    var nums = [];
    for (var s = 0; s < scopes.length && nums.length < 12; s++) {
      var cands = scopes[s].querySelectorAll('a,button');
      for (var i = 0; i < cands.length && nums.length < 12; i++) {
        var t = (cands[i].textContent || '').trim();
        if (t) nums.push(t.slice(0, 6) + (cands[i].tagName === 'A' ? '' : '(b)'));
      }
    }
    out.pager = nums;
  } catch (e) { out.scopes = 'err'; }
  // v1.11.6 — 화면에 실제로 그려진 상품 링크(공개 상품 주소 · 값은 호스트+ID 조각만).
  //   라우터 데이터가 안 바뀌어도 화면이 바뀌었다면 다음 판은 DOM 을 읽어야 한다 — 그 설계 근거.
  try {
    var mids = document.querySelectorAll('a[href*="nvMid="]');
    var ss = document.querySelectorAll('a[href*="smartstore.naver.com/"]');
    var cat = document.querySelectorAll('a[href*="/catalog/"]');
    out.dom = { nvMid: mids.length, smartstore: ss.length, catalog: cat.length };
    var first = [];
    for (var m = 0; m < mids.length && first.length < 3; m++) {
      var h = String(mids[m].getAttribute('href') || '');
      var mm = /nvMid=(\d+)/.exec(h);
      if (mm && first.indexOf(mm[1]) < 0) first.push(mm[1]);
    }
    out.domFirst = first;
  } catch (e) { out.dom = 'err'; }
  return out;
}

/** v1.13.1 — 「화면이 어떤 응답을 받았나」(net_tap 요약)를 서버에 따로 한 건 남긴다.
 *  STALE·BLOCK_TEXT·판독 실패·NO_PAGER 네 갈래 모두에서 부른다 — 22:02 퍼즐 회차는 BLOCK_TEXT 로 끝나
 *  tap 요약이 서버에 안 남았다. 진단용이라 실패해도 수집을 멈추지 않는다. */
async function tapReport(tabId, keyword, pagingIndex, why, errLabel) {
  try {
    const [pr] = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: navProbe });
    const probe = (pr && pr.result) || {};
    const tap = probe.tap === undefined ? 'none' : probe.tap;
    await reportBlocked({ keyword, pagingIndex, err: errLabel || 'TAP_PROBE(화면이 받은 응답 요약)',
                          href: probe.href || '',
                          body: JSON.stringify({ why: why, q: probe.q || '', env: probe.env || '', tap: tap }),
                          note: '진단 — 차단 아님. 클릭 뒤 화면이 어떤 응답을 받았나' });
  } catch (e) { /* 진단 실패는 무시 */ }
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
        // ⚠️ v1.17.1 — 「쇼핑이 아니면 튕긴 것」이 아니다. 사람 경로로 들어가느라 네이버 첫 화면·
        //    통합검색을 거치므로 `onEntryHost` 로 판정한다(15:07 오판 사고).
        if (u && !onEntryHost(u)) { clearInterval(iv); resolve(); return; }
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
async function fetchPage(keyword, pagingIndex, prevIds) {
  // ⚠️ v1.17.4 — `let` 이다. 쇼핑 탭이 `target="_blank"` 라 진입 중에 **탭이 바뀔 수 있고**,
  //    그 뒤 읽기·클릭은 반드시 **바뀐 탭**에서 해야 한다(안 그러면 통합검색을 읽는다).
  let tabId = await ensureWorkTab();
  // ⭐ 2026-09-12 — **페이지를 주소창으로 넘기지 않는다.**
  //
  // 종전엔 장마다 `chrome.tabs.update({url})` 로 이동했다. 그건 **주소창에 붙여넣고
  // 엔터를 치는 것과 같아서**, 어디서 왔는지(referrer)가 비어 있고 클릭도 없다.
  // 2페이지를 주소창에 쳐서 여는 사람은 없다 — 우리는 그걸 **시간당 160번** 했다.
  //
  // 이제 이렇게 한다:
  //   · 1페이지 = 주소로 연다(사람이 검색창에 치는 것과 같은 **1회**)
  //   · 2페이지부터 = **화면 안의 페이지 버튼을 실제로 클릭**한다
  // ⚠️ 클릭이 안 되면(버튼을 못 찾으면) **옛 방식으로 폴백**하고 그 사실을 서버에 알린다.
  //    현장에서 자동으로 판명되게 — 사람이 확인하러 들어가지 않아도 되게.
  if (pagingIndex <= 1) {
    // v1.16.0 — 먼저 **검색창에 쳐서** 들어간다(사람과 같은 순서). 안 되면 종전 주소 열기.
    //   ⚠️ 폴백을 지우지 말 것 — 네이버가 검색창 모양을 바꾸면 수집이 통째로 멈춘다.
    let entered = false;
    if (await searchEntryEnabled()) {
      const use = await humanEntry(tabId, keyword);
      if (use) {
        entered = true;
        tabId = use;                      // ⚠️ 새 탭을 이어받았으면 여기서 갈아탄다
        if (_entryVia) _navMode.entry[_entryVia] += 1;
      }
    }
    if (!entered) {
      // 사람 주소와 같은 최소 형태. pagingSize·productSet·viewType 을 붙이지 않는다.
      const url = 'https://search.shopping.naver.com/search/all'
        + `?query=${encodeURIComponent(keyword)}`;
      await chrome.tabs.update(tabId, { url });
      await waitNavigated(tabId, encodeURIComponent(keyword));
      _navMode.entry.url += 1;
    }
    _navMode.url += 1;
  } else {
    _clickedAt = Date.now();   // v1.13.0 — 이 시각 뒤에 도착한 응답이 「이 클릭의 답」이다
    const clicked = await clickToPage(tabId, pagingIndex);
    if (clicked) {
      _navMode.click += 1;
      await waitNavigated(tabId, `pagingIndex=${pagingIndex}`);
    } else {
      // 버튼을 못 찾았다 — v1.11.3: **주소 이동으로 가지 않는다**(pagingIndex 주소 = 차단 표식, 9/15 실측).
      // 라우터 이동(SPA)을 시도하고, 그것도 없으면 이 키워드는 여기까지만 담는다.
      _navMode.fallback += 1;
      if (!_navMode.reported) {
        _navMode.reported = true;
        reportBlocked({ keyword, pagingIndex, err: 'NO_PAGER(페이지 버튼 못 찾음)',
                        note: '주소 이동·라우터 이동 안 함(v1.13.1) — 이 키워드는 여기까지만 담음' });
        await tapReport(tabId, keyword, pagingIndex, 'NO_PAGER');
      }
      return { total: 0, list: [] };   // 이 키워드는 여기까지
    }
  }

  // ⚠️ 고정 시간만 기다리고 한 번 읽던 것을 **값이 나올 때까지 되읽기**로 바꾼다
  //    (2026-08-11 실사고: 정상 페이지를 3초 만에 읽어 '데이터 없음' → 차단으로 오판 →
  //     60개 회차 전멸 + 6시간 정지. 서버 통계의 '5개·9개 수집' 키워드도 같은 원인).
  //    기다리는 대상이 '시간'이 아니라 '데이터'라, 페이지가 느린 날에도 성립한다.
  let out = null, lastErr = '';
  // ⭐ 2026-09-15 — 클릭으로 넘긴 뒤엔 **내용이 실제로 바뀔 때까지** 기다린다(시간이 아니라 내용).
  //    v1.11.0·v1.11.1 실측: 클릭 9회가 전부 「됐다」로 셌는데 읽은 건 9번 다 1페이지였다
  //    (중복 제외 = 담긴 수 × 9). 첫 상품이 이전 페이지와 같으면 '아직'이다.
  //    끝까지 안 바뀌면 그 장만 주소 이동으로 되돌리고(stale) 서버에 알린다 — 수집이 멈추는 것보다 낫다.
  // ⚠️ v1.11.3 — 안 넘어가도 **주소 이동으로 되돌리지 않는다.** v1.11.2 가 그 폴백을 탔다가
  //    `?query=…&pagingIndex=2` 주소를 연 1초 뒤 캡차(19:43:50). 1페이지 주소는 같은 날 네 번 통과했다.
  //    ⇒ 「주소창에 pagingIndex 를 붙여 여는 것」이 차단 표식이다(9/12 · 8/28 과 같은 결론).
  //    대신 라우터 이동(사람 클릭이 내부적으로 하는 것)을 한 번 더 시도하고, 그래도 안 바뀌면
  //    그 키워드는 여기까지만 담고 끝낸다. 왜 안 넘어갔는지는 navProbe 로 서버에 남긴다.
  let staleTries = 0;
  const tries = pagingIndex > 1 ? (CFG.readTriesPaged || CFG.readTries) : CFG.readTries;
  for (let attempt = 0; attempt < tries; attempt++) {
    let cur;
    try { cur = await chrome.tabs.get(tabId); } catch (e) { throw new Error('작업 탭이 사라졌습니다'); }
    // 주소가 검색 도메인을 벗어났으면 그건 진짜 차단(캡차·로그인 유도)
    if (isBlockedUrl(cur && cur.url)) {
      // 주소가 아예 다른 곳으로 튕겼다 — 그 주소 자체가 증거다.
      reportBlocked({ keyword, pagingIndex, err: 'REDIRECT(검색 도메인 이탈)',
                      href: (cur && cur.url) || '', title: (cur && cur.title) || '',
                      note: '주소 이탈' });
      throw new Error('BLOCKED:' + cur.url);
    }

    const [res] = await chrome.scripting.executeScript({
      target: { tabId }, world: 'MAIN', func: pageExtract, args: [{ page: pagingIndex, since: _clickedAt }],
    });
    out = res && res.result;
    if (out && !out.err) {
      if (pagingIndex > 1 && !pageChanged(out.list, prevIds)) {
        // 내용이 이전 페이지 그대로 — 아직 안 넘어간 것이다.
        staleTries += 1; lastErr = 'STALE_PAGE';
        // ⛔ v1.13.1 — 여기서 라우터 이동(routerPush)을 걸던 것을 **뺐다**. 그 이동이 주소창 이동으로
        //    되돌아가 퍼즐을 불렀다(22:02 실측 · 주소 `?query=…&pagingIndex=2`). 클릭 뒤엔 기다리기만 한다.
        await sleep(CFG.readGapMs);
        continue;
      }
      if (pagingIndex > 1) _navMode.src[out.src || '?'] = (_navMode.src[out.src || '?'] || 0) + 1;
      return { total: out.total || 0, list: out.list || [] };
    }
    // 차단 '문구'를 실제로 본 경우에만 차단으로 단정한다.
    // ⚠️ 이때도 무엇을 봤는지 반드시 남긴다 — 종전엔 차단 분기가 증거를 안 남겨
    //    팝업 진단칸이 정작 필요할 때 비어 있었다(2026-08-11).
    if (out && out.err === 'BLOCK_TEXT') {
      const ev = { keyword, pagingIndex, at: new Date().toISOString(), err: 'BLOCK_TEXT(차단 문구 확인)',
                   title: out.title || '', href: out.href || '', body: out.body || '' };
      chrome.storage.local.set({ readFail: ev });
      reportBlocked({ ...ev, note: '차단 문구' });     // 서버도 알게 한다(기다리지 않는다)
      await tapReport(tabId, keyword, pagingIndex, 'BLOCK_TEXT');   // v1.13.1 — 막히기 직전 화면이 받은 응답
      throw new Error(`BLOCKED:${out.title || out.href}`);
    }
    lastErr = (out && out.err) || '주입 실패';
    await sleep(CFG.readGapMs);
  }

  if (lastErr === 'STALE_PAGE') {
    // 클릭도 라우터 이동도 내용을 못 바꿨다 — 이 키워드는 여기까지만 담고 끝낸다(주소 이동 금지).
    _navMode.stale += 1;
    let probe = {};
    try {
      const [pr] = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: navProbe });
      probe = (pr && pr.result) || {};
    } catch (e) { probe = { probe: 'inject-error' }; }
    // ⚠️ 서버는 body 를 500자에서 자른다(collector.py) — 짧은 값이 앞에 오게 순서를 정하고,
    //    응답 요약(tap)은 **따로 한 건** 더 보낸다(v1.13.0). 21:39 회차의 prev/got 이 잘려 나갔던 교훈.
    delete probe.tap;
    // ⚠️ v1.17.5 의 세 값(hit·cov·after)을 **앞쪽**에 둔다 — 서버가 body 를 500자에서 자른다.
    const front = { click: _lastClickBranch, how: _lastClickHow, tnote: _trustedNote || '',
                    hit: _clickHit || '', cov: _clickCovered, after: _pagerAfter || '',
                    entry: _navMode.entry, enote: _entryNote || '', via: _entryVia || '', prev: (prevIds || []).length,
                    got: organicIds((out && out.list) || []).length, src: (out && out.src) || '' };
    probe = Object.assign(front, probe);
    if (!_staleReported) {
      _staleReported = true;
      reportBlocked({ keyword, pagingIndex, err: 'STALE_PAGE(클릭 뒤 내용 불변)',
                      href: probe.href || '', body: JSON.stringify(probe),
                      note: '주소 이동·라우터 이동 안 함 — 이 키워드는 여기까지만 담음' });
      await tapReport(tabId, keyword, pagingIndex, 'STALE');
    }
    return { total: 0, list: [] };
  }

  // 여기까지 왔으면 '차단'이 아니라 '판독 실패'다 — 6시간 정지시키지 않고 다음 회차에 재시도한다.
  // 무엇을 봤는지 남겨 둬야 다음에 사람 손 안 빌리고 원인을 가른다.
  const ev = { keyword, pagingIndex, at: new Date().toISOString(),
               err: lastErr, title: (out && out.title) || '', href: (out && out.href) || '',
               body: (out && out.body) || '' };
  chrome.storage.local.set({ readFail: ev });
  // ⚠️ 이건 차단이 아니라 **판독 실패**다. 그래도 서버에 남긴다 —
  //    「막혔다」와 「못 읽었다」는 다른 축이고, 섞이면 또 사흘을 쓴다.
  reportBlocked({ ...ev, note: '판독 실패(차단 아님)' });
  await tapReport(tabId, keyword, pagingIndex, lastErr);
  throw new Error(`판독 실패(${lastErr}) — 차단 아님, 다음 회차 재시도`);
}

/* (isAdItem·hasAdHint·toProduct 는 rank_rules.js 로 이사 — 2026-09-02 신고 #253.
   광고 판별이 눈멀어 광고가 순번을 먹던 사고의 수정과 그 회귀 테스트가 거기 있다.) */

/** 키워드 1건을 300위까지 수집
 *
 *  ⚠️ 순위는 **실제로 받은 개수로 누적**한다(종전엔 `(페이지-1)×pageSize+1` 로 계산).
 *     페이지가 요청한 개수를 그대로 주지 않는 경우(광고 제외·마지막 페이지 등)
 *     고정 계산은 순위를 통째로 어긋나게 만든다. 누적이면 어떤 경우에도 맞다. */
/* 🎯 조기 종료 목표 — 서버 `/keywords` 의 `targets` (2026-09-18 대표 확정).
 *
 *   「그 키워드로 찾아야 할 상품을 **다 찾았으면** 거기서 멈추고 다음 키워드로 간다」.
 *   실측(진단 #301): 목표를 다 찾은 364개 키워드가 끝난 페이지 = **중앙값 1 · 최대 8**.
 *   11장씩 긁던 4,004장이 **783장**이면 된다(80% 절감).
 *
 *   ⚠️ **목표가 없으면 종전대로 깊이까지 간다.** 서버가 안 주거나(구버전) 그 키워드에
 *      nvMid 가 채워진 상품이 하나도 없으면 여기 키가 없다 — 그때는 아무것도 안 바뀐다.
 *   ⚠️ **1페이지는 무조건 끝까지 읽는다.** 목표를 1위에서 찾았다고 그 페이지를 덜 담으면
 *      경쟁사 목록·분석이 통째로 빈다. 멈추는 것은 **다음 페이지로 넘어가는 일**뿐이다.
 */
let _targets = {};          // { 키워드: [nvMid, …] } — 회차마다 서버 값으로 갈아끼운다

function targetsFor(keyword) {
  const t = _targets && _targets[keyword];
  return Array.isArray(t) && t.length ? t.map(String) : null;
}

/** 지금까지 담은 상품 안에 목표가 전부 들어왔나 */
function allTargetsFound(products, want) {
  if (!want || !want.length) return false;
  const got = new Set((products || []).map(
    (p) => String(p.nvMid || p.id || p.productId || '')));
  for (let i = 0; i < want.length; i++) {
    if (!got.has(String(want[i]))) return false;
  }
  return true;
}

async function collectKeyword(keyword) {
  _navMode = { url: 0, click: 0, fallback: 0, stale: 0, reported: _navMode.reported, src: {},
               how: { trusted: 0, synth: 0 },
               entry: { portal: 0, shopbox: 0, url: 0 } };   // 키워드마다 새로 센다
  _clickedAt = 0;
  _staleReported = false; _lastClickBranch = ''; _lastClickHow = '';
  // 순번 부여의 실체는 rank_rules.takeOrganic 하나다 — 광고 제외가 seenIds 중복 처리보다
  // 먼저인 순서까지가 계약이고, node 회귀 테스트가 그 계약을 검사한다(신고 #253 후속).
  const st = {
    products: [], seenIds: new Set(), maxRank: CFG.maxRank,
    adSkipped: 0, dupSkipped: 0, adHintMissed: 0,
    fp: {},   // 광고 필드 지문 집계(v1.10.3) — 값 없이 필드 유무·호스트만. 서버 meta.adFp 로 간다.
    // 광고 원본 1건을 남겨 둔다 — 다음에 판별 규칙을 넓힐 때 추측 대신 이걸 본다.
    onFirstAd: (item) => {
      chrome.storage.local.get('rawSampleAd').then((o) => {
        if (!o.rawSampleAd) {
          chrome.storage.local.set({ rawSampleAd: { keyword, at: new Date().toISOString(), item } });
        }
      });
    },
  };
  let total = 0;
  let rawCount = 0;            // 걸러내기 전 원본 개수 — 사후 재구성용(신고 #253 교훈)
  const pages = Math.min(CFG.pagesPerKeyword, CFG.maxPages);
  let prevIds = [];   // 이전 장의 광고 제외 상품 ID — 다음 장이 실제로 바뀌었는지 집합으로 본다(v1.11.5)
  for (let i = 1; i <= pages; i++) {
    const { total: t, list } = await fetchPage(keyword, i, prevIds);
    if (i === 1) total = t;
    if (!list.length) break;
    rawCount += list.length;
    prevIds = organicIds(list);
    // ⚠️ 첫 키워드 첫 상품의 '원본 JSON'을 저장해 둔다. toProduct 의 필드명 가정
    //    (p.productTitle·p.category1Name 등)이 실제 네이버 응답과 맞는지 내일 첫 실행 때
    //    팝업에서 눈으로 검증하기 위함(맞으면 매핑 확정, 다르면 즉시 교정).
    if (i === 1 && list[0]) {
      chrome.storage.local.set({ rawSample: { keyword, at: new Date().toISOString(), item: list[0] } });
    }
    RR.takeOrganic(list, st);
    // 🎯 조기 종료 — 이 페이지까지 담은 것 안에 목표가 전부 들어왔으면 여기서 끝낸다.
    //    ⚠️ 이 판정은 **페이지를 다 담은 뒤**에 한다(위 takeOrganic 다음). 담기 전에
    //       끊으면 그 페이지가 반만 들어가 순위·경쟁사가 어긋난다.
    const _want = targetsFor(keyword);
    if (_want && allTargetsFound(st.products, _want)) {
      st.stoppedEarly = { page: i, targets: _want.length, kept: st.products.length };
      break;
    }
    if (st.products.length >= CFG.maxRank) break;   // 목표 깊이 도달
    // 마지막 페이지 판정 — 설정값(80)이 아니라 화면 최소 페이지 크기(40) 미만일 때만.
    // 페이지가 pagingSize=80 을 무시하고 40씩 그려도 여기서 끊기지 않고 다음 장으로 간다.
    if (list.length < 40) break;
    if (i < pages) await sleep(jitter());
  }
  // 지문은 많아야 열댓 종류다 — 상위 20개만(키워드 하나 meta 가 커지지 않게).
  const adFp = Object.entries(st.fp || {}).sort((a, b) => b[1] - a[1]).slice(0, 20)
    .reduce((o, [k, v]) => { o[k] = v; return o; }, {});
  await chrome.storage.local.set({
    lastAdStat: { keyword, at: new Date().toISOString(), kept: st.products.length,
                  ads: st.adSkipped, dup: st.dupSkipped, hint: st.adHintMissed, raw: rawCount, fp: adFp },
  });
  return { total, products: st.products, adSkipped: st.adSkipped,
           dupSkipped: st.dupSkipped, adHintMissed: st.adHintMissed, rawCount, adFp,
           // 조기 종료했으면 그 사실을 서버가 알아야 한다 — 「깊이를 덜 판 것」과
           // 「목표를 찾아 멈춘 것」은 완전히 다른 일이고, 섞이면 절감을 못 잰다.
           stoppedEarly: st.stoppedEarly || null };
}

/* 🔴🔴 v1.17.8 — **세 번째 그물: 직전 회차와 결과가 똑같으면 올리지 않는다.**
 *
 *   2026-09-17 00:00~11:00 에 서로 다른 12개 키워드가 **같은 상품 32개**를 올렸고,
 *   오류도 막힘 보고도 없이 9시간을 갔다. 그물이 하나도 없었기 때문이다.
 *   앞의 둘(검색창이 키워드를 기다린다 · 주소에 키워드가 있는가)이 뚫려도
 *   여기서 잡힌다 — **다른 키워드가 같은 목록을 내놓는 일은 정상적으로 일어나지 않는다.**
 *
 *   ⚠️ 같은 키워드를 다시 재는 것은 정상이다(값이 같아도 된다) — 그래서 키워드가 **다를 때만** 막는다.
 *   ⚠️ 막는 데서 그치지 않고 **서버에 사유를 알린다**. 조용히 건너뛰면 오늘 사고의 재판이다.
 *   ⚠️ 상품이 없는 회차(0개)는 비교하지 않는다 — 「둘 다 0개」는 흔하고 오염이 아니다.
 */
let _lastUp = { keyword: '', sig: '' };

function uploadSignature(products) {
  const ids = (products || []).map((p) => String(p.nvMid || p.id || p.productId || ''));
  return ids.length ? ids.length + ':' + ids.join(',') : '';
}

async function uploadKeyword(token, keyword, payload) {
  const sig = uploadSignature(payload.products);
  if (sig && _lastUp.sig === sig && _lastUp.keyword && _lastUp.keyword !== keyword) {
    const note = 'same-as@' + String(_lastUp.keyword).slice(0, 20) + '|n' + (payload.products || []).length;
    try {
      await reportBlocked({ keyword, pagingIndex: 1, err: 'SAME_AS_PREV(직전 키워드와 결과가 동일)',
                            href: '', body: JSON.stringify({ prevKeyword: _lastUp.keyword,
                              n: (payload.products || []).length, via: _entryVia || '', enote: _entryNote || '' }),
                            note: '검색이 안 바뀐 것으로 본다 — 이 회차는 올리지 않는다' });
    } catch (e) { /* 보고 실패가 차단을 막지는 않는다 */ }
    await log(`⛔ 직전 키워드와 결과가 같아 올리지 않음 (${note})`);
    throw new Error('업로드 취소 — 직전 회차와 동일한 결과');
  }
  const res = await fetch(`${CFG.serverBase}/api/collector/serp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Collector-Token': token },
    body: JSON.stringify({
      keyword, total: payload.total, products: payload.products,
      // 사후 재구성용 메타(신고 #253 교훈 — 서버 저장본에서 광고 증거가 사라져
      // 「광고 0건」이라는 거짓 정상을 봤다). 구서버는 이 필드를 몰라도 무시한다.
      meta: {
        collectorVersion: (chrome.runtime.getManifest && chrome.runtime.getManifest().version) || '',
        rankPolicy: 'organic-v3(ad:legacy-or-adId+adType+adcrUrl@ader)',
        pageSize: CFG.pageSize, productSet: 'total', sort: 'rel',
        // 2026-09-12 — 페이지를 **어떻게** 넘겼는지. 클릭이 실제로 되는지가
        // 현장에서만 확인 가능해, 서버가 집계로 알 수 있게 싣는다.
        // v1.15.0 — how = 표준 입력이었나 합성이었나 · tnote = 표준 입력이 실패한 사유.
        nav: { url: _navMode.url, click: _navMode.click, fallback: _navMode.fallback, stale: _navMode.stale,
               src: _navMode.src, how: _navMode.how, tnote: _trustedNote || undefined,
               // v1.16.0 — 1페이지 진입 방식과 그 실패 사유.
               entry: _navMode.entry, enote: _entryNote || undefined, via: _entryVia || undefined },
        rawCount: payload.rawCount || 0, adSkipped: payload.adSkipped || 0,
        dupSkipped: payload.dupSkipped || 0, adHintMissed: payload.adHintMissed || 0,
        // v1.10.3 — 광고 필드 지문 집계(제목·가게명 없음). 과필터 원인을 서버 데이터로 가른다.
        adFp: payload.adFp || {},
      },
    }),
  });
  if (!res.ok) throw new Error(`업로드 실패 HTTP ${res.status}`);
  // 올린 뒤에 기억한다 — 실패한 회차는 기준이 되면 안 된다.
  _lastUp = { keyword, sig };
  return res.json();
}

let running = false;
/* 시간대 슬롯 수집이 대기 중임을 온디맨드에게 알리는 깃발.
 * 온디맨드가 락을 계속 쥐면 시간대 경로가 굶는다(2026-08-08 실사고). */
let dailyDue = false;
const DAILY_DUE_KEY = 'dailyDueUntil';
const DAILY_DUE_MS = 5 * 60 * 1000;   // 양보 신호 유효기간 — 만료되면 온디맨드가 다시 돈다

/** 시간대 수집이 자기 차례를 기다리는 중인가.
 *
 * ⚠️ 이걸 storage 에 두는 이유(2026-08-28 실사용에서 드러남):
 *    module 변수(dailyDue)는 배경 스크립트가 잠들면 사라진다. 그러면 다음 1분 알람에서
 *    온디맨드가 다시 먼저 락을 잡고, 시간대 수집은 영영 자기 차례를 못 잡는다.
 *    실제 로그:
 *      1:08:01 온디맨드 8건 시작 → 1:08:39 「양보」 → 1:09:01 온디맨드 9건 **또 시작**
 *      → 1:09:27 「지금 수집 실행」이 '이미 수집 중'으로 튕김
 *    두 알람이 30초 어긋난 채 둘 다 1분 주기라, 온디맨드가 항상 먼저 잡는다. */
async function dailyIsWaiting() {
  try {
    const o = await chrome.storage.local.get(DAILY_DUE_KEY);
    return Number(o[DAILY_DUE_KEY] || 0) > Date.now();
  } catch (e) { return false; }
}
async function markDailyWaiting(on) {
  try {
    await chrome.storage.local.set({ [DAILY_DUE_KEY]: on ? Date.now() + DAILY_DUE_MS : 0 });
  } catch (e) { /* 무시 */ }
}

async function runCollection(manual = false) {
  if (running) {
    await log(running === 'ondemand'
      ? '⏳ 밀린 요청을 처리하는 중입니다 — 한 건 끝나는 대로 시간대 수집이 이어받습니다'
      : '이미 수집 중 — 중복 실행 무시');
    if (manual && running === 'ondemand') await markDailyWaiting(true);   // 사람이 눌렀으니 차례를 예약
    return;
  }
  running = 'daily';   // ⚠️ 첫 await 이전에 '동기' 선점 — ondemand 와 알람이 겹쳐도 이중 진입 불가
  // ⏸ 이 기계에서 일시정지를 눌러 뒀으면 자동·수동 모두 들어가지 않는다(v1.20.0).
  //    ⚠️ running='daily' 를 '먼저' 잡은 뒤 검사한다 — 순서를 바꾸면 첫 await 사이에
  //       알람이 겹쳐 이중 진입할 수 있다(바로 위 주석의 그 이유).
  if (await isLocalPaused()) {
    await setState({ running: false, pausedByLocal: true, current: '' });
    if (manual) await log('⏸ 이 수집기가 일시정지 상태입니다 — 팝업에서 ▶ 재개를 누르세요.');
    running = false; return;
  }
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
  sendHeartbeat(manual ? 'run-manual' : 'run');   // v1.21.0 — 회차 시작을 서버가 바로 본다(기다리지 않는다)

  const hourStart = Date.now();
  const hourTag = hourKey();
  // ⚠️ 예산은 '시작으로부터 50분'이 아니라 **이 시간대가 끝날 때까지**로 잡는다.
  //    1분 알람으로 중간에 이어받을 수 있게 되면서, :40 에 이어받은 회차가 50분을
  //    통으로 쓰면 다음 시간대까지 밀고 들어간다(두 시간대가 겹쳐 요청이 몰린다).
  const _msLeftInHour = (60 - new Date().getMinutes()) * 60 * 1000
                        - new Date().getSeconds() * 1000 - 5 * 60 * 1000;  // 5분 여유
  const hourBudget = Math.max(60 * 1000, Math.min(CFG.hourBudgetMs, _msLeftInHour));
  try {
    // 이번 시간대 몫만 받아온다(24시간 분산). 서버가 슬롯 + 밀린 것을 함께 준다.
    const nowHour = new Date().getHours();
    const res = await fetch(`${CFG.serverBase}/api/collector/keywords?hour=${nowHour}${await workerParams()}`, {
      headers: { 'X-Collector-Token': token },
    });
    if (!res.ok) throw new Error(`키워드 조회 실패 HTTP ${res.status}`);
    const { keywords = [], done: already = 0, total = 0,
            slot = null, overdue = 0, targets = null, paused = false } = await res.json();
    // 🛑 화면에서 껐으면 이 회차를 통째로 건너뛴다(대표 확정 2026-09-18).
    //    ⚠️ 이미 시작한 회차는 서버가 응답으로만 알리므로 여기서 멈추는 게 유일한 지점.
    if (paused) {
      await setState({ running: false, finishedHour: hourTag, current: '', pausedByScreen: true });
      await log('🛑 화면에서 수집을 꺼 둔 상태 — 이번 회차 건너뜀 (화면에서 켜면 재개)');
      return;
    }
    await setState({ pausedByScreen: false });
    // 🎯 조기 종료 목표 — 서버가 주면 쓰고, 안 주면(구버전 서버) 비운다 = 종전 동작.
    _targets = (targets && typeof targets === 'object') ? targets : {};
    const _nTgt = Object.keys(_targets).length;
    await log(`⏱ ${nowHour}시 몫 ${keywords.length}개`
      + (slot === null ? '' : ` (이 시간대 ${slot} · 밀린 것 ${overdue})`)
      + ` — 전체 ${total} · 오늘 완료 ${already}`
      + (_nTgt ? ` · 🎯 찾을 상품이 정해진 키워드 ${_nTgt}개` : ''));
    if (!keywords.length) {
      await setState({ running: false, finishedHour: hourTag, current: '' });
      await log('이번 시간대 수집 대상 없음');
      return;
    }
    // ⭐ 오늘 전체 진척을 팝업이 읽을 수 있게 싣는다(2026-08-28 대표 요청
    //    「총 개수 / 추적 완료 / 추적 실패 결과값도 있어야 할 거 같아」).
    //    ⚠️ target·done·failed 는 **이번 시간대 회차** 값이라 매 회차 0 으로 돌아간다.
    //       그것만 보면 「오늘 얼마나 했나」를 알 수 없었다 — 그 값은 서버가 준다.
    //    dayTotal  = 오늘 재야 할 전체(유니버스)
    //    dayDone   = 오늘 이미 끝낸 것(서버 기준) + 이번 회차에서 더 한 것
    await setState({
      target: keywords.length, slot: slot ?? 0, overdue,
      dayTotal: total, dayDone: already, dayKey: cycleDate(),
    });

    let done = 0, failed = 0, streak = 0;
    // ⚠️ 이번 회차에서 캡차를 만났는가 — 아래 clearBlocked 가 방금 건 6시간 쉼을
    //    스스로 취소하지 않게 하는 표식이다(2026-09-10 수정).
    let blockedThisRound = false;
    for (const kw of keywords) {
      // 다음 시간대와 겹치지 않게 — 남은 것은 서버가 '밀린 것'으로 다시 내려준다
      if (Date.now() - hourStart > hourBudget) {
        await log(`⏱ 이번 시간대 시간 소진 — ${keywords.length - done - failed}개는 다음 회차로`);
        break;
      }
      try {
        const payload = await collectKeyword(kw);
        if (!payload.products.length) throw new Error('상품 0건');
        if (payload.stoppedEarly) {
          const se = payload.stoppedEarly;
          await log(`🎯 [${kw}] 찾을 상품 ${se.targets}개를 ${se.page}페이지에서 다 찾아 멈춤`
                    + ` (담긴 ${se.kept}개 · ${CFG.pagesPerKeyword - se.page}장 아낌)`);
        }
        await uploadKeyword(token, kw, payload);
        done++; streak = 0;
        // 오늘 완료 수도 같이 올린다 — 다음 시간대에 서버 값으로 다시 맞춰진다.
        await setState({ done, failed, current: kw, dayDone: already + done });
        if (done % 25 === 0) {
          await log(`… ${done}/${keywords.length} 진행 중 (직전 [${kw}] 오가닉 ${payload.products.length}개 · 광고 ${payload.adSkipped}개 제외)`);
        }
      } catch (e) {
        // 캡차로 확인되면 더 두드리지 않고 즉시 접는다(재시도가 차단을 깊게 만든다)
        if (String(e.message || '').startsWith('BLOCKED:')) {
          await markBlocked(e.message.slice(8) || '수집 중 감지');
          blockedThisRound = true;
          break;
        }
        failed++; streak++;
        await log(`⚠️ [${kw}] 실패: ${e.message}`);
        // 오늘 누적 실패 — 회차가 바뀌어도 남게 따로 센다(그날 무엇이 안 됐는지 보려고).
        const { state: _st = {} } = await chrome.storage.local.get('state');
        const _today = cycleDate();
        const _dayFail = (_st.dayKey === _today ? Number(_st.dayFailed || 0) : 0) + 1;
        await setState({ done, failed, current: kw, dayFailed: _dayFail, dayKey: _today });
        if (streak >= CFG.maxConsecutiveFail) {
          await log(`🛑 연속 ${streak}회 실패 — 차단 의심으로 이번 회차 중단`);
          break;
        }
        await sleep(jitter() * (1 + streak));   // 실패할수록 더 길게 쉰다
      }
      // 2026-09-18 — 남은 예산을 남은 개수로 나눠 고르게 편다(몰아치기 방지).
      var _kwLeft = keywords.length - done - failed;
      var _msLeft = hourBudget - (Date.now() - hourStart);
      await sleep(jitter() + await spreadGap(_msLeft, _kwLeft));
    }
    // ⭐ 값을 실제로 받았으면 차단이 풀린 것으로 보고 쉼을 지운다.
    // ⚠️ 단 **이번 회차에서 캡차를 만났으면 절대 지우지 않는다** — 앞부분 몇 개가
    //    성공했다는 이유로 방금 건 6시간 쉼을 스스로 취소해 버리면, 다음 시간대에
    //    차단된 채로 다시 두드려 차단이 깊어진다(2026-09-10 수정. 종전 코드는
    //    `if (done > 0)` 하나뿐이라 캡차를 만난 회차에서도 쉼이 지워졌다).
    if (done > 0 && !blockedThisRound) await clearBlocked();
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
    await markDailyWaiting(false);              // 내 차례가 끝났다 — 온디맨드 재개
  }
}

/** 낮 시간 온디맨드 — 직원이 새 키워드를 분석하면 서버 요청 큐에 쌓이고,
 *  1분 주기로 그걸 걷어 즉시 수집한다(한 번에 최대 10개 — 소량이라 IP 부하 미미).
 *  새벽 전체 수집이 도는 동안에는 건너뛴다. */
async function runOnDemand() {
  if (running) return;
  running = 'ondemand';   // ⚠️ 첫 await 이전에 '동기' 선점 — daily 와 알람이 겹쳐도 이중 진입 불가
  try {
    // ⏸ 이 기계에서 일시정지 중이면 밀린 요청 처리도 건너뛴다(v1.20.0). finally 가 락을 푼다.
    if (await isLocalPaused()) return;
    // 캡차 쉼 중이면 아예 들어가지 않는다(매분 재타격 = 차단 연장)
    if (await getBlockedUntil() > Date.now()) return;
    // ⭐ 시간대 수집이 차례를 기다리고 있으면 이번 분은 통째로 비켜 준다.
    //    한 건 끝나고 양보하는 것만으로는 부족했다 — 다음 1분 알람에서 내가 또 먼저
    //    잡아 버려서 시간대 수집이 영영 못 들어갔다(2026-08-28 실측).
    if (await dailyIsWaiting()) return;
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
      const res = await fetch(`${CFG.serverBase}/api/collector/requests?_=1${await workerParams()}`, {
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
    let ok = 0, fail = 0, streak = 0, done = 0, blockedThisRound = false;
    for (const kw of kws) {
      try {
        const payload = await collectKeyword(kw);
        if (!payload.products.length) throw new Error('상품 0건');
        await uploadKeyword(token, kw, payload);
        ok++; streak = 0;
        if (ok === 1 && !blockedThisRound) await clearBlocked();   // 값을 실제로 받았다 = 차단 풀림
        await log(`  ✅ [${kw}] 온디맨드 완료 (오가닉 ${payload.products.length}개 · 광고 ${payload.adSkipped}개 제외)`);
      } catch (e) {
        if (String(e.message || '').startsWith('BLOCKED:')) {
          await markBlocked(e.message.slice(8) || '온디맨드 중 감지');
          blockedThisRound = true;
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
      await sleep(jitter() + await gapFor(CFG.onDemandGapMs));
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
/* ─────────────────────────────────────────────────────────────────────────
 * 📡 살아있음 신호 (v1.21.0 · 대표 확정 2026-09-22 「수집기 자체 개발 → 버전 교체 → 재가동」)
 *
 * 왜 — 2번 설정 노트북이 9/21 07:29 부터 서버에 요청을 **한 건도** 안 보냈다. 일시정지·캡차 쉼·
 *      크롬 종료·알람 소실 중 어느 것이든 서버에선 똑같이 「0건」이라 원인을 가를 수 없었다.
 *      ⇒ 5분마다 **멈춰 있어도** 자기 상태를 보낸다. 서버가 「신호 끊김」(확장이 안 돎)과
 *         「신호는 오는데 수집 0」(이유가 상태에 적혀 있음)을 가른다.
 * ⚠️ 여기서 isLocalPaused()/getBlockedUntil() 로 **걸러서 안 보내면 안 된다** — 그 값을 알리는 것이 목적이다.
 * ⚠️ 절대 예외를 밖으로 내지 않는다 — 신호가 수집을 넘어뜨리면 본말전도다.
 * ⚠️ 개인정보 없음 — 기계 식별은 스스로 만든 무작위 id(instanceId). IP 는 보내지 않는다(서버도 저장 안 함).
 * ─────────────────────────────────────────────────────────────────────── */
const HEARTBEAT_ALARM = 'heartbeat';
const HEARTBEAT_PERIOD_MIN = 5;
const INSTANCE_KEY = 'instanceId';
async function instanceId() {
  try {
    const o = await chrome.storage.local.get(INSTANCE_KEY);
    if (o[INSTANCE_KEY]) return o[INSTANCE_KEY];
    const id = (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID()
      : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
    await chrome.storage.local.set({ [INSTANCE_KEY]: id });
    return id;
  } catch (e) { return ''; }
}
async function alarmNames() {
  try { return (await chrome.alarms.getAll()).map((a) => `${a.name}:${a.periodInMinutes || 0}`); }
  catch (e) { return []; }
}
async function sendHeartbeat(reason) {
  const stamp = new Date().toISOString();
  try {
    const token = await getToken();
    if (!token) {
      await setState({ lastHeartbeatAt: stamp, lastHeartbeatOk: false, lastHeartbeatNote: '토큰 없음' });
      return false;
    }
    const { state = {}, readFail = null, workerNo = CFG.workerNo, workerCount = CFG.workerCount } =
      await chrome.storage.local.get(['state', 'readFail', 'workerNo', 'workerCount']);
    let ver = ''; try { ver = chrome.runtime.getManifest().version; } catch (e) { /* 무시 */ }
    let chromeVer = '';
    try { const m = /Chrome\/([\d.]+)/.exec(navigator.userAgent || ''); chromeVer = m ? m[1] : ''; } catch (e) { /* 무시 */ }
    const body = {
      instanceId: await instanceId(),
      workerNo: Number(workerNo) || 1,
      workerCount: Number(workerCount) || 1,
      extVersion: ver,
      chromeVersion: chromeVer,
      reason: String(reason || ''),
      pausedByLocal: await isLocalPaused(),          // 멈춰 있어도 보낸다 — 그 사실을 알리려고
      pausedByScreen: !!state.pausedByScreen,
      blockedUntil: await getBlockedUntil(),
      slowUntil: Number(state.slowUntil || 0),
      running: !!running,
      lastFinishedAt: state.finishedAt || '',
      dayDone: Number(state.dayDone || 0),
      dayTotal: Number(state.dayTotal || 0),
      lastError: readFail ? `${readFail.at || ''} ${readFail.err || ''}`.slice(0, 200) : '',
      alarms: await alarmNames(),
    };
    const res = await fetch(`${CFG.serverBase}/api/collector/heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Collector-Token': token },
      body: JSON.stringify(body),
    });
    await setState({ lastHeartbeatAt: stamp, lastHeartbeatOk: !!res.ok,
                     lastHeartbeatNote: res.ok ? '' : `HTTP ${res.status}` });
    return !!res.ok;
  } catch (e) {
    try {
      await setState({ lastHeartbeatAt: stamp, lastHeartbeatOk: false,
                       lastHeartbeatNote: String((e && e.message) || e).slice(0, 80) });
    } catch (e2) { /* 무시 */ }
    return false;
  }
}
/** 알람이 빠져 있으면 다시 건다 — 심장박동·사람 버튼에서 부른다. 다시 걸었으면 true. */
async function ensureAlarms(why) {
  try {
    const d = await chrome.alarms.get('daily');
    const o = await chrome.alarms.get('ondemand');
    const h = await chrome.alarms.get(HEARTBEAT_ALARM);
    const missing = [!d && 'daily', !o && 'ondemand', !h && 'heartbeat'].filter(Boolean);
    if (missing.length || d.periodInMinutes !== 1) {
      armAlarms();
      await log(`⏰ 알람 재장전 (${why}) — ${missing.length ? '빠진 알람: ' + missing.join(', ') : '주기 틀림'}`);
      return true;
    }
  } catch (e) { /* 무시 */ }
  return false;
}

function armAlarms() {
  // 'daily' 는 이름만 남았고 실제로는 **매시간 자기 몫**을 수집하는 알람이다(24시간 분산).
  // when 을 1분 뒤로 둬 브라우저를 켜자마자 그 시간대 몫을 이어받는다.
  // ⭐ 1분 주기 (2026-08-28 — 종전 60분). 시간당 한 번만 깨우면, 회차가 중간에
  //    끊겼을 때(브라우저가 워커를 껐다든지) **그 시간대가 통째로 날아간다.**
  //    1분마다 깨워 두면 끊긴 자리에서 이어받는다. 이미 그 시간대 몫을 끝냈으면
  //    state.finishedHour 를 보고 조용히 돌아가므로 헛도는 비용은 없다.
  //    (서버는 오늘 이미 수집한 키워드를 빼고 내려주므로 다시 재는 일도 없다.)
  chrome.alarms.create('daily', { periodInMinutes: 1, when: Date.now() + 60000 });
  // 30초 오프셋 — daily 와 만기가 매시 정각에 겹치지 않게(동시 발화 자체를 회피)
  chrome.alarms.create('ondemand', { periodInMinutes: 1, when: Date.now() + 30000 });
  // 📡 v1.21.0 — 5분마다 살아있음 신호. 첫 신호는 15초 뒤(설치·재시작 직후 서버가 바로 본다).
  chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: HEARTBEAT_PERIOD_MIN, when: Date.now() + 15000 });
}
chrome.runtime.onInstalled.addListener(() => {
  armAlarms();
  log('설치됨 — 1분 주기로 자기 시간대 몫과 밀린 요청을 처리합니다.');
  sendHeartbeat('installed');
});

/** 워커가 깨어날 때마다 알람이 제대로 걸려 있는지만 확인한다(2026-08-28).
 *  ⚠️ 여기서 무조건 armAlarms() 를 부르면 안 된다 — when 이 매번 1분 뒤로 밀려
 *     알람이 영원히 안 뜬다. **주기가 틀렸을 때만** 다시 건다.
 *     확장을 새로고침만 하고 버전이 그대로면 onInstalled 가 안 뜨는 경우가 있어
 *     옛 60분 주기가 그대로 남는 것을 막는 안전망이다. */
(async () => {
  try {
    const a = await chrome.alarms.get('daily');
    const h = await chrome.alarms.get(HEARTBEAT_ALARM);   // v1.21.0 — 새 버전으로 폴더만 바꿔도 걸리게
    if (!a || a.periodInMinutes !== 1 || !h) {
      armAlarms();
      await log('⏰ 알람 재장전 — 1분 주기(수집) + 5분 주기(살아있음 신호)로 맞췄습니다.');
    }
  } catch (e) { /* 무시 */ }
})();
chrome.runtime.onStartup.addListener(() => { armAlarms(); log('브라우저 시작 — 알람 재장전.'); sendHeartbeat('startup'); });

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
  if (a.name === HEARTBEAT_ALARM) { await ensureAlarms('심장박동'); sendHeartbeat('alarm'); return; }
  if (a.name === 'ondemand') { runOnDemand(); return; }
  if (a.name !== 'daily') return;
  // 24시간 분산 — 매시간 자기 시간대 몫만 수집한다(시각 제한 없음).
  // 같은 시간대를 이미 돌았으면 건너뛴다(알람이 시간당 두 번 뜨는 경우 방어).
  const { state = {} } = await chrome.storage.local.get('state');
  if (state.finishedHour === hourKey()) return;   // 이 시간대 몫은 이미 끝냈다
  if (running === 'daily') return;                // 이미 돌고 있다 — 조용히 물러난다
  if (running === 'ondemand') {
    // 온디맨드가 돌고 있으면 한 건 끝나는 대로 비켜달라고 표시하고 물러난다.
    // ⚠️ 표시는 storage 에 남긴다 — 그래야 다음 1분 알람에서 온디맨드가 스스로
    //    안 들어오고 내가 락을 잡는다. module 변수만 쓰면 워커가 잠들 때 사라져
    //    온디맨드가 매분 먼저 잡아 버린다(2026-08-28 실사용에서 확인된 회귀).
    dailyDue = true;
    await markDailyWaiting(true);
    return;
  }
  dailyDue = false;
  await markDailyWaiting(false);   // 내가 잡았다 — 온디맨드를 다시 풀어 준다
  runCollection(false);
});

chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.cmd === 'run') { runCollection(true); sendResponse({ ok: true }); }
  // 📡 v1.21.0 — 사람이 팝업에서 「지금 상태 보내기」. 알람이 빠져 있으면 함께 다시 건다.
  if (msg?.cmd === 'heartbeat') {
    (async () => {
      await ensureAlarms('사람이 누름');
      const ok = await sendHeartbeat('manual');
      await log(ok ? '📡 이 기계의 상태를 서버에 보냈습니다.' : '📡 서버 보고 실패 — 상태 칸의 「서버 보고」 줄을 확인하세요.');
    })();
    sendResponse({ ok: true });
  }
  // ⏸ 사람이 팝업에서 누른 '일시정지 / 재개'(v1.20.0) — 이 기계에서만 적용된다.
  //    화면(서버) 스위치와 별개다. 자동으로 풀리지 않으므로 다시 누를 때까지 멈춰 있다.
  if (msg?.cmd === 'setLocalPause') {
    (async () => {
      if (msg.on) {
        await chrome.storage.local.set({ [LOCAL_PAUSE_KEY]: true });
        await setState({ running: false, pausedByLocal: true, current: '' });
        await log('⏸ 이 수집기를 일시정지했습니다 (이 기계에서만 · 사람이 누름). ▶ 재개를 누르면 다시 돕니다.');
      } else {
        await chrome.storage.local.remove(LOCAL_PAUSE_KEY);
        await setState({ pausedByLocal: false });
        await log('▶ 이 수집기를 재개했습니다 — 다음 회차부터 다시 수집합니다.');
      }
    })();
    sendResponse({ ok: true });
  }
  // 🐢 사람이 켜는 안전 속도 — 캡차를 만나 자동으로 켜지는 것과 **같은 장치**를 쓴다.
  //    차단이 의심되는 때(회선이 막 시끄러웠던 직후 등)에 사람이 미리 절반 속도로
  //    돌릴 수 있게 한 것. 24시간 뒤 스스로 풀린다(끄는 것을 잊어도 원복된다).
  if (msg?.cmd === 'slowOn') {
    (async () => {
      const until = Date.now() + SLOW_WINDOW_MS;
      await chrome.storage.local.set({ [SLOW_KEY]: until });
      await setState({ slowUntil: until });
      await log('🐢 안전 속도 켜짐 — 24시간 동안 절반 속도로 돕니다(사람이 켠 것).');
    })();
    sendResponse({ ok: true });
  }
  // v1.14.0 — 🔍 **사람이 연 화면을 같은 자로 잰다.**
  //   9/16 A/B 의 치명적 결함이 이것이었다 — 대표가 손으로 2페이지를 눌렀을 때 확장이 꺼져 있어
  //   net_tap 이 안 돌았고, 그래서 「사람의 2페이지 요청이 200 이었나」를 **잰 값이 0건**이다.
  //   「사람은 되고 기계는 안 된다」가 서로 다른 자로 잰 것이라 판정에 쓸 수 없었다(9/12 교훈).
  //   이 버튼은 **이미 화면에 있는 응답을 복사해 보낼 뿐** — 네이버에 요청을 한 건도 더 보내지 않는다.
  if (msg?.cmd === 'humanProbe') {
    (async () => {
      try {
        const tabs = await chrome.tabs.query({ url: '*://search.shopping.naver.com/*' });
        const t = tabs.find((x) => x.active) || tabs[0];
        if (!t) {
          await log('🔍 네이버쇼핑 검색 결과 화면이 안 열려 있습니다 — 그 화면을 띄우고 다시 눌러 주세요.');
          return;
        }
        await tapReport(t.id, '(사람 시험)', 0, 'HUMAN', 'HUMAN_PROBE(사람이 연 화면)');
        await log('🔍 이 화면이 받은 응답을 서버에 보냈습니다 (진단 1건 · 네이버 요청 0건).');
      } catch (e) {
        await log('🔍 응답 보내기 실패 — ' + (e && e.message ? e.message : e));
      }
    })();
    sendResponse({ ok: true });
  }
  if (msg?.cmd === 'slowOff') {
    (async () => {
      await chrome.storage.local.remove(SLOW_KEY);
      await setState({ slowUntil: 0 });
      await log('🐇 안전 속도 꺼짐 — 평소 속도로 돌아갑니다.');
    })();
    sendResponse({ ok: true });
  }
  return true;
});
