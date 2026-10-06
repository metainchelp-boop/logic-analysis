"""보고서 생성 가볍게 · 잘게 — 옛 판(a981b35) 그대로 옮긴 사본과 표 해시 대조 (NV-S00 · 쓰기 줄 막힘 해소).

같은 입력을 두 벌 만든다. 한 벌은 옛 생성(tests/_report_a981b35.py — 글자 그대로 옮긴 정답), 다른 벌은 새 생성(지도 ·
판 사실 기억 · 겹침표 · 높이표)으로 돌린 뒤 판 · dirty · 대조 상태 · 관리 상태 · 짝 기억 표를 줄 번호까지 SHA-256 으로
견준다. 반환값(세 칸)과 예외 종류도 같아야 한다. 저장소는 두 가지 — 메모리 SQLite(ReportAdapter)와 실제 쓰기 저장소
(open_writer · WAL · 잠금 · 연결 거절 규칙 · BEGIN IMMEDIATE)다. 관리 판단 · 열린 이슈만 같은 가짜를 붙인다.
"""
from datetime import date, datetime, timedelta
import hashlib
import inspect
import json
import os
import pathlib
import re
import shutil
import sqlite3
import tempfile
from types import MethodType, SimpleNamespace
import unittest

from naver_engine import reporting as R, store as S
from naver_engine.tests import _report_a981b35 as OLD
from naver_engine.tests.test_report_revisions import ReportAdapter

NOW = datetime(2026, 10, 5, 10, tzinfo=S.KST)   # 월요일 10:00 — 9/28~10/4 주간 기한과 같은 시각
WEEKS = [R.period("weekly", date(2026, 9, 1)+timedelta(days=7*n)) for n in range(6)]   # 9/1 주 ~ 10/5 주
SEPT = R.period("monthly", date(2026, 9, 1))
TABLES = ("naver_auto_report_snapshot", "naver_auto_report_dirty", "naver_auto_report_validation",
          "naver_auto_report_review", "naver_auto_management_state", "naver_auto_management_event",
          "naver_auto_link_memory")
ROOT = pathlib.Path(__file__).resolve().parents[2]


class SliceAdapter(ReportAdapter):
    """ReportAdapter + 계정별 주기(주간 주기 계정의 재대조 기준을 보려고)."""
    def __init__(self):
        super().__init__()
        self.cadences = {}

    def synchronize_management(self, now):
        return _decisions(self, now)


def _decisions(st, now):
    return {cid: {"possibility_id": pid, "stage": st.stage,
                  "decision": SimpleNamespace(cadence=st.cadences.get(cid, st.cadence), attributable=st.attributable)}
            for cid, pid in st.groups.items()}


def memory_store(test):
    st = SliceAdapter()
    test.addCleanup(st._conn.close)
    return st


def real_store(test):
    """실제 쓰기 저장소. 관리 판단 · 사람 확인 · 열린 이슈만 ReportAdapter 와 같은 가짜(외부 원장이 필요 없게)."""
    folder = tempfile.mkdtemp(prefix="nv-report-")
    test.addCleanup(shutil.rmtree, folder, True)
    box = []
    st = S.open_writer(os.path.join(folder, "engine.db"), clock=lambda: box[0].now if box else NOW)
    box.append(st)
    test.addCleanup(st.close)
    st.now = NOW
    st.groups, st.cadence, st.stage, st.cadences = {101: 11}, "daily", "진행중", {}
    st.attributable, st.human_confirmed, st.open_issue_pids, st.fail_period = True, True, set(), None
    st.synchronize_management = MethodType(_decisions, st)
    for name in ("current_decisions", "issues", "seed", "recheck"):
        setattr(st, name, MethodType(getattr(ReportAdapter, name), st))
    return st


def digest(st):
    out = {}
    for table in TABLES:
        h, n = hashlib.sha256(), 0
        for row in st._conn.execute(f"SELECT rowid,* FROM {table} ORDER BY rowid"):
            h.update(repr(row).encode())
            n += 1
        out[table] = (n, h.hexdigest())
    return out


