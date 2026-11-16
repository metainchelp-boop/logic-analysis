"""현재 배포 게이트 전체 + SEO 시험을 임시 DB/네트워크 금지 상태로 실행한다."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PY_BOOT = """import os,socket,sys
def offline(*a,**k): raise AssertionError('external network forbidden in compatibility checks')
socket.socket.connect=offline
socket.create_connection=offline
target=os.path.abspath(sys.argv[1])
sys.argv=[target]
__file__=target
sys.path.insert(0,os.path.dirname(target))
with open(target,encoding='utf-8') as source: code=compile(source.read(),target,'exec')
exec(code,globals())
"""
NODE_BOOT = """const path=require('node:path');
require('node:net').Socket.prototype.connect=function(){throw Error('external network forbidden');};
global.fetch=()=>Promise.reject(Error('external network forbidden'));
const target=path.resolve(process.argv[1]);process.argv=[process.execPath,target];require(target);
"""


def main():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    gates = list(dict.fromkeys(re.findall(r"\b(python|node) ([\w/-]+tests/[\w.-]+\.(?:py|js))", workflow)))
    for name in ("test_seo_workflow.py", "test_seo_evidence.py", "test_seo_readonly_diagnosis.py"):
        gate = ("python", "backend/tests/" + name)
        if gate not in gates:
            gates.append(gate)
    results = []
    with tempfile.TemporaryDirectory(prefix="seo-regression-") as tmp:
        for number, (runtime, filename) in enumerate(gates):
            env = dict(os.environ, DB_PATH=str(Path(tmp) / f"fixture-{number}.db"),
                       JWT_SECRET_KEY="offline-seo-compatibility-only", PYTHONDONTWRITEBYTECODE="1")
            command = ([sys.executable, "-B", "-c", PY_BOOT, filename] if runtime == "python"
                       else ["node", "-e", NODE_BOOT, filename])
            try:
                completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=75)
                item = {"file": filename, "passed": completed.returncode == 0, "exit_code": completed.returncode}
                if not item["passed"]:
                    item["failure_tail"] = (completed.stdout + completed.stderr)[-2000:]
            except subprocess.TimeoutExpired:
                item = {"file": filename, "passed": False, "failure_tail": "test timeout"}
            results.append(item)
            print(("PASS " if item["passed"] else "FAIL ") + filename, flush=True)
    print(json.dumps({"passed": sum(r["passed"] for r in results), "total": len(results),
                      "failures": [r for r in results if not r["passed"]]}, ensure_ascii=False), flush=True)
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
