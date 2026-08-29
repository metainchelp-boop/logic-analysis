# 광고센터 네이버 특화 재편 — 설계 (A안 확정)

> 2026-08-29 대표 확정. 목적: 멀티채널로 난잡해진 광고센터를 **네이버 광고 특화 운영 도구**로 픽스.
> 흐름 = **특이사항 점검 → 진행현황 파악 → AI 진단 → AI 광고세팅(승인 후 실행)**.
> 원칙: ①본질로 재집중(기능 추가 아님) ②기능 손실 금지(숨김·코드 보존) ③화면 숨김 ≠ 연동 해제.

## 0. 확정된 결정

| 항목 | 결정 |
|---|---|
| 범위 | 네이버 생태계 전체: 검색광고(API) + GFA(엑셀) + 커머스 |
| 유지 채널 | + 쿠팡애즈, 토스애즈 (커머스 라인) |
| 숨김 채널 | 카카오·메타·당근·모비온·유튜브·메타체험단 — **UI만 숨김, 코드·데이터·수집 보존** |
| 허브 | 광고주 1줄 = 연동상태 + 성과 + 특이사항 통합 |
| AI 세팅 | **제안 → 담당자 승인 → 실행**. 범위: 입찰가·키워드 추가/제외·캠페인/그룹 on-off·예산 (소재 생성은 P2 — 네이버 심사 필요) |
| 특이사항 | 자동감지 + 담당자 메모 |

## 1. 정보구조(IA) — 네비 8→6

```
[운영]
 🎯 네이버 관제      ← 신규 허브 = 홈 (기존 home 대체)
 💰 소진 관리        ← 스펜딩 + 월별 기록 + 엑셀 업로드 3탭 통합
[관리]
 ➕ 광고주 등록      ← register 유지 (허브에서도 진입)
 📋 진행현황·승인    ← status 유지 (삭제요청 승인·라이프사이클)
 📄 AI 리포트        ← report 유지 (매월 발송 규칙)
 ⚙️ 설정             ← settings 유지
```
- **광고주 상세(작업실)** = 허브 행 클릭 진입(네비 항목 아님). 기존 s-dashboard 개편: 네이버 성과 + 특이사항·메모 + AI 진단 + AI 세팅.
- 네비 숨김(화면·함수·백엔드 전부 보존): home, dashboard(네비만), channel, campaign(상세의 "새 캠페인 설계" 버튼으로 진입 유지), insights, team, learn.
- ⚠️ route() 해시맵(L734)의 openInsights·openLearn **식별자 참조 유지**(함수 삭제 시 라우팅 전체 붕괴). 맵 엔트리 제거는 go('home') 폴백으로 안전.
- ⚠️ s-campaign→`/insights/{cid}/proposal-success` 호출, collector→`run_due_reports` — **insights 백엔드 라우터 유지 필수**.

## 2. 채널 숨김 (조사 검증 완료)

- `CHANNELS` L629~641에 `hidden:true` + `const VISIBLE_CHANNELS = CHANNELS.filter(c=>!c.hidden)` 파생.
- 치환 지점(전수): 순회 L800(cardHtml)·818(openForm)·975(collectChannels)·1906(upRender) + 분모 카운트 L780·801·804·1020·1150·1374·1782.
- `chMeta`(L1311)는 CHANNELS.find **유지**(숨긴 채널의 기존 데이터 lookup).
- 파생 상수 정리: CONNECT_CHANNELS(L864)→네이버3종, ADS_KEYS(L1310)→coupang·gfa(+toss upload), CAMPAIGN_CHANNELS(L1567)→네이버 중심, TESTABLE(L821), bulk-ch option(L1886), UP_EXTRA(L1905)→naver_gfa·coupang_ads·toss_ads.
- GUIDES 본문 채널명 하드코딩 3곳 수정(channel L2349, upload L2415~, register L2400).
- **자격증명 절대 disconnect 금지** — `/team/spend-by-month`가 `_gather_perf` 실시간 조회 기반이라 소진 집계에서 빠짐. 숨긴 채널 수집(collector)도 그대로 돈다(스냅샷 유지).
- 과거 월별기록은 channels_json 동결이라 무영향.

## 3. 🎯 네이버 관제 허브

**백엔드**: `GET /team/overview` 확장(최소변경 — 이미 광고주별 스냅샷 KPI+alerts 집계).
추가 필드(광고주별):
- `connect`: `connected`(네이버 채널 connected≥1) / `link_sent`(유효 ConnectLink 미제출) / `link_expired` / `not_requested` / `error`(신규)
  - 판정 근거: ChannelCredential.status + ConnectLink(submit_count, expires_at 문자열비교 — `_now_kst_iso()` 방식)
  - `error`: ChannelCredential.status에 `"error"` 값 추가, collector 실패 시 기록 (1줄 확장)
- `note`: 최신 담당자 메모 1건(ActivityLog type="note")
- `naver`: 검색광고 캠페인 수·상태 요약(스냅샷 기반)

