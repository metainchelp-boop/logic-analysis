#!/usr/bin/env python3
"""무통신 비교: 실제 수집기 + 합성 HTTP/시계/저장소. 실서비스 SLA를 추정하지 않는다."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from naver_engine import naver_read as N, performance_reads as current
from naver_engine.tests.test_performance_batch_reads import BatchFixture
from naver_engine.tests.test_performance_reads import MemoryPerformance
from naver_engine.tests.test_morning import A, creds


def baseline_module(ref):
    # 이미 검증한 로컬 Git 객체의 수집기만 읽는다. 체크아웃/파일/운영 상태를 바꾸지 않는다.
    commit = subprocess.check_output(["git", "rev-parse", "--verify", ref+"^{commit}"], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(["git", "show", commit+":naver_engine/performance_reads.py"], cwd=ROOT, text=True)
    name = "naver_engine._performance_benchmark_baseline"
    module = types.ModuleType(name)
    module.__package__ = "naver_engine"
    sys.modules[name] = module
    exec(compile(source, commit+":performance_reads.py", "exec"), module.__dict__)
    return module, commit


class Queue(MemoryPerformance):
    def performance_work(self, now, limit):
        return deepcopy([job for job in self.jobs if self.results.get(job["job_key"], {}).get("status") != "ok"][:limit])


def simulate(module, accounts, campaigns, latency, wait):
    f = BatchFixture(campaigns)
    queue = Queue(f.clock)
    queue.jobs = [dict(f.store.jobs[0], customer_id=A+i, job_key=f"synthetic-{i}") for i in range(accounts)]
    f.http.routes[0] = (f.http.routes[0][0], lambda call: (200, [dict(row,
        nccCampaignId=f"cmp-{call.customer}-{i:04d}", customerId=int(call.customer))
        for i, row in enumerate(f.campaigns)]))
    f.http.tick = lambda call: f.clock.advance(latency)
    start, rounds, first_round = f.clock.monotonic(), 0, None
    while sum(result.get("status") == "ok" for result in queue.results.values()) < accounts:
        reader = N.NaverReader(creds(), transport=f.http, clock=f.clock)
        outcome = module.run_performance(reader, queue, f.clock.now, max_calls=18, max_seconds=20)
        rounds += 1
        if first_round is None:
            first_round = {"calls": reader.calls, "completed": outcome.counts.get("ok", 0),
                           "counts": outcome.counts}
        assert reader.calls <= 18, "회차 호출 예산 초과"
        assert all(value.get("status") in ("ok", "partial") for value in queue.results.values()), "비정상 합성 결과"
        if len(queue.results) == accounts and all(value["status"] == "ok" for value in queue.results.values()):
            break
        assert rounds < accounts*20, "합성 수집이 끝나지 않음"
        f.clock.advance(wait)
    assert all(result["daily_rows"][0]["spend"] == campaigns*1000 for result in queue.results.values())
    return {"accounts": accounts, "campaigns_per_account": campaigns, "calls": len(f.http.calls),
            "rounds": rounds, "synthetic_seconds": round(f.clock.monotonic()-start, 3),
            "first_round": first_round, "round_wait_seconds": wait, "exact_totals_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="847be08ad8c306b7fce3fb427d1cc3168014493f")
    parser.add_argument("--accounts", type=int, default=24)
    args = parser.parse_args()
    if not 1 <= args.accounts <= 300:
        parser.error("합성 계정 수는 1~300입니다")
    old, ref = baseline_module(args.baseline)
    with patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지")):
        results = [{"before": simulate(old, args.accounts, campaigns, 0.2, 60),
                    "after": simulate(current, args.accounts, campaigns, 0.2, 30)} for campaigns in (1, 6, 25)]
    print(json.dumps({"baseline": ref, "network": False, "latency_seconds": 0.2,
        "scope": "performance-only; synthetic storage; no structure/backfill/report costs; not production ETA",
        "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
