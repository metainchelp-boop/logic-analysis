# NAVER 과거 보관본의 서버 B 이전과 제한된 로컬 정리

이 도구는 이미 만들어진 과거 복구 사본을 회사 백업 서버 B에 암호화하여
보존하고, Mac에서 회수·복호화·원본 바이트 검증을 마친 뒤 운영 서버의
해당 파일만 정리한다. 설치나 실행을 자동으로 예약하지 않는다.
DB를 열거나 운영 서비스, 일일 백업의 `local`, `outgoing`, `state.json`을
읽고 바꾸지 않는다. 퇴역 이미지 삭제와 `/metainc01` 분류는 별도 작업이다.

## 고정 범위

- `/var/backups/metainc/naver-cold-archives/` 안에서
  `cold_backup_archive.py`의 기존 8개 프로필에 명시된 디렉터리만 허용한다.
  존재하는 모든 허용 디렉터리를 조사하며, 모르는 디렉터리·불완전한 구성은
  전체 작업을 중단한다. 각 폴더의 원본 manifest 2개와 manifest에 대응하는
  `engine.db*.gz`만 포함한다.
- `8c13`의 최종 위치는 위 cold 폴더 안의
  `20261103T143402Z-8c13b0b72a61-v1`이다. 과거 cold 합계와 8c13 크기를
  별도 합산하지 않는다. 새 plan의 실제 파일 목록과 바이트 수로 계산한다.
- `/var/backups/metainc/naver-engine-interrupted-20261106/`의
  `snapshot.sqlite.json`, `snapshot.sqlite.gz`, `packed.zip.broken`을 함께 보존한다.
  깨진 ZIP도 손실 없이 옮긴다. 이 묶음을 정상 일일 백업으로 등록하지 않는다.
- source의 평문 묶음 최대 11GiB, 암호문 최대 12GiB, plan 최대 256KiB이다.
  암호문은 B의 새 전용 폴더
  `/var/backups/metainc-app-retirement/naver-archives-20261106-v1/archives.gpg`
  에만 저장한다. 기존 ScaleForce 백업 및 완료된 퇴역 전송 세션은 건드리지 않는다.

## 파일과 실행 위치

| 파일 | 위치·역할 |
| --- | --- |
| `naver_archive_common.py`, `cold_backup_archive.py` | source와 Mac의 동일한 검증된 도구 디렉터리, 고정 프로필·형식·검증 |
| `naver_archive_source.py` | 운영 서버, 읽기 전용 plan/stream 및 별도 cleanup |
| `naver_archive_transport.py` | 운영 서버 send, Mac fetch |
| `preservation/recovery-public.asc`, `preservation/server-b-known-hosts` | transport 옆, 기존 공개키와 B 호스트 키의 고정 SHA 검증 |
| `naver_archive_receiver.py` | B, 새 제한 SSH 키의 강제 명령으로만 실행 |
| `naver_archive_recover.py` | Mac, 회수한 암호문의 인증 복호화와 바이트 검증 |
| `naver_archive_receiver_control.py` | B의 root로만 실행, 고정 세션 설치·정확한 인증 철회 |
| `naver_archive_receiver_operator.py` | Mac, 공개 helper SHA·호스트 키 검증 및 기존 관리자 SSH 경로로 control 실행 |

실행 전 최종 PR 커밋과 각 도구의 SHA256을 대조한다. root 실행 파일과
부모 디렉터리는 root 소유이며 다른 사용자가 쓸 수 없어야 한다. Mac에서도
동일하게 검토한 소스만 실행한다. 이 PR을 병합한다고 receiver, SSH 키,
서버 폴더가 설치되거나 전송·삭제가 실행되지는 않는다.

## 실행 전 확인

1. 기존 회사 복구 키의 공개 fingerprint와 Mac·오프라인 사본을 확인한다.
   도구는 기존 공개키 fingerprint를 고정하며, 개인 키를 source나 B에
   전송하지 않는다. 비밀번호는 Mac의 GPG pinentry에만 입력한다.
