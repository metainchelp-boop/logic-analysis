# ERP 전용 SSH 터널 후보 — 설치 완료 아님

기존 ERP HTTP·blue/green·백업 계정/키/SSH 정책은 유지합니다. 새 BE 계정은 `naver-erp-tunnel` 하나이며, AD의 별도 SSH 서비스가 전용 개인키를 갖습니다. 엔진에는 개인키·known_hosts·SSH 설정을 mount하지 않고 소켓 폴더만 읽기 전용으로 붙입니다. 이 폴더에는 설치/삭제/키 생성 스크립트가 없습니다.

## 파일과 경계

| 후보 | 승인 후 배치 위치 / 의미 |
| --- | --- |
| `be-nginx.conf` | BE `/etc/nginx/conf.d/naver-erp-ingress.conf`; `127.0.0.1:18081`만, 기존 `sales_be_up` 사용 |
| `be-sshd.conf` | BE 신규 계정에만 적용하는 별도 SSH include 후보 |
| `authorized_keys.template` | BE `/etc/ssh/authorized_keys/naver-erp-tunnel`; 새 공개키만, root:root 0644, 부모 root:root 0755 |
| `ad-ssh.conf` | AD `/etc/metainc/naver-erp-tunnel/ssh_config`; root:root 0600 |
| `ad-tunnel.service` | AD의 별도 systemd 서비스 후보; root UID·GID 10001, capability 없음 |

`@BE_SSH_IPV4@`, `@AD_EGRESS_IPV4@`는 실측한 숫자 IPv4, `@NEW_TUNNEL_PUBLIC_KEY_BASE64@`는 새 전용 ED25519 공개키로만 치환합니다. 미치환 상태는 설치 대상이 아닙니다. SSH 개인키는 AD 전용 폴더 root:root 0700 아래 `id_ed25519` root:root 0600, 확인된 BE **ECDSA P-256** host key만 넣은 `known_hosts`도 0600입니다. 서버가 실제 허용하는 host key 알고리즘과 인증용 새 client ED25519 키는 별개입니다. 파일은 symlink/hardlink 없이 단일 link여야 하며 기존 파일·계정·포트 충돌 시 덮어쓰지 않고 중단합니다. 백업용 자격·인증서·계정·설정은 참조하지 않습니다.

소켓은 AD `/run/metainc-naver-erp-tunnel/erp.sock`, 폴더 root:10001 0750, 소켓 root:10001 0660입니다. 엔진의 UID/GID 10001와 그룹 구성, host의 같은 GID에 불필요한 다른 사용자가 없는지 확인합니다. 엔진 mount는 **폴더** `/run/metainc-naver-erp-tunnel` → `/run/naver-erp-tunnel:ro`, `create_host_path: false`입니다. 이 mount는 별도 Compose 후보에서 검증하며 여기서는 실제 Compose를 바꾸지 않습니다.

systemd 249의 숫자 Group에도 GID 10001 그룹 항목이 필요합니다. 기존 이름/GID/사용자가 없을 때만 전용 그룹을 생성하고 기존 그룹은 변경하지 않습니다. 서비스의 ExecStartPre는 같은 cgroup 안에서 BE 숫자 IPv4의 22번 TCP 접속 성공과 loopback 22번의 EACCES/EPERM 또는 TCP timeout을 확인합니다. timeout은 후속 검증에 진입하는 조건일 뿐 필터 적용 성공 증거가 아닙니다. 설치·활성화 완료에는 unit 밖 두 주소의 전후 양성 대조, 실제 unit/PID/cgroup 및 동일 네트워크 namespace, 정확 IPAddressAllow/Deny와 ingress/egress BPF 직접 부착, 소켓 소유권, 소켓→nginx→앱의 무인증 4 route 403·기타 route 400, 기존 앱 기준선 유지가 모두 필요합니다. BPF 조회 권한 거절이나 어느 검증 실패도 신규 서비스 중지로 끝나며 정책을 완화하지 않습니다. probe는 root:root 0600이며 인증·업무 호출·표준출력을 하지 않습니다. 구현 원본은 별도 관리 저장소 `logic-analysis/backend/tools/naver_erp_tunnel_bpf_preflight.py`이며 서버 설치와 인증된 업무 조회·화면 배포는 별개입니다.

## 설치 전 필수 게이트

