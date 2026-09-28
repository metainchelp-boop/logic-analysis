
# 네이버 검색광고 API — 쇼핑검색광고 자동 운영용 사실 정리 (로컬 명세 기준)

작성 2026-09-27 · 읽기 전용 조사(파일 수정·API 호출 없음) · 비밀값 옮겨 적지 않음

**근거 약칭** (전부 스크래치패드 `/tmp/claude-0/-home-user/2324b47f-529e-5437-a1d6-c6b0a1ae585e/scratchpad/` 아래)
- `[NCC]` = `sa-pages/assets/json/ncc-heroes-ncc.json` · `[EST]` = `estimate.json` · `[RPT]` = `ncc-report.json` · `[MST]` = `master-report.json` · `[ATW]` = `atower.json`
- `[ERR]` = `searchad-apidoc/NaverSA_API_Error_Code_MAP.md` · `공지 파일명:줄` = `sa-pages/_posts/…`
- 숫자는 해당 파일의 줄 번호

---

## 0. 한눈에 보기 (결론)

1. **쇼핑 입찰 단위는 둘.** 그룹 기본 입찰가 `Adgroup.bidAmt`, 그리고 소재(상품) 한 건마다 붙는 `Ad.adAttr = {bidAmt, useGroupBidAmt}`입니다. `useGroupBidAmt=false`여야 소재 입찰가가 쓰입니다([NCC] 3915-3918, 4779).
   ⚠️ 그런데 명세의 소재 수정 API는 `fields`가 필수이고 허용 값이 `userLock`·`inspect` 두 개뿐입니다([NCC] 1190-1224). **소재 입찰가를 바꾸는 호출 방식이 명세에 적혀 있지 않습니다.** ③의 기존 코드는 `fields=adAttr`로 호출하는데, 실제로 되는지 실증한 기록은 없습니다.
2. **쇼핑몰 상품형·제품 카탈로그형은 키워드를 사지 않습니다**(키워드는 쇼핑 브랜드형만 추가 가능 — `2021-03-17-release-note.md:13`). 검색어를 **보는** 것은 두 가지로 됩니다: `NPLA_SCH_KEYWORD` 통계, 그리고 `SHOPPINGKEYWORD_DETAIL` 보고서. 반면 검색어를 **막는** API(제외 키워드)는 명세 문구상 "웹사이트 캠페인 전용"이라, 쇼핑에서 되는지는 미확인입니다.
3. **네이버 자체 자동입찰(`autobidStrategy`)** 은 쇼핑몰 상품형 그룹 전용입니다. 목표는 `MAX_CONV_VALUE`(전환가치 최대화) 하나뿐이고 나머지 값은 고정입니다. **ROAS 목표나 입찰 상한은 지금 쓸 수 없습니다**(`2025-10-15-release-note.md:38-42`).
   켜면 네이버가 기본입찰가·소재 노출 여부·실제 입찰가를 직접 관리합니다(:15). ⇒ **우리 엔진과 동시에 돌리면 서로 입찰가를 덮어씁니다.**
4. **입찰 추정**은 `/npla-estimate` 두 가지뿐입니다: 순위별 입찰가, 항상 노출되는 최소 입찰가. **"이 입찰가면 클릭이 몇 번" 같은 성과 예측은 쇼핑용이 없습니다**(성과 예측은 키워드용 `/estimate/performance`만 — [EST] 164, 213).
5. **통계**: `/stats`는 약 2시간 늦게 반영됩니다(2025-10-27부터). 시간대 분석(`hh24`)은 요청 시점부터 과거 7일까지만 됩니다. 쇼핑에서는 `avgRnk`(평균 순위)가 나오지 않습니다(파워링크 전용). 쇼핑 평균 순위는 검색어 보고서의 `Sum of AD rank ÷ Impression`으로만 구할 수 있습니다.
6. **A/B 전용 기능(캠페인 실험)은 API에 없습니다.** 소재 노출 방식 `adRollingType`도 쇼핑에는 해당되지 않습니다. 쓸 수 있는 도구는 입찰가 변형(소재·그룹), 성별·연령 가중치, PC·모바일 가중치, 시간 교대 후 비교, 소재 복사, 쇼핑 전용 URL 파라미터입니다.
7. **호출 한도의 숫자는 로컬 문서 어디에도 없습니다.** 정해진 것은 "호출 대상 계정마다 속도 제한", 429 가이드(많이 쌓이면 5분 이상 전면 중단), 대량 수정 한도 두 가지(키워드 200건, 추정 200건)뿐입니다. **쇼핑 소재 입찰 변경은 대량 경로가 없어 소재 1건에 호출 1번**입니다.

---

## 1. 캠페인·광고그룹·소재 구조

### 1-1. 캠페인
| 항목 | 사실 | 근거 |
|---|---|---|
| 유형 | `campaignTp` = `WEB_SITE`·`SHOPPING`·`POWER_CONTENTS`·`BRAND_SEARCH`·`PLACE` | [NCC] 6469 |
| 하루 예산 | `dailyBudget`(기본 0). **`useDailyBudget=true`일 때만 적용** | [NCC] 6485, 6593 |
| 소진 방식 | `deliveryMethod` = `ACCELERATED`(기본) / `STANDARD`(균등) | [NCC] 6490 |
| 켜고 끄기 | `userLock`(true = 노출 중지) | [NCC] 6603 |
| 부분 수정 | `PUT /ncc/campaigns/{id}?fields=` `userLock`·`budget`·`period` | [NCC] 1656 경로 |
| URL 파라미터 | `trackingUrlCustomParams` — **쇼핑검색 캠페인만**. 최대 5쌍, key·value 각 100바이트 이하, 영·한·일·숫자·`-`·`_`만 | [NCC] 6589, `2024-11-20-release-note.md` |
| 기간 필드 | `periodStartDt`/`periodEndDt`는 KST 자정을 UTC로 쓴 값(`…T15:00:00.000Z`)만 받음. 시·분·초가 섞이면 400 (2026-06-10부터) | [NCC] 6466 이후 설명, `2026-06-10-notice.md` |
| 삭제 | 캠페인 삭제 시 하위 요소도 함께 영구 삭제 | [NCC] 1580 |

### 1-2. 광고그룹 유형 (쇼핑 캠페인 안)
- 명세의 `adgroupType` 목록: `WEB_SITE, SHOPPING, INFORMATION, PRODUCT, BRAND_SEARCH, PLACE, CATALOG, BRAND_ZONE, SHOPPING_BRAND, LOCAL_AD, BRAND_NEW, DOOH`([NCC] 4752).
- 쇼핑 캠페인 안의 3종:
  - **`SHOPPING` = 쇼핑몰 상품형** (추정 · 공지 맥락으로 소거). 2018-09-19 공지가 CATALOG를 "쇼핑 캠페인의 새 그룹 유형"으로 추가했고, 2021-03-17 공지는 기존 유형을 "쇼핑몰 상품형·제품 카탈로그형"이라 부릅니다.
  - **`CATALOG` = 제품 카탈로그형**(`2018-09-19-release-note.md`).
  - **`SHOPPING_BRAND` = 쇼핑 브랜드형**(`2021-03-17-release-note.md:10-14`). 상품그룹 번호(`nccProductGroupId`) 필수, 키워드 추가 가능, 입찰가 최소 300원.
