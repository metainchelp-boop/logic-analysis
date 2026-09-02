/* METAINC 로직분석 수집기 — 스마트스토어 상품 페이지 플로팅 버튼(FAB)
 * 시안 v1: 키워드 입력 → [보내기] → ①자동 스크롤(lazy 전부 로드) → ②완전 수집 → ③전송
 * 실패해도 페이지·기존 북마클릿 흐름에 어떤 영향도 없음(무해 실패 원칙). */
(function () {
  'use strict';
  if (window.top !== window) return; // iframe 내 실행 방지

  var FAB_ID = 'metainc-logic-fab';
  var running = false;

  function isProductPage() {
    return /^\/[^/]+\/products\/\d+\/?$/.test(location.pathname);
  }

  function $(id) { return document.getElementById(id); }

  function setStep(n, msg) {
    // n: 0=대기, 1=스크롤, 2=수집, 3=전송, 4=완료
    for (var i = 1; i <= 3; i++) {
      var el = $('metainc-step-' + i);
      if (el) el.className = 'metainc-step' + (i < n ? ' metainc-done' : (i === n ? ' metainc-on' : ''));
    }
    var st = $('metainc-fab-status');
    if (st && msg != null) st.textContent = msg;
  }

  function productName() {
    try {
      var og = document.querySelector('meta[property="og:title"]');
      if (og && og.content) return og.content.trim();
    } catch (e) {}
    return (document.title || '').trim();
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function autoScroll() {
    // 리뷰·상세 lazy 로딩이 전부 끝날 때까지 페이지 끝으로 반복 스크롤(높이 안정 3회 or 최대 40스텝 ≈ 25초)
    var lastH = 0, same = 0, steps = 0;
    while (steps < 40 && same < 3) {
      window.scrollTo(0, document.body.scrollHeight);
      await sleep(600);
      steps++;
      var h = document.body.scrollHeight;
      if (h === lastH) same++; else { same = 0; lastH = h; }
      setStep(1, '자동 스크롤 중… (' + steps + ') 리뷰·상세 로딩 대기');
    }
    window.scrollTo(0, 0);
    await sleep(400);
  }

  async function runCapture() {
    if (running) return;
    var kwInput = $('metainc-fab-keyword');
    var keyword = kwInput ? kwInput.value.trim() : '';
    if (!keyword) {
      setStep(0, '⚠️ 분석 키워드를 먼저 입력해주세요 (예: 콤부차)');
      if (kwInput) kwInput.focus();
      return;
    }
    running = true;
    var btn = $('metainc-fab-btn');
    if (btn) { btn.disabled = true; btn.textContent = '수집 중…'; }
    try {
      await autoScroll();

      setStep(2, '완전 수집 중…');
      await sleep(200);
      var html = document.documentElement.outerHTML;
      // 수집물 자가 검증 — 비정상(너무 작은) HTML은 전송하지 않음(빈 데이터 전송 원천 차단)
      if (!html || html.length < 30000) {
        setStep(0, '❌ 수집 실패(내용 부족) — 북마클릿으로 진행해주세요');
        return;
      }

      setStep(3, '로직분석으로 전송 중…');
      var payload = {
        html: html,
        product_url: location.href.split('?')[0],
        product_name: productName(),
        keyword: keyword,
        captured_at: Date.now()
      };
      chrome.runtime.sendMessage({ type: 'METAINC_CAPTURE', payload: payload }, function (res) {
        if (chrome.runtime.lastError || !res || !res.ok) {
          setStep(0, '❌ 전송 실패 — 다시 시도하거나 북마클릿으로 진행해주세요');
        } else {
          setStep(4, '✅ 전송 완료 — 로직분석 탭에서 분석이 시작됩니다 (' + Math.round(html.length / 1024) + 'KB)');
        }
      });
    } catch (e) {
      setStep(0, '❌ 오류: ' + (e && e.message ? e.message : '알 수 없음') + ' — 북마클릿으로 진행해주세요');
    } finally {
      running = false;
      if (btn) { btn.disabled = false; btn.textContent = '📥 이 상품 로직분석으로 보내기'; }
    }
  }

  function injectFab() {
    if ($(FAB_ID)) return;
    var box = document.createElement('div');
    box.id = FAB_ID;
    box.innerHTML =
      '<div class="metainc-fab-head"><span class="metainc-fab-logo">📊</span>METAINC 로직분석' +
      '<button type="button" id="metainc-fab-close" title="닫기">×</button></div>' +
      '<input type="text" id="metainc-fab-keyword" placeholder="분석 키워드 입력 (예: 콤부차)" autocomplete="off">' +
      '<button type="button" id="metainc-fab-btn">📥 이 상품 로직분석으로 보내기</button>' +
      '<div class="metainc-steps">' +
      '<span class="metainc-step" id="metainc-step-1">① 자동 스크롤</span>' +
      '<span class="metainc-step" id="metainc-step-2">② 완전 수집</span>' +
      '<span class="metainc-step" id="metainc-step-3">③ 전송</span></div>' +
      '<div id="metainc-fab-status">리뷰·상세가 전부 로드될 때까지 자동 스크롤 후 수집합니다.</div>';
    document.body.appendChild(box);
    $('metainc-fab-btn').addEventListener('click', runCapture);
    $('metainc-fab-close').addEventListener('click', function () { box.remove(); });
    $('metainc-fab-keyword').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') runCapture();
    });
  }

  function removeFab() {
    var el = $(FAB_ID);
    if (el && !running) el.remove();
  }

  // 팝업에서 "보내기" 트리거 시 FAB 표시·포커스
  try {
    chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
      if (msg && msg.type === 'METAINC_TRIGGER') {
        if (isProductPage()) {
          injectFab();
          var kw = $('metainc-fab-keyword');
          if (kw) kw.focus();
          sendResponse({ ok: true });
        } else {
          sendResponse({ ok: false, reason: 'not-product' });
        }
      }
      return false;
    });
  } catch (e) {}

  // SPA 라우팅 대응 — URL 변화 감시로 FAB 토글
  var lastHref = '';
  setInterval(function () {
    if (location.href === lastHref) return;
    lastHref = location.href;
    if (isProductPage()) injectFab(); else removeFab();
  }, 1500);
  if (isProductPage()) injectFab();
})();
