# 네이버 관제 엔진 — S14·S16 패키징·배포 전 점검

현재 문서는 **배포를 승인하거나 실행한 기록이 아닙니다.** 승인 범위는 로컬 개발·합성 시험이며, 머지·배포·실계정 읽기·회사 서버에 알림이나 숫자를 보내는 일은 하지 않았습니다. Q7은 대표님 승인에 따라 SQLite WAL과 단일 쓰기 소유자를 사용합니다. 자동 입찰·키워드 단위 쓰기는 포함하지 않습니다.

## 1. 현재 가능한 것과 차단된 것

- `python -m naver_runtime check-config`: 비밀값 원문 없이 실행 설정 검사.
- `python -m naver_runtime dry-run`: 현재 설정과 차단 상태를 출력하며 DB·키·네트워크를 열지 않습니다. 합성 업무 흐름 시험은 아래 Linux CI의 unittest로 별도 실행하며, 이 명령 성공을 업무 동작 검증으로 쓰지 않습니다.
- `python -m naver_runtime run`: 별도 엔진 프로세스. 모든 기능이 꺼진 기본값에서는 외부 업무 호출 없이 유닉스 소켓의 최소 상태 응답만 제공합니다.
- S16의 일회용 코드·브라우저 검증자 교환과 웹 연결은 구현됐지만 `NAVER_ENGINE_WEB_ENABLED=false`가 기본입니다. `true` 설정 자체는 허용하며, 실제 `run`은 관제 전용 교환 키 또는 자체 서명 값이 없거나 유효하지 않으면 DB를 열기 전에 **시작 전 거절**합니다. `check-config`·`dry-run`은 키를 검사하지 않습니다. 구현·합성 시험 성공은 웹 활성화나 운영 배포 승인이 아닙니다.
- ③의 `NAVER_AUTO_WEB=off`, `NAVER_AUTO_ENGINE=`도 기본값입니다. 엔진 설정과 ③ 설정은 서로 다른 파일이며 한쪽만 바꿔서는 공개 승인 조건을 만족하지 않습니다.
- 광고주 공유 화면 「광고 성과」 연결(G1~G3), 회사 다른 서버에 암호화 백업이 실제 도착·복원되는지, 공유 서버 자원 여유는 아직 운영 확인이 필요합니다. 해당 게이트가 남으면 S14 전체나 배포 준비 완료라고 보고하지 않습니다.

## 2. 파일·프로젝트 경계

| 파일 | 역할 |
|---|---|
| `Dockerfile.naver-engine` | Python 3.12 전용 이미지. 순수 `app.naver_auto`만 함께 포함 |
| `Dockerfile.naver-engine.dockerignore` | 엔진 코드 허용 목록. ③ 코드·레거시 문서·DB·키를 build context에서 제외 |
| `compose.naver-engine.yml` | 명시 프로젝트 `naver-engine`, 단일 서비스, 호스트 포트 없음 |
| `deploy/naver-engine.env.example` | 전부 꺼진 예시. 실제 키 없음 |
| `deploy/naver-engine-ad-api.override.yml` | 기존 ③에 소켓 **폴더**와 보조 그룹만 추가하는 검토 파일 |
| `deploy/naver-engine-backup.override.yml` | 공개 인증서·전송 인증키·고정 호스트키 파일의 읽기 전용 mount |
| `deploy/naver-engine-nginx.conf` | 운영 ③ `server {}` 안에 넣는 검토용 include. 전체 nginx 교체 파일 아님 |

기존 `docker-compose.yml`에는 S16 광고센터 전용 교환 키의 선택적 환경 전달(빈 기본값)만 추가합니다. 기존 포트·DB·사용자·권한과 `Dockerfile`, `deploy/nginx-ad.metainc.co.kr.conf`는 바꾸지 않습니다. 옛 자동입찰 프로세스를 연결하거나 실행하지 않습니다. 엔진은 ③와 compose 프로젝트·이미지·데이터를 분리합니다. `replicas`를 늘리거나 두 `run`을 같은 DB에 연결하지 않습니다. 파일 자체의 독점 잠금은 실수 방어이지 다중 작성자 운영 기능이 아닙니다.

### 승인 뒤 사용할 경로 배치

| 호스트 경로 | 컨테이너 경로 | 소유·권한 |
|---|---|---|
| `/srv/metainc/naver-engine` | `/opt/naver-engine` 이미지 코드 | 코드만, 실행 중 읽기 전용 |
| `/var/lib/metainc/naver-engine` | `/var/lib/naver-engine` | UID:GID `10001:10001`, 폴더 `0700`, DB·WAL·SHM `0600` |
| `/run/metainc/naver-engine` | `/run/naver-engine` | `10001:10001`, 폴더 `0750`, 소켓 `0660` |
| `/var/backups/metainc/naver-engine` | `/var/backups/naver-engine` | `10001:10001`, 폴더 `0700`, 백업 `0600` |
| `/etc/metainc/naver-engine/runtime.env` | 환경으로만 주입 | 운영자가 관리, `0600`, 코드 동기화 대상 밖 |

