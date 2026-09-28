# ③ 기존 「쇼핑 순위 기반 자동입찰(autobid)」 전수 판독 보고

범위: `/home/user/metainc-content-studio/autobid/` 전체(파이썬 4,429줄 · 시험 70개) + 배포 워크플로 `.github/workflows/deploy-autobid.yml` + git 이력(autobid 커밋 37개, 마지막 2026-07-30) + 이것을 쓰는 쪽(① `AutobidClient`)·감시하는 쪽(② 로직분석 WORKLOG) 교차 확인. 읽기만 했고 네이버·서버는 부르지 않았다. 비밀값은 옮겨 적지 않았다(이름만 적음).

> ⚠️ 문서 범위 정정: content-studio 저장소의 `README.md`·`OPERATIONS.md`·`DEPLOY.md`·`CHANGELOG.md`·`HANDOFF_BRIEF.md` 에는 **autobid 언급이 0건**이다(grep `autobid|자동입찰|입찰|5070` 결과 없음). autobid 문서는 `autobid/README.md` 한 개, 커밋 메시지, 배포 워크플로뿐이다. ③ 광고센터 저장소에서도 `HANDOVER.md:28`(「자동입찰(쓰기)은 S5 후속」) 한 줄이 전부다.

---

## 0. 한 줄 결론
- autobid 는 **「쇼핑 상품 소재(nccAdId) × 검색어」 하나마다 목표 광고 순위(기본 3위)를 정해 두고, 10분마다 소재 입찰가를 올리거나 내리는** 순위 추종형 엔진이다. 사람이 정한 상한(max_bid)이 있어야만 돈다.
- **이미 멈췄다.** 2026-09-10 ③ 가 서버 컨테이너 3개를 지우고 외부 포트를 닫았다(② `docs/WORKLOG.md:3121-3130`, ③ 회신 인용). 멈추기 전 실제 규모는 **광고계정 2개 · 키워드 2개**, 마지막 입찰 변경은 **2026-07-30 12:33**, 그 뒤 6주 동안 판정은 전부 CAP(상한에 붙어 보류)였다(같은 곳 :3133-3137).
- 권고: **공존 금지 · 서버는 되살리지 않음 · 코드 조각만 새 엔진에 흡수**. 세 저장소를 통틀어 **쇼핑 소재 단위 입찰가를 읽고 쓰는 코드는 이것뿐**이라(① `NaverSearchAdClient`, ③ `naver_searchad.py` 둘 다 `adAttr`·`/ncc/ads`·`npla-estimate` 0건) 참고 가치는 크다. 다만 순위를 얻던 방식(사무실 회선에서 브라우저로 위장해 검색 결과를 긁는 에이전트)은 가져오지 않는다.

---

## 1) 무엇을 하는가

### 1-1. 입찰 대상과 목표
- 입찰 대상 1건 = 쇼핑 상품 소재 × 쇼핑 검색어(`app/models.py:38-61` `BidTarget`: `adgroup_id`, `ad_id`(nccAdId), `keyword`, `nv_mid`, `mall_name`, `device`, `target_rank` 기본 3, `max_bid` 필수, `step` 기본 50, `enabled` 기본 꺼짐).
- 확정 사양(README): 쇼핑검색 먼저 · 파워링크는 3단계 · 규모 1,000계정 × 키워드 5개 = 5,000건 · 10분 주기 · 순위는 모바일·서울 기준 · 광고주 API 키는 **직접 받아 암호화 저장**(`autobid/README.md:7-16`).
- 목표는 **순위 하나**다. 전환·ROAS·예산은 판단에 들어가지 않는다(`app/decide.py:25-67` 입력은 현재가·현재 순위·목표 순위·step·상한·하한·오늘 인상 횟수뿐).
- 목표 순위는 1~10위까지 등록할 수 있다(`app/web.py:224`).

### 1-2. 순위를 어디서 얻나 — 네 번 바뀌었다(git 이력)
| 순서 | 방식 | 코드 | 결과 |
|---|---|---|---|
| ① | 서버가 모바일 쇼핑 검색 결과를 직접 긁음(`msearch.shopping.naver.com/search/all`, `__NEXT_DATA__` 파싱) | `app/ranker.py:23-66` | 2026-07-29 서버 IP 가 418 로 막힘(`app/estimator.py:3-6` 주석). 지금은 진단 경로 `/api/rank-test` 에서만 쓴다(`app/web.py:433-452`) |
| ② | 공식 **쇼핑검색 순위별 예상 입찰가** `POST /npla-estimate/average-position-bid/id`(1~4위) → 현재가가 몇 위 예상가에 닿는지로 **예상 순위** 산출 | `app/estimator.py:26-83` | 평균 지표라 목표 3위인데 실제 1위 노출(과입찰) 사고(`app/stats.py:4-7` 주석) |
| ③ | 공식 통계 `/stats` 의 `avgRnk` | `app/stats.py:23-94` | 모든 검색어 평균이라 순위 판정 금지로 회수(`app/engine.py:63` 주석, 커밋 c321347). 진단 `/api/stat-test` 에만 남음 |
| ④ | **사무실(맥미니) 에이전트**가 10분마다 네이버를 긁어 `/api/agent/slots` 로 보고 → 서버는 저장된 값만 읽음 | `agent/autobid_agent.py` 전체, `app/web.py:465-538`, `app/ranker.py:135-145` | 최종 구조. 신선한 값(기본 1,200초 이내 `config.py:45`)이면 1순위, 없거나 오래되면 ② 예상가로 되돌아감(`engine.py:67-81`) |

- 에이전트 방식: `curl_cffi` 로 브라우저를 흉내 내고 네이버 홈을 먼저 들러 쿠키를 받은 뒤 요청(`agent/autobid_agent.py:102-128`). 418 이 나면 주소·요청 모양을 바꿔 가며 다시 두드린다(`:294-311`, v6·v8 설명 `:18-24`).
- 최종 판단 기준은 **쇼핑검색 1페이지의 광고 모듈에서 소재 ID(`nad-a001-02-…`)가 나오는 순서**다(`agent/autobid_agent.py:183-199, 348-352`, 커밋 8e9d5a7). 자연 상품 카드 순위는 화면 표시용 「심층 순위」로만 보낸다(`:314-352`, `engine.py:100-104`).

