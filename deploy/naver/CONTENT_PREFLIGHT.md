# 콘텐츠 컨테이너 메타데이터 사전 관찰

2026-11-01. `content_runtime_preflight.py`는 보존 범위를 좁히기 위한 독립 Python 표준 라이브러리 helper다. 이를 전송·실행하는 수동 `naver-content-preflight.yml`을 준비했다. 현재 검증은 **로컬 합성 fixture와 실제 Bash guard만** 사용했다. 이 구현자는 운영 실행·SSH·앱 종료·사본 생성·DB 연결을 하지 않았다.

## 입력과 실행 전 조건

- 실제 운영 전송·실행 및 결과 수집은 root의 별도 범위다. 기존 app-inventory collector는 바꾸지 않는다. 수동 workflow를 추가하고, 기존 앱 배포 workflow의 제외 경로와 합성 CI의 PR 경로만 함께 추가했다.
- 같은 시점의 새 app-inventory에서 콘텐츠 컨테이너의 전체 64자리 ID, `sha256:` 이미지 ID, 호스트 init PID를 받아야 한다. 코드에는 운영 ID/PID 기본값이 없다. 인자는 `--container-id`, `--expected-image`, `--expected-init-pid` 세 개뿐이다.
- 고정 후보는 검토한 소스의 `/tmp` DB 8개와 각 `-wal`/`-shm`/`-journal`, 총 32개다. `/app/data` DB 9개와 sidecar는 FD 분류의 알려진 경로로만 쓴다. 소스·실행 이미지가 바뀌면 이 목록의 유효성을 먼저 다시 검토한다. 이미지 ID는 소스 SHA나 실효 DB 설정의 증명이 아니다.
- `.env`, 프로세스 환경, 명령 인자, 키, DB 내용은 읽지 않는다. 앱 모듈 import나 SQLite 연결도 하지 않는다. 따라서 환경 override와 소스의 fallback 경로가 실제 적용됐는지는 항상 **unknown**이다.
- Linux Docker 호스트의 `/proc` 및 필요한 Docker 메타데이터 읽기 권한이 필요하다. 권한 부족·시점 불일치는 incomplete이며 우회하거나 앱을 재기동하지 않는다. `Proc`의 대체 proc root는 합성 fixture용이며 CLI로 제공하지 않는다.

## 수동 workflow의 전송 경계

Actions의 `콘텐츠 보존 전 메타데이터 관찰 (읽기 전용)`은 `workflow_dispatch`만 허용한다. 최초 실행자와 재실행자 모두 대표 계정 `metainchelp-boop`, ref는 main이어야 한다. 계정·ref·세 입력 형식·PID 상한을 각각 명시적 if/exit로 검사한다. AND-list와 `set -e`의 조합에 계정 제한을 맡기지 않는다. guard 회귀는 mac Bash 3.2에서도 실제 실행하며 Ubuntu runner의 CI/운영 실행과 구분한다.

원본 서버의 **확인된 기존 호스트 공개키** SHA256 지문을 `VPS_HOST_FINGERPRINT` secret으로 설정해야 한다. 값은 `SHA256:`와 base64 43자리 형식이어야 하며 누락/형식 오류이면 서버에 접촉하기 전에 실패한다. 지문은 workflow 입력으로 받지 않고, SSH/SCP 및 정리 연결 모두 같은 필수 secret으로 고정한다. 네트워크에서 새로 관찰한 키만 믿고 secret을 자동 등록하거나 host key 검증을 생략하지 않는다. 초기 조회에는 이 secret/관련 var가 없었으나, root가 배포 문서의 공유 서버와 기존 known_hosts의 일치 ECDSA 지문을 별도로 확인해 secret을 등록했다. 2026-11-01 05:49:59Z 갱신이라는 이름 메타데이터를 확인했으며 이 구현자는 secret 값을 읽지 않았다. 지문 출처/등록의 준비 공백은 해소됐고 실제 SSH host key 협상과 운영 실행 검증은 아직 별도 root 범위다. 액션이 기존 신뢰 키와 다른 호스트 키 알고리즘을 선택하면 접속 실패로 남긴다.

전체 합성 시험에 통과한 뒤 공개 helper 한 파일만 전달한다. 원격은 root UID와 no-symlink `/tmp`를 확인하고 `umask 077`과 exclusive `mkdir`로 실행 ID/attempt별 0700 디렉터리를 만든다. 실행 전에 디렉터리/파일의 root 소유권·종류·symlink 거절과 전송 전후 SHA-256을 대조한다. 실제 helper는 10초 관찰 상한 외에 `timeout -k 1s 20s`를 적용하며 SSH는 30/45초, SCP는 45초 상한이다. 앱 소스·환경·키·DB는 전송하지 않는다. 원격 helper stderr를 공개 로그로 내보내지 않고, 허용 결과 JSON만 `CONTENT_RUNTIME_PREFLIGHT=` 뒤에 출력한다. exit 2는 불완전 관찰로 workflow도 실패 처리한다.

원격 폴더 생성 성공이 확인됐으면 SCP/해시/실행 실패 뒤에도 always 정리를 시도한다. 현재 실행의 고정 helper 파일과 빈 0700 폴더만 지우며 재귀 삭제하지 않는다. 예상하지 못한 파일·소유권·symlink이면 실패로 남긴다. 강제 runner 종료·SSH 불능·생성 성공을 확인하지 못한 경우까지 정리를 보장하지 않으며 남은 경로를 임의로 넓혀 삭제하지 않는다. 모든 신규 경로는 기존 앱 배포의 `paths-ignore`에 포함되고, PR 합성 CI에서 검사된다. 수동 preflight는 기존 배포와 같은 concurrency 그룹을 사용하며 진행 중 실행을 취소하지 않는다.