컨테이너는 비루트 UID:GID `10001:10001`, 읽기 전용 루트, capability 제거, 권한 상승 금지, `/tmp`만 임시 쓰기를 사용합니다. 웹 API와 예약 실행은 같은 UID·단일 쓰기 소유자를 사용합니다. WAL 읽기에도 SHM이 필요하므로 엔진의 데이터 폴더는 읽기·쓰기로 붙입니다. ③ 중계에는 **엔진 DB를 붙이지 않고**, 소켓 폴더만 읽기 전용으로 붙입니다. 유닉스 소켓 연결 자체는 읽기 전용 mount에서도 가능합니다. ③ 기존 사용자·`/app/data/app.db`·`/app/data/secret.key` 소유권은 바꾸지 않습니다.

호스트 폴더는 승인된 운영 작업에서 미리 준비합니다. `create_host_path: false`이므로 누락된 경로를 Docker가 root 소유로 조용히 만들어 주지 않습니다. `/run`은 재부팅 때 사라질 수 있으므로, 소유·권한을 재생성할 운영 절차를 먼저 정해야 합니다. **소켓 파일 하나를 mount하지 않습니다.** 디렉터리를 공유해야 엔진 재시작 후 새 inode를 ③가 봅니다.

코드·`backend/`·저장소 루트 아래에는 운영 DB·백업·`.env`를 두지 않습니다. 같은 코드 폴더를 다른 이름으로 바인드 mount하지 않습니다. 심볼릭 링크·하드링크도 경계를 통과하는 방법으로 사용하지 않습니다. 코드 복사 시 `--exclude=.env*`, `--exclude=*.db*`, `--exclude=*.key*`, `--exclude=*.pem`, `--exclude=data/`, `--exclude=backups/`, `--exclude=__pycache__/`를 유지합니다. 삭제 동기화 옵션은 사용하지 않습니다. ③ 배포 대상에는 `backend/naver_page/` 실제 화면 파일 다섯(`index.html`, `sso-bootstrap.js`, `app.js`, `app.css`, `favicon.svg`)과 최신 `.dockerignore`를 포함해야 합니다. `sso-bootstrap.js`는 화면 첫 스크립트이며 누락하면 새 로그인 연결이 동작하지 않습니다. 레거시 README·HANDOVER의 키를 읽거나 복사하지 않습니다.

## 3. 설정과 비밀값

공유 성과용 `NAVER_ENGINE_METRICS_ENABLED`도 기본 `false`입니다. 이 기능을 켜려면 아침 점검과 알림 스위치가 모두 켜져 있어야 합니다. 코드 추가·합성 시험 성공만으로 운영 스위치를 켜지 않습니다.

기본 스위치는 `NAVER_ENGINE_SYNC_ENABLED`, `NAVER_ENGINE_LINKS_ENABLED`, `NAVER_ENGINE_MORNING_ENABLED`, `NAVER_ENGINE_ALERTS_ENABLED`, `NAVER_ENGINE_ISSUE_ALERTS_ENABLED`, `NAVER_ENGINE_BACKUP_ENABLED`, `NAVER_ENGINE_WEB_ENABLED` 모두 `false`입니다. `NAVER_ENGINE_SHADOW_START`와 `NAVER_ENGINE_ISSUE_ALERTS_FROM`도 빈 값이며, 광고주 이슈 알림 시작은 그림자 시작일에서 14일 뒤보다 빨라서는 안 됩니다. 자동 재시작도 기본 `restart: "no"`입니다. 운영에 자동 재시작이 필요하면 관측·경보·중지 절차와 함께 별도 승인합니다.

- `NAVER_ENGINE_ERP_KEY`: 새 엔진 전용 키. ①은 별도 `NAVER_ENGINE_KEY_SHA256` 지문만 갖습니다. 기존 ②·③의 `ERP_SYNC_API_KEY`는 바꾸거나 재사용하지 않습니다. 키와 지문은 대표님이 승인된 보관 위치에서 준비하며 대화·문서·로그에 출력하지 않습니다.
- `NAVER_MGR_CUSTOMER_ID`, `NAVER_MGR_API_KEY`, `NAVER_MGR_SECRET_KEY`: 승인된 회사 관리계정의 읽기 자격. 전부 꺼짐 시험에서는 실제 값을 주입하지 않습니다.
- `NAVER_AUTO_TOKEN_SECRET`: 관제 화면 API의 별도 서명 값. S16 교환 키와 다른 값이며 이것만 있어서는 웹 실행 조건을 충족하지 못합니다.
- `SSO_NAVER_CONTROL_CLIENT_KEY`: S16 관제 전용 64자리 hex 교환 키. 환경 예시는 빈 값이며, 유효한 키와 자체 서명 값이 모두 있어도 기본 웹 스위치와 운영 승인 조건은 별개입니다.
- `NAVER_ENGINE_DB`, `NAVER_ENGINE_SOCKET`, `NAVER_ENGINE_BACKUP_DIR`: compose가 컨테이너 안 전용 경로로 고정합니다. 호스트 경로 선택용 변수와 컨테이너 내부 경로를 혼동하지 않습니다.
- Compose는 **2.30 이상**의 `env_file.format: raw`를 사용합니다. 환경 파일의 `$`가 임의 보간되지 않도록 실제 값에 shell용 따옴표를 추가하지 않습니다. 환경 파일을 shell에서 `source`하지 않습니다.