### 1-3. 주기
- 엔진 10분(`app/config.py:12`, `AUTOBID_CYCLE_MINUTES`). 운영 시간 08~24시(`config.py:15-16`, `engine.py:135`) — 그 밖에는 바꾸지 않고 하트비트만 찍는다.
- 계정을 10분 창(540초) 안에 고르게 나눠 처리하고 계정 사이 최대 30초 쉰다(`engine.py:154-155, 185-186`).
- 목표를 이룬(HOLD) 대상은 두 사이클에 한 번만 본다(`engine.py:166-167`).
- 예상가·순위 저장값 유효 480초(`config.py:29`).
- 에이전트도 10분(서버가 `intervalSec` 로 내려줌 `web.py:488`, 에이전트 `:355-397`), 검색어 사이 3초(`:93`), 실패하면 1분 뒤 재시도(`:95, 407-411`).

### 1-4. 입찰 계산식(`app/decide.py:25-67`, 순서대로 먼저 걸리는 것이 이긴다)
1. 현재 입찰가를 모르면 → **FREEZE**(동결)
2. 현재가 > 상한 → **상한까지 즉시 인하**(순위 데이터와 무관, 동결보다 먼저)
3. 순위 데이터 없음 → **FREEZE**(마지막 입찰가 유지)
4. 순위 밖 또는 목표보다 아래 → 이미 상한이면 CAP, 오늘 인상 30회 넘었으면 CAP. 목표 순위 예상가를 알면 그 값으로 바로(상한까지), 모르면 `현재가 + step`(상한까지)
5. 목표보다 위(과입찰) → 예상가가 있고 차이가 step 이상이면 `max(최소 입찰가, 예상가)` 로, 아니면 `max(최소 입찰가, 현재가 − step)` 로 인하
6. 목표와 같음 → HOLD
- 엔진 쪽 추가 규칙: 에이전트 실측이 있을 때는 **순위 밖일 때만** 예상가로 뛰어오르고, 노출 중이면 step 단위로만 움직인다(`engine.py:69-76`). 예상가 모드에서는 목표 순위를 4위로 자른다(`engine.py:80`).

### 1-5. 안전장치
| 장치 | 값 | 근거 |
|---|---|---|
| 상한 필수 | 없으면 등록 거부 | `web.py:222-223` |
| 최소 입찰가 | 50원 | `config.py:19` |
| 대상당 하루 인상 횟수 | 30회 | `config.py:20`, `engine.py:30-34` |
| 급등 차단 | 30분 창 첫 입찰가의 2배 이상이면 단계 인상으로 낮추고, 그래도 넘으면 CAP | `config.py:21-22`, `engine.py:37-44, 89-96` |
| 절대값 설정 | 같은 요청이 두 번 가도 두 번 오르지 않음 | `app/naverad.py:20-42` |
| 전체 비상 정지 | `EngineState.kill_switch` | `models.py:92`, `engine.py:131-135`, `web.py:651-659` |
| 계정 격리 | 계정 하나의 예외가 사이클을 못 멈춤 | `engine.py:174-179` |
| 사이클 중복 실행 막음 | 시작 뒤 10분 안 미완료면 건너뜀 | `engine.py:140-143` |
| 세이프 모드 표시 | 한 사이클의 모든 대상이 FREEZE 면 `safe_mode=True` | `engine.py:189-193` |
| 신규 계정 관문 | 읽기 + 광고그룹 입찰가 +10원 → 확인 → 원복 통과한 계정만 엔진이 처리 | `app/gate.py:15-59`, `engine.py:149-152` |
| 이관 상태 | EXTERNAL / OURS / STOPPED — OURS 만 처리 | `models.py:24-25`, `web.py:207-216` |

### 1-6. 감시견(watchdog) 역할
- 엔진과 따로 도는 프로세스. 60초마다 `EngineState.heartbeat_at` 을 보고, **15분 넘게 소식이 없으면 웹훅으로 한 번 알리고**, 돌아오면 복구 알림(`watchdog.py:16-18, 32-52`). 웹훅 이름 `AUTOBID_ALERT_WEBHOOK`, 비어 있으면 로그만.
- 엔진이 계정 하나 처리할 때마다 하트비트를 찍는다(`engine.py:182-183`).
- 보지 않는 것: 세이프 모드, 비상 정지, 오류 수, CAP 연속, 에이전트 실측이 오래됐는지. ⇒ **「살아 있지만 일을 안 하는」 상태는 못 잡는다**(아래 4절 6주 CAP 사례).
- 세 프로세스 모두 `restart: always` 컨테이너(`docker-compose.autobid.yml:13, 23, 33`).

---

## 2) 네이버 API 클라이언트(`naverad_client.py` + `app/naverad.py`)

### 2-1. 서명·헤더
- `X-Timestamp`(밀리초) · `X-API-KEY` · `X-Customer` · `X-Signature = base64(HMAC-SHA256("{ts}.{METHOD}.{path}", 비밀키))`, 쿼리스트링은 서명에서 뺀다(`naverad_client.py:36-50`). 모든 요청에 `Content-Type: application/json; charset=UTF-8`.
- 키 이름: 0단계 스크립트는 `AUTOBID_API_KEY`·`AUTOBID_SECRET_KEY`·`AUTOBID_CUSTOMER_ID`(`README.md:48-52`), 운영 엔진은 광고주별로 DB 에 Fernet 암호화 저장(`AUTOBID_ENC_KEY`, `app/crypto.py`, `app/naverad.py:12-17`).

