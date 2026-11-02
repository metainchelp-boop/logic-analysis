# 미사용 NAVER 산출물 정리 모드

## 승인 범위

기존 정리 계획이 허용하는 미사용 NAVER engine/relay 커밋 태그와 release 폴더만 정리하는 고정 모드를 추가한다. 기존 전체 cleanup은 배포 명령 로그를 만들고 오래된 로그를 정리하므로 이번 작업에는 사용할 수 없다. release 폴더만 정리하는 안은 회수 범위가 부족하고, 별도 후보 판정기를 만드는 안은 보존 규칙이 달라질 위험이 있다. 따라서 기존 후보·보존·삭제 직전 재검사를 그대로 재사용하되 로그 처리 경로만 분리한다.

## 계약

- 입력은 `cleanup-artifacts-plan` 또는 `cleanup-artifacts <allowlist_sha256>`뿐이다. 경로·이미지명·보존 예외·삭제 목록 입력을 추가하지 않는다.
- 두 모드는 기존 `build_plan`, `protected_state`, image/release identity와 삭제 직전 재검사를 공유한다. current, fallback, 배포 기록, 모든 컨테이너의 이미지·mount, unit/drop-in/compose/companion 참조 수집을 유지한다. 기존 전체 cleanup은 path 참조로 release만 보호한다. 새 모드는 그 참조의 같은 커밋 이미지와 같은 이미지 ID의 다른 NAVER 태그까지 추가로 보존하며, 삭제 직전에도 다시 확인한다. 이 추가 보호는 기존 전체 cleanup에는 적용하지 않는다.
- 새 해시는 `unused-naver-artifacts-v1` scope와 기존 정렬된 type/ref/id 목록을 함께 결속한다. 기존 cleanup-plan 해시와 새 해시의 교차 적용을 거부한다. legacy hash와 동작은 그대로 유지한다.
- apply는 같은 고정 deploy lock과 root 검사, 미완결 배포 거절을 적용한다. 기존 state 디렉터리가 없거나 실제 디렉터리가 아니면 거절한다. 잠금 파일 외에 state/log 파일을 만들거나 바꾸지 않는다. commands 로그 생성·삭제·chmod, prune-logs, 기존 전체 cleanup shell 경로 호출은 없다.
- Docker 원문 출력은 메모리에 누적하지 않고 버린다. stdout은 기존 고정 JSON 결과 접두사와 새 mode/scope, 제거·거절·실패 목록, 실제 free bytes 전후뿐이다. 강제 image 삭제, container/systemd/volume/build cache 변경은 없다.
- 예상 회수량은 기존 측정치를 참고로만 제공한다. 표시값의 상하한이 일치하지 않더라도 보장 회수량으로 사용하지 않는다. 용량 판단은 적용 뒤 실제 free bytes와 기존 배포 용량 guard가 담당한다.
- workflow는 수동 dispatch만, 기존 main 검사·공유 concurrency·helper hash 확인을 유지한다. 제품 checkout/키는 deploy mode에만 제공하며 새 모드에는 전달하지 않는다.

## 검증과 인계

기존 전체 cleanup 검사와 새 mode의 후보 동일성/다른 hash, 양방향 hash 교차 거절, current/fallback/container/unit 참조 보호, late reference·retag·in-use 거절, inode 교체·symlink 경합, 미완결 배포·잠금 거절을 검사한다. 기존 로그의 내용·mode·mtime·inode와 로그 없는 상태가 그대로 남는지 확인한다. 실제 이미지 삭제는 fake host 안에서만 실행하고, 원문 canary가 stdout/stderr로 나오지 않는지 검사한다. workflow의 선택지·입력 검증·고정 명령·제품 자격 미주입과 기존 배포 제외 경로도 확인한다.

로컬·Linux 회귀와 비밀정보 검사 후 전용 브랜치로 push/PR한다. 병합, 실제 PLAN/APPLY, 실제 용량 판단, 제품 배포는 root가 별도로 수행한다.
