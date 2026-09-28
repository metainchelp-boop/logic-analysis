# 공식 대행사 매니저 계정으로 광고주 800곳을 한 프로그램이 운영할 때 — API 인증·권한·규모 사실 정리

> 범위: 읽기 전용 조사. 파일 수정·커밋·배포는 하지 않았고, 네이버 API·서버도 호출하지 않았다. 비밀값은 이름만 적었다.
> 근거 표기: `파일:줄`, 또는 `명세파일 › 경로/정의.필드`. 명세·코드에서 확인하지 못한 것은 **미확인**으로 적었다.
> 명세 사본 위치 약칭: `SA/` = `/tmp/claude-0/-home-user/2324b47f-529e-5437-a1d6-c6b0a1ae585e/scratchpad/sa-pages/`, `DOC/` = 같은 scratchpad 의 `searchad-apidoc/`.

---

## 0. 결론 요약

1. **매니저 계정 API(atower)는 4개이고 모두 GET, 즉 조회 전용이다.** 핵심은 `GET /manager-accounts/{managerAccountNo}/child-ad-accounts`이다. 한 번 호출로 관리 가능한 하위 광고계정(최대 1000개/쪽)의 `customerId`(= X-Customer 값)와 `accountRole`(MASTER=운영관리 / READ_ONLY=운영조회)을 돌려준다. 800곳은 한 쪽에 다 들어간다.
2. **인증은 광고주별이 아니라 "라이선스 + 비밀키 서명 + `X-Customer`로 대상 계정 지정" 구조다(확정).** 공식 가이드는 `X-Customer`를 "조회할 광고주ID"라고 적는다. 그래서 **매니저 라이선스 1벌로 하위 광고주 customerId를 넣어 호출하는 모델이 설계상 의도된 것으로 보인다(강한 추정).** 하지만 "매니저 라이선스로 하위 계정 ncc에 쓰기까지 된다"는 문장은 명세 어디에도 없다. 네이버도 "대행사 Agent 관리 방식은 추후 가이드"라고만 적었다(**미확인 — 하위 계정 1곳에서 실증이 필요하다**).
3. **지금 우리 저장소 세 곳(① 전산, ③ 광고센터, ③ 자동입찰)은 모두 "광고주마다 라이선스·비밀키·고객ID 3종을 받아 따로 저장"하는 방식이다.** 비밀값이 두 서버에 세 벌로 흩어져 있다. ③이 ① 자격을 가져다 쓰는 길은 **없다**(ad-sync 계약에 자격 필드 없음).
4. **호출 한도 수치(초당·일일·동시)는 공개 문서에 없다.** 문서에 있는 것은 네 가지다. 한도가 "호출 대상 계정당 속도 제한"이라는 것, 키워드도구는 IP도 한도 단위에 들어간다는 것, 429·1016 오류, 요청당 건수 상한(키워드 수정 200, 생성 100 등)이다. /stats 데이터는 **약 2시간 늦게** 나온다(2025-10-27 변경 공지).
5. **권고.** 매니저 방식이 실증되면 비밀값을 ③ 서버에 **1벌만** 두고, 광고주별로는 `customerId`와 권한만 저장한다. 계정 목록은 네이버 child-ad-accounts를 매일 동기화하고, 운영 대상 여부는 ① 계약 단계(ad-sync)와 교차해 정한다. 작업은 대기열 1개에서 **계정별 1작업씩 순번 처리**하고, 전역 동시 수를 제한하고, 800곳을 60분에 고르게 펼친다.

---

## 1. atower.json — 매니저(관리) 계정 API

### 1-1. 경로 전부

- 명세상 경로는 `/api/...`로 적혀 있다. 하지만 문서 사이트 설정이 `^/api`를 떼고 보여주고(`SA/app/config.js:44` `uriReplace`), 릴리스 노트도 `/ad-accounts`·`/manager-accounts`로 적는다(`SA/_posts/2025-08-12-release-note1.md`). **실제 호출 경로는 `https://api.searchad.naver.com/manager-accounts` 형태**다(서비스 URL은 `SA/assets/i18n/markdown-ko-KR.json › #/guides`).

| # | 메서드·경로 | 파라미터 | 응답 | 설명(명세 원문 요지) |
|---|---|---|---|---|
| 1 | `GET /ad-accounts` | `page`(query, int32, 선택), `size`(query, 선택, **최대 1000**) | `AdAccountsResponse`(쪽 나눔) | 자신이 구성원으로 포함된 광고계정 목록 |
| 2 | `GET /ad-accounts/{adAccountNo}/members` | `adAccountNo`(path, int64, 필수) | `AdAccountMember[]`(배열, 쪽 나눔 없음) | 자신이 권한을 가진 특정 광고계정의 구성원 목록 |
| 3 | `GET /manager-accounts` | `page`, `size`(최대 1000) | `ManagerAccountsResponse`(쪽 나눔) | 자신이 구성원으로 포함된 관리계정 목록 |
| 4 | `GET /manager-accounts/{managerAccountNo}/child-ad-accounts` | `managerAccountNo`(path, int32 — 명세상 `required:false`로 적힌 오기), `page`, `size`(최대 1000) | `ChildAdAccountResponse`(쪽 나눔) | 지정 관리계정의 **하위 광고계정(관리 가능한 광고계정)** 목록 |

근거: `SA/assets/json/atower.json › paths` 4개(operationId `getAdAccountsUsingGET`·`getAdAccountMembersUsingGET`·`getManagerAccountsUsingGET`·`getChildAdAccountsUsingGET`). 네 경로 모두 오류 응답은 401·403·404이다.

### 1-2. 응답 필드 전부 (atower.json › definitions)

