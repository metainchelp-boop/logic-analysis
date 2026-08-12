/* METAINC 플레이스 순위 추적기 — 무인 러너 (v1.0.3)
 *
 * 매일 06:30(로컬) chrome.alarms 로 기동해, 로직분석에 등록된 추적 대상(업체×키워드)을
 * 키워드별로 pcmap.place.naver.com 목록 탭에서 수집(자동 스크롤 + __APOLLO_STATE__ 판독)하고,
 * 결과를 보관한 뒤 로직분석 탭을 열어 브리지로 전달한다(로그인된 웹앱이 /api/place/ingest 호출).
 *
 * 설계 원칙:
 *  - 무해 실패: 어떤 단계가 실패해도 다음 키워드로 진행, 결과는 '미확인'으로 기록.
 *  - 서스펜션 내성: 진행 상태를 storage 에 두고 단계 전환은 전부 chrome.alarms 로 —
 *    MV3 서비스워커가 중간에 잠들어도 워치독 알람이 같은 단계를 재개한다.
 *  - 사람 속도: 키워드당 1탭, 탭 간 35~50초 간격(랜덤) — 부하·오탐 방지.
 *  - 순위 판독 로직은 서버 place_crawler.parse_place_search / find_place_rank 와 1:1
 *    (2026-08-04 맥 실측 스파이크로 검증: APOLLO 인라인·지역 포함 키워드는 위치 무관 재현).
 *  - 기존 「로직분석 수집기」 확장과 완전 별개(파일·저장소·설치 독립, 공존).
 */

'use strict';

var RUN_HOUR = 6, RUN_MIN = 30;                 // 매일 06:30 — 쇼핑 수집기 새벽 창(01:00~05:45) 회피
var DAILY_ALARM = 'place-daily';
var STEP_ALARM = 'place-step';
var SYNC_ALARM = 'place-sync-wait';
var SYNC_WAIT_MS = 30000;                       // 선동기화 대기 — 로직 탭이 목록을 push 할 시간
var STEP_GAP_MS = 35000;                        // 키워드 간 기본 간격(+0~15초 랜덤)
var STEP_WATCHDOG_MS = 180000;                  // 단계 워치독 — 워커 서스펜션·탭 무응답 재개(스크롤 판독 최장 ~60초 감안)
var RUN_STALE_MS = 2 * 60 * 60 * 1000;          // 2시간 넘은 진행 상태는 버림(비정상 종료 잔재)
var RESULT_TTL_MS = 20 * 60 * 60 * 1000;        // 결과 보관 20시간 — 아침 수동 로그인까지 대기 가능
var MAX_TRIES_PER_STEP = 2;

var ERP_URL_PATTERNS = [
  'http://metainc.co.kr/*',
  'https://metainc.co.kr/*',
  'http://www.metainc.co.kr/*',
  'https://www.metainc.co.kr/*'
];

/* ---------- 공용 유틸 ---------- */
function norm(s) { return String(s || '').toLowerCase().replace(/\s+/g, ''); }
function sGet(keys) { return new Promise(function (res) { try { chrome.storage.local.get(keys, function (r) { res(r || {}); }); } catch (e) { res({}); } }); }
function sSet(obj) { return new Promise(function (res) { try { chrome.storage.local.set(obj, function () { res(); }); } catch (e) { res(); } }); }
function sRemove(keys) { return new Promise(function (res) { try { chrome.storage.local.remove(keys, function () { res(); }); } catch (e) { res(); } }); }
function closeTabQuiet(tabId) { if (!tabId) return; try { chrome.tabs.remove(tabId, function () { void chrome.runtime.lastError; }); } catch (e) {} }