일반 `compose config`는 비밀값을 출력할 수 있습니다. 실제 환경을 검사할 때는 `config --quiet`만 사용하며 `--environment`, 렌더링 결과, `inspect` 환경 출력을 보고서에 붙이지 않습니다. 런타임 예외·로그도 원문 자격·요청 주소·응답 본문을 포함하지 않는지 확인합니다.

엔진의 별도 기본 bridge는 외부 송신이 가능한 네트워크입니다. 호스트 포트가 없다는 사실을 외부 송신 차단으로 오해하지 않습니다. 기본 꺼짐 무호출 시험과 운영 방화벽·전산/네이버 허용 목적지 검토를 별도로 수행합니다.

### S16 목적지별 키 위치와 전환 순서

세 소비부는 서로 다른 64자리 hex 원문 키를 사용하고 ① BE에는 대응하는 SHA-256 지문만 둡니다. 기존 `ERP_SYNC_API_KEY`, `NAVER_ENGINE_ERP_KEY`, JWT·관제 서명 값은 변경하거나 재사용하지 않습니다. 키·지문 원문을 대화·문서·로그에 출력하지 않습니다.

| 소비부·목적지 | 소비부 주입 경로 | ① BE 지문 설정 |
|---|---|---|
| ③ 광고센터 `AD_CENTER` | 별도 ③ 환경의 `SSO_AD_CENTER_CLIENT_KEY` → 기본 `docker-compose.yml`의 `ad-api.environment`. 네이버 override 없이도 전달하며 빈 값은 새 교환만 거절합니다. | `SSO_AD_CENTER_KEY_SHA256` |
| ② 로직분석 `LOGIC_ANALYSIS` | ② 배포 환경의 `SSO_EXCHANGE_CLIENT_KEY` → ② `.github/workflows/deploy.yml`이 생성하는 운영 Compose의 `env_file: .env`. 저장소의 개발용 Compose도 같은 전달 방식이지만 운영에 직접 쓰이지 않습니다. 이 이름은 ② 전용이며 엔진 환경 파일에 넣지 않습니다. | `SSO_LOGIC_ANALYSIS_KEY_SHA256` |
| 관제 엔진 `NAVER_CONTROL` | 코드 밖 `/etc/metainc/naver-engine/runtime.env`의 `SSO_NAVER_CONTROL_CLIENT_KEY` → 엔진 Compose의 `env_file.format: raw`. ③ 컨테이너에 넣지 않습니다. | `SSO_NAVER_CONTROL_KEY_SHA256` |

① BE 배포는 `.github/workflows/deploy-vps.yml`에서 GitHub 비밀값 `ENV_FILE`을 바탕으로 후보 `.env`를 매번 새로 생성합니다. 따라서 서버 `.env`만 수동 수정해서는 다음 배포까지 지문 설정이 지속된다고 볼 수 없습니다. 실제 승인된 배포에서 세 지문의 **지속 주입 경로를 확정**하고 다음 후보 생성에도 유지되는지 검증해야 합니다. 이 개발 작업은 `ENV_FILE`이나 서버 비밀값을 변경하지 않습니다.

1. **수신부 먼저:** 별도 승인 뒤 ① 발급·교환 BE와 ②·③·관제 수신부의 선행 코드·키 전달을 준비합니다. 수신부 준비 전 전산 입구를 전환하지 않으며, 이번 개발에서는 관제·중계 스위치를 켜지 않습니다. HTTPS·신뢰 IP·원문 미기록·목적지/만료/재사용/검증자 거절은 별도 증거로 확인합니다.
2. **FE 마지막:** 세 수신부의 준비 상태와 승인된 검증을 확인한 뒤에만 ① FE의 세 입구를 새 방식으로 전환합니다. 새 창 URL에는 비밀 아닌 `sso_start` 식별자만 넣고 코드·검증자는 URL에 넣지 않습니다. 개발 합성 시험과 실제 세 입구 실사용 성공은 구분합니다.
3. **기존 경로 별도 폐기:** 세 입구 실사용 확인 뒤 별도 승인·차례에 ②·③의 legacy `?sso=` 경로를 폐기합니다. 새 입구 전환과 동시에 차단하지 않습니다. 관제는 이미 `/session {code,codeVerifier}`만 받으며 옛 ERP JWT 경로로 재시도하지 않습니다. 상세 계약은 `docs/superpowers/specs/2026-09-30-s16-exchange-contract.md`를 따릅니다.