- **ManagerAccount**(#3 content 요소): `managerAccountNo`(관리계정 번호) · `managerAccount`(→ManagerAccountDetail) · `naverId`(계정책임자 네이버 ID) · `roleName`(OWNER/MASTER/READ_ONLY = 계정책임자/운영관리/운영조회) · `createdAt`(권한 받은 시각) · `lastAccessTime` · `favorite`
- **ManagerAccountDetail**: `no` · `name` · `childAdAccountCount`(하위 광고계정 수, nullable) · `country` · `currency` · `timezone` · `timezoneId` · `createdAt` · `updatedAt` · `deleted` · `deletedAt` · `disabled`
- **ChildAdAccount**(#4 content 요소, ★동기화 원천): `adAccountNo`(광고계정 번호) · `adAccountName` · **`customerId`(SA 계정 ID = X-Customer에 넣을 값)** · **`accountRole`(MASTER=운영관리 / READ_ONLY=운영조회)** · `ownerNaverId`(계정책임자 네이버 ID — 개인 식별값)
- **AdAccount**(#1 content 요소): `adAccountNo` · `adAccount`(→AdAccountDetail) · `naverId` · `roleName`(OWNER/MASTER/READ_ONLY) · `createdAt` · `lastAccessTime` · `favorite`
- **AdAccountDetail**: `no` · `name` · **`masterCustomerId`(SA 계정 ID)** · `country` · `currency` · `timezone` · `timezoneId` · `createdAt` · `updatedAt` · `deleted` · `deletedAt` · `disabled` · `penalty.penalized`(이용정지)
- **AdAccountMember**(#2): `adAccountNo` · `naverId` · `roleName`(OWNER/MASTER/READ_ONLY) · `createdAt`
- **쪽 나눔 공통**(AdAccountsResponse·ManagerAccountsResponse·ChildAdAccountResponse): `content[]` · `empty` · `first` · `last` · `number` · `numberOfElements` · `size` · `totalElements` · `totalPages` · `pageable{offset,pageNumber,pageSize,paged,unpaged,sort}` · `sort{empty,sorted,unsorted}`
- ⚠️ definitions에는 경로가 없는 스키마(`ApiCredentials`·`OauthAccessToken`·`ManagedCustomerLink`·`Customer` 등)가 잔뜩 남아 있다. 문서 사이트 설정이 `customerlinks`·`apimyclientscontroller`·`apilicenses`·`apikeys`·`managercandidates`·`auth` 태그를 숨긴다(`SA/app/config.js:32`). **호출 가능한 API가 아니다.** 라이선스 발급·관리계정 초대 같은 쓰기 API는 공개돼 있지 않다.

### 1-3. 권한 수준

- **atower API 자체는 조회 전용이다.** 4개 모두 GET이고, 링크 생성·초대·권한 변경 경로는 없다.
- 권한 체계는 응답 필드로만 드러난다. 광고계정 구성원 역할은 OWNER(계정책임자)/MASTER(운영관리)/READ_ONLY(운영조회)이고, **관리계정에서 하위 계정에 대한 접근 역할은 MASTER 또는 READ_ONLY**이다(`definitions.ChildAdAccount.accountRole`). 이름상 MASTER는 운영(쓰기), READ_ONLY는 조회만 가능한 역할로 읽힌다. **그 역할이 ncc 쓰기 API에서 실제로 어떻게 집행되는지는 명세에 없다(미확인).**

### 1-4. 배경(왜 이 API인가)

- 옛 방식인 `GET /customer-links?type=MYCLIENTS`(ManagedCustomerLink)는 **2025-09-01 데이터 갱신 중단, 2025-09-15 사용 종료**다(`SA/_posts/2025-08-07-notice2.md`). 공식 파이썬 샘플은 아직 이 옛 경로를 쓰고 있다(`DOC/python-sample/examples/ad_management_sample.py:19-23`). **따라 쓰면 안 된다.**
- 계정 권한 정보를 담던 Account Master 리포트도 2025-09-15에 종료됐고 "신규 API로만 확인 가능"하다(`SA/_posts/2025-08-07-notice1.md`).
- 새 API는 2025-09-01 플랫폼 개편 이후 사용 가능하다. 공지에는 "응답 필드는 추후 변경될 수 있음", "대행사 Agent 관리 방식 및 기존 영업권 관리계정 체계 전환 방식은 추후 가이드·설명회 예정"이라고 적혀 있다(`SA/_posts/2025-08-12-release-note1.md`).
- 명세의 host는 `localhost:10065`이고 securityDefinitions가 없다. 경로별 헤더가 명시되지 않았다는 뜻이다. **atower 호출 때 `X-Customer`에 무엇을 넣는지(매니저 자신의 customerId로 추정)는 미확인이다.**

---

## 2. 인증 구조

### 2-1. 확정되는 것

- **발급**: 광고주센터 → 광고 시스템 → 도구 › API 사용 관리에서 "라이선스(API-KEY)"와 "비밀키(API_SECRET)"를 발급한다(`SA/assets/i18n/markdown-ko-KR.json › #/guides, #/samples`, `DOC/README.md:14-19`).
- **서명**: `base64( HMAC-SHA256( API_SECRET, "{밀리초 타임스탬프}.{HTTP메서드}.{요청 URI}" ) )`(`markdown-ko-KR.json › #/samples`, `DOC/python-sample/examples/signaturehelper.py:9-14`). 서명 URI에는 **경로만** 넣고 쿼리는 넣지 않는다. 우리 코드 세 곳이 같게 구현돼 있다: ③ `backend/app/adapters/naver_searchad.py:22-36`·주석 `:277-279`, ① `NaverSearchAdClient.java:234-260`, 자동입찰 `autobid/naverad_client.py:36-50`.
- **헤더 4종**: `X-Timestamp`, `X-API-KEY`(라이선스), **`X-Customer`("조회할 광고주ID")**, `X-Signature`(`markdown-ko-KR.json › #/samples › 호출`).
- 운영 망 `https://api.searchad.naver.com`. 샌드박스(`sandbox-api...`)는 2022년 한시 운영 기록만 있고 지표·보고서는 제공하지 않았다(`SA/_posts/2022-04-01-notice1.md`).

### 2-2. 매니저 라이선스 1벌로 하위 광고주 customerId를 넣어 ncc 쓰기까지 되는가

**정황 근거(모두 간접)**
1. 라이선스(`X-API-KEY`)와 대상 계정(`X-Customer`)이 **별개 헤더**다. 가이드도 X-Customer를 "조회할 광고주ID"라고 적는다. 라이선스 소유자와 대상 계정이 다를 수 있는 구조다(`markdown-ko-KR.json › #/samples`).
2. 공식 샘플의 옛 흐름이 "같은 헤더로 `/customer-links?type=MYCLIENTS` → 내 광고주 목록"이었다(`ad_management_sample.py:19-23`). 대행사가 자기 라이선스로 광고주 목록을 받고 각 광고주를 호출하는 전형적인 형태다.
3. atower `/ad-accounts`·`/manager-accounts`는 "**자신이** 구성원으로 포함된" 계정 목록이다. 라이선스가 곧 "구성원(네이버 ID)"을 식별한다는 뜻으로 읽힌다(`atower.json › paths`).
4. 오류표에 `1006 권한이 없습니다. 계정 권한을 다시 확인하세요`, `1018 접근 권한이 없습니다`, **`5002 충전기능은 본인의 계정에서만 사용 가능합니다`**가 있다(`DOC/NaverSA_API_Error_Code_MAP.md:16-17, 157`). "본인 계정이 아닌 계정을 호출하는 경우"가 시스템에 존재하고, 권한으로 거르며, 충전만 명시적으로 막는다는 정황이다.
5. `ChildAdAccount.accountRole = MASTER(운영관리)`가 있다.
6. 2026-07-02 공지: "구 검색광고의 **Agent**에 대한 탈퇴 처리 과정에서 일부 **Agent의 API 비밀키 변경** … 영업권 관련 오류는 없음"(`SA/_posts/2026-07-02-notice.md`). 대행사(Agent)가 자기 API 키를 갖고 영업권으로 광고주에 연결되는 구조가 실재한다.

**판정**
- **확정**: 라이선스 + 비밀키 + X-Customer 구조. 광고주 본인 라이선스로 그 광고주를 읽고 쓰는 방식은 실제로 동작한다. 우리 자동입찰 관문이 실계정에서 그룹 입찰가 +10원 → 원복 쓰기를 검증하는 코드를 갖고 있다(`autobid/app/gate.py:48-66`). ③ 화면 안내문도 "광고주 본 계정 **또는 위임받은 대행 계정**이 필요합니다"라고 적는다(`backend/static/index.html:658`).
- **강한 추정**: 매니저(관리계정 구성원) 라이선스로 `X-Customer=하위 customerId`를 넣으면 **읽기**가 된다.
- **추정(조건부)**: `accountRole=MASTER`인 하위 계정만 **쓰기**(입찰가·on/off 등)가 되고, READ_ONLY는 1006/1018로 거절될 것이다.
- **미확인**: 위 두 가지를 명문으로 보장하는 문장이 명세에 없다. 라이선스가 네이버 ID(구성원) 단위인지 광고계정 단위인지도 명문이 없다. 비즈머니·보고서(stat-report/master-report)가 매니저 라이선스로 하위 계정에 대해 되는지도 없다.
- ⇒ **설계 확정 전에 실증 1건이 필요하다.** 순서: MASTER 하위 계정 1곳 → ① `GET /ncc/campaigns` → ② 그룹 1개 `bidAmt` +10원 → 확인 → 원복(자동입찰 관문과 같은 절차) → ③ READ_ONLY 계정 1곳에서 같은 쓰기가 거절되는지 → ④ `GET /billing/bizmoney`·`POST /stat-reports` 가부.

---

## 3. 자격 저장 비교 — ① 전산 vs ③ 광고센터 (+ ③ 자동입찰)

| 항목 | ① 전산 BE | ③ 광고센터 | ③ 자동입찰(content-studio/autobid) |
|---|---|---|---|
| 저장 위치 | 표 `advertiser_platform_credential`(업체×매체 1행, 유일키 `company_idx, platform_idx`) — `schema.sql:4526-4539`, `AdvertiserPlatformCredential.java:31-32` | 표 `channel_credentials`(client_id, channel, mode, status, `fields_json`) — `backend/app/models.py:157-166` | 표 `ab_account`(customer_id 유일) — `autobid/app/models.py:14-35` |
| 네이버 필드 | `api_key_enc`·`api_secret_enc`(암호화)·`api_customer_id`(평문) — **BLOCK 161** `schema.sql:5039-5050`, `…Credential.java:69-76` | `customer_id`·`api_license`·`secret_key`(필드마다 암호화) — `routers/clients.py:1165-1172, 1931-1933` | `customer_id`·`api_key_enc`·`secret_key_enc` — `models.py:19-21` |
| 암호화 | jasypt `StringEncryptor`(빈 `jasyptStringEncryptor`, 마스터키 설정명 `jasypt.encryptor.password`) — `application.yml:56-59`, `JasyptConfig.java:18` | Fernet, 키 파일 `secret.key`(설정명 `FERNET_KEY_FILE`) — `security.py:40-49` | Fernet(설정명 `AUTOBID_ENC_KEY`) — `autobid/README.md` 구조표 |
| DB | MariaDB | **SQLite**(`database.py:9-13`) + gunicorn 워커 4(`Dockerfile:18-19`) | SQLite 추정(미확인) |
| 입력 경로 | 광고주 관리 `PATCH /api/ad-setup/credentials`(관리부서·대표, 본인 담당 범위) — `AdSetupController.java:187-191`, `AdSetupService.java:892`; 광고주 사전조사 폼 — `MarketingSurveyNaverCredentialService.java:37-51` | 직원 입력 + **광고주 자가 입력 링크**(`CONNECT_CHANNEL_META`) — `clients.py:1929-1933`. mode는 `delegated`로 저장되지만 필드 3종은 똑같이 받는다 — `static/app.js:184` | 관제 화면 직접 등록 — `app/web.py:90-93` |
| 해석기 | `AdCredentialResolver` — 가망 idx ↔ 광고주 clientId를 `Client.legacyLeadId`로 변환. `ad_platform.integration_vendor=NAVER_SEARCHAD`(BLOCK 205, `schema.sql:6301-6310`)인 매체만 대상. 3종이 다 차야 사용 — `AdCredentialResolver.java:43-116`, `AdApiCredential.java:19-33` | 없음(행마다 직접 복호화) | `client_for(account)` — `app/naver_ad.py:12-17` |
| 연결 시험 | `POST /api/ad-setup/credentials/test` → `GET /ncc/campaigns` 1회 — `AdSetupController.java:193-199`, `AdSetupService.java:862-888`, `NaverSearchAdClient.java:115-130` | `/clients/{id}/channels/{ch}/test` → `fetch_performance`(캠페인 + stats) — `clients.py:1165-1180` | 관문: 읽기 + 그룹 입찰 +10원→원복 — `gate.py:15-66` |
| 쓰는 곳 | 매일 05:05 최근 30일 합계 수집(캠페인 목록 + /stats, 계정당 2회) — `AdMetricCollectScheduler.java:32-37`, `AdMetricCollector.java:61-109`, `NaverSearchAdClient.java:157-189` | 매일 06:00 순차 수집(계정 사이 1.5초) — `collector.py:16-25, 95-113`; 쓰기(키워드 입찰·on/off·그룹예산·키워드 추가·캠페인 생성) — `naver_searchad.py:98-235, 357-405` | 10분 주기 쇼핑 소재 입찰 — `config.py:12`, `naver_ad.py:29-42` |
| 전역 자격 경로 | `naver.ad.*` env(기본 꺼짐, 회사 1벌) — `NaverSearchAdClient.java:45-62` | 없음 | `AUTOBID_API_KEY/SECRET_KEY/CUSTOMER_ID`(0단계 실증용) — `verify_phase0.py:58-68` |

**③이 ① 자격을 가져다 쓰는 길**
- **지금은 없다.** ③가 ①에서 받는 것은 `GET /api/ad-sync/contracts`뿐이다(`erp_sync.py:120-157`, 설정명 `ERP_SYNC_URL`·`ERP_SYNC_API_KEY`). 응답 필드는 `possibility_id`·`company_name`·`store_url`·`sales_manager`·`stage`·`ad_center_registered`·`contracts[round,product,start_date,end_date,amount,type]`로, **자격 필드가 없다**(① `AdSyncDto.java:20-26, 54-60`, ③ `ERP_CONTRACT_SYNC_API.md:59-100`). 반대 방향으로는 ① → 자동입찰 bid-status 조회가 있을 뿐이다(`autobid/app/web.py:558-561`).
- ① 호스트 `api.metainc.co.kr`은 **HTTP**이고 HTTPS 전환은 "안 함"으로 결정돼 있다(FE CLAUDE.md "전산 HTTPS 전환 — 안 함"). **비밀키를 ① → ③로 네트워크 전송하는 설계는 피해야 한다.**
- **매니저 방식이면 넘길 필요가 있는 값은 비밀이 아닌 `customerId`뿐이다.** ①은 `api_customer_id`를 평문 식별값으로 취급한다(`…Credential.java:66-67`). ad-sync 응답에 예를 들어 `naver_customer_id`를 **덧붙이는 방식(additive)**이면 비밀 전송 없이 연결할 수 있다. 다만 ad-sync는 ③↔① 외부 계약이라 ①에 사전 통지·합의가 필요하다. ①의 `HandoverSheetComparisonService.java:410-413`도 이미 customerId를 읽고 있다.

**800곳 자격을 어디서 한 번에 관리할지**
- 광고주별 3종 방식을 유지하면 800곳 × (라이선스·비밀키 수령) × 세 저장소가 된다. 수령·갱신·불일치 관리가 현실적이지 않다. 2026-07-02처럼 네이버 쪽에서 키가 바뀌면 세 곳을 다 고쳐야 한다.
- 매니저 방식이면 **비밀값 1벌(매니저 라이선스·비밀키)은 ③ 서버 비밀값(env/파일)에만** 둔다. 광고주별 행에는 `customerId`·`accountRole`·`adAccountNo`·매칭 정보만 둔다. **계정 목록의 원천은 네이버 child-ad-accounts**, 계약·운영 단계의 원천은 ① ad-sync로 역할을 가른다.
- ①의 기존 3종 입력칸과 데이터는 **매니저 하위에 없는 계정의 예비 경로**로 남긴다(무회귀).

---

## 4. 호출 한도·규모

### 4-1. 문서에 적힌 한도·제약(전부)

| 내용 | 근거 |
|---|---|
| 사용량 제한은 "**호출 대상 계정당 속도 제한**"이고 전체 사용량에 따라 유연하게 운영된다. **수치는 비공개** | `SA/_posts/2020-12-18-notice.md:11` |
| 별도로 공격 방지 **내부 보안 장치**가 존재한다(2020-09-10 강화) | 같은 공지 :13 |
| 키워드도구(`/keywordstool`)는 다른 기능 대비 속도 1/5~1/6이고, **IP도 측정 단위**에 들어간다(IP당 약 1/2). 여러 customerId를 동시에 부를 때는 장비·네트워크를 분리하라고 권고하며, 대량 429가 나면 **5분 이상 전면 중단**하라고 한다. (공지는 "키워드 도구에 한정"이라고 명시) | 같은 공지 :27-36 |
| 오류 `429 요청이 많아 처리할 수 없습니다`, `1016 너무 많은 접속`, `1014 최대 허용개수 초과`, `503 정기점검` | `DOC/NaverSA_API_Error_Code_MAP.md:13-14, 162-163` |
| 키워드 일괄 수정 `PUT /ncc/keywords?fields=bidAmt…` **요청당 200개**, 키워드 생성 **100개** | `ncc-heroes-ncc.json › PUT /api/ncc/keywords{?fields}`, `POST /api/ncc/keywords{?nccAdgroupId}` description |
| 쇼핑 소재 수정 `PUT /ncc/ads/{adId}`는 **단건만**. fields 열거값은 `userLock`,`inspect`뿐이고 `adAttr`는 "쇼핑 광고면 수정 시 필수" | `ncc-heroes-ncc.json › PUT /api/ncc/ads/{adId}{?fields}`, `definitions.Ad.adAttr` |
| 예상 입찰가(estimate) 키/키워드 **200개**, 입찰가 배열 **100개** | `estimate.json › definitions` |
| 목록 `recordSize` 1~1000(캠페인 영문 설명은 1~2000으로 불일치) | `ncc-heroes-ncc.json › GET campaigns/adgroups/keywords` |
| atower `size` 최대 1000 | `atower.json › parameters.size` |
| master-report 목록 최근 100건 | `master-report.json › GET /master-reports` |
| `/stats` `ids`는 **같은 캠페인 유형**끼리만 묶을 수 있다(섞으면 400/11003). breakdown은 1개만. 시간대·요일·기기 상세는 과거 7일(브랜드검색 90일) | `SA/_posts/2017-10-17-notice.md`, `ncc-report.json › /stats breakdown` |
| **/stats 지연 3시간 → 2시간**(2025-10-27~). `cycleBaseTm`(사용 가능한 최신 시각)이 분 단위로 갱신 | `SA/_posts/2025-09-26-notice2.md` |
| stat-report는 **D+1** 다운로드(예: 1월 11일자는 1월 12일부터), 보관 **14일**, 지표는 최대 **48시간 내 수정**될 수 있고 수정되면 기존 리포트 상태가 `changed` | `SA/_posts/2018-01-12-notice.md`, `2025-09-26-notice2.md` |
| master-report `fromTime` = 그 시각 이후 **변경분(Delta)**만 생성 | `master-report.json › POST /master-reports` |

- **초당·일일·동시 호출 수치는 어디에도 없다(미확인).** `/stats` `ids` 최대 개수도 명세에 없다. ③는 스스로 50개로 자른다(`naver_searchad.py:443-444`).

### 4-2. 800 광고주 × 1시간 주기 호출 수 추정

**가정(실측 아님)**
- A1: 광고주 800곳, 1차는 쇼핑만, 24시간 운영(최악 기준. 자동입찰은 8~24시 운영 — `autobid/app/config.py:15-16`).
- A2: 광고주당 평균 쇼핑 캠페인 2 · 광고그룹 10 · 상품 소재 50(자리표시값 — **실측 필요**).
- A3: `/stats` 한 번에 id 50개(③ 코드 값. 공식 최대 미확인).
- A4: 입찰 대상 광고주당 5개(자동입찰 확정 스펙 "1,000계정 × 평균 키워드 5개" — `autobid/README.md` 확정 스펙표).
- A5: 쇼핑 소재 입찰 1건 = GET + PUT 2회(`autobid/app/naver_ad.py:35-42`).

| 항목 | 방식 A: 매시간 구조를 다시 훑기(③ `collect_keyword_performance` 형태, `naver_searchad.py:408-472`) | 방식 B: 구조는 하루 1회 master-report 변경분, 매시간은 통계만 |
|---|---|---|
| 통계 읽기(계정·시간당) | 캠페인 1 + 그룹목록 2 + 소재목록 10 + stats 2 = **15** | stats 2(그룹·소재) = **2** |
| 통계 읽기(전체) | 12,000/시간(평균 3.3건/초) · 288,000/일 | 1,600/시간(0.44건/초) · 38,400/일 |
| 구조 동기화 | (위에 포함) | master-report 4종 × (생성 1 + 상태조회 2 + 다운로드 1) = 계정당 16/일 → **12,800/일** |
| 입찰 쓰기 | 대상 4,000 · 매시간 전부 변경 시 8,000/시간(최악) | 25% 변경 가정 시 2,000/시간 |
| 비즈머니 | 800/시간 | 3시간마다면 약 270/시간 |
| 전일 대량 보고서 | — | stat-report 3종(AD_DETAIL·AD_CONVERSION_DETAIL·SHOPPINGKEYWORD_DETAIL) × 4회 = 9,600/일(48시간 수정 반영해 D-2 재생성까지 하면 19,200/일) |
| **합계** | **약 20,800/시간 ≈ 5.8건/초 ≈ 50만/일** | **약 4,400/시간 ≈ 1.2건/초 + 일 배치 2.2만~3.2만 ≈ 13만/일** |
| 계정당 시간당 | 약 26회 | 약 5~6회 |

- 한도가 문서대로 "대상 계정당"이라면 계정당 시간당 5~26회로는 걸릴 가능성이 낮다(**수치 미공개라 추정**). 실제 위험은 **한 IP에서 몰아 부를 때의 보안 장치**(키워드도구 외 기능에서 IP가 한도 단위인지는 미확인)와 순간 폭주다.
- 같은 광고주 계정을 **① 05:05 수집(계정당 2회) · ③ 06:00 수집 · 자동입찰 10분 주기**가 함께 부른다. 계정당 예산을 나눠 쓴다.
- **대량 보고서로 줄이는 방법**
  - 구조(캠페인·그룹·소재·입찰가·예산) = master-report `fromTime` 변경분(하루 1회, 또는 쓰기 직후만 재조회).
  - 검색어·시간대·지역 상세 = stat-report(전일분, D+1).
  - 시간 단위 판단 = `/stats`(그룹·소재 id 묶음, 같은 유형만).
  - 2단계 파워링크 = `PUT /ncc/keywords?fields=bidAmt` 200개 일괄. 지금 ③ `set_keyword_bid`는 키워드 1건씩 PUT이다(`naver_searchad.py:357-363`). 1차 쇼핑은 소재 단건 PUT밖에 없어서 줄일 수 없다.
- **1시간 주기의 뜻**: /stats는 약 2시간 늦다. 매시간 판단은 "2시간 전까지의 누적"을 보는 것이다. 응답 `cycleBaseTm`을 저장해 이중 집계를 막아야 한다. 48시간 안에 지표가 수정될 수 있으므로 A/B 판정은 최소 하루 이상 창과 D-2 재확인으로 해야 한다.

### 4-3. 공유 서버 자원 한계

- ③ 광고센터·② 로직분석·자동입찰 3컨테이너·스튜디오가 한 서버에 있다. `docker ps` 6개: autobid_engine/watchdog/web, logic-analysis, content-studio, ad-api(② CLAUDE.md 2026-08-31 기록).
- 메모리 **3.9GB 중 가용 약 2.7GB**(② 기록 2026-09-14). 디스크 **36G 중 21G(63%)**, ② DB 3.1GB(② 기록 2026-08-30). ① BE는 위 목록에 없으므로 **다른 호스트(1.234.23.117)로 추정**된다.
- ③는 **SQLite + gunicorn 워커 4**이다(`database.py:9-13`, `Dockerfile:18-19`). 수집 스케줄러는 파일 잠금으로 워커 1개만 돈다(`collector.py:154-170`). 현재 수집은 계정 사이 1.5초 **순차**라서 800곳이면 대기만 20분이다(`collector.py:17, 113`). 매시간 쓰기 루프에는 맞지 않는다.
- 시간별 스냅샷을 그대로 쌓으면 800 × (그룹 10 + 소재 50) × 24 ≈ **하루 115만 행**이 된다(A2 가정). 보관 정책(시간 단위 N일, 이후 일 단위)과 SQLite 단일 쓰기 한계를 고려해야 한다. `database.py` 주석대로 PostgreSQL 교체도 검토 대상이다.
- ② 로직분석이 같은 서버 IP에서 자기 라이선스로 **`/keywordstool`을 호출**한다(`logic-analysis/backend/naver_crawler.py:28-30, 786-799`). 키워드도구는 IP도 한도 단위이므로(2020-12-18 공지), ③ 에이전트가 키워드 발굴에 키워드도구를 쓰면 ②와 IP 예산을 나눠 쓴다. ②에 통지하고 상한을 합의해야 한다.

---

## 5. 비즈머니(billing) 잔액 조회 경로

| 경로 | 파라미터 | 응답 필드 |
|---|---|---|
| `GET /billing/bizmoney` | 없음 | `bizmoney`(잔액) · `budgetLock` · `refundLock` · `customerId` |
| `GET /billing/bizmoney/histories/charge` | `searchStartDt`,`searchEndDt`(KST YYYYMMDD, 필수) | 충전: `displayCd`·`displayName`·`newRefundableAmt`·`newNonRefundableAmt`·`statDt` |
| `GET /billing/bizmoney/histories/exhaust` | 같음 | 차감: `activityCd`·`campaignTp`(1 파워링크, 2 쇼핑 …)·`prodInfoCd`·`useRefundableAmt`·`useNonrefundableAmt`·`settleDt`·`customerId` |
| `GET /billing/bizmoney/histories/period` | 같음 | 일별 상태: 잔액·충전·사용·환불 금액들·`settleDt`·`customerId` |

근거: `ncc-heroes-billing.json › paths, definitions`. 비즈머니 사용조회(`/billing/bizmoney/cost`)는 **2025-08-06 종료**됐고 나머지 4개는 유지된다(`SA/_posts/2025-06-26-notice.md`). 광고비는 `/stats`의 `salesAmt`나 stat-report 비용 항목으로 본다. 충전 API는 공개 명세에 없고, 오류 5002는 "충전은 본인 계정만"이다. **매니저 라이선스로 하위 계정 잔액을 조회할 수 있는지는 미확인**(2장 실증 ④). 잔액 부족 알림 API는 없으므로 주기적으로 조회해야 한다.

---

## 6. 권고 — 인증 구조 · 계정 목록 동기화 · 작업 분산

### 6-1. 인증 구조
1. **먼저 실증한다**(2-2의 ①~④). 결과에 따라 갈린다.
   - **성공** → 매니저 라이선스·비밀키 **1벌만** ③ 서버 비밀값으로 둔다(설정명 예: `NAVER_MANAGER_API_KEY`/`…_SECRET`/`…_CUSTOMER_ID` — 값은 저장소·로그·화면에 절대 두지 않는다). 광고주별로는 `customerId`만 쓴다.
   - **실패(쓰기 불가)** → 조회만 매니저, 쓰기는 광고주별 3종 예비 경로로 간다.
2. 비밀값 1벌이 새면 **800곳 전체가 노출**된다. 저장은 파일 권한과 암호화로, 호출 모듈 1곳만 복호화하고, 오류 메시지·로그에 싣지 않는다(① `AdApiCredential.toString` 마스킹 선례 `AdApiCredential.java:29-33`). 키 교체 절차와 401/비밀키 변경 응답 감지(2026-07-02 사례) → 전 계정 쓰기 즉시 중지 + 알림을 둔다.
3. ①의 광고주별 3종 저장은 **삭제하지 않고 예비 경로로 유지**한다(무회귀). 매니저 하위에 없는 계정이나 READ_ONLY 계정만 그 경로를 쓴다.
4. ① → ③로는 **비밀키를 넘기지 않는다**(HTTP). 넘길 필요가 있으면 ad-sync에 `naver_customer_id` 같은 비밀 아닌 필드를 덧붙인다(계약 변경 → ① 사전 통지).

### 6-2. 계정 목록 동기화(매일 1회 + 수동)
1. `GET /manager-accounts` → 관리계정 전부. 여러 개일 수 있다(영업권 관리계정 체계 전환 방식 미공개).
2. 관리계정마다 `child-ad-accounts?size=1000`로 모든 쪽을 받는다.
3. 표 예시 `naver_account`: `customerId`(키) · `adAccountNo` · `adAccountName` · `accountRole` · `managerAccountNo` · `last_seen_at` · `disabled/deleted/penalized`(필요하면 `/ad-accounts`로 보강). `ownerNaverId`는 개인 식별값이므로 저장을 최소화하고 화면 노출을 제한한다.
4. 광고주 매칭:
   - 1순위: ① `api_customer_id`와 같은 customerId(ad-sync 확장 시).
   - 2순위: ③ `ChannelCredential.fields.customer_id` 기존 값.
   - 3순위: 이름 유사 → **사람 확인 대기**(자동 확정 금지).
5. 운영 대상 판정 = `accountRole=MASTER` **AND** ① 계약 단계가 진행 계열(ad-sync `stage` 문자열 그대로 — 계약) **AND** 계정 정상. 목록에서 사라진 계정은 즉시 쓰기를 중지하고 기록은 보존한다.

### 6-3. 작업 분산(대기열·순번)
1. **대기열 1개, 실행 프로세스 1개**. ③ 파일 잠금 선례를 쓰거나 별도 컨테이너로 둔다. gunicorn 워커마다 돌지 않게 한다.
2. **계정별 직렬화**: 한 customerId에는 동시에 1작업만 돈다(입찰 덮어쓰기와 경쟁 방지). 전역 동시 수는 작게(예: 4~8) 시작한다.
3. **고른 분산**: 800곳을 60분 슬롯에 해시로 배치한다(분당 약 13~14곳). 우선순위는 승인된 변경 > 매시간 자동 입찰 > 통계 > 일 배치 순이다.
4. **429/1016**: 지수 대기. 짧은 시간에 연속되면 전역 5분 휴지(2020-12-18 권고). 401/403/1006/1018은 그 계정을 「권한 상실」로 표시하고 쓰기를 중지한다. 503은 점검으로 보고 전체 대기한다.
5. **쓰기 안전**: 대표 확정상 무승인 자동은 「A/B 테스트」와 「상한 있는 입찰 조정」 두 가지뿐이다.
   - 입찰은 GET 직후 **절대값 PUT**으로 한다(재시도해도 이중 인상이 없다 — `naver_ad.py:20-42` 방식).
   - 기존 가드(±50% · 최소 70원 · 10원 단위 · 앵커 없으면 3,000원 상한 — `naver_searchad.py:282-306`) 위에 **광고주별 절대 상한**을 둔다.
   - **네이버 자동입찰(`autobidStrategy.isAutobidActive=true`) 그룹은 건너뛴다**(네이버가 입찰을 관리 — `SA/_posts/2025-10-15-release-note.md`).
   - 모든 변경은 감사 기록과 되돌리기 값을 남긴다.
6. **③ 자동입찰과 한 계정에 두 입찰기 금지**: README "이관 철칙"(같은 계정 동시 구동 금지)을 새 에이전트에도 적용한다. 쇼핑 1차는 자동입찰 엔진과 통합하거나, 계정 단위 소유권 표(`migration` 필드 방식)를 공유해야 한다.
7. **쇼핑 소재 입찰 경로 검증**: 자동입찰 엔진은 `PUT /ncc/ads/{id}?fields=adAttr`를 쓴다(`naver_ad.py:41-42`). 명세 열거값에는 `adAttr`가 없고, 관문은 **그룹 입찰가만** 검증한다(`gate.py:48-57`). 실증 때 소재 단위 쓰기도 함께 확인해야 한다.
8. 저장은 시간 단위 스냅샷을 보관 기한과 함께 두고, `cycleBaseTm`을 기록한다. stat-report는 D-1·D-2 재생성으로 48시간 수정을 반영한다(14일 보관이므로 받자마자 저장).


[핵심 사실]
- (확인) atower(매니저 계정) API는 GET 4개뿐이며 모두 조회 전용이다: /ad-accounts, /ad-accounts/{adAccountNo}/members, /manager-accounts, /manager-accounts/{managerAccountNo}/child-ad-accounts — SA/assets/json/atower.json › paths(operationId getAdAccountsUsingGET 등 4개); SA/_posts/2025-08-12-release-note1.md
- (확인) 실제 호출 경로는 /api 접두어 없이 https://api.searchad.naver.com/manager-accounts 형태다 — SA/app/config.js:44 uriReplace '^\/api'; 2025-08-12-release-note1.md 의 'GET /manager-accounts'; markdown-ko-KR.json #/guides Service URL
- (확인) child-ad-accounts 응답 항목은 adAccountNo·adAccountName·customerId(SA 계정 ID)·accountRole(MASTER/READ_ONLY)·ownerNaverId이고, 쪽당 최대 1000개라 800곳은 한 쪽에 들어간다 — atower.json › definitions.ChildAdAccount, parameters.size '최대 1000개'
- (확인) 관리계정·광고계정 역할 체계는 OWNER(계정책임자)/MASTER(운영관리)/READ_ONLY(운영조회)이고, 관리계정의 하위 계정 접근 역할은 MASTER 또는 READ_ONLY이다 — atower.json › definitions.ManagerAccount.roleName, AdAccount.roleName, ChildAdAccount.accountRole
- (확인) 옛 ManagedCustomerLink(/customer-links MYCLIENTS)는 2025-09-15 종료됐고 계정 마스터 리포트도 종료됐다. 공식 파이썬 샘플은 아직 옛 경로를 쓴다 — SA/_posts/2025-08-07-notice2.md, 2025-08-07-notice1.md; DOC/python-sample/examples/ad_management_sample.py:19-23
- (확인) 인증은 X-Timestamp·X-API-KEY(라이선스)·X-Customer(조회할 광고주ID)·X-Signature(HMAC-SHA256 'ts.METHOD.path' base64) 4헤더이고, 서명 URI는 경로만 쓴다 — SA/assets/i18n/markdown-ko-KR.json › #/samples; DOC/python-sample/examples/signaturehelper.py:9-14; ③ naver_searchad.py:22-36·277-279; ① NaverSearchAdClient.java:234-260
- (추정) 매니저 라이선스 1벌로 하위 광고주 customerId를 X-Customer에 넣어 조회할 수 있다 — X-Customer='조회할 광고주ID'(markdown-ko-KR.json #/samples); 옛 MYCLIENTS 샘플 흐름; 오류 1006/1018/5002(NaverSA_API_Error_Code_MAP.md:16-17,157); 2026-07-02 Agent 비밀키 공지. 명문 보장은 없다
- (미확인) 매니저 라이선스로 하위 계정 ncc 쓰기(입찰가 변경 등)는 accountRole=MASTER일 때만 될 것으로 보이지만 명세에 명문이 없다 — ChildAdAccount.accountRole 설명(MASTER=운영관리); 2025-08-12 공지 '대행사 Agent 관리 방식은 추후 가이드 예정'
- (확인) ① 전산은 광고주별 네이버 자격을 advertiser_platform_credential(업체×매체 1행)의 api_key_enc·api_secret_enc(jasypt 암호화)·api_customer_id(평문)로 저장한다(BLOCK 161) — metainc-web-backend/src/main/resources/schema.sql:4526-4539, 5039-5050; AdvertiserPlatformCredential.java:31-32, 69-76
- (확인) ① AdCredentialResolver가 가망 idx↔광고주 clientId(Client.legacyLeadId)를 바꿔 주고, integration_vendor=NAVER_SEARCHAD 매체에서 3종이 다 찬 자격만 돌려준다 — AdCredentialResolver.java:43-116; schema.sql:6301-6310(BLOCK 205); AdApiCredential.java:19-27
- (확인) ① 연결 시험은 POST /api/ad-setup/credentials/test → GET /ncc/campaigns 1회이고, 수집은 매일 05:05 계정당 캠페인 목록+stats 2회로 최근 30일 합계를 만든다 — AdSetupController.java:193-199; AdSetupService.java:862-888; NaverSearchAdClient.java:115-130, 157-189; AdMetricCollector.java:47-109; AdMetricCollectScheduler.java:32-37
- (확인) ③ 광고센터는 channel_credentials.fields_json에 customer_id·api_license·secret_key를 Fernet(키 파일 secret.key)으로 필드마다 암호화해 저장하고, DB는 SQLite다 — metainc-ad-dashboard/backend/app/models.py:157-166; routers/clients.py:1165-1172, 1931-1933; security.py:40-49; database.py:9-13
- (확인) ③ 자동입찰(content-studio/autobid)도 ab_account에 광고주별 customer_id·api_key_enc·secret_key_enc를 따로 저장한다. 같은 광고주 비밀값이 최대 세 벌로 흩어진다 — metainc-content-studio/autobid/app/models.py:14-35; app/naver_ad.py:12-17
- (확인) ③가 ① 자격을 가져다 쓰는 경로는 없다. ad-sync 응답 필드에 자격이 없다 — ① dto/adsync/AdSyncDto.java:20-26, 54-60; ③ erp_sync.py:120-157; ERP_CONTRACT_SYNC_API.md:59-100
- (확인) 네이버 검색광고 API 사용량 제한은 '호출 대상 계정당 속도 제한'이고 초당·일일·동시 수치는 공개돼 있지 않다 — SA/_posts/2020-12-18-notice.md:11; 명세 전체에 수치 없음
- (확인) 키워드도구는 다른 기능보다 1/5~1/6 느리게 제한되고 IP도 측정 단위에 들어간다. 대량 429가 나면 5분 이상 중단하라고 권고한다 — SA/_posts/2020-12-18-notice.md:27-36
- (확인) 키워드 일괄 수정은 요청당 200개, 키워드 생성은 100개가 상한이고, 쇼핑 소재 수정은 단건 PUT뿐이다 — ncc-heroes-ncc.json › PUT /api/ncc/keywords{?fields}, POST /api/ncc/keywords{?nccAdgroupId}, PUT /api/ncc/ads/{adId}{?fields}
- (확인) /stats 지연은 2025-10-27부터 약 2시간이다. stat-report는 D+1 제공·14일 보관이고 지표가 48시간 안에 수정될 수 있다 — SA/_posts/2025-09-26-notice2.md; 2018-01-12-notice.md
- (확인) master-report는 fromTime 이후 변경분(Delta)만 생성할 수 있어 구조 동기화 호출을 줄일 수 있다 — master-report.json › POST /master-reports RequestJob.fromTime
- (추정) 800곳 × 1시간 주기 호출은 최적화 시 약 4,400건/시간(1.2건/초)+일 배치 2~3만, 매시간 구조 재조회 방식이면 약 20,800건/시간(5.8건/초)이다 — 가정 A1~A5(광고주당 캠페인2·그룹10·소재50·입찰대상5, stats 50개 묶음, 소재 입찰 GET+PUT) 기반 계산; autobid/README.md 확정 스펙; naver_searchad.py:443-444
- (확인) 비즈머니 잔액은 GET /billing/bizmoney(bizmoney·budgetLock·refundLock·customerId)로 보고, 충전·차감·일별 이력 3경로가 있다. 사용조회(cost)는 2025-08-06 종료됐다 — ncc-heroes-billing.json › paths, definitions.Bizmoney; SA/_posts/2025-06-26-notice.md
- (확인) ② 로직분석이 같은 공유 서버에서 자기 라이선스로 /keywordstool을 호출한다. 키워드도구는 IP 한도라 ③ 에이전트가 쓰면 IP 예산을 나눠 쓴다 — logic-analysis/backend/naver_crawler.py:28-30, 786-799; SA/_posts/2020-12-18-notice.md
- (확인) 공유 서버는 메모리 3.9GB(가용 약 2.7GB)·디스크 36G 중 63% 사용이고, ③ ad-api는 SQLite+gunicorn 워커 4이며 수집은 계정 사이 1.5초 순차다 — ② CLAUDE.md 기록(2026-08-30·09-14); ③ Dockerfile:18-19, database.py:9-13, collector.py:16-17, 113
- (확인) 자동입찰 엔진은 쇼핑 소재 입찰을 PUT /ncc/ads/{id}?fields=adAttr로 쓰는데, 명세 fields 열거값에는 adAttr가 없고 관문은 그룹 입찰가 쓰기만 검증한다 — autobid/app/naver_ad.py:29-42; app/gate.py:48-57; ncc-heroes-ncc.json › PUT /api/ncc/ads/{adId}{?fields} enum ['userLock','inspect'], definitions.Ad.adAttr
- (확인) 쇼핑몰 상품형 그룹에 네이버 전환목표 자동입찰(autobidStrategy)을 켜면 네이버가 기본입찰가·소재 입찰을 관리하므로, 우리 입찰 쓰기와 충돌할 수 있다 — SA/_posts/2025-10-15-release-note.md

[위험]
- 매니저 라이선스로 하위 계정 쓰기가 명세상 보장되지 않는다. 실증 없이 설계를 확정하면 첫 실계정에서 1006/1018로 막혀 광고주별 3종 수령으로 되돌아갈 수 있다.
- 매니저 비밀키 1벌이 유출되면 광고주 800곳 전부가 영향을 받는다(피해 범위 집중). 저장·복호화 지점을 1곳으로 좁히고, 로그·오류 메시지에서 빼고, 교체 절차를 두어야 한다.
- 현재 같은 광고주 비밀값이 ① jasypt, ③ Fernet 키 파일, 자동입찰 Fernet env로 세 벌 흩어져 있다. 네이버 쪽 키 변경(2026-07-02 Agent 비밀키 변경 사례) 때 불일치와 누락이 생긴다.
- ① 호스트 api.metainc.co.kr는 HTTP이고 HTTPS 전환은 '안 함'으로 결정됐다. ①→③로 비밀키를 넘기는 설계는 평문 전송이 된다.
- ① JasyptConfig와 ③ security.py에 암호화 키·JWT 비밀의 개발용 기본값 폴백이 코드에 있다(값 생략). 운영 설정이 빠지면 약한 키로 암호화·서명될 위험이 있다.
- ③ 자동입찰(10분 주기)과 새 에이전트가 같은 계정 입찰가를 동시에 쓰면 서로 덮어쓴다(autobid README '이관 철칙').
- 네이버 자동입찰(autobidStrategy) 그룹에 우리 입찰을 쓰면 충돌한다.
- 호출 한도 수치가 비공개이고 IP 기반 보안 장치가 있다. 800곳을 몰아 부르면 429/1016이 연쇄로 나고 5분 휴지가 필요하다. ②의 keywordstool과 같은 IP를 쓴다.
- /stats는 약 2시간 늦고 지표는 48시간 안에 수정될 수 있다. 시간 단위 판단이나 짧은 A/B 판정은 오판할 수 있다.
- 쇼핑 소재 입찰 경로(fields=adAttr)는 명세 열거값에 없고 관문 검증도 없다. 1차(쇼핑)의 핵심 쓰기가 미검증 상태다.
- 공유 서버 메모리 가용 약 2.7GB, 디스크 63%이고 ③는 SQLite 단일 쓰기다. 시간별 스냅샷(하루 약 115만 행 가정)을 보관 정책 없이 쌓으면 서버 전체가 흔들린다.
- atower 응답 필드는 '추후 변경될 수 있음'으로 공지돼 있다. 동기화 파서가 조용히 깨질 수 있다.
- child-ad-accounts의 ownerNaverId는 개인 식별값이다. 저장·노출을 최소화해야 한다.
- ad-sync에 customerId 필드를 더하는 것은 ③↔① 외부 계약 변경이다. 사전 통지 없이 바꾸면 계약 위반이 된다.

[미확인]
- 매니저(관리계정 구성원) 라이선스로 X-Customer=하위 customerId를 넣어 ncc 읽기·쓰기가 되는지(명문 없음 — 실증 필요)
- atower(/manager-accounts 등) 호출 때 X-Customer에 넣을 값(매니저 자신의 customerId로 추정)
- API 라이선스가 네이버 ID(구성원) 단위인지 광고계정 단위인지
- READ_ONLY 하위 계정에서 쓰기 시 어떤 오류 코드가 오는지
- 비즈머니·stat-report·master-report를 매니저 라이선스로 하위 계정에 대해 호출할 수 있는지
- 초당·일일·동시 호출 한도 수치, 키워드도구 외 기능에서 IP가 한도 단위인지
- /stats ids 최대 개수와 ids 전달 형식(①은 쉼표 결합, ③는 반복 파라미터)
- atower page 파라미터가 0부터인지 1부터인지
- 쇼핑 소재 입찰 PUT /ncc/ads/{id}?fields=adAttr의 공식 지원 여부
- 광고주당 평균 캠페인·그룹·소재·입찰 대상 수(호출 추정의 입력값)
- 관리계정이 하나인지 여러 개인지(영업권 관리계정 체계 전환 방식 미공개), 800곳 중 accountRole=MASTER 비율
- ① advertiser_platform_credential에 네이버 자격이 채워진 업체 수, ③ channel_credentials naver_searchad connected 수(서버 DB라 조회하지 않음)
- ① BE 서버와 ③/② 공유 서버가 다른 호스트인지(docker ps 기록상 다른 호스트로 추정)