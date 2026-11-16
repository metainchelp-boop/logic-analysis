# Paused 앱 자료의 암호화 복구 후보 생성

사용자가 승인한 세 앱 철거·서버 B 별도 보관·전용 복구 키 범위의 후속 구현이다. import 전용 archive producer, 고정 암호화 전송·수신 helper, 수동 workflow와 합성시험을 포함한다. 개발 검증에서는 원격 실행, 실제 pause, 전송, DB 접속, 종료를 수행하지 않는다. 이전의 휘발 자료 선복사→unpause→stop 방식 대신 **같은 freeze 구간에서 전체 보존→Mac 복구 검사→정확 종료**를 채택한다. 원래 프로세스는 복구 검사 완료까지 paused 상태로 남아 원래 deleted FD를 유지한다.

## 호출과 외부 실행 조건

`archive_snapshot(preflight, request, gpg_stdin_fd, restart_evidence=...)`는 고정 session `data-snapshot-20261102-v1` 하나만 생성한다. 제품 실행 함수와 일반 stdout CLI는 없다. 직접 실행은 출력 없이 exit2다. 호출자는 검토한 preflight/producer 파일의 SHA를 고정하고, 정확한 두 컨테이너의 재배포·재시작·ingress 및 외부 writer를 통제한 뒤 pause한다. FIFO만으로 GPG 수신자를 식별할 수 없으므로 **호출자의 검토된 GPG 파이프 결속이 필수**다.

producer는 Docker의 정확 ID/PID/running/paused 상태, 모든 worker의 starttime/PPID/pid·mount namespace, 모든 task/TID와 v1 freezer 또는 v2 cgroup의 완료 상태를 전후 확인한다. 확인된 system.slice/docker 또는 docker ID cgroup만 허용하며 nested cgroup, task 차이, FREEZING, unreadable은 실패다. preflight 성공도 시간상 관찰이며 미래 writer lock이 아니다. 외부 실행 통제를 관찰 두 번으로 대체하지 않는다.

## 고정 보존 범위

- 광고 data, 콘텐츠 data, 자동입찰 local volume의 세 고정 전체 트리와 콘텐츠 pinned procroot의 `/tmp` 전체를 포함한다. DB뿐 아니라 WAL/SHM/journal, JSON, 첨부, 빈 디렉터리도 같은 상대 경로로 manifest에 기록한다.
- 광고·콘텐츠의 모든 regular deleted FD를 device/inode별로 중복 제거하고 크기0도 보존한다. PID/FD/flags/mount/file identity를 대조한 kernel proc magic link만 예외적으로 pin하며, `pread`를 사용해 원래 offset을 바꾸지 않는다.
- shared writable file mapping은 이미 포착한 파일 identity를 `/proc/PID/map_files`로 pin한다. FD가 없고 트리에도 없는 mapping, 권한 부족, identity 차이는 `mapping_unpinned`로 실패한다. 이미 관찰된 io_uring/aio FD 또는 O_DIRECT도 불완전 처리한다.
- 고정 회복 설정은 `ad-container`, `content-container`의 bounded Docker subset, Compose label로 확인한 두 고정 Compose 파일, 기존 고정 AutoBid `.env`다. 콘텐츠 `/app/.env`는 pinned procroot를 통해 보존하며 없으면 `recovery_config_absent=['content-dotenv']`를 명시한다. 다른 host `.env`나 label의 임의 경로를 따라가지 않는다.
- Docker `Config.Env`는 **초기 컨테이너 환경**이다. 이후 애플리케이션 dotenv 및 동적 상태와 같다는 주장을 하지 않는다. 생성 JSON에는 초기 환경·command·entrypoint·port·mount·restart·network 등의 검토한 subset만 포함하며 내용은 암호화 stream 안에만 남긴다.
- 원래 재시작 정책은 `original-restart-policy`(`restart-json`) 객체로 보존한다. 고정 control session의 `fence-complete.json`만 허용하며 root0600/nlink1/8192B 이하·root0700 부모·검토된 정확 SHA를 요구한다. caller의 `restart_evidence`는 sha256/operator_evidence_sha256/control_policy_sha256 세 고정 hash만 받는다. 양쪽 fence 완료 뒤의 canonical journal, 정확 ID/image/StartedAt 및 현재 restart=no를 확인한다. journal FD와 모든 부모를 전체 stream 동안 유지하여 전후 같은 FD·내용 hash·path edge·ctime를 검증한다. 초기 Env를 새 평문 파일에 기록하지 않는다.
- 읽기 전용 control41403670586으로 확정한 `nginx-ad`, `nginx-logic`, `nginx-studio`(`opaque-nginx`)를 포함한다. 고정 resolved 파일은 각각 `/etc/nginx/sites-available/ad.metainc.co.kr`, `/etc/nginx/sites-enabled/logic-analysis`, `/etc/nginx/sites-available/studio.metainc.co.kr.conf`다. 원문을 해석·실행하지 않으며 source의 전후 control 검사가 해당 파일의 실제 검토 SHA/metadata와 결속한다. 필수 config9개, 선택 content-dotenv1개이며 기존 config 상한16개는 유지한다.