def old_generate(st):
    return OLD._report_generate(st, st.now)


def new_generate(st):
    return st.generate_reports(st.now)


def insert_snapshot(st, pid, key, payload, review_status="not_required", status="ready"):
    """판은 넣기만 한다 — 시험도 옛 판·다른 판을 「넣어서」 만든다(기존 줄을 고치면 판 사실 기억과 어긋난다)."""
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return st._conn.execute("""INSERT INTO naver_auto_report_snapshot
        (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
        VALUES(?,?,?,?,?,?,?)""", (pid, key, "legacy-"+key, "2026-10-03T12:00:00+09:00", status, review_status, raw)).lastrowid


def legacy_payload(period, cid=101, *, version=None, spend=1000):
    """형식 1(합계만) 옛 판. version=None 이면 키가 없다 — 그 밖은 그 값을 그대로 싣는다."""
    days = [{"customer_id": cid, "day": str(period.start+timedelta(days=n)), "basic_complete": True,
             "conversion_complete": True, "imp": 100, "clk": 10, "spend": spend, "conversions": 1,
             "conversion_value": 2000, "checked_at": NOW.isoformat()} for n in range((period.end-period.start).days+1)]
    payload = R.aggregate(period, [cid], days, NOW)
    if version is not None:
        payload["format_version"] = version
    return payload


def copy_latest(st, pid, key):
    """지금 최신 판과 같은 판을 하나 더 넣는다(같은 검토 상태·형식 — 등록 판정은 그대로 · 판 수와 최신 번호만 바뀐다)."""
    row = st._conn.execute("""SELECT possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json
        FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""",
        (pid, key)).fetchone()
    return st._conn.execute("""INSERT INTO naver_auto_report_snapshot
        (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
        VALUES(?,?,?,?,?,?,?)""", row).lastrowid


def run(st, generate):
    try:
        result = generate(st)
    except Exception as error:   # 예외 종류도 대조한다(문구는 값이 섞일 수 있어 보지 않는다)
        result = ("error", type(error).__name__)
    return result, digest(st)


# ── 시나리오: 같은 순서로 두 저장소를 바꾸며 생성을 부른다. 생성마다 (반환, 표 해시) 를 모은다. ──
def sc_idle(st, gen):
    st.seed(date(2026, 9, 1), date(2026, 10, 4))
    return [gen(st), gen(st), gen(st)]


def sc_partial_dirty(st, gen):
    st.groups = {101: 11, 102: 12, 103: 13}
    for cid, pid in st.groups.items():
        st.seed(date(2026, 9, 1), date(2026, 10, 4), cid=cid, pid=pid)
    out = [gen(st)]
    st.now += timedelta(hours=1)
    st.seed(date(2026, 9, 23), date(2026, 9, 23), cid=102, pid=12, spend=2500)
    out += [gen(st), gen(st)]
    return out


def sc_over_cap(st, gen):
    st.groups = {101+n: 11+n for n in range(23)}
    for n in range(23):
        st.seed(date(2025, 8, 6), date(2025, 8, 6), cid=101+n, pid=11+n)
    return [gen(st), gen(st), gen(st)]


def sc_consecutive(st, gen):
    st.seed(date(2026, 9, 1), date(2026, 10, 4))
    out = [gen(st)]
    st.now += timedelta(hours=1)
    # 9/21 주의 원천이 바뀌면 그 주와(수집 dirty) 다음 주(전파)를 한 거래에서 다시 만든다 — 다음 주는 방금 넣은 판을 참조한다.
    st.seed(WEEKS[3].start, WEEKS[3].start, spend=3000)
    out += [gen(st), gen(st)]
    return out


def sc_legacy(st, gen):
    # 원천 있는 옛 판(형식 1 · 키 없음) → 재구성 새 판. 원천 없는 옛 판(9/1 주) → 미보관 유지(매번 다시 표시 · 새 판 없음).
    st.seed(WEEKS[1].start, date(2026, 10, 4))
    insert_snapshot(st, 11, WEEKS[0].key, legacy_payload(WEEKS[0]))
    insert_snapshot(st, 11, WEEKS[2].key, legacy_payload(WEEKS[2], version=1))
    insert_snapshot(st, 11, WEEKS[3].key, legacy_payload(WEEKS[3], version=1.0))
    insert_snapshot(st, 11, SEPT.key, legacy_payload(SEPT, version=True), review_status="needs_staff_review")
    out = [gen(st), gen(st)]
    st.now += timedelta(minutes=1)
    out.append(gen(st))
    return out