## 4. 백업 Q6 — 암호화 복사와 복원은 별도 증거

아침 점검 뒤 SQLite 온라인 백업으로 일관된 사본을 만들고 같은 서버 `local/`에 압축 평문 7일치를 보관합니다. 복사본에는 `0600`을 사용합니다. `outgoing/`에는 공개 인증서로 암호화한 사본만 놓습니다. 백업 생성 성공을 서버 밖 복사 성공으로 표시하지 않습니다.

백업 override의 세 파일은 다음뿐입니다.

- `/run/secrets/naver-backup-recipient.pem`: 받는 쪽 공개 인증서(`NAVER_BACKUP_CERT`).
- `/run/secrets/naver-backup-upload-key`: 보내기 전용 SSH 인증키(`NAVER_BACKUP_SSH_KEY`). 복호화 개인키가 아닙니다. 실행 UID만 읽도록 `0400`을 확인합니다.
- `/run/secrets/naver-backup-known-hosts`: 사전에 별도 경로로 확인한 회사 전산 서버 호스트키(`NAVER_BACKUP_KNOWN_HOSTS`). 처음 접속에서 무조건 믿는 옵션은 금지합니다.

**복호화 개인키는 엔진 서버·전산 서버·이미지 어디에도 넣지 않습니다.** 승인된 GitHub 비밀값에서 복원 연습 때만 별도 안전 환경으로 꺼냅니다. 잃으면 백업을 복원할 수 없으므로 보관·접근·교체 책임자도 정해야 합니다.

① 담당자가 전산 운영 DB와 분리한 폴더·받기 전용 계정을 준비해야 합니다. 새 파일 추가만 허용하고 기존 파일 덮어쓰기·지우기·일반 shell·포트 전달을 금지합니다. 원격 30일 보관 정리는 **받는 서버가 스스로** 하며, 엔진은 원격 삭제 권한을 갖지 않습니다. 전송 성공 응답·수신 파일 hash·권한·덮어쓰기 거절 증거를 모두 남깁니다. 이 수신 계정 설정은 본 패키징만으로 생성되지 않습니다.

수신 구현 후보는 `deploy/naver-backup-receiver.py`입니다. ① 승인 뒤 root 소유·수신 계정 수정 불가인 고정 경로에 설치하고, `naver-backup`의 `authorized_keys`에는 `restrict,command="/usr/bin/python3 /검증한/고정/수신스크립트"` 형태로 해당 스크립트만 연결합니다. `/var/backups/metainc/naver-engine-received`는 수신 계정 소유 `0700`, 사본은 `0600`입니다. 같은 SHA-256의 재전송은 내용 대조 후 같은 영수증만 돌려줍니다. 30일 정리 인자는 SSH가 아닌 수신 서버 root 타이머에서만 쓰며, 일반 shell·SFTP·다른 인증 경로와 용량 한도도 별도로 검증합니다. 이 설명의 예시 경로를 그대로 설치 명령으로 실행하지 않습니다.

OpenSSL CMS AES-256-GCM의 실제 이미지 지원을 검증해야 합니다. 로컬 OpenSSL 성공은 이미지 성공이 아닙니다. 컨테이너와 같은 이미지의 임시 시험 인증서로 암호화 → 복호화 → 원본 hash 일치 → 암호문 변조 거절을 확인하고 이미지 digest와 OpenSSL 버전을 기록합니다. 아직 기본 이미지 digest·apt 패키지 결과가 고정되지 않았으므로 재현 빌드 완료라고 쓰지 않습니다.

켜기 전 최초 1회, 그 뒤 매월 회사 다른 서버에 있는 사본을 실제로 받아 별도 임시 환경에서 복원합니다. 무결성 검사·표별 줄 수·백업 날짜를 대조합니다. 원본 DB 위에 풀지 않습니다. 실패 시 대표 시스템 경보, 설정 화면의 「마지막 서버 밖 사본」 표시가 실제 결과와 일치해야 합니다. 서로 다른 서버의 복사본은 같은 데이터센터 전체 사고까지 보장하지 않습니다.

## 5. nginx와 ③ 중계 게이트

`deploy/naver-engine-nginx.conf`는 **server 안의 include**입니다. 기존 공유 nginx 전체를 덮지 않습니다. 적용 전 ②·③·스튜디오에 영향과 변경 위치를 알리고, 운영 `dashboard.metainc.co.kr`의 실제 블록·인증서·80/443·IPv4/IPv6·중복 location을 확인합니다. 이 저장소의 옛 ad 호스트 설정이 운영 dashboard 설정과 같다고 가정하지 않습니다.