2. B의 현재 여유를 새로 읽는다. 수신 시작은 최소 15GiB,
   수신 중에는 최소 3GiB를 남기는 조건이다. 과거의 41GB 보고만으로 통과시키지 않는다.
3. **서로 다른 새 운송 SSH 공개키 두 개**와 각 장비의 현재 IPv4를 준비한다.
   새 B control은 키별 `restrict`, `from`, 설치 시점부터 180분 만료와 고정
   강제 명령을 사용한다. 키 생성·private key 이동은 수행하지 않는다.
   이전 퇴역 운송 키와 종료된 세션을 재활성화하지 않는다.
4. receiver가 허용하는 `SSH_ORIGINAL_COMMAND`는 아래 두 문자열뿐이다.
   source 송신과 Mac 회수 경로 모두 실제 허용 IP와 키 배치를 확인한다.
   이 세션은 두 작업이 끝나면 종료하고 SSH 허용 항목을 제거한다.

   ```text
   receive-naver-archives-20261106-v1
   fetch-naver-archives-20261106-v1
   ```

5. B의 `/var/backups/metainc-app-retirement` 및 전용 세션 폴더는 root:root
   0700, 상위 경로는 root 소유·그룹/전체 쓰기 금지여야 한다. 세션은 새 빈 폴더로
   control이 배타 생성한다. 미리 만들지 않는다. receiver는 기존 목적지나 partial을 덮어쓰거나 지우지 않는다.
6. 이 작업 동안 다른 운영자가 같은 과거 보관 폴더를 변경·정리하지 않는다.
   source 도구끼리는 부모 디렉터리 flock으로 조정하지만 기존 cold 생성기나
   root의 수동 조작까지 공유 잠금으로 막지는 않는다. 일일 백업은 대상 경로가 다르다.
   source의 공용 상위 `/var/backups/metainc`는 root 소유·그룹/전체 쓰기 금지이면
   0755도 허용하며 변경하지 않는다. 실제 cold 및 interrupted 보관 폴더는 0700이다.

## 순서와 통과 근거

아래 명령의 경로는 검토한 도구·전용 작업 폴더로 채운다. 실행 결과 원문은
공개 GitHub에 올리지 않는다. JSON 증거 파일은 private 폴더의 0600 일반 파일로
저장하고, 명령 종료 0과 파싱 성공을 확인한다. 실패 출력을 성공 영수증으로 쓰지 않는다.
Mac의 `/tmp`, `/var` 같은 심볼릭 링크 대신 실제 절대경로를 사용한다.

### 0. B의 새 수신 경로 설치와 종료

Mac operator는 같은 디렉터리의 controller·receiver·known-hosts 원문 SHA를
고정 검증한다. 기존 관리자 key는 해당 Mac 사용자 소유 0600 일반 파일이어야
하며 Python은 key 본문을 읽지 않는다. SSH만 인증에 사용하고 agent·proxy·
포트 전달을 끈다. 공개키와 요청 JSON만 SSH stdin으로 전송한다.

```text
python3 -I -B /tools/naver_archive_receiver_operator.py install \
  --send-public-key /private-work/send-key.pub \
  --fetch-public-key /private-work/fetch-key.pub \
  --source-ip CURRENT_VPS_IPV4 --fetch-ip CURRENT_MAC_IPV4 \
  --admin-key /private-existing-admin-key --output /private-work/b-install.json
```

현재 두 IP에 대한 `sshd -T`가 기본 primary/secondary 인증 파일, 공개키 인증,
root 로그인 허용, ForceCommand 없음 조건을 통과해야 한다. 기존 primary
`/root/.ssh/authorized_keys`는 내용·identity를 확인하고 변경하지 않는다.
secondary `/root/.ssh/authorized_keys2`가 이미 있으면 중단한다. 새 파일은
pending 작성·fsync 뒤 Linux `renameat2(RENAME_NOREPLACE)`로 게시한다.
다른 세션의 secondary를 지우거나 병합하지 않고 sshd 설정·서비스도 바꾸지 않는다.