### 2-2. 쓰는 엔드포인트
| 용도 | 엔드포인트·필드 | 근거 |
|---|---|---|
| 캠페인 목록 | `GET /ncc/campaigns` → `campaignTp == "SHOPPING"` | `gate.py:22-28`, `web.py:176-182` |
| 광고그룹 | `GET /ncc/adgroups?nccCampaignId=` · `GET /ncc/adgroups/{id}` · `PUT /ncc/adgroups/{id}?fields=bidAmt` | `naverad.py:20-26`, `gate.py:49-57` |
| 소재 | `GET /ncc/ads?nccAdgroupId=` · `GET /ncc/ads/{id}` → `adAttr.bidAmt`, `adAttr.useGroupBidAmt`, `referenceData.productId` | `naverad.py:45-57`, `web.py:186-198` |
| **소재 입찰가 변경** | `GET /ncc/ads/{id}` 로 받은 객체 전체에 `adAttr.bidAmt=새 값`, `adAttr.useGroupBidAmt=false` 를 넣어 `PUT /ncc/ads/{id}?fields=adAttr` | `naverad.py:29-42` |
| 순위별 예상가 | `POST /npla-estimate/average-position-bid/id` body `{device, items:[{key: nccAdId, position: 1..4}]}` → `estimate[].position/bid` | `estimator.py:26-43` |
| 진단 전용 | `/npla-estimate/exposure-minimum-bid/id`, `/npla-estimate/average-position-bid/keyword`, `/estimate/average-position-bid/keyword`, `GET /stats`(ids·fields·timeRange/datePreset) | `web.py:321-358, 399-430`, `stats.py:23-60`, `verify_phase0.py:128-145` |

- 명세 대조:
  - `PUT /api/ncc/ads/{adId}{?fields}` 의 `fields` enum 은 **`userLock`, `inspect` 둘뿐**이다(`ncc-heroes-ncc.json`). `adAttr` 는 enum 에 없다. 다만 `Ad.adAttr` 설명은 「Bid information… (Required if Shopping Ad) #required-update」다. ⇒ `fields=adAttr` 가 공식 방식인지는 **명세상 미확인**. 실제로 바뀐 적은 있다는 간접 근거: ③ 회신이 「실제 입찰가 변경은 2026-07-30 12:33 이 마지막」이라 했고(② `WORKLOG.md:3137`), 엔진은 PUT 이 200 일 때만 RAISE/LOWER 로 적는다(`engine.py:106-109`).
  - NPLA 예상가 명세: `type` = `id`(nccAdId) 또는 `product`, **한 번에 최대 200개 키**, 순위 범위 「PC 1~10, MOBILE 1~5」, 금액은 10원 단위 70~100,000(`estimate.json` `RequestWithPosition`·`KeyAndPosition`·`NPLAEstimateBidByPosition`). 코드 주석은 실측 오류 문구 「valid range is 1 to 4」라 1~4만 쓴다(`estimator.py:22-23`) — **명세와 실측이 다르다(어느 쪽이 지금 맞는지 미확인)**. autobid 는 소재 하나당 한 번씩 부른다(묶어 부르기 안 함).
- 2025-10-15 공지: 쇼핑몰 상품형 광고그룹에 네이버 자체 **전환목표 자동입찰**(`autobidStrategy.isAutobidActive`, 목표 `MAX_CONV_VALUE`)이 열렸고, 이 기능이 「광고그룹의 기본입찰가와 각 소재의 노출 여부, 실제 입찰가를 관리」한다(`_posts/2025-10-15-release-note.md`). autobid 코드에는 `autobidStrategy`·`systemBiddingType` 을 보는 곳이 **없다**(grep 0건).

### 2-3. 오류·재시도·속도 제한
- 429 만 재시도: 최대 3번, 1.5초·3.0초·4.5초 쉬고 다시(`naverad_client.py:68-70`). 요청 예외(네트워크)도 1·2·3초 쉬고 재시도(`:75-78`). 재시도마다 타임스탬프·서명을 새로 만든다(`:65`).
- 그 밖의 비정상 응답은 예외 없이 `(상태코드, 원문)` 을 돌려주고 호출부가 판단한다(`:71-74`). 네이버 오류 본문의 코드(예: 1016 「너무 많은 접속」, `NaverSA_API_Error_Code_MAP.md:15`)는 해석하지 않는다.
- 계정·IP 단위 속도 조절기, 동시 처리, 무작위 지연은 없다. 한 스레드가 순서대로 돈다(`engine.py:157-186`).
- 명세상 속도 제한은 「호출 대상 계정당」이고, 키워드 도구만 다른 기능의 1/5~1/6 + IP 단위 제한, 429 가 쏟아지면 5분 이상 멈추라는 안내가 있다(`_posts/2020-12-18-notice.md:11, 29-36`). autobid 의 짧은 재시도는 이 안내보다 훨씬 공격적이다.
- 사소한 결함: `post()` 가 받은 `params` 를 버린다(`naverad_client.py:87-88`). 지금 `post` 에 params 를 넘기는 호출부는 없다.

### 2-4. ③ 광고센터 어댑터(`backend/app/adapters/naver_searchad.py`)와 겹치는 부분
| 항목 | autobid | ③ 어댑터 |
|---|---|---|
| 서명 | 같은 식(`naverad_client.py:36-50`) | 같은 식(`naver_searchad.py:22-36`) — **완전 중복** |
| 오류 처리 | `(status, 원문)` 반환 · 429 재시도 | 비정상이면 `RuntimeError` · **429 재시도 없음**(`:39-44, 327-344`) |
| 입찰가 쓰기 | 쇼핑 **소재**(`adAttr`) · 광고그룹 `bidAmt` | 파워링크 **키워드** `PUT /ncc/keywords/{id}?fields=bidAmt`(`:357-363`) — 쇼핑 소재 쓰기 없음 |
| 안전 범위 | 대상별 상한 필수 · 최소 50원 · 하루 30회 · 30분 2배 차단 · **10원 단위 맞춤 없음** | 1회 ±50% · 최소 70원 · 절대 상한 100,000 · 기준값 없으면 3,000 · **10원 단위 맞춤**(`:282-308`) |
| 공통 조회 | `/ncc/campaigns`, `/ncc/adgroups`, `/stats` | 같음 + `/ncc/keywords` · `/ncc/channels` · 캠페인/그룹/키워드 생성(`:99-234, 385-405`) |
| 예상가 | NPLA 소재 축 | 없음 |
- 두 곳의 최소 입찰가가 다르다(50 vs 70). 쇼핑 소재 최소값은 명세에서 찾지 못했다(NPLA 예상가 응답 범위는 70~100,000) → **미확인**.

---

## 3) 데이터 저장·화면(`autobid/app`)

