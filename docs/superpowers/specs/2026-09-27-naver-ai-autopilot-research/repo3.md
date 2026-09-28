# ③ 광고센터 저장소 지도: 네이버 광고 AI 자동운영을 얹기 위한 조사

조사 범위: `/home/user/metainc-ad-dashboard`(HEAD `c61a03e`, main과 같음)의 파이썬 파일 전부, `index.html`, 문서, 배포 파일. 참고로 ③의 다른 저장소 `metainc-content-studio/autobid`, ① 전산 BE의 광고 자격·수집·ad-sync 코드, 네이버 검색광고 공식 명세 로컬 사본도 함께 봤다.
작업은 읽기만 했다. 파일 수정·커밋·서버/네이버 호출은 없고, 비밀값은 옮겨 적지 않았다.

---

## 0. 결론

1. **③는 "사람이 버튼을 누르는 도구"로 설계돼 있어서, 24시간 도는 엔진을 얹을 자리가 없다.**
   - 스케줄러는 웹 워커 1개 안의 데몬 스레드이고, 하루 1번 06:00에만 돈다(`collector.py:16,128-151,154-170`).
   - DB는 SQLite 파일 1개다(`database.py:8-14`).
   - AI는 요청 시점에 `requests`로 직접 부른다(`ai_insights.py:13-26`).
2. **쇼핑검색 지원이 없다.** 어댑터는 캠페인 → 그룹 → 키워드만 다룬다.
   - 쇼핑 상품 소재(`/ncc/ads`)를 조회하거나 입찰을 바꾸는 함수가 없다(`adapters/naver_searchad.py` 함수 목록).
   - 캠페인 생성도 `WEB_SITE` 고정이다(`:133,:186`).
   - 키워드가 0개면 진단·제안이 400으로 거절된다(`routers/clients.py:1535,1571`). 그래서 쇼핑 전용 광고주는 지금 AI 기능을 못 쓴다.
3. **그대로 가져다 쓸 부품이 확실히 있다.**
   - HMAC 서명(`_signature/_headers`). 공식 샘플과 같은 방식이다.
   - 입찰가·예산 클램프(`clamp_bid/clamp_budget` + 상수).
   - "적용 직전 재조회 → 24시간 누적 상한 → 항목마다 즉시 저장, before/after 기록" 흐름(`clients.py:1673-1794`).
   - `SetupProposal`의 제안 → 승인 → 적용 표.
   - `ClientSetting` 키-값 저장소, RBAC(`deps.py`).
   - 이 부품들은 적대적 리뷰 반영 커밋 `4196f09`로 이미 한 번 다듬어졌다.
4. **800명 규모에서 막히는 지점이 정해져 있다.**
   - 관제 허브 `/team/overview`와 `/alerts`가 광고주마다 스냅샷 **전체 이력**을 불러온다(`clients.py:815-820,1428-1433`).
   - `/team/spend-by-month`는 **한 요청 안에서** 광고주마다 네이버를 실시간 호출한다(`clients.py:925-929`).
   - 수집은 1스레드 순차 처리에 광고주 사이 1.5초 대기다(`collector.py:17,113`).
   - AI 비서는 광고주 40곳만 본다(`insights.py:365`).
5. **같은 광고 계정에 쓰는 손이 여럿이다. 가장 큰 운영 위험이다.**
   - ③ autobid는 공유 서버에서 가동 중이다(logic-analysis CLAUDE.md, 2026-08-31 `docker ps` 실측).
   - 네이버 자체 쇼핑 자동입찰이 있다(2025-10-15 릴리스 노트).
   - 외부 프로그램이 있다(autobid README의 "이관 철칙").
   - 이번 엔진까지 더해진다. 계정 단위로 한 곳만 쓰게 하는 장치가 반드시 필요하다.

---

## 1. 구조

### 1-1. FastAPI 앱 구성 (`backend/app/main.py`)

**기동 순서**
1. `Base.metadata.create_all`(`:11`)
2. `ALTER TABLE`로 가벼운 마이그레이션. 실패는 무시한다(`:16-33`).
3. CORS `allow_origins=["*"]`(`:36-41`)
4. 라우터 4개를 `/api` 아래에 붙인다(`:43-46`).
5. `seed.run()`(`:54`). 사용자가 한 명이라도 있으면 시드를 건너뛴다(`seed.py:10-11`).
6. `collector.start_scheduler()`(`:59`)
7. `/connect/{token}` 공개 페이지(`:69-71`), 캐시 금지 `index.html`(`:79-82`), 정적 파일 mount(`:85`)

**라우터**

| 라우터 | 역할 |
|---|---|
| `auth.py` | 로그인, 내 정보, 비밀번호 변경, SSO |
| `clients.py` (2,053줄) | 광고주 CRUD, 채널 키, 리포트, 캠페인 제안, 관제, 소진, 설정·직원, 수집 트리거, 업로드, 경고, AI 진단·세팅, 메모, 이력, 내역서, 자가입력 링크 |
| `insights.py` | 예측, 예산, 키워드 추천, 동종비교, 텍스트, 시너지, 성공확률, NL 비서, 오토파일럿(시뮬레이션만), 리포트 예약 |
| `erp.py` | 전산 webhook 수신, 관리자 수동 동기화 |

`requirements.txt`에는 `fastapi, uvicorn, gunicorn, sqlalchemy, pydantic, python-jose, passlib, python-multipart, cryptography, bcrypt, requests, openpyxl`만 있다. **`anthropic` SDK와 스케줄러 라이브러리는 없다.**

### 1-2. DB

- **SQLite 파일 1개**: `DB_PATH` 환경변수, 없으면 `backend/app.db`(`database.py:8-9`).
- 운영 경로: 컴포즈가 `DB_PATH=/app/data/app.db`로 지정하고, 호스트 `./data`를 볼륨으로 붙인다(`docker-compose.yml:10-12`).
- 엔진 설정은 `check_same_thread=False`뿐이다. WAL·busy_timeout·풀 설정이 없다(grep 결과 0건).
- 마이그레이션 도구(Alembic 등)가 없다. `main.py`의 ALTER 목록이 전부다.
- 시각 형식이 섞여 있다.
  - `server_default=func.now()`는 SQLite에서 UTC(naive)다(`clients.py:1117` 주석).
  - `applied_at` 등은 KST ISO 문자열이다(`models.py:120,141`).

### 1-3. `models.py` 표 전체 (12개)

| 표 | 핵심 칸 | 비고 |
|---|---|---|
| `teams` (Team, :8) | id, name | |
| `users` (User, :14) | email(unique), name, password_hash, role, team_id | role = staff/lead/admin/viewer |
| `clients` (Client, :24) | name, category, status, owner_id, team_id, contact, contract_start/end, biz_reg_name, erp_possibility_id(idx), sales_manager, db_grade, memo, delete_requested_* | status = active/paused/ended/delete_requested/archived |
| `channel_metrics` (ChannelMetric, :46) | client_id, channel, payload_json, collected_at | 광고주 × 채널 × 수집시각 1행. 어댑터 결과를 통째로 JSON 저장. 복합 인덱스(client_id, channel, id)는 `main.py:26-27` |
| `reports` (Report, :56) | client_id, date_from/to, data_json, report_json, created_by | AI 결과보고서 |
| `connect_links` (ConnectLink, :69) | client_id, token(unique), channels_json, expires_at, used_at, submit_count | 광고주가 로그인 없이 키를 넣는 링크 |
| `activity_logs` (ActivityLog, :86) | client_id, user_id, user_name, type, message, meta_json, created_at | 광고주 타임라인. 메모도 `type="note"`로 여기 쌓인다(`clients.py:1797-1822`) |
| `campaign_proposals` (CampaignProposal, :103) | objective, monthly_budget, proposal_json, status(draft/applied/discarded), apply_result_json, applied_by/at | AI 캠페인 설계 → 대표만 실적용 |
| `setup_proposals` (SetupProposal, :123) | summary, diagnosis_json, items_json, status, result_json, applied_by/at | AI 세팅. 항목별 결과를 `result_json`에 남긴다 |
| `client_settings` (ClientSetting, :144) | client_id, key, value_json | 현재 key는 `autopilot`, `report_schedule` |
| `channel_credentials` (ChannelCredential, :157) | client_id, channel, mode(delegated/direct/upload), status(connected/disconnected), fields_json | 필드별 Fernet 암호화 |
| `monthly_records` (MonthlyRecord, :169) | month, client_id, client_name, total_spend, channels_json, recorded_by | 월 소진 확정 기록 |