- 상품그룹(`ProductGroup`)은 API로 **등록할 수 없고 조회만** 됩니다(`GET /api/ncc/product-groups` — [NCC] 3230, `2021-03-17-release-note.md`).
  - `registrationMethod` `WHOLE`/`EACH`
  - `attrJson.productNvmids`(EACH일 때 노출 상품) / `excludeNvmids`(WHOLE일 때 제외 상품)

### 1-3. 소재(상품) 유형
- `Ad.type` 목록에서 쇼핑 관련: `SHOPPING_PRODUCT_AD`, `CATALOG_AD`, `SHOPPING_BRAND_AD`(라이트형), `SHOPPING_BRAND_IMAGE_THUMBNAIL_AD`, `SHOPPING_BRAND_IMAGE_BANNER_AD`([NCC] 4034).
- **브랜드형 소재 3종은 API로 등록할 수 없습니다**(`2021-03-17-release-note.md`, `2021-10-27-release-note.md`).
- `nccQi` = `SHOPPING_PRODUCT_AD`·`CATALOG_AD`의 품질지수, 1~7 ([NCC] 3960).
- ⚠️ **`SHOPPING_PRODUCT_AD`를 만들 때 보내는 `ad` 내용의 형식은 명세에 없습니다**(미확인). 관련 오류 코드: 3826 "상품id를 확인하세요", 3827 "해당 광고그룹에서는 등록할 수 없는 소재 유형"([ERR] 80-81).
  - 2026-09-16 공지의 응답 예시에는 `referenceKey`가 소재 단계에 나오는데, 명세의 `Ad` 정의에는 이 칸이 없습니다.

### 1-4. 소재 단위 입찰과 그룹 기본 입찰의 관계
- `Adgroup.bidAmt`: 그룹의 기본 입찰가. 70~100,000, 비우면 70([NCC] 4779).
- `Ad.adAttr`: "입찰 정보(쇼핑 소재면 필수)". 예시 `{"bidAmt":50,"useGroupBidAmt":true}`. 태그는 `#hidden-create #hidden-response #required-update`([NCC] 3915-3918, 4559-4560).
  - 읽는 법: `useGroupBidAmt=true`면 그룹가, `false`면 소재 자신의 `bidAmt`. 키워드도 같은 쌍을 씁니다(키워드 입찰 수정 시 `bidAmt`와 `useGroupBidAmt` 둘 다 필수 — [NCC] 2687).
- ⚠️ **어긋나는 점 2가지**
  1. 소재 수정 `PUT /ncc/ads/{adId}{?fields}`에서 `fields`는 `required: true`이고 허용 값은 `userLock`·`inspect`뿐입니다([NCC] 1190-1224). `adAttr`는 목록에 없습니다.
     ③ `metainc-content-studio/autobid/app/naverad.py:29-42`는 `params={"fields":"adAttr"}`로 부르지만, 성공 여부는 미확인입니다.
  2. 명세는 `adAttr`를 `#hidden-response`(응답에 안 나옴)로 표시합니다. 그런데 ③ 코드는 GET 응답에서 `adAttr`를 읽습니다(`verify_phase0.py:113`, `naverad.py:38`). 실측이 필요합니다.
- 쇼핑 상품 소재의 **최소 입찰가는 명세에 없습니다**. 예시 50은 예시일 뿐입니다(미확인). 추정 API의 입찰 설명에는 "unit: 10 KRW"라고 적혀 있습니다([EST] 564, 586).

### 1-5. 켜고 끄기
- 캠페인·그룹·소재 모두 `userLock`이 있습니다([NCC] 6603, 4956, 4057).
- 소재에는 시스템이 제어하는 `enable`이 따로 있습니다([NCC] 3936).
- 상태 사유 `statusReason`에 `LACK_OF_ACCOUNT_BALANCE`, `GROUP_LIMITED_BY_BUDGET` 등이 있습니다([NCC] Ad 정의). 사람이 끈 것과 시스템이 멈춘 것을 이 값으로 가를 수 있습니다.
- 그룹: `PUT /ncc/adgroups/{id}?fields=` `bidAmt·userLock·budget·networkBidWeight·targetLocation·targetTime·targetMedia·targetGender`([NCC] 835-870).

### 1-6. 예산
- 그룹 `dailyBudget` 70~1,000,000,000, `useDailyBudget`, 부분 수정 키 `fields=budget`([NCC] 4804, 4946).
- 공유 예산: `/api/ncc/shared-budgets*` — 생성·수정·그룹/캠페인 제외([NCC] 3312-3635).

### 1-7. 매체·기기·시간대 가중치 (쇼핑에서 되는지)
| 장치 | 쇼핑에서 | 근거 |
|---|---|---|
| `pcNetworkBidWeight`·`mobileNetworkBidWeight` (10~500, 기본 100) | 명세에 쇼핑 제외 문구 없음 → **실측 필요**(추정 가능) | [NCC] 4822, 4848 |
| `contentsNetworkBidWeight` (10~500) | **쇼핑 전용**("쇼핑 캠페인 이외에서는 무시") | [NCC] 4794 |
| `contentsNetworkBidAmt`·`useCntsNetworkBidAmt` | **쇼핑에서 안 씀** | [NCC] 4789, 4936 |
| 요일/시간 타겟팅(Criterion `SD`) | 타겟팅 가능, **가중치 불가** | `2022-04-26-release-note.md:72`, `2023-08-23-release-note.md:62` |
| 지역(`RL`) | 2023-10-18부터 추가. 단 `negative=true`만, 가중치 100만 | `2023-10-18-release-note.md:7-8` |
| 성별(`GN`)·연령(`AG`) | 타겟팅과 가중치(50~500) 모두 가능 | 위 표 · [NCC] 6806 |
| 이용자 세그먼트(`AD`) | 불가 | `2023-08-23-release-note.md:62` |
| 가중치 변경 | `PUT /ncc/criterion/{ownerId}/bidWeight?codes=&bidWeight=` | [NCC] 2335 |
| 타겟팅 교체 | `PUT /ncc/criterion/{ownerId}/{type}` — ⚠️ **본문에 없는 코드는 모두 "사용 안 함"으로 바뀜** | [NCC] 2398 |
| `targets`(targetTp: `MEDIA_TARGET`·`PC_MOBILE_TARGET`·`TIME_WEEKLY_TARGET`·`AD_TAG`…) | 지역·요일·성별·연령은 2022년에 Criterion으로 옮겨짐. `MEDIA_TARGET`의 쇼핑 적용은 설명 없음(플레이스 예시만) | [NCC] 9596, `2022-04-26-release-note.md:58-63`, `2024-11-13-release-note.md` |
| `systemBiddingType` | `NONE`/`ML`만(`MAXCONV`은 2025-08-13 금지, 2025-09-10에 NONE으로 일괄 전환) | [NCC] 4921, `2025-07-30-notice1.md:16-20` |
| Criterion 유형 `DV`·`CA` | 명세 목록에만 있고 설명·공지 없음 → 미확인 | [NCC] 6858 부근 |