/* ---------- 매일 알람 ---------- */
function nextRunTime() {
  var d = new Date();
  d.setHours(RUN_HOUR, RUN_MIN, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  return d.getTime();
}
function ensureDailyAlarm() {
  try { chrome.alarms.create(DAILY_ALARM, { when: nextRunTime(), periodInMinutes: 24 * 60 }); } catch (e) {}
}
try { chrome.runtime.onInstalled.addListener(ensureDailyAlarm); } catch (e) {}
try { chrome.runtime.onStartup.addListener(ensureDailyAlarm); } catch (e) {}
ensureDailyAlarm();

/* ---------- 수집 시작 ---------- */
function maybeStartRun(source) {
  return sGet(['place_enabled', 'place_run', 'place_sync']).then(function (st) {
    if (st.place_enabled === false && source === 'daily') {
      return sSet({ place_last_run: { finishedAt: Date.now(), source: source, skipped: 'disabled' } });
    }
    var run = st.place_run;
    if (run && run.startedAt && (Date.now() - run.startedAt) < RUN_STALE_MS) return; // 진행 중 — 중복 기동 방지
    if (source === 'daily') {
      // 새벽 무인 수집은 목록 선동기화 후 시작 — 스토리지 목록은 추적 화면을 마지막으로 연 시점의
      // 스냅샷이라, 직원들이 낮에 등록한 대상을 반영하려면 수집 직전 로직 탭을 잠깐 열어 최신 목록을 받는다.
      var sy = st.place_sync;
      if (sy && sy.at && (Date.now() - sy.at) < 2 * SYNC_WAIT_MS) return; // 선동기화 이미 진행 중
      return startTargetSync(source);
    }
    return buildAndGo(source); // 수동(지금 수집)은 화면이 방금 목록을 push 했으므로 바로 시작
  });
}

/* 선동기화 — 로직분석 추적 화면을 백그라운드로 열면 페이지가 서버 목록을 받아 확장에 push 한다.
 * 로그인·SSO 실패 시엔 기존 목록으로 그대로 진행(무해 폴백). */
function startTargetSync(source) {
  return new Promise(function (resolve) {
    resolveErpToken(function (tok) {
      var url = tok
        ? 'https://logic.metainc.co.kr/?sso=' + encodeURIComponent(tok) + '#placetrack'
        : 'https://logic.metainc.co.kr/#placetrack';
      function arm(tabId) {
        sSet({ place_sync: { tabId: tabId, source: source, at: Date.now() } }).then(function () {
          try { chrome.alarms.create(SYNC_ALARM, { when: Date.now() + SYNC_WAIT_MS }); } catch (e) {}
          resolve();
        });
      }
      try {
        chrome.tabs.create({ url: url, active: false }, function (tab) {
          arm((!chrome.runtime.lastError && tab) ? tab.id : null);
        });
      } catch (e) { arm(null); }
    });
  });
}

function finishTargetSync() {
  sGet(['place_sync']).then(function (st) {
    var sy = st.place_sync || {};
    closeTabQuiet(sy.tabId);
    sRemove(['place_sync']).then(function () { buildAndGo(sy.source || 'daily'); });
  });
}

function buildAndGo(source) {
  return sGet(['place_targets', 'place_run']).then(function (st) {
    var run = st.place_run;
    if (run && run.startedAt && (Date.now() - run.startedAt) < RUN_STALE_MS) return; // 선동기화 중 수동 시작 등
    var targets = (st.place_targets && st.place_targets.targets) || [];
    targets = targets.filter(function (t) { return t && t.keyword && t.business_name; });
    if (!targets.length) {
      return sSet({ place_last_run: { finishedAt: Date.now(), source: source, skipped: 'no-targets' } });
    }
    // 키워드별 그룹 — 같은 키워드의 여러 업체는 한 번의 검색으로 함께 판독
    var byKw = {};
    targets.forEach(function (t) {
      var k = t.keyword.trim();
      if (!byKw[k]) byKw[k] = [];
      byKw[k].push({ id: t.id, business_name: t.business_name, region: t.region || '', place_id: t.place_id || '' });
    });
    var queue = Object.keys(byKw).map(function (k) { return { keyword: k, targets: byKw[k] }; });
    var newRun = { queue: queue, idx: 0, tries: 0, results: [], startedAt: Date.now(), source: source || 'manual', tabId: null };
    return sSet({ place_run: newRun }).then(function () { scheduleStep(1500); });
  });
}

function scheduleStep(delayMs) {
  try { chrome.alarms.create(STEP_ALARM, { when: Date.now() + Math.max(1000, delayMs) }); } catch (e) {}
}

/* ---------- 단계 실행 (키워드 1개 = 탭 1개) ---------- */
function step() {
  sGet(['place_run']).then(function (st) {
    var run = st.place_run;
    if (!run || !run.queue) return;
    if (run.startedAt && (Date.now() - run.startedAt) > RUN_STALE_MS) { // 너무 오래된 잔재 — 마무리
      return finishRun(run, 'stale');
    }
    closeTabQuiet(run.tabId);
    run.tabId = null;

    if (run.idx >= run.queue.length) return finishRun(run, 'done');

    var item = run.queue[run.idx];
    run.tries = (run.tries || 0) + 1;
    if (run.tries > MAX_TRIES_PER_STEP) {          // 이 키워드는 포기 — 전 대상 미확인 기록 후 전진
      item.targets.forEach(function (t) {
        run.results.push({ target_id: t.id, keyword: item.keyword, business_name: t.business_name,
          region: t.region, place_id: t.place_id || null, rank: null, state: '미확인' });
      });
      run.idx += 1; run.tries = 0;
      return sSet({ place_run: run }).then(function () { scheduleStep(3000); });
    }

    // 워치독 — 아래 어디서 멈춰도 STEP_WATCHDOG_MS 후 이 단계 재진입(tries 증가)
    scheduleStep(STEP_WATCHDOG_MS);

    sSet({ place_run: run }).then(function () {
      var url = 'https://pcmap.place.naver.com/place/list?query=' + encodeURIComponent(item.keyword);
      try {
        chrome.tabs.create({ url: url, active: false }, function (tab) {
          if (chrome.runtime.lastError || !tab) return;   // 워치독이 재시도
          run.tabId = tab.id;
          sSet({ place_run: run });
          waitTabComplete(tab.id, 45000, function () {
            setTimeout(function () { extractFromTab(tab.id, run, item); }, 1800);
          });
        });
      } catch (e) { /* 워치독이 재시도 */ }
    });
  });
}

function waitTabComplete(tabId, timeoutMs, cb) {
  var done = false;
  function finish() { if (done) return; done = true; try { chrome.tabs.onUpdated.removeListener(onUpd); } catch (e) {} cb(); }
  function onUpd(id, info) { if (id === tabId && info && info.status === 'complete') finish(); }
  try { chrome.tabs.onUpdated.addListener(onUpd); } catch (e) {}
  setTimeout(finish, timeoutMs);
  try { chrome.tabs.get(tabId, function (t) { if (!chrome.runtime.lastError && t && t.status === 'complete') finish(); }); } catch (e) {}
}

/* 페이지 주입 판독 — 서버 파서(place_crawler)와 동일 규칙. 자기완결(외부 참조 금지). */
function pageExtract() {
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  return (async function () {
    try {
      var els = [].slice.call(document.querySelectorAll('*')).filter(function (e) {
        try { var s = getComputedStyle(e); return (e.scrollHeight > e.clientHeight + 100) && /(auto|scroll)/.test(s.overflowY); } catch (_) { return false; }
      });
      els.sort(function (a, b) { return b.scrollHeight - a.scrollHeight; });
      var sc = els[0] || document.scrollingElement;
      // 끝까지 스크롤 — 네이버 목록은 배치 로딩이 느릴 수 있어(네트워크) 높이 정지 판정을 넉넉히:
      // 900ms 간격 × 5회 연속 정지 + 중간(3회째) 1.6초 추가 대기 후 재확인. 최대 60스텝(~60초).
      var last = 0, still = 0, steps = 0;
      while (steps < 60 && still < 5) {
        try { sc.scrollTop = sc.scrollHeight; } catch (_) {}
        window.scrollTo(0, document.body.scrollHeight);
        await sleep(900); steps++;
        var h = (sc && sc.scrollHeight) || document.body.scrollHeight;
        if (h === last) {
          still++;
          if (still === 3) await sleep(1600);
        } else { still = 0; last = h; }
      }
      await sleep(500);
      var ap = null; try { ap = window.__APOLLO_STATE__ || null; } catch (_) {}
      var items = [];
      if (ap) {
        Object.keys(ap).forEach(function (key) {
          var val = ap[key];
          if (!val || typeof val !== 'object') return;
          var isAd = key.indexOf('Ad') >= 0 || String(val.adId || '').toLowerCase().indexOf('nad') >= 0;
          var isBiz = key.indexOf('PlaceListBusinessesItem') === 0 || key.indexOf('RestaurantListSummary') === 0
            || key.indexOf('RestaurantAdSummary') === 0 || (('id' in val) && ('name' in val));
          if (!isBiz) return;
          var name = val.name || val.businessName; if (!name) return;
          // 리뷰 수도 함께 담는다(2026-08-12) — 목록 데이터에 이미 들어 있는데 종전엔 버렸다.
          // 이 값이 없으면 리뷰는 「수동 분석에서 캡처를 붙여넣을 때만」 채워지는데
          // 그 경로가 실제로는 한 번도 성공한 적이 없었다(DB 71행 중 리뷰 0행).
          // 저장수는 목록 데이터에 없다 → 담당자 직접 입력이 유일한 출처(서버와 동일 규약).
          // 숫자만 남겨 정수화 — 서버 파서 place_crawler._to_int 와 같은 규칙.
          // ⚠️ parseInt 만 쓰면 '1,204' 가 1 이 된다(검증에서 실제로 잡힌 건).
          //    단 값이 아예 없을 때는 서버(0)와 달리 null 을 준다 — 가짜 0 을 보내지 않기 위해.
          var n = function (v) {
            if (v === null || v === undefined) return null;
            var d = String(v).replace(/[^\d]/g, '');
            return d ? parseInt(d, 10) : null;
          };
          items.push({
            id: String(val.id || val.businessId || ''), name: String(name), ad: !!isAd,
            vr: n(val.visitorReviewCount),
            br: n(val.blogCafeReviewCount != null ? val.blogCafeReviewCount : val.blogReviewCount)
          });
        });
      }
      var rank = 0;
      items.forEach(function (it) { if (!it.ad) { rank++; it.rank = rank; } else { it.rank = null; } });
      return { ok: items.length > 0, items: items, url: String(location.href).slice(0, 200) };
    } catch (e) { return { ok: false, items: [], err: String(e).slice(0, 150) }; }
  })();
}

function extractFromTab(tabId, run, item) {
  try {
    chrome.scripting.executeScript({ target: { tabId: tabId }, world: 'MAIN', func: pageExtract }, function (results) {
      var out = (!chrome.runtime.lastError && results && results[0] && results[0].result) || { ok: false, items: [] };
      onExtracted(out, item);
    });
  } catch (e) { onExtracted({ ok: false, items: [] }, item); }
}

function onExtracted(out, item) {
  sGet(['place_run']).then(function (st) {
    var run = st.place_run;
    if (!run) return;
    closeTabQuiet(run.tabId); run.tabId = null;

    var items = (out && out.items) || [];
    item = run.queue[run.idx] || item;

    // 판독 깊이 기록 — 이 키워드에서 오가닉 몇 위까지 훑었는지(팝업 진단용)
    if (out && out.ok) {
      var organicCount = 0;
      items.forEach(function (x) { if (!x.ad) organicCount++; });
      run.depths = (run.depths || []).concat([{ k: item.keyword, n: organicCount }]);
    }
    item.targets.forEach(function (t) {
      if (!out || !out.ok) {
        run.results.push({ target_id: t.id, keyword: item.keyword, business_name: t.business_name,
          region: t.region, place_id: t.place_id || null, rank: null, state: '미확인' });
        return;
      }
      // 매칭: ① 플레이스 ID 정확 일치(1차) ② 없으면 업체명 포함(2차 폴백 — ID 오기재 시에도 놓치지 않게)
      var matched = null, i, it;
      if (t.place_id) {
        for (i = 0; i < items.length; i++) {
          it = items[i];
          if (!it.ad && String(it.id) === String(t.place_id)) { matched = it; break; }
        }
      }
      if (!matched && t.business_name) {
        for (i = 0; i < items.length; i++) {
          it = items[i];
          if (!it.ad && it.name && norm(it.name).indexOf(norm(t.business_name)) >= 0) { matched = it; break; }
        }
      }
      run.results.push({
        target_id: t.id, keyword: item.keyword, business_name: t.business_name, region: t.region,
        place_id: (matched && matched.id) || t.place_id || null,
        rank: matched ? matched.rank : null,
        state: matched ? '노출' : '미노출',
        // 목록에서 내 업체를 찾았을 때만 리뷰가 있다(못 찾았으면 잴 대상이 없으므로 null).
        // 가짜 0 금지 — 서버가 None 을 그대로 저장해 화면이 「미확인」으로 표기한다.
        visitor_reviews: matched ? (matched.vr != null ? matched.vr : null) : null,
        blog_reviews: matched ? (matched.br != null ? matched.br : null) : null
      });
    });

    run.idx += 1; run.tries = 0;
    sSet({ place_run: run }).then(function () {
      scheduleStep(STEP_GAP_MS + Math.floor(Math.random() * 15000));
    });
  });
}

/* ---------- 마무리: 결과 보관 → 로직분석 탭 열어 브리지 전달 ---------- */
function finishRun(run, reason) {
  var results = run.results || [];
  var counts = { exposed: 0, missing: 0, unknown: 0 };
  results.forEach(function (r) {
    if (r.state === '노출') counts.exposed++;
    else if (r.state === '미노출') counts.missing++;
    else counts.unknown++;
  });
  var depthMin = null, depthMax = null;
  (run.depths || []).forEach(function (d) {
    if (!d || !d.n) return;
    if (depthMin === null || d.n < depthMin) depthMin = d.n;
    if (depthMax === null || d.n > depthMax) depthMax = d.n;
  });
  var pending = {
    results: results,
    ran_at: new Date().toISOString(),
    source: run.source || 'manual',
    created_at: Date.now(),
    summary: counts
  };
  closeTabQuiet(run.tabId);
  sRemove(['place_run']).then(function () {
    return sSet({
      place_pending_results: pending,
      place_last_run: { finishedAt: Date.now(), source: run.source, reason: reason,
        keywords: (run.queue || []).length, results: results.length,
        exposed: counts.exposed, missing: counts.missing, unknown: counts.unknown,
        depthMin: depthMin, depthMax: depthMax, delivered: false }
    });
  }).then(function () {
    if (!results.length) return;                    // 기록할 게 없으면 탭도 안 연다
    resolveErpToken(function (tok) {
      var url = tok
        ? 'https://logic.metainc.co.kr/?sso=' + encodeURIComponent(tok) + '#placetrack'
        : 'https://logic.metainc.co.kr/#placetrack';
      try {
        chrome.tabs.create({ url: url, active: false }, function (tab) {
          if (!chrome.runtime.lastError && tab) sSet({ place_bridge_tab: tab.id });
        });
      } catch (e) {}
    });
  });
}

/* 전산 SSO 토큰 — 기존 수집기와 동일 2단계(열린 전산 탭 즉석 판독 → 7일 미러 폴백) */
function resolveErpToken(cb) {
  try {
    chrome.tabs.query({ url: ERP_URL_PATTERNS }, function (tabs) {
      if (chrome.runtime.lastError || !tabs || !tabs.length) return mirrorFallback(cb);
      try {
        chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: function () {
            try { return (localStorage.getItem('token') || '').replace(/^Bearer\s+/i, ''); } catch (e) { return ''; }
          }
        }, function (results) {
          if (chrome.runtime.lastError) return mirrorFallback(cb);
          var tok = (results && results[0] && results[0].result) || '';
          if (tok) { sSet({ metainc_erp_token: { token: tok, saved_at: Date.now() } }); cb(tok); }
          else mirrorFallback(cb);
        });
      } catch (e) { mirrorFallback(cb); }
    });
  } catch (e) { mirrorFallback(cb); }
}
function mirrorFallback(cb) {
  sGet(['metainc_erp_token']).then(function (res) {
    var t = res && res.metainc_erp_token;
    var fresh = t && t.token && (Date.now() - (t.saved_at || 0) < 7 * 24 * 60 * 60 * 1000);
    cb(fresh ? t.token : '');
  });
}