- 암호화: Fernet 키 파일은 `FERNET_KEY_FILE` 또는 `backend/secret.key`이고, 없으면 자동 생성한다(`security.py:40-52`).
- JWT: HS256, 12시간(`:23-25`). ⚠️ `JWT_SECRET` 기본값 문자열이 코드(`security.py:23`)와 컴포즈 기본값(`docker-compose.yml:14`) 양쪽에 있다. 환경변수가 없으면 약한 비밀키로 돈다.

### 1-4. 역할·권한·광고주 가시성 (`deps.py`)

- **역할 4종**: admin(대표·전체) / lead(팀장·팀) / staff(담당자·본인) / viewer(전 직원·읽기 전용)(`:28-29`).
- **`visible_clients`**(`:32-39`): admin과 viewer는 전체, lead는 `team_id` 일치, staff는 `owner_id` 일치.
- **`can_edit`**(`:42-49`): viewer는 거짓, admin은 참, lead는 같은 팀, staff는 본인 광고주.
- **`require_editor`**(`:52-56`): staff/lead/admin만 통과, viewer는 403.
- **관리자 전용 경로**(`clients.py:233-235 _admin_only`): 전면삭제, 삭제승인·거부, 복원, 학습센터, 시스템 키, 직원 권한, 수동 수집, 캠페인 제안 **실적용**(`:729-731`), 전산 동기화(`erp.py:200`).
- ⚠️ `GET /clients/{id}`는 `can_edit`만 본다(`clients.py:120`). 그래서 viewer가 허브 행을 눌러 상세(`openDashboard`)를 열면 404가 난다. 반면 리포트·제안 목록은 viewer를 허용한다(`:590,697`). 규칙이 서로 다르다.

### 1-5. 로그인과 SSO (`routers/auth.py`)

- `POST /auth/login`: 이메일·비밀번호(pbkdf2_sha256).
- `POST /auth/sso`(`:57`):
  1. 전산 `ERP_BASE_URL="http://api.metainc.co.kr"`(`:52`)의 `/api/employee-management/my-profile`에 토큰을 전달해 검증한다(timeout 8초).
  2. `result.id`로 `email="erp:<로그인ID>"` 사용자를 찾고, 없으면 자동 가입시킨다.
  3. `authority.name`과 `teamList` 문자열에서 공백을 빼고 "광고관리"가 들어 있으면 staff, 아니면 viewer다(`:94-98`).
  4. admin은 SSO로 부여하지 않고 강등도 하지 않는다.
- 화면 쪽: `?sso=<토큰>`으로 들어오면 주소에서 토큰을 지우고 SSO를 호출한다(`index.html` bootstrap, 약 2485행).
- 전산 GNB는 iframe으로 `https://dashboard.metainc.co.kr`를 연다(`docs/전산-통합/AdvertisePage.tsx:11-12`). 주석에 "'ad.' 서브도메인은 광고차단기에 막혀 'dashboard.'로 사용"이라고 적혀 있다. 그런데 저장소의 nginx 설정·DEPLOY.md는 아직 `ad.metainc.co.kr` 기준이라 문서가 낡았다.

---

## 2. 네이버 검색광고 어댑터 (`backend/app/adapters/naver_searchad.py`, 484줄)

### 2-1. 서명

- `X-Timestamp`(ms), `X-API-KEY`, `X-Customer`, `X-Signature` = base64(HMAC-SHA256("ts.method.uri", secret))(`:22-36`).
- 서명에는 path만 넣고 쿼리는 `params`로 보낸다(`:275-279`, `_put` :335-344).
- 공식 파이썬 샘플(`searchad-apidoc/python-sample/examples/signaturehelper.py`)과 같은 방식이다.

### 2-2. 함수 전체

| 함수 | 읽기/쓰기 | 호출 | 비고 |
|---|---|---|---|
| `get_campaigns` :39 | 읽기 | GET /ncc/campaigns | 페이징(recordSize/baseSearchId) 미사용 |
| `get_stats` :47 | 읽기 | GET /stats (ids, fields=PERF_FIELDS, timeRange) | `PERF_FIELDS=[impCnt,clkCnt,salesAmt,ccnt,convAmt]`(:19) |
| `fetch_summary` :71 | 읽기 | 캠페인 목록 | 연결 테스트용 |
| `_derive` :84 | 계산 | CTR·CPC·ROAS | |
| `_post` :99 | 쓰기 | POST 공통 | |
| `get_channels` :108 | 읽기 | GET /ncc/channels | 비즈채널 |
| `build_plan` :117 | 계산 | 캠페인안 → 호출 계획(미리보기) | 캠페인 `WEB_SITE` 고정, `userLock:True` |
| `apply_plan` :163 | 쓰기 | 캠페인 → 그룹 → 키워드 생성 | 전부 일시중지로 생성. 월 한도 초과 시 거절 |
| `fetch_performance` :237 | 읽기 | 캠페인 + 기간 합계 | 수집기·실시간 조회 공용 |
| `clamp_bid` :293 / `clamp_budget` :311 | 계산 | 안전 범위로 자르기 | 아래 2-4 |
| `_get` :327 / `_put` :335 | 공통 | | 재시도·429 대기 없음 |
| `get_adgroups` :347 / `get_keywords` :352 | 읽기 | GET /ncc/adgroups?nccCampaignId, /ncc/keywords?nccAdgroupId | |
| `set_keyword_bid` :357 | 쓰기 | PUT /ncc/keywords/{id}?fields=bidAmt | 본문 {nccKeywordId, bidAmt, useGroupBidAmt:false} |
| `set_keyword_enabled` :366 | 쓰기 | PUT ...?fields=userLock | |
| `set_adgroup_budget` :375 | 쓰기 | PUT /ncc/adgroups/{id}?fields=budget | 본문 {nccAdgroupId, dailyBudget, useDailyBudget:true} |
| `add_keywords` :385 | 쓰기 | POST /ncc/keywords?nccAdgroupId | 항상 `userLock:True` |
| `collect_keyword_performance` :408 | 읽기 | 캠페인 → 그룹 → 키워드 + /stats(50개씩) | 켜진 캠페인 10개 × 그룹 10개, 키워드 통계 최대 120개(:415,419,441,443) |
| `get_keyword` :475 / `get_adgroup` :481 | 읽기 | 단건 | 적용 직전 재검증용 |

### 2-3. 쇼핑 캠페인·소재(상품) 단위 지원: **없음**

- `/ncc/ads` 계열 함수가 없다. 명세상 쇼핑 상품 소재는 `Ad.type=SHOPPING_PRODUCT_AD`이고, 입찰은 `Ad.adAttr {"bidAmt","useGroupBidAmt"}`에 들어 있다(`ncc-heroes-ncc.json` definitions `Ad`, `AdRequest.adAttr` 예시).
- ⚠️ 쇼핑 상품 소재의 입찰을 바꾸는 방법이 명세에 분명히 나와 있지 않다. `PUT /ncc/ads/{adId}{?fields}`의 fields 허용값은 `['userLock','inspect']`뿐인데, `adAttr` 칸은 `#required-update`로 표시돼 있다. autobid는 `fields=adAttr`로 구현했지만 "소재별 응답 스키마 차이가 있을 수 있어" 실패 시 원문을 그대로 반환하게 해 두었다(`autobid/app/naverad.py:29-42`). 실계정 검증 기록은 **미확인**이다.
- 네이버 자체 자동입찰: 쇼핑몰 상품형 그룹에는 `Adgroup.autobidStrategy`(`isAutobidActive`, `autobidBidGoal` NONE/MAX_CONV_VALUE)가 있다. 2025-10-15 릴리스 노트에 따르면 이 기능이 "그룹 기본입찰가·각 소재 노출 여부·실제 입찰가를 관리"한다. 켜진 그룹은 엔진이 건드리면 안 된다.
- 쇼핑용 예상 입찰가: `/npla-estimate/average-position-bid/{id|product}`, `/npla-estimate/exposure-minimum-bid/{type}`(estimate.json)이 있다. 어댑터는 추정 API를 전혀 쓰지 않는다.

### 2-4. 안전장치 상수와 clamp 로직 (`:282-324`)

**상수**

| 상수 | 값 | 뜻 |
|---|---|---|
| `MAX_CHANGE_PCT` | 50 | 1회 변경폭 상한(%) |
| `MIN_BID` | 70 | 최소 입찰가(원) |
| `MAX_BID_LIMIT` | 100000 | 입찰가 절대 상한(원) |
| `MIN_DAILY_BUDGET` | 100 | 일 예산 하한(원) |
| `NO_ANCHOR_MAX_BID` | 3000 | 현재값이 0일 때 입찰가 상한(원) |
| `NO_ANCHOR_MAX_BUDGET` | 100000 | 현재값이 0일 때 일 예산 상한(원) |

