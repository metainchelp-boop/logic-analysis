# 명시 광고계정 번호의 이름 충돌 확인 보완

2026-10-07 · 개발 검증 완료 · 이 문서는 운영 배포 증거가 아닙니다.

## 문제와 결과

전산에 유일한 광고계정 번호가 등록되어 있어도, 다른 업체의 동일·유사 이름 후보만으로 대표의 연결 확인이 차단됐습니다. 계정 이름이 다른 업체를 가리키는 경우에는 같은 업체·계정 쌍이 차단행과 이름 후보행으로 중복 표시됐습니다.

현재 전체 catalog를 보는 대표에게만 명시 번호 검토 경로를 제공합니다. 이름 후보와 실제 번호·확정 주장을 구분하고, 이름 근거만 충돌하면 원본 광고계정 번호를 정확히 입력해 한 건씩 확인할 수 있습니다. 이름이 같은 경우에도 이 경로는 일괄 확인에 포함하지 않습니다. 동일 쌍의 중복 후보만 제거하고 다른 계정 후보는 보존합니다.

## 유지하는 보호 조건

- 실제 번호 중복, 광고계정 번호와 고객번호의 불일치, 다른 업체의 현재·밀린 미취소 확정은 계속 차단합니다.
- 숨김·목록 밖 업체의 번호 주장도 검사하며, 유효한 중복 행으로 충돌 검사를 피할 수 없습니다.
- 이름만 있는 후보, 구형 고객번호만 있는 자료, 직원 권한 및 범위를 좁힌 대표 조회에는 새 검토 경로를 적용하지 않습니다.
- 원천·조직·담당 범위의 신선도와 쓰기 트랜잭션 안의 재검사를 유지합니다.
- 자동 매칭, 기존 연결 확인, 계약 단계·점검 주기·관리 포함 정책, API 형태와 DB 구조는 변경하지 않습니다.

제품 변경은 `naver_engine/catalog_links.py`에 한정합니다. 회귀 시험은 `naver_engine/tests/test_catalog_links.py`에 합성 자료로 추가했습니다.

## 검증

최소 재현 세 사례는 수정 전 모두 실패했고 수정 후 모두 통과했습니다. 다른 업체의 이름만 바꾸는 비교에서도 이름 후보와 실제 주장 혼합이 차단 원인임을 확인했습니다.

Linux/Python 3.12.14/SQLite 3.46.1에서 다음 범위를 외부 통신 없는 비루트 컨테이너로 실행했습니다. **143개 통과, 실패·건너뜀 0개**이며 실제 Chromium 화면 시험 두 개를 포함합니다.

```sh
PYTHONPATH=backend:. NAVER_SCREEN_REQUIRE_BROWSER=1 python -m unittest \
  naver_engine.tests.test_catalog_links \
  backend.tests.test_naver_auto_matching \
  naver_engine.tests.test_monitoring_identity_policy \
  naver_engine.tests.test_auto_identity_memory \
  naver_engine.tests.test_account_catalog.CatalogReadTest \
  naver_engine.tests.test_owner_verification \
  naver_engine.tests.test_guardrails \
  naver_engine.tests.test_web.LinksTest.test_name_holder_counts \
  naver_engine.tests.test_web.LinksTest.test_name_candidate_held_by_out_of_scope_prospect \
  naver_engine.tests.test_web.LinksTest.test_preview_of_account_held_elsewhere_refused \
  naver_engine.tests.test_catalog_links_screen
```

macOS/Python 3.14.4에서는 기존 파일 저장소의 초기화 실패가 있어 전체 통과로 계산하지 않았습니다. 위 Linux 시험에서 해당 범위를 다시 검증했습니다. 처음 컨테이너로 옮긴 자료의 macOS 메타데이터 파일은 시험 묶음에서 제외한 뒤 전체 검사를 통과했습니다. 독립 소스 검토와 `git diff --check`도 통과했습니다.

## 운영 후속

이번 검증은 합성 자료로 수행했습니다. 제품 배포 후에는 최신 이관·전산 목록으로 각 보류 건을 다시 평가하고, 허용되는 행만 기존 단건 원본 번호 확인 경로로 확정해야 합니다. 기존 확정이나 다른 업체의 번호 충돌이 발견되면 계속 보류합니다. 목록 조회 시간 초과와 수집 완료 여부는 별도 문제이며 이 수정으로 해결됐다고 판단하지 않습니다.
