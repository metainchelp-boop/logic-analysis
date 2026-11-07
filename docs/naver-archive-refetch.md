# 과거 NAVER 보관본 전체 재회수

원래 서버 B에 완성된 암호문 한 개를 다시 받기 위한 별도 도구다. [설계와 시간 계산](superpowers/specs/2026-11-07-naver-refetch-only-design.md)을 먼저 확인한다. 기존 send·recover·원본 정리 도구는 변경하지 않는다. 이번 변경의 검토·CI 통과는 운영 설치 승인과 실제 복구 성공을 뜻하지 않는다.

## 실행 전 준비

1. 검토된 정확한 커밋에서 기존 11개 공개 도구·asset과 새 `naver_archive_refetch_receiver.py`, `naver_archive_refetch_operator.py`, `naver_archive_refetch_client.py`를 별도 새 Mac 도구 폴더에 설치한다. 원래 도구는 덮어쓰지 않는다. 공개 파일 SHA와 각 새 모듈의 종속 코드 핀을 검증한다.
2. 원래 plan, sent, B install, B revoke 영수증의 원문 SHA를 보존 기록과 대조한다. 기존 client·SSH·B receiver 종료와 이전 인증 철회를 확인한다. 원래 `archives.gpg.partial`의 소유·0600·nlink 1·전체 SHA·identity를 확인한다. 개인 키 본문은 읽지 않는다.
3. 현재 Mac 공인 IPv4와 원래 회수 공개키를 확인한다. 새 전용 인증은 그 IP 하나와 키 하나만 허용한다. 기존 send 키는 설치하지 않는다. B의 기존 데이터·도구 폴더나 이전 인증 기록을 삭제해 가드를 통과시키지 않는다.
4. 기존 부분 파일을 남긴 상태에서 새 암호문 전체와 격리 복원에 필요한 Mac 공간을 확인한다. 이 회차의 약 3.26GB 암호문과 약 3.26GB 압축 보관본 복원, 512MiB 이상의 여유가 필요하다. 디스크 여유는 실행 시점에 다시 측정한다.

## 새 인증 설치

아래 인자는 모두 검증한 파일 경로·공개 메타데이터다. 비밀번호·개인 키 본문을 인자나 환경 변수에 넣지 않는다. `--output`은 존재하지 않는 새 파일이어야 한다.

```text
python3 -I -B <새도구>/naver_archive_refetch_operator.py install
  --plan <작업폴더>/plan-bundle.json --plan-sha256 <원문SHA>
  --sent <작업폴더>/sent.json --sent-sha256 <원문SHA>
  --old-install <작업폴더>/b-install.json --old-install-sha256 <원문SHA>
  --old-revoke <작업폴더>/b-revoke.json --old-revoke-sha256 <원문SHA>
  --fetch-public-key <작업폴더>/fetch-key.pub --fetch-ip <현재MacIPv4>
  --admin-key <기존관리자키경로>
  --output <작업폴더>/b-refetch-install.json
```

설치는 B의 원래 primary와 철회 증거, 기존 데이터 잠금, 암호문 전량 SHA와 길이를 확인한 후 새 도구·config·회수 전용 인증을 게시한다. 소요 상한은 B 480초, Mac 교환 600초다. 성공 영수증의 원문 SHA, `config.issued_at`, `start_before`, `expires_at`을 기록한다. 설치 후 30분 안에 회수를 시작해야 하며 인증은 발급 후 6시간이다.

설치가 실패하거나 응답을 잃으면 예약된 영수증 파일과 원격의 실제 상태를 조사한다. 빈 출력이나 `secondary_published=false`는 원격 무변경 증거가 아니다. 자동 재설치·디렉터리 정리·인증 연장은 하지 않는다. 게시된 실패 영수증에 정확한 secondary metadata가 남은 경우에도 그 증거를 대조한 뒤 정확 철회만 수행한다.

## 전체 회수

기존 부분 파일과 새 출력·새 결과 영수증은 같은 0700 작업 폴더에 둔다. 새 출력 이름은 아래처럼 고정돼 있어 원래 파일에 이어 쓰지 않는다.

```text
python3 -I -B <새도구>/naver_archive_refetch_client.py
  --plan <작업폴더>/plan-bundle.json --plan-sha256 <원문SHA>
  --sent-receipt <작업폴더>/sent.json --receipt-sha256 <원문SHA>
  --installed <작업폴더>/b-refetch-install.json --install-sha256 <새설치원문SHA>
  --fetch-public-key <작업폴더>/fetch-key.pub --transport-key <작업폴더>/fetch-key
  --preserved-partial <작업폴더>/archives.gpg.partial --preserved-sha256 <기존부분파일SHA>
  --output <작업폴더>/archives-refetch-20261107-v1.gpg
  --output-receipt <작업폴더>/refetch-result.json
```

서버는 4시간, Mac 전체 작업은 4시간 30분으로 제한한다. 단계별로 시간을 다시 부여하지 않는다. 만료나 저속 때문에 실패하면 자동 재접속하지 않는다. 0.3MB/s가 유지될 때 전송 계산은 약 181분이며 완료를 보장하는 값은 아니다.

성공은 종료 0, `fetched_unverified`, 원래 암호문 길이·SHA, SSH 종료와 EOF, 로컬 전량 재읽기, 배타 게시, 기존 부분 파일의 전후 대조가 모두 일치한 상태다. 이 결과는 복호화 성공이 아니다.

실패 시 원래 부분 파일과 새 partial/final, 결과 영수증을 보존한다. `preserved_unchanged=false`는 대조를 완료하지 못했을 수도 있으므로 변조 확정이나 삭제 가능으로 해석하지 않는다. 모든 바이트가 도착했어도 SSH nonzero, 시간 초과, 게시 실패가 있으면 별도 조사 전 성공으로 취급하지 않는다.

## 복구 검증과 철회

전체 회수 성공 뒤 기존 `naver_archive_recover.py`를 원래 plan/sent와 새 완성 암호문에 실행한다. 격리 복원 폴더와 recovery 영수증은 각각 새 경로다. 전용 복구 키 비밀번호는 Mac 보안 입력창에서만 받는다. 기존 검증은 GPG 인증·키 지문·종료 0, 내부 파일·압축 전후 원본 SHA/길이, 격리 복원과 재대조를 요구한다.

성공·실패 모두 실행 프로세스 종료와 실제 파일 상태를 확인하고 새 설치 영수증에 결속해 철회한다. 철회가 활성 연결을 종료시킨다고 간주하지 않는다.

```text
python3 -I -B <새도구>/naver_archive_refetch_operator.py revoke
  --installed <작업폴더>/b-refetch-install.json --receipt-sha256 <새설치원문SHA>
  --admin-key <기존관리자키경로>
  --output <작업폴더>/b-refetch-revoke.json
```

철회 성공은 `revoked` 또는 실제 secondary 부재를 확인한 `already_absent`, primary 불변과 정확한 설치 영수증 결속을 함께 확인한다. 새 도구 폴더·B 암호문·Mac 부분 파일·키를 지우지 않는다. 복구 영수증 검증 뒤 VPS 원본 정리 여부는 기존 담당 절차로 처리한다.
