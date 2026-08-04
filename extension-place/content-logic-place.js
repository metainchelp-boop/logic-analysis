/* METAINC 플레이스 순위 추적기 — 로직분석 페이지 브리지 (v1.0.0)
 *
 * 역할 3가지 (기존 수집기 브리지와 별개 메시지 채널 — METAINC_PLACE_* 접두):
 *  1) 러너가 보관한 수집 결과(place_pending_results)를 웹앱에 postMessage 로 전달.
 *     앱이 /api/place/ingest 기록 후 ACK 하면 러너에 삭제 요청. 20시간 동안 2초 간격 재시도
 *     (새벽 무인 수집 → 아침 수동 로그인까지 기다릴 수 있게).
 *  2) 웹앱의 추적 목록 동기화(METAINC_PLACE_TARGETS)·즉시 수집(METAINC_PLACE_RUN)을 러너에 중계.
 *  3) 설치 알림(METAINC_PLACE_EXT_READY) — 추적 화면이 연동 상태를 표시할 수 있게. */
(function () {
  'use strict';
  var RETRY_MS = 2000;
  var TTL_MS = 20 * 60 * 60 * 1000;
  var acked = false;
  var BANNER_ID = 'metainc-place-bridge-banner';
  var VERSION = '1.0.0';

  function announce() {
    try { window.postMessage({ type: 'METAINC_PLACE_EXT_READY', version: VERSION }, window.location.origin); } catch (e) {}
  }
  announce();
  setTimeout(announce, 1500);   /* 앱 리스너가 아직 안 붙었을 수 있어 한 번 더 */

  window.addEventListener('message', function (ev) {
    if (ev.source !== window || !ev.data) return;

    if (ev.data.type === 'METAINC_PLACE_PING') { announce(); return; }

    if (ev.data.type === 'METAINC_PLACE_RESULTS_ACK') {
      acked = true;
      removeBanner();
      try { chrome.runtime.sendMessage({ type: 'PLACE_CLEAR_RESULTS' }); } catch (e) {}
      return;
    }
    if (ev.data.type === 'METAINC_PLACE_TARGETS') {
      try { chrome.runtime.sendMessage({ type: 'PLACE_TARGETS_SET', payload: ev.data.payload }); } catch (e) {}
      return;
    }
    if (ev.data.type === 'METAINC_PLACE_RUN') {
      try { chrome.runtime.sendMessage({ type: 'PLACE_RUN' }); } catch (e) {}
      return;
    }
  });

  function showBanner() {
    try {
      if (acked || document.getElementById(BANNER_ID)) return;
      var el = document.createElement('div');
      el.id = BANNER_ID;
      el.style.cssText = 'position:fixed;top:56px;left:50%;transform:translateX(-50%);z-index:2147483646;'
        + 'background:#4f46e5;color:#fff;font:600 13px/1.5 -apple-system,"Malgun Gothic",sans-serif;'
        + 'padding:10px 18px;border-radius:12px;box-shadow:0 8px 24px rgba(79,70,229,.35);max-width:92vw;text-align:center;';
      el.textContent = '📊 플레이스 순위 수집 결과가 대기 중입니다 — 로그인하면 자동으로 기록됩니다';
      (document.body || document.documentElement).appendChild(el);
    } catch (e) {}
  }
  function removeBanner() {
    try { var el = document.getElementById(BANNER_ID); if (el) el.remove(); } catch (e) {}
  }

  var startedAt = Date.now();
  function attempt() {
    if (acked) return;
    try {
      chrome.storage.local.get('place_pending_results', function (res) {
        if (acked) return;
        var p = res && res.place_pending_results;
        if (!p || !p.results || !p.results.length) return;                 /* 전달할 것 없음 */
        if (p.created_at && (Date.now() - p.created_at) > TTL_MS) return;  /* 만료 — 러너가 기동 시 청소 */
        try { window.postMessage({ type: 'METAINC_PLACE_RESULTS', payload: p }, window.location.origin); } catch (e) {}
        if (Date.now() - startedAt > 3000) showBanner();
        if (Date.now() - startedAt < TTL_MS) setTimeout(attempt, RETRY_MS);
      });
    } catch (e) {}
  }
  setTimeout(attempt, 800);
})();
