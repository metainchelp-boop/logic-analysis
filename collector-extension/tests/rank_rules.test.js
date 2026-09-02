/* 순위 규칙 회귀 테스트 — 신고 #253 (2026-09-02)
 *
 * 검사 대상은 확장이 실제로 쓰는 rank_rules.js **그 파일**이다(사본 금지 — 한 규칙 한 곳).
 * 픽스처는 코덱스가 라이브 네이버에서 실측한 구조를 그대로 옮겼다:
 *   · 광고: adId·adType·adcrUrl(ader.naver.com) 세 필드 동시 존재 + mallProductUrl 도 있음
 *   · 오가닉: mallProductUrl 있음 + crUrl 에 /adcr 이 들어 있음(광고 아님!)
 *   · 사고 형태: 원본 66번째 상품 앞에 광고 21개 → 광고 제외 시 45위인데,
 *     판별이 눈멀어 광고가 순번을 먹고(중복 제거로 10개만 우연히 빠짐) 56위로 기록됨
 * 실행: node collector-extension/tests/rank_rules.test.js  (배포 게이트에서 매번 돈다)
 */
'use strict';
const { isAdItem, hasAdHint, toProduct, takeOrganic } = require('../rank_rules.js');

let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log('PASS  ' + name); }
  else { failed++; console.log('FAIL  ' + name + (detail ? ' — ' + detail : '')); }
}

/* ── 픽스처(전부 예시 값 — 실업체명·실상품 미사용) ── */
let seq = 0;
function mkOrg(id, mall) {
  return {
    id: String(id), productTitle: '오가닉 상품 ' + id, mallName: mall || '가게' + id,
    mallProductUrl: 'https://smartstore.naver.com/shop' + id + '/products/' + (900000 + (seq++)),
    crUrl: 'https://cr.shopping.naver.com/adcr?x=' + id,   // ⚠️ 요즘 오가닉에도 /adcr 이 있다
    price: '10000',
  };
}
function mkAd(id) {
  return {
    id: String(id), productTitle: '광고 상품 ' + id, mallName: '가게' + id,
    mallProductUrl: 'https://smartstore.naver.com/shop' + id + '/products/' + (800000 + (seq++)),
    adId: 'nad-a001-' + id, adType: 'PRODUCT_AD',
    adcrUrl: 'https://ader.naver.com/v1/click/' + id,      // 신형 — 'adcr' 문자열이 없다
    crUrl: 'https://cr.shopping.naver.com/adcr?x=' + id,
    price: '10000',
  };
}
function mkLegacyAd(id) {
  return {   // 구형 광고 — mallProductUrl 없음, adcrUrl 이 cr.shopping.naver.com/adcr
    id: String(id), productTitle: '구형 광고 ' + id, mallName: '',
    adcrUrl: 'https://cr.shopping.naver.com/adcr?nvadid=' + id,
    price: '10000',
  };
}
function freshState() {
  return { products: [], seenIds: new Set(), maxRank: 300,
           adSkipped: 0, dupSkipped: 0, adHintMissed: 0 };
}

/* 사고 재현 원본 — 코덱스 라이브 실측 구조 그대로:
 * 66번째(대상) 앞에 오가닉 44 + 광고 21. 광고 21 중 10개는 상품 ID 가 **앞서 나온
 * 오가닉과 같다**(오가닉이 먼저, 광고가 뒤 — 그래서 종전 버그에서는 그 10개만 중복으로
 * 우연히 빠지고 11개가 순번을 먹어 45위가 정확히 56위로 밀렸다).
 * 광고 A0~A4 의 오가닉 쌍둥이는 대상 **뒤**에 온다(광고가 먼저 — id 선점 사고 축). */
function buildLiveList() {
  const raw = [];
  for (let d = 0; d < 10; d++) raw.push(mkOrg('D' + d));       // 오가닉(광고의 원래 자리)
  for (let d = 0; d < 10; d++) raw.push(mkAd('D' + d));        // 같은 id 의 광고 — 뒤에 옴
  for (let a = 0; a <= 10; a++) raw.push(mkAd('A' + a));       // 광고 11개(id 겹침 없음)
  for (let o = 0; o < 34; o++) raw.push(mkOrg('O' + o));       // 나머지 오가닉
  if (raw.length !== 65) throw new Error('픽스처 구성 오류 ' + raw.length);
  raw.push(mkOrg('TARGET', '대상가게'));                       // 66번째 = 대상
  for (let a = 0; a < 5; a++) raw.push(mkOrg('A' + a));        // 광고 A0~A4 의 오가닉 쌍둥이
  for (let t = 0; t < 15; t++) raw.push(mkOrg('T' + t));       // 뒤쪽 평범한 오가닉
  return raw;
}

