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

## 직원 오류신고 2건 대응 (2026-08-04 저녁, 이예은)
1. **「보고서에서 키워드 순위 노출 칸 사라짐」** — 탭 분리 1차의 회귀. RankCheckCard(콤팩트 카드)가
   `/rank/keyword-exposure` 노출 분석 블록(요약 카드·추천 키워드·노출/미노출 칩)까지 대체해버림.
   수정: `RankTrackingSection`에 `analysisOnly` 모드 신설(노출 분석·1회성 조회만 렌더, 추적 목록·등록 폼 숨김)
   → 스토어 분석에 재마운트(보고서 원상 복구), RankCheckCard 폐기. 분리 원칙 재정의:
   **탭으로 옮기는 것은 '추적 현황 열람·관리'뿐, 분석 결과(노출 분석)는 보고서 소속.**
2. **「추적 상품 업체명에 스토어명 대신 URL 아이디(슬러그) 저장」** — 쇼핑 API 종료(7/31) 후
   등록 시 스토어명 확보(1차 키워드 검색→2차 스토어 검색→3차 페이지 방문)가 전부 실패하면
   슬러그가 그대로 남는 문제. 수정 3중:
   - `database.heal_tracked_product_info` — 순위 체크가 SERP에서 상품을 찾은 순간 매칭 아이템의
     실제 mallName으로 store_name 보정(슬러그/빈 값일 때만, 정상 이름 불변). 호출 지점 =
     초기 체크(`run_initial_rank_check`) + 매일 08:00 배치(scheduler 홈탭 저장 루프).
   - `/api/products` GET 백그라운드 보정 조건 확대(상품명 빈 값 → +스토어명 빈 값/슬러그) +
     쓰기 가드(해소된 실제 이름일 때만 교체).
   - 등록 예방: `ProductAddRequest.store_name_hint`(선택) — 분석 화면의 검증된 실제 스토어명
     (`_realStoreName`)을 TrackRegisterButton이 동봉, 서버가 슬러그 대체.
   기존 슬러그 데이터는 별도 마이그레이션 없이 **다음 목록 조회·다음 아침 배치에서 자가치유**.

## ⚠️ 세션 인프라 사고 기록 (2026-08-04)
- 원격 세션 컨테이너 재시작 시 로컬 저장소가 **첫 커밋 이전 스냅샷으로 복원**되는 일 발생
  (원격·라이브는 무손상). 낡은 트리 위에 새 수정이 얹혀 빌드하면 이미 배포된 기능이 번들에서
  소실될 뻔함 → **작업 재개 시 반드시 `git fetch` 후 `git log origin/<branch>` 대조**로
  로컬·원격 정합부터 확인할 것. 복구 절차: 이번 턴 수정 파일만 사본 보관 → `checkout -B <branch>
  origin/main` → 무충돌 파일 복사·겹침 파일 재적용 → 재빌드·재검증.
