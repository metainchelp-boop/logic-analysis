/* 순위 읽기 도우미 — 화면이 받은 검색 결과를 옆에서 읽는다 (MAIN 세계 · document_start)
 *
 * 무엇을 하나
 *   · 첫 화면(서버가 그려 보낸 1페이지 · 또는 주소로 바로 연 N페이지)은 __NEXT_DATA__ 에서 읽는다.
 *   · 직원이 페이지를 넘기거나 검색창에 다시 치면 화면이 스스로 검색 결과를 받아 온다 —
 *     그 응답을 **화면이 받는 자리에서 복사**만 한다(fetch·XHR 를 감싸되 요청은 그대로 흘려보낸다).
 *   · 읽은 목록을 같은 탭의 human_view.js 로 넘긴다(문자열 사건 — 세계 사이에는 문자열만 건너간다).
 *
 * 하지 않는 것 (바꾸지 말 것)
 *   · 네이버에 요청을 보내지 않는다 — 검색·클릭·페이지 넘김·스크롤 전부 없다.
 *   · 요청을 고치지 않는다(주소·헤더·본문 그대로).
 *   · 기본 보기(관련도순 · 전체 상품 · 40개씩)가 아닌 화면은 읽지 않는다 — 가격순·필터 화면은 순위가 아니다.
 *
 * ⚠️ 이 파일은 페이지 안에서 돈다 — 확장 API 를 못 쓰고, 바깥 변수도 없다.
 * ⚠️ 규칙 원본: 기본 보기 판정은 collector-extension/net_tap.js 의 defaultScope 와 같다.
 */
