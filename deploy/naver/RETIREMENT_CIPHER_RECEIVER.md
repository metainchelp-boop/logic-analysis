# 광고센터 image 암호문 일회 수신기

`retirement_cipher_receiver.py`는 서버 B에서만 설치·실행하는 고정 forced-command 수신기다. 이 파일 자체는 계정·SSH 키·디렉터리·서버 설정을 설치하지 않는다. 운영 담당이 이번 전송의 source IP, `restrict`, 만료시각, 고정 Python/receiver 명령을 별도로 검증해 전송 전용 공개키 한 항목만 추가한다. 기존 회사 수신기·백업 키·보존정책은 변경하지 않는다.

- 원격 요청은 정확히 `receive-ad-image-20261102-v1`이어야 한다. 인자를 거부하고 명령문·shell을 실행하지 않는다.
- 경로는 `/var/backups/metainc-app-retirement/ad-image-20261102-v1` 하나뿐이다. 운영 담당이 미리 준비한다. `/`·`/var`·`/var/backups`는 root:root·group/world 쓰기 금지, 전용 부모와 마지막 디렉터리는 root:root 0700이어야 한다. 모든 부모는 no-follow descriptor로 고정하고 이름 연결·inode·권한·소유를 다시 대조한다.
- `.receive.lock`은 root:root 0600·일반 파일·하드링크 1개만 허용하고 nonblocking flock을 사용한다. 수신 파일도 0600이며 기존 `image.gpg.partial` 또는 `image.gpg.pending`가 있으면 덮어쓰거나 지우지 않는다.
- 시작 직전 가용량 2GiB 이상, 입력 상한 512MiB, 전체 alarm 900초다. 블록마다 남은 실제 여유를 다시 검사한다. 2GiB는 시작 조건이며 수신 후 항상 2GiB를 남기는 보장은 아니다. 중단 불가능한 커널 I/O까지 900초 내 해제한다고 보장하지 않으므로 호출 측 SSH/작업 timeout도 필요하다.
- 입력은 opaque 암호문 binary stream이다. receiver는 GPG 형식·복호화 가능성·image 내용을 판정하지 않는다. 파일 내용·경로·원문 예외는 출력하지 않는다.

수신은 exclusive `image.gpg.partial`에만 쓴다. EOF·크기 검사 후 파일 fsync, 같은 descriptor 재읽기 SHA-256/길이 대조, no-overwrite hardlink 발행과 디렉터리 fsync를 거쳐 `image.gpg.pending`을 만든다. 정상 완료 시 partial 별칭만 제거한다. 실패·timeout 시 partial을 자동 삭제하지 않는다. 발행 중 장애면 두 이름이 같은 inode를 가리키거나 pending만 남을 수도 있으며, 실패 영수증의 digest는 null이다. 기존 사본이나 부분 파일을 자동 정리·재사용하지 않는다.

정상 stdout은 1KiB 이하 JSON 한 줄, 종료 코드 0이다.

```json
{"status":"received_unverified","bytes":257,"sha256":"<ciphertext sha256>"}
```

실패는 고정 상태명·수신 바이트 수·`sha256:null`, 종료 코드 2다. `received_unverified`는 보관·복구 검증 완료가 아니다. source의 Docker/GPG/SSH 종료 코드가 모두 0이고 source 암호문 길이/해시와 영수증이 일치해야 전송 성공으로 기록한다. 이후 독립 회수·인증 복호화·정확한 image config digest/레이어 검증이 별도로 필요하다. 이 단계는 앱 writer·원래 앱 키·DB 일관성·종료 안전성을 증명하지 않는다.

로컬 합성 검사:

```sh
python3 -I -B -m unittest discover -s deploy/naver/tests -p 'test_retirement_cipher_receiver.py' -v
```

테스트는 임시 synthetic namespace와 가짜 payload만 사용하며 실제 서버·키·고객 자료를 읽지 않는다. 운영 설치·Linux/SSH 강제명령·실제 source→B 전송 성공의 증거가 아니다.