def sc_policy_and_accounts(st, gen):
    st.seed(date(2026, 9, 1), date(2026, 10, 4))
    st.seed(date(2026, 9, 1), date(2026, 10, 4), cid=103)   # 주간 주기 계정 — 업체 원천에 있지만 매일 관리 대상은 아님
    st.cadences[103] = "weekly"
    out = [gen(st)]
    st.open_issue_pids.add(11)            # 열린 이슈 → 주간 검토 정책 변화
    st.now += timedelta(minutes=1)
    out.append(gen(st))
    st.groups[102] = 11                   # 새 계정 연결 → 기대 계정 증가
    st.now += timedelta(minutes=1)
    out.append(gen(st))
    st.open_issue_pids.clear()
    st.now += timedelta(minutes=1)
    out += [gen(st), gen(st)]
    return out


def sc_not_due_and_outside(st, gen):
    st.seed(date(2026, 9, 1), date(2026, 10, 6))   # 10/5 주 · 10월은 아직 기한 전
    st.seed(date(2026, 9, 1), date(2026, 9, 30), cid=199, pid=99)   # 관리 대상 밖 업체의 dirty 는 남는다
    return [gen(st), gen(st)]


def sc_deadline(st, gen):
    st.seed(date(2026, 9, 1), date(2026, 10, 4))
    st.now = NOW-timedelta(microseconds=1)   # 9/28 주 기한(10:00) 바로 전
    out = [gen(st)]
    st.now = NOW
    out += [gen(st), gen(st)]
    return out


def sc_recheck(st, gen):
    month = SEPT
    st.seed(month.start, month.end)
    out = [gen(st)]
    st.now += timedelta(hours=1)
    st.recheck(month.start, month.end, "reading")
    out.append(gen(st))
    st.recheck(month.start, month.end, "ok")
    out.append(gen(st))
    return out


SCENARIOS = {"idle": sc_idle, "partial_dirty": sc_partial_dirty, "over_cap": sc_over_cap,
             "consecutive": sc_consecutive, "legacy": sc_legacy, "policy_accounts": sc_policy_and_accounts,
             "not_due_outside": sc_not_due_and_outside, "deadline": sc_deadline, "recheck": sc_recheck}
REAL_SCENARIOS = ("idle", "partial_dirty", "over_cap", "consecutive", "legacy")


class OracleEquivalenceTest(unittest.TestCase):
    """옛 생성과 새 생성이 같은 입력에서 같은 줄을 쓴다(줄 번호 · 값 · 판 바이트 · 반환 · 예외)."""
    generate = staticmethod(new_generate)

    def compare(self, factory, name):
        scenario = SCENARIOS[name]
        expected = scenario(factory(self), lambda st: run(st, old_generate))
        actual = scenario(factory(self), lambda st: run(st, self.generate))
        self.assertEqual(len(actual), len(expected))
        for step, (got, want) in enumerate(zip(actual, expected)):
            with self.subTest(scenario=name, step=step):
                self.assertEqual(got[0], want[0])
                self.assertEqual(got[1], want[1])
        return expected

    def test_memory_store_matches_old_generation_in_every_scenario(self):
        for name in SCENARIOS:
            self.compare(memory_store, name)

    def test_real_writer_store_matches_old_generation(self):
        for name in REAL_SCENARIOS:
            self.compare(real_store, name)

    def test_scenarios_really_exercise_the_paths_they_name(self):
        # 시나리오가 헛돌면 대조가 아무것도 증명하지 못한다 — 각 길이 실제로 쓰였는지 옛 생성 결과로 확인한다.
        cap = self.compare(memory_store, "over_cap")
        self.assertEqual([r[0]["advertisers"] for r in cap], [20, 3, 0])
        idle = self.compare(memory_store, "idle")
        self.assertGreater(idle[0][0]["generated"], 0)
        self.assertEqual([r[0]["generated"] for r in idle[1:]], [0, 0])
        legacy = self.compare(memory_store, "legacy")
        st = memory_store(self)
        sc_legacy(st, new_generate)
        statuses = {key: json.loads(raw)["details"]["status"] for key, raw in st._conn.execute(
            """SELECT period_key,payload_json FROM naver_auto_report_snapshot WHERE report_id IN
               (SELECT MAX(report_id) FROM naver_auto_report_snapshot GROUP BY possibility_id,period_key)""")
            if "details" in json.loads(raw)}
        self.assertEqual(statuses[WEEKS[2].key], "reconstructed")
        self.assertEqual(statuses[WEEKS[3].key], "reconstructed")
        self.assertEqual(statuses[SEPT.key], "reconstructed")
        self.assertNotIn(WEEKS[0].key, statuses)   # 원천 없는 옛 판은 그대로(미보관) — 빈 새 판으로 바꾸지 않는다
        self.assertEqual(legacy[-1][0]["generated"], 0)


