/* METAINC 로직분석 수집기 — 로직분석 페이지 브리지 (v1.0.1)
 * 보관된 수집물을 앱에 postMessage로 전달. 앱이 ACK 하면 보관물 삭제.
 *
 * v1.0.1 수정: 재시도가 30초에서 끊겨 로그인(아이디/비번 입력)이 30초를 넘기면
 * 수신이 영영 안 되던 문제 → 수집물 유효시간(10분) 동안 2초 간격으로 계속 재시도.
 * + 로그인 화면에서 "수집물 대기 중" 안내 배너를 띄워 상황을 알 수 있게 함. */
(function () {
  'use strict';
  var startedAt = Date.now();
  var MAX_WAIT_MS = 10 * 60 * 1000;   /* 수집물 유효시간과 동일 — 로그인 대기 포함 */
  var RETRY_MS = 2000;
  var acked = false;
  var BANNER_ID = 'metainc-bridge-banner';

  window.addEventListener('message', function (ev) {
    if (ev.source !== window || !ev.data) return;
    if (ev.data.type === 'METAINC_EXT_ACK') {
      acked = true;
      removeBanner();
      try { chrome.runtime.sendMessage({ type: 'METAINC_CLEAR' }); } catch (e) {}
    }
  });

  function showBanner() {
    try {
      if (acked || document.getElementById(BANNER_ID)) return;
      var el = document.createElement('div');
      el.id = BANNER_ID;
      el.style.cssText = 'position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:2147483646;'
        + 'background:#1e40af;color:#fff;font:600 13px/1.5 -apple-system,"Malgun Gothic",sans-serif;'
        + 'padding:10px 18px;border-radius:12px;box-shadow:0 8px 24px rgba(30,64,175,.35);max-width:92vw;text-align:center;';
      el.textContent = '🧩 수집한 상품이 대기 중입니다 — 로그인하면 분석이 자동으로 시작됩니다 (최대 10분 대기)';
      (document.body || document.documentElement).appendChild(el);
    } catch (e) {}
  }

  function removeBanner() {
    try {
      var el = document.getElementById(BANNER_ID);
      if (el) el.remove();
    } catch (e) {}
  }

  function attempt() {
    if (acked) return;
    if (Date.now() - startedAt > MAX_WAIT_MS) { removeBanner(); return; }
    try {
      chrome.storage.local.get('metainc_pending_capture', function (res) {
        if (acked) return;
        var cap = res && res.metainc_pending_capture;
        if (!cap || !cap.html) { removeBanner(); return; } /* 보관물 없음(다른 탭이 처리) — 종료 */
        if (Date.now() - (cap.captured_at || 0) > MAX_WAIT_MS) {
          try { chrome.runtime.sendMessage({ type: 'METAINC_CLEAR' }); } catch (e) {}
          removeBanner();
          return; /* 10분 지난 수집물은 폐기(오래된 데이터 오주입 방지) */
        }
        window.postMessage({ type: 'METAINC_EXT_CAPTURE', payload: cap }, window.location.origin);
        /* 3초 넘게 ACK가 없으면 로그인 대기 상태로 보고 안내 배너 표시 */
        if (Date.now() - startedAt > 3000) showBanner();
        setTimeout(attempt, RETRY_MS);
      });
    } catch (e) {}
  }
  setTimeout(attempt, 800);
})();