**`clamp_bid(current, proposed)`**
- 현재값 > 0이면 [max(70, cur×0.5), min(100000, cur×1.5)] 범위로 자른다.
- 현재값이 0이면 [70, 3000]으로 자른다.
- 결과를 10원 단위로 내리고, 70원 미만이면 70원으로 올린다.
- 반환값: (적용값, 잘렸는지, 사유 문구).

**`clamp_budget`**
- 현재값 > 0이면 [max(100, cur×0.5), cur×1.5]. ⚠️ 절대 상한이 없다.
- 현재값이 0이면 [100, 100000].
- 10원 단위로 내린다.

**라우터 쪽 추가 가드**
- 24시간 누적 상한 `DAILY_CUM_LIMIT_PCT=50`(`clients.py:1459`).
- 기준선 `_daily_baseline`(`:1462-1488`)은 **적용된 SetupProposal의 before 값만** 본다. 캠페인 제안 적용·autobid·사람 손 변경은 기준선에 들어가지 않는다.

⚠️ **최소 입찰가가 서로 다르다.** 어댑터는 70원인데, autobid는 "쇼핑검색 최소 입찰가 50"을 기본값으로 둔다(`autobid/app/config.py`). 명세의 `AdRequest.adAttr` 예시도 `bidAmt:50`이다. 쇼핑 최소가 공식적으로 얼마인지는 명세 본문에서 **미확인**이다. 70원 가드를 그대로 쓰면 쇼핑 입찰을 50~69원으로 못 내린다.

### 2-5. 명세와 대조해서 나온 점

- **PUT 본문이 최소 필드만 담고 있다.**
  - `AdKeyword.nccAdgroupId`는 명세상 `#required-update`인데 `set_keyword_bid`·`set_keyword_enabled` 본문에 없다.
  - Adgroup은 `dailyBudget, pcNetworkBidWeight, mobileNetworkBidWeight, useDailyBudget, useCntsNetworkBidWeight`가 `#required-update`인데 `set_adgroup_budget` 본문에 일부만 있다.
  - 공식 샘플과 autobid는 "GET → 합치기 → PUT" 방식을 쓴다(`ad_management_sample.py`, `autobid/app/naverad.py:20-26`).
  - 최소 본문이 실제로 통과하는지는 **미확인**이다(실적용 기록 없음).
- **429/1016 대비가 없다.** 명세상 사용량 제한은 "호출 대상 계정당 속도 제한"이다(2020-12-18 공지). 오류코드는 `1016 너무 많은 접속`, `429`(`NaverSA_API_Error_Code_MAP.md:15,163`). 어댑터에는 재시도가 없고, autobid 클라이언트만 429 재시도를 한다.
- **목록 페이징을 안 쓴다.** 캠페인은 1~2000, 그룹은 1~1000(recordSize/baseSearchId/selector)까지 한 번에 받는다.
- **`/customer-links`는 2025-09-15에 종료됐다**(2025-08-07-notice2). 대체 API는 `/manager-accounts`, `/manager-accounts/{no}/child-ad-accounts`(`atower.json`, 응답 `ChildAdAccount.customerId`, 페이지당 최대 1000)다.
- **파워링크(2차) 주의**: 그룹 생성 시 `aiAdsOptIn`을 지정하지 않으면 **true(ADVoost Max 사용)**로 처리된다(2026-07-15 릴리스 노트). `apply_plan`은 이 값을 보내지 않는다(`:212-219`). 지금은 `userLock:True`라서 바로 집행되지는 않는다.

---

## 3. AI 세팅 흐름 (제안 → 승인 → 실행)

### 3-1. 경로 (모두 `routers/clients.py`)

**1) 진단: `POST /clients/{id}/searchad/diagnose`**(`:1516-1549`, 쓰기 없음)
- admin·viewer 또는 편집 권한자만 호출할 수 있다.
- `_searchad_creds`로 키 3종을 복호화한다(`:1491-1505`).
- `collect_keyword_performance(days=30)`로 키워드 성과를 모은다.
- 키워드가 0개면 400(`:1535`).
- 입력: 광고주명, 업종, 메모 최근 3건(`_client_notes`, ActivityLog note), 캠페인, 그룹, 키워드 상위 60개(`:1542`).
- `ai_insights.diagnose_searchad`를 호출해 {headline, problem, good, advice, severity}를 받는다.

**2) 제안: `POST /clients/{id}/setup-proposals`**(`:1552-1642`, `require_editor` + `can_edit`)
- 같은 데이터를 모은 뒤 진단과 `propose_searchad_setup`을 **연달아 두 번** 호출한다.
- 정규화(`:1586-1629`):
  - 항목은 최대 8개(`:1590`).
  - 허용 타입만 남긴다.
  - target_id가 실제 수집 목록에 있는지 확인한다.
  - 서버가 `clamp_bid/clamp_budget`으로 `value, current_value, clamped, clamp_note`를 미리 계산한다.
- `SetupProposal(status=draft)`로 저장하고 ActivityLog `setup_proposal`을 남긴다.

**3) 목록: `GET /clients/{id}/setup-proposals`**(`:1645-1664`), 최근 10건.

**4) 적용: `POST /setup-proposals/{pid}/apply`**(`:1667-1794`, `require_editor` + `can_edit`)
- 본문: {item_indexes[], confirm}.
- 거절 조건:
  - `confirm`이 없으면 400.
  - 이미 적용된 제안이면 400(`:1687`).
  - **만든 지 2시간 지난 제안은 만료**(`:1692`).
  - 인덱스는 정규화한다(음수·범위 밖·중복 제거).
- 타입별 동작:

| 타입 | 동작 |
|---|---|
| `bid` | 실시간 `get_keyword`로 현재값을 다시 읽는다. 그룹 입찰가를 따르는 키워드면 그룹 입찰가를 기준으로 삼는다. `clamp_bid` → 24시간 누적 상한 → `set_keyword_bid` |
| `kw_off` | 되살릴 때 쓸 입찰가를 before로 저장 → `set_keyword_enabled(False)` |
| `budget` | `get_adgroup` 재조회 → `clamp_budget` → 24시간 상한 → `set_adgroup_budget` |
| `kw_add` | `clamp_bid(0, v)` → `add_keywords`(중지 상태) |

- **항목마다 `result_json`을 즉시 커밋**한다(`:1775-1779`).
- 끝나면 한 건이라도 성공했을 때 `status=applied, applied_by, applied_at`을 기록하고, ActivityLog `setup_applied`에 요약 한 줄을 남긴다(`:1781-1794`).
- ⚠️ 행 잠금이 없다. 같은 제안을 동시에 두 번 누르면 이중 적용될 여지가 있다(상태 확인과 적용 사이 경쟁).

### 3-2. 항목 타입

- 구현된 것: `ALLOWED_SETUP_TYPES={"bid","kw_off","kw_add","budget"}`(`:1456`).
- 설계 문서에 있으나 아직 없는 것: kw_on, group_onoff, camp_onoff(`docs/.../2026-08-29-naver-focus-redesign-design.md:81`).
- 쇼핑 소재 입찰 타입은 없다.

### 3-3. 다른 AI 쓰기 경로

- **캠페인 제안**: `POST /clients/{id}/campaign-proposals`(`:645`) → `campaign_ai.generate`. 적용 `POST /campaign-proposals/{pid}/apply`(`:709-766`)는 dry_run이 기본이고, 실적용은 admin만, confirm 필수, 월 한도 검사, 전부 일시중지로 생성한다. HANDOVER.md 11-3에는 "첫 실제적용 테스트 아직 안함"이라고 적혀 있다.
- **오토파일럿**: `AUTOPILOT_DEFAULT={"enabled":False,"target_roas":300,"max_bid_change_pct":20}`(`insights.py:392`). 설정 저장(`:402-416`)과 **시뮬레이션만** 있다. `executed:False`를 반환하고(`:419-444`), 캠페인 일예산 ±cap%만 흉내 낸다.

### 3-4. 모델 호출 방식

- 세 모듈 모두 **`requests.post("https://api.anthropic.com/v1/messages")`로 직접** 부른다. 헤더는 `x-api-key`, `anthropic-version: 2023-06-01`이다.
  - `campaign_ai.py:10-11,81-95`
  - `ai_insights.py:9-26`
  - `report_ai.py:11-12,297-311`