class FormatJudgementTest(unittest.TestCase):
    """형식 번호가 숫자가 아닐 때는 원문 파이썬 판정을 그대로 — 오류도 같은 자리 · 같은 종류."""
    def judged(self, version, review_status="not_required"):
        def scenario(st, gen):
            st.seed(date(2026, 9, 1), date(2026, 10, 4))
            out = [gen(st)]
            payload = json.loads(st._conn.execute("""SELECT payload_json FROM naver_auto_report_snapshot
                WHERE period_key=? ORDER BY report_id DESC LIMIT 1""", (WEEKS[4].key,)).fetchone()[0])
            payload["format_version"] = version
            insert_snapshot(st, 11, WEEKS[4].key, payload, review_status=review_status)
            st.now += timedelta(minutes=1)
            return out+[gen(st), gen(st)]
        return (scenario(memory_store(self), lambda st: run(st, old_generate)),
                scenario(memory_store(self), lambda st: run(st, new_generate)))

    def test_non_numeric_versions_follow_the_original_python_comparison(self):
        for version in (None, "2", 1.0, 2.0, True, False, [2], {"v": 2}, 2, 3):
            with self.subTest(version=version):
                old, new = self.judged(version)
                self.assertEqual(new, old)

    def test_null_version_raises_type_error_like_the_original_and_changes_no_dirty_row(self):
        old, new = self.judged(None)
        self.assertEqual(new[1][0], ("error", "TypeError"))
        self.assertEqual(new[1][1]["naver_auto_report_dirty"], new[0][1]["naver_auto_report_dirty"])
        self.assertEqual(new, old)

    def test_review_mismatch_short_circuits_before_the_format_comparison(self):
        # 원문 등록 검사는 검토 상태가 다르면 형식을 보지 않는다 — 글자 "2" 도 등록(다시 표시)은 확정되고,
        # 그 판을 다시 만드는 업체 거래에서 원문과 같은 자리 · 같은 종류(TypeError)로 멈춘다.
        old, new = self.judged("2", review_status="needs_staff_review")
        self.assertEqual(new[1][0], ("error", "TypeError"))
        self.assertNotEqual(new[1][1]["naver_auto_report_dirty"], new[0][1]["naver_auto_report_dirty"])
        self.assertEqual(new, old)