### 3-1. 저장
- SQLite(WAL), 운영 경로 `sqlite:////srv/autobid/data/autobid.db`, 도커 볼륨 `autobid-data`(`deploy-autobid.yml:45`, `docker-compose.autobid.yml:12`). MariaDB 전환은 2단계 계획만(`config.py:5`).
- 표 5개(`models.py`): `ab_account`(광고주명·customer_id·암호화 키 2개·status OK/KEY_ERROR/PAUSED·migration·gate_status·region·device) · `ab_target`(위 1-1) · `ab_rank_cache`(`검색어|기기|지역` 키로 에이전트 실측·예상가·통계 저장, 이름표로 구분 `est|…`, `stat|…`, `deep|…`) · `ab_bid_log`(모든 판단: 순위·목표·기존가·새 가격·동작·**사유 필수**) · `ab_engine_state`(1행: 비상 정지·사이클 번호·하트비트·세이프 모드).
- 스키마 변경은 `create_all` + `ALTER TABLE ADD COLUMN` 실패 무시 방식(`models.py:114-132`).
- 암호화 키 `AUTOBID_ENC_KEY` 는 러너 호스트 `~/.autobid/enc.key` 에 한 번 만들고 다시 만들지 않는다(다시 만들면 저장된 키를 못 푼다 — `deploy-autobid.yml:6-8, 31-36`).

### 3-2. 화면·API
- 관제 화면은 자체완결 HTML 한 장(`app/admin_page.py` 460줄): 요약 수치(자사 구동 계정·켜진 대상·목표 달성률·상한 도달·사이클) → 광고주 목록 → 광고주 상세(계정·대상·로그) · 대상 등록 시 쇼핑 캠페인›그룹›소재를 불러와 고르는 창(`web.py:167-204`) · 로그 엑셀/PDF 내려받기(`web.py:295-318`, `app/export.py`) · 비상 정지 · 이관 상태 선택 · 기기 전환.
- 대상 등록 창은 `nv_mid` 는 보내지만 `mall_name` 은 보내지 않는다(`admin_page.py:422-423`).
- 진단 API 5개: `estimate-test`, `ad-check`, `stat-test`, `rank-test`, `agent/script`(에이전트 파일 내려받기).
- ① 전산 쪽 계약 API(`web.py:556-616`): `GET /api/erp/clients`, `GET /api/erp/bid-status[?client_id=]`, 헤더 `X-Api-Key`(이름 `AUTOBID_ERP_API_KEY`), 상태 문자열 「유지·조정 중·상한 도달·확인 중·점검 중·중지·대기」가 계약. ① 이 이것을 매일 04:50 에 가져가 공유 대시보드 자동입찰 칸(P03)에 쓴다(① `AutobidClient.java:16-37`, `AutobidCacheRefreshScheduler.java:14`, 기본 주소 `https://logic.metainc.co.kr/autobid`).
- 에이전트 API: `GET /api/agent/keywords`, `POST /api/agent/slots`, 헤더 `X-Agent-Key`(이름 `AUTOBID_AGENT_KEY`)(`web.py:465-538`).

### 3-3. SSO·권한
- 전산이 `?sso=<토큰>` 으로 새 탭을 열면, autobid 가 그 토큰으로 ① `GET /api/employee-management/my-profile` 을 불러 본인 확인(`app/sso.py:26-57`) → Fernet 암호화 쿠키 12시간(`sso.py:30, 60-76`, `web.py:619-634`).
- 열람 = 전산 로그인 전 직원, 조작 = `autobidControlAccess == true`(① 이 「대표 ∥ 특수권한」으로 계산해 내려줌 — ① `EmployeeDetail.java:120`) 또는 권한명에 「최고관리자」/「대표」(구버전 대비)(`sso.py:52-56`). 쓰기 API 는 서버에서도 403(`web.py:43-47`).
- 비상 관리자: HTTP Basic(`AUTOBID_ADMIN_USER`/`AUTOBID_ADMIN_PASSWORD`, 비밀번호 없으면 전면 차단 `web.py:25-40`).
- ⚠️ 이것은 ① `my-profile` 의 추가 소비자다(①·② 계약 목록에는 ③ 광고센터·② 로직분석만 적혀 있다).

---

## 4) 운영 상태

| 시점 | 상태 | 근거 |
|---|---|---|
| 2026-07-28 | 대표 사양 확정 · 0단계 실증 | `README.md:7, 20` |
| 2026-07-28~30 | 1단계 MVP 구현 · 배포 · 시범 1호 계정 연결 · 순위 방식 4번 교체 | git 이력(9a5d2ac → 8e9d5a7), `estimator.py:3-6`, `stats.py:4-7` |
| 2026-07-30 | 코드 마지막 변경(에이전트 v9) | 커밋 8e9d5a7 |
| 2026-07-30 12:33 | **마지막 실제 입찰 변경** | ③ 회신(② `WORKLOG.md:3137`) |
| 2026-08-31 | 서버에 `autobid_engine`·`autobid_watchdog`·`autobid_web` 4주째 가동, `autobid_web` 만 `0.0.0.0:5070` 로 외부 공개 | ② `CLAUDE.md` 「실측 확정 (2026-08-31)」 |
| 2026-09-10 | ③ **상시 중단**: 컨테이너 3개 삭제 · 외부 포트 차단 · 이력·설정 백업 보존. 실규모 **키워드 2개 · 광고계정 2개**, 최근 3일 판정 684건 **전부 CAP**, 하루 추정 호출 600~1,700회 | ② `WORKLOG.md:3121-3139` |
| 2026-09-10 18:14 | 서버를 지운 뒤에도 맥미니 에이전트는 계속 보고 → 대표께 종료 절차서 전달 | ② `WORKLOG.md:3141-3155` |
| 2026-09-11 이후 | 공유 서버에 autobid 컨테이너 0개 | ② `WORKLOG.md:2725, 2845, 201, 45` |
| 2026-09-18 | `/autobid` 요청 현재 로그 1건(8/31 480건) — 에이전트는 사실상 멈춘 것으로 보임(추정) | ② `CLAUDE.md` 「정정 — 회선이 갈렸다」 |

- **목표 규모(1,000계정)는 한 번도 가지 않았다.** 대상 광고주 수 = 문서상 목표 1,000 / 실제 2.
- 2단계(분산 실행·공유 캐시·엑셀 일괄 등록)·3단계(파워링크)는 **미구현**(`README.md:21-23`).

