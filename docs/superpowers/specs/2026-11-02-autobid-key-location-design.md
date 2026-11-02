# 자동입찰 원래 키 보관 후보의 메타데이터 확인

2026-11-02. 기존 세 앱 철거·복구 준비 승인과 사용자의 작업 계속 지시를 잇는 좁은 조사다. 원래 배포 장비/계정을 사용자가 기억하지 못하므로 기존 소스가 복제한 설정 파일 후보 한 곳의 존재만 확인한다. 새 보관용 GPG 키와 기존 앱 Fernet 키는 서로 다른 역할이다. 이 구현은 실제 서버 조회·키 회수·배포·철거를 수행하지 않는다.

## 접근 비교와 선택

1. 기존 runner 실행 기록 재조회: 이미 실행 주체를 확인하지 못했고 새 위치 근거가 없으므로 같은 조회만 반복하지 않는다.
2. **확인된 checkout 안의 고정 후보 메타데이터 조회(선택):** 콘텐츠 저장소 배포 workflow는 `~/.autobid/enc.key`를 checkout의 `autobid/.env`로 복제한다. 기존 VPS inventory가 확인한 `/root/content-studio-deploy` 아래에서 `/root/content-studio-deploy/autobid/.env` 하나만 확인한다. 이 checkout에서 자동입찰을 배포했거나 이 파일에 원래 키가 남아 있다는 결론은 아직 내리지 않는다.
3. 홈·파일시스템·환경·프로세스 광역 탐색: 승인된 관찰 경계를 넘고 비밀 노출 가능성이 있어 제외한다. runner나 root의 홈을 추정해 추가 경로를 열지 않는다.

## 관찰 계약

- Python 표준 라이브러리 helper 하나, 인자/입력 경로 없음. 고정 부모 세 개와 `.env`만 처리한다. 기존 공용 root/data allowlist는 수정하지 않는다.
- `/`부터 각 부모를 `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`로 열고, no-follow stat과 열린 descriptor의 device/inode/유형·권한·소유를 대조한다. leaf는 no-follow stat만 하며 open/read/hash/파싱하지 않는다.
- leaf stat 뒤 각 부모의 **이름을 원래 부모 descriptor 기준으로 다시 stat**하여 열린 디렉터리와 같은 identity인지 확인한다. 마지막 leaf metadata도 재대조한다. missing 역시 같은 이름의 재조회와 열린 부모 연결 검증 후에만 absent로 기록한다. 링크·비정규 파일·권한 오류·변경·상한은 fail-closed다.
- 출력은 고정 alias, 존재/종류, 숫자 metadata, 고정 실패 enum, UTC 관찰 시각만. 원문 경로·예외·파일명·환경값·키 원문/해시는 출력하지 않는다. `original_key_available=unknown`, `stop_safety=not_determined`는 모든 결과에서 유지한다.
- 성공은 한정된 두 시점의 경로 메타데이터 관찰이다. 원자적 snapshot, 키 포함 여부, 키 일치/복구 가능성, 전체 writer 부재를 뜻하지 않는다. 최대 5초 alarm과 4KiB JSON 한도, workflow 외부 20초 timeout을 둔다. 커널의 중단 불가능 I/O까지 시간 내 해제한다고 보장하지 않는다.

## 수동 workflow

기존 콘텐츠 preflight의 대표 actor/triggering_actor·main 검사, 고정 SSH host fingerprint, 검증된 helper hash, 실행 ID/attempt별 exclusive 0700 디렉터리, root 소유 공개 helper 한 파일 전송, 좁은 정리를 재사용한다. 별도 concurrency, cancel-in-progress false, contents read만 허용한다. 경로 입력·자동 push 트리거·앱 코드 실행·제품 배포는 없다. 기존 배포 제외 목록에 새 workflow 한 줄, 합성 PR 검사 목록에 새 workflow 한 항목만 추가한다.

## 구현 및 검증 순서

1. 최신 main의 격리 worktree에서 helper와 테스트를 추가한다. 임시 합성 디렉터리의 정상/부재/링크/비정규 파일/권한/부모 교체/leaf 교체를 검사하고 실제 후보를 열지 않는다.
2. 모든 파일 read/open과 환경·subprocess 접근 canary를 통해 leaf 본문 접근·출력 누출이 없는지 검사한다. CLI 인자는 파일 접근 전에 거절하고 deadline/예외가 고정 enum만 반환하는지 확인한다.
3. 수동 workflow의 실제 Bash guard를 사용자/재실행자/ref/지문별로 실행한다. 전송·cleanup·hash·timeout·배포 제외와 PR 검사 연결을 소스 경계 시험으로 확인한다.
4. 기존 `deploy/naver/tests` 전체와 shellcheck, diff/비밀정보 검사 및 독립 검토를 거친다. 구현 담당은 커밋/푸시/운영 실행 없이 정확한 변경 파일과 검사 결과를 루트에 전달한다.

이 문서는 경로·실패 계약과 검사 순서를 자체 검토했다. 추가 사용자 승인을 반복 요청하지 않고 기존 준비 승인 범위에서 구현하며, 새 경로나 내용 읽기로 자동 확대하지 않는다. 별도 writing-plans 스킬은 설치되어 있지 않아 위 순서를 구체 실행 계획으로 사용한다.
