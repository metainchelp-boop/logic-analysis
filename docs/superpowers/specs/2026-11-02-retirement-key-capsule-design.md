# 원본 키 파일의 전용 암호화 보존

기존 복구 사본 준비·서버 B의 별도 보관·전용 복구 키 선택·작업 계속 지시의 연속 구현이다. 이번 담당 범위는 새 소스 helper, 합성 시험, 이 설계뿐이다. 커밋·원격 실행·운영 원본 읽기는 루트가 담당한다.

## 범위와 선택

고정 원본은 `/root/ad-dashboard-deploy/data/secret.key`, `/root/content-studio-deploy/autobid/.env` 두 파일이며 합계64KiB 이하로 제한한다. env 구문이나 키 값을 해석하지 않는다. 파일 보존은 해당 파일에 유효한 원본 복호화 키가 있다는 증명이 아니다.

개별 파일을 콘솔로 복사하는 방식은 노출 경로를 늘리고, 평문 tar 파일을 만드는 방식은 불필요한 디스크 사본을 남긴다. 두 파일을 no-follow descriptor로 함께 고정하고, 제한된 메모리에 읽어 표준 USTAR로 구성한 뒤 GPG stdin에만 쓰는 방식을 선택한다. `ad-dashboard/secret.key`, `autobid/.env` 두 regular 멤버만 포함하고 mode0600·uid/gid/mtime0으로 고정한다. 원본 절대경로와 plaintext hash는 출력하지 않는다.

## 보안·실행 계약

- session `key-capsule-20261102-v1`, source `/root/.metainc-retirement-transfer/key-capsule-20261102-v1`, command `receive-key-capsule-20261102-v1`, B `/var/backups/metainc-app-retirement/key-capsule-20261102-v1/keys.gpg.pending`.
- 공개 GPG 수신자와 B host key는 검토된 이미지 보존의 공개 asset 및 SHA256/fingerprint와 동일하다. 입력은 `prepare`, `send`, `cleanup` 중 하나뿐이다. 별도 helper를 사용하며 기존 이미지 helper의 전역 값은 변경하지 않는다.
- B 수신기는 별도 설치한 고정 forced-command로만 진입하며 임시 SSH 인증은 restrict·PTY/forwarding 금지로 제한한다. receiver의 received_unverified 영수증은 독립 복호화 또는 복구 성공을 의미하지 않는다.
- 모든 원본 부모는 descriptor 기반 no-follow·root 소유·group/other 쓰기 금지가 기본이다. 단, 사전 목록 `APP_INVENTORY-41386297018.json:701–712`에서 확인한 `/root/ad-dashboard-deploy`의 uid501/gid50/mode0755 조합만 원본 읽기 경계에서 추가 허용한다. 같은 목록의 data 디렉터리와 secret.key는 root 소유다. 이 예외는 session·공개 asset·다른 경로에 적용하지 않으며 chmod/chown은 없다. 파일은 root 소유·regular·nlink1·group/other 쓰기 금지·크기 제한, 읽기 전후 inode/device/mode/uid/gid/nlink/size/mtime/ctime 및 부모 연결과 ctime을 대조한다. 두 descriptor를 함께 열고 전체 읽기 후 다시 확인한다. 회전·교체·크기 변화·권한 불일치는 실패한다.
- `prepare`는 원본 metadata만 확인하며 공개 GPG home·신규 SSH 전송 키를 전용0700 session에 만든다. `send`만 원본 body를 읽는다. 성공/실패 모두 원본 파일을 변경하지 않는다. 앱·DB·Docker·daemon 환경 조회는 없다.
- GPG와 SSH는 고정 argv·최소 환경·shell 없음·agent 없음·엄격한 host pin을 쓴다. 평문은 메모리와 GPG stdin만 거친다. core dump를 비활성화하고 소유한 mutable buffer는 종료 시 덮어쓴다. Python/OS 전체 메모리의 완전한 영구 삭제나 swap 비활성화를 주장하지 않는다.
- phase 전체300초, 암호문 최대1MiB, 통합 stderr64KiB, receipt stdout1KiB, source session filesystem 최소16MiB. bounded pipeline에서 GPG/SSH 두 종료 코드0, 암호문 bytes/SHA256, 엄격한 단일 JSON receipt를 함께 검증한다. 평문 archive를 만드는 별도 프로세스는 없으므로 process_rc는 gpg/ssh만 포함한다.
- 기존 prepare/send/cleanup lock·no-overwrite·attempt/terminal receipt 경계를 따른다. 실패나 강제 종료 후 같은 session을 재전송하지 않는다. 루트가 B 임시 인증을 먼저 철회한 뒤 cleanup은 전송용 SSH private/public 파일만 제거하고 receipts·공개 GPG home은 보존한다. 원본·수신 암호문·복구 개인 키는 삭제하지 않는다.

## 출력과 검증

출력은 고정10필드 JSON 한 줄이다. phase/status/session/error/ssh_public_key/source_size_bytes/bytes/sha256/process_rc/backup_verified만 허용하며 backup_verified는 항상false다. source_size_bytes는 prepare metadata 또는 send 실제 두 파일 크기 합계이고 bytes/hash는 암호문 값이다. prepared/transferred_unverified/transport_key_removed/already_closed/failed 상태를 사용한다.

1. 합성 원본의 arbitrary bytes가 두 tar 멤버에 정확히 보존되는지, prepare는 body를 열지 않는지 검증한다.
2. 부모·leaf symlink, hardlink, 소유·권한·크기, 중간 교체/변경, 동시 lock, no-overwrite, 미종료 attempt 재호출과 cleanup을 검증한다.
3. 합성 GPG/SSH에서 부분 쓰기·backpressure·단계 실패·크기/로그/시간 한계·receipt 불일치와 출력 canary 비노출을 검증한다.
4. source 구현과 별도 receiver/workflow의 독립 검토 후 루트가 정확한 최종 커밋 CI 및 실제 실행을 담당한다. 로컬 합성 시험은 운영 원본·SSH·독립 복호화 검증이 아니다.

로컬 집중시험43개 통과: 합성 filesystem/프로세스 경계, 고정 부모 소유권 예외, 원본 변경 감지, 준비 단계 body 미접근, 실제 공개키 전용 GPG→합성 receiver를 포함한다. 운영 원본·개인 복구 키·실제 SSH 접근은 수행하지 않았다.
