# 네이버 관제 단순 배포 (naver-deploy)

다른 섹션처럼 **실행 버튼 한 번**(입력: 제품 커밋)으로
시험 → 이미지 빌드 → 서비스 교체 → 헬스체크 → 실패 시 직전 판 자동 복원까지 끝내는 장치다.
작은 수정 기준 전체 10~15분, 사람 손은 커밋 입력과 실행 버튼뿐이다.

| 파일 | 하는 일 |
|---|---|
| `.github/workflows/naver-deploy.yml` | 실행 버튼. `test`(시험·빌드 확인) → `ship`(서버로 보내 실행) |
| `deploy/naver/naver-deploy.sh` | 서버에서 도는 배포 스크립트(`inspect` / `deploy`) |
| `deploy/naver/make-source-archive.sh` | 제품 커밋에서 관제에 필요한 파일만 tar 로 묶음 |
| `deploy/naver/product-tests.sh` | 제품 단위 시험(요약만 출력) |
| `deploy/naver/tests/` | 서버 없이 도는 스크립트 시험(가짜 systemctl·docker·curl) |

이 파일들은 `deploy.yml` 의 `paths-ignore` 에 있어 **머지해도 로직분석이 재배포되지 않는다.**

> ⚠️ **main push 동작의 영구 변경.** 같은 커밋이 `deploy.yml` 자신도 고치므로 `deploy.yml` 도 무시 목록에 넣었다
> (`paths-ignore` 는 바뀐 파일이 전부 무시 대상일 때만 건너뛴다). 그래서 **이 PR 이후 `deploy.yml` 만 고친 커밋은
> main 에 push 돼도 로직분석을 자동 배포하지 않는다.** 배포 절차를 고친 뒤 바로 반영하려면 Actions 에서
> 「Deploy to VPS」를 수동 실행한다. 다른 파일(backend·frontend 등)이 함께 바뀐 커밋은 지금처럼 자동 배포된다.
> CLAUDE.md 「배포 규칙」(main 푸시 → 배포)과 함께 검토할 변경이다.

## 0. 실행 전 지켜야 할 것

- **최초 `inspect` 는 공개 출력 제한 수정(이 문서의 3장 「공개 로그에 나가는 것」)이 들어간 커밋이 재검증·머지된 뒤에만 실행한다.**
  그 전 판(e747271)의 inspect 는 unit·override·label 원문을 출력했다.
- **첫 배포와 되돌리기 훈련 동안 옛 실행기(「Conversion diagnostic through existing VPS connection」, 브랜치
  `codex/naver-conversion-existing-executor-20261026`)는 dispatch 하지 않는다.** 운영 진입점은 이 워크플로 하나뿐이어야 한다.
  새 장치의 `flock` 은 옛 실행기를 막지 못하고, concurrency group 은 SSH 가 끊긴 뒤 서버에서 계속 도는 작업까지 막지 못한다.
  가능하면 첫 `deploy` 전에 그 워크플로를 **Disable workflow** 로 꺼 둔다.
- **같은 SCHEMA_VERSION 안의 데이터·프로토콜 하위 호환은 이 장치가 확인하지 않는다.** 자동 복원은 이미지·unit·override 만 되돌리고
  DB 는 그대로 두므로, 새 판이 남긴 데이터를 직전 판이 읽을 수 있는지는 **배포 대상마다 리뷰에서** 확인한다. 우회 입력은 없다.

---

## 1. 배포하는 법

1. GitHub → `metainchelp-boop/logic-analysis` → **Actions** 탭
2. 왼쪽 목록에서 **「네이버 관제 배포 (naver-deploy)」** 선택
3. 오른쪽 **Run workflow** 버튼 → Branch 는 **main** 그대로
4. 입력
   - `commit`: 배포할 제품 커밋 40자리 (`metainc-ad-dashboard`). 예: `abceeb737548ada081072df95279d19981b561f7`
   - `mode`:
     - `inspect` — 서버 상태만 읽는다(아무것도 바꾸지 않음). commit 칸은 형식만 맞으면 된다(지금 운영 커밋을 넣으면 됨).
     - `deploy` — 실제 배포.
5. **Run workflow** 누르기. 대표 계정(`metainchelp-boop`)이 main 에서 실행할 때만 동작한다.

**처음에는 반드시 `inspect` 를 먼저 돌려** 서버 배치가 아래 「서버 배치 가정」과 같은지 확인한 뒤 `deploy` 한다.

