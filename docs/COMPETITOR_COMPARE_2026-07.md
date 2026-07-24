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