고정 도구 경로는
`/root/.metainc-naver-archive-receiver/naver-archives-20261106-v1/receiver.py`다.
새 도구·데이터 폴더는 root:root 0700, receiver와 인증 파일은 0600이다.
두 키 모두 이 세션의 receive/fetch 두 명령에만 접근한다. 키별 action 분리는 없다.

송신·회수가 끝나면 설치 영수증 **파일 원문 SHA**를 별도로 확인하여 철회한다.
`status=failed`라도 `secondary_published=true`인 정확한 설치 영수증은 철회
근거로 사용할 수 있다. 공개키 원문은 영수증에 넣지 않는다.

```text
python3 -I -B /tools/naver_archive_receiver_operator.py revoke \
  --installed /private-work/b-install.json --receipt-sha256 INSTALL_FILE_SHA256 \
  --admin-key /private-existing-admin-key --output /private-work/b-revoke.json
```

철회는 설치 때의 secondary metadata·해시와 실제 두 인증 줄의 고정 명령·IP·
만료·공개키 해시까지 대조한 파일 하나에 한정한다. 파일이 없으면 `already_absent`
로 보고하며 그 시점의 부재만 확인한다. 데이터·도구 폴더는 지우지 않는다.
설치 실패는 부분 파일이나 활성 인증이 남을 수 있으므로 null/false를 부재로
해석하거나 새 output 경로로 맹목 재시도하지 않는다. operator가 원격 응답을
받지 못한 경우에도 원격 변경은 끝났을 수 있다. 실제 상태를 먼저 대조한다.
같은 UID의 동시 변경에 대한 원자적 compare-and-unlink 보장은 없으므로
설치·철회 중 해당 인증 파일을 다른 운영자가 수정하지 않는 창을 사용한다.

### 1. source plan — 읽기 전용 조사

```text
python3 -I -B /tools/naver_archive_source.py plan
```

stdout은 **줄바꿈 없는 canonical JSON**이다. 그대로 `plan.json`에 보관하고
파일의 SHA256을 기록한다. 파일 목록, 각 SHA·길이·inode·mtime·ctime·할당량과
전체 바이트를 검토한다. 각 gzip의 전체 해제 바이트도 기존 manifest와 대조한다.
plan 실패 시 운영 파일 변경은 없으며 다음 단계로 가지 않는다.
할당량 합계는 회수 후보량일 뿐 최종 확보 공간을 보장하지 않는다.

### 2. source send — 암호문 전송만

```text
python3 -I -B /tools/naver_archive_transport.py send \
  --plan /private-work/plan.json --plan-sha256 PLAN_SHA256 \
  --transport-key /private-work/new-transport-key \
  --session-dir /private-work/new-send-session
```

`session-dir`는 새 경로여야 한다. source plan과 현재 원본이 다시 일치해야 한다.
작은 manifest와 기존 gzip·깨진 ZIP을 스트리밍하고 재압축하지 않는다.
source 평문 묶음을 디스크에 만들지 않는다. 격리 GPG 홈에는 공개키만 넣는다.
암호화 AES256, GPG 압축 없음, 고정 수신자·고정 B 호스트 키를 사용한다.

송신은 암호문을 길이 프레임으로 전달하며 source·GPG 종료 0과 두 stderr의
EOF 뒤에만 END 프레임을 보낸다. 수신기는 END의 총길이·해시와 후행 EOF를
검증하기 전까지 partial을 최종 파일로 게시하지 않는다. 옛 raw 스트림과
호환되지 않으므로 transport·receiver를 같은 최종 버전으로 설치한다.