### 알려진 결함(코드로 확인한 것)
1. **순위 매칭 키가 서로 모순된다.** `ranker.rank_of` 는 「검색 결과의 광고 추적 ID 는 우리 nccAdId 와 다른 체계」라며 nvMid → 몰명(부분 일치 포함) → adId 순으로 찾는다(`ranker.py:79-106`, 커밋 29773ef). 그런데 최종 에이전트 v9 는 광고 모듈 슬롯을 `nvMid=""`, `adId=nad-a001-02-…` 로 보내며 「우리 nccAdId 와 동일 형식」이라 적었다(`agent/autobid_agent.py:59, 183-199`). 둘 중 어느 쪽이 맞는지 실측 기록은 없다 → **미확인**. 결과적으로 `mall_name` 이 채워진 대상은 **정확한 소재 ID 보다 몰명 부분 일치가 먼저 걸린다**(같은 몰의 다른 광고·이름 일부만 같은 몰을 우리 것으로 볼 위험). 화면 등록 경로는 `mall_name` 을 안 보내 이 위험은 API 로 직접 넣은 대상에만 있다.
2. **6주 동안 상한에 붙은 채 아무도 몰랐다.** 판정 전부 CAP = 현재가가 상한이고 목표 순위에 못 미친(또는 순위 밖) 상태로 계속 보류. 감시견은 하트비트만 봐서 경보가 없었다. 원인(매칭 실패인지 실제 순위 부족인지)과 비용 영향은 **미확인**.
3. **인증 오류(401)로 계정이 KEY_ERROR 로 바뀌지 않는다.** 엔진은 예외 문자열에 「401」이 있을 때만 바꾸는데(`engine.py:177`), 네이버 401 은 예외가 아니라 `(401, 원문)` 으로 돌아와 FREEZE 로만 끝난다(`naverad.py:47-49`, `decide.py:33-34`).
4. **관문이 실제 쓰기 경로를 검증하지 않는다.** 관문은 광고그룹 `bidAmt` 만 바꿔 보고(`gate.py:49-59`), 엔진은 소재 `adAttr` 을 바꾼다(`engine.py:107`, `naverad.py:29-42`).
5. **PC 대상도 모바일 화면으로 잰다.** 에이전트는 쇼핑검색을 늘 모바일 세션으로 열고 그 광고 순위를 대상 기기와 무관하게 보고한다(`agent/autobid_agent.py:365-386`).
6. **지역 설정은 이름뿐.** `region` 은 저장 키에만 쓰이고 에이전트 요청에는 안 들어간다(에이전트는 사무실 위치에서 잰다 — `web.py:483-487`, `agent/autobid_agent.py:379`).
7. **목표 5~10위는 예상가 모드에서 4위로 바뀐다**(등록 1~10 허용 `web.py:224` ↔ `estimator.py:23`, `engine.py:80`) — 의도보다 비싸게 입찰.
8. **10원 단위를 맞추지 않는다.** 상한·step 이 임의 정수면 `min(예상가, 상한)` 결과가 10원 단위가 아닐 수 있다(`decide.py:52, 55`). 거절되는지는 **미확인**.
9. **배포가 연동 키를 지운다.** 배포 때마다 `.env` 를 새로 쓰는데 `AUTOBID_AGENT_KEY`·`AUTOBID_ERP_API_KEY` 가 빠져 있다(`deploy-autobid.yml:38-49`). 그대로면 재배포 직후 에이전트·① 연동이 503 이 된다(`web.py:466-467, 568-569`). 운영 중 어떻게 채웠는지 **미확인**.
10. **네이버 자체 자동입찰과 충돌을 확인하지 않는다**(2-2절). `useGroupBidAmt=false` 를 강제로 넣어 소재를 그룹 입찰가에서 떼어 낸다(`naverad.py:40`).
11. **규모를 감당하지 못한다(추정).** 대상 하나에 GET 1~2회 + 예상가 POST(캐시 480초) + 바꿀 때 GET+PUT. 한 스레드 순서 처리라 5,000건이면 10분 안에 끝나지 않는다. 계정당 순서대로 도는 구조·SQLite·단일 컨테이너라 800명 규모에는 설계를 새로 해야 한다.
12. `autobid_web` 이 외부에 열려 있었다(③ 가 9/10 닫음, ② `WORKLOG.md:3127`).

---

## 5) 새 자동운영 엔진과 겹치는 지점 — 두 프로그램이 같은 쇼핑 소재 입찰을 바꾸면

무엇이 깨지나(근거 포함):
1. **서로 덮어쓰며 번갈아 올린다.** autobid 는 10분마다 **절대값**을 쓴다(`naverad.py:20-42`). 새 엔진이 ROAS·A/B 기준으로 바꾼 값을 다음 사이클에 순위 기준으로 되돌린다. README 가 외부 프로그램(빗스토리)과의 동시 구동을 「서로 입찰가를 덮어써 번갈아 인상하는 충돌」이라며 금지한 바로 그 상황이다(`README.md:25-26`).
2. **autobid 안전장치가 거꾸로 작동한다.** 급등 차단·하루 인상 횟수는 autobid 자신의 로그만 센다(`engine.py:30-44`). 새 엔진의 변경은 보이지 않아 기준이 틀어지고, 새 엔진이 autobid 상한 위로 올린 값은 「상한 초과 → 상한까지 인하」 규칙이 즉시 끌어내린다(`decide.py:38-39`).
3. **A/B 시험이 오염된다.** 시험 중 한쪽 칸의 입찰가를 autobid 가 순위 목표로 바꾸면 시험 결과를 믿을 수 없다.
4. **그룹 입찰 구조가 몰래 바뀐다.** autobid 는 소재를 개별 입찰로 떼어 낸다(`useGroupBidAmt=false`). 새 엔진이 그룹 입찰가로 운영하면 그 소재만 따라오지 않는다.
5. **네이버 자체 자동입찰까지 셋이 싸운다.** 2025-10-15 기능이 켜진 그룹은 네이버가 소재 실제 입찰가를 관리한다.
6. **기록이 두 군데로 갈라진다.** `ab_bid_log` 와 새 엔진 로그 중 무엇이 진실인지 알 수 없다. ① P03 칸은 autobid 의 `/api/erp/bid-status` 를 보고 있다.
7. **이관 잠금이 autobid 안에만 있다.** `migration` 값은 autobid DB 에만 있어(`models.py:24-25`) 다른 프로그램이 볼 방법이 없다.