- 새 include는 선택한 ③ server의 접근 기록을 끕니다. `/naver/?sso=`, `/?sso=`, 정적 자원 요청의 Referer까지 접근 로그로 남지 않도록 기존 하위 location의 재정의도 검사합니다. 로그가 필요하면 주소·쿼리·Referer·Authorization이 없는 별도 형식을 먼저 합의합니다. 기존 error log·WAF·상위 프록시 로그의 토큰 처리도 별도 확인합니다.
- `/naver`, `/naver/`, `/api/naver-auto` 응답은 오류·꺼짐·없는 파일에도 `Referrer-Policy: no-referrer`, `Cache-Control: no-store`를 붙입니다. 상속 `error_page`나 외부 리다이렉트가 이 헤더를 지우지 않는지 검사합니다.
- `X-Real-IP`는 무조건 `$remote_addr`로 덮어씁니다. 기존 `/` 경로도 같은 규칙이어야 합니다. 밖에서 가짜 `X-Real-IP: 192.0.2.1`을 보내 실제 연결 주소로 인식되는지 확인합니다. 신뢰할 수 없는 사용자 입력을 Real IP 기준으로 바꾸는 전역 설정은 허용하지 않습니다.
- 현재 `default_server`가 알 수 없는 Host를 **444**로 끊는지 별도 검사합니다. include에는 새 default server를 넣지 않습니다. 기존 ②·스튜디오·TLS default와 충돌시키지 않습니다.
- 엔진은 유닉스 소켓에서만 WSGI 신뢰 표지를 넣고, 소켓 `0660`·같은 디렉터리 재연결·가짜 HTTP 헤더로 표지를 만들 수 없음·서로 다른 요청 출처의 로그인 제한 분리를 검증합니다.
- ③ `/api/health`와 별개로 중계→엔진 연결 실패가 대표 경보에 도달하는지 확인합니다. 헬스 응답만으로 아침 점검·심박·공유 숫자·백업 성공을 판정하지 않습니다.
- 미리보기 실제 읽기를 붙일 때 20초 안의 자체 마감·짧은 호출 제한을 검증합니다. ③ 중계 30초 뒤에도 엔진이 계속 읽는 상태를 허용하지 않습니다.

## 6. 배포를 막는 확인표

아래는 자동으로 완료되는 체크박스가 아닙니다. 담당자·날짜·원본 증거를 붙여야 통과입니다.

1. **① BE #805 선행:** 실제 머지·배포 SHA, 엔진 키 지문, 조직·계약·고객 번호 경로, 알림·심박 경로, 스키마 충돌 점검, 감시 동작을 확인합니다. 문서의 PR 이름은 현재 운영 배포를 증명하지 않습니다. 기존 ②·③ 계약 동기화 키 무변경도 대조합니다.
2. **S16 전환:** 구현된 세 입구의 받는 곳 전용·60초·한 번만 쓰는 교환 코드와 브라우저 검증자 계약을 확인합니다. 목적지별 키 전달·BE 지문 지속 주입·수신부 우선/FE 마지막 전환을 별도 승인 아래 검증하고, 다른 입구 코드·재사용·만료·검증자 불일치 거절을 검사합니다. 관제의 옛 로그인 토큰 경로는 닫힌 상태를 유지합니다. 개발 완료만으로 웹 스위치를 켜지 않으며 ②·③ legacy 폐기는 별도 차례입니다.
3. **공유 성과 G1~G3:** 엔진의 최근 30일·어제까지 완전한 확정 숫자만 ①로 보내고 `MANUAL` 보존·`ENGINE` 우선·3일 뒤 자체 수집 복귀·광고비 scope가 통과해야 합니다. **공유 성과 연결 미완료이면 생산 배포 금지**입니다.
4. **합성 무호출:** 모든 스위치 꺼짐 실제 기동 시험과 가짜 자격·가짜 자료의 unittest를 구분합니다. 실제 네이버·전산·SSH 호출 **0건** 증거가 있어야 합니다. `check-config`·`dry-run` 성공을 이 증거 대신 쓰지 않습니다.
5. **실제 이미지·환경:** Python 3.12·OpenSSL·권한·read-only root·WAL·단일 writer·소켓 재생성·③ 연결 재복구·이미지 digest를 확인합니다. 정적 compose 검사는 Docker 기동 검사가 아닙니다.
6. **S0 보안:** 승인된 배포 뒤 ③ `tools.check_secrets`를 실행해 사유·출처만 확인합니다. 관리자가 데모 계정뿐이면 대표 SSO 관리자 지정 또는 승인된 `tools.set_password` 절차로 공개 비밀번호를 바꿉니다. 기존 암호화 키 `0600`, 수동 배포 폴더의 최신 compose·`.dockerignore`, 배포 전후 대표 「광고 센터」 SSO 재로그인을 확인합니다.
7. **화면·중계:** `NAVER_SCREEN_REQUIRE_BROWSER=1` 브라우저 시험과 `NAVER_RELAY_REQUIRE_APP=1` 앱 시험을 통과시킵니다. 없는 의존성으로 건너뛴 결과는 배포 증거가 아닙니다. 실제 nginx 검증·가짜 요청 출처·로그 비밀값 미노출은 별도 증거입니다.
8. **백업·복원:** 회사 다른 서버의 append-only 수신 경계·30일 정리 책임·최초 복원 연습·대표 경보·마지막 성공 표시까지 확인합니다.
9. **공유 서버 여유:** ②·③·스튜디오의 평소·피크 CPU/RAM/디스크·백업 증가량, 아침 회차 소요와 ③ 06:00 수집 종료를 실측합니다. 현재 `0.50 CPU / 512 MiB / 64 PID`는 임시 상한일 뿐 용량 수용 증거가 아닙니다. 계약 단계 조용한 창은 03:50~04:20, 05:50~07:10을 보존하고 실측 전 줄이지 않습니다.
10. **최초 운영 승인:** 대표님만 보는 그림자 점검 **14일**의 시작일·끝일·성공 기준·중지 담당자를 기록합니다. 직원·광고주에게 판단이나 경보를 공개하는 단계는 별도 확인입니다. 최초 무호출 시험과 실제 계정을 읽는 그림자 운영은 다른 단계입니다.
11. **소식판·복구:** ① 호출 시작 전에 알리고 공유 서버 변경은 ②·③·스튜디오와 조율합니다. 실행 스위치·백업 경보·중지 시 심박 감시 설정의 책임자를 지정합니다. 아직 배포하지 않았으므로 외부 소식판이나 비밀값을 자동 수정하지 않습니다.

