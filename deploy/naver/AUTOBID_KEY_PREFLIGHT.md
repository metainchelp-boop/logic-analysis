# 자동입찰 키 보관 후보 한 곳의 메타데이터 관찰

수동 `naver-autobid-key-preflight.yml`은 고정 `/root/content-studio-deploy/autobid/.env`의 존재·종류·수치 metadata만 관찰한다. 후보 근거는 기존 콘텐츠 checkout과 자동입찰 배포 소스의 `enc.key` → `autobid/.env` 복제 구조다. 이 경로에서 실제 자동입찰을 배포했거나 원래 키가 남았다는 뜻은 아니다.

## 실행 조건과 출력

정확한 변경 커밋의 합성 CI와 독립 검토 뒤 운영 담당이 main의 수동 workflow를 실행한다. 입력 경로는 없다. 최초 실행자와 재실행자가 모두 대표 계정이어야 한다. 기존 VPS SSH secret과 별도로 확인한 `VPS_HOST_FINGERPRINT`가 필수이며 누락·불일치 시 우회하지 않는다.

도구는 `/`부터 부모 descriptor를 no-follow로 고정하고 부모명 연결과 leaf metadata를 전후 대조한다. 최종 파일은 stat만 하며 열거나 읽지 않는다. 부모 링크·비정규 파일·권한 실패·시점 변경은 `status=incomplete`, 존재는 null이다. 안정적으로 파일 또는 부모가 없으면 `status=complete`, `exists=false`, `target_absent`/`parent_absent`를 구분한다. 정규 파일 존재는 그 metadata만 보고하며 크기0도 임의 정상 키로 판정하지 않는다.

`AUTOBID_KEY_METADATA=` 뒤 JSON만 수집한다. `original_key_available=unknown`, `stop_safety=not_determined`는 성공/부재/실패 모두 유지한다. workflow 성공도 키 확보·복구·철거 승인이 아니다. 경로 원문·파일 내용·환경·DB·키·키 해시·임의 예외는 출력하지 않는다. 다른 runner/홈/volume/이미지 경로는 조회하지 않는다.

각 실행은 기존 콘텐츠 preflight와 다른 concurrency 및 exclusive 임시 0700 경로를 쓴다. 공개 helper 한 파일만 전송해 해시를 대조하고 20초 외부 timeout 아래 실행한다(내부 alarm5초/JSON4KiB). 정리는 해당 helper와 빈 임시 디렉터리에 한정한다. 강제 종료·SSH 불능 시 정리를 보장하지 않으며 임의 재귀 삭제를 하지 않는다. 제품 deploy 제외 경로와 PR 합성 CI 범위를 시험으로 고정했다.

## 로컬 합성 검사

```sh
python3 -I -B -m unittest discover -s deploy/naver/tests -p 'test_autobid_key*py' -v
```

임시 합성 디렉터리만 사용한다. 부모 교체·leaf rotation·링크·FIFO·권한 거부·부재 변화·원문 누출·read/open 금지를 검사한다. workflow 검사는 실제 Bash guard와 소스 계약 검사이며 SSH/SCP·Linux 실제 filesystem·운영 후보 존재 확인을 대신하지 않는다. 전체 기존 도구 회귀는 정확한 변경 커밋의 CI에서 수행한다.

본문 또는 원래 키 회수가 다음에 필요해지면 별도 승인된 비밀 처리 절차를 구체화한다. 파일 존재 결과만 보고 환경 내용을 로그로 출력하거나 원본 앱을 기동하지 않는다.