- 모델: 환경변수 `CLAUDE_MODEL` 하나를 세 모듈이 같이 쓴다. 기본값은 **`claude-sonnet-4-6`**이다(`campaign_ai.py:11`, `ai_insights.py:10`, `report_ai.py:12`, `docker-compose.yml:16`). 역할별로 다른 모델을 쓸 수 없다.
- max_tokens: 진단 1400, 제안 2600, 캠페인 3000, 리포트 2500, 비서 1200.
- timeout: 90~120초.
- 없는 것: 재시도, 사용량(토큰) 기록, 프롬프트 캐싱, 구조화 출력.
- JSON 파싱은 코드펜스를 벗기고 `{`부터 `}`까지 문자열을 잘라 쓴다(`ai_insights.py:29-35`, `campaign_ai.py:101-106`).
- 키는 `ANTHROPIC_API_KEY`이고, 없으면 한글 RuntimeError를 낸다.

**공식 SDK로 바꿀 때** (claude-api 스킬 기준으로 확인)
- `claude-sonnet-4-6`은 아직 유효한 이전 세대 모델이다($3/$15).
- 과제가 제시한 `claude-opus-5`($5/$25), `claude-sonnet-5`($2/$10), `claude-haiku-4-5`($1/$5) ID와 가격이 스킬 표와 일치한다.
- SDK로 쓸 수 있는 기능:
  - 구조화 출력: `client.messages.parse()` / `output_config.format`, `strict:true` 도구.
  - 자동 재시도: 408/409/429/5xx, 기본 2회.
  - 프롬프트 캐싱, `response.usage` 기록.
  - Message Batches: 비동기, 50% 비용.
  - Models API로 모델 존재 확인.
- 주의:
  - Opus 5와 Sonnet 5는 assistant prefill이 400이다.
  - Opus 5는 thinking이 기본으로 켜져 있다.
  - Haiku 4.5는 컨텍스트가 200K이고 `budget_tokens` 방식을 쓴다.

---

## 4. 수집기 (`backend/app/collector.py`)

### 4-1. 언제·무엇을·어떻게

**언제**
- 매일 **06:00 KST** 1회(`:16,120-126`).
- 스케줄러 라이브러리 없이 데몬 스레드가 `time.sleep(다음 06시까지)`로 기다린다(`:128-151`).
- gunicorn 워커 4개 중 **1개만** `fcntl.flock`으로 스케줄러를 잡는다(`:154-170`). 잠금 파일은 `DB_PATH`와 같은 디렉터리의 `collector.lock`.

**무엇을**
- 상태 connected이고, 수집기가 있는 채널이고, 광고주가 archived가 아닌 모든 `ChannelCredential`(`:82-91`).
- 채널별 함수: naver_searchad(`fetch_performance`, 기본 7일, 캠페인 합계), meta_chehum, youtube, meta_ads, kakao, coupang_ads, naver_gfa(`:66-74`).

**저장**
- 자격 1건마다 `ChannelMetric` 1행에 결과 JSON을 통째로 넣고 커밋한다. 실패는 롤백 후 목록에만 남긴다.
- 광고주 사이 `sleep(1.5)`(`:17,113`).
- ⚠️ 실패해도 `ChannelCredential.status`를 `error`로 바꾸지 않는다. 설계 문서 §3에 적힌 1줄 확장이 미구현이고, 허브는 화면에서 48시간 신선도로 "수집이상"을 계산한다(`index.html` boardState).

**후속 작업**: 같은 루프에서 `erp_sync.pull_sync`(`:137-146`)와 `insights.run_due_reports()`(`:147-151`)를 부른다.

**수동 실행**: `POST /admin/collect`는 admin 전용이고, **HTTP 요청 안에서 동기로** `collect_all()`을 돈다(`clients.py:1085-1092`). 스케줄 실행과 서로 막는 장치가 없다.

### 4-2. 광고주 800명이 되면 막히는 곳

1. **수집 시간** (추정)
   - 현재 방식: 광고주당 네이버 2회 호출 + 1.5초 대기로 약 2.5~3.5초. 800명이면 하루 1회 약 35~50분. 하루 1회로는 버틸 수 있다.
   - 시간 단위·키워드/소재 단위로 바꾸면: `collect_keyword_performance`가 광고주당 최대 약 114회를 호출한다(1 + 10 + 100 + 3). 800명이면 1주기에 약 9만 회다. 1스레드 순차로는 1시간 안에 끝낼 수 없다.
2. **수동 수집 요청**: 800명을 HTTP 요청 하나로 돌리면 nginx `proxy_read_timeout 120s`(저장소 conf 기준, 운영 conf는 **미확인**)를 넘는다. 스레드는 계속 돌아서 예약 수집과 겹치면 스냅샷이 중복 저장된다.
3. **`/team/overview`**(`:787-900`)와 **`/alerts`**(`:1415-1450`)
   - 광고주마다 `ChannelMetric`을 `.all()`로 **전 이력** 불러온다(`:815-820,1428-1433`).
   - 여기에 광고주당 connected 조회와 담당자 조회가 따로 붙는다. 800명이면 쿼리가 약 2,400개이고, 수집 이력이 쌓일수록 선형으로 느려진다.
   - `analytics.latest_per_channel`도 같은 패턴이다(`analytics.py:102-118`). 이 함수를 쓰는 동종비교가 모집단 광고주마다 반복한다(`insights.py:205-239`).
4. **`/team/spend-by-month`와 월 마감**: 광고주마다 `_gather_perf`로 네이버·기타 매체를 **실시간 호출**한다(`clients.py:925-929`). 월 마감 `close_monthly`도 이 함수를 부른다(`:960-979`). 800명이면 요청 하나가 타임아웃 난다.
5. **AI 비서 절단**: `clients[:40]`(`insights.py:365`). 800명 중 40명만 보고 답한다. 순서도 정해져 있지 않다.
6. **SQLite 잠금**: 워커 4개와 수집 스레드가 동시에 쓴다. WAL도 busy_timeout 조정도 없어서 시간 단위 엔진이 쓰기 시작하면 "database is locked" 위험이 커진다(추정).
7. **① 전산과 중복 수집**: ①도 `AdMetricCollectScheduler`가 매일 05:05 KST에 자체 자격으로 검색광고 통계를 걷는다(`metainc-web-backend/.../AdMetricCollectScheduler.java:36`). 같은 광고주를 두 번 조회한다.

---

## 5. 화면

### 5-1. 파일

- **실제로 쓰는 파일은 `backend/static/index.html` 하나**다. 305KB, 2,786줄. 인라인 CSS는 약 8~418행, JS는 약 620~2508행, 가이드는 2509행부터.
- 바닐라 JS다. 프레임워크·빌드가 없다.
- `app.js`와 `styles.css`는 Sprint 1 잔재로 **어디서도 참조하지 않는다**(grep 0건).
- `naver-categories.js`는 네이버쇼핑 카테고리 트리다(`window.NAVER_CATS`).
- `connect.html`은 광고주가 키를 넣는 공개 페이지다.

### 5-2. 라우팅

- 해시 기반이다.
  - `go(id)`(약 722행): `GO_DELEGATE`로 화면별 렌더 함수에 넘긴다.
  - `setRoute`(741행): 같은 주소면 다시 쓰지 않아 무한루프를 막는다.
  - `route()`(742행): `dashboard/{id}`, `register/{id}` 딥링크를 처리한다.
  - `hashchange`는 `_suppressHash`로 화면이 스스로 바꾼 주소를 무시한다.
- **새 화면 추가 절차**: nav 링크 + `<section id="s-...">` + route map + `activateScreen(id,navKey)` 또는 `setRoute`(HANDOVER.md 6장).

### 5-3. 주요 화면 위치

| 화면 | 위치 |
|---|---|
| 🎯 네이버 관제 허브 | `#s-home`. 정적 목업은 `loadHome()`(약 801행)이 갈아끼운다 |
| 광고주 상세 작업실 | `openDashboard(id)`(약 1220행), `#s-dashboard`에 그림 |
| AI 진단·세팅 패널 | 검색광고가 연동돼 있을 때만 붙는다(`aiPanelHtml` 약 1305행) |
| AI 캠페인 설계 | `openCampaign`(약 1774행) |
| 소진 관리 3탭 | `openSpending/openRecords/openUpload` + `moneyTabs` |
| 페이지별 사용 가이드 | `GUIDES`(2509행 이후) |

