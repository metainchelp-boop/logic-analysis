# 키워드 순위 탭 분리 (2026-08-04) — 연속성 메모리

## 배경 (대표 지시)
- 스토어 분석 하단의 「키워드별 노출 순위」를 **독립 탭**으로 분리 — "같이 정보를 공유하고 연동되더라도 보는 공간은 철저하게 분리".
- 계층은 **키워드가 아니라 광고주 업체가 최상위** — 업체 목록 → 업체 클릭 → 그 업체의 키워드 추적 현황.
- 시안성은 아이템스카우트/셀러랩스 수준 지향. 시안 v2 확정("시안 좋다 이대로 진행해").
- 시안 고정 링크: https://claude.ai/code/artifact/09fd87cb-abcf-4060-b098-1af3471cafd2

## 1차 구현 (배포 완료 — main bf9e3c3, deploy run #323 success 2026-08-04 12:32 KST)
- **BE** `backend/client_dashboard.py`:
  - `GET /api/cd/rank-overview` — 업체별 롤업(최근 8일 client_rank_history 집계: keywords/exposed/top10/up/down/last_checked/top_keywords[:2] + totals). 스코핑은 my_clients 동일(viewer=본인 prospect / manager=본인+무소유 advertiser / admin=전체).
  - `GET /api/cd/{client_id}/rank-board` — 키워드별 최신 순위·page·prev_rank·delta(양수=상승)·volume(client_analyses 최신 summaryCards.totalVolume)·series(8일). 정렬=노출(순위순) 먼저.
- **FE**:
  - `KeywordRankPage.jsx` 신설 — 랜딩=업체 목록(KPI 5장·검색·주의/상승/하락 필터) → 상세=키워드 보드(Δ배지·7일 스파크라인·상태 칩). 하단에 기존 `RankTrackingSection` 재마운트(상품 등록·수동 재확인·노출 분석 무손실). products는 자체 로드(`/products`).
  - `RankCheckCard.jsx` 신설 — 스토어 분석 잔류 콤팩트 카드. **1회성 조회(/rank/check)를 계속 수행해 `setRankCheckResult`로 올림**(진입 전략·시장 매출 4개 소비처 무회귀). 「탭에서 상세 보기」 클릭 시 sessionStorage `logic_rank_ctx`(searchedKeyword/searchedProductUrl/cachedProductName/relatedKeywords) 기록 → KeywordRankPage가 1회 소비.
  - `TopBar.jsx` 「📊 키워드 순위」 탭(스토어 분석 다음), `App.jsx` validPages 'rank'+페이지 블록+`handleOpenRankTab`, `AnalysisResults.jsx` :303 교체(onOpenRankTab prop), TOC 앵커 `sec-rank`는 카드가 승계.
- **부수 수정**: bce091d 병합 때 `index.html`/`index.bundle.html`에 **충돌 마커가 커밋돼 있던 것 발견·정리**(main은 무영향, 브랜치만). 배포 전 헤드리스 실렌더에서 적발.
- 검증: BE 단위 테스트(Δ부호·검색량 매핑·정렬)·헤드리스 크롬 실렌더(목록→상세→왕복, JS 오류 0)·회귀 게이트 기준선 동일(8/10)·배포 후 라이브 번들에 신규 컴포넌트 포함+`/api/cd/rank-overview` 401(=라우트 활성) 확인.
- 이 배포에 **타 세션 SEO 최적화 탭(7f8640f~1a4841e, PR #63)이 동승** — 같은 지정 브랜치 stack이었고 대표 「배포하자」로 일괄 승인. PR #63은 머지 처리됨.

## 다음 차수 (대표 지시 대기)
- 2차 디자인 확산: 대시보드 → 로직 분석 → 플레이스 순으로 같은 톤 통일.
- 키워드 보드 고도화: 정렬/필터(검색량순·급락만)·기간 선택(7일→30일)·미노출 연속일 배지.