1. 신규 계정·파일·포트·unit·runtime 폴더가 없는지 확인하고 root/기존 사용자/백업 계정의 SSH 전체 effective policy와 대상 파일 hash, Docker/활성 upstream 기준선을 보관합니다. 후보는 신규 경로에만 배치합니다. SSH fragment의 `Match all` 뒤에 parent 파일의 global-only 항목이 오는 경우까지 **전체** native `sshd -t`로 검사합니다. `sshd -T -C user=...`에서 신규 정책이 모두 적용되고 기존 계정 정책이 byte-equivalent인지 대조합니다. 기존 관리 접속 세션을 유지하며 SSH restart 대신 검증 후 reload만 합니다.
2. 계정은 sudo/추가 그룹 없는 별도 시스템 계정, root 관리 home, 존재하고 실행 가능한 nologin shell을 사용합니다. `MaxSessions 0`가 shell/exec/SFTP를 막으므로 기존 Python 또는 강제 명령 runtime을 쓰지 않습니다. 비밀번호 로그인 금지와 PAM account validity는 서로 다릅니다. 잠긴 계정의 공개키 인증이 해당 서버의 PAM 구성에서 실제 허용되는지 확인하며, 실패를 기존 계정/PAM/global SSH 변경으로 우회하지 않습니다.
3. nginx의 새 18081 설정은 기존 `sales-be.conf`를 대체하지 않습니다. 일반 공개 nginx는 `X-Metainc-Naver-Ingress`를 제거해야 합니다. 앱은 marker가 1이면 UA/신뢰 IP와 무관하게 먼저 exact 4 route와 **GET의 engine 전용 키 / POST의 NAVER_CONTROL 전용 키**를 검증하고, SSO 본문 목적지와 키의 목적지도 대조해야 합니다. marker 자체는 인증이 아니며 기존 trusted-IP 목록을 넓히지 않습니다. 해당 앱 후보가 없으면 ingress를 열지 않습니다.
4. 실제 nginx 1.18/SSH 8.9/systemd 249에서 전체 설정 parser 및 합성 요청 검사를 합니다. `systemd-analyze verify`는 주소 placeholder 치환 후 실행합니다. `IPAddressAllow/Deny`의 cgroup-BPF 지원과 실제 적용 여부를 별도 확인하며 단순 unit 문법 통과를 방화벽 증거로 부르지 않습니다. 기존 HTTP 계약/응답·root/백업 접속·blue/green 교체 후 같은 18081 경유가 유지되는지 대조합니다.
5. AD runtime에서 터널 설정 누락/연결 실패/재시작/잘못된 소켓 권한은 닫혀야 하고 HTTP/DNS/proxy fallback은 0이어야 합니다. 이번 4 route 밖인 alerts/heartbeat/metrics를 기존 HTTP로 보내지 않습니다. 네이버 API 통신과 기존 백업 경로는 별도로 유지합니다. 모든 실제 업무 스위치는 합성 검증이 끝나기 전 켜지 않습니다.

## 네이티브 시험 및 복구 한계

정적 시험: `PYTHONDONTWRITEBYTECODE=1 python3 deploy/naver-erp-tunnel/test_policy.py -v`.

네이티브 시험은 Ubuntu 22.04 일회용 컨테이너에서만 실행합니다. 이미지 빌드 때 공개 패키지를 설치하며, 실행은 반드시 `docker run --rm --network none <시험이미지>`로 외부망을 끊습니다. 실제 Secrets·host 경로·Docker socket은 mount하지 않습니다. 전용 Dockerfile/harness는 합성 SSH 키와 임시 sshd/nginx/HTTP 응답만 사용합니다. 이 시험은 앱의 실제 인증/DB/운영 방화벽을 검증하지 않습니다.

`ExitOnForwardFailure`는 소켓 bind 실패를 잡지만 원격 18081의 건강을 보장하지 않습니다. SSH 연결만 성공했다고 완료로 보고하지 않고 소켓→nginx→앱의 상태/인증 결과를 별도로 확인합니다. SSH server는 **원격 목적지**만 제한할 수 있어 키 소유자가 같은 목적지에 만든 로컬 TCP/SOCKS listener 자체를 막지는 못합니다. 목적지 밖 forwarding, remote forwarding, Unix 원격 목적지, shell/PTY/SFTP는 거절되어야 합니다.

`RuntimeDirectoryPreserve=yes`는 컨테이너 bind가 가리키는 폴더 inode를 유지합니다. 비정상 종료로 소켓이 남으면 `StreamLocalBindUnlink=no`에 따라 자동 재시작은 실패로 닫힙니다. 운영자가 전용 서비스 정지·활성 listener 없음·정확 경로/소켓 종류/소유권을 확인한 후 **그 소켓 하나만** 정리하고 재기동합니다. 폴더를 교체했다면 엔진 mount 재생성이 필요하므로 임의 교체하지 않습니다.

실패 시 AD 신규 서비스만 중지하고 업무 스위치는 닫습니다. 새 nginx/SSH 후보만 격리 후 전체 parser·기존 effective policy와 hash를 확인한 뒤 reload합니다. 현재 파일이 설치 receipt의 예상 hash와 다르면 덮어쓰거나 reload하지 않고 중단합니다. 기존 계정/키/앱/container를 자동 삭제·재시작하지 않습니다. key/요청/응답/행 데이터/SSH stderr 원문을 보고서나 CI artifact로 올리지 않습니다.