- 관제 허브 구성: `api('/team/overview')` 결과로 KPI 4장, 필터 알약, 검색, 표 `renderBoard`(837행). 연동 상태는 `CONNECT_META` 5종(connected/link_sent/link_expired/not_requested/stale), 네이버 연동 수 `naverConn`, 행 클릭 시 상세로 이동.
- AI 패널 함수: `runDiagnose`(1336), `setupChange`(1351, 서버가 실제 적용할 값만 표시), `setupHtml`(1359, 체크박스 목록), `runSetup`(1384), `applySetup`(1398, 확인창 뒤 `{item_indexes, confirm:true}` 전송).
- ⚠️ nav에는 설계 문서의 6메뉴가 아니라 10개 가까이 남아 있다(436~455행).

### 5-4. 재사용할 팔레트·클래스

**`:root` 토큰**(8행): `--bg #f4f6fa`, `--panel #fff`, `--panel2 #f1f3f8`, `--line #e4e7ee`, `--line2 #d6dae3`, `--text #1c2230`, `--sub #5f6878`, `--muted #9aa3b2`, `--green #16a34a`, `--amber #d97706`, `--blue #2f6fe0`, `--red #dc2626`, 각 `*bg`, `--naver #03c75a`, `--meta #6c5ce7`.
- 참고: 회사 표준 파랑 `#3b82f6`과 달리 `--blue`는 `#2f6fe0`이다.

⚠️ **CSS 범위 함정**: 대부분의 규칙이 `#s-dashboard .kpi-grid/.card/.cards/.section-title`처럼 화면 id에 묶여 있다. 다른 화면에서는 적용되지 않는다(HANDOVER.md 6장). 그래서 최근 화면(허브·AI 패널)은 **인라인 스타일 + 토큰**으로 짰다. 새 화면도 이 방식을 따르는 것이 안전하다.

---

## 6. 배포

- **Dockerfile**: python:3.12-slim, `TZ=Asia/Seoul`, `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:5051 --timeout 120`(`Dockerfile:18-20`).
- **docker-compose.yml**
  - 서비스 `ad-api`, 포트 `127.0.0.1:5051`, 볼륨 `./data:/app/data`.
  - 환경변수 이름: DB_PATH, FERNET_KEY_FILE, JWT_SECRET, ANTHROPIC_API_KEY, CLAUDE_MODEL, MC_AD_API_URL/TOKEN, YOUTUBE_API_KEY, COUPANG_ADS_PATH, GFA_API_BASE, ERP_SYNC_URL/API_KEY/STATUS/AUTOCREATE.
  - 헬스체크: `/api/health`, 60초 간격.
- **nginx**: `deploy/nginx-ad.metainc.co.kr.conf`. `ad.` 도메인 기준이라 운영 `dashboard.`와 다르다. 운영 conf는 서버에만 있다(**미확인**).
- **실제 배포 방식**: HANDOVER.md 3장에 따르면 로컬에서 rsync + ssh 수동 배포다(`/root/ad-dashboard-deploy`, `docker cp index.html` 후 `docker compose up -d --build`). GitHub Actions 배포는 보류 상태이고, `.gitignore:13-17`가 `.github/workflows/deploy.yml`을 제외한다.
- **공유 서버 동거**: 같은 VPS에 logic 5050, studio 5060, ad-api 5051, autobid 5070이 함께 돈다. logic-analysis CLAUDE.md의 2026-08-31 실측으로는 autobid 컨테이너 3개가 4주째 가동 중이고, `autobid_web`만 `0.0.0.0:5070`으로 열려 있다. `DEPLOY.md:59-60`이 권하는 `docker system prune -af`를 돌리면 다른 섹션의 롤백 이미지까지 지워진다.
- **테스트·검증 하니스: ③ 저장소에는 없다.** tests·pytest·verify 파일이 0건이다.
  - HANDOVER.md 3장에 수동 검증 패턴만 있다(py_compile, `node new Function`, TestClient + 임시 DB_PATH).
  - 설계 문서가 말하는 "기존 verify 하니스"(`:104`)는 저장소 밖이다(**미확인**).
  - autobid에는 `tests/`(pytest 9개 파일)와 `verify_phase0.py`가 있다.

---

## 7. ERP 연동 (`erp_sync.py`, `routers/erp.py`)

**당겨오기 `pull_sync`**(`erp_sync.py:114-157`)
- 환경변수 `ERP_SYNC_URL`과 `ERP_SYNC_API_KEY`가 없으면 아무것도 하지 않는다.
- 단계명 9개(`SYNC_STAGES`, :27-32)마다 `GET <url>?stage=<단계>&has_contract=true`를 `X-Api-Key`와 함께 호출한다.
- 응답 `result.items`를 풀어서 한 건씩 `upsert_company`에 넘긴다.

**`upsert_company`**(`:60-111`)
- 매칭: `possibility_id`가 먼저, 없으면 `company_name == client.name`.
- 갱신하는 칸: `contract_start`(가장 이른 시작일), `contract_end`(가장 늦은 종료일), `erp_possibility_id`, `biz_reg_name`, `sales_manager`, `db_grade`.
- 상태 자동 반영은 `ERP_SYNC_STATUS=1`일 때만 한다. `STAGE_MAP`: 진행중·전략관리 → active, 홀딩중·환불중 → paused, 계약만료 → ended, 사후관리 → archived(:18-23). 삭제요청 중인 광고주는 건드리지 않는다.
- 광고주 자동 생성은 `ERP_SYNC_AUTOCREATE=1`이면서 `ad_center_registered`가 켜져 있을 때만 한다.
- 영업담당 자동배정은 이름이 딱 1명 일치할 때만 한다.

**① 쪽이 실제로 보내는 필드** (`AdSyncDto.java`)
- `possibility_id, company_name, store_url, sales_manager(관리 담당자명), stage, ad_center_registered, contracts[round, product, start_date, end_date, amount, type]`.
- ⚠️ `biz_reg_name`과 `db_grade`는 보내지 않는다. 그래서 ③의 이 두 칸은 당겨오기로 절대 채워지지 않는다.

**webhook**: `POST /erp/contract-webhook`(`X-Webhook-Secret`)은 구현돼 있다. 하지만 ① 코드에서 이 주소를 호출하는 곳을 grep했더니 0건이다. 현재는 쓰이지 않는다.

**③가 받지 않는 것: 광고 API 자격.**
- ①에는 광고주별 자격 `AdvertiserPlatformCredential`(jasypt)과 해석기 `AdCredentialResolver`가 있다.
- ③는 이것을 받아오지 않고 자기 `ChannelCredential`(Fernet)을 따로 둔다.
- autobid는 또 따로 `Account` 표를 둔다(`AUTOBID_ENC_KEY`).
- 같은 광고주의 키가 세 군데에 흩어질 수 있다.

---

## 8. 자동운영 엔진을 얹을 때

엔진 요구사항: 목표 설정, 1시간 주기, A/B, 자동 입찰 조정, 감사 로그, 비상 정지.

### 8-1. 그대로 재사용할 것

- **서명과 호출 골격**: `_signature/_headers/_get/_put`.
- **clamp 로직과 상수**: 기본값으로 쓰되, 담당자가 정하는 상한으로 덮어쓸 수 있게 한다.
- **적용 흐름**(`apply_setup_proposal`):
  - 적용 직전 실시간 재조회
  - 그룹 입찰가를 따르는 키워드는 그룹가를 기준으로
  - 24시간 누적 상한
  - 항목별 즉시 커밋과 before/after 기록
  - 이 흐름을 엔진의 "변경 실행기" 표준으로 삼으면 된다.
- **`SetupProposal`**: 승인이 필요한 변경(예산, 새 키워드·그룹·소재, 켜기·끄기)의 대기열로 쓴다. 담당자 승인 → 적용 흐름이 이미 있다.
- **`ClientSetting`**: 광고주별 목표를 담는다(ROAS·CPA·노출·클릭 목표, 입찰 상한, 엔진 on/off). 기존 `autopilot` 키를 확장한다.
- **RBAC**: `visible_clients`, `can_edit`, `require_editor`, `_admin_only`.
- **ActivityLog**: 사람이 읽는 타임라인으로 계속 쓴다. 엔진 변경의 한 줄 요약을 여기에 남긴다.
- **ERP 단계 매핑**(`STAGE_MAP`): 계약만료·환불중·홀딩중 광고주는 엔진을 자동 정지한다. 다만 `ERP_SYNC_STATUS`가 기본 꺼짐이라 켜기로 결정해야 한다.
- **화면**: 허브 표(`renderBoard`), 작업실 AI 패널, 토큰 팔레트.
- **autobid 부품**(③ 소유라 이식 가능):
  - `decide.py`: 입찰 판단 순수 함수와 단위 테스트
  - `gate.py`: 신규 계정 읽기 확인 + 쓰기 +10원 변경·원복 검증
  - `naverad.set_ad_bid`: GET → 합치기 → PUT, 쇼핑 소재 `adAttr`
  - 하트비트, 감시자, 킬스위치
  - 계정 이관 상태 EXTERNAL/OURS/STOPPED
  - 429 재시도 클라이언트