---

## 2. 쇼핑 "키워드" — 검색어 단위 통제

- **쇼핑몰 상품형·카탈로그형은 키워드가 없습니다**(`2021-03-17-release-note.md:13`). 관련 오류: 3923 "해당 캠페인 유형에서는 키워드를 생성할 수 없습니다"([ERR] 118).
- **제외 키워드 API** `POST/GET/DELETE /api/ncc/adgroups/{id}/restricted-keywords`
  - 설명: "This feature is only available for adgroups of **website** campaign types"([NCC] 677-683, 737, 792).
  - `type` 값: `KEYWORD_PLUS_RESTRICT`(스마트블록·유사검색어) / `EXP_SEARCH`(확장검색)([NCC] 5172; `2024-09-13-release-note.md`).
  - 오류 3728 "키워드 확장 노출 제외키워드를 지원하지 않는 캠페인 유형"([ERR] 66).
  - ⚠️ 그런데 2026-09-16 공지는 **플레이스(LOCAL_AD)** 그룹에서 이 API를 쓰다가 ADVoost가 켜져 있으면 3754/4422로 막힌다고 적었습니다(`2026-09-16-release-note.md:150-157`). "웹사이트 전용" 문구가 낡았을 수 있습니다.
  - ⇒ **쇼핑 그룹에서 되는지는 미확인.** 정황상 쇼핑에도 제외어 개념이 있어 보입니다: 대량작업 종류 `ADD_RESTRICTED_KEYWORD`, 쇼핑 노출진단 스키마의 `restrictKeyword`·`exclusionTerms`([NCC] `NccMassJob`, `ShoppingExposureStatusDiagnosisExposureReasons`). 다만 두 정의 모두 명세에 **호출 경로가 없습니다.**
- `targetTp`의 `RESTRICT_KEYWORD_TARGET`·`NON_SEARCH_KEYWORD_TARGET`: 목록에만 있고 사용법 문서가 없습니다(미확인, [NCC] 9620-9634).
- **카탈로그형 전용 `AD_TAG` 타겟팅**: `CATALOG_AD`에만 적용, 태그 3~10자, 최대 30개(`PUT /ncc/targets/{id}` — [NCC] 3671-3677, `2019-02-27-release-note.md`).
- **쇼핑 브랜드형**: 키워드마다 `attr.shopping_brand_keyword_type` = 0(일반)/1(내 브랜드)/2(다른 브랜드), 최소 300원(`2021-03-17-release-note.md`).
- **검색어 데이터(보기만 가능)**
  - `GET /stats?id=<소재 또는 그룹 ID>&statType=NPLA_SCH_KEYWORD`([RPT] 441-464)
    - 쇼핑 캠페인 전용(`2016-10-17-release-note.md:16`), 최근 30일
    - 2017-09-26부터 **노출이 1번이라도 있었던 검색어** 기준. 노출 많은 순으로 조회당 최대 1,000건(`2017-09-27-release-note.md:16`)
    - 응답: `schKeyword·impCnt·clkCnt·drtCrto·salesAmt`([RPT] StatTypeResponse)
  - 대량 보고서 `SHOPPINGKEYWORD_DETAIL` / `SHOPPINGKEYWORD_CONVERSION_DETAIL`([RPT] 524)
    - 열 구성(`2018-02-21-release-note.md`): Date · Customer · Campaign · AdGroup · **Search keyword** · AD ID · BizChannel · **Hours** · Region · Media · PC/Mobile · Impression · Click · Cost · **Sum of AD rank**(+View count, 2019-05-30)
    - 전환판: Conversion Method(1 직접 / 2 간접) · Conversion Type · count · Sales
    - 2025-07-01부터 검색 매체만 집계, 검색어가 없는 노출은 행으로 제공하지 않음(`2025-06-02-notice1.md`)
    - Conversion Type은 문자열(`purchase`·`add_to_cart`…, 2024-07-03 — `2024-05-30-notice1.md`)
    - Cost는 정수(long)이고 VAT 포함(2026-03-30 — `2026-02-11-notice1.md`)

---

## 3. 자동입찰 `autobidStrategy`

- 광고그룹 칸 설명: "광고 그룹의 자동 입찰 전략(**쇼핑 검색 캠페인의 상품몰 유형만 유효**)"([NCC] 4775).
- 명세 정의 `AutobidStrategyRequest`([NCC] 5337-5406):
  - `autobidBidGoal`: `NONE, MAX_CLICK, MAX_CONV, MAX_CONV_VALUE, TARGET_CPA, TARGET_IMPRESSIONSHARE`
  - `autobidBidStrategy`: `NO_CAP, BID_CAP, COST_CAP, FIXED_BID, TARGET_ROAS` · `autobidBidStrategyValue`(숫자)
  - `autobidBidType`: `CPC, CPM, CPV, CPT` — "Only the current CPC value is valid"
  - `autobidTargetType`: `CMP, GRP, PDG` — "Only the current GRP value is valid"
  - `isAutobidActive`, `nccAutobidStrategyId`, `autobidTargetId`, `customerId`
- **2025-10-15 공지(실제로 쓸 수 있는 값)** (`2025-10-15-release-note.md:15-42`)
  - 대상: **전환 로그를 수집하고 있는 쇼핑몰 상품형** 그룹
  - 설정 방법: 그룹 생성·수정 API에 `autobidStrategy`를 넣음. 조회하면 전략 정보가 함께 옴
  - 고정값: `autobidTargetType=GRP` · `autobidBidType=CPC` · `autobidBidStrategy=NO_CAP` · `autobidBidStrategyValue=0`
  - 목표: `NONE` 또는 `MAX_CONV_VALUE`(전환가치 최대화)만
  - 동작: "**하루예산 내에서** … 광고그룹의 **기본입찰가와 각 소재의 노출 여부, 실제 입찰가를 관리**"
- **하루 예산이 필수인가**: 새 공지에는 명시가 없습니다(미확인). 옛 `MAXCONV`는 하루 예산이 없으면 오류였습니다(`2019-12-18-release-note.md:12`).
- **켜면 수동 입찰이 막히는가**: 새 공지에는 명시가 없습니다(미확인). 옛 `MAXCONV`는 "자동입찰 + 입찰가 입력 → 오류"(:13)였지만, 동시에 "개별 관리가 필요한 소재는 직접 입찰가 설정도 가능"(:17)이라고 적었습니다.
  ⇒ 설계상 **`isAutobidActive=true`인 그룹은 우리 입찰 조정 대상에서 빼야 합니다**(서로 덮어씀).
