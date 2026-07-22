/* METAINC 로직분석 수집기 — 백그라운드: 수집물 보관 + 로직분석 탭 오픈 */
chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (msg && msg.type === 'METAINC_CAPTURE') {
    chrome.storage.local.set({ metainc_pending_capture: msg.payload }, function () {
      if (chrome.runtime.lastError) { sendResponse({ ok: false }); return; }
      chrome.tabs.create({ url: 'https://logic.metainc.co.kr/#home' });
      sendResponse({ ok: true });
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