### 8-2. 바꿔야 할 것

- **모델 호출**
  - `requests` 직접 호출을 **공식 `anthropic` SDK**로 바꾼다. requirements에 추가해야 한다.
  - 역할별 모델을 설정으로 둔다. 계획·진단 `claude-opus-5`, 반복 판단 `claude-sonnet-5`, 분류 `claude-haiku-4-5`. 지금은 `CLAUDE_MODEL` 하나라 나눌 수 없다.
  - JSON 문자열 자르기는 구조화 출력으로 바꾼다.
  - 사용량·요청 ID를 기록한다.
  - 고정된 시스템 프롬프트에 캐싱을 적용한다.
  - **새 모델을 들이기 전에 채점할 과거 데이터 시험 세트가 없다.** 하니스를 새로 만들어야 한다.
- **어댑터 확장**
  - 쇼핑: 소재 목록·단건 조회, 소재 단위 입찰 변경, 소재 id 기준 `/stats`(`purchaseCcnt/purchaseConvAmt/purchaseRor` 칸 존재), `autobidStrategy` 감지, NPLA 예상 입찰가.
  - 공통: 429/1016 백오프, 목록 페이징, 대량 조회용 stat-reports(`AD`, `AD_CONVERSION`, `SHOPPINGKEYWORD_DETAIL` 등), 비즈머니 잔액(`/api/billing/bizmoney`).
  - 수정 방식: GET → 합치기 → PUT.
- **실행 구조**: 웹 워커 안 데몬 스레드를 **별도 프로세스·컨테이너의 작업 큐와 워커**로 바꾼다. 계정별 동시성 제한을 두고, 1시간 주기로 광고주를 분산한다. 지금 구조는 웹 배포(재시작)가 주기 도중 엔진을 죽인다.
- **DB**: SQLite를 PostgreSQL이나 MariaDB로 옮긴다. 최소한 WAL과 단일 쓰기자를 둔다. 시각은 UTC 하나로 통일한다. 새로 필요한 표:
  - 목표·정책(auto/승인 필요 구분, 상한)
  - 주기 실행 기록
  - 시간별 엔티티 스냅샷
  - A/B 실험(대상, 대조군·실험군, 기간, 판정)
  - 변경 원장: 주체(엔진/사람), 대상 id, before/after, 사유, 모델·프롬프트 버전, 승인 id, 네이버 응답 원문
  - 비상정지 상태(전사·광고주 단위)
- **자격 출처 결정**: ① 자격, ③ 자격, autobid 계정 중 어느 쪽을 쓸지 대표가 정해야 한다.
  - 대행사 매니저 계정 하나로 800명을 다룰 수 있는지 확인이 필요하다. `/manager-accounts/{no}/child-ad-accounts`로 하위 계정의 customerId 목록은 받을 수 있다.
  - 하지만 매니저 라이선스 하나에 X-Customer만 바꿔서 하위 계정을 조작할 수 있는지는 명세에서 **미확인**이다. 2025-08-12 릴리스 노트는 "대행사 Agent 관리 방식은 추후 가이드"라고만 적었다.
- **권한 모델**: 엔진은 사람이 아닌 "시스템 주체"로 기록한다. 대표 결정대로 **A/B와 상한 안의 입찰 조정만 자동**, 나머지는 `SetupProposal` 승인으로 보낸다. 이 구분은 코드 상수가 아니라 정책 표에 둔다.
- **800명 대응**: `/team/overview`와 `/alerts`는 최신 스냅샷만 조회하도록(서브쿼리나 최신 표) 바꾼다. `/spend-by-month`는 저장된 스냅샷을 쓴다. AI 비서의 40명 절단은 명시하거나 요약 입력으로 바꾼다.
- **파워링크(2차) 대비**: 그룹을 만들 때 `aiAdsOptIn`을 명시한다. 기본값이 true이기 때문이다.

### 8-3. 위험

1. **여러 엔진이 같은 계정에 쓴다**: autobid 가동 중, 네이버 자체 자동입찰, 외부 프로그램. 계정 단위 "한 곳만 쓰기" 표시와 `isAutobidActive` 그룹 제외가 없으면 입찰가를 서로 덮어쓴다.
2. **A/B 테스트의 범위가 정해지지 않았다**: 무엇을 A/B하는지(입찰가 구간? 그룹 분할? 소재?)가 없다. 새 소재 생성은 네이버 심사 대상이고, 설계 문서는 소재 생성을 P2로 미뤘다(`:91`). 새 소재·그룹 생성은 대표가 정한 "승인 필요"와 겹친다. **정의가 필요하다.**
3. **상한 기준이 1시간 주기와 맞지 않을 수 있다**: 지금 가드는 1회 ±50%, 24시간 누적 ±50%, 절대 상한 10만원이다. 1시간마다 도는 엔진에는 주기당 상한, 광고주별 절대 최고 입찰가, 일 변경 횟수 같은 담당자 설정 상한이 따로 필요하다. 예산 쪽 `clamp_budget`에는 절대 상한이 없다.
4. **쇼핑 최소 입찰가가 70원인지 50원인지 모른다.**
5. **통계가 늦게 도착한다**: 전환은 뒤늦게 잡히고, 응답에 `cycleBaseTm` 최신 시각이 따로 있다. 1시간마다 판단하면 덜 쌓인 전환 데이터에 과민 반응할 수 있다(추정).
6. **최소 본문 PUT이 실계정에서 통과하는지 모른다**(2-5).
7. **SQLite 잠금과 데이터 손실**: 파일 DB 하나에 워커 4개가 붙어 있다. 백업 절차도 저장소 문서에 없다.
8. **보안**
   - CORS `*`, JWT 기본값 문자열.
   - HANDOVER.md 0장에 전산 연동 키(`AD_SYNC_API_KEY`)가 평문으로 있다. README.md·`seed.py:66` 출력에는 데모 계정 비밀번호가 평문으로 있다. 값은 옮기지 않았다.
   - `autobid_web`이 0.0.0.0에 열려 있다.
9. **운영 기반이 약하다**: 테스트·CI가 없고 root SSH 수동 배포다. 공유 서버라 prune을 돌리면 다른 섹션까지 피해를 본다.
10. **API 구조가 바뀌었다**: `/customer-links`는 종료됐다. 계정 구조는 2025-09 광고계정 통합 뒤의 체계를 따라야 한다.

---

## 9. 미확인으로 남긴 것 (지어내지 않음)

- 쇼핑 상품 소재 입찰 변경에 쓰는 PUT fields 값(`adAttr`)이 공식적으로 허용되는지.
- 쇼핑검색 최소 입찰가(50원 / 70원).
- 대행사 매니저 계정 라이선스 하나로 하위 광고계정을 X-Customer만 바꿔 조작할 수 있는지.
- 최소 본문 PUT(키워드 bidAmt, 그룹 budget)이 실계정에서 통과하는지.
- 운영 nginx 설정(`dashboard.` 도메인, 타임아웃 값).
- 운영 DB의 실제 광고주 수, 스냅샷 행 수, 크기.
- 설계 문서가 말하는 "기존 verify 하니스"의 위치.
- AI 세팅 적용(`apply_setup_proposal`)과 캠페인 제안 실적용이 운영에서 실제로 돌아간 적이 있는지.
- 네이버 샌드박스를 지금도 쓸 수 있는지(2022-04-01 공지만 확인).