- **ROAS 목표는 쓸 수 없습니다**: `TARGET_ROAS`는 목록에만 있고, 공지상 전략은 `NO_CAP` 고정입니다.
- **ADVoost 쇼핑**: 정의만 있습니다([NCC] 5182-5257).
  - `AdvoostShoppingMigrationRequest`(일예산 10,000~100,000,000원, `nccAdgroupId` = "ADV 동시 등록을 trigger 할 쇼검 광고그룹 ID")
  - `AdvoostShoppingStatusResponse`(`advoostShoppingEligible`, 사유 `ALREADY_HAS_ACTIVE_PMAX` 등)
  - **호출 경로와 공지가 없습니다** → 미공개/미확인.

---

## 4. 입찰 추정 (estimate) — 쇼핑

| 경로 | 입력 | 출력 | 무엇을 예측하나 | 근거 |
|---|---|---|---|---|
| `POST /npla-estimate/average-position-bid/{type}` (`type`=`id`→`Ad.nccAdId`, `product`→`Ad.productId`) | `{device: PC\|MOBILE, items:[{key, position}]}` · 최대 200건 · position PC 1~10 / 모바일 1~5 | `NPLAEstimateBidByPosition {product, position, nccAdId, bid}` | 목표 평균 노출 순위에 필요한 입찰가 | [EST] 251-298, 504, 521, 568 |
| `POST /npla-estimate/exposure-minimum-bid/{type}` (위와 같은 type) | `{device, items:[문자열]}` · 최대 200건 | `NPLAEstimateBid {device, estimate:[{product, nccAdId, bid}]}` | 항상 노출되는 최소 입찰가 | [EST] 300-340, 611-720 |

- **쇼핑용 성과 예측(입찰가 → 노출·클릭·비용)은 없습니다.** `/estimate/performance{/type}`·`/estimate/performance-bulk`는 키워드(type `id`/`keyword`)용입니다([EST] 164, 213).
- 2017 공지의 응답 예시는 `items` 배열 형태라서 명세 스키마(단일 객체)와 모양이 다릅니다(`2017-01-12-release-note.md`). 실제 응답 모양은 미확인입니다.
- 쇼핑 **브랜드형 키워드** 상단 노출 최소 입찰가: `GET /api/ncc/estimate/shopping-brand/type/pc_mins|mobile_mins`(최대 200, 품질지수 4단계 기준). **로컬 `estimate.json`에는 없습니다**(`2021-09-15-release-note.md`).
- 2025-05-13부터 PC position 11~15를 넣으면 400입니다(`2025-05-13-notice1.md`).
- ⚠️ ③ `autobid/verify_phase0.py:136-141`은 `/npla-estimate/…/keyword`로 부릅니다. 명세의 type 목록(`id`/`product`)에 `keyword`는 없습니다.

---

## 5. 통계

### 5-1. `/stats`
- 경로: `GET /api/stats{?id|ids, fields, timeRange, datePreset, timeIncrement, breakdown}`([RPT] 209, 326)
- 조회 대상 ID: 캠페인·그룹·키워드·**소재**·Criterion
- `fields` 목록([RPT] 약 240-256): `impCnt, clkCnt, salesAmt, ctr, cpc, avgRnk, ccnt, recentAvgRnk, recentAvgCpc, pcNxAvgRnk, mblNxAvgRnk, crto, convAmt, ror, cpConv, viewCnt, purchaseCcnt, purchaseConvAmt, purchaseRor`
- 의미
  - **`salesAmt` = 광고비(VAT 포함)**("Cost Summation(VAT included)" — [RPT] DailyStatMap). 매출이 아닙니다.
  - `ccnt` = 전환수
  - `convAmt`·`ror`·`cpConv`·`crto`는 응답 스키마에 설명이 없습니다. 이름으로 보아 전환매출·광고수익률·전환당비용·전환율로 추정합니다.
  - `purchaseCcnt`·`purchaseConvAmt`(2026-03-30), `purchaseRor`(2026-05-13)
  - `avgRnk`는 "Only PC Powerlink+BZ site or Mobile Powerlink" → **쇼핑 순위가 아닙니다.**
  - `recentAvgRnk`·`recentAvgCpc`는 2025-10-27부터 0으로 고정(`2025-09-26-notice2.md:36`)
  - 신규 `pcNxAvgCpc`·`mblNxAvgCpc`(같은 공지 :13)는 **로컬 fields 목록에 없습니다**
  - `topImpRto`는 브랜드형 키워드 전용이고 2026-09-30부터 0 고정. 역시 로컬 목록에 없습니다
- 파라미터
  - `timeRange {"since","until"}`(KST)
  - `datePreset` today·yesterday·last7days·last30days·lastweek·lastmonth·lastquarter
  - `timeIncrement` 1 / allDays(`ids` 조회는 allDays만)
  - `breakdown` `pcMblTp|dayw|hh24|regnNo` 중 **하나만**([RPT] 283-302, 400-418)
  - 성별·연령·읍면동 breakdown은 2024-11-07에 삭제(`2024-11-07-release-note.md`)
- **breakdown(`hh24` 포함)은 요청 시점부터 과거 7일까지만** 됩니다(브랜드검색만 90일 — `2017-11-08-release-note.md:14`). 긴 기간의 시간대 분석은 대량 보고서의 `Hours` 열로 해야 합니다.
- `ids`에는 **같은 캠페인 유형의 ID만** 넣을 수 있습니다. 섞으면 400 / 코드 11003(`2017-11-08-release-note.md:17-21`). `ids` 최대 개수는 미확인입니다.
- Criterion ID(`ownerId~dictionaryCode`)로는 `hh24`를 볼 수 없습니다(`2022-04-26-release-note.md:218-224`).
- **반영 지연**: 2025-10-27부터 2시간(전에는 3시간). `cycleBaseTm`(반영된 마지막 시각)이 분 단위로 갱신(`2025-09-26-notice2.md:34-35`). 무효 클릭 등으로 최대 48시간 안에 값이 바뀔 수 있음(:26).

### 5-2. 대량 보고서 (비동기)
1. `POST /api/stat-reports {reportTp, statDt}` — 날짜 하루 단위([RPT] 893-906)
2. `GET /api/stat-reports/{id}`로 상태 확인 — `REGIST·RUNNING·BUILT·NONE·ERROR·WAITING·AGGREGATING`([RPT] 538-546)
3. `BUILT`가 되면 `downloadUrl`로 받기(2025-10-27 이후 생성분은 URL에 `fileVersion=v2` — `2025-10-20-notice1.md`)
4. `DELETE`로 정리

