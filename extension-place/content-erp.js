/* METAINC 로직분석 수집기 — 전산 포털 토큰 미러 (v1.1.0)
 * 전산(metainc.co.kr) 로그인 토큰(localStorage 'token')을 확장 저장소에 미러링.
 * 로직분석 탭을 열 때 ?sso=<토큰> 으로 자동 로그인하기 위함 — 전산 상단 메뉴의
 * '로직분석' 버튼과 완전히 동일한 공식 SSO 경로 재사용(서버 변경 없음).
 * 전산에서 로그아웃하면 미러도 즉시 삭제(오래된 토큰 오사용 방지). */
(function () {
  'use strict';
  var last = null;

  function mirror() {
    try {
      var raw = (localStorage.getItem('token') || '').replace(/^Bearer\s+/i, '');
      if (raw === last) return;
      last = raw;
      if (raw) chrome.storage.local.set({ metainc_erp_token: { token: raw, saved_at: Date.now() } });
      else chrome.storage.local.remove('metainc_erp_token');
    } catch (e) {}
  }

  mirror();
  setInterval(mirror, 60 * 1000);                 /* 전산 탭이 열려 있는 동안 최신 유지(토큰 갱신 반영) */
  window.addEventListener('storage', mirror);      /* 다른 탭에서 로그인/로그아웃 시 즉시 반영 */
  document.addEventListener('visibilitychange', function () { if (!document.hidden) mirror(); });
})();
