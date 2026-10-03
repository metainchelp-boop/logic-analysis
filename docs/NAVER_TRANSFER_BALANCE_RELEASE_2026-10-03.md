# 이관 잔액 정렬·현재 목록 합계·검색·전산 자격 팝업 배포 준비

## 승인과 현재 상태

대표 승인 범위는 이관 화면의 잔액순 정렬, 현재 표시 목록의 잔액 합계, 실관리 대조 검색, 전산의 기존 네이버 자격 팝업으로 바로 이동하는 기능이다. 이후 전산 보안 의존성 갱신·재검증과 전산 선행 배포 후 관제 배포까지 승인했다. 이 문서는 제어기 핀 보완의 로컬 준비 증거와 후속 실행 기록을 구분하며, 관제 운영 적용 완료 기록이 아니다.

- 현재 운영 제품: `e132a4b6ebba40ca58fb4de3cd3a66a3c910b218`.
- 대상 관제 제품: `01344b145d0b679a6ee730d7fa4b5990278dd654`.
- 최초 핀 보완의 비교 기준 제어 커밋: `cc756981723995762e69589a4b0bc5fab2fb55e5`.
- 최신 진단 제어 커밋: `c1747d36054e34d548b2c5adc9698defd2206d1e`. 문서 갱신 시점 관제 적용 횟수는 0이며, 최초 준비의 실제 실패 원인은 아직 확정되지 않았다.
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

기존·대상 Store는 바이트 단위로 같으며 schema11 SQL 50개와 이관 계약이 동일하다. **최초 핀·허용 목록 보완 시점**에는 제어기의 최상위 함수 20개 AST가 비교 기준 커밋과 동일했고 승인·권한·bootstrap·호스트 기준·DB 조건·실패 복구의 검증 및 실행 함수도 변경하지 않았다. 별도의 초기 bootstrap 업그레이드 핀은 변경하지 않았다. 이후 아래 진단 보완으로 `naver_preview_release.command`의 실패 처리와 `naver_preview_code_upgrade.prepare`의 단계 표시는 변경되었으므로, 함수 AST 전체 불변을 최신 진단 커밋에 그대로 적용하지 않는다.

## 최초 로컬 검증과 배포 순서

