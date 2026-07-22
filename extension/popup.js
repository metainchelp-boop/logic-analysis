/* 팝업 — 현재 탭 감지 + FAB 트리거 */
document.addEventListener('DOMContentLoaded', function () {
  var st = document.getElementById('pg-status');
  var btn = document.getElementById('send-btn');
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    var tab = tabs && tabs[0];
    var url = (tab && tab.url) || '';
    var isProduct = /smartstore\.naver\.com\/.+\/products\/\d+/.test(url);
    if (isProduct) {
      st.textContent = '스마트스토어 상품 ✓';
      st.className = 'pill pg';
      btn.disabled = false;
      btn.addEventListener('click', function () {
        chrome.tabs.sendMessage(tab.id, { type: 'METAINC_TRIGGER' }, function () {
          window.close();
        });
      });
    } else {
      st.textContent = '상품 페이지 아님';
      st.className = 'pill pr';
    }
  });
});