[핵심 사실]
- (확인) ③ 광고센터는 FastAPI 앱 1개(라우터 auth·clients·insights·erp)이고, DB는 SQLite 파일 하나다. WAL·busy_timeout·마이그레이션 도구가 없다. — backend/app/main.py:11-46, backend/app/database.py:8-14, docker-compose.yml:12 (DB_PATH=/app/data/app.db), grep 'journal_mode|WAL|busy_timeout' 0건
- (확인) 표는 12개다(teams, users, clients, channel_metrics, reports, connect_links, activity_logs, campaign_proposals, setup_proposals, client_settings, channel_credentials, monthly_records). 채널 키는 필드마다 Fernet으로 암호화한다. — backend/app/models.py:8-184, backend/app/security.py:40-60
- (확인) RBAC는 admin=전체, lead=팀, staff=본인 광고주, viewer=전체 읽기 전용이다. 쓰기는 require_editor(staff/lead/admin)로 막는다. — backend/app/deps.py:29-56
- (확인) GET /clients/{id}는 can_edit만 확인해서 viewer가 광고주 상세 작업실을 열면 404가 난다. 리포트·제안 목록은 viewer를 허용하므로 규칙이 서로 다르다. — backend/app/routers/clients.py:114-122 vs :590, :697
- (확인) SSO는 전산 my-profile로 토큰을 검증해 자동 가입시키고, 팀명에 '광고관리'가 있으면 staff, 없으면 viewer를 준다. admin은 SSO로 부여하지 않는다. — backend/app/routers/auth.py:52-118 (특히 :94-98)
- (확인) 네이버 검색광고 어댑터는 캠페인·그룹·키워드 조회와 키워드 입찰·on/off·그룹 일예산·키워드 추가만 지원한다. 쇼핑 상품 소재(/ncc/ads) 조회·입찰 함수가 없고, 캠페인 생성은 WEB_SITE 고정이다. — backend/app/adapters/naver_searchad.py 함수 목록(:39-484), :133, :186
- (확인) 키워드가 0개인 광고주는 AI 진단·제안이 400으로 거절된다. 그래서 쇼핑 전용 광고주는 지금 AI 세팅을 쓸 수 없다. — backend/app/routers/clients.py:1534-1535, :1570-1571; collect_keyword_performance는 키워드만 순회(naver_searchad.py:408-472)
- (확인) 안전장치 상수는 MAX_CHANGE_PCT=50, MIN_BID=70, MAX_BID_LIMIT=100000, MIN_DAILY_BUDGET=100, NO_ANCHOR_MAX_BID=3000, NO_ANCHOR_MAX_BUDGET=100000이다. clamp는 ±50%, 10원 단위이고, 현재값이 0이면 보수적 상한을 쓴다. 예산에는 앵커가 있을 때 절대 상한이 없다. — backend/app/adapters/naver_searchad.py:282-324
- (확인) AI 세팅 적용 흐름: confirm 필수, 2시간 지난 제안 만료, 적용 직전 실시간 재조회, 24시간 누적 ±50% 상한, 항목마다 result_json 즉시 커밋과 before/after 기록, ActivityLog 요약. 항목 타입은 bid/kw_off/kw_add/budget 4종뿐이다. — backend/app/routers/clients.py:1456-1459, :1462-1488, :1672-1794
- (확인) 24시간 누적 기준선은 적용된 SetupProposal의 before 값만 본다. 캠페인 제안 적용·autobid·사람의 수동 변경은 반영되지 않는다. — backend/app/routers/clients.py:1462-1488
- (확인) AI 호출은 세 모듈 모두 requests로 api.anthropic.com/v1/messages를 직접 부른다. CLAUDE_MODEL 환경변수 하나를 공유하고 기본값은 claude-sonnet-4-6이다. 재시도·사용량 기록·구조화 출력이 없고 JSON은 문자열 자르기로 파싱한다. — campaign_ai.py:10-11,81-106; ai_insights.py:9-35; report_ai.py:11-12,297-323; docker-compose.yml:16; requirements.txt에 anthropic 없음
- (확인) claude-sonnet-4-6은 아직 유효한 이전 세대 모델이다($3/$15). 과제가 제시한 claude-opus-5($5/$25)·claude-sonnet-5($2/$10)·claude-haiku-4-5($1/$5)는 현재 모델표와 일치한다. — claude-api 스킬 Current Models 표(2026-06-24 캐시)
- (확인) 수집기는 매일 06:00 KST 1회, 웹 워커 4개 중 1개가 fcntl 잠금으로 잡은 데몬 스레드에서 순차 실행한다. 광고주 사이 1.5초를 쉬고, 결과 JSON을 ChannelMetric에 저장한다. 실패해도 자격 상태를 error로 바꾸지 않는다. — backend/app/collector.py:16-17, 77-117, 128-170; grep status='error' 0건
- (확인) 800명 규모에서 /team/overview와 /alerts는 광고주마다 스냅샷 전 이력을 불러오는 N+1 구조다. /team/spend-by-month는 한 요청 안에서 광고주마다 네이버를 실시간 호출한다. AI 비서는 40명만 본다. — backend/app/routers/clients.py:815-820, 1428-1433, 925-929; backend/app/routers/insights.py:365; analytics.py:102-118
- (추정) 수집을 키워드 단위·1시간 주기로 바꾸면 광고주당 최대 약 114회, 800명이면 1주기 약 9만 회 호출이다. 1스레드 순차로는 1시간 안에 끝낼 수 없다. — naver_searchad.py:415,419,441,443 상한값을 곱한 추정
- (확인) 화면은 backend/static/index.html 하나(305KB, 바닐라 JS, 해시 라우팅)다. app.js와 styles.css는 참조되지 않는 잔재다. 관제 허브는 loadHome/renderBoard, 작업실은 openDashboard, AI 패널은 aiPanelHtml/runSetup/applySetup이다. — index.html 약 722-757행(go/route), 801-884행, 1220-1416행; grep 'app.js|styles.css' index.html 0건
- (확인) CSS 규칙 대부분이 #s-dashboard 같은 화면 id에 묶여 있어 새 화면은 인라인 스타일과 :root 토큰(--blue #2f6fe0 등)으로 짜는 것이 관례다. — index.html:8 (:root), HANDOVER.md 6장
- (확인) 배포는 Docker(gunicorn -w 4 UvicornWorker, timeout 120)이고 127.0.0.1:5051로 연다. 실제 반영은 rsync와 ssh 수동이고 GitHub Actions 배포는 보류돼 있다. 저장소에 테스트·검증 하니스가 없다. — Dockerfile:18-20, docker-compose.yml:6-7, .gitignore:13-17, HANDOVER.md 3장, grep verify/pytest/TestClient 0건(코드)
- (확인) 운영 URL은 dashboard.metainc.co.kr이고, 저장소 nginx conf와 DEPLOY.md는 낡은 ad.metainc.co.kr 기준이다. — docs/전산-통합/AdvertisePage.tsx:11-12, deploy/nginx-ad.metainc.co.kr.conf:8, DEPLOY.md:1
- (확인) ERP 당겨오기는 단계 9개마다 X-Api-Key로 ① /api/ad-sync/contracts를 호출해 계약기간·영업담당 등을 upsert한다. 상태 반영(ERP_SYNC_STATUS)과 자동 생성(ERP_SYNC_AUTOCREATE)은 기본 꺼짐이다. — backend/app/erp_sync.py:18-157
- (확인) ① AdSyncDto는 biz_reg_name과 db_grade를 보내지 않는다. 그래서 ③의 두 칸은 당겨오기로 채워지지 않는다. ③ webhook을 ①이 호출하는 코드도 없다. — metainc-web-backend/.../dto/adsync/AdSyncDto.java:20-27; ① src grep 'contract-webhook|X-Webhook-Secret' 0건
- (확인) 같은 광고주의 네이버 API 자격이 ① AdvertiserPlatformCredential(jasypt), ③ ChannelCredential(Fernet), autobid Account 세 군데에 따로 저장될 수 있다. ①도 매일 05:05에 자체 수집한다. — ① entity/AdvertiserPlatformCredential.java:30-85, service/adcred/AdCredentialResolver.java; ③ models.py:157-166; autobid/app/naverad.py:12-17; ① scheduler/AdMetricCollectScheduler.java:36
- (미확인) 쇼핑 상품 소재 입찰은 Ad.adAttr{bidAmt,useGroupBidAmt}에 있다. 그런데 PUT /ncc/ads/{adId}의 fields 허용값은 userLock·inspect뿐이라 adAttr 변경 방법이 명세에 분명하지 않다. — ncc-heroes-ncc.json definitions Ad/AdRequest.adAttr, paths PUT /api/ncc/ads/{adId}{?fields} fields enum; autobid/app/naverad.py:29-42 주석
- (확인) 쇼핑몰 상품형 광고그룹에는 네이버 자체 전환목표 자동입찰(autobidStrategy, MAX_CONV_VALUE)이 있어서 그룹 입찰과 소재 입찰을 스스로 관리한다. 켜진 그룹은 엔진이 건드리면 충돌한다. — sa-pages/_posts/2025-10-15-release-note.md; ncc-heroes-ncc.json definitions Adgroup.autobidStrategy, AutobidStrategyRequest
- (확인) /customer-links(ManagedCustomerLink)는 2025-09-15에 종료됐다. 대행사는 /manager-accounts와 /manager-accounts/{no}/child-ad-accounts(ChildAdAccount.customerId, 페이지당 최대 1000)로 하위 계정을 조회해야 한다. — sa-pages/_posts/2025-08-07-notice2.md, 2025-08-12-release-note1.md, assets/json/atower.json
- (미확인) 매니저 계정 라이선스 하나에 X-Customer만 바꿔서 하위 광고계정 800곳을 조작할 수 있는지는 명세에 나와 있지 않다. — 2025-08-12-release-note1.md:50 '대행사 Agent 관리 방식은 추후 가이드'; atower.json에 호출 방식 서술 없음
- (확인) 네이버 API 사용량 제한은 호출 대상 계정당 속도 제한이고, 오류코드 429와 1016이 있다. ③ 어댑터에는 재시도·백오프가 없다(autobid 클라이언트만 429 재시도). — sa-pages/_posts/2020-12-18-notice.md; NaverSA_API_Error_Code_MAP.md:15,163; naver_searchad.py:327-344; autobid/naverad_client.py:68-78
- (확인) 파워링크 그룹은 aiAdsOptIn을 지정하지 않으면 ADVoost Max가 켜진 상태(true)로 생성된다. 현재 apply_plan은 이 값을 보내지 않는다. — sa-pages/_posts/2026-07-15-release-note.md; naver_searchad.py:212-219
- (미확인) 쇼핑 최소 입찰가가 어댑터(70원)와 autobid 설정(50원)에서 다르다. 공식 최소값은 명세 본문에서 찾지 못했다. — naver_searchad.py:283; autobid/app/config.py MIN_BID 기본 50; ncc-heroes-ncc.json AdRequest.adAttr 예시 bidAmt:50
- (확인) ③ autobid 컨테이너가 공유 서버에서 가동 중이다(2026-08-31 실측). 네이버 자체 자동입찰, 외부 프로그램과 함께 같은 계정에 입찰을 쓸 수 있다. — /home/user/logic-analysis/CLAUDE.md 2026-08-31 docker ps 표; autobid/README.md '이관 철칙'