class OverlapAndHighWaterTest(unittest.TestCase):
    def latest(self, st, key):
        return st._conn.execute("""SELECT report_id,payload_json FROM naver_auto_report_snapshot
            WHERE possibility_id=11 AND period_key=? ORDER BY report_id DESC LIMIT 1""", (key,)).fetchone()

    def test_next_week_in_the_same_transaction_references_the_report_just_inserted(self):
        st = memory_store(self)
        sc_consecutive(st, new_generate)
        week, following = self.latest(st, WEEKS[3].key), self.latest(st, WEEKS[4].key)
        reference = json.loads(following[1])["details"]["comparison"]["reference"]
        self.assertEqual(reference["report_id"], week[0])
        self.assertEqual(reference["period_key"], WEEKS[3].key)

    def test_rows_inserted_after_the_plan_rebuild_the_map_and_match_the_oracle(self):
        def prepare(st):
            st.groups = {101: 11, 102: 12}
            for cid, pid in st.groups.items():
                st.seed(date(2026, 9, 1), date(2026, 10, 4), cid=cid, pid=pid)
            old_generate(st)
            st.now += timedelta(hours=1)
            for cid, pid in st.groups.items():
                st.seed(WEEKS[3].start, WEEKS[3].start, cid=cid, pid=pid, spend=4000)
        expected = memory_store(self)
        prepare(expected)
        for pid in (11, 12):
            copy_latest(expected, pid, WEEKS[3].key)   # 계획 뒤에 들어온 판(등록 판정은 바꾸지 않는 같은 판)
        want = run(expected, old_generate)

        st = memory_store(self)
        prepare(st)
        cycle = S._report_plan(st, st.now)
        self.assertEqual([pid for pid, _ in cycle.batches], [11, 12])
        for pid in (11, 12):
            copy_latest(st, pid, WEEKS[3].key)
        for pid, targets in cycle.batches:
            S._report_batch(st, cycle, pid, targets)
        self.assertEqual((cycle.result(), digest(st)), want)
        # 새 판의 판 번호 · 이전 판 번호가 끼어든 판을 센다(지도를 다시 만들지 않았다면 하나씩 작다)
        payload = json.loads(self.latest(st, WEEKS[3].key)[1])
        self.assertEqual(payload["revision_no"], 3)


class RollbackCacheTest(unittest.TestCase):
    def test_failed_insert_does_not_poison_counts_or_the_fact_memory(self):
        def scenario(st, gen):
            st.seed(date(2026, 8, 1), date(2026, 8, 31))
            out = [gen(st)]
            st.now += timedelta(hours=1)
            st.seed(date(2026, 8, 17), date(2026, 8, 17), spend=2000)
            st.fail_period = R.period("weekly", date(2026, 8, 17)).key   # 같은 거래의 두 번째 판 넣기에서 실패
            out.append(gen(st))
            st.fail_period = None
            out += [gen(st), gen(st)]
            return out
        old = scenario(memory_store(self), lambda st: run(st, old_generate))
        st = memory_store(self)
        new = scenario(st, lambda st: run(st, new_generate))
        self.assertEqual(old[1][0], ("error", "OperationalError"))
        self.assertEqual(new, old)
        live = {row[0] for row in st._conn.execute("SELECT report_id FROM naver_auto_report_snapshot")}
        self.assertLessEqual(set(st._report_fact_cache), live)

    def test_facts_read_inside_a_transaction_are_not_remembered(self):
        # 되돌려진 판의 번호는 다음 판이 다시 쓴다 — 거래 안에서 읽은 사실을 기억하면 다른 판의 사실로 둔갑한다.
        st = memory_store(self)
        payload = legacy_payload(WEEKS[0], version=2)
        st._conn.execute("BEGIN")
        rid = insert_snapshot(st, 11, WEEKS[0].key, payload, review_status="needs_staff_review")
        self.assertEqual(S._report_facts(st, st._conn, [rid])[rid][0], "needs_staff_review")
        st._conn.execute("ROLLBACK")
        again = insert_snapshot(st, 11, WEEKS[0].key, legacy_payload(WEEKS[0], version=1))
        self.assertEqual(again, rid)
        self.assertEqual(S._report_facts(st, st._conn, [rid])[rid], ("not_required", 1, 1))