### 결과 읽기

`ship` 작업 로그 마지막 줄 `NAVER_DEPLOY_RESULT={...}` 의 `status`:

| 종료 코드 | status | 뜻 | 할 일 |
|---|---|---|---|
| 0 | `DEPLOYED` | 배포·헬스·60초 유지 통과 | 없음 |
| 0 | `DEPLOYED_WITH_WARNINGS` | 배포·헬스 통과, 마무리 경고(`warnings` 코드) | 경고 코드 확인 |
| 2 | `DEPLOY_FAILED_RESTORED` | 새 판이 실패해 **직전 판으로 자동 복원**, 복원 판 헬스 통과 | `reason`·`health_status` 로 원인 확인 후 고쳐서 다시 |
| 3 | `RECOVERED_INTERRUPTED_RUN` | 지난 배포가 중간에 끊겨(SSH 끊김·재부팅 등) 이번 실행이 **먼저 직전 판으로 복원**함 | 같은 입력으로 다시 실행 |
| 4 | `RESTORE_FAILED` | 복원까지 실패 → 두 서비스 정지를 시도. 실제로 멈췄는지는 `services_stopped_confirmed`(true/false) | 개발 담당에게 즉시 알림. `inspect` 결과 첨부 |
| 10 | `REFUSED` | 시작 전 거부. **서비스는 그대로**. `reason` 예: `SCHEMA_CHANGED`(`schema_current`→`schema_new`), `CONFIG_SHAPE_CHANGED`, `FLAGS_CHANGED`, `EXECUTION_ENABLED`, `LAYOUT`, `BUILD_FAILED`, `CHECK_CONFIG` | `reason` 확인 |
| 11 | `LOCKED` | 다른 관제 배포가 서버에서 실행 중 | 끝난 뒤 다시 |

`inspect` 결과는 `NAVER_DEPLOY_INSPECT={...}` 한 줄 JSON 이다.

### 공개 로그에 나가는 것 (이 저장소는 공개다)

- **deploy:** `phase=<단계 이름>` 줄들과 마지막 `NAVER_DEPLOY_RESULT={...}` 한 줄뿐이다. 결과 줄의 모든 값은 필드별 형식
  (커밋 40자리, `sha256:` 이미지 ID, 숫자, 대문자 사유 코드, `name=true|false` 스위치 등)을 통과한 것만 나가고, 문구는 고정표에서 고른다.
  자세한 사유·단계 로그는 서버 `/var/lib/metainc/naver-deploy/incoming/<실행번호>/deploy.log`, docker build·compose 원문 출력은
  `/var/lib/metainc/naver-deploy/runs/<시각>-<커밋>/commands.log`(root 전용 폴더)에만 남는다.
- **inspect:** unit·override·tmpfiles·label·Env **원문을 내지 않는다.** unit 은 ExecStart 모양(compose 파일 역할 목록, 커밋, 커밋 횟수,
  Environment 줄 수), override 는 키 이름과 image 태그, tmpfiles 는 허용된 `d` 줄, 컨테이너는 이미지 ID·상태·RestartCount·
  허용된 label 4개·mount 경로·스위치 참거짓, 데이터 폴더는 파일 이름·크기·권한만 낸다. sqlite 는 쓰지 않는다.
- **test 작업:** 제품 의존성 설치·시험·Docker build 의 stdout·stderr 는 러너 임시 폴더(`$RUNNER_TEMP/private`)에만 쓰고 올리지 않는다.
  로그에는 단계 이름·종료 코드·시험 개수만 나간다.

---

## 2. 처음 한 번 — 대표님 작업 (값은 어디에도 적지 않는다)

워크플로가 비공개 제품 저장소(`metainc-ad-dashboard`)의 정확한 커밋을 읽으려면 **읽기 전용 deploy key** 가 필요하다.

1. 내 PC 터미널에서 키 한 쌍을 만든다(암호 없이 Enter 두 번):
   `ssh-keygen -t ed25519 -C naver-deploy-readonly -f naver-deploy-key`
   → `naver-deploy-key`(개인키), `naver-deploy-key.pub`(공개키) 두 파일이 생긴다.
2. **공개키** 등록: GitHub → `metainc-ad-dashboard` → Settings → **Deploy keys** → **Add deploy key**
   - Title: `logic-analysis naver-deploy (read-only)`
   - Key: `naver-deploy-key.pub` 내용 붙여넣기
   - **Allow write access 는 체크하지 않는다**(읽기 전용).