## 7. 안전한 로컬 정적 검사 예시

아래 검사는 서비스를 띄우거나 이미지를 빌드하지 않습니다. 저장소 루트에서 실행합니다. `docker compose` plugin이 없고 동일한 Compose CLI가 `docker-compose`로 설치되어 있다면 명령 실행 파일만 바꾸되 프로젝트·파일 지정은 유지합니다.

```sh
python -m unittest discover -s tests -p 'test_naver_engine_packaging.py' -v
docker compose --project-name naver-engine --file compose.naver-engine.yml config --no-env-resolution --quiet
docker compose --project-name naver-engine --file compose.naver-engine.yml --file deploy/naver-engine-backup.override.yml config --no-env-resolution --quiet
```

③ override의 합성 검사는 실제 ③ 프로젝트와 섞이지 않도록 별도 검토 이름을 씁니다. 아래도 구성 검사만 합니다.

```sh
docker compose --project-name naver-package-review --file docker-compose.yml --file deploy/naver-engine-ad-api.override.yml config --no-env-resolution --quiet
```

운영 기동 명령은 위 게이트가 모두 확인된 뒤 배포 작업에서 확정합니다. 기본 compose를 생략한 명령, 프로젝트명을 생략한 명령, 공유 Docker 자원의 일괄 정리, 볼륨 삭제, DB 위 복원은 금지합니다. 엔진만 멈춰도 ③와 다른 서비스가 멈추지 않는 절차를 검증하며, 스키마가 새 판으로 올라간 뒤 옛 이미지로 무조건 되돌리지 않습니다. 복구는 검증한 별도 사본과 호환 이미지로 계획하고 원본을 보존합니다.

## 8. 개발 전용 Linux CI

S14 런타임, G1~G3 공유 성과, S16 로그인 연결의 개발 검증은 같은 읽기 전용 CI와 격리 조건을 사용합니다.

`.github/workflows/naver-runtime-tests.yml`은 `codex/naver-runtime-20260930`, `codex/naver-shared-metrics-20260930`, `codex/naver-sso-20260930` 가지 push와 해당 가지의 수동 실행에만 맞습니다. 배포 작업·운영 비밀값·쓰기 토큰·self-hosted runner가 없으며 `contents: read`, checkout 자격 저장 금지를 사용합니다. GitHub 공식 [workflow 권한·분기 문법](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)과 [수동 실행 조건](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)에 근거합니다. 수동 실행은 workflow가 기본 가지에 있어야 하므로 새 개발 가지에서는 우선 push 조건으로 검증합니다.

의존성 준비만 네트워크가 있는 GitHub-hosted 임시 runner에서 수행합니다. 시험은 별도 네트워크 namespace에서 loopback만 켜고 **원래 비루트 runner UID로 낮춘 뒤**, allowlist 환경만 전달합니다. 외부 시험 주소 연결 실패 canary가 통과해야 엔진·③·런타임·패키징 시험을 실행합니다. loopback HTTP와 유닉스 소켓은 합성 서버용으로만 허용합니다. 준비 단계의 네트워크를 포함해 전체 workflow가 무통신이라고 표현하지 않습니다.