권고: **폐기(서버 부활 금지) + 코드 흡수. 공존은 하지 않는다.**
- 근거 ① 이미 멈췄다: 컨테이너 삭제·포트 차단·재가동 시 사전 공유 확약(② `WORKLOG.md:3125-3130`). 공존을 고민할 대상이 사실상 없다.
- 근거 ② 목표가 다르다: autobid 는 「순위」, 새 엔진은 「노출·클릭·전환·ROAS」. 순위 추종은 새 엔진의 목표 중 하나(노출)로 흡수하면 된다.
- 근거 ③ 순위 입력원이 새 방향과 맞지 않는다: 서버 긁기는 418 로 막혔고, 사무실 에이전트는 브라우저 위장으로 차단을 피한 방식이며 ② 수집기와 같은 회선을 나눠 쓰다 캡차 원인 후보가 됐다(② `CLAUDE.md` 8/31 실측, `WORKLOG.md:3113-3115`). 새 엔진은 공식 API(예상가·통계·보고서)만 쓰는 편이 안전하다.
- 근거 ④ 800명 규모 구조(분산·동시 처리·DB)가 없다(4절 11).
- 근거 ⑤ 권한·SSO·로그·안전 규칙은 쓸 만하다(6절).
- 함께 해야 할 일:
  - **한 소재·한 그룹에 쓰는 프로그램은 하나**라는 잠금 표를 새 엔진 쪽에 두고, 외부 프로그램·네이버 자체 자동입찰(`autobidStrategy.isAutobidActive`)·autobid 잔존 여부를 적용 전에 확인한다.
  - ① P03 계약(`/api/erp/clients`·`/api/erp/bid-status`, 필드명·상태 문자열)이 살아 있다. 새 엔진이 같은 모양으로 내주거나, 바꾸면 ① 에 사전 통지(계약 변경). 지금은 autobid 서버가 없어 ① 04:50 갱신이 실패하고 옛 스냅샷이 남아 있을 가능성이 크다(① `AutobidClient.java:26-27` 「실패 시 기존 스냅샷 보존」 · 실제 설정·결과 **미확인**).
  - 맥미니에서 에이전트가 완전히 꺼졌는지 확인(9/18 1건 이후 기록 미확인).
  - 새 엔진이 네이버 검색 결과를 긁는 순위 측정을 하게 되면 ② 에 착수 시점·호출량 사전 통지(② `CLAUDE.md` 「③ 광고센터와 같은 물리 자원」).
  - ③ 가 보존한 입찰 이력 백업(위치 **미확인**)은 2계정·2키워드라 모델 채점용 지난 데이터로서 가치는 작다.

---

## 6) 재사용할 수 있는 코드·교훈

### 코드
| 조각 | 쓸 곳 | 근거 |
|---|---|---|
| **쇼핑 소재 입찰가 읽기(그룹가 폴백)·쓰기(절대값)** | 새 엔진 1차(쇼핑)의 핵심 쓰기 경로. 세 저장소에서 유일 | `app/naverad.py:29-57` |
| `decide()` 순수 함수 + 시험 11개 | 「상한 있는 입찰가 조정(승인 없이 허용)」의 안전 층. 순서(상한 초과 강제 인하 → 데이터 없으면 동결 → 이동)가 그대로 쓸 만함 | `app/decide.py`, `tests/test_decide.py` |
| 엔진 패턴: 계정 격리·사이클 잠금·비상 정지·하트비트·운영 시간·급등 차단·「사유 필수」 로그 | 24시간 운영 루프 뼈대 | `app/engine.py`, `models.py:74-85` |
| 서명 클라이언트의 429 재시도·서명 재생성·`(status, 원문)` 반환 | ③ 어댑터에 없는 재시도를 보강할 때 참고(단, 공지 기준으로 대기 시간 늘리고 1016 처리 추가) | `naverad_client.py:53-79` |
| NPLA 순위별 예상가 호출·캐시 | 쇼핑 입찰 진입가 참고값. 명세상 한 번에 200개까지 묶어 부를 수 있음 | `app/estimator.py`, `estimate.json` |
| 계정 관문(읽기 + 쓰기 검증 후에만 활성) | 800명 온보딩 절차의 모양. 단 실제 쓰기 경로(`adAttr`)를 검증하도록 고치고, 라이브 입찰가를 잠깐 바꾸는 방식은 재검토 | `app/gate.py` |
| 이관 상태(EXTERNAL/OURS/STOPPED) | 「한 계정 한 운영자」 잠금 표의 원형 | `models.py:24-25`, `web.py:207-216` |
| 전산 SSO + 열람/조작 분리(서버 403 이중) | ③ 광고센터 권한 설계 참고 | `app/sso.py`, `web.py:25-47` |
| ① 계약 API + 계약 시험 7개 | P03 호환 유지 | `web.py:556-616`, `tests/test_erp_api.py` |
| 로그 엑셀/PDF | 광고주 보고용 | `app/export.py` |
| 암호화 키 「한 번 만들고 다시 만들지 않음」 배포 가드 | 광고주 키 보관 | `deploy-autobid.yml:6-8, 31-36` |

### 교훈
1. **돈을 움직이는 식별자는 실측으로 맞춰 본 뒤에만 쓴다.** 검색 결과 ID 와 우리 소재 ID 가 달라 「순위 밖」 오판 → 계속 인상 → 목표 3위인데 1위(커밋 29773ef). 그 뒤에도 매칭 키 판단이 두 번 뒤집혔다.
2. **평균 지표를 실시간 순위로 쓰지 않는다.** NPLA 예상가는 평균이라 과입찰을 불렀고, `/stats avgRnk` 는 모든 검색어 평균이었다(`stats.py:4-7`, 커밋 c321347).
3. **살아 있음 ≠ 일하고 있음.** 하트비트는 멀쩡했는데 6주 동안 전부 CAP. 새 엔진에는 「CAP·FREEZE 연속」, 「목표 대비 성과 이탈」, 「비용은 쓰는데 변경 0」 같은 결과 경보가 필요하다.
4. **차단을 위장으로 피하면 다른 섹션이 다친다.** 같은 사무실 회선의 ② 수집기가 캡차에 걸렸다(원인 기여도는 미확정).
5. **배포가 설정을 지우지 않게 한다**(4절 9).
6. **공개 포트는 처음부터 닫는다**(`0.0.0.0:5070`).
7. **네이버 쪽 규칙을 따라간다**: 10원 단위, 최소 입찰가(쇼핑 미확인), 순위 범위(명세 1~5/1~10 vs 실측 1~4), 계정당 속도 제한과 429 폭주 시 5분 이상 멈춤, 네이버 자체 자동입찰과의 충돌.
8. **외부 프로그램과 동시 구동 금지는 사람 절차가 아니라 시스템 잠금이어야 한다**(README 는 「사람 책임」이라고 적음 `web.py:209`).
9. **광고주 키를 하나씩 받아 두는 방식은 800명에 무겁다.** 대행사 관리 계정 API(`GET /manager-accounts`, `/manager-accounts/{no}/child-ad-accounts` — `atower.json`, 2025-09-01 신설 공지)로 하위 계정 목록은 얻을 수 있다. 다만 **한 대행사 키로 하위 계정의 캠페인·입찰을 조작할 수 있는지는 로컬 명세·공지에서 확인하지 못했다(미확인)**.