최초 핀 보완 시 아래 로컬 명령으로 preview 전체 회귀 197개가 통과했다. 실제 DB·광고·계정 연결 쓰기는 실행하지 않았다. 진단 보완 후의 추가 시험 결과는 아래 후속 기록과 구분한다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s backend/tests -p 'test_naver_preview_*.py' -q
git diff --check
```

1. 주 작업자가 핀·허용 목록·시험·문서 diff를 검토한 뒤 제어 커밋과 원격 반영을 별도로 수행한다.
2. 전산 보안 갱신 CI 및 선행 운영 배포·기존 팝업 확인을 완료한다. 업체/권한/닫기/늦은 응답의 합성 회귀와 실제 운영 화면 확인은 서로 다른 증거로 기록한다.
3. 정확한 Linux 봉인 패키지와 고정 제어 커밋으로 준비한다. 준비 성공은 서비스 교체 성공과 구분한다.
4. 승인된 적용 후 별도 상태 조회에서 제품·schema11·일관 DB 사본·비로그인 401·금지 업무 쓰기 403·기존 앱/nginx/bootstrap 불변을 확인하고 실제 이관 화면을 검증한다.

실패 복구는 기존 알고리즘대로 실패 DB/WAL을 별도 보존하고 전환 직전 일관 사본과 기존 제품을 함께 복원한다. 전환 뒤의 새 기록이 활성 DB에 그대로 남는다고 표현하지 않는다. 최초 로컬 핀 보완 담당은 커밋·push·배포 dispatch·서비스 시작·운영 수정을 수행하지 않았으며 이후 원격 실행은 주 작업자가 진행했다. 전체 수집 완료나 실제 자격 저장 성공도 주장하지 않는다.

## 후속 실행 기록 — 최초 준비 실패와 제한 진단

아래 원격 실행·운영 화면 결과는 주 작업자가 확인하여 제공한 증거이며, 문서 편집 담당자가 운영 서버에 재접속하여 재현한 결과가 아니다.

- 전산 보안 갱신 [CI 37117501513](https://github.com/metainchelp-boop/metainc-web-frontend/actions/runs/37117501513) 및 [배포 37117667052](https://github.com/metainchelp-boop/metainc-web-frontend/actions/runs/37117667052) 성공과 운영의 기존 네이버 자격 팝업 확인이 완료되었다. 실제 팝업 확인은 자격 저장·업무 데이터 변경 성공을 뜻하지 않는다.
- 최초 관제 [준비 37117890361](https://github.com/metainchelp-boop/logic-analysis/actions/runs/37117890361), 작업 `111188128590`, 제어 `9d48af00c8b7e9325390d81397a0f4c9d260323b`: `ok=false`, `stage=code_build_relay`, `error_kind=RuntimeError`, `error_code=COMMAND_FAILED`, `created_paths=[]`. 적용은 실행하지 않았고 기존 `e132a4b` 운영은 유지되었다. 기존 단계 표시는 relay 이미지 빌드와 직후 compose 검증을 구분하지 않았으므로 이 결과만으로 빌드 실패라고 단정할 수 없다. 또한 `created_paths=[]`는 새 이미지 캐시나 준비 소스까지 전혀 생기지 않았다는 증거가 아니다.
- 읽기 전용 [조회 37118024948](https://github.com/metainchelp-boop/logic-analysis/actions/runs/37118024948)의 `AD_DEPLOY_PREFLIGHT`: `/srv` 여유 `7,685,791,744`바이트(약 7.7 GB), 사용 가능한 메모리 `1,729,644` KiB, 기존 컨테이너 불변·호스트 기준 동일. 이 수치만으로 Docker 저장소/inode/할당량 등 모든 용량 원인을 배제하거나 네트워크 원인을 확정하지 않는다.
- 진단 제어 `48bea9e` 및 권한 거절 표현 보완 `c1747d36054e34d548b2c5adc9698defd2206d1e`: 정확한 Docker build 인자·제품 태그·Dockerfile·소스 경로가 일치하는 실패만 `DOCKER_BUILD_DENIED`, `TLS`, `RATE`, `DISK`, `NETWORK`, `STEP`, `UNKNOWN`의 고정 접미사로 분류한다. 실제 오류 코드는 모두 `DOCKER_BUILD_` 접두사를 가진다. stdout/stderr의 제한된 끝부분을 메모리에서만 검사하며 원문·키·URL을 출력하거나 저장하지 않는다. 권한 거절을 우선 분리하며 거절 시 우회하지 않고 중단한다. 성공 동작, timeout, 환경, 다른 명령의 `COMMAND_FAILED`는 유지한다.
- 같은 진단 변경에서 engine/relay 빌드 직후 `code_config_engine` / `code_config_relay` 단계를 설정하여 compose 검증 실패와 구분했다. 패키지·암호문·소스·중단된 준비 트리·기존 자격·호스트 기준 검증, 승인, DB, 적용·복구 동작은 약화하지 않았다. 운영환경 변경·이미지 삭제·네트워크 우회는 실행하지 않았다.
- 진단의 민감 stdout/stderr·정확한 명령 제한·성공/timeout 불변·미분류·실패 단계 회귀를 포함한 preview 전체 **202개** 통과. release 시험은 `python -O`에서도 **13개** 통과했다. 주 작업자의 최종 커밋 재실행과 독립 보안 검토도 통과했다.

### 20:05:05 KST 동일 패키지 재준비 결과

[재준비 37118463924](https://github.com/metainchelp-boop/logic-analysis/actions/runs/37118463924), 작업 `111189737998`는 고정 제어 `c1747d36054e34d548b2c5adc9698defd2206d1e`에서 `stage=code_config_relay`, `error_code=COMMAND_FAILED`로 실패했다. 기존 `verify_interrupted_source`가 봉인 소스·override를 검증하는 경로를 유지했고, 단계상 engine·relay **두 이미지 빌드가 모두 통과했음**을 확인했다. 이 시점의 `code_config_relay`는 relay의 `docker compose ... config --quiet`와 그 뒤 격리 엔진의 `check-config` 실행을 모두 포함하므로 어느 명령에서 거절됐는지는 아직 구분하지 못한다. compose 구성 충돌·엔진 설정 거절 등은 가설이며 실제 원인으로 기록하지 않는다.

주 작업자가 다음 제한 진단으로 `check-config` 단계를 추가 분리하고 정확한 구성 검증 명령에 한해 고정 오류 분류를 보완할 예정이다. 이 문서 편집 담당은 코드에 추가 변경하지 않는다. 재준비 성공·실제 원인·관제 적용 성공은 아직 확인되지 않았고 **관제 적용 0회**, 기존 `e132a4b` 운영 유지로 기록한다. 이번 문서 갱신은 파일 편집만이며 커밋·push는 주 작업자의 배포 진행 종료 후 검토까지 보류한다.
