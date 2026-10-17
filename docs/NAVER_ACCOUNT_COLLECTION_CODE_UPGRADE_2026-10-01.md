# 계정 확인·즉시 수집 코드 전용 업그레이드

## 승인 범위와 준비 상태

2026-10-01 승인 범위는 검증된 광고계정 확인과 즉시 GET 전용 네이버 데이터
수집입니다. 광고 변경·자동입찰·알림·직원 권한 확대는 포함하지 않습니다.
엔진과 릴레이 두 서비스만 교체하며, 일반 광고센터 배포는 하지 않습니다.

현재 컨트롤러는 후보 커밋 `abf24060eaf907416439bf3e57d83242bb1b7bb5`만
허용합니다. CI 실행 `36867269364`의 성공과 같은 커밋의 봉인 영수증 확인은
배포 전 필수입니다. CI 수정으로 커밋이 바뀌면 재검토 후 정확한 핀을
함께 갱신해야 하며, 임의 입력으로 핀을 바꿀 수 없습니다.

- 이전 운영 커밋: `f7eb2e58aafad81e27978f175d83cca0eb5c5733`
- 운영 기준 지문: `5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76`
- 이전 소스 압축 지문: `23b4a2fe6d85ba52b082907801e8494eceb7a14ea32f33b8ac9ee296a9f93d0e`
- 이전 전환 이력: `NAVER_CODE_UPGRADE_2026-10-01.md`는 변경하지 않습니다.
- 원본 부트스트랩 업그레이드의 `OLD_COMMIT`과 범용 소스 허용 범위는 변경하지 않습니다.

## 변경 허용 경로

실행 소스 묶음 안에서는 다음 파일의 내용 변경만 허용합니다.
기존 파일 삭제·권한 변경·심볼릭 링크·그 밖의 파일 추가나 변경은 거부합니다.

- `naver_engine/web.py`
- `naver_engine/sync.py` (기존 대표·조직 최신성 검사를 공개 helper로 이동)
- `naver_runtime/__main__.py`
- `naver_runtime/writer.py`
- `naver_runtime/scheduler.py`
- `naver_runtime/collection_requests.py` (신설 가능)
- `backend/naver_page/app.js`
- `backend/naver_page/index.html`

묶음에 포함되는 검증 파일은 다음 다섯 개만 별도로 허용합니다.

- `naver_engine/tests/test_verified_collection.py`
- `naver_engine/tests/test_verified_collection_screen.py`
- `naver_engine/tests/verified_collection_browser.js`
- `naver_runtime/tests/test_collection_requests.py`
- `naver_runtime/tests/test_collection_integration.py`

`naver_engine/views.py`, `naver_engine/morning.py`는 변경하지 않으므로 허용하지
않습니다. 위 파일 외의 테스트·문서도 디렉터리 단위로 허용하지 않습니다.
`docs/`, `tools/`, `.github/`는 현재 묶음 밖입니다. 이 전제가 달라지면
먼저 경로와 변경 내용을 재검토합니다.

## 유지하는 보호 장치

환경·비밀값은 기존과 바이트 단위로 같아야 하며 새로 쓰지 않습니다.
Compose·Dockerfile·requirements·bootstrap·스키마 버전/SQL/마이그레이션은
동일해야 합니다. 이미지 출처·ID·비루트 사용자, 정확한 유닛 내용,
활성/자동시작 상태, 기존 세 앱의 운영 기준 지문을 검증합니다.

기존 부트스트랩 요청·시작·종료 영수증은 읽고 비교만 합니다.
미완료 요청이 있으면 거부하고, 요청이 없으면 없는 상태를 유지합니다.
DB·키·nginx·전산 터널·기존 세 앱은 수정하지 않습니다.

실패 시 정확한 이전 `f7eb2e5` 이미지·유닛으로 복구하고 같은 준비/보안
검사를 통과해야 합니다. 복구 불일치 시 두 서비스는 중지된 상태로 남습니다.
복구는 코드/유닛 복구이지 업무 기록이나 이미 완료된 GET 수집의 취소가 아닙니다.
새 DB 스키마·설정·부트스트랩 요구 사항이 생기면 이 계약으로 배포할 수 없습니다.

## 릴리스 담당자 실행 순서

1. AD 소스의 변경 경로와 스키마·설정 무변경을 확인하고 최종 커밋을 고정합니다.
   봉인 도구와 봉인 워크플로의 브랜치 조건은
   `codex/naver-ad-account-matching-20261001` 한 개로 정확히 지정합니다.
2. 같은 커밋·브랜치에서 수동 CI와 `preview-seal`을 실행하고 두 실행의 성공,
   `linux-tests`/`preview-seal` 작업 성공을 각각 확인합니다.
3. 이번 전용 디스패처 `outputs/dispatch-verified-account-collection.py`의 `BRANCH`,
   `SOURCE`, 코드 전용 대상 핀을 최종 브랜치·작업 폴더·커밋으로 지정합니다.
   운영 기준·공개 인증서 핀·실행 출처·artifact digest·로컬 `git archive`와
   봉인 영수증의 소스 압축 지문 대조는 그대로 둡니다. 이전 디스패처
   `outputs/dispatch-verified-naver-preview.py`는 변경하지 않고 보존합니다.
4. 컨트롤러 대상 핀을 같은 커밋으로 고정하고 전체 preview 회귀검사를 통과시킵니다.
   디스패치 브랜치는 `codex/ad-deploy-prep-20261001`입니다.
5. `preview-code-prepare`를 실행합니다. 암호문 출처가 확인된 다운로드 패키지만
   전달하며 다른 입력은 모두 `off`입니다. 이 단계는 서비스 재시작을 하지 않습니다.
6. 준비 실행 ID와 영수증 지문을 확인한 뒤 `preview-code-upgrade`를 실행합니다.
   패키지는 `release`와 새 32자리 소문자 16진수 `operation_id` 두 필드뿐입니다.
   `release`는 `baseline`, `source_commit`, `ciphertext_sha256`,
   `source_tar_gz_sha256`, 준비 `run_id`, `operation: code-prepare`입니다.
   새 부트스트랩 요청·보류·승인 필드를 추가하지 않습니다.
7. 실행 성공뿐 아니라 작업 로그의 준비/적용 결과를 확인합니다.
   필요한 경우 `gh api repos/metainchelp-boop/logic-analysis/actions/jobs/<ID>/logs`
   로 SSH 단계의 실제 결과를 확인하되 비밀값·서명된 다운로드 주소는 출력하지 않습니다.
8. 독립적인 `preview-status`와 `preview-collection-status`로 서비스 출처·보안
   차단·실제 수집 상태를 확인합니다. 헬스체크나 배포 성공만으로 수집 완료를 선언하지 않습니다.

준비 35분 SSH/40분 작업, 적용 60분 SSH/65분 작업 예산과
`deploy-logic-analysis` 동시 실행 제어는 유지합니다.

## 이 차수 검증

로컬 합성 회귀: `python3 -m unittest discover -s backend/tests -p 'test_naver_preview_*.py' -q`.
실제 운영 디스패치·데이터 수집 완료 검증과는 별도입니다.
