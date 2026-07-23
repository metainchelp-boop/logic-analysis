/* METAINC 로직분석 수집기 — 백그라운드: 수집물 보관 + 로직분석 탭 오픈 (v1.1.0)
 * 전산 포털에서 미러링한 토큰이 있으면 ?sso= 로 자동 로그인 탭을 연다.
 * (?sso 는 해시 앞 — 전산 포털 링크와 동일 형식. 토큰이 없거나 오래되면 일반 탭 → 로그인 폴백) */
chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (msg && msg.type === 'METAINC_CAPTURE') {
    chrome.storage.local.set({ metainc_pending_capture: msg.payload }, function () {
      if (chrome.runtime.lastError) { sendResponse({ ok: false }); return; }
      chrome.storage.local.get('metainc_erp_token', function (res) {
        var t = res && res.metainc_erp_token;
        /* 7일 넘은 미러 토큰은 사용하지 않음 — 어차피 만료라 401 왕복만 늘림 */
        var fresh = t && t.token && (Date.now() - (t.saved_at || 0) < 7 * 24 * 60 * 60 * 1000);
        var url = fresh
          ? 'https://logic.metainc.co.kr/?sso=' + encodeURIComponent(t.token) + '#home'
          : 'https://logic.metainc.co.kr/#home';
        chrome.tabs.create({ url: url });
        sendResponse({ ok: true });
      });
    });
    return true; // async sendResponse
  }
  if (msg && msg.type === 'METAINC_CLEAR') {
    chrome.storage.local.remove('metainc_pending_capture', function () {
      sendResponse({ ok: true });
    });
    return true;
  }
  return false;
});
