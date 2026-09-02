/* 팝업 — 현재 탭 감지 + FAB 트리거 */
function isNaverStoreProductUrl(rawUrl) {
  try {
    var url = new URL(rawUrl);
    var supportedHosts = ['smartstore.naver.com', 'brand.naver.com', 'm.brand.naver.com'];
    return url.protocol === 'https:' && supportedHosts.indexOf(url.hostname) !== -1 && /^\/[^/]+\/products\/\d+\/?$/.test(url.pathname);
  } catch (e) {
    return false;
  }
}

document.addEventListener('DOMContentLoaded', function () {
  var st = document.getElementById('pg-status');
  var btn = document.getElementById('send-btn');
  var version = document.getElementById('extension-version');
  if (version) version.textContent = 'v' + chrome.runtime.getManifest().version;
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    var tab = tabs && tabs[0];
    var url = (tab && tab.url) || '';
    var isProduct = isNaverStoreProductUrl(url);
    if (isProduct) {
      st.textContent = '네이버 스토어 상품 ✓';
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