**프론트**: s-home 대체 신규 렌더. 상단 KPI(전체/연동완료/미연동/특이사항) + 필터(연동상태·특이사항·담당자[admin]) + 광고주 표(이름|연동배지|이번달 소진|ROAS|특이사항 배지|메모|담당자|[상세][링크재발송]). 행 클릭 → 상세 작업실.

## 4. 특이사항 (자동 + 메모)

- 자동감지: `_channel_anomalies`(L1349~) 기존 4규칙(노출0·ROAS급락·소진급증·체험단리뷰율) 유지 + 추가:
  - `소진 0`(전일 스냅샷 대비, 스냅샷 규칙 → _channel_anomalies 내)
  - `수집 끊김`(connected인데 48h 스냅샷 없음 — 광고주 단위 규칙 → /alerts·overview 루프, L321 신선도 패턴 재사용)
  - `링크 만료`(재발송 필요 — 광고주 단위)
  - 잔액 부족은 스냅샷에 잔액 필드가 없어 **P2**(어댑터 확장 필요).
- 메모: **ActivityLog type="note"** (새 테이블 없음). `POST /clients/{id}/notes` 신설(require_editor) → 허브·상세에 최신 1건 + 이력. 작성자·시각은 기존 필드.

## 5. AI 진단 + AI 세팅 (상세 작업실)

### 데이터 전제 (신규 — 키워드 단위 파이프라인)
현 스냅샷은 캠페인 합계뿐. 어댑터에 추가:
- `GET /ncc/adgroups?nccCampaignId=` , `GET /ncc/keywords?nccAdgroupId=` (조회)
- 키워드 단위 `/stats` (ids=키워드ID 배열, 기존 get_stats 재사용)
- 서명: 기존 `_signature`/`_headers` 재사용 — **method가 서명에 포함됨을 검증 완료**(L23), uri는 쿼리 제외 path만.

### AI 진단
- `ai_insights._call + _parse_json` 재사용, SYSTEM 프롬프트 신규: 캠페인·키워드 성과 입력 → 진단문(잘된 것/문제/원인/권고) JSON.
- 기존 keyword-advice 룰(임계값)은 진단 카드에 병기(빠른 신호), Claude 진단은 서술.

### AI 세팅 — "제안 → 승인 → 실행"
**기존 CampaignProposal 파이프라인(draft→dry-run→confirm→실행→기록)을 레퍼런스로 복제.**
- 모델 신규: `SetupProposal(id, client_id, status: draft|applied|discarded, items_json, summary, created_by, created_at, applied_by, applied_at, apply_result_json)`
- items_json 항목: `{type: bid|kw_off|kw_on|kw_add|group_onoff|camp_onoff|budget, target_id, target_name, current, proposed, why, checked}`
- 엔드포인트:
  - `POST /clients/{id}/setup-proposals` — 키워드 단위 성과 수집 → Claude 제안 생성(require_editor)
  - `POST /setup-proposals/{pid}/apply` — body: 체크된 항목 ids, `confirm=true` 필수. 담당자(require_editor, visible 범위) 실행. 항목별 어댑터 호출 → 항목별 성공/실패 결과 기록 + ActivityLog.
- 어댑터 쓰기 함수 신규(naver_searchad.py):
  - `update_keyword_bids([{id, bidAmt}])` — PUT /ncc/keywords/{id}?fields=bidAmt (또는 배열 PUT)
  - `toggle_keywords/adgroups/campaigns(ids, userLock)` — PUT ?fields=userLock
  - `add_keywords(adgroup_id, [{keyword, bidAmt}])` — POST /ncc/keywords
  - `update_budget(entity, id, dailyBudget)` — PUT ?fields=budget
- **안전 가드**: ①입찰가 변경폭 ±50% 클램프·최소 70원 ②예산 변경폭 ±50% 클램프 ③confirm 필수 ④전 항목 ActivityLog ⑤실패 항목은 결과에 명시(부분 성공 허용) ⑥키워드 추가는 항상 userLock=true(꺼진 상태)로 생성 후 담당자가 네이버에서 확인.
- P2: 소재 생성(POST /ncc/ads — 네이버 심사), 잔액 조회, 예약 실행.

## 6. 💰 소진 관리 통합

s-spending + s-records + s-upload를 탭 3개로 한 화면(신규 라우트 `money`). 기존 open* 함수·백엔드 그대로, 래퍼 화면만 신규. 업로드 탭 채널: naver_gfa·coupang_ads·toss_ads(+수동입력).

## 7. 구현 순서 (배포 단위)

1. **P1-a 정리**: 채널 숨김 + 네비 6개 + 소진관리 통합 + GUIDES 갱신 (프론트 위주, 즉시 배포 가능)
2. **P1-b 허브**: /team/overview 확장(connect 판정·note·error status) + 관제 화면 + 메모 API + 특이사항 신규 규칙
3. **P1-c AI 세팅**: 키워드 파이프라인 → 진단 → SetupProposal 제안·승인·실행 (어댑터 쓰기 4종)
4. **P2**: 소재 생성·잔액·자동화 수위 상향

각 단계 배포 전 E2E 검증(기존 verify 하니스), 시안 컨펌 후 착수.