/* ---------- 메시지 라우터 (콘텐츠 스크립트 · 팝업) ---------- */
chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (!msg || !msg.type) return false;

  if (msg.type === 'PLACE_TARGETS_SET') {           // 웹앱 → 추적 목록 동기화
    sSet({ place_targets: { targets: (msg.payload && msg.payload.targets) || [], synced_at: Date.now() } })
      .then(function () { sendResponse({ ok: true }); });
    return true;
  }
  if (msg.type === 'PLACE_RUN') {                    // 웹앱/팝업 → 지금 전체 수집
    maybeStartRun('manual').then(function () { sendResponse({ ok: true }); });
    return true;
  }
  if (msg.type === 'PLACE_CLEAR_RESULTS') {          // 브리지 ACK → 결과 삭제 + 브리지 탭 정리
    sGet(['place_pending_results', 'place_bridge_tab', 'place_last_run']).then(function (st) {
      var lr = st.place_last_run || {};
      lr.delivered = true;
      closeTabQuiet(st.place_bridge_tab);
      return sRemove(['place_pending_results', 'place_bridge_tab']).then(function () {
        return sSet({ place_last_run: lr });
      });
    }).then(function () { sendResponse({ ok: true }); });
    return true;
  }
  if (msg.type === 'PLACE_STATUS') {                 // 팝업 상태 조회
    Promise.all([
      sGet(['place_enabled', 'place_targets', 'place_run', 'place_last_run', 'place_pending_results']),
      new Promise(function (res) { try { chrome.alarms.get(DAILY_ALARM, function (a) { res(a || null); }); } catch (e) { res(null); } })
    ]).then(function (arr) {
      var st = arr[0], alarm = arr[1];
      sendResponse({
        ok: true,
        enabled: st.place_enabled !== false,
        nextRunAt: alarm && alarm.scheduledTime,
        targets: ((st.place_targets && st.place_targets.targets) || []).length,
        syncedAt: st.place_targets && st.place_targets.synced_at,
        running: !!(st.place_run && st.place_run.queue),
        progress: st.place_run ? { idx: st.place_run.idx, total: st.place_run.queue.length } : null,
        lastRun: st.place_last_run || null,
        pending: !!st.place_pending_results
      });
    });
    return true;
  }
  if (msg.type === 'PLACE_TOGGLE') {                 // 팝업 ON/OFF
    sSet({ place_enabled: !!msg.enabled }).then(function () { sendResponse({ ok: true }); });
    return true;
  }
  return false;
});

/* ---------- 알람 라우터 ---------- */
try {
  chrome.alarms.onAlarm.addListener(function (alarm) {
    if (!alarm) return;
    if (alarm.name === DAILY_ALARM) maybeStartRun('daily');
    else if (alarm.name === SYNC_ALARM) finishTargetSync();
    else if (alarm.name === STEP_ALARM) step();
  });
} catch (e) {}

/* 결과 TTL 청소 — 기동 시 20시간 지난 미전달 결과 폐기(다음 수집이 새로 기록) */
sGet(['place_pending_results', 'place_sync']).then(function (st) {
  var p = st.place_pending_results;
  if (p && p.created_at && (Date.now() - p.created_at) > RESULT_TTL_MS) {
    sRemove(['place_pending_results']);
  }
  var sy = st.place_sync; // 브라우저 재시작 등으로 알람을 잃은 선동기화 잔재 정리(자동 수집 재개 가능하게)
  if (sy && sy.at && (Date.now() - sy.at) > 10 * 60 * 1000) {
    closeTabQuiet(sy.tabId);
    sRemove(['place_sync']);
  }
});
