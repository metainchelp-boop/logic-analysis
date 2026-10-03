# 이관 잔액 정렬·현재 목록 합계·검색·전산 자격 팝업 배포 준비

## 승인과 현재 상태

대표 승인 범위는 이관 화면의 잔액순 정렬, 현재 표시 목록의 잔액 합계, 실관리 대조 검색, 전산의 기존 네이버 자격 팝업으로 바로 이동하는 기능이다. 이후 전산 보안 의존성 갱신·재검증과 전산 선행 배포 후 관제 배포까지 승인했다. 이 문서는 제어기 핀 보완의 로컬 준비 증거이며 운영 적용 완료 기록이 아니다.

- 현재 운영 제품: `e132a4b6ebba40ca58fb4de3cd3a66a3c910b218`.
- 대상 관제 제품: `01344b145d0b679a6ee730d7fa4b5990278dd654`.
- 준비 기준 제어 커밋: `cc756981723995762e69589a4b0bc5fab2fb55e5`.
- 주 작업자가 확인한 [사전 상태 37113678073](https://github.com/metainchelp-boop/logic-analysis/actions/runs/37113678073), 작업 `111176257778`: `status.ok=true`, 기존 운영 제품·기준값 불변. 이 문서 작성 과정에서 운영에 직접 접속하거나 쓰지 않았다.
- 전산 보안 갱신의 필수 CI, 선행 배포와 기존 팝업 확인이 완료되기 전 관제 `preview-code-prepare` / `preview-code-apply`를 실행하지 않는다.

## 고정 값과 봉인 출처

| 항목 | 값 |
| --- | --- |
| 기존 압축 SHA-256 | `94c0e58e700b73c4459edadeb97b34c3268a8c8483fe4107c178b9423444ae29` |
| 대상 Linux 압축 SHA-256 | `0faf3865ec14802d96bf51fa376961064196105e52578f24c93e56430120693d` |
| 기존·대상 Store SHA-256 | `d33bc6315eac7b020f17ffc87a19c920a1a307b3bf9799f921759cb60a1c3e2e` |
| 호스트 기준 SHA-256 | `5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76` |
| Linux 봉인 실행 | [37117023116](https://github.com/metainchelp-boop/metainc-ad-dashboard/actions/runs/37117023116) |
| 봉인 도구 커밋 | `c43baaa8af3ccebd7eaa565754c3b9575d57e3e7` |

대상 압축 지문은 주 작업자가 제공한 Linux 봉인 영수증 값이다. 읽기 전용 실행 메타데이터 조회로 위 실행의 `completed / success`, `workflow_dispatch`, 브랜치 `codex/naver-account-first-20261002`, 도구 커밋과 `.github/workflows/naver-runtime-tests.yml` 경로를 확인했다. 이번 제어기 보완 담당은 암호문을 해독하거나 전체 봉인 영수증을 독립 재취득하지 않았다. 배포 담당은 별도의 봉인 검증에서 불변 도구·워크플로·제품 원문 및 암호문·artifact 지문을 함께 대조해야 한다. Mac gzip 재압축 값으로 Linux 영수증을 대체하지 않는다. 인증정보·서명 URL은 이 문서에 기록하지 않는다.

## 실제 아카이브 차이와 제한

봉인 대상과 동일한 소스 경로의 기존·대상 `git archive`를 메모리에서 비교했다. 변경은 아래 5개만이며 신규 1개, 삭제 0개, 파일 모드 변경 0개다.

- 화면: `backend/naver_page/app.css`, `backend/naver_page/app.js`, `backend/naver_page/index.html`.
- 시험: `naver_engine/tests/test_screen.py`, `naver_engine/tests/test_transfer_balance_screen.py` (신규).

제어기의 허용 목록은 이 화면 3개·시험 2개로만 좁혔다. Store, 서버, scope, view_sync 등 이전 릴리스의 허용 경로는 제외했다. 신규 시험과 이름이 인접한 모듈, 자격정보 파일, 심볼릭 링크, 삭제, 모드 변경은 허용하지 않는다. Store 지문을 가상으로 다시 고정하더라도 Store 변경을 이번 화면 전용 범위로 수용하지 않는 회귀 시험을 포함한다.

기존·대상 Store는 바이트 단위로 같으며 schema11 SQL 50개와 이관 계약이 동일하다. 제어기의 최상위 함수 20개 AST도 준비 기준 커밋과 동일하다. 승인·권한·bootstrap·호스트 기준·DB 조건·실패 복구의 검증 및 실행 함수는 변경하지 않았다. 별도의 초기 bootstrap 업그레이드 핀도 변경하지 않았다.

## 검증과 다음 게이트

아래 로컬 명령으로 preview 전체 회귀 197개가 통과했다. 실제 DB·광고·계정 연결 쓰기는 실행하지 않았다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s backend/tests -p 'test_naver_preview_*.py' -q
git diff --check
```

1. 주 작업자가 핀·허용 목록·시험·문서 diff를 검토한 뒤 제어 커밋과 원격 반영을 별도로 수행한다.
2. 전산 보안 갱신 CI 및 선행 운영 배포·기존 팝업의 업체/권한/닫기/늦은 응답 검증을 완료한다.
3. 정확한 Linux 봉인 패키지와 고정 제어 커밋으로 준비한다. 준비 성공은 서비스 교체 성공과 구분한다.
4. 승인된 적용 후 별도 상태 조회에서 제품·schema11·일관 DB 사본·비로그인 401·금지 업무 쓰기 403·기존 앱/nginx/bootstrap 불변을 확인하고 실제 이관 화면을 검증한다.

실패 복구는 기존 알고리즘대로 실패 DB/WAL을 별도 보존하고 전환 직전 일관 사본과 기존 제품을 함께 복원한다. 전환 뒤의 새 기록이 활성 DB에 그대로 남는다고 표현하지 않는다. 이 로컬 준비에는 커밋·push·배포 dispatch·서비스 시작·운영 수정이 없으며, 전체 수집 완료나 실제 자격 저장 성공도 주장하지 않는다. 이후 실제 준비·적용·독립 조회 결과는 별도 증거와 함께 추가한다.
