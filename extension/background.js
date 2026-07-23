/* METAINC 로직분석 수집기 — 백그라운드: 수집물 보관 + 로직분석 탭 오픈 (v1.1.2)
 *
 * 자동 로그인(SSO) 토큰 확보 — 2단계:
 *  1순위) [보내기] 시점에 열려 있는 전산 포털 탭에서 토큰을 즉석으로 읽음(chrome.scripting).
 *         → 전산 탭이 확장 설치 전부터 열려 있어 미러 스크립트가 주입 안 된 경우까지 커버.
 *  2순위) content-erp.js 가 미러링해 둔 저장 토큰(7일 이내) — 전산 탭이 닫혀 있을 때 폴백.
 * 둘 다 없으면 일반 탭 → 로그인 화면 폴백(대기 배너·10분 재시도).
 * (?sso 는 해시 앞 — 전산 포털의 '로직분석' 버튼과 동일 형식·동일 공식 경로) */

var ERP_URL_PATTERNS = [
  'http://metainc.co.kr/*',
  'https://metainc.co.kr/*',
  'http://www.metainc.co.kr/*',
  'https://www.metainc.co.kr/*'
];

/* 열려 있는 전산 탭에서 로그인 토큰을 직접 읽기 (실패 시 '' 콜백 — 어떤 오류도 전송을 막지 않음) */
function readErpTokenFromOpenTab(cb) {
  try {
    chrome.tabs.query({ url: ERP_URL_PATTERNS }, function (tabs) {
      if (chrome.runtime.lastError || !tabs || tabs.length === 0) { cb(''); return; }
      try {
        chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: function () {
            try { return (localStorage.getItem('token') || '').replace(/^Bearer\s+/i, ''); }
            catch (e) { return ''; }
          }
        }, function (results) {
          if (chrome.runtime.lastError) { cb(''); return; }
          var tok = (results && results[0] && results[0].result) || '';
          if (tok) { try { chrome.storage.local.set({ metainc_erp_token: { token: tok, saved_at: Date.now() } }); } catch (e) {} }
          cb(tok);
        });
      } catch (e) { cb(''); }
    });
  } catch (e) { cb(''); }
}

function openLogicTab(token) {
  var url = token
    ? 'https://logic.metainc.co.kr/?sso=' + encodeURIComponent(token) + '#home'
    : 'https://logic.metainc.co.kr/#home';
  chrome.tabs.create({ url: url });
}

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (msg && msg.type === 'METAINC_CAPTURE') {
    chrome.storage.local.set({ metainc_pending_capture: msg.payload }, function () {
      if (chrome.runtime.lastError) { sendResponse({ ok: false }); return; }
      readErpTokenFromOpenTab(function (liveTok) {
        if (liveTok) { openLogicTab(liveTok); sendResponse({ ok: true }); return; }
        chrome.storage.local.get('metainc_erp_token', function (res) {
          var t = res && res.metainc_erp_token;
          /* 7일 넘은 미러 토큰은 사용하지 않음 — 어차피 만료라 401 왕복만 늘림 */
          var fresh = t && t.token && (Date.now() - (t.saved_at || 0) < 7 * 24 * 60 * 60 * 1000);
          openLogicTab(fresh ? t.token : '');
          sendResponse({ ok: true });
        });
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