[핵심 사실]
- (확인) autobid 는 쇼핑 상품 소재(nccAdId) × 검색어마다 목표 광고 순위(기본 3위)를 정하고 10분마다 소재 입찰가를 올리고 내리는 순위 추종형 엔진이다. 전환·ROAS·예산은 판단에 들어가지 않는다. — autobid/app/models.py:38-61, app/decide.py:25-67, app/config.py:12, README.md:7-16
- (확인) 최종 순위 입력원은 사무실 맥미니 에이전트가 curl_cffi 브라우저 위장으로 네이버 쇼핑검색을 긁어 광고 모듈 소재 ID 순서를 보고하는 방식이고, 실측이 없거나 1,200초 넘게 오래되면 공식 NPLA 순위별 예상가(1~4위)로 되돌아간다. — agent/autobid_agent.py:102-128, 183-199, 314-397; app/engine.py:67-81; app/config.py:45; app/estimator.py:26-83
- (확인) 안전장치: 상한 필수, 최소 50원, 대상당 하루 인상 30회, 30분 창 2배 급등 차단, 절대값 설정, 전체 비상 정지, 계정 격리, 사이클 중복 방지, 전 대상 FREEZE 시 세이프 모드, 쓰기 검증 관문, 이관 상태 OURS 만 처리. — web.py:222-223; config.py:19-22; engine.py:30-44, 89-96, 131-193; naverad.py:20-42; gate.py:15-59; models.py:24-27
- (확인) 감시견은 하트비트가 15분 넘게 없을 때만 웹훅으로 알리고, 세이프 모드·CAP 연속·에이전트 실측 노후는 보지 않는다. — autobid/watchdog.py:16-18, 32-52
- (미확인) 소재 입찰가 변경은 GET /ncc/ads/{id} 객체 전체에 adAttr.bidAmt·useGroupBidAmt=false 를 넣어 PUT /ncc/ads/{id}?fields=adAttr 로 보낸다. 명세의 fields enum 은 userLock·inspect 뿐이라 adAttr 방식은 명세상 확인되지 않는다. — app/naverad.py:29-42; ncc-heroes-ncc.json PUT /api/ncc/ads/{adId}{?fields} fields enum; Ad.adAttr 설명 '#required-update'
- (추정) 실제 입찰 변경이 적용된 적은 있다(간접): ③ 회신이 마지막 실제 변경을 2026-07-30 12:33 으로 적었고, 엔진은 PUT 200 일 때만 RAISE/LOWER 로 기록한다. — logic-analysis docs/WORKLOG.md:3137; autobid/app/engine.py:106-109
- (확인) 네이버 API 클라이언트는 429 와 네트워크 예외만 최대 3회 짧게 재시도(1.5/3.0/4.5초)하고, 그 밖은 (상태, 원문) 반환이며 1016 등 본문 오류 코드는 해석하지 않는다. 속도 조절기·동시 처리 없음. — naverad_client.py:53-79; NaverSA_API_Error_Code_MAP.md:15,163; _posts/2020-12-18-notice.md:29-36
- (확인) 서명 방식은 ③ 광고센터 어댑터와 완전히 같고, ③ 어댑터는 429 재시도가 없으며 쇼핑 소재 입찰 쓰기(adAttr)·NPLA 예상가 코드가 없다. ① NaverSearchAdClient 에도 없다. — naverad_client.py:36-50 vs metainc-ad-dashboard backend/app/adapters/naver_searchad.py:22-36, 327-363; grep adAttr|npla|/ncc/ads 결과 ①·③ 0건
- (확인) ③ 는 2026-09-10 autobid 를 상시 중단했다(서버 컨테이너 3개 삭제·외부 포트 차단·이력 백업). 실규모는 광고계정 2개·키워드 2개였고 최근 3일 판정 684건이 전부 CAP, 마지막 실제 입찰 변경은 2026-07-30 12:33. — logic-analysis docs/WORKLOG.md:3121-3139 (③ 회신 인용)
- (추정) 2026-09-11 이후 공유 서버에 autobid 컨테이너는 0개이고, 9/18 현재 로그 기준 /autobid 요청은 1건으로 맥미니 에이전트도 사실상 멈춘 것으로 보인다. — logic-analysis docs/WORKLOG.md:45, 201, 2725, 2845; logic-analysis CLAUDE.md 「정정 — 회선이 갈렸다 (2026-09-18)」
- (미확인) 순위 매칭 키 판단이 코드 안에서 모순된다: ranker.rank_of 는 검색 결과 광고 ID≠nccAdId 라며 nvMid→몰명(부분일치)→adId 순으로 찾고, 에이전트 v9 는 광고 모듈 소재 ID 가 nccAdId 와 같다고 보고 nvMid 를 비워 보낸다. 어느 쪽이 맞는지 실측 기록 없음. — app/ranker.py:79-106; agent/autobid_agent.py:59, 183-199; 커밋 29773ef, 8e9d5a7
- (확인) 네이버 401 은 예외가 아니라 (401, 원문)으로 돌아와 계정이 KEY_ERROR 로 바뀌지 않고 FREEZE 로만 끝난다. — app/engine.py:177; app/naverad.py:47-49; app/decide.py:33-34
- (확인) 관문은 광고그룹 bidAmt 만 +10원 변경·원복으로 검증하고, 엔진이 실제로 쓰는 소재 adAttr 쓰기 경로는 검증하지 않는다. — app/gate.py:49-59 vs app/engine.py:107, app/naverad.py:29-42
- (확인) 배포 워크플로가 매번 .env 를 새로 쓰면서 AUTOBID_AGENT_KEY·AUTOBID_ERP_API_KEY 를 넣지 않아, 그대로면 재배포 직후 에이전트·① 연동 경로가 503 이 된다. — content-studio .github/workflows/deploy-autobid.yml:38-49; autobid/app/web.py:466-467, 568-569
- (확인) autobid 코드는 네이버 자체 쇼핑 전환목표 자동입찰(autobidStrategy, 2025-10-15)과 systemBiddingType 을 확인하지 않는다. 네이버 기능은 그룹 기본입찰가와 소재 실제 입찰가를 관리한다. — _posts/2025-10-15-release-note.md; ncc-heroes-ncc.json Adgroup.autobidStrategy; autobid 전체 grep 0건
- (추정) ① 전산은 매일 04:50 autobid 의 /api/erp/bid-status 를 가져가 공유 대시보드 P03 칸에 쓰고, 실패하면 기존 스냅샷을 보존한다. autobid 서버가 없어진 지금 옛 스냅샷이 남아 있을 가능성이 크다. — metainc-web-backend AutobidClient.java:16-37, 26-27; AutobidCacheRefreshScheduler.java:14; application.yml:155-161
- (확인) NPLA 순위별 예상가 명세는 한 번에 최대 200개 키, 순위 PC 1~10·MOBILE 1~5, 금액 10원 단위 70~100,000 인데, autobid 는 실측 오류 문구를 근거로 1~4위만 쓰고 소재 하나씩 부른다. — estimate.json RequestWithPosition·KeyAndPosition·NPLAEstimateBidByPosition; autobid/app/estimator.py:22-23, 26-43
- (미확인) 대행사 관리 계정 API 로 하위 광고계정 목록은 조회할 수 있으나, 한 대행사 키로 하위 계정의 입찰을 조작할 수 있는지는 로컬 명세에서 확인되지 않는다. — atower.json GET /api/manager-accounts, /api/manager-accounts/{no}/child-ad-accounts; _posts/2025-08-12-release-note1.md