모든 프로세스가 종료 0이고 송신 암호문의 SHA·길이가 B의 같은 FD 재읽기
결과와 같을 때만 `sent_unverified`를 낸다. 이 결과는 복구 검증이나 삭제 허가가 아니다.
전용 송신 폴더에 작성된 `sent.json`과 그 **파일 원문 SHA256**을 별도로 보관한다.
stdout의 보기용 JSON과 파일 원문은 공백이 다를 수 있으므로 서로 해시를 혼용하지 않는다.
정상 END를 B가 게시한 뒤 SSH 응답이나 `sent.json` 기록만 유실될 수는 있다.
이때 자동 재전송·partial 삭제 없이 양쪽 실제 파일 상태를 대조한다.

### 3. Mac fetch — 회수한 암호문 대조

```text
python3 -I -B /tools/naver_archive_transport.py fetch \
  --sent-receipt /private-work/sent.json --receipt-sha256 SENT_FILE_SHA256 \
  --transport-key /private-work/new-transport-key \
  --output /private-work/archives.gpg
```

SSH가 종료 0이어야 하며 회수 파일 길이·SHA가 송신 영수증과 같아야 한다.
지정한 `--output` 파일에는 암호문만 저장하며 stdout은 `fetched_unverified`
JSON이다. 기존 파일을 덮어쓰지 않는다. 실패 시 partial 또는 이미 게시된
final이 남을 수 있으므로 두 경로를 대조하고 자동 재시도하지 않는다.
최종 hardlink 게시 뒤 partial을 unlink하기 직전에 fd·final·partial의
identity·소유·0600·nlink=2를 재확인한다. 교체가 관측되면 남겨 두고 중단한다.
검증 영수증은 원격 현재 파일의 존속·보존정책까지 보장하지 않으므로 B 파일의
위치, 소유·접근권한과 보존 책임을 운영 인수인계에 함께 남긴다.

### 4. Mac recover — 인증 복호화·원본 바이트 검증

```text
python3 -I -B /tools/naver_archive_recover.py \
  --plan /private-work/plan.json --plan-sha256 PLAN_SHA256 \
  --transfer-receipt /private-work/sent.json \
  --cipher /private-work/archives.gpg --gnupg-home /private-existing-key-home \
  --output /private-work/recovery.json
```

GPG 종료 0, `DECRYPTION_OKAY`, `GOODMDC`, 고정 primary recipient에 해당하는
`DECRYPTION_KEY`를 모두 요구한다. 묶음의 정확한 구성·각 파일 해시·길이·EOF와
각 gzip의 해제 원본 해시·길이를 검증한다. 기본 모드는 평문을 디스크에 쓰지 않는다.
기존 source manifest 원문도 그대로 대조한다. interrupted snapshot은 보존 당시
JSON에 대조하며 데이터베이스의 업무적 정합성이나 SQLite 복원 성공으로 표현하지 않는다.
입력 파일은 현재 사용자 또는 root 소유 0600 일반 파일, hardlink 1개여야 하며
GPG 홈과 결과 폴더는 현재 사용자 소유 0700이어야 한다. GPG는 고정 설치 후보
경로에서 찾고 실행 파일 소유·권한을 확인한다. 설치된 패키지 관리자와 실행 파일은
신뢰 전제이며 GPG 바이너리 자체의 해시를 고정하지 않는다.

실제 파일 재구성이 필요한 복구 연습에는 위 명령에
`--restore-dir /private-work/new-isolated-restore`를 추가한다. 먼저 무쓰기 검증을
끝낸 뒤 같은 암호문을 다시 인증 복호화하여 새 0700 폴더에 원래 gzip·manifest·
깨진 ZIP을 0600으로 재구성한다. 원래 소유·mtime은 plan에 남지만 자동 복원하지 않는다.
복원 시작에는 `total_bytes + 512MiB`, 쓰는 동안에도 최소 512MiB 여유를 요구한다.
3600초 제한은 두 번의 복호화와 디스크 재해시를 합한 전체 작업에 적용한다.
실패한 복구 폴더는 검증 완료본이 아니며 자동 정리하지 않는다.
cold의 DB 복구는 기존 `cold_backup_archive.restore_isolated` 경로에서 별도
격리 검증하고, interrupted gzip은 검증된 JSON과 함께 따로 다룬다.