원본 symlink, special file, unresolved hardlink, 다른 mount/device, 이름·개수·크기·시간 상한 위반은 건너뛰지 않고 실패한다. 부모는 no-follow descriptor로 확인하며 기존 관찰된 광고 deployment 부모 한 경로의 UID501/GID50/0755만 preflight의 정확 예외를 재사용한다. 구성 파일은 같은 FD의 bounded pread 및 전체9개 stat 값·경로 edge·부모 identity/ctime를 전후 비교한다. 원본 chmod/chown/삭제는 없다.

AutoBid 공개 저장소로 오인할 수 있는 private 앱 Compose 원문은 이 저장소에 추가하지 않는다. 기존 private 복구 자료의 검토 provenance는 `metainc-content-studio` commit `f9217b83dcfb199a16243ad9d724e01931152a8f`, `autobid/docker-compose.autobid.yml`, 1778B, SHA256 `d917f2c72ff6f3833d61538d03a60a5d619d61a0e9197536f2d9ce59e60cc935`다. 실제 마지막 AutoBid runtime은 여전히 확인되지 않았다. 별도 암호화 보관은 실행 담당이 수행한다.

## 암호화 내부 형식과 검증

canonical USTAR regular member만 사용한다. uid/gid/mtime0, mode0600, 순차 `objects/00000001` 이름이며 순서는 트리의 파일→deleted→recovery_config다. 실제 원래 이름·stat·원문 SHA·PID/FD 참조는 최종 canonical `manifest.json`에만 포함한다. 트리 root directory4개도 빈 상대 경로로 포함한다. 마지막은 정확1024zero이며 PAX·link·추가 member는 없다.

manifest schema는 `metainc-retirement-data-v1`, consistency는 `frozen_crash_recovery_candidate`, application_restore_verified는 false다. 실제 파일 bytes를 첫 번째 stream hash 후 두 번째 전체 hash와 대조하고, 디렉터리 목록·metadata·mapping·preflight private guard·pause/cgroup·구성 파일을 다시 확인한 뒤 manifest를 쓴다. 마지막 freeze 확인과 모든 열린 context 종료까지 성공해야 producer가 성공한다. 나중에 실패하면 앞서 나온 암호문이나 manifest가 있어도 완료 보관본으로 승인하지 않는다.

상한은 source 합계2GiB, 항목100000개, 경로 누계8MiB, 깊이32, deleted64개/256참조, mapping pin256개, task8192개, config16개/각256KiB/합계2MiB, manifest32MiB, 총1800초다. tar 상한은 `MAX_BYTES+MAX_MANIFEST+(MAX_ENTRIES+MAX_DELETED+MAX_CONFIG_OBJECTS+1)*1024+2048`이다. 디렉터리 수집과 manifest encoding도 상한을 넘기기 전에 중단한다. stderr/예외/공개 영수증에는 원문·원래 이름·환경·원본 내용 해시를 남기지 않는다. core dump를 비활성화하고 평문은 메모리와 GPG pipe에만 있다.