- `reportTp` 13종: `AD, AD_DETAIL, AD_CONVERSION, AD_CONVERSION_DETAIL, ADEXTENSION, ADEXTENSION_CONVERSION, EXPKEYWORD, SHOPPINGKEYWORD_DETAIL, SHOPPINGKEYWORD_CONVERSION_DETAIL, SHOPPINGBRANDPRODUCT, SHOPPINGBRANDPRODUCT_CONVERSION, CRITERION, CRITERION_CONVERSION`([RPT] 524)
- 2025-10-27 변경: 기존 보고서 전량 삭제, **보관 기간 14일**. 만든 뒤 데이터가 바뀌면 상태가 "**CHANGED**"가 되어 받을 수 없음 → 다시 만들어야 함(`2025-09-26-notice2.md:24-28`). ⚠️ `CHANGED`는 로컬 상태 목록에 없습니다.
- 2025-12-01부터 Content-Type 헤더를 중복으로 보내면 안 됨(`2025-10-30-notice1.md`). 제공 기간은 최근 2년(`2026-03-20-notice1.md`). 성별·연령 성과는 대량 보고서에 없음(`2021-03-10-notice1.md`).

### 5-3. 마스터 보고서
- `POST /master-reports {item, fromTime?}` — `fromTime`을 주면 그 시각 이후 바뀐 것만(델타)
- 상태 `REGIST·RUNNING·BUILT·NONE·ERROR`, 목록 조회는 최근 100개([MST] 24, 76, 168)
- `item`: `ShoppingProduct·CatalogAd·ProductGroup·ProductGroupRel·Adgroup·Ad·AdExtension·Criterion·SharedBudget·Qi` 등 30종
- Adgroup 마스터 19번 열 "Using Ai Ads"(2026-07-16 — `2026-06-16-notice1.md`). 계정 마스터는 2025-09-15에 종료.

---

## 6. A/B 테스트에 쓸 수 있는 장치

| 장치 | 쇼핑에서 | 근거 |
|---|---|---|
| 캠페인 실험·초안(experiment/draft) API | **없음**(명세 전체 경로 목록에 없음) | [NCC] paths 전수 |
| 소재 노출 방식 `adRollingType` (`ROUND_ROBIN`/`PERFORMANCE`) | **해당 없음** — `WEB_SITE`·`POWER_CONTENTS`에서만 유효, 나머지 기본 `ROUND_ROBIN` | `2018-07-18-release-note.md:8-10`, [NCC] 4739 |
| 같은 상품을 두 그룹에 두기 | `PUT /ncc/ads?ids&targetAdgroupId&userLock`(소재를 다른 그룹에 복사) 경로가 있음 → 복사는 가능. 두 소재가 경매에서 어떻게 처리되는지는 미확인. 오류 3822 "같은 내용의 소재가 이미 등록"이 어느 범위에 적용되는지도 미확인 | [NCC] 1255, [ERR] 77 |
| 확장소재 | `SHOPPING_EXTRA`는 **API로 만들 수 없음**. 쇼핑 브랜드형 확장 전부 불가. 카탈로그형 확장(`CATALOG_RELEASE_DATE·DETAIL·PROMOTION·MOVIE·BRAND_MESSAGE·PURCHASE_CONDITION`)은 가능. "추가홍보문구"라는 이름은 로컬 명세에 없음 → `SHOPPING_EXTRA`가 그것인지 미확인 | [NCC] AdExtension.type 설명, `2018-09-19`/`2019-01-30-release-note.md` |
| 확장소재 노출 시간표 | `schedule`(요일별 24시간 비트) + `usePeriod` — 만들 수 있는 확장에만 해당 | [NCC] AdExtension.schedule |
| **입찰가 변형** | 소재 단위(`adAttr.bidAmt`)·그룹 단위(`bidAmt`). 시간을 교대하며 바꾸고 `hh24`(7일)나 보고서 `Hours`로 비교 | §1-4, §5 |
| 성별·연령 가중치 | 50~500 | §1-7 |
| PC·모바일 가중치 | 10~500(쇼핑 적용은 실측 필요) | [NCC] 4822, 4848 |
| 랜딩 URL 파라미터 | `trackingUrlCustomParams`(쇼핑 캠페인 단위, 5쌍) | `2024-11-20-release-note.md` |

⚠️ 소재를 켜고 끄며 번갈아 돌리기(`userLock`)나 그룹 복사 방식의 A/B는 대표 확정 "승인 없이 자동"의 범위(A/B·입찰가 조정)와 "켜고 끄기·새 그룹 = 승인"이 겹칩니다 → **판단이 필요합니다.**

---

## 7. 호출 한도·오류

- **숫자로 된 호출 한도(초당·분당)는 로컬 문서 어디에도 없습니다**(미확인).
  - "사용량 제한은 **호출 대상 계정(커스터머)마다** 속도 제한, 전체 사용량에 따라 유연"(`2020-12-18-notice.md:11`)
  - 키워드 도구만 다른 기능의 1/5~1/6, IP 기준도 포함돼 IP당 약 1/2(:29-30)
  - 대응 지침: 429가 오면 기다렸다 재시도. 수 초 안에 429가 대량으로 쌓이면 **5분 이상 모든 호출 중단**. 여러 계정을 동시에 부를 때는 장비·네트워크를 나누라고 권고(:34-36)
- 오류표 중 한도 관련: `429` 요청 과다 · `1016` 너무 많은 접속 · `503` 정기점검 · `1014` 최대 허용개수 초과([ERR] 13, 15, 162-163)
- **한 번에 바꿀 수 있는 개수**
  - 키워드 대량 수정 `PUT /ncc/keywords?fields=` 200건([NCC] 2681-2687)
  - 키워드 생성 100건([NCC] 2897-2903)
  - 추정 200건([EST] 504 외)
  - 검수이력 100건(`2025-12-03-release-note.md`)
  - **소재·광고그룹은 대량 수정 경로가 없습니다**(한 건씩 PUT — [NCC] 1190, 549)
  - 목록 조회 `recordSize` 1~1000(캠페인 설명에는 "1~1000"과 "1~2000"이 섞여 있음 — [NCC] 951, 1752)
  - 매니저 하위 계정 목록 한 쪽 최대 1000개([ATW] 201)
- **입찰·예산 관련 오류 코드**
  - `2102` 입찰가 값 오류 · `3703` 그룹 입찰가 오류 · `3704` 그룹 일예산 오류 · `3505` 캠페인 일예산 오류 · `3720` 그룹 일예산 사용여부 오류 · `3717` 매체 가중치 오류 · `3724` 그룹 예산정보 없음 · `3726` 개별 필드 수정 미지원 · `3904`/`3916` 키워드 입찰가·기본입찰가 사용여부 오류 · `3713`/`3915` userLock 값 오류([ERR])
  - `11003` stats에 캠페인 유형 혼합(`2017-11-08`)
  - `3755` ADVoost ON 그룹의 고급옵션 변경 불가(bidAmt·가중치 포함, `2026-09-16-release-note.md:157`)
  - 기간 형식 400(`2026-06-10`) · `MAXCONV` 오류(`2025-07-30`)