3. **개인키** 등록: GitHub → `logic-analysis` → Settings → **Secrets and variables → Actions** → **New repository secret**
   - Name: `NAVER_PRODUCT_DEPLOY_KEY`
   - Secret: `naver-deploy-key` 파일 내용 전체(첫 줄 `-----BEGIN OPENSSH PRIVATE KEY-----` 부터 끝 줄까지)
4. 내 PC 의 두 파일을 지운다(GitHub 에만 남긴다).

키가 없으면 `deploy` 는 `test` 단계에서 「NAVER_PRODUCT_DEPLOY_KEY secret 이 없습니다」로 멈춘다(서버 접속 없음).
`inspect` 는 키 없이도 된다. VPS 접속 secret(`VPS_HOST`·`VPS_USER`·`VPS_SSH_KEY`)은 이미 이 저장소에 있다.

> 대안: VPS secret 3개를 `metainc-ad-dashboard` 에도 등록하고 이 워크플로를 비공개 저장소로 옮기면
> deploy key 가 필요 없고 로그도 비공개가 된다. 대신 로직분석 배포와 같은 concurrency group 을 공유하지 못한다
> (서버 쪽 `flock` 직렬화는 그대로 유지된다).

---

## 3. 무엇이 일어나는가

### `test` 작업 (GitHub 러너, 서버 접속 없음)
1. 실행 조건: 대표 계정 · main · commit 40자리 · mode 확인
2. 배포 스크립트 시험: `shellcheck` + `deploy/naver/tests`(가짜 서버로 정상 배포·자동 복원·스키마 거부·inspect 읽기 전용·잠금 충돌·중단 복구 등)
3. (`deploy` 만) 제품 커밋을 deploy key 로 받아
   - `naver_engine/tests`, `naver_runtime/tests`, `backend/tests/test_naver_relay*` 를 제품 CI 와 같은 방식(외부망 없는 비루트 namespace, Playwright·FastAPI 필수)으로 실행
   - 관제 범위 파일만 tar 로 묶고(해시 기록) 두 Dockerfile(`Dockerfile.naver-engine`, `Dockerfile.naver-relay`)을 실제로 빌드

### `ship` 작업
1. 같은 커밋으로 tar 를 다시 만들어 **시험한 tar 와 해시가 같은지** 확인
2. `scp` 로 스크립트(+tar)를 서버 `/tmp/naver-deploy-<실행번호>` 에 보낸 뒤
3. `inspect` 는 바로 실행해 JSON 출력.
   `deploy` 는 root 전용 폴더 `/var/lib/metainc/naver-deploy/incoming/<실행번호>` 로 옮겨 해시를 다시 확인하고,
   **`systemd-run` 으로 별도 작업**으로 띄운 뒤 단계 이름과 결과 한 줄만 따라 출력한다(서버 로그 원문은 흘리지 않는다).
   SSH 가 끊겨도 서버에서는 끝까지(실패 시 복원까지) 돈다.

### 서버의 `naver-deploy.sh deploy` 순서
1. `flock` 잠금(동시 실행 방지). 지난 실행이 서비스를 멈춘 뒤 끝나지 못했으면 **먼저 직전 판으로 복원**하고 끝(코드 3)
2. 현재 배치 확인 — 모르는 모양이면 거부(아래 「서버 배치 가정」). 실행 중 engine 컨테이너 Env 에서 **유효 스위치 10개**
   (제품 `naver_runtime/config.py` 와 같은 참/거짓 규칙)와 두 컨테이너 mount 목록을 기록한다. `execution` 은 false 여야 한다