class StatementBudgetTest(unittest.TestCase):
    """판 표를 업체 · 기간 수만큼 훑지 않는다 — 문장 수로 고정한다(시간이 아니라 모양)."""
    def traced(self, st, fn):
        statements = []
        st._conn.set_trace_callback(statements.append)
        try:
            return fn(), statements
        finally:
            st._conn.set_trace_callback(None)

    @staticmethod
    def snapshot_statements(statements):
        return [" ".join(s.split()) for s in statements if "naver_auto_report_snapshot" in s]

    def build(self, pids=12):
        st = memory_store(self)
        st.groups = {101+n: 11+n for n in range(pids)}
        for n in range(pids):
            st.seed(date(2026, 9, 1), date(2026, 10, 4), cid=101+n, pid=11+n)
        st.generate_reports(st.now)
        return st

    def test_idle_plan_reads_the_snapshot_table_once_plus_new_facts_only(self):
        st = self.build()
        st._report_fact_cache = {}   # 엔진을 막 켠 것처럼 — 최신 판 사실을 처음 읽는다
        latest = st._conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM naver_auto_report_snapshot GROUP BY possibility_id,period_key)").fetchone()[0]
        _, first = self.traced(st, lambda: S._report_plan(st, st.now))
        reads = self.snapshot_statements(first)
        self.assertEqual(sum("GROUP BY possibility_id,period_key" in s for s in reads), 1)
        facts = [s for s in reads if "json_extract" in s]
        self.assertEqual(len(facts), -(-latest // S.REPORT_FACTS_CHUNK))
        self.assertEqual(len(reads), 1+len(facts))
        # 두 번째 회차: 판 사실은 기억에서 — 판 본문(JSON)을 읽는 문장이 하나도 없다
        _, second = self.traced(st, lambda: S._report_plan(st, st.now))
        reads = self.snapshot_statements(second)
        self.assertEqual(len(reads), 1)
        self.assertFalse([s for s in second if "json_extract" in s or "payload_json" in s])

    def test_batch_reads_at_most_two_rows_by_number_per_target(self):
        st = self.build(pids=3)
        st.now += timedelta(hours=1)
        for n in range(3):
            st.seed(date(2026, 9, 1), date(2026, 9, 30), cid=101+n, pid=11+n, spend=1500)
        cycle = S._report_plan(st, st.now)
        targets = sum(len(periods) for _pid, periods in cycle.batches)
        self.assertGreater(targets, 3)
        def batches():
            for pid, periods in cycle.batches:
                S._report_batch(st, cycle, pid, periods)
        _, statements = self.traced(st, batches)
        reads = [s for s in self.snapshot_statements(statements) if s.startswith("SELECT")]
        by_number = [s for s in reads if "WHERE report_id=" in s]
        tops = [s for s in reads if s.startswith("SELECT MAX(report_id)")]
        self.assertEqual(len(tops), len(cycle.batches))     # 높이표 한 번씩(가장 큰 번호 — 색인 끝 한 칸)
        self.assertLessEqual(len(by_number), 2*targets)
        self.assertEqual(len(reads), len(tops)+len(by_number))   # 판 표 훑기(GROUP BY · 업체·기간 조건) 없음
        self.assertGreater(cycle.made, 0)


class ReadSideTest(unittest.TestCase):
    """최신 판 목록(JOIN)과 검토 한 건 조회가 옛 상관 부분질의 · 전체 목록 고르기와 같은 답을 낸다."""
    def build(self, st):
        st.groups = {101: 11, 102: 12}
        for cid, pid in st.groups.items():
            st.seed(date(2026, 9, 1), date(2026, 10, 4), cid=cid, pid=pid)
        legacy = legacy_payload(WEEKS[0])   # 판 번호(revision_no) 없는 옛 판 — 표시 번호를 판 수로 센다
        insert_snapshot(st, 12, WEEKS[0].key, legacy)
        insert_snapshot(st, 12, WEEKS[0].key, legacy)
        st.generate_reports(st.now)
        st.now += timedelta(hours=1)
        st.seed(WEEKS[3].start, WEEKS[3].start, spend=5000)
        st.generate_reports(st.now)
        st.seed(WEEKS[4].start, WEEKS[4].start, spend=7000)   # 대기 dirty 가 남은 최신 판(갱신 중으로 보인다)
        return st

    def test_latest_list_matches_the_correlated_subquery_on_writer_and_reader(self):
        st = self.build(real_store(self))
        self.assertEqual(st.report_snapshots(), OLD._report_snapshots(st))
        self.assertTrue(any(row["validation"]["status"] == "updating" for row in st.report_snapshots()))
        reader = S.open_reader(st._path)
        self.addCleanup(reader.close)
        reader._clock = st._clock
        self.assertEqual(reader.report_snapshots(), OLD._report_snapshots(reader))
        memory = self.build(memory_store(self))
        self.assertEqual(memory.report_snapshots(), OLD._report_snapshots(memory))

    def test_current_lookup_matches_picking_from_the_whole_list_for_every_report(self):
        st = self.build(memory_store(self))
        ids = [row[0] for row in st._conn.execute("SELECT report_id FROM naver_auto_report_snapshot ORDER BY report_id")]
        self.assertGreater(len(ids), len(st.report_snapshots()))   # 최신이 아닌 판도 섞여 있다
        for report_id in ids+[ids[-1]+1]:
            with self.subTest(report_id=report_id):
                self.assertEqual(S._report_current(st, report_id), OLD.review_current(st, report_id))

    def test_review_outcomes_match_the_original_lookup(self):
        def outcomes(old):
            st = self.build(memory_store(self))
            if old:
                st._report_current_snapshot = lambda report_id: OLD.review_current(st, report_id)
            latest = {(r["possibility_id"], r["period_key"]): r["report_id"] for r in st.report_snapshots()}
            stale = st._conn.execute("""SELECT MIN(report_id) FROM naver_auto_report_snapshot
                WHERE possibility_id=11 AND period_key=?""", (WEEKS[3].key,)).fetchone()[0]
            calls = [(latest[(11, WEEKS[2].key)], "approved"),     # 최신 · 완결 → 승인
                     (stale, "approved"),                            # 최신이 아닌 판 → 보고서가 변경되었습니다
                     (latest[(11, WEEKS[4].key)], "approved"),     # 대기 dirty → 승인 막힘
                     (latest[(11, WEEKS[4].key)], "held"),         # 보류는 남길 수 있다
                     (latest[(11, SEPT.key)], "approved")]
            out = []
            for report_id, decision in calls:
                try:
                    out.append(st.record_report_review(report_id, 100, st.now, decision, "확인"))
                except Exception as error:
                    out.append((type(error).__name__, str(error)))
            return out, digest(st)
        new, old = outcomes(False), outcomes(True)
        self.assertEqual(new, old)
        self.assertEqual(new[0][0]["review_status"], "approved")
        self.assertEqual(new[0][1], ("StoreRefused", "보고서가 변경되었습니다. 최신본을 확인해 주세요"))
        self.assertEqual(new[0][2][0], "StoreRefused")
        self.assertEqual(new[0][3]["review_status"], "held")


class InvariantTest(unittest.TestCase):
    def test_runtime_sources_never_update_delete_or_replace_report_snapshots(self):
        # 판 지도 · 판 사실 기억은 「판은 넣기만 한다」에 기댄다. 연결은 지우기를 늘 거절하고, 고치기는 이 시험이 막는다.
        pattern = re.compile(r"\b(?:UPDATE|DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO)\s+"
                             r"naver_auto_report_snapshot\b", re.IGNORECASE)
        found = []
        for package in ("naver_engine", "naver_runtime"):
            for path in (ROOT/package).rglob("*.py"):
                if "tests" in path.relative_to(ROOT/package).parts:
                    continue
                if pattern.search(path.read_text(encoding="utf-8")):
                    found.append(str(path.relative_to(ROOT)))
        self.assertEqual(found, [])

    def test_oracle_helpers_are_still_the_a981b35_helpers(self):
        # 사본은 이 도우미들을 그대로 부른다 — 도우미가 바뀌면 사본이 더는 옛 판의 정답이 아니다(지문 = a981b35 원문).
        sources = {name: hashlib.sha256(inspect.getsource(getattr(S, name)).encode()).hexdigest()
                   for name in OLD.HELPER_SHA256}
        self.assertEqual(sources, OLD.HELPER_SHA256)


if __name__ == "__main__":
    unittest.main()