### 5. source cleanup — 별도 검증 증거에 결속한 파일 정리

운영자는 완료된 Mac 복구 영수증을 검토하고 **영수증 파일의 SHA256을 별도
채널/기록으로 확인한 후** source의 private 위치에 root:root 0600으로 설치한다.
이 receipt는 암호학적 서명이 아니다. root 운영자가 제공한 증거의 출처와
검토를 신뢰하는 수동 작업이다. 임의 JSON의 `verified` 값이나 송신 성공만으로
자동 삭제하지 않는다. plan·암호문·회수 검증·대상 목록·B 보존 위치를 함께 검토한다.

```text
python3 -I -B /tools/naver_archive_source.py cleanup \
  --plan /private-work/plan.json --plan-sha256 PLAN_SHA256 \
  --recovery-receipt /private-work/recovery.json --recovery-sha256 RECOVERY_FILE_SHA256 \
  --confirm REMOVE_ONLY_RECOVERY_VERIFIED_NAVER_ARCHIVES_20261106
```

원본 전체를 재해시하고 gzip 해제 대조까지 다시 통과해야 정리가 시작된다.
다른 파일, hardlink, symlink, 파일 교체, 계획 변경을 발견하면 중단한다.
첫 삭제 전에 고정 journal
`/var/backups/metainc/naver-archives-20261106-v1.cleanup.jsonl`을 배타 생성한다.
각 파일 직전 다시 identity·hash를 확인하고 확정 파일 하나씩만 unlink·fsync한다.
모든 그룹의 payload(`.gz`, `packed.zip.broken`)를 먼저 정리하고 모든 JSON
manifest는 마지막에 정리한다. wire plan 순서·해시는 유지하며 journal은 실제
삭제 순서를 기록한다. payload 단계에서 멈추면 manifest가 남는다.
부모 폴더는 남긴다. `rm -rf`, wildcard, image prune, live DB 작업은 없다.

중간 실패는 일부 파일이 이미 정리됐을 수 있다. journal은 상태별 JSON 한 줄씩
추가하고 fsync하며 이전 기록을 잘라내지 않는다. 마지막 줄이 불완전하면 성공으로
읽지 않는다. 직전 완전한 기록의 `pending`,
`removed_files`, 실제 남은 파일과 B 복구 자료를 대조한다. journal이 이미 있으면
자동 재실행하지 않는다. receipt의 false/null이나 오류 코드만으로 삭제 가능하다고
해석하지 않는다. 마지막 파일 FD가 닫힌 뒤 `df`로 실제 여유를 새로 확인한다.
그 다음 정기 백업 상태와 관제 응답을 별도로 확인한다.

## 형식과 보존

묶음은 `NAVER-ARCHIVE-V1\n` magic, 8바이트 big-endian plan 길이,
canonical plan JSON, plan 순서의 정확한 파일 바이트이다. 압축 아카이브를 다시
압축하지 않고 경로 해석·tar 추출을 피하는 작은 고정 형식이다. trailing 데이터는
거부한다. 복구에는 최종 도구 버전, plan, 송신 영수증, Mac 검증 영수증,
B 암호문과 별도 복구 키가 필요하다. 키와 데이터를 같은 위치에 묶어 보관하지 않는다.

합성 시험과 CI는 실제 서버 B 전송, 실제 회사 키 복호화, 실제 디스크 확보와
구분해 기록한다. 운영 실행 전에는 B에 보존됐거나 로컬 정리가 끝났다고 보고하지 않는다.

전송 바깥 형식은 `NAVER-ARCHIVE-CIPHER-FRAMES-V1\n`,
`uint32 big-endian 길이(1..65536) + 암호문` 반복,
`uint32 0 + uint64 암호문 총길이 + SHA256 raw 32바이트 + EOF`이다.
최대 196608 프레임·12GiB이며 영수증 해시·길이는 framing을 제외한 암호문만
계산한다. receiver는 길이 상한, 프레임 수, 절단, END 해시와 후행 데이터를 검사한다.