Linux Python 3.12 시험은 macOS에서 파일 잠금과 SQLite WAL이 충돌하는 차이를 우회하려고 저장소 잠금을 약화하지 않습니다. 브라우저 시험은 기존 하네스를 사용하며 추가 보안 완화 인자를 넣지 않습니다. 기존 `chromium.launch()`가 브라우저 자체 sandbox를 입증하는 시험은 아닙니다. 이 CI는 실제 계정·운영 서버·실제 nginx 검증을 대신하지 않습니다.

운영 후보 이미지도 push 없이 임시 runner에서 빌드하며, `--network none`, UID `10001:10001`, 읽기 전용 루트로 `check-config`, `dry-run`, 실제 이미지의 암호화 왕복·변조 거절 시험을 수행합니다. 결과와 의존성 버전만 7일 보관합니다. 작성한 workflow의 정적 검사와 실제 GitHub 실행 성공은 따로 보고합니다.

## 9. 공유 성과 G1~G3 — 구현과 운영 검증의 경계

- 기존 관제의 29일 비교 창은 그대로입니다. 공유 성과는 한국 기준 어제까지 정확한 30일을 따로 읽어 검증합니다.
- 당일 아침 점검 완료 뒤 08:10~18:00에 배치당 가망 최대 2곳을 처리합니다. 묶인 모든 계정·캠페인의 일별 원천과 같은 기간 합계가 정확히 맞아야 전송합니다. 빠진 날·칸을 0으로 취급하려면 남은 정수 합계가 같은 기간 총합과 일치해야 합니다. 빈 캠페인 목록·불명확한 집계 기준 시각은 정상 0으로 보내지 않습니다.
- 새 요청·재시도 대기에는 45초 예산과 Naver 읽기 최대 80회 제한을 둡니다. ERP 전송은 별도 timeout이므로 전체 배치가 정확히 45초 안에 끝난다는 보장은 아닙니다. 큰 계정의 당일 처리율·서버 자원은 실제 그림자 운영에서 측정해야 합니다.
- 캠페인 목록으로 최소 요청 수를 먼저 계산합니다. 한 가망이 80회를 초과하면 그날 `capacity` 보류하고 다른 가망을 계속 처리합니다. 같은 날·같은 연결 상태의 실패는 최대 8회까지 시도하며, 그 뒤에는 `attempt-cap` 보류합니다. 재시작해도 제한은 유지하고 새 날짜나 의미 있는 연결 변경 때 다시 시도합니다. 80번째 요청을 마친 정상 자료는 전송할 수 있습니다. 이는 대형 가망 수집 완료의 대안이 아니라 무한 재시도를 막는 안전 한도입니다.
- 저장소 판 7의 별도 표는 날짜·가망별 원천 숫자, 해시, 전송 상태와 실패를 보관합니다. 업무 이름·본문·자격은 넣지 않습니다. 재전송 전에 원천을 재검증하고, 짝·단계가 바뀌면 이전 결과를 재사용하지 않습니다. 미연결 광고주는 성공 처리하지 않습니다. 해당 날짜에는 보류하고 다음 날 다시 확인합니다.
- 새 `POST /api/ad-sync/naver-metrics`는 엔진 전용 키와 숫자 7칸만 사용합니다. 서버는 현재 연결 광고주가 정확히 하나일 때만 저장합니다. STORE/PLACE 등 복수 연결은 임의 선택하지 않고 409로 보류합니다.
- 서버는 `API`/`ENGINE` 자동 행 하나만 갱신하고 `MANUAL`은 보존합니다. 마지막 엔진 수신부터 72시간 이내에는 자체 키 수집을 생략하며, 초과한 뒤 유효한 자체 키가 있을 때만 기존 수집기로 복귀합니다. 자동 성과의 직접 삭제는 화면과 서버에서 막습니다.
- BE의 nullable `engine_received_at` 칼럼(BLOCK 254), §14 계약, FE의 `ENGINE` 출처 호환을 한 묶음으로 검토합니다. 기존 자료 backfill·운영 데이터 수정은 하지 않습니다. MariaDB 실제 이관·실계정 읽기·광고비 공개 범위의 로그인 화면 점검은 운영 승인 뒤 별도입니다.
- 원천 표의 보관 주기·디스크 증가량은 아직 운영 실측 전입니다. 임의 삭제 작업을 넣지 않았습니다. S16의 승인된 운영 전환, 실제 백업 복원, 네트워크·자원·14일 그림자 승인 조건은 여전히 남습니다.