/* ① 이번 라이브 구조에서 56위가 45위로 정상화되는지 (80개 보기 한 장) */
{
  const st = freshState();
  takeOrganic(buildLiveList(), st);
  const target = st.products.find((p) => p.productId === 'TARGET');
  check('① 대상 상품이 45위다(종전 버그로는 56위)', target && target.rank === 45,
        '실제 ' + (target ? target.rank : '미발견'));
  check('①-보조 광고 21개가 전부 걸러졌다', st.adSkipped === 21, '실제 ' + st.adSkipped);
}

/* ② 광고와 오가닉이 같은 상품 ID 인 경우 오가닉이 보존되는지 */
{
  const st = freshState();
  takeOrganic(buildLiveList(), st);
  const twin = st.products.find((p) => p.productId === 'A0');
  check('② 광고의 오가닉 쌍둥이가 순위에 남는다', !!twin,
        '광고 자리가 seenIds 를 선점하면 여기서 사라진다');
  check('②-보조 중복 제거는 0건(광고가 id 를 선점하지 않으므로)', st.dupSkipped === 0,
        '실제 ' + st.dupSkipped);
}

/* ③ 정상 상품 crUrl 에 /adcr 이 있어도 제외되지 않는지 */
check('③ 오가닉(crUrl 에 /adcr)은 광고가 아니다', !isAdItem(mkOrg('X')), '');

/* ④ 과거 레거시 cr.shopping.naver.com/adcr 광고도 계속 제외되는지 */
check('④ 구형 광고(레거시 링크)도 계속 걸린다', isAdItem(mkLegacyAd('L1')), '');
check('④-보조 신형 광고(세 필드 조합)가 걸린다', isAdItem(mkAd('N1')), '');

/* ⑤⑥ 40개 보기로 쪼개 돌려도 같은 답인지 — 2페이지 5번째 = 전체 45위 */
{
  const raw = buildLiveList();
  // 오가닉 40개가 차는 지점까지가 1페이지(코덱스 실측: 페이지당 오가닉 40 + 광고 얹힘)
  let cut = 0, orgSeen = 0;
  for (; cut < raw.length && orgSeen < 40; cut++) if (!isAdItem(raw[cut])) orgSeen++;
  const st = freshState();
  takeOrganic(raw.slice(0, cut), st);
  const page1Kept = st.products.length;
  takeOrganic(raw.slice(cut), st);
  const target = st.products.find((p) => p.productId === 'TARGET');
  check('⑤ 40개 보기 1페이지 오가닉이 40개다', page1Kept === 40, '실제 ' + page1Kept);
  check('⑥ 2페이지에서 대상이 5번째(전체 45위)다',
        target && target.rank === 45 && target.rank - page1Kept === 5,
        '실제 ' + (target ? target.rank : '미발견') + ' (1페이지 ' + page1Kept + ')');
}

/* ⑦ 광고 표식 없는 일반 상품의 순위가 변하지 않는지 */
{
  const st = freshState();
  takeOrganic([mkOrg('P1'), mkOrg('P2'), mkOrg('P3')], st);
  const ranks = st.products.map((p) => p.rank).join(',');
  check('⑦ 광고 없는 목록은 1,2,3 그대로다', ranks === '1,2,3', '실제 ' + ranks);
  check('⑦-보조 광고 제외 0 · 힌트 0', st.adSkipped === 0 && st.adHintMissed === 0, '');
}

/* 번외 — 판별을 '모든 URL 에서 adcr 찾기'로 넓히면 안 되는 이유가 지켜지는지:
 * 오가닉 40개짜리 목록에서 단 하나도 광고로 걸리면 안 된다. */
{
  const st = freshState();
  const orgs = []; for (let i = 0; i < 40; i++) orgs.push(mkOrg('Z' + i));
  takeOrganic(orgs, st);
  check('번외 오가닉 40개 전량 보존(과잉 판별 없음)', st.products.length === 40,
        '실제 ' + st.products.length);
}

/* 워커 전역 합본 컴파일 — importScripts 는 rank_rules.js 와 background.js 를 **같은
 * 전역**에 합쳐 읽는다. 파일 한 장씩의 node --check 로는 이름 재선언 충돌을 못 잡아
 * 맥미니 적용 첫 판에서 'isAdItem has already been declared' 로 워커가 죽었다(실사고).
 * 그래서 두 파일을 실제로 이어 붙여 컴파일한다(실행은 안 함 — chrome.* 무해). */
{
  const fs = require('fs'), path = require('path'), vm = require('vm');
  const dir = path.join(__dirname, '..');
  const combined = fs.readFileSync(path.join(dir, 'rank_rules.js'), 'utf8')
    + '\n' + fs.readFileSync(path.join(dir, 'background.js'), 'utf8')
        .replace(/importScripts\([^)]*\);/, '');   // 합본이 곧 importScripts 결과다
  let err = null;
  try { new vm.Script(combined, { filename: 'worker-combined.js' }); } catch (e) { err = e; }
  check('워커 전역 합본이 컴파일된다(이름 재선언 충돌 없음)', !err, err && err.message);
}

console.log('');
if (failed) { console.log(failed + '개 실패'); process.exit(1); }
console.log('rank_rules 회귀 전부 통과');
