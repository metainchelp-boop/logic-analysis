# 광고센터 고정 이미지의 암호화 보존: 원본 측

2026-11-02. 기존 복구 사본 준비·서버 B 보관·전용 복구 키 선택 및 작업 계속 지시의 연속 범위다. 첫 차수는 이미지 하나만 보존하며 앱 volume·DB·별도 설정/키 파일 접근·컨테이너 중지·삭제는 포함하지 않는다. 이미지 내부에 포함된 설정이나 비밀은 해석하지 않고 암호화해 취급한다. 실제 이미지 목록은 실행 직전 다시 대조한다.

## 고정 계약

- session: `ad-image-20261102-v1`, 원본 전용 경로 `/root/.metainc-retirement-transfer/ad-image-20261102-v1`.
- image: `sha256:959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922`, inspect Size 최대256MiB. 이미지 이름/tag·임의경로·Docker context를 입력받지 않는다.
- 수신자: `78076C3BC580EB5AC684EDE8BE5DAF3D1B780CA5`. helper 옆 `recovery-public.asc`는 승인된 공개 asset SHA256으로 고정한다. 기존 키 저장소·에이전트·private GPG 키에 접근하지 않는다.
- 목적지: `root@139.162.109.181`, 강제명령 `receive-ad-image-20261102-v1`. helper 옆 `server-b-known-hosts`의 승인된 SHA256 및 공개 호스트 지문을 고정한다. host key 자동등록·agent 전달·원격 임의명령은 없다.

## 선택한 실행 방식

로컬 평문 tar 작성은 제한된 VPS 공간과 자료 노출을 늘린다. `docker save → gpg encrypt → ssh forced receiver`의 pipe를 선택한다. 암호문만 중계하며 크기·SHA256을 계산하고 receiver의 `received_unverified` 영수증과 대조한다. Docker daemon 자체가 save 과정에서 내부 임시파일을 만들 수 있으므로 **디스크를 쓰지 않는 방식이라고 주장하지 않는다**.

`prepare`는 root·고정 실행파일·no-follow 디렉터리·exclusive session을 확인하고 공개 asset 및 격리 GPG 공개키 저장소를 만든다. Docker root/driver/version과 systemd docker MainPID의 comm/starttime을 제한 조회한다. 승인된 daemon 환경 점검은 `/proc/<PID>/environ`을 최대64KiB 메모리로 읽고 `DOCKER_TMPDIR`, `TMPDIR`만 허용 경로와 대조한다. 나머지 값은 해석·저장·출력하지 않는다. 따라서 환경 읽기0이라고 보고하지 않는다. root가 `/var/lib/docker`와 다르거나 임시 경로가 `/tmp`, `/var/lib/docker/tmp` 외이면 거부한다. `/var/lib/docker`와 `/tmp`에서 가용3GiB 이상을 prepare/send 직전에 확인하고 기본 Docker tmp가 같은 filesystem인지 검사한다. [Moby v27.5.1의 prepareTempDir](https://github.com/moby/moby/blob/v27.5.1/daemon/daemon.go#L1351)은 DOCKER_TMPDIR 또는 Docker root/tmp를 사용한다. 다른 실행조건은 추정하지 않고 거부한다. daemon PID/시점 조회 실패를 안전으로 바꾸지 않는다. SSH ed25519 운반용 키는 신규 전용 파일0600로 생성하고 public 부분만 반환한다.

`send`는 준비 영수증과 공개키를 재대조하고 단 한번의 attempt marker를 exclusive 기록한다. Docker archive plaintext는 gpg stdin에만 연결하며 읽거나 로그로 복사하지 않는다. 암호문 최대512MiB, 통합 stderr64KiB, receiver stdout1KiB, 사전 점검을 포함한 phase 예산900초를 넘으면 세 프로세스를 종료·회수하고 실패 영수증만 남긴다. 세 종료 코드0과 암호문 크기/해시·중복 필드와 여러 줄을 거부하는 receiver JSON을 모두 대조한 뒤 전송 영수증을 기록한다. 전송 성공은 독립 복호화·복구 검증이 아니다.

`cleanup`은 같은 nonblocking exclusive lock 아래 단말 영수증 또는 미전송 준비 상태를 확인하고 전용 SSH private/public 두 파일만 제거한다. 공개 GPG 저장소와 안전한 영수증은 보존한다. 송신 도중 강제 kill되어 단말 영수증이 없으면 active 여부를 추정하지 않고 cleanup을 거부한다. 이 상태의 재전송 거부도 단말 영수증을 만들지 않는다. 루트가 B의 해당 임시 SSH 인증을 먼저 철회한 뒤 실행한다. 원본 앱·이미지·수신 암호문·복구키는 건드리지 않으며 정리 성공을 백업 성공으로 보고하지 않는다. 동일 session 재준비·재전송은 금지한다.

## 구현과 검증

1. source helper·합성 단위시험·이 문서만 수정한다. workflow와 receiver는 별도 파일 소유자가 구현한다.
2. 합성 filesystem에서 no-follow·권한·동시 lock·no overwrite·phase 전이·실패 후 정리를 검증한다.
3. 합성 Docker/GPG/SSH 프로세스로 정상 pipe, 단계별 실패, 일부 쓰기, 조기 EOF, 초과 크기/로그/시간, 영수증 불일치를 검사한다. 운영 바이너리·서버·키는 실행하지 않는다.
4. 로컬 집중검사·독립 검토 후 루트가 정확한 커밋의 CI/비밀정보 검사·수동 실행을 담당한다. 구현 담당은 커밋·푸시·원격 실행을 하지 않는다.

로컬 source 집중시험37개 통과: 합성 filesystem/프로세스 경계와 승인된 공개 GPG asset의 공개키 전용 import/encrypt를 포함한다. Linux 운영 Docker/systemd/proc, 실제 SSH/수신기 연결, 원본 이미지 전송·독립 복호화는 로컬 시험으로 검증하지 않았다.
