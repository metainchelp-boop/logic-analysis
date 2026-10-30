#!/usr/bin/env bash
# 제품 단위 시험 — naver_engine/tests, naver_runtime/tests, backend/tests/test_naver_relay*.
# 제품 저장소 tools/naver-runtime-ci-tests.sh 와 같은 방식(unittest discover -v, PYTHONPATH=backend:.,
# 비루트, 외부망 없는 namespace, NAVER_SCREEN_REQUIRE_BROWSER=1·NAVER_RELAY_REQUIRE_APP=1 은 호출하는 쪽이 준다).
#
# 이 저장소(logic-analysis)는 공개라 Actions 로그도 공개다. 비공개 제품 소스가 traceback 으로 새지
# 않게 전체 출력은 러너 임시 폴더에만 두고, 로그에는 묶음별 요약과 실패한 시험 이름만 낸다.
#
# 사용: product-tests.sh <제품 소스 폴더> <출력 폴더>
set -euo pipefail

source_dir=$1
output_dir=$2
cd "$source_dir"
if [ "$(id -u)" = 0 ]; then
  echo '시험 프로세스가 root 이면 중단합니다.' >&2
  exit 2
fi

# 제품 CI 와 같은 격리 확인: lo 만 있고 경로가 없으며 외부 연결이 막혀 있어야 한다.
python - <<'PY'
import errno
import json
import os
import socket
import subprocess
import sys

interfaces = json.loads(subprocess.check_output(["ip", "-j", "link", "show"]))
assert {item["ifname"] for item in interfaces} == {"lo"}, "시험 전용 네트워크 namespace 가 아닙니다"
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
assert not any(name.startswith(("NAVER_MGR_", "ERP_SYNC_", "SSO_")) for name in os.environ)
assert "NAVER_ENGINE_ERP_KEY" not in os.environ and "NAVER_AUTO_TOKEN_SECRET" not in os.environ
print(json.dumps({"external_canary": "ENETUNREACH", "uid": os.geteuid(), "python": sys.version.split()[0]}))
PY

status=0
export NAVER_SCREEN_SHOTS="$output_dir/screenshots"

run_suite() { # label discover-args...
  local label=$1 result ran last
  shift
  if python -m unittest discover "$@" -v >"$output_dir/$label.txt" 2>&1; then
    result=통과
  else
    result=실패
    status=1
  fi
  ran=$(grep -E '^Ran [0-9]+ tests? in ' "$output_dir/$label.txt" | tail -n 1 || true)
  last=$(grep -E '^(OK|FAILED)( |$)' "$output_dir/$label.txt" | tail -n 1 || true)
  printf '%s: %s · %s · %s\n' "$label" "$result" "${ran:-Ran ?}" "${last:-?}"
  if [ "$result" = 실패 ]; then
    grep -E '^(FAIL|ERROR): ' "$output_dir/$label.txt" | head -n 50 || true
  fi
}

run_suite naver_engine-tests -s naver_engine/tests
run_suite naver_runtime-tests -s naver_runtime/tests
run_suite backend-test_naver_relay -s backend/tests -p 'test_naver_relay*.py'
exit "$status"
