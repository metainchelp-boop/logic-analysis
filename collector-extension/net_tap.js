/* 응답 가로채기(net tap) — v1.13.0 (2026-09-15)
 *
 * 왜 만들었나
 *   2페이지부터는 화면 안의 페이지 버튼을 **클릭**해서 넘긴다(주소창 이동 = 차단 표식, 9/15 세 번 확인).
 *   그런데 클릭 뒤 우리가 읽던 두 곳 — 라우터 현재 props · __NEXT_DATA__ — 이 **둘 다 1페이지 그대로**인
 *   회차가 잇따랐다(21:30 갈비살 p2 · 21:39 감바스밀키트 p2, 29초를 기다려도 불변).
 *   화면이 2페이지를 그렸는지, 아니면 그리지 못했는지(응답이 막혔는지)를 **그 두 곳으로는 가릴 수 없다.**
 *
 *   네이버 화면이 2페이지를 그리려면 어딘가에서 **2페이지 데이터를 받아 와야 한다.** 그 응답을
 *   화면이 받는 그 자리에서 그대로 복사해 둔다. 우리가 요청을 **하나도 더 보내지 않는다** —
 *   화면이 스스로 한 요청의 답을 옆에서 읽을 뿐이다(요청 수·모양·시각 전부 사람 클릭 그대로).
 *
 * 어디서 도는가
 *   manifest `content_scripts` · `world: "MAIN"` · `run_at: "document_start"` —
 *   페이지 스크립트보다 먼저 페이지 세계에 들어가 `fetch` 와 `XMLHttpRequest` 를 감싼다.
 *   background 의 pageExtract(MAIN 세계 주입)가 `window.__mcTap` 을 읽는다.
 *
 * 무엇을 남기나 (값은 페이지 안에만 · 서버로는 요약만)
 *   items  — 본문에 상품 표식("nvMid"·"productTitle"·"mallName")이 있는 응답: 시각·경로·상태·크기·
 *            pagingIndex(주소에 있으면)·앞 3개 ID·JSON 본문. 최근 6건.
 *   misses — 그 밖의 응답: 시각·경로·상태·크기·앞 80자. 최근 20건. 어떤 경로를 부르는지 배우는 용도.
 *
 * ⚠️ 이 파일은 페이지 안에서 돈다 — 확장 API 를 쓸 수 없고, 바깥 변수도 없다.
 * ⚠️ 감싼 함수의 toString 은 원본과 같게 둔다(감싼 흔적이 문자열로 드러나지 않게).
 */
