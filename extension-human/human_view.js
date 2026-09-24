/* 순위 읽기 도우미 — 화면 쪽 전달자 (ISOLATED 세계 · document_start)
 *
 * human_tap.js(페이지 세계)가 읽은 목록을 받아 로그인 여부를 붙여 확장 안(background)으로 넘긴다.
 * 서버로 보낼지 말지는 background 가 정한다(우리 추적 키워드일 때만).
 * ⚠️ 로그인 여부는 화면에 보이는 「로그인」·「로그아웃」 링크로만 본다 — 쿠키·계정은 읽지 않는다.
 */
(function () {
  function loginState() {
    try {
      if (document.querySelector('a[href*="nidlogin.logout"]')) return 'in';
      if (document.querySelector('a[href*="nidlogin.login"]')) return 'out';
    } catch (e) {}
    return 'unknown';
  }
  document.addEventListener('__mc_hv_page', function (ev) {
    try {
      var d = JSON.parse(String(ev.detail || ''));
      if (!d || !d.keyword || !Array.isArray(d.list)) return;
      // 첫 화면은 머리 부분이 아직 안 그려졌을 수 있다 — 조금 기다렸다 로그인 링크를 본다.
      setTimeout(function () {
        try {
          d.loggedIn = loginState();
          chrome.runtime.sendMessage({ type: 'hv-page', data: d }, function () { void chrome.runtime.lastError; });
        } catch (e) {}
      }, d.src === 'first' ? 1500 : 0);
    } catch (e) {}
  });
})();
