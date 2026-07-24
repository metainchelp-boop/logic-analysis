# 광고주 vs 경쟁사 비교 분석 (2026-07) — 연속성 메모리

> 운영자 요청(2026-07-23): 광고주 등록처럼 경쟁사도 등록해 1:1 비교, 차이·따라가야 할 것 도출.
> 시안 확정(A안: 업체 상세 안 경쟁사 슬롯) + 1차 항목 + **AI 대결 코칭** 포함. 경쟁사 입력=광고주와 동일(이름+키워드+HTML).
> 작업 브랜치: `claude/competitor-compare`.

## 설계

- **A안**: 업체(광고주) 상세 안에 「경쟁사」 슬롯. 경쟁사도 **광고주와 동일 분석 파이프라인 재사용**(이름+키워드+HTML, URL은 HTML 자동추출).
- 경쟁사는 `clients.role='competitor'` + `competitor_of=<광고주 id>` 로 저장 → **광고주 리스트·자동추적·정산·가망·계약동기화에서 완전 격리**, 비교 화면에서만 사용.

## 구현

### BE (커밋 f06fd14)
- `clients` 마이그레이션 #4: `role`(advertiser/competitor) + `competitor_of`(광고주 링크).
- 격리: `my-clients`·`registered-clients`·`get_all_clients`(clients.py)·스케줄러 자동분석(×2)·계약단계 동기화 쿼리에 `COALESCE(role,'advertiser')='advertiser'` 필터.
- `quick-register`: `role`+`competitor_of` 옵션 지원. 연결 광고주 존재 검증, 이름충돌 분리(경쟁사가 동명 광고주를 안 덮음), 재등록 갱신.
- 신규 엔드포인트(`/api/cd`):
  - `GET /{id}/competitors` — 광고주에 연결된 경쟁사 목록(최근 분석 요약).
  - `GET /compare?advertiser_id=&competitor_id=` — 양측 최근 분석 1건씩(교차접근 차단: 경쟁사가 그 광고주 소속인지 검증).
  - `POST /compare-coaching` — 광고주 vs 경쟁사 격차 요약을 Claude(`chat._get_claude_client`)에 넣어 "이기려면" 전략 브리핑. `CLAUDE_API_KEY` 미설정 시 `available:false` 친화 안내.
- 검증: 격리 SQLite — 리스트 격리·목록·최신분석 선택·교차접근 차단·자동분석 제외·이름충돌 분리 7/7 PASS.

### FE
- **신규 `CompetitorCompareSection.jsx`** (+ `CompetitorRadar`): 업체 상세 안 렌더.
  - 경쟁사 슬롯(목록·비교 버튼·삭제 ✕·"경쟁사 등록" 버튼).
  - 비교: 대진표 + 핵심지표 6종(순위·판매가·리뷰수·평점·종합진입점수·상세품질, 저장 분석에서 **방어적 추출**·없으면 '집계 없음') + 우열/격차 + 종합 레이더(5축 SVG) + 키워드 커버리지 갭(연관 키워드 차집합) + 따라가야 할 것(열세 지표 격차순 자동) + 강점 + **AI 대결 코칭 카드**(/compare-coaching).
- 경쟁사 등록 흐름: `App.competitorContext` 상태 → 업체 상세 '경쟁사 등록' → 분석 화면 전환(배너 표시) → 분석 후 `SaveToClientSection` 저장 시 `role=competitor`+`competitor_of` 로 quick-register(경쟁사 모드에선 항상 신규 경쟁사로, 광고주에 안 붙음). 저장 성공 시 모드 해제.
- 배선: App(상태·핸들러·배너·prop) → ClientDashboard(슬롯 렌더·onRegisterCompetitor) → AnalysisResults(prop 전달) → SaveToClientSection(경쟁사 저장).
- 무손실: 경쟁사 미등록/데이터 없음이면 슬롯만 표시(기존 화면 무영향). 저장 분석 구조 편차는 방어적 추출로 흡수.
- 검증: 헤드리스 크로미움 렌더 14/14 PASS(슬롯·목록·비교표·순위·레이더 6폴리곤·따라가야 할 것·키워드 갭·AI 코칭 호출·summary 격차 포함·응답 렌더).

## 상태