(function () {
  try { if (window.__mcHv) return; window.__mcHv = { at: Date.now() }; } catch (e) { return; }

  var KEEP = ['nvMid', 'id', 'productId', 'productTitle', 'productName', 'mallProductUrl', 'adcrUrl', 'crUrl',
              'price', 'lowPrice', 'mallName', 'mallNm', 'brand', 'maker', 'category1Name', 'category2Name',
              'category3Name', 'reviewCount'];

  function defaultScope(url) {
    var keys = ['query', 'pagingIndex', 'pagingSize', 'sort', 'productSet', 'viewType', 'origQuery', 'adQuery', 'frm'];
    var it = url.searchParams.keys(), k;
    while (!(k = it.next()).done) { if (keys.indexOf(k.value) < 0 || url.searchParams.getAll(k.value).length !== 1) return false; }
    return (!url.searchParams.has('sort') || url.searchParams.get('sort') === 'rel')
      && (!url.searchParams.has('productSet') || url.searchParams.get('productSet') === 'total')
      && (!url.searchParams.has('pagingSize') || url.searchParams.get('pagingSize') === '40');
  }
  function knownSource(url) {
    return url.protocol === 'https:' && url.hostname === 'search.shopping.naver.com'
      && (url.pathname === '/api/search/all' || /^\/_next\/data\/[^/]+\/search\/all\.json$/.test(url.pathname)
          || url.pathname === '/search/all');
  }
  function pageOf(url) {
    var p = url.searchParams.get('pagingIndex');
    return p && /^[1-9]\d*$/.test(p) ? Number(p) : 1;
  }

  function looksProduct(o) {
    if (!o || typeof o !== 'object') return false;
    var hasTitle = typeof o.productTitle === 'string' || typeof o.productName === 'string';
    if (!hasTitle) return false;
    return o.mallName !== undefined || o.nvMid !== undefined || o.id !== undefined
        || o.mallProductUrl !== undefined || o.crUrl !== undefined;
  }
  function unwrap(el) {
    if (looksProduct(el)) return el;
    if (el && typeof el === 'object' && looksProduct(el.item)) return el.item;
    return null;
  }
  /* 수집기 pageExtract 와 같은 판독 — 경로를 고정하지 않고 「상품처럼 생긴 객체 배열」 중 가장 긴 것 */
  function extract(root) {
    var best = null, total = 0, seen = new Set(), stack = [root], guard = 0;
    while (stack.length && guard++ < 300000) {
      var cur = stack.pop();
      if (!cur || typeof cur !== 'object' || seen.has(cur)) continue;
      seen.add(cur);
      if (Array.isArray(cur)) {
        var got = [];
        for (var i = 0; i < cur.length; i++) { var u = unwrap(cur[i]); if (u) got.push(u); }
        if (got.length && got.length * 2 >= cur.length && (!best || got.length > best.length)) best = got;
        for (var j = 0; j < cur.length; j++) if (cur[j] && typeof cur[j] === 'object') stack.push(cur[j]);
      } else {
        for (var k in cur) {
          var v = cur[k];
          if (typeof v === 'number' && v > total && (k === 'total' || k === 'totalCount' || k === 'productCount')) total = v;
          if (v && typeof v === 'object') stack.push(v);
        }
      }
    }
    return { list: best || [], total: total };
  }
  /* 광고 판별·식별에 쓰는 칸만 남긴다(값은 글자·숫자·참거짓만). 나머지는 버린다. */
  function prune(p) {
    var o = {};
    for (var k in p) {
      if (!Object.prototype.hasOwnProperty.call(p, k)) continue;
      if (KEEP.indexOf(k) < 0 && !/^ad/i.test(k)) continue;
      var v = p[k];
      if (typeof v === 'string') o[k] = v.slice(0, 500);
      else if (typeof v === 'number' || typeof v === 'boolean') o[k] = v;
    }
    return o;
  }
  function emit(keyword, page, root, src) {
    try {
      if (!keyword) return;
      var r = extract(root);
      if (!r.list.length) return;
      var list = [];
      for (var i = 0; i < r.list.length && i < 200; i++) list.push(prune(r.list[i]));
      document.dispatchEvent(new CustomEvent('__mc_hv_page', { detail: JSON.stringify(
        { keyword: keyword, page: page, total: r.total, src: src, list: list, at: Date.now() }) }));
    } catch (e) { /* 읽기 실패는 조용히 — 화면 동작을 건드리지 않는다 */ }
  }
  function onResponse(reqUrl, status, text) {
    try {
      if (status !== 200) return;
      var url = new URL(String(reqUrl), location.href);
      if (!knownSource(url) || !defaultScope(url)) return;
      var q = url.searchParams.get('query') || '';
      var s = String(text || '');
      if (s.indexOf('"productTitle"') < 0 && s.indexOf('"productName"') < 0) return;
      emit(q, pageOf(url), JSON.parse(s), 'tap');
    } catch (e) {}
  }
  function mask(wrapped, orig) {
    try { wrapped.toString = function () { return Function.prototype.toString.call(orig); }; } catch (e) {}
    return wrapped;
  }

  // ── 첫 화면: 서버가 그려 보낸 데이터 ──
  function firstScreen() {
    try {
      var url = new URL(location.href);
      if (url.pathname !== '/search/all' || !defaultScope(url)) return;
      var nd = window.__NEXT_DATA__;
      if (!nd) {
        var el = document.getElementById('__NEXT_DATA__');
        if (el) nd = JSON.parse(el.textContent || 'null');
      }
      if (nd) emit(url.searchParams.get('query') || '', pageOf(url), nd, 'first');
    } catch (e) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', firstScreen, { once: true });
  else firstScreen();

  // ── 화면이 스스로 받아 오는 응답(페이지 넘김·다시 검색) ──
  try {
    var of = window.fetch;
    if (typeof of === 'function') {
      window.fetch = mask(function (input) {
        var u = '';
        try { u = (input && typeof input === 'object' && input.url) ? input.url : String(input); } catch (e) { u = ''; }
        var p = of.apply(this, arguments);
        try {
          p.then(function (res) {
            try {
              if (!/search\.shopping\.naver\.com/.test(String(res && res.url || u))) return;
              res.clone().text().then(function (t) { onResponse(res.url || u, res.status, t); }).catch(function () {});
            } catch (e) {}
          }).catch(function () {});
        } catch (e) {}
        return p;
      }, of);
    }
  } catch (e) {}
  try {
    var XP = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
    if (XP && typeof XP.open === 'function' && typeof XP.send === 'function') {
      var xo = XP.open, xs = XP.send;
      XP.open = mask(function (m, u) { try { this.__mcHvUrl = String(u || ''); } catch (e) {} return xo.apply(this, arguments); }, xo);
      XP.send = mask(function () {
        try {
          var x = this;
          x.addEventListener('loadend', function () {
            try {
              var t = (x.responseType === '' || x.responseType === 'text') ? x.responseText
                    : (x.responseType === 'json' ? JSON.stringify(x.response) : '');
              if (t) onResponse(x.responseURL || x.__mcHvUrl, x.status, t);
            } catch (e) {}
          });
        } catch (e) {}
        return xs.apply(this, arguments);
      }, xs);
    }
  } catch (e) {}
})();