(function () {
  try {
    if (window.__mcTap) return;
  } catch (e) { return; }
  var T = { installed: Date.now(), items: [], misses: [], sequence: 0 };
  try { window.__mcTap = T; } catch (e) { return; }

  function pathOf(u) {
    try { var x = new URL(String(u), location.href); return x.host + x.pathname; }
    catch (e) { return String(u || '').slice(0, 80); }
  }
  function pageOf(u) {
    var m = /[?&]pagingIndex=(\d+)/.exec(String(u || ''));
    return m ? parseInt(m[1], 10) : 0;
  }
  /* 코덱스 1.22.0 이식(3차 · 2026-09-22) — 요청이 「우리가 아는 검색 요청」인지와 그 범위를 함께 남긴다.
   *   keyword·page  : 주소의 query·pagingIndex
   *   scopeVerified : 기본 범위(정렬 rel · productSet total · 페이지 크기 40 · 허용된 칸만)인가 — 다른 범위의 응답을
   *                   「그 키워드의 순위」로 읽지 않게 하는 표식(서버는 이 값을 판정에만 쓰고 요청은 안 바꾼다)
   *   sourceKnown   : search.shopping.naver.com 의 /api/search/all 또는 _next/data …/search/all.json GET 인가
   * ⚠️ 여기서 요청을 바꾸거나 더 보내지 않는다 — 읽어서 적을 뿐이다. */
  function defaultScope(url) {
    var keys = ['query', 'pagingIndex', 'pagingSize', 'sort', 'productSet', 'viewType', 'origQuery', 'adQuery', 'frm'];
    var it = url.searchParams.keys(), k;
    while (!(k = it.next()).done) { if (keys.indexOf(k.value) < 0 || url.searchParams.getAll(k.value).length !== 1) return false; }
    return (!url.searchParams.has('sort') || url.searchParams.get('sort') === 'rel')
      && (!url.searchParams.has('productSet') || url.searchParams.get('productSet') === 'total')
      && (!url.searchParams.has('pagingSize') || url.searchParams.get('pagingSize') === '40');
  }
  function requestInfo(u, method) {
    var out = { requestStartedAt: Date.now(), requestId: T.installed + ':' + (++T.sequence),
                keyword: '', page: pageOf(u), path: pathOf(u), sourceKnown: false, scopeVerified: false };
    try {
      var url = new URL(String(u), location.href);
      out.keyword = url.searchParams.get('query') || '';
      var page = url.searchParams.get('pagingIndex');
      out.page = page && /^[1-9]\d*$/.test(page) ? Number(page) : 0;
      out.scopeVerified = defaultScope(url);
      out.sourceKnown = String(method || 'GET').toUpperCase() === 'GET'
        && url.protocol === 'https:' && url.hostname === 'search.shopping.naver.com'
        && (url.pathname === '/api/search/all' || /^\/_next\/data\/[^/]+\/search\/all\.json$/.test(url.pathname));
    } catch (e) {}
    return out;
  }
  function responseMatched(request, responseUrl) {
    try {
      var response = new URL(String(responseUrl), location.href);
      return response.protocol === 'https:'
        && response.host + response.pathname === request.path
        && (response.searchParams.get('query') || '') === request.keyword
        && defaultScope(response)
        && Number(response.searchParams.get('pagingIndex') || 0) === request.page;
    } catch (e) { return false; }
  }
  function idsOf(s) {
    var out = [], re = /"nvMid"\s*:\s*"?(\d+)/g, m;
    while (out.length < 3 && (m = re.exec(s))) { if (out.indexOf(m[1]) < 0) out.push(m[1]); }
    return out;
  }
  function record(url, status, text, request, responseUrl) {
    try {
      var s = String(text || '');
      var hit = s.indexOf('"nvMid"') >= 0 || s.indexOf('"productTitle"') >= 0 || s.indexOf('"mallName"') >= 0;
      var ent = { at: Date.now(), path: pathOf(url), page: pageOf(url), status: status | 0, size: s.length };
      if (request) {
        ent.keyword = request.keyword; ent.sourceKnown = request.sourceKnown; ent.scopeVerified = request.scopeVerified;
        ent.requestId = request.requestId; ent.requestStartedAt = request.requestStartedAt;
        ent.responseMatched = responseUrl ? responseMatched(request, responseUrl) : null;
      }
      if (hit && s.length < 8000000) {
        ent.ids = idsOf(s);
        try { ent.json = JSON.parse(s); } catch (e) { ent.json = null; ent.parse = 'fail'; }
        T.items.push(ent);
        while (T.items.length > 6) T.items.shift();
      } else {
        ent.head = s.slice(0, 80);
        T.misses.push(ent);
        while (T.misses.length > 20) T.misses.shift();
      }
    } catch (e) { /* 기록 실패는 무시 — 화면 동작을 건드리지 않는다 */ }
  }
  function textLike(ct) {
    // content-type 이 없으면 본다. 있으면 글자 계열만(이미지·폰트·미디어는 건너뛴다).
    if (!ct) return true;
    return /json|text|javascript|html|xml/i.test(String(ct));
  }
  function mask(wrapped, orig) {
    try { wrapped.toString = function () { return Function.prototype.toString.call(orig); }; } catch (e) {}
    return wrapped;
  }

  // ── fetch ──
  try {
    var of = window.fetch;
    if (typeof of === 'function') {
      var wf = function (input, init) {
        var url = '';
        try { url = (input && typeof input === 'object' && input.url) ? input.url : String(input); } catch (e) { url = ''; }
        var request = null;
        try { request = requestInfo(url, (init && init.method) || (input && input.method)); } catch (e) { request = null; }
        var p = of.apply(this, arguments);
        try {
          p.then(function (res) {
            try {
              var ct = (res && res.headers && typeof res.headers.get === 'function') ? res.headers.get('content-type') : '';
              if (!textLike(ct)) return;
              res.clone().text().then(function (t) { record(url, res.status, t, request, res.url); }).catch(function () {});
            } catch (e) {}
          }).catch(function () {});
        } catch (e) {}
        return p;
      };
      window.fetch = mask(wf, of);
    }
  } catch (e) {}

  // ── XMLHttpRequest ──
  try {
    var XP = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
    if (XP && typeof XP.open === 'function' && typeof XP.send === 'function') {
      var xo = XP.open, xs = XP.send;
      XP.open = mask(function (m, u) {
        try { this.__mcUrl = String(u || ''); this.__mcMethod = String(m || 'GET'); } catch (e) {}
        return xo.apply(this, arguments);
      }, xo);
      XP.send = mask(function () {
        try {
          var x = this;
          x.addEventListener('loadend', function () {
            try {
              var ct = '';
              try { ct = x.getResponseHeader('content-type') || ''; } catch (e) { ct = ''; }
              if (!textLike(ct)) return;
              var t = '';
              if (x.responseType === '' || x.responseType === 'text') t = x.responseText;
              else if (x.responseType === 'json') t = JSON.stringify(x.response);
              else return;
              var request = null;
              try { request = requestInfo(x.__mcUrl, x.__mcMethod); } catch (e) { request = null; }
              record(x.__mcUrl, x.status, t, request, x.responseURL);
            } catch (e) {}
          });
        } catch (e) {}
        return xs.apply(this, arguments);
      }, xs);
    }
  } catch (e) {}
})();