- **대행사(매니저) 계정**
  - `GET /api/manager-accounts`, `/api/manager-accounts/{no}/child-ad-accounts`(`accountRole` = MASTER/READ_ONLY — [ATW] 121, 170, 673)
  - 요청마다 `X-Customer` 헤더로 대상 계정을 지정(`python-sample/examples/ad_management_sample.py:11`)
  - 옛 `/customer-links`는 2025-09-15 종료(`2025-08-07-notice2.md`). 그런데 공식 샘플 :23은 아직 옛 경로를 씁니다.
  - 2026-07-02: 계정 통합 후 일부 대행사의 API 비밀키가 바뀜 → 인증 오류가 나면 재발급(`2026-07-02-notice.md`)

---

## 8. 최근 변경 공지 중 자동화에 영향 주는 것

| 시점 | 내용 | 영향 |
|---|---|---|
| 2024-11-07 | stats breakdown 성별·연령·읍면동 삭제 | 인구통계 성과는 Criterion 기준으로만 |
| 2024-11-20 | 쇼핑 캠페인 `trackingUrlCustomParams` | A/B 표시에 활용 가능 |
| 2025-05-13 | estimate PC position 1~10 | 11~15는 400 |
| 2025-07-01 | 검색어 보고서를 검색 매체 기준으로 집계 | 검색어 없는 행 사라짐 |
| 2025-08-13 / 09-10 | `MAXCONV` 금지 → `NONE` 전환 | 옛 자동입찰 경로 폐기 |
| 2025-09-01 / 09-15 | 계정 마스터·customer-links 종료, ad-accounts·manager-accounts 신설 | 800명 계정 목록은 새 API로 |
| 2025-10-15 | 쇼핑 전환목표 자동입찰(Beta) `autobidStrategy` | 우리 엔진과 충돌 가능 |
| 2025-10-27 | 대량 보고서 전량 삭제·보관 14일·48시간 변경·CHANGED / stats 2시간 지연·`cycleBaseTm` 분 단위·`recentAvgRnk`·`recentAvgCpc` 0 고정·`pcNxAvgCpc`·`mblNxAvgCpc` 신설 | 수집·재수집 로직 |
| 2025-10-27 | 쇼핑 브랜드 상품별 보고서 집계 기준 변경(과거분까지 소급) | 과거 비교 깨짐 |
| 2025-10-19~ | 보고서 URL `fileVersion=v2` | 다운로더 |
| 2025-11-26 | 에누리 매체 ID 변경(클릭·전환은 최대 20일간 옛 코드로 들어올 수 있음) | 매체 매핑 |
| 2025-12-01 | stat-report Content-Type 형식 강제 | 호출 코드 |
| 2025-12-11 | 파워링크 키워드 `adRelevanceScore`·`expectedClickScore` | 파워링크 단계용 |
| 2026-03-30 | 보고서 COST 정수·VAT 포함 | 금액 단위 |
| 2026-03-30 / 05-13 | `purchaseCcnt`·`purchaseConvAmt`·`purchaseRor` | ROAS 계산에 새 칸 |
| 2026-06-10 | 기간 필드 KST 자정 검증(400) | 날짜 직렬화 |
| 2026-07-15 | `aiAdsOptIn`(ADVoost Max) — 파워링크+확장검색 전용, **값을 안 주면 true** | 파워링크 그룹 생성 시 반드시 명시 |
| 2026-07-29 | 파워링크 품질지수 4 고정 | QI를 판단 근거로 쓰면 안 됨 |
| 2026-09-16 | ADVoost 플레이스 — 켜면 입찰가·가중치·제외어·소재 변경 불가(3755 등) | 플레이스 단계 설계 |
| 2026-09-30 | 브랜드형 `topImpRto` 0 고정 | 상단 노출률 지표 소멸 |
| 2026-11-16 | 확장소재 보고서 8번 열 삭제 → 뒤 열이 한 칸씩 당겨짐 | 열 위치로 읽는 파서 |

---

## 9. 파워링크·플레이스 — 쇼핑과 다른 점만

- **파워링크**(`WEB_SITE`)
  - 키워드마다 입찰(`bidAmt`+`useGroupBidAmt`, 대량 200건)
  - `adRollingType` 적용(기본 `PERFORMANCE`)
  - 제외어 API 공식 지원(`EXP_SEARCH`/`KEYWORD_PLUS_RESTRICT`), `useExpSearch`·`expSearchBudgetRatio`
  - **`aiAdsOptIn` 기본 true**
  - Criterion 전 항목에 가중치 가능
  - `/estimate/performance`로 성과 예측 가능, `avgRnk` 제공, 보고서 `EXPKEYWORD`
  - 품질지수 4 고정(2026-07-29)
- **플레이스**(`PLACE` 캠페인, 그룹 `LOCAL_AD`)
  - 소재(`LOCAL_AD`)는 API로 등록 불가(`2021-06-21-release-note.md`)
  - 요일·지역 타겟팅만(가중치 불가), 성별·연령은 가중치 가능
  - `MEDIA_TARGET`으로 검색/콘텐츠, 네이버/파트너 선택(`2024-11-13`)
  - `adgroupAttrJson.useAdvoost=true`면 연동형 소재가 자동 생성되고 **입찰가·가중치·제외어·소재 변경이 막힘** → 자동 입찰 불가(`2026-09-16-release-note.md:8-9, 150-157`)
  - 추정 API `/npc-estimate`가 무엇 전용인지는 명세에 설명이 없음(2017-02 파워컨텐츠 도입 직후 추가돼 파워컨텐츠용으로 추정)

---

## 10. 명세 ↔ 공지 ↔ 기존 코드가 어긋나는 곳

1. 소재 입찰가 수정: 명세 `fields` = `userLock|inspect`(필수) ↔ ③ 코드는 `fields=adAttr`.
2. `adAttr`: 명세 `#hidden-response` ↔ ③ 코드는 GET 응답에서 읽음.
3. `/npla-estimate` type: 명세 `id|product` ↔ ③ `verify_phase0.py`는 `keyword`.
4. stats fields 목록에 `pcNxAvgCpc`·`mblNxAvgCpc`·`topImpRto`가 없음(공지에는 있음).
5. stat-report 상태 목록에 `CHANGED`가 없음(공지에는 있음).
6. 그룹 부분 수정 `fields` 목록에 `useAdvoost`가 없음(2026-09-16 공지에는 `?fields=useAdvoost`).
7. 제외 키워드 "웹사이트 전용" ↔ 2026-09-16 공지는 플레이스에서의 사용을 전제.
8. `autobidStrategy` 목록은 넓음 ↔ 공지상 실제로 쓸 수 있는 값은 고정.
9. 비즈채널 `channelTp` 목록에 쇼핑몰(MALL) 유형이 없음 ↔ 그룹 설명은 "MALL 유형 채널"을 요구([NCC] Adgroup.pcChannelId).

