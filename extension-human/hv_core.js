/* 순위 읽기 도우미 — 순수 규칙 (chrome 의존 0 · background.js 와 node 시험이 같은 파일을 읽는다)
 *
 * 핵심 규칙: **1페이지부터 끊김 없이 본 만큼만** 순위를 매긴다.
 *   광고는 순위 번호를 먹지 않으므로(대표 확정 2026-08-12) 2페이지 첫 상품이 몇 위인지는
 *   1페이지의 오가닉 수를 알아야 정해진다. 그래서 같은 탭에서 1 → 2 → 3 … 차례로 본 페이지만 잇는다.
 *   중간 페이지로 바로 들어오면(주소로 3페이지를 열었다 등) 그 화면은 순위로 쓰지 않는다.
 * 순번 부여는 수집기와 **같은 함수**(RankRules.takeOrganic)를 쓴다 — rank_rules.js 는 수집기 것과 한 글자도 다르면 안 된다(게이트가 지킨다).
 */
(function () {
  const MAX_RANK = 300;
  const SESSION_MS = 30 * 60 * 1000;   // 같은 검색을 이어 보는 것으로 치는 시간

  /** 탭 상태에 페이지 한 장을 잇는다. 반환 { state, ok, reason } — ok=false 면 순위로 쓰지 않는다. */
  function mergePage(state, keyword, page, list, now) {
    const kw = String(keyword || '').trim();
    const p = Number(page) || 0;
    if (!kw || p < 1 || !Array.isArray(list) || !list.length) return { state, ok: false, reason: 'empty' };
    if (p === 1) return { state: { kw, pages: { 1: list }, at: now }, ok: true, reason: '' };
    const fresh = state && state.kw === kw && (now - (state.at || 0)) <= SESSION_MS;
    if (!fresh) return { state, ok: false, reason: 'need-page-1' };
    for (let i = 1; i < p; i++) {
      if (!state.pages[i]) return { state, ok: false, reason: 'gap' };
    }
    const pages = {};
    for (let i = 1; i < p; i++) pages[i] = state.pages[i];   // 뒤로 갔다 다시 넘기면 그 뒤 페이지는 버린다
    pages[p] = list;
    return { state: { kw, pages, at: now }, ok: true, reason: '' };
  }

  /** 이어 본 페이지들로 순위 목록을 만든다(수집기 SerpProduct 모양). */
  function build(state, RankRules, total) {
    const nums = Object.keys(state.pages).map(Number).sort((a, b) => a - b);
    const st = { products: [], seenIds: new Set(), maxRank: MAX_RANK, adSkipped: 0, dupSkipped: 0, adHintMissed: 0 };
    for (const n of nums) {
      st.sourcePage = n;
      RankRules.takeOrganic(state.pages[n], st);
    }
    const covered = st.products.length;
    // 결과 끝 — 네이버가 알려 준 전체 수만큼 다 담았을 때만. 애매하면 끝으로 치지 않는다
    // (끝으로 잘못 치면 못 찾은 대상이 「300위 밖」으로 적힌다 — 그 쪽이 더 나쁜 오보다).
    const endOfResults = Number(total) > 0 && covered >= Number(total);
    return { products: st.products, pagesRead: nums.length, covered, endOfResults, adSkipped: st.adSkipped };
  }

  /** 오늘 할 일 목록에 있는 키워드인가 — 목록이 없으면(서버에 못 닿음) 아무것도 보내지 않는다. */
  function isTracked(todoSet, keyword) {
    if (!todoSet || typeof todoSet.has !== 'function') return false;
    return todoSet.has(String(keyword || '').trim());
  }

  const HvCore = { mergePage, build, isTracked, MAX_RANK, SESSION_MS };
  if (typeof module !== 'undefined' && module.exports) module.exports = HvCore;
  if (typeof globalThis !== 'undefined') globalThis.HvCore = HvCore;
})();
