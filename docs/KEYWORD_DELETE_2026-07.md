# 순위추적 키워드 개별 삭제 (2026-07-23) — 연속성 메모리

> 건의: 이예은(2026-07-22) — "7개 등록 키워드 중 3개만 추적, 4개 삭제 등 여러 서브키워드 변경 등록하며 추이 확인에 용이". 운영자 시안 확인 후 구현 승인.

## 배경 / 사실확인

- 순위추적은 상품별 키워드가 `tracked_keywords`에 개별 행으로 저장(키워드마다 `rankings`·`competitor_snapshots` 독립 이력). 구조상 개별 삭제 가능.
- 그러나 기존엔 **키워드 "추가"만 있고 "개별 삭제"가 없었음** — 삭제는 `DELETE /api/products/{id}`(상품 전체, 모든 키워드·이력 삭제)뿐.
- → 3개만 남기려면 상품을 통째로 지우고 재등록해야 했고, **남길 키워드의 순위 이력까지 소실**되는 불편. 서브키워드 교체 운용에 치명적.

## 구현 [FE+BE]

**[BE]**
- `database.py`: `get_keyword_product_and_count(keyword_id)`(소속 상품 ID + 총 키워드 수), `delete_tracked_keyword(keyword_id)`(자식 행 명시 삭제 후 키워드 삭제, 단일 커밋. FK=ON이라 CASCADE도 동작하나 방어적 명시).
- `main.py`: `DELETE /api/keywords/{keyword_id}` — `_verify_keyword_ownership`(404/403) 재사용 + **마지막 1개 키워드 삭제 불가 가드**(count≤1 → 400, 키워드 0개 상품 방지). 남기는 키워드 이력은 유지.

**[FE]** `RankTrackingSection.jsx`
- `handleDeleteKeyword(keywordId, keyword, siblingCount)` + `renderKeywordDeleteCell` 추가.
- 키워드 표 두 곳 모두에 '관리' 열 + ✕ 버튼: ① 상품별 카드 뷰(`p.keywords`), ② 전체 스캔 뷰 펼침 상세(`kws`).
- **canEdit(편집 권한)에만 노출**(viewer 미표시), **마지막 1개는 ✕ 비활성**(회색), 확인창("이 키워드의 순위 이력도 함께 삭제됩니다. 상품과 다른 키워드는 유지"), 삭제 후 `refreshProducts()`.
- 셀·버튼 `stopPropagation`으로 행 펼침 토글과 분리. 차트 펼침 행 colSpan은 canEdit 시 +1.
- 기존 상품 삭제·키워드 추가·순위 추이 차트 전부 무변경.

## 검증

- BE: 격리 SQLite 테스트 — 키워드 1개 삭제 시 해당 이력만 삭제·나머지 키워드 이력 온전·마지막 1개 count=1 감지·없는 키워드 None.
- FE: 헤드리스 크로미움 렌더 6/6 PASS — ✕ 3개(키워드3), confirm 호출, DELETE /keywords/10 호출, refreshProducts 호출, 성공 토스트, 마지막 1개 disabled. viewer(canEdit=false) → ✕ 미표시.
- `py_compile` OK, 번들 재생성.

## 상태

- [x] 구현 + 검증
- [ ] PR(draft) → 운영자 "배포하자" 대기 (배포 = main 머지 → VPS blue-green 무중단, DDL 없음)
- 이예은 건의 게시판 회신은 운영자가 진행.
