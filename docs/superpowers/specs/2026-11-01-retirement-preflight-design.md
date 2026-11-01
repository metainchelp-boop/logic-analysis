# 철거 계획 2단계 — 기동 장치의 제한 메타데이터 조회

## 승인 범위와 목적

대표의 「이어서 해」와 기존 `RETIREMENT_PLAN.md` 2단계에 따른 후속 구현이다. 첫 조회에서 발견한 관련 미분류 systemd 6개와 root crontab rc1의 불확실성을 줄인다. 기존 `app-inventory`의 읽기 전용 전송·검사·수동 실행 경로를 그대로 사용한다. 서비스 종료·재시작·설정/환경값/DB/키 내용 조회·보관·삭제는 수행하지 않는다. Mac agent·ERP·컨테이너 내부 `/tmp`·주기 cron은 이번 확장 밖이다.

## 선택과 대안

소스/기존 안전 조회에는 미분류 6개의 고정 실명이 없어 유추한 이름을 allowlist에 추가할 수 없다. 전체 이름/명령을 출력하는 대신, 이미 읽은 두 systemd 목록의 관련 이름을 메모리에서만 분류하고 제한된 개수의 메타데이터를 별칭으로 출력한다. 기존 고정 unit 출력 형식은 유지한다.

root cron은 stderr를 새로 수집하거나 해석하지 않는다. 고정 spool 디렉터리와 root 파일의 존재·파일 종류·권한·소유·크기 같은 메타데이터를 추가한다. 기존 crontab rc1은 계속 unavailable이며, spool 파일 부재도 전체 cron 부재로 바꾸지 않는다.

## systemd 계약

- 기존 관련 prefix 판정 뒤 ASCII `[A-Za-z0-9_.@:-]`만 허용하며 전체 1~200자, 영숫자 첫 문자, `.service`/`.timer` suffix를 확인한다. 옵션처럼 시작하거나 slash·공백·제어문자·비ASCII·escape가 있는 이름은 조회하지 않는다.
- 정렬한 고유 관련 후보 중 유효 이름 최대 16개만 `systemctl show` 배열 인자로 전달한다. 기존 `PROPERTIES`와 `WorkingDirectory`만 요청한다. 원문 stdout/stderr는 기존 실행기의 제한을 따른다.
- 반환 `Id`가 요청 이름과 정확히 같아야 한다. 실패·잘림·identity 불일치는 별칭별로 표시하며, 거부된 이름 수·상한 초과 수·목록 실패도 보존한다.
- 출력 이름은 `related-unit-N`이고 원문 이름·Id·FragmentPath·DropInPaths·알 수 없는 의존 이름/working directory는 공개하지 않는다. prefix에서 `ad-dashboard`/`content-studio`/`autobid`/`naver`/`logic-analysis` 앱 힌트를 출력한다. 이 힌트는 실행 명령이나 실제 대상 앱을 증명하지 않는다.
- 상태는 기존 enum, PID/재시작은 숫자, 의존은 고정 unit allowlist와 기타 개수만 허용한다. WorkingDirectory는 기존 `safe_path`에 맞는 값만 출력하고 나머지는 redacted로 표시한다. 추가 파일 stat·git·명령 실행의 인자로 사용하지 않는다.
- 미분류 후보가 존재하면 전체 systemd 상태는 계속 incomplete이다. 개별 메타데이터 성공을 전체 기동 경로 확인 완료로 승격하지 않는다.

## root cron spool 계약

조회 경로는 `/var/spool/cron/crontabs`와 `/var/spool/cron/crontabs/root` 두 개뿐이다. 각 상위 디렉터리를 `O_DIRECTORY|O_NOFOLLOW` descriptor로 고정하고 `stat(..., follow_symlinks=False)`로 확인한다. 최종 경로는 부모 descriptor 기준 stat만 하며 cron 파일을 열지 않는다. 메타데이터만 수집하며 디렉터리 열거·파일 open/read/hash·du·수정은 하지 않는다. absent, permission_denied, stat_failed, symlink_refused, 경로 교체/비디렉터리 거절을 구분한다. 조회한 경로는 로그의 기존 `root` 마스킹 대상일 수 있으며 결과를 복원하지 않는다.

## 검증과 완료 조건

합성 secret canary를 이름·Id·Fragment/drop-in·의존·working directory·stderr/예외에 넣어 최종 JSON에 남지 않는지 검사한다. 잘못된/옵션 이름의 외부 조회 0회, 16개 상한, 이름 identity, 실패/잘림, NAVER 관련 6개의 힌트, 기존 고정 unit 형식, spool symlink/부재/권한실패와 내용 읽기 0회를 검사한다. focused 검사 뒤 root가 기존 전체 회귀·독립 검토·CI·병합·읽기 전용 재조회를 수행한다.

자체 검토: 입력/출력 경계와 상한, 실패 의미, 기존 형식 호환, 읽기 전용 범위에 모호한 항목과 미정 placeholder가 없는지 확인했다. 새 조회가 Mac/ERP/DB/키/복구 검증을 해결했다고 주장하지 않는다.