- [x] BE + FE 구현·검증, 번들 재생성
- [ ] 운영자 승인("배포하자" + "FE까지 완성 후 통째로 배포") → main 머지 → VPS blue-green(스키마 마이그레이션 자동, DDL은 ADD COLUMN 뿐 무중단)
- 후속(2·3차 후보): 경쟁사 감시 알림(카톡) · 가격/프로모션 캘린더 · 다중 경쟁사 벤치마크 · 키워드별 순위 매트릭스(경쟁사 다중 키워드 분석) · 부정리뷰 불만 추출.

## 영업사원 경쟁사 등록 + 30일 자동삭제 (2026-07-23, 운영자 지시)

- 지시: "영업사원은 등록하되 30일 뒤 자동 삭제." 배경: 영업사원=viewer라 기존엔 업체 등록 자체가 불가(관리팀만). 경쟁사 입력 동선을 열되 데이터 누적 방지.
- 정책: **영업사원(viewer)은 경쟁사만 등록 가능**(광고주 신규 등록은 계속 관리팀). **영업사원이 등록한 경쟁사는 30일 뒤 자동 삭제**(관리팀 등록분은 영구).
- BE:
  - `clients.expires_at` 마이그레이션(#5, NULL=영구).
  - `quick-register` 권한 완화: 의존성 `require_register_permission`→`get_current_user`. 내부에서 광고주 등록은 manager/superadmin만(403), 경쟁사는 전원 허용. viewer가 등록한 경쟁사에 `expires_at=+30d`(재등록 시 연장). 관리팀 경쟁사는 NULL.
  - `cleanup_expired_competitors()` — 만료 경쟁사 + 분석기록 삭제. 스케줄러 `_run_daily_analysis`(09:00) 시작 시 호출.
  - `list_competitors` 응답에 `expires_at`·`days_left` 추가.
- FE:
  - `SaveToClientSection`: '⚔️ 경쟁사로 저장' 탭 신설(연결 광고주 드롭다운+경쟁사명). viewer(`allowCompetitorOnly`)는 이 탭만 노출·트리거 문구도 경쟁사, "30일 후 자동 삭제" 안내. quick-register에 role/competitor_of 전달.
  - `AnalysisResults`: 저장 섹션을 viewer에게도 렌더(경쟁사 전용, `allowCompetitorOnly=role==='viewer'`).
  - `CompetitorCompareSection`: 경쟁사 목록에 '⏳ N일 후 삭제' 배지(days_left).
- 검증: BE 격리 SQL TTL 5/5(만료만 삭제·잔존·분석기록 동반삭제·days_left) + FE 렌더 9/9(경쟁사 전용·드롭다운·30일 안내·탭 숨김·role/competitor_of/name·배지) PASS.

## 영업사원 본인 등록분 분리 (2026-07-23, 운영자 지시)

- 지시: "영업사원도 본인이 등록한 것만 따로 구분해서 영업자료로 볼 수 있게 영역을 나누면 될 거 같아."
- BE: `list_competitors` — viewer는 `created_by=본인`만 반환(관리팀=전체). 각 항목 `mine` 플래그. `compare`·`compare-coaching`도 viewer는 본인 등록 경쟁사만 접근(403 가드).
- FE: `CompetitorCompareSection` — viewer면 슬롯 제목 "경쟁사 비교 (내 영업자료)"·"내가 등록한 경쟁사만 표시" + 관리팀 화면엔 본인 등록분에 '내 등록' 배지. `ClientDashboard`에서 `isViewer` 전달.
- 검증: 스코핑 SQL — viewer9/viewer8 각자 본인 것만·관리팀 전체 PASS.

## 실사용 보완 (2026-07-24) — 스토어명 자동채움 + 경쟁사 진입 안내

- 신고: 판매페이지 확장 분석 시 커버 '광고주/스토어'가 "-"로 비어있고, 경쟁사 등록 위치가 안 보임.
- 스토어명 자동채움: `AnalysisResults` — companyName 미지정(확장 자동분석)이면 `advertiserReport.product_info.store_name` → `analysisData.targetProductInfo.store_name` → 상품 URL 스마트스토어 슬러그 순으로 커버(`_displayCompany`) 자동 표기. `SaveToClientSection`에 `defaultName` 전달 → 저장 모달 업체명/경쟁사명 기본값 자동 채움.
- 경쟁사 진입 발견성: 저장 카드에 안내 추가 — 관리팀 "이 업체 저장 후 업체관리→경쟁사 등록", viewer "경쟁사로 저장하면 업체관리에서 비교". (경쟁사 비교 UI 자체는 업체관리에 있음 — 발견성만 보완)
- 검증: FE 렌더 4/4 PASS(실측 스토어명·URL 슬러그 폴백·안내 노출).

## 영업팀 전용 흐름 재설계 + 데이터 3건 보완 (2026-07-24, 운영자 "웅 이렇게 해줘")

- 지시(요약): 영업사원 계정은 **완전 개인 모드** — 관리팀 광고주는 아예 안 보이게, **영업 대상(prospect)을 먼저 분석·저장**하고 거기에 상위노출 경쟁사를 붙여 비교. 본인 등록분만·각 30일. (시안 `영업팀-전용-흐름-시안.html` 승인)
- 새 role `prospect`(영업 대상) 도입 — 광고주/경쟁사와 별개. 광고주 목록·자동분석·계약동기화(모두 `role='advertiser'` 필터)에서 자연 제외.
- **BE(`client_dashboard.py`)**:
  - `quick_register`: `role in (advertiser|prospect|competitor)`. 광고주 등록=관리팀만, prospect·competitor=전원. viewer의 prospect·competitor는 +30일 TTL. 경쟁사 앵커 = advertiser **또는** prospect.
  - `my-clients`·`registered-clients`: viewer는 **본인 등록 prospect만**(관리팀 광고주 완전 비노출). `_COLS`에 role·expires_at 추가, `days_left` 계산.
  - `_verify_client_access`: viewer는 **본인 등록분만**(기존 '전체 읽기' → 개인화). 관리팀 광고주 접근 차단.
  - `cleanup_expired_competitors`: prospect까지 확장 + 만료 prospect에 매달린 경쟁사 동반 삭제(고아 방지). 스케줄러 호출부 변경 없음(함수명 유지).
  - 공통 헬퍼 `_days_left`.
- **FE**:
  - `SaveToClientSection` 재설계: viewer·컨텍스트 없음 → **"영업 대상으로 저장"**(role=prospect, 드롭다운 없음). 상세 '경쟁사 등록' 진입(competitorContext) → **경쟁사 고정 저장**(앵커 고정, 드롭다운 없음). 관리팀은 기존 탭 흐름 유지. prop `allowCompetitorOnly`→`isViewer`.
  - `CompetitorCompareSection`: viewer는 앵커 라벨 '광고주'→**'영업 대상'**(대진표·비교표·AI 코칭 문구).
  - `ClientDashboard`: viewer 목록 제목 '내 영업 대상', 빈 상태·플레이스홀더 문구 영업 대상, 행에 '⏳ N일 후 자동 삭제' 배지.
  - `App` 경쟁사 등록 배너: viewer면 '영업 대상 …의 경쟁사로 저장'.
- **데이터 3건 보완**:
  1. `DatalabGrowthSection`: 비수기(`reliable===false`)에도 성장률 **숫자 표시 + '참고' 배지**(기존 '—'로 안 보이던 문제).
  2. 키워드별 노출 순위 속도: 후보 12→8, 워커 5→6, 예산 12→18s(`main.py`), FE 타임아웃 25→32s(`RankTrackingSection`) — 예산 내 완주율↑·스피너 단축.
  3. 판매량 추정 일치화: 공통 헬퍼 `window.reviewAnchorEstimate`(utils.js, 작성률 11.6%·12개월). `SalesEstimationSection`·`MarketRevenueSection`이 **동일 자사 월판매/월매출** 표시. 시장 규모는 '상위 N개 합산'으로 스코프 명확화(자사 1개 매출과 혼동 방지).
- 검증: BE 격리 SQL 4/4(viewer prospect 스코핑·앵커 advertiser|prospect·cleanup 동반삭제·days_left) + FE 헤드리스 렌더(prospect/고정경쟁사/영업자료 라벨·성장률 참고배지·두 섹션 앵커 동일값 718건/17,950,000원) PASS.
- 상태: `claude/sales-flow` 브랜치 stack. **배포 대기(운영자 "배포하자")** — main 푸시 시 blue-green 무중단.