[위험]
- 같은 광고 계정에 여러 엔진이 입찰을 쓴다: 가동 중인 autobid, 네이버 쇼핑 자체 자동입찰(autobidStrategy), 외부 프로그램, 새 엔진. 계정 단위 '한 곳만 쓰기' 표시와 isAutobidActive 그룹 제외가 없으면 입찰가를 서로 덮어쓴다.
- 쇼핑 상품 소재 입찰 변경 방법(PUT /ncc/ads fields=adAttr)이 명세상 불명확하고 실계정 검증 기록이 없다. 1차 쇼핑의 핵심 쓰기 경로다.
- 키워드 입찰·그룹 예산 PUT이 명세상 #required-update 필드를 빠뜨린 최소 본문으로 보내진다. 실계정에서 거절되거나 다른 필드가 초기화될지 미검증이다. 공식 샘플과 autobid는 GET→합치기→PUT을 쓴다.
- 쇼핑 최소 입찰가 불일치(어댑터 70원, autobid 50원). 70원 가드를 그대로 쓰면 쇼핑 입찰을 50~69원으로 못 내린다.
- clamp_budget은 앵커가 있으면 절대 상한이 없다. 24시간 누적 ±50%와 1회 ±50%는 1시간 주기 자동 엔진용 상한으로 설계된 게 아니다. 주기당 상한, 광고주별 최고 입찰가, 일 변경 횟수 같은 담당자 설정 상한이 필요하다.
- 24시간 누적 기준선이 SetupProposal 적용 이력만 봐서 엔진·autobid·사람의 변경을 합산하지 못한다. 변경 원장이 하나로 통합돼야 한다.
- 'A/B 테스트'의 대상과 방식이 정의되지 않았다. 새 소재·그룹 생성은 네이버 심사 대상이고 대표가 정한 '승인 필요' 항목과 겹친다.
- 통계·전환이 늦게 들어오는데(cycleBaseTm) 1시간 주기로 판단하면 덜 집계된 전환에 과민 반응할 수 있다(추정).
- 웹 워커 안 데몬 스레드 스케줄러라 웹 배포·재시작이 엔진 주기를 중간에 끊는다. /admin/collect는 HTTP 요청 안에서 동기로 돌아 예약 수집과 겹칠 수 있다.
- SQLite 파일 하나에 gunicorn 워커 4개와 수집 스레드가 동시에 쓰는데 WAL·busy_timeout 설정이 없다. 엔진 쓰기가 늘면 database is locked 위험이 크다.
- 800명에서 /team/overview와 /alerts는 스냅샷 전 이력을 N+1로 불러오고, /team/spend-by-month와 월 마감은 한 요청 안에서 광고주 전원을 실시간 호출한다. 느려지거나 타임아웃이 난다.
- AI 비서가 clients[:40]만 보고 답해서 800명 중 대부분을 빠뜨린 답을 조용히 낸다.
- AI 호출이 모델 하나(CLAUDE_MODEL)를 공유하고, 재시도·사용량 기록·구조화 출력이 없고, JSON을 문자열 자르기로 파싱한다. 과거 데이터 시험 세트(eval)도 없어서 모델 교체를 채점할 수 없다.
- 광고 API 자격이 ① AdvertiserPlatformCredential, ③ ChannelCredential, autobid Account 세 군데로 나뉠 수 있다. 키 갱신 누락이나 서로 다른 키 사용 위험이 있다. ①·③ 수집이 같은 광고주를 두 번 조회한다.
- 파워링크(2차) 그룹 생성 시 aiAdsOptIn을 지정하지 않으면 ADVoost Max가 기본으로 켜진다.
- 네이버 API 429/1016 대비(백오프)가 ③ 어댑터에 없다. 대량 호출이 한꺼번에 몰리면 계정별 속도 제한에 걸린다.
- 보안: CORS allow_origins '*', JWT_SECRET 기본값 문자열이 코드와 컴포즈에 있다. HANDOVER.md에 전산 연동 키가, README.md와 seed.py 출력에 데모 비밀번호가 평문으로 있다(값은 옮기지 않음). autobid_web이 0.0.0.0:5070으로 열려 있다.
- 운영 기반이 약하다: 테스트·CI가 없고 root SSH rsync 수동 배포다. 공유 서버(②·스튜디오·autobid 동거)에서 DEPLOY.md가 권하는 docker system prune -af를 돌리면 다른 섹션의 롤백 이미지까지 지워진다.
- /customer-links API가 종료됐고 계정 구조가 2025-09 광고계정 통합 체계로 바뀌었다. 옛 공식 샘플 방식을 따르면 실패한다.
- 문서가 낡았다: nginx conf·DEPLOY.md는 ad.metainc.co.kr인데 운영은 dashboard.metainc.co.kr이다. 설계 문서의 6메뉴·error 상태·추가 항목 타입은 일부만 구현됐다.

[미확인]
- 쇼핑 상품 소재(SHOPPING_PRODUCT_AD) 입찰 변경에 PUT /ncc/ads/{adId}?fields=adAttr를 공식적으로 쓸 수 있는지
- 쇼핑검색 최소 입찰가 공식 값(50원 / 70원)
- 대행사 매니저 계정 API 라이선스 하나에 X-Customer만 바꿔 하위 광고계정 약 800곳을 조작할 수 있는지(광고계정 통합 뒤 Agent 방식 가이드)
- 키워드 bidAmt와 그룹 budget을 최소 본문 PUT으로 보냈을 때 실계정에서 통과하는지, 다른 필드가 초기화되지 않는지
- 운영 서버 nginx 설정(dashboard.metainc.co.kr, proxy_read_timeout 값)
- 운영 DB의 실제 광고주 수, ChannelMetric 행 수, DB 파일 크기, 백업 절차
- 설계 문서가 말하는 '기존 verify 하니스'의 위치와 존재 여부
- apply_setup_proposal(AI 세팅 실적용)과 apply_campaign_proposal 실적용이 운영에서 실제로 실행된 적이 있는지
- 네이버 검색광고 샌드박스를 현재 쓸 수 있는지(2022-04-01 공지만 확인)
- 'A/B 테스트'로 자동 허용하는 대상의 정의(입찰가 구간 실험인지, 그룹 분할인지, 소재 교체인지)
- 자동입찰 판단에 쓸 통계의 실제 지연 시간(cycleBaseTm)과 전환 집계 지연
- 자격 정본을 ① AdvertiserPlatformCredential, ③ ChannelCredential, autobid Account 중 어디로 둘지(대표 결정 필요)
- autobid의 현재 대상 계정·가동 범위, 이번 엔진과의 역할 분담