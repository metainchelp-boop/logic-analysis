#!/usr/bin/env python3
"""합성 원천 + 실제 Store 메서드의 메모리 SQL 비용. 운영 속도 추정용이 아니다.

파일 Store의 단일 writer 잠금, WAL/fsync, 실제 HTTP 지연은 시험하지 않는다.
현재 위임·원천·조직·매칭·단계 검사와 synchronize_management는 실제 구현이다.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
from time import perf_counter
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.naver_auto import matching as M  # noqa: E402
from naver_engine import erp_read as E, management as MP, naver_read as N, store as S  # noqa: E402
from naver_engine.tests import test_account_catalog as TC, test_alerts as TA, test_morning as TM  # noqa: E402
from naver_engine.tests.test_performance_batch_reads import BatchFixture  # noqa: E402


METHODS = (
    "inventory_account_valid", "inventory_snapshot", "account_catalog",
    "account_catalog_status", "org_current", "decision_fingerprint",
    "management_states", "current_decisions", "synchronize_management",
    "performance_account_valid",
)


def make_fixture(accounts=1793, managed=764, campaigns=25, history_days=0):
    """합성 SQL만 만든다. 반환 Store에는 fixture의 검증 override가 없다."""
    if not 1 <= managed <= accounts <= 10000 or not 0 <= campaigns <= 1000 or not 0 <= history_days <= 40:
        raise ValueError("합성 규모 범위가 올바르지 않습니다")
    fixture = BatchFixture(campaigns)
    connection = sqlite3.connect(":memory:", isolation_level=None)
    for statement in S._SCHEMA:
        connection.execute(statement)
    for table, columns in S._REVISION_COLUMNS.items():
        for name, definition in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    store = S.Store(connection, ":memory:", None, writer=True, clock=fixture.clock.now)
    try:
        now = fixture.clock.now()
        names = {TM.A + n: hashlib.sha256(str(n).encode()).hexdigest()[:16] for n in range(accounts)}
        store.record_org(TA.org_body(now, owners=[TA.owner(11 + n, 100) for n in range(managed)]), now)
        children = {cid: {"customerId": cid, "adAccountNo": 8000000 + n, "adAccountName": name}
                    for n, (cid, name) in enumerate(names.items())}
        store.record_accounts(N.ChildAccounts(children, {1: accounts}, ()), now)
        store.record_account_catalog({"generated_at": now.isoformat(), "total": managed, "complete": True,
            "items": [TC.company(11 + n, "진행중", company_name=names[TM.A + n]) for n in range(managed)]},
            [E.NaverIdRow(11 + n, M.VENDOR_NAVER, str(TM.A + n)) for n in range(managed)], now)
        for n in range(managed):
            store.record_decision(11 + n, TM.A + n, "confirmed", 0, now)
        if history_days:
            store.synchronize_management(now)
            states, fingerprint = store.management_states(), store.decision_fingerprint()
            rows = []
            for ago in range(1, history_days + 1):
                cycle = now.date() - timedelta(days=ago)
                day, at = cycle - timedelta(days=1), MP.generation_for(cycle)
                for n in range(managed):
                    cid = TM.A + n
                    rows.append((f"{cid}:daily:{cycle}:{day}:{day}", cid, "daily", str(cycle), str(day),
                        str(day), at, at, states[cid]["stage_revision"], 11 + n, fingerprint,
                        "ok", at, at, 0, at))
            # 후보 조회가 참조하는 완결 이력만 합성한다. 성과값의 성공 검증을 대신하지 않는다.
            connection.executemany("""INSERT INTO naver_auto_performance_job
                (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
                 stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts,generation)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        fixture.store = store
        return fixture
    except BaseException:
        store.close()
        raise


def run_benchmark(accounts=1793, managed=764, campaigns=25, history_days=0):
    """외부 연결은 거절한다. 시간은 중첩 계측이므로 항목 합산을 하지 않는다."""
    with patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지")), \
            patch.object(socket.socket, "connect_ex", side_effect=AssertionError("외부 송신 금지")):
        fixture = make_fixture(accounts, managed, campaigns, history_days)
        store = fixture.store
        timings = defaultdict(lambda: [0, 0.0])
        sql = {"statements": 0, "commits": 0}

        def trace(statement):
            sql["statements"] += 1
            sql["commits"] += statement == "COMMIT"

        def wrap(name, original):
            def measured(*args, **kwargs):
                started = perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    timings[name][0] += 1
                    timings[name][1] += perf_counter() - started
            return measured

        for name in METHODS:
            setattr(store, name, wrap(name, getattr(store, name)))
        store._conn.set_trace_callback(trace)

        def result(phase, started, **extra):
            return {"phase": phase, "wall_seconds": round(perf_counter() - started, 6),
                    **sql, **extra, "methods": {name: {"calls": count, "milliseconds": round(seconds * 1000, 3)}
                                                for name, (count, seconds) in timings.items()}}

        def reset():
            timings.clear()
            sql.update(statements=0, commits=0)

        try:
            started = perf_counter()
            jobs = store.performance_work(fixture.clock.now(), 24)
            queue = result("candidate_selection", started, selected_jobs=len(jobs))
            if not jobs:
                raise AssertionError("합성 관리계정 후보가 없습니다")
            reset()
            started = perf_counter()
            for _ in range(20):
                if not store.performance_account_valid(jobs[0], fixture.clock.now()):
                    raise AssertionError("합성 원천의 실제 권한 검증이 실패했습니다")
            validation = result("authority_validation_20", started)
            reset()
            started = perf_counter()
            # 계정 1곳만 실제 수집한다. 전체 후보 생성 비용은 limit=1이어도 포함된다.
            outcome = fixture.run(limit=1, max_calls=18, max_seconds=20)
            collection = result("collect_one_account", started, code=outcome.code, counts=outcome.counts,
                                http_calls=fixture.reader.calls)
            if any(call.method != "GET" for call in fixture.http.calls):
                raise AssertionError("GET 외 요청이 생겼습니다")
            return {"notice": "합성 원천과 실제 Store 메서드의 메모리 SQL 측정입니다. 운영 속도 추정이 아닙니다.",
                    "coverage": "실제 synchronize_management/MS.snapshot/매칭/권한 검사 사용. 파일 잠금·WAL/fsync·운영 데이터·실제 HTTP 지연 미검증.",
                    "timing_note": "메서드 시간은 중첩되므로 서로 더하지 않습니다. 호출 속도 제한은 가상 시계로 유지됩니다.",
                    "accounts": accounts, "managed": managed, "campaigns": campaigns,
                    "completed_history_days": history_days, "phases": [queue, validation, collection]}
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", type=int, default=1793, help="합성 전체 계정 수(1~10000)")
    parser.add_argument("--managed", type=int, help="합성 관리계정 수(기본 min(764, accounts))")
    parser.add_argument("--campaigns", type=int, default=25, help="첫 계정의 합성 캠페인 수(0~1000)")
    parser.add_argument("--history-days", type=int, default=0, help="과거 완결 작업 이력 일수(0~40)")
    args = parser.parse_args()
    managed = min(764, args.accounts) if args.managed is None else args.managed
    if not 1 <= managed <= args.accounts <= 10000 or not 0 <= args.campaigns <= 1000 or not 0 <= args.history_days <= 40:
        parser.error("1 <= managed <= accounts <= 10000, 0 <= campaigns <= 1000, 0 <= history-days <= 40이어야 합니다")
    print(json.dumps(run_benchmark(args.accounts, managed, args.campaigns, args.history_days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