3. 원본 tar 범위 검사, **SCHEMA_VERSION 비교**(새 판 `naver_engine/store.py` vs 실행 중 이미지 안의 `store.py` 또는 이 장치가 붙인 이미지 라벨). 다르면 거부. 우회 입력 없음
4. 복구 기록 저장: `state.json` + `runs/<시각>-<커밋>/` 에 현재 unit 2개·override 2개·mount 목록 사본, 직전 이미지 ID, 스위치
5. `releases/naver-<새 커밋>` 생성(이미 있으면 같은 원본인지 확인만), 현재 override 에서 **커밋만 치환**(각 1회 단언)
6. **서비스를 멈추기 전에**
   - 두 이미지 빌드(`metainc/naver-{engine,relay}:<커밋>`, 원문 출력은 비공개 명령 로그로)
   - 지금 판과 새 판의 `compose config`(JSON)에서 **관제 설정 묶음**(서비스 목록, data·socket·backup·tunnel mount, user 10001:10001,
     restart no, network_mode, read_only, tmpfs, cap_drop, security_opt)을 정규화해 비교 → 이미지 태그 말고 다르면 거부(`CONFIG_SHAPE_CHANGED`).
     호스트 전체 baseline 은 보지 않는다. environment(비밀값 포함)는 비교·출력하지 않는다
   - **격리된 `check-config`**: 새 이미지를 `docker run --network none --read-only --user 10001:10001 --cap-drop ALL` 로,
     운영 data·socket·backup·tunnel mount 없이(데이터 경로는 빈 tmpfs) 실행한다. 환경은 새 compose 설정의 유효 environment
     (runtime.env 포함)를 `-e 이름` 으로만 넘겨 값이 명령줄·로그에 남지 않는다. 새 판 스위치가 **지금 판과 하나라도 다르면 거부**(`FLAGS_CHANGED`),
     `execution=false` 단언
7. DB 복사 공간 확인 → relay 정지 → engine 정지(둘 다 MainPID 0·컨테이너 PID 0 확인)
8. 엔진이 멈춘 상태에서만 `engine.db*` 파일 복사(`/var/backups/metainc/naver-deploy-db`, 최근 3벌). sqlite 로 열지 않는다
9. unit 2개에서 **커밋만 치환**(engine 6회·relay 4회 단언) → `daemon-reload` → `compose up --no-start --no-build --force-recreate` →
   새 컨테이너의 mount 목록이 직전과 같고, engine 스위치가 기록과 같은지 확인
10. engine 시작 → relay 시작
11. 헬스: engine `/_engine/health` 200, relay `/naver/` 200, `/api/naver-auto/me` 401 → **60초 유지**(두 unit active, MainPID·NRestarts 불변, 컨테이너 RestartCount 0, StartedAt 불변)
12. 실패하면 기록으로 **직전 unit·override·이미지 복원 → mount·스위치 재확인 → 같은 헬스체크**. 복원도 실패하면 두 서비스 정지를 시도하고,
    MainPID 0·컨테이너 정지를 실제로 확인했는지(`services_stopped_confirmed`)를 따로 보고한다(코드 4)
13. 성공하면 이미지 정리: 이 장치가 배포한 기록 중 **최근 3개·현재·직전은 절대 삭제하지 않는다.** 기록에 없는 태그(옛 실행기가 만든 것 등)는 건드리지 않는다

### 건드리지 않는 것
`runtime.env`, nginx, ERP 터널 unit, 로직분석 등 다른 앱, saved-exports companion(engine unit 의 4번째 `-f` 파일 — 경로 그대로 유지),
`engine.db`/`-wal`/`-shm`/`-journal`(제자리 보존, 복사만). 끝에 runtime.env·tmpfiles·터널 unit·nginx 지문이 그대로인지 확인해 보고한다.
옛 release 폴더는 지우지 않는다.

---

## 4. 서버 배치 가정과 확인 방법

옛 실행기(`codex/naver-conversion-existing-executor-20261026` 의 `release/conversion-20261026/backend/tools/`)가 만든 배치를 기준으로 했다.
`inspect` 로 눈으로 확인하고, `deploy` 는 아래를 실행 때마다 검사해 다르면 **멈추기 전에 거부**한다.