freeze는 애플리케이션 transaction 완료나 모든 커널 비동기 I/O 부재를 증명하지 않는다. 검토한 고정 Python SQLite 경로에서 특수 VFS/OFF/MEMORY/비동기 직접 I/O 사용 근거는 없으며 관찰된 예외는 거부한다. 호스트 전체 Dirty=0 또는 fsfreeze는 요구하지 않는다. 원본 SQLite 연결·checkpoint는 실행하지 않는다. SQLite WAL/rollback journal을 포함한 격리 writable scratch 복구, integrity/key/첨부 검증이 완료되기 전에는 복구 성공 또는 삭제 가능으로 승격하지 않는다. [SQLite WAL 보존](https://sqlite.org/wal.html#the_wal_file), [SQLite 임시 파일과 journal](https://sqlite.org/tempfiles.html), [SQLite mmap](https://sqlite.org/mmap.html).

호출자 완료 조건은 producer/GPG/SSH 전부 RC0, cipher hash·bytes와 B 수신 영수증 일치, B 회수본의 GPG 인증 및 Mac 검증이다. 수신 영수증만으로 SQLite/application recovery를 증명하지 않는다. 실패 시 자동 stop/delete/unpause하지 않는다. 원래 paused 컨테이너와 보존된 partial을 실행 담당이 조사한다.

## 합성 검증

### 고정 전송과 수신 계약

`retirement_data_source.py prepare|send|cleanup`만 허용한다. prepare는 0700 one-shot session, 전용0600 SSH transport key, 공개 복구 키와 서버 B host pin을 준비하며 앱 pause와 원본 읽기를 수행하지 않는다. source SHA는 workflow가 no-follow/same-FD로 확인한 byte snapshot을 실행하고, source는 preflight/archive/control 세 모듈을 각각 고정 SHA의 같은 byte snapshot으로 로드한다. 최종 reviewed pins와 nginx/control 정책을 넣기 전에는 실행을 거부한다.

send는 기존 이미지 보존과 같은 global lock 및 session lock을 획득한다. 대표가 별도 GitHub API로 확인한 재배포 통제 기록의 고정 SHA와 현재 workflow run을 확인하며, GitHub token을 서버에 전달하거나 서버에서 외부 GitHub 상태를 다시 증명하지 않는다. 고정 control 정책의 ID/PID·nginx preimage·restart=no를 현재 상태와 비교하고 durable attempt를 먼저 기록한 후 정확한 두 ID에 pause만 실행한다. 현재 nginx maintenance 전환은 암호화 보관 이후 실행 담당의 별도 작업이므로 send가 이미 maintenance라고 가정하지 않는다.

실행 순서는 GitHub 두 배포 통제→restart fence 완료→완료 journal의 exact SHA를 최종 source에 pin→정확 CI→prepare/B 설치→pause/send다. pause 전 source가 fixed journal의 hash를 재확인하며 미확정·변경이면 앱을 pause하지 않는다. 최종 module/control/journal pin 미확정 상태는 실행 완료 상태가 아니다.

모든 source/control/archive Docker 호출은 고정 local unix socket, 전용 빈 session Docker config와 최소 환경을 사용한다. fork producer는 이미 hash-bound된 module snapshot을 상속하며 standard stdout/stderr는 `/dev/null`로 연결한다. 평문은 별도 inherited pipe를 통해 GPG stdin에 직접 쓰고, 성공 후 별도의1KiB control pipe에 고정 숫자 요약만 반환한다. 부모는 GPG ciphertext만 hash/count한다. producer·GPG·SSH RC0와 control proof, B의 bytes/hash가 모두 일치하고 마지막 control 재검사도 통과해야 `transferred_unverified`다.

B 수신 helper는 인자0, forced command `receive-data-snapshot-20261102-v1`만 허용한다. root0700 namespace 아래 `data.gpg.partial`을 exclusive 생성하고 fsync·동일FD 재해시 후 덮어쓰기 없는 link 승격으로 `data.gpg.pending`을 만든다. cipher cap은 archive cap+16MiB=`2300300288`B, 시작 여유는 cap+3GiB=`5521525760`B이며 매 chunk에도3GiB reserve를 유지한다. 실패 partial은 삭제하지 않으며 같은 namespace 재시도를 허용하지 않는다.

source 전체 deadline2400초 안에 archive1800초가 포함되고 receiver2400초, workflow outer2430초다. 실패·SIGINT/TERM/HUP는 child process group을 TERM→KILL→wait하고 모든 pipe를 닫은 후 terminal 실패 영수증을 남긴다. reap 불확실은 terminal로 기록하지 않는다. worker가 예상치 않게 고아가 되어도 상속된 lock을 유지하므로 동시에 cleanup하지 못한다. source GPG에는 공개 키만 있고 `--no-autostart`를 사용하므로 복호화 private-key cache를 만들지 않는다. Mac 복구 키 cache 정리는 별도 secure verifier의 책임이다.

cleanup은 terminal attempt와 같은 lock을 확인하고 정확 transport private/public key만 지운다. 실패 때도 자동 resume/stop/delete는 없으며 두 번째 pause 실패 시 첫 컨테이너의 pause도 유지한다. 원본 앱, PID, 자료, image와 B 암호문을 건드리지 않는다. 공개 결과는15필드 `phase,status,session,error,ssh_public_key,bytes,sha256,process_rc,backup_verified,source_bytes,archive_bytes,object_count,paused,operator_evidence_sha256,run`이며 backup_verified=false를 유지한다. prepare/cleanup의 counts와 operator SHA는 null, pause는 not_observed다. send 성공만 process_rc archive/gpg/ssh 모두0, paused 두 alias 모두paused와 고정 operator SHA를 가진다. 실패 pause_requested는 명령 시도 이후 실제 freeze 확인이 미완료일 수 있음을 보존한다.

`python3 -I -B -m unittest discover -s deploy/naver/tests -p test_retirement_data_archive.py -v`

fake Docker/proc/cgroup와 private 임시 합성 파일만 사용한다. pause/task/parent/FD/map/config 변경, 부분 stream, 정해진 크기·시간 상한, 정확 tar·manifest 계약과 노출 금지를 확인한다. Mac의 `/dev/fd` stat 차이는 시험 adapter에서만 보정한다. 실제 Linux 커널 freeze/운영 자료/서버/GPG/SSH 검증을 대신하지 않는다.
