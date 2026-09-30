"""GitHub 임시 runner의 로컬 이미지로 Compose raw 환경값 보존을 직접 확인한다.

가짜 값만 넣은 별도 일회용 컨테이너이며 네트워크·볼륨·실제 환경 파일은 없다.
config 출력에서 $를 $$로 표기하는 것과 컨테이너가 받은 실제 값을 구분한다.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"naver-runtime-ci:[0-9a-f]{40}", args.image):
        raise SystemExit("전용 CI 임시 이미지에서만 실행합니다")
    value = 'literal:$NAVER_PACKAGE_UNSET:${NAVER_PACKAGE_UNSET:-expanded}:$$:"quoted"'
    with tempfile.TemporaryDirectory(prefix="naver-image-contract-") as folder:
        root = Path(folder)
        envfile = root / "synthetic.env"
        envfile.write_text("NAVER_PACKAGE_RAW_CANARY=" + value + "\n", encoding="utf-8")
        envfile.chmod(0o600)
        check = ("import os; assert os.environ['NAVER_PACKAGE_RAW_CANARY'] == " + repr(value)
                 + "; assert os.geteuid() == 10001; print('raw-env-preserved')")
        config = {"services": {"probe": {
            "image": args.image, "pull_policy": "never", "network_mode": "none", "read_only": True,
            "user": "10001:10001", "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
            "pids_limit": 16, "env_file": [{"path": str(envfile), "format": "raw", "required": True}],
            "command": ["python", "-c", check]}}}
        compose = root / "compose.json"
        # 명령 문자열의 $가 Compose 자체에서 바뀌지 않도록 인자도 escape한다.
        config["services"]["probe"]["command"][2] = check.replace("$", "$$")
        compose.write_text(json.dumps(config), encoding="utf-8")
        env = {"PATH": os.environ["PATH"], "COMPOSE_DISABLE_ENV_FILE": "1"}
        subprocess.run(["docker", "compose", "--project-name", "naver-raw-env-ci", "--file", str(compose),
                        "run", "--rm", "--no-deps", "--pull", "never", "-T", "probe"],
                       env=env, check=True, timeout=60)


if __name__ == "__main__":
    main()