## 11. 개발 전 "읽기 1회"로 확정해야 할 것 (쓰기 없음)
- 쇼핑 그룹에서 `GET …/restricted-keywords`가 되는지(200인지 3728 오류인지)
- `GET /ncc/ads?nccAdgroupId=` 응답에 `adAttr`가 실제로 오는지, `SHOPPING_PRODUCT_AD`의 `ad`·`referenceKey` 모양
- `GET /ncc/adgroups/{id}` 응답의 `autobidStrategy` 모양
- `/npla-estimate/*/id`의 실제 응답 모양(단일 객체인지 배열인지)
- 소재 입찰가 변경이 `fields=adAttr`로 되는지 — 이것만은 쓰기라 **대표 승인 뒤 1건 변경·원복**으로 확인


[핵심 사실]
- (추정) 쇼핑 캠페인은 campaignTp=SHOPPING이고, 그 안의 광고그룹 유형은 SHOPPING(쇼핑몰 상품형)·CATALOG(제품 카탈로그형)·SHOPPING_BRAND(쇼핑 브랜드형) 세 가지다 — ncc-heroes-ncc.json 6469, 4752; _posts/2018-09-19-release-note.md; _posts/2021-03-17-release-note.md:10-14; 2019-12-18-release-note.md:9-11
- (확인) 쇼핑 소재 입찰은 Ad.adAttr {bidAmt, useGroupBidAmt}로 한다. useGroupBidAmt=true면 그룹의 bidAmt(70~100,000)가 적용된다 — ncc-heroes-ncc.json 3915-3918(adAttr '쇼핑 소재면 필수', 예시), 4779(Adgroup.bidAmt), 2687(키워드도 같은 쌍)
- (확인) 명세의 소재 수정 PUT /ncc/ads/{adId}는 fields가 필수이고 허용 값이 userLock·inspect뿐이다. 소재 입찰가(adAttr)를 바꾸는 호출 방식은 명세에 없다 — ncc-heroes-ncc.json 1190-1224; 기존 코드 metainc-content-studio/autobid/app/naverad.py:29-42는 fields=adAttr 사용(실증 기록 없음)
- (확인) 쇼핑몰 상품형·카탈로그형은 키워드를 추가할 수 없다. 키워드는 쇼핑 브랜드형만 가능(최소 300원) — _posts/2021-03-17-release-note.md:13-14; NaverSA_API_Error_Code_MAP.md 118(3923)
- (미확인) 제외 키워드 API는 명세 문구상 웹사이트 캠페인 전용이다. 쇼핑 그룹에서 되는지는 확인되지 않는다 — ncc-heroes-ncc.json 677-683, 737, 792; 반대 정황 _posts/2026-09-16-release-note.md:150-157(플레이스에서 사용)
- (확인) 쇼핑 검색어 성과는 /stats?statType=NPLA_SCH_KEYWORD(최근 30일, 노출 발생 검색어, 최대 1,000건)와 SHOPPINGKEYWORD_DETAIL/CONVERSION_DETAIL 보고서로 볼 수 있다 — ncc-report.json 441-464, 524; _posts/2016-10-17-release-note.md:13-16; 2017-09-27-release-note.md:16; 2018-02-21-release-note.md
- (확인) autobidStrategy는 전환 로그를 모으는 쇼핑몰 상품형 그룹 전용이다. 실제로 쓸 수 있는 값은 GRP·CPC·NO_CAP·0 고정, 목표는 NONE 또는 MAX_CONV_VALUE뿐이다 — _posts/2025-10-15-release-note.md:15-18, 35-42; ncc-heroes-ncc.json 4775, 5337-5406
- (확인) 네이버 자동입찰을 켜면 네이버가 그룹 기본입찰가·소재 노출 여부·실제 입찰가를 관리한다. 하루예산 필수 여부와 수동 입찰 차단 여부는 새 공지에 없다 — _posts/2025-10-15-release-note.md:15; 옛 MAXCONV 규칙 2019-12-18-release-note.md:12-13
- (확인) MAXCONV는 2025-08-13부터 설정 불가, 2025-09-10에 NONE으로 전환됐다. 현재 systemBiddingType은 NONE/ML — _posts/2025-07-30-notice1.md:16-20; ncc-heroes-ncc.json 4921
- (미확인) ADVoost 쇼핑은 명세에 정의(AdvoostShoppingMigration/Status)만 있고 호출 경로와 공지가 없다 — ncc-heroes-ncc.json 5182-5257; paths 목록에 없음
- (확인) 쇼핑 추정 API는 /npla-estimate/average-position-bid 와 /exposure-minimum-bid(type id|product, 최대 200건, position PC 1~10/모바일 1~5) 둘뿐이고, 쇼핑용 성과 예측은 없다 — estimate.json 251-340, 504, 521, 568; 성과 예측은 키워드용 164, 213
- (확인) /stats의 salesAmt는 광고비(VAT 포함)다. convAmt·ror·cpConv·crto는 응답 스키마에 설명이 없다 — ncc-report.json DailyStatMap(salesAmt 'Cost Summation(VAT included)'), fields 목록 약 240-256
- (확인) avgRnk는 파워링크 전용이라 쇼핑 순위가 아니다. 쇼핑 평균 순위는 검색어 보고서의 Sum of AD rank ÷ Impression으로만 구할 수 있다 — ncc-report.json DailyStatMap.avgRnk 설명; _posts/2018-02-21-release-note.md 15번 열
- (확인) stats breakdown(hh24 포함)은 한 번에 하나만, 요청 시점부터 과거 7일까지만 된다. ids에 다른 캠페인 유형을 섞으면 400/11003 — ncc-report.json 294-302; _posts/2017-11-08-release-note.md:14, 17-21
- (확인) 2025-10-27부터 stats 지연 2시간·cycleBaseTm 분 단위, 대량 보고서 보관 14일·최대 48시간 내 변경 시 CHANGED 상태로 재생성 필요 — _posts/2025-09-26-notice2.md:24-28, 34-36
- (확인) adRollingType은 WEB_SITE·POWER_CONTENTS에서만 유효하고, 캠페인 실험 API는 명세에 없다 — _posts/2018-07-18-release-note.md:8-10; ncc-heroes-ncc.json paths 전수
- (확인) 소재를 다른 광고그룹으로 복사하는 API(PUT /ncc/ads?ids&targetAdgroupId&userLock)가 있다 — ncc-heroes-ncc.json 1255-1316
- (확인) 쇼핑몰 상품형은 성별·연령 가중치(50~500)가 되고, 요일/시간은 타겟팅만 되며, 지역은 제외(negative=true)·가중치 100만 된다 — _posts/2022-04-26-release-note.md:72; 2023-08-23-release-note.md:62; 2023-10-18-release-note.md:7-8; ncc-heroes-ncc.json 2335
- (확인) 숫자로 된 호출 한도는 로컬 문서에 없다. 속도 제한은 호출 대상 계정마다 적용되고, 429가 대량으로 쌓이면 5분 이상 중단하라는 지침만 있다 — _posts/2020-12-18-notice.md:11, 29-36; NaverSA_API_Error_Code_MAP.md 15, 163
- (확인) 대량 수정은 키워드 PUT 200건·생성 100건·추정 200건만 있고, 소재·광고그룹은 한 건씩 PUT해야 한다 — ncc-heroes-ncc.json 2681-2687, 2897-2903, 1190, 549; estimate.json 504
- (확인) 대행사 계정은 /api/manager-accounts/{no}/child-ad-accounts(한 쪽 최대 1000, accountRole MASTER/READ_ONLY)로 하위 계정을 조회하고, 요청마다 X-Customer 헤더로 대상 계정을 지정한다. 옛 customer-links는 2025-09-15 종료 — atower.json 121, 170, 201, 673; python-sample/examples/ad_management_sample.py:11; _posts/2025-08-07-notice2.md
- (확인) ADVoost Max(aiAdsOptIn)는 파워링크+확장검색 전용이고, 값을 지정하지 않으면 true가 된다 — _posts/2026-07-15-release-note.md:9-10; ncc-heroes-ncc.json 4770
- (확인) topImpRto는 2026-09-30부터 브랜드형 키워드에 대해 0으로 고정된다 — _posts/2026-08-27-notice1.md:13-20

