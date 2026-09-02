/* 순위 규칙(순수 함수) — 신고 #253 후속 (2026-09-02)
 *
 * 왜 파일을 따로 뒀나: 광고 판별·순번 부여가 background.js 안에 있으면 검사할 방법이
 * 없다(서비스워커는 chrome.* 없이 못 돌린다). 여기는 chrome 의존이 0 이라
 * background.js(importScripts)와 node 회귀 테스트가 **같은 파일**을 읽는다 — 한 규칙 한 곳.
 *
 * ── 광고 판별의 역사 ──
 * 2026-08-12 실측: 광고는 mallProductUrl 이 없고 클릭 주소가 cr.shopping.naver.com/adcr.
 *   → 첫 URL(mallProductUrl || adcrUrl || crUrl)에 'adcr' 포함 여부로 판별(v1.7.0).
 * 2026-09-02 실측(신고 #253, 코덱스 교차 확인): 네이버가 형식을 바꿨다 —
 *   ① 광고에도 mallProductUrl 이 생겨 첫 URL 검사가 눈멀었다(광고가 오가닉으로 계산됨).
 *   ② adcrUrl 도 cr.shopping.naver.com/adcr → ader.naver.com/v1/... 으로 바뀌었다.
 *   ③ 정상 오가닉의 crUrl 에도 /adcr 이 들어 있다 — **모든 URL에서 'adcr' 을 찾으면
 *      오가닉을 광고로 오인한다. 절대 그렇게 넓히지 말 것.**
 *   실측 근거: 40개 보기 2페이지 원본 51건 = 오가닉 40 + 광고 11.
 *   광고 11건 전부 adId·adType·adcrUrl 세 필드가 동시에 있었고(교집합 11·불일치 0),
 *   오가닉 40건에는 이 조합이 없었다.
 * 실사고: 바먹감귤/청귤 — 광고 21개가 순번을 먹어 45위가 56위로 기록됐다(정확히 11계단 =
 *   광고 21 중 중복 제거로 우연히 빠진 10개를 뺀 나머지).
 */

/** 이 상품이 '광고'인가 — 순위 번호를 주지 않기 위한 판별.
 *  ① 레거시(무회귀 유지): 첫 URL 에 'adcr' — 구형 광고(mallProductUrl 없음)를 계속 거른다.
 *  ② 2026-09 실측 조합: adId·adType·adcrUrl 세 필드 동시 존재.
 *  ⚠️ '덜 거르는' 쪽으로만 틀리게 유지한다 — 오가닉을 광고로 잘못 걸러 상품이 통째로
 *     사라지는 것(미노출 오보)이 광고를 못 거르는 것보다 나쁘다. */
function isAdItem(p) {
  if (!p || typeof p !== 'object') return false;
  const url = String((p.mallProductUrl || p.adcrUrl || p.crUrl) || '');
  if (url.includes('adcr')) return true;
  return !!(p.adId && p.adType && p.adcrUrl);
}

/** 링크·조합으로는 광고로 안 걸렸는데 광고 표식처럼 보이는 키를 가진 상품 수(진단 전용·거르지 않음) */
function hasAdHint(p) {
  if (!p || typeof p !== 'object') return false;
  for (const k in p) {
    if (/^ad(Id|cr|Product|Type|Rank)/i.test(k) && p[k]) return true;
  }
  return false;
}

/** 네이버 응답 → 서버가 쓰는 형태로 정리 */
function toProduct(p, rank) {
  return {
    rank,
    productId: String(p.id || p.nvMid || ''),
    title: String(p.productTitle || p.productName || '').replace(/<[^>]*>/g, ''),
    link: String(p.mallProductUrl || p.adcrUrl || p.crUrl || ''),
    price: String(p.price || p.lowPrice || ''),
    mallName: String(p.mallName || p.mallNm || ''),
    brand: String(p.brand || p.maker || ''),
    category1: String(p.category1Name || ''),
    category2: String(p.category2Name || ''),
    category3: String(p.category3Name || ''),
    reviewCount: String(p.reviewCount || ''),
  };
}

/** 페이지 1장의 상품 목록에서 오가닉만 골라 누적 순번을 붙인다.
 *
 *  st = { products, seenIds, maxRank, adSkipped, dupSkipped, adHintMissed, onFirstAd? }
 *  — 광고·중복 제외 순서가 계약이다:
 *  ⭐ 광고는 순위 번호를 먹지 않는다(2026-08-12 대표 확정 「광고 제외로 가야 해」).
 *  ⚠️ 광고를 거를 때 seenIds 에 넣지 않는 것이 핵심 — 광고주 상품은 '광고 자리'와
 *     '오가닉 자리'로 두 번 나오는데, 광고 자리가 id 를 선점하면 진짜 오가닉 자리가
 *     중복으로 걸러져 그 업체가 통째로 미노출로 보고된다.
 *     (신고 #253 이 정확히 그 반대 사고였다 — 광고 판별이 눈멀자 광고가 id 를 선점해
 *      오가닉 자리가 지워지고 광고 자리가 순위에 남았다.) */
function takeOrganic(list, st) {
  for (let idx = 0; idx < list.length; idx++) {
    if (st.products.length >= st.maxRank) break;
    const item = list[idx];
    if (isAdItem(item)) {
      st.adSkipped++;
      if (st.adSkipped === 1 && typeof st.onFirstAd === 'function') st.onFirstAd(item);
      continue;
    }
    if (hasAdHint(item)) st.adHintMissed++;
    const mapped = toProduct(item, st.products.length + 1);
    if (mapped.productId && st.seenIds.has(mapped.productId)) { st.dupSkipped++; continue; }
    if (mapped.productId) st.seenIds.add(mapped.productId);
    mapped.rank = st.products.length + 1;   // 광고·중복을 건너뛴 자리를 메운 최종 순위
    st.products.push(mapped);
  }
  return st;
}

const RankRules = { isAdItem, hasAdHint, toProduct, takeOrganic };
if (typeof module !== 'undefined' && module.exports) module.exports = RankRules;
if (typeof globalThis !== 'undefined') globalThis.RankRules = RankRules;