Compose 구성 출력과 컨테이너 환경값도 구분합니다. CI의 Compose v2.38.2는 [`config` 직렬화 뒤](https://github.com/docker/compose/blob/v2.38.2/cmd/compose/config.go#L165-L181) JSON/YAML의 모든 `$`를 [정확히 한 번 `$$`로 이스케이프](https://github.com/docker/compose/blob/v2.38.2/cmd/compose/config.go#L495-L499)합니다. 패키징 시험은 합성 raw env의 펼친 출력이 이 규칙과 정확히 일치해야 통과하며, 원문·두 번 이스케이프·실제 보간된 값은 거절합니다. [`--no-interpolate`](https://docs.docker.com/reference/cli/docker/compose/config/)로 경로 기본값 해석까지 끄지 않습니다. raw env가 실제 컨테이너에서 원문 그대로 전달되는지는 별도의 네트워크 없는 합성 이미지 시험으로 검증하며, 운영 env·키·볼륨은 사용하지 않습니다.

## 10. 복호화 완료 사본의 로컬 복원 검증 도구

`python -m naver_runtime.restore_check`는 **이미 복호화된 ZIP만** 받습니다. 키 조회·발급·복호화·전송·서버 접속은 하지 않습니다. 기존 `restore_archive`와 `inspect_snapshot`으로 스냅샷 SHA-256, SQLite 무결성, 정확한 표별 건수를 검증하고, 생성기가 기록한 명시적 UTC `created_at`을 한국 날짜로 바꿔 예상일과 대조합니다. 원본 ZIP은 변경하지 않습니다. 새 출력 폴더의 `snapshot.sqlite`만 남기며 기존 폴더·파일·링크는 거절합니다.

아래 경로는 예시이며, 승인된 별도 안전 환경에서 실제 준비한 경로로 바꿉니다. 입력 ZIP은 실행자 소유 `0600`, 출력의 **상위 폴더는 미리 마련한 실행자 소유 `0700`**이어야 합니다. 모든 경로는 링크 없는 절대 경로이며 코드 폴더 밖입니다. `check-20261001` 자체는 미리 만들지 않습니다.

```sh
python -m naver_runtime.restore_check \
  --archive /private/restore-work/decrypted.zip \
  --expected-kst-date 2026-10-01 \
  --output-dir /private/restore-work/check-20261001
```

성공은 종료 코드 `0`과 날짜·압축본/스냅샷 해시·표별 건수 JSON, 실패는 종료 코드 `1`과 일반 실패 메시지입니다. 경로·행 데이터·예외 원문은 출력하지 않습니다. 성공한 복원 DB는 평문 `0600`이므로 승인된 복원 작업자가 별도 보관·폐기합니다. 이 도구의 성공만으로 사본의 출처 진위, CMS 복호화·암호문 변조 거절, 다른 서버 수신 또는 운영 복원 완료를 증명하지 않습니다. §4의 실제 사본 최초/월별 복원과 키·수신 계정 승인 조건은 그대로 남습니다.

### 수신기 설치 전 보호 기준

수신기만 Python 3.8 이상 문법·API에 맞추며, `hashlib.file_digest` 대신 묶음 해시를 사용합니다. 전체 엔진의 Python 요구 버전을 낮춘다는 뜻은 아닙니다. 수신 시작점은 root가 미리 만든 `/run/metainc/naver-backup-receiver.lock`을 `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`으로 열고 소유자·파일 종류·권한·단일 링크를 검사한 뒤, 비차단 배타 잠금을 얻습니다. 잠금 파일 `root:root 0644`, 부모 `root:root 0755`이며 수신 계정이 교체할 수 없어야 합니다. root 정리도 같은 잠금을 사용합니다. 설치자는 부팅 후 잠금 경로를 안전하게 재생성하고 실행 중 잠금 파일을 교체하지 않습니다. 모든 수신·정리는 헤더·본문·EOF·파일 검사까지 포함해 300초로 제한됩니다.

승인된 수신 상한은 파일당 2 GiB, 폴더 전체 8 GiB, 최대 128개 파일입니다. 최종 사본뿐 아니라 고아 임시·이름 불명 일반 파일도 합산합니다. 디스크에는 최소 20 GiB와 65,536개 인오드를 남기도록 시작 전과 쓰는 중 검사합니다. 같은 해시 재전송은 새 임시 파일을 만들지 않고 전송 본문과 기존 사본의 해시·길이를 모두 대조하므로 상한에 도달해도 확인할 수 있습니다. 그 외 새 사본은 한도에 먼저 닿으면 거절하며, **30일치 보관 용량을 보장하거나 기존 사본을 덮어쓰기·조기 삭제하지 않습니다.** 다른 서비스의 동시 디스크 사용까지 통제하는 OS 전용 할당량은 아니므로 서버 디스크 경보·운영 용량 점검은 별도로 유지합니다.

`--prune` 진입은 SSH가 아닌 root 로컬 실행만 허용합니다. 최종 사본은 수신 시각 기준 30일, `.receiving-*` 중 1시간 지난 일반 파일·해당 수신 계정 소유·private 권한·단일 링크인 고아만 정리합니다. 링크가 2개인 발행 중단 사본은 임의로 지우지 않고 기존의 내용 검증 재전송 복구를 유지합니다. 삭제 후 폴더를 동기화합니다. 이 보호 코드와 합성 시험은 계정·강제 명령·비밀번호/포트 전달 차단·root 타이머의 실제 설치 및 SSH 검증을 대신하지 않습니다.