| 가정 | 근거(옛 코드) | 실행 중 확인 |
|---|---|---|
| unit `metainc-naver-engine.service` / `metainc-naver-relay.service` 가 `/etc/systemd/system` 에 있고 drop-in 없음, enabled·active | `naver_preview_lifecycle.py` UNITS·UNIT_DIR | `systemctl show` FragmentPath·DropInPaths·UnitFileState·ActiveState |
| ExecStart = `/usr/bin/docker compose --project-name naver-<이름> -f <release>/compose.naver-<이름>.yml [-f <release>/deploy/naver-engine-backup.override.yml] -f <release>/preview-<이름>.override.yml [engine 만: -f saved-exports companion] up --no-build --no-recreate --abort-on-container-exit --exit-code-from naver-<이름> naver-<이름>`, ExecStop 같은 파일 + `stop --timeout 45`, `Restart=always`, engine `Requires=` 에 터널, relay `Requires=` 에 engine | `unit_files()` :21-42, `ExportProxy.compose` | 토큰 단위로 정확히 비교. companion 은 `/srv/metainc/ad-deploy-staging/saved-exports/<32hex>/naver-saved-exports.override.yml` 만 허용 |
| release 폴더 `/srv/metainc/ad-deploy-staging/releases/naver-<커밋>`, unit 안 커밋 문자열 engine 6회·relay 4회 | `naver_preview_release.py` ROOT·`compose()` | 횟수 단언 |
| override `preview-engine.override.yml`·`preview-relay.override.yml` 에 `    image: metainc/naver-<이름>:<커밋>` 한 줄, 커밋 1회 | `prepare()` :329-333, `target_override` | 줄·횟수 단언 |
| 이미지 `metainc/naver-<이름>:<커밋>`, 라벨 `metainc.naver.preview.source=<커밋>`, 사용자 10001:10001; 컨테이너 1개씩, compose project/service `naver-<이름>` | `manifest()`, `_snapshot()` | `docker image inspect`·`docker inspect` |
| 소켓 `/run/metainc/naver-engine/engine.sock`, `/run/metainc/naver-relay/relay.sock`, Host `dashboard.metainc.co.kr` | `unix_request()`, tmpfiles | 헬스체크가 곧 확인 |
| 데이터 `/var/lib/metainc/naver-engine/engine.db*` | compose 기본값 | 이름 규칙 검사(모르는 `engine.db*` 이름이면 거부) |
| `/etc/tmpfiles.d/metainc-naver-preview.conf`, `docker.service`·`metainc-naver-erp-tunnel.service` active | lifecycle | 존재·active 확인, 지문 불변 확인 |
| SSH 사용자(VPS_USER)가 root | `deploy.yml` 이 `/root/logic-analysis-deploy` 에 배포, 옛 실행기 euid 0 요구 | `deploy` 는 root 아니면 거부, `inspect` 의 `id` 로 확인 |
| `python3`, `curl`, `flock`, `systemd-run` 이 서버에 있음 | — | 없으면 거부, `inspect` 의 `tools` |

---

## 5. 첫 배포 계획 (대표 승인 후)

1. (공개 출력 제한 수정이 재검증·머지된 뒤) `inspect`(commit 칸: 지금 운영 커밋) → 결과를 개발 담당이 대표께 보고
2. `deploy` abceeb7(`report_output_schema.py` 1파일, 스키마 21 불변)
3. 되돌리기 훈련: `deploy` c44a663 (기존 `releases/naver-c44a663…` 은 같은 원본인지 확인 후 재사용)
4. `deploy` abceeb7 재배포

---

## 6. 옛 실행기 은퇴 (첫 배포·되돌리기 훈련 성공 뒤)

옛 실행기 파일은 지금 바꾸지 않는다. 새 방식 첫 배포와 훈련이 끝나면:

1. 옛 경로를 막는다(0장대로 첫 배포 전에 이미 꺼 두는 것을 권한다): GitHub → Actions → 「Conversion diagnostic through existing VPS connection」
   (브랜치 `codex/naver-conversion-existing-executor-20261026` 의 `debug-rank.yml`) → 오른쪽 `…` → **Disable workflow**.
   두 경로가 같은 서버를 동시에 바꾸지 않게 하기 위함이다(새 장치의 `flock` 은 옛 실행기를 막지 못한다). 첫 배포·훈련 동안 옛 경로 dispatch 는 금지.
2. 새 배포가 끝나면 옛 실행기의 host baseline·receipt 는 더 이상 현재 상태와 맞지 않는다. 옛 rollback 도 쓰지 않는다 — 되돌리기는 이 장치로 직전 커밋을 다시 `deploy` 한다.
3. 옛 이미지 태그는 이 장치가 새로 3번 배포한 뒤 자동으로 정리 대상이 된다(기록에 있는 것만). 옛 release 폴더·receipts 는 이 장치가 지우지 않는다. 필요하면 `inspect` 로 현재 unit 이 가리키지 않는 것을 확인한 뒤 따로 정리한다.
4. 옛 실행기 브랜치·워크플로 정리 PR 은 별도로 검토한다.

---

## 7. 로컬 시험

서버·docker·systemd 없이 가짜 루트로 돈다:

```
python3 -m unittest discover -s deploy/naver/tests -v
shellcheck -S warning deploy/naver/*.sh
```
