# Mutable data 보존 전 유한 범위 관찰

`retirement_data_preflight.py`는 종료·핀 보존·DB 연결·백업을 실행하지 않는다. `coverage_complete`도 정해진 시점의 관찰 완료이며 `stop_safety=not_determined`, `runtime_selection=not_proven`을 항상 유지한다. 운영 실행은 아직 하지 않았다.

## 여섯 관찰 묶음

1. 입력한 새 광고/콘텐츠 전체 container ID와 init PID를 고정 image/name/running/working-directory에 대조한다. bind 선언뿐 아니라 호스트 자료 디렉터리와 container `/app/data`의 device/inode를 대조한다. 자동입찰은 정확한 local volume/경로/options 없음 및 연결된 container 없음만 허용한다.
2. 광고 database.py, 콘텐츠 dotenv 로딩 entrypoint와9개 DB 설정 모듈의 검토 SHA를 내부 대조한다. 불일치는 `source_unreviewed`다. 다른 기능 전체의 실행 코드 동등성을 요구하지 않으며, 불일치 시 정확한 DB 경로/설정 파일만 별도 private 검토 후 pin을 갱신한다. 검토 기준은 기존 `/private/tmp/codex-retirement-audit-20261031` 소스 사본이다.
3. Docker 초기 환경은 DB 설정 키만 Go template에서 선별해 받는다. 콘텐츠 `/app/.env`와 기존 자동입찰 고정 `.env`는 각각64KiB 이하로 내부 읽고 DB 경로만 파싱한다. 원문·다른 설정·값·값 해시는 결과에 남기지 않는다. dotenv보다 초기 환경이 우선한다. 복잡한 보간/중복/불명 quoting, 허용 범위 밖 경로, 불명 cwd와 비SQLite/상대 자동입찰 URL은 거부한다. 광고/콘텐츠 bind와 콘텐츠 내부 `/tmp`, 자동입찰 volume 안에 모든 정적 설정 경로와6개 알려진 fallback을 포함해야 한다. 현재 runtime이 이 중 어느 파일을 선택했는지는 증명하지 않는다.
4. 세 자료 디렉터리 **전체**와 콘텐츠 `/tmp` 전체를 no-follow FD로 순회하여 종류·개수·바이트·blocks만 집계한다. 파일 본문을 열지 않는다. 호스트 부모 중 기존 관찰된 `/root/ad-dashboard-deploy` 한 경로에만 UID501/GID50/0755 예외를 허용하며 다른 부모/자료 디렉터리는 UID0 기준을 유지한다. symlink/특수파일·미해결 hardlink·다른 device/mount·깊이/개수 초과·변경은 불완전이다.32개 고정 내부 DB/sidecar 후보는 별도 숫자 alias/metadata만 관찰한다.
5. 호스트 `/proc` 전체를 두 차례 순회하고 두 번째 조회 중 새로 보인 PID를 최대64개 추가 조회하여 regular FD flags와 shared writable mmap을 제한 검사한다. 무관한 프로세스의 FD/map 변경·생성·종료는 숫자로 집계하며 호스트 전체 정지를 요구하지 않는다. 대상 앱 및 관련 writer의 identity/FD/map 불확실성은 거부하고, 마지막에도 조회하지 못한 새 PID가 있으면 불완전이다. FD를 닫은 writer도 maps의 device/inode 및 허용 경로/namespace로 찾는다. 삭제된 외부 writer도 해당 자료 경로와 일치하면 감지한다. 대상 앱의 범위 밖 writable regular/mmap, 외부 writer는 `writers_unresolved`다. 알려진 대상 앱의 현재 writer 수를 writer 부재로 바꾸지 않는다. 이 검토된 읽기 전용 observer 자신의 PID만 self-referential FD 열거 예외로 제외한다.
6. 광고/콘텐츠 **모든 regular deleted FD**를 unique device/inode별로 묶어 크기·link·mount·app alias·참조 수·memory/heartbeat 힌트를 새로 기록한다. 이전 콘텐츠4개 zero 패턴은 비교 boolean일 뿐 제외 조건이 아니다. nonzero나 광고센터 자료도 조용히 누락하지 않는다. 마지막에 container/workers/PID starttime/namespace/volume/자료 디렉터리와 bind identity를 재대조한다.

## 상한과 결과

전체60초(정상 CLI signal deadline), PID4096개, PID당 FD4096개/전체131072개, maps파일256KiB, 일반 metadata/config64KiB, route-source256KiB, 자료 항목 전체100000개/깊이32, deleted64 identity/256참조, 명령의 stdout+stderr131072B, 공개 JSON65536B다. 상한·권한·관찰 중 변경은 성공으로 대체하지 않는다. kernel의 중단 불가능 I/O까지60초 종료를 보장하지 않으므로 향후 workflow에 외부 timeout도 둔다. 원문 stderr·예외·고객 파일명·환경값·원본 FD target은 출력하지 않는다. 공개 key/enum은 GitHub의 VPS 사용자 secret 마스킹을 피하도록 소문자 `root`를 포함하지 않는다.

## 후속 cold source 재사용

`Files.directory/read/bind_identity`, `Docker.inspect/volume/workers`, `Proc.identity/root_fd/mounts`, `resolve_routes`, `scan_tree`, `scan_host`, `collect`가 재사용 경계다. `collect(..., private=state)`는 성공 때만 private container/process guard와 모든 deleted-file 참조의 `(pid, fd, process_identity, file_identity, flags, mount_id)`를 남긴다. `scan_host(..., private=state)`도 같은 private 참조를 제공한다. **private object를 JSON/로그/영수증에 쓰지 않는다.** 실패한 collect는 state를 비운다. CLI는 private state를 만들거나 공개하지 않는다.

이 함수는 실제 application FD를 pin하지 않으며, 반환 뒤 PID/FD가 유효하다는 보장도 없다. 후속 source는 같은 session의 명시적 writer freeze 뒤 guard를 다시 대조하고 모든 실제 대상 regular FD를 pin하여 휘발 자료를 별도 상한 아래 암호화 보존해야 한다. 종료 전에 마지막 참조 소실 위험을 해소한다. nonzero 범위/용량 불명은 별도 명시 정책 없이 성공시키지 않는다. 재기동 장치 통제·실제 일관 사본·원격 수신·격리 SQLite/key/첨부 검증은 이 모듈 밖의 실행 단계다.

## 합성 검증

```sh
python3 -I -B -m unittest discover -s deploy/naver/tests -p test_retirement_data_preflight.py -v
```

가짜 Docker 응답과 private 임시 파일시스템/proc만 사용한다. macOS fixture의 bind/mount는 명시적 test adapter이며 실제 Linux bind/커널 동작 증거가 아니다. 실제 DB/키/암호문/서버와 product module import는 사용하지 않는다.