[위험]
- 소재 입찰가 변경 호출(fields=adAttr)이 명세에 없다. 기존 ③ 코드에 그대로 의존하면 1차 쇼핑 입찰 조정 전체가 실패할 수 있다 — 대표 승인 뒤 1건 변경·원복으로 실증해야 한다
- 명세는 adAttr를 응답에 안 나오는 칸(#hidden-response)으로 표시한다. GET 응답에 소재 입찰가가 없으면 현재가를 읽지 못해 상한 검사가 무너진다
- 네이버 자동입찰(isAutobidActive=true)이 켜진 그룹에서 우리 엔진도 입찰가를 바꾸면 서로 덮어쓴다(네이버가 소재 노출·입찰가를 관리 — 2025-10-15:15). 대상에서 반드시 빼야 한다
- 쇼핑 소재 입찰 변경은 대량 경로가 없어 소재 1건마다 GET+PUT이다. 광고주 800명 × 상품 수 × 주기로 호출량이 폭증해 429가 대량으로 쌓이면 5분 이상 전면 중단해야 한다(2020-12-18:36). 계정마다 속도 제한이라 계정 분산이 필요하다
- PUT /ncc/criterion/{ownerId}/{type}는 본문에 없는 코드를 모두 '사용 안 함'으로 바꾼다(2398). 가중치 A/B를 이 경로로 하면 기존 타겟팅이 사라질 수 있다 — 반드시 bidWeight 전용 경로를 쓴다
- ③ verify_phase0.py는 /npla-estimate/…/keyword로 부르는데 명세 type 목록은 id|product뿐이다. 추정값 수집 로직이 실패할 수 있다
- stats의 hh24는 과거 7일까지만 되고 ids에 캠페인 유형을 섞으면 11003 오류다. 시간대 A/B나 장기 분석을 stats로만 설계하면 깨진다 — 대량 보고서 Hours 열이 필요하다
- 대량 보고서는 최대 48시간 안에 값이 바뀌면 CHANGED 상태로 받을 수 없게 되고 14일 뒤 삭제된다. 재생성·중복 처리 없이 쌓으면 성과 데이터가 틀리거나 빈다
- salesAmt는 광고비인데 이름을 매출로 오해하면 ROAS가 뒤집힌다. convAmt·purchaseConvAmt 등 매출 칸은 응답 스키마에 설명이 없어 실측 확인이 필요하다
- 성별·연령·PC/모바일 가중치 조정을 대표 확정 '입찰가 조정(상한 있음)'에 넣을지는 판단이 필요하다. userLock 교대나 그룹 복사로 하는 A/B는 '켜고 끄기·새 그룹 = 승인' 범위와 겹친다
- 파워링크 단계에서 aiAdsOptIn을 빼먹으면 기본 true라 ADVoost Max가 켜진다. 플레이스에서 useAdvoost=true면 입찰가·가중치 변경이 3755로 막혀 자동 입찰이 불가능하다
- 2026-07-02 공지대로 계정 통합 뒤 일부 대행사 비밀키가 바뀌었다. 인증 실패를 일시 오류로 처리하면 조용히 멈춘다
- 2026-11-16부터 확장소재 보고서 열이 한 칸씩 당겨진다. 열 위치로 읽는 파서는 틀린 값을 읽는다

[미확인]
- 쇼핑 그룹에서 restricted-keywords(제외 키워드) API가 되는지. RESTRICT_KEYWORD_TARGET·NON_SEARCH_KEYWORD_TARGET 타겟 유형의 사용법
- SHOPPING_PRODUCT_AD를 만들 때 보내는 ad 내용의 형식, 그리고 referenceKey 등 실제 응답 칸
- 소재 입찰가(adAttr)를 수정하는 올바른 호출 방식(fields 값), 그리고 GET 응답에 adAttr가 실제로 오는지
- 쇼핑 상품 소재의 최소·최대 입찰가와 입찰 단위(명세에는 예시 50과 'unit: 10 KRW' 문구뿐)
- 새 쇼핑 자동입찰(2025-10-15)에서 하루예산이 필수인지, 켜면 수동 입찰(소재·그룹)이 막히는지
- ADVoost 쇼핑의 호출 경로와 공개 여부(정의만 있음)
- /npla-estimate 응답의 실제 모양(명세 스키마는 단일 객체, 2017 공지 예시는 items 배열)
- pcNetworkBidWeight·mobileNetworkBidWeight와 MEDIA_TARGET이 쇼핑 그룹에 적용되는지
- 같은 상품을 두 그룹에 둘 때 경매에서 어떻게 처리되는지, 오류 3822의 적용 범위
- SHOPPING_EXTRA가 '추가홍보문구'인지 여부, 쇼핑몰 상품형에 API로 붙일 수 있는 확장소재가 있는지
- 숫자로 된 호출 한도(초당·분당·동시성)와 /stats ids 최대 개수
- convAmt·ror·cpConv·crto의 정확한 정의(VAT 포함 여부, 직접/간접 전환 포함 범위)
- Criterion 유형 DV·CA의 의미와 쇼핑 적용 여부
- 2025-10-27 이후 대량 보고서가 통상 몇 시에 만들어지는지