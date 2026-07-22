/* METAINC 로직분석 수집기 — 로직분석 페이지 브리지
 * 보관된 수집물을 앱에 postMessage로 전달. 앱이 ACK 하면 보관물 삭제.
 * 로그인 전이면 앱이 ACK를 안 하므로 30초간 재시도(로그인 후 자동 수신). */
(function () {
  'use strict';
  var tries = 0;
  var acked = false;

  window.addEventListener('message', function (ev) {
    if (ev.source !== window || !ev.data) return;
    if (ev.data.type === 'METAINC_EXT_ACK') {
      acked = true;
      try { chrome.runtime.sendMessage({ type: 'METAINC_CLEAR' }); } catch (e) {}
    }
  });

  function attempt() {
    if (acked || tries >= 30) return;
    try {
      chrome.storage.local.get('metainc_pending_capture', function (res) {
        if (acked) return;
        var cap = res && res.metainc_pending_capture;
        if (!cap || !cap.html) return;
        if (Date.now() - (cap.captured_at || 0) > 10 * 60 * 1000) {
          try { chrome.runtime.sendMessage({ type: 'METAINC_CLEAR' }); } catch (e) {}
          return; // 10분 지난 수집물은 폐기(오래된 데이터 오주입 방지)
        }
        window.postMessage({ type: 'METAINC_EXT_CAPTURE', payload: cap }, window.location.origin);
        tries++;
        setTimeout(attempt, 1000);
      });
    } catch (e) {}
  }
  setTimeout(attempt, 800);
})();
