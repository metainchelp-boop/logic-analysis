#!/usr/bin/env bash
# CI의 새 네트워크 namespace 안에서만 실행한다. 이 파일 자체는 namespace를 만들지 않는다.
set -euo pipefail

nv_ci_source="$1"
nv_ci_output="$2"
cd "$nv_ci_source"
if [[ "$(id -u)" == 0 ]]; then
  echo '시험 프로세스가 root이면 중단합니다.' >&2
  exit 2
fi

# 실제 외부 접속이 아닌 TEST-NET 주소. lo만 존재하고 route가 없다는 조건부터 검증한다.
python - <<'PY' | tee "$nv_ci_output/network-isolation.txt"
import errno
import json
import os
import socket
import subprocess
import sys

interfaces = json.loads(subprocess.check_output(["ip", "-j", "link", "show"]))
assert {item["ifname"] for item in interfaces} == {"lo"}, "시험 전용 네트워크 namespace가 아닙니다"
assert not subprocess.check_output(["ip", "route", "show"]).strip(), "외부 경로가 있습니다"
assert os.geteuid() != 0, "root 시험 금지"
assert sys.version_info[:2] == (3, 12), "Python 3.12 시험 필요"
with socket.socket() as canary:
    canary.settimeout(1)
    try:
        canary.connect(("192.0.2.1", 443))
    except OSError as error:
        assert error.errno == errno.ENETUNREACH, "외부 연결 거절 사유가 예상과 다릅니다"
    else:
        raise AssertionError("외부 연결이 차단되지 않았습니다")
with socket.socket() as local:
    local.bind(("127.0.0.1", 0))
    local.listen(1)
    with socket.create_connection(local.getsockname(), timeout=1):
        accepted, _ = local.accept()
        accepted.close()
assert not any(name.startswith(("NAVER_MGR_", "ERP_SYNC_")) for name in os.environ)
assert "NAVER_ENGINE_ERP_KEY" not in os.environ
assert "NAVER_AUTO_TOKEN_SECRET" not in os.environ
assert not any(name.startswith("SSO_") for name in os.environ)
print(json.dumps({"external_canary": "ENETUNREACH", "loopback": "ok", "uid": os.geteuid(),
                  "python": sys.version.split()[0], "real_credentials_inherited": False}))
PY

nv_ci_status=0
export NAVER_SCREEN_SHOTS="$nv_ci_output/screenshots"
for nv_ci_suite in naver_engine/tests backend/tests naver_runtime/tests tests; do
  nv_ci_label="${nv_ci_suite//\//-}"
  if python -m unittest discover -s "$nv_ci_suite" -v 2>&1 | tee "$nv_ci_output/$nv_ci_label.txt"; then
    printf '%s: 통과\n' "$nv_ci_suite"
  else
    printf '%s: 실패\n' "$nv_ci_suite" >&2
    nv_ci_status=1
  fi
done
exit "$nv_ci_status"
