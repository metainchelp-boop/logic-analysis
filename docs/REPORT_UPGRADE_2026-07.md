# 보고서 고도화 · 디자인 개선 (2026-07) — 연속성 메모리 (append-only)

> 작업 브랜치: `claude/vigilant-brown-854eeg` · 운영자 지시: "전체 진행해. 단, 절대로 어떠한 경우에라도 무언가 기능을 상실하거나 유실되거나 해서는 안되." (2026-07-23)
> 시안(고정 링크): https://claude.ai/code/artifact/b04eefa2-d9e3-4a92-81a6-e1aaa6a23e9a — 개선·수정 시 같은 아티팩트에 재배포(새 URL 금지)

## 배경

실전달본(콤부차 보고서 2026-07-20 내보내기, 345KB)과 렌더 코드 4관점(정보구조·시각디자인·설득력·내보내기) 교차 분석 →
치명 결함 3건(내부 UI 유출·AI 로딩 박제·모바일 viewport 사장) + 개선 12건 로드맵 확정. 상세 근거는 시안 아티팩트 참조.

## 구현 내역 (2026-07-23, 12건 전체)

| # | 항목 | 구현 위치 |
|---|---|---|
| 1 | 내보내기 캡처 통일(내부 UI 유출 차단) | **신규 `frontend/js/report-capture.js`** — 수동 내보내기(`ReportSection.jsx`)·업체 자동저장/저장 보고서 다운로드(`App.jsx captureAutoReportHtml`)가 같은 빌더 사용. 제거 목록 단일 출처(`REMOVE_SELECTORS`): sec-report/notify/save-client + anchor-nav(-wrap) + topbar + **.footer(버전 문자열)** + .no-export |
| 2 | AI 로딩 박제 차단 | `AiFeedbackAllSection.jsx` 숨김 상태 마커(`.ai-state` data-state=loading/done/idle) + 로딩 문구 `.no-export`(이중 방어). 빌더가 미완료 시 "별도 전달" 카드로 대체, 수동 내보내기는 확인창으로 대기 유도 |
| 3 | 모바일 정상화 | 내보내기 viewport `width=1200` → `device-width`(빌더 일원화). `.rpt-grid/.rpt-flex` 640px 1열 규칙을 report-theme.css + 빌더 주입 CSS 양쪽에 정의 |
| 4 | 배지 3색+범례+결측 중립 | report-theme.css `.b-dl`(#e0f2fe/#0284c7)·`.b-n` 신설. 데이터랩 6개 섹션 배지 `✅ 데이터랩`→`📊 데이터랩`. `SummaryCardsSection` 결측 KPI('-'·0) → 회색 '집계 없음'. `.report-legend`를 report-main 내부(=전달본 포함)에 추가, 좌측 목차 범례에도 데이터랩 추가 |
| 5 | 표지 통일+담당자 CTA | 빌더 표지: 보라 #6C5CE7 폐기 → 인디고 #4f46e5→#7c3aed + METAINC 로고타입 + 담당자명(SSO 사용자). 이중 푸터 → 단일(담당·고객센터 02-2082-2005·면책 1줄), "자동 생성" 문구·버전 제거. 마무리 CTA 카드(#1e293b) 추가 |
| 6 | 히어로 요약 | `SummaryCardsSection` — 종합 진입 점수(6장에 묻힘)를 최상단 승격: 결론 1문장+점수 게이지(conic)+액션 Top3(전략 심각도순, #sec-strategy 앵커)+등급 배지. 점수·순위 없으면 히어로 생략(기존 화면 그대로 — 무손실 폴백) |
| 7 | 유효성 게이트 | `DatalabWeekdaySection` peakIndex≤0 → 미렌더. `DatalabDemographicsSection` 성별 격차<10%p → "차이 없음" 분기·연령 전값 0 → 데이터 없음 처리. `DatalabCategoryKeywordsSection` 빈쪽 1줄 안내(빈 tbody 방지). `ReviewTextAnalysisSection` 표본<10건 "참고용" 표기 |
| 8 | 무관 키워드 필터 | `RelatedKeywordsSection` — 연관도(분석 키워드 포함) 우선 → 검색량순, 기본 30개+`전체 보기`(no-export), "상품명에 넣을 후보 5" 칩 카드. keyword 미전달 시 기존 동작 그대로(폴백) |
| 9 | 정적 목차 | 빌더가 실렌더된 `.report-divider` 기준 목차 카드 생성(표지 아래, 색 도트+정적 앵커 rpt-part-N). 빈 anchor-nav-wrap 제거 |
| 10 | 경쟁 진단 재배치 | `EntryStrategySection` `part` prop 분할: 'competition'(상품헤더+비교표+격차, 3장 경쟁사 비교표 뒤) / 'strategy'(점수+전략+권고, 6장). 미지정 시 기존 전체 렌더(하위 호환). 내부 "1./2./3." 번호 제거, 격차 카드 '가격 조정 필요'→해결책 병기 |
| 11 | 마이크로카피 | SEO ①~④ 결번 제거(4파일). `GoldenKeywordCard` `.golden-card` 스타일 연결+점수 /100+대표1개·상표 주의 문구. CPC 용어 풀이 |
| 12 | 차트·인쇄 품질 | `ChartCanvas` devicePixelRatio≥2(내보내기 2배 해상도). 빌더: 원격 이미지 onerror 자동 숨김(깨진 아이콘 방지). report-theme.css `@page A4 12mm` + print에서 스크롤 박스 해제·표 축소 |

### 부수 수정 (같은 브랜치)

- **`frontend/build.js` — babel preset `runtime:'classic', development:false` 명시.** babel 8 기본이 automatic(ESM import 생성)으로 바뀌어 로컬 babel 8 환경에서 실행 불가 번들이 나오는 문제 차단. ⚠️ 배포 CI(`deploy.yml`)도 `npm install @babel/core @babel/preset-react` 무버전 설치라 npm 태그가 8로 바뀌는 순간 같은 사고 예정이었음 — 이 수정으로 CI도 안전.
  - 참고: 저장소에 커밋된 구 번들(`app.1c326c497552.js` 등)은 이미 ESM 오염 상태였으나, **배포는 CI가 매번 재빌드**하므로 라이브는 무영향(라이브 확인: `app.00e13bc1e2f8.js`, 오염 0·확장 브리지·bid-estimate 포함 정상).
- **확장 v1.0.1** (`extension/`): 브리지 재시도 30초 → 유효시간 10분(2초 간격) + 로그인 화면 "수집물 대기 중" 안내 배너. 운영자 신고(로그인 화면에서 수신 안 됨) 대응. zip 전달 완료.

## 검증 (2026-07-23, 헤드리스 크로미움)

- 캡처 파이프라인 DOM 테스트 29/29 PASS — 내부 UI 문구 미포함·AI 대체·목차/CTA/푸터 생성·화면 DOM 무손상·AI done 시 섹션 유지.
- 렌더 스모크 테스트 33/33 PASS — 수정 컴포넌트 17케이스 렌더(히어로/폴백/part 분할/게이트/정렬) + 내용 검증 16건.
- `node frontend/build.js` 성공(66파일, jsx-dev-runtime 0건).
- 테스트 하네스: 세션 스크래치 `capture-test/`(저장소 미포함).

## 상태

- [x] 12건 구현 + 번들 재생성 + 검증
- [ ] PR (draft) → 운영자 "배포하자" 승인 대기 (배포 = main 머지 → VPS blue-green, 스왑 순간 수 초 502 정상)
- [ ] 배포 후 실검증: 실제 키워드 1회 분석 → ①화면 정상 ②HTML 내보내기에서 내부 문구·AI 로딩 부재 ③폰 열람 1열 ④자동저장 보고서 동일 확인

## 배포 기록 (2026-07-23)

- PR #97 머지(squash 252bae2) → deploy run #294 success(02:41~02:43Z) → 헬스 200 ·
  라이브 번들 `app.a771d2a179ae.js` 마커 검증(ReportCapture·b-dl·AI 대체·SSO 폴백 포함, ESM 오염 0).
- 확장 v1.1.0(전산 SSO 자동 로그인) zip 운영자 전달. v1.1.1: FAB 위치 우하단 → **우측 세로 중앙**
  (다른 섹션 확장이 우하단 사용 — 운영자 확정. 좌측 중앙 지시 후 우측 중앙으로 정정됨).
- 운영자 실검증 대기: 확장 자동 로그인 · 보고서 내보내기(내부 문구/AI 로딩 부재) · 폰 1열.