## 허용되는 관찰

Docker에는 고정 inspect 템플릿과 `docker top ... -eo pid,ppid,comm`만 실행한다. inspect는 ID/name/image/running/PID와 mount type/destination만 내부에서 읽고, 전체 inspect/환경/args/health 값은 받지 않는다. 이름은 정확히 `/content-studio`이어야 하며 다른 이름은 proc 조회 전에 거절한다. 이름은 출력하지 않는다. top의 알려지지 않은 실행명은 `other`로 바꾼다. 처음과 끝의 inspect·top, init starttime/namespace 및 각 worker의 관찰 전후 starttime/namespace를 비교한다.

`/proc/PID/root`, namespace 링크, FD 링크는 Linux 커널 메타데이터 접근의 명시적 예외다. PID 디렉터리와 그 아래 일반 디렉터리는 no-follow stat → open → fstat의 device/inode/mode를 비교하고 FD를 닫는다. 고정 `/tmp` 후보는 부모 no-follow 검증과 최종 lstat만 하며 파일을 열지 않는다. 후보가 symlink이면 거절한다. 후보 이름 대신 `candidate-1`부터 `candidate-32`까지의 고정 alias와 존재 상태·크기·시각·권한·숫자 identity만 출력한다.

각 worker는 FD의 stat/readlink와 제한된 fdinfo의 octal flags만 관찰한다. DB 파일 자체나 열린 FD 내용을 읽지 않는다. FD link 원문·고객 파일명·예외 메시지는 출력하지 않는다. 알려진 경로/후보 inode의 FD 수, 쓰기 가능 수, 삭제-open 수 및 미분류 일반파일의 쓰기/삭제-open 수만 반환한다. 미분류 writer·삭제-open·관찰 실패는 incomplete로 남긴다. 이는 알려진 파일이 없는 경우에도 동일하다.

mountinfo는 `/tmp`뿐 아니라 32개 후보 각각에 대해 root/부모/중첩 mount 중 가장 긴 경로를 선택한다. tmpfs/ramfs일 때만 `memory_backed=true`, 그 외는 null이다. Docker bind 선언은 별도 필드다. `persistence_after_stop`은 모든 경우 unverified이며 mount 메타데이터로 복구 가능성을 판정하지 않는다.

## 상한과 결과 해석

| 항목 | 상한 |
|---|---:|
| 전체 관찰 | 10초, CLI SIGALRM 포함 |
| worker | 64개 |
| worker별 FD | 4,096개 |
| stat/mountinfo 한 파일 | 65,536B |
| fdinfo 한 파일 | 4,096B |
| Docker 명령 한 번의 stdout+stderr | 65,536B |
| JSON 출력 | 65,536B |

상한·권한·PID/namespace 변화·mount 불명·top/inspect 변화·알 수 없는 FD는 실패/불완전 상태다. 원문 stderr를 기록하지 않는다. 최종 컨테이너/init/프로세스 목록 불일치이면 후보/worker 관찰을 폐기한다. 시그널 deadline은 개별 파일 예외 처리에 흡수되지 않으며 불완전 JSON으로 끝낸다. 커널의 중단 불가능 I/O까지 시간 내 해제한다고 보장하지 않는다.

`bounded_observations_complete`와 exit 0은 정해진 범위의 관찰이 완료됐다는 뜻이다. 종료 허가가 아니다. 다음 필드는 결과와 무관하게 유지한다.

- `effective_database_paths=unknown_environment_overrides_not_read`
- `writer_absence=unverified_even_if_observed_counts_are_zero`
- `stop_safety=not_determined`

프로세스/FD 목록은 두 시점의 관찰이며 동결/락이 아니다. 두 시점 사이의 짧은 worker·FD 변경, FD가 닫힌 mmap writer, 외부/다른 namespace writer, 설정 override, 알려지지 않은 경로의 DB 여부, DB 일관성은 증명하지 않는다. 내부 `/tmp`·tmpfs·삭제-open 자료의 보존 설계와 실제 회수/격리 복구 검증은 따로 필요하다. 이 helper는 복사·checkpoint·설정 변경·중지·삭제를 수행하지 않는다.

## 합성 검증

```sh
python3 -I -B -m unittest discover -s deploy/naver/tests -p test_content_runtime_preflight.py
```

helper 22건과 workflow 13건, 총 35건의 로컬 집중 시험이 통과했다. helper는 DB 내용 열기 금지, 경로/키 canary 비노출, symlink/디렉터리 교체, FD/byte/time 상한, PID/starttime/namespace/top/inspect 변화, 미분류 writer/삭제-open, 부모/중첩 mount, 다른 컨테이너 이름 거절, CLI 잘못된 값 비노출, command timeout/출력 상한을 포함한다. workflow는 실제 Bash 계정·입력·지문 guard와 전송·정리·앱 배포 제외의 소스 경계를 검사한다. 정적 source assertion은 실제 SSH/SCP/실패 정리나 운영 Docker/커널 동작·GitHub CI 검증을 대신하지 않는다.

통합된 위치에서 집중 시험은 다음과 같이 실행한다.

```sh
python3 -I -B -m unittest discover -s deploy/naver/tests -p 'test_content*py' -v
```

CI와 수동 workflow는 같은 디렉터리의 전체 합성 시험을 실행한다. 전체 시험 수·정확한 커밋의 CI/운영 결과는 해당 실행 기록으로 따로 확인한다.