[위험]
- 같은 쇼핑 소재·그룹에 두 프로그램(또는 네이버 자체 자동입찰·외부 프로그램)이 동시에 쓰면 절대값 덮어쓰기로 입찰가가 번갈아 오르고, autobid 의 '상한 초과 즉시 인하' 규칙이 새 엔진 변경을 끌어내리며, A/B 시험이 오염된다 — 시스템 차원의 '한 대상 한 운영자' 잠금이 필요하다.
- autobid 는 소재 입찰가를 쓸 때 useGroupBidAmt=false 를 강제해 소재를 그룹 입찰가에서 떼어 낸다 — 흡수 시 그대로 가져오면 그룹 입찰 운영과 충돌한다.
- PUT /ncc/ads?fields=adAttr 는 명세 enum 에 없는 방식이다 — 새 엔진이 그대로 쓰면 네이버 쪽 변경 때 조용히 깨질 수 있다(쓰기 뒤 재조회 검증 필수).
- 6주 동안 CAP 에 붙은 채 경보가 없었던 사례처럼 하트비트 감시만으로는 '살아 있지만 돈만 쓰는' 상태를 못 잡는다 — 새 엔진은 결과 경보가 필요하다.
- 최소 입찰가(50 vs 70)·10원 단위·NPLA 순위 범위(명세 1~5/1~10 vs 실측 1~4)가 코드마다 다르다 — 잘못 쓰면 요청 거절 또는 의도보다 비싼 입찰.
- 사무실 에이전트식 순위 긁기를 되살리면 ② 로직분석 수집기와 회선·캡차 문제가 재발할 수 있고, ② 에 사전 통지 의무가 있다.
- ① P03(공유 대시보드 자동입찰 칸)이 autobid 계약 API 에 묶여 있다 — 새 엔진이 계약 모양을 바꾸면 ① 사전 통지가 필요하고, 지금은 옛 스냅샷이 노출되고 있을 수 있다.
- autobid 식 '광고주 키를 하나씩 받아 암호화 보관' 은 800명 규모에서 운영 부담·유출 면적이 크다.
- 429 대응이 공지 권고(폭주 시 5분 이상 중단)보다 공격적이고 1016 처리가 없다 — 800계정 동시 운영 시 계정별 속도 제한에 걸릴 위험.
- 배포 워크플로가 .env 를 덮어써 연동 키를 지우는 구조 — 같은 방식을 복사하면 재배포마다 연동이 끊긴다.

[미확인]
- 검색 결과 광고 모듈의 소재 ID(nad-a001-02-…)가 우리 API 의 nccAdId 와 실제로 같은지 — 코드 주석끼리 모순, 실측 기록 없음.
- PUT /ncc/ads/{id}?fields=adAttr 가 네이버 공식 지원 방식인지(명세 enum 에는 없음).
- 쇼핑 상품 소재의 최소 입찰가(50원인지 70원인지)와 10원 단위가 아닌 값을 보냈을 때 거절되는지.
- NPLA 예상가 순위 범위가 지금 1~4인지 명세의 MOBILE 1~5 / PC 1~10 인지.
- 6주간 전부 CAP 이었던 원인(매칭 실패인지 실제 순위 부족인지)과 그 기간 비용 영향.
- 운영 중 AUTOBID_AGENT_KEY·AUTOBID_ERP_API_KEY 를 .env 에 어떻게 채웠는지(배포 워크플로에는 없음).
- ③ 가 보존했다는 autobid 입찰 이력·설정 백업의 위치와 내용.
- 맥미니 에이전트가 9/18 이후 완전히 종료됐는지.
- ① 운영 서버에 AUTOBID_ERP_API_KEY 가 설정돼 있어 04:50 갱신이 실제로 호출·실패 중인지, P03 에 어떤 스냅샷이 남아 있는지.
- 한 대행사(관리 계정) API 키로 하위 광고계정 800명의 캠페인·입찰을 X-Customer 만 바꿔 조작할 수 있는지.
- 시범 계정 2개가 지금 네이버 콘솔에서 어떤 입찰가(상한 고정 상태 유지 여부)로 남아 있는지.