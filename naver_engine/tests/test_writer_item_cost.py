"""NV-S00 2차 — 쓰기 줄 항목 CPU(짝 맞추기 기억 · 지난 작업 계정별 묶음). 네트워크·운영 DB를 쓰지 않는다.

직원 로그인은 감사 한 줄을 반드시 남긴다(쓰기 줄 15초 대기). 보고서 회차를 조각으로 나눈 뒤에도 수집 후보(performance_work)가
화면 부하에서 한 항목으로 19~37초 쓰기 줄을 쥐었다 — CPU 의 6할이 관리 판정마다 다시 하는 짝 맞추기, 나머지 대부분이
계정마다 지난 작업 전체를 훑는 고리였다. 이 시험은 두 가지를 고정한다.
  ① 같은 입력이면 지난 짝 맞추기를 다시 쓰고, 입력이 하나라도 다르면(값 · 형 · 차례 · 계산 함수) 다시 계산한다.
  ② 결과는 a981b35 판(tests/_performance_a981b35.py — 글자 그대로 옮긴 사본)과 판정 · 후보 · 표까지 같다.
"""
from dataclasses import astuple, is_dataclass
from datetime import timedelta
from pathlib import Path
import runpy
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.naver_auto import matching as M
from naver_engine import erp_read as E, inventory as I, management as MP, management_store as MS
from naver_engine.tests import _performance_a981b35 as OLD
from naver_engine.tests import test_account_catalog as TC, test_morning as TM


make_fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
    "tools/naver-store-selection-benchmark.py"))["make_fixture"]


def _plain(value):
    """비교용 평문 — 데이터 클래스는 모든 칸(비교 제외 칸 포함)을 · 사전은 열쇠 차례까지."""
    if is_dataclass(value) and not isinstance(value, type):
        return (type(value).__name__, _plain(astuple(value)))
    if isinstance(value, dict):
        return ("dict", [(_plain(k), _plain(v)) for k, v in value.items()])
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, [_plain(v) for v in value])
    return (type(value).__name__, value)


def _tables(store):
    names = [r[0] for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: list(store._conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')) for name in names}


class _Plain:
    """칸을 더할 수 없는 저장소(기억 없이도 같은 답이어야 한다)."""
    __slots__ = ()


class MatchMemoTest(unittest.TestCase):
    """관리 판정의 짝 맞추기 기억 — 열쇠 범위 · 무효화 · 형 구별 · 오류 · 계산 함수 교체."""

    def inputs(self):
        accounts = {101: {"customer_id": 101, "ad_account_no": 9001, "account_name": "가나다 상점", "present": 1},
                    102: {"customer_id": 102, "ad_account_no": 9002, "account_name": "라마바 마켓", "present": 1},
                    103: {"customer_id": 103, "ad_account_no": 9003, "account_name": "사아자 몰", "present": 0}}
        catalog = {"generated_at": "2026-10-06T09:00:00+09:00",
                   "items": [{"possibility_id": 11, "company_name": "가나다 상점"},
                             {"possibility_id": 12, "company_name": "라마바"},
                             {"possibility_id": 13, "company_name": "사아자 몰"}],
                   "ids": [{"possibility_id": 11, "vendor": M.VENDOR_NAVER, "customer_id_raw": "101",
                            "ad_account_no_raw": None}]}
        decisions = [SimpleNamespace(possibility_id=12, customer_id=102, decision=M.DECISION_CONFIRMED)]
        return accounts, decisions, catalog, {}

    def direct(self, accounts, decisions, catalog, evidence):
        return I._matching(SimpleNamespace(accounts=accounts, live_decisions=decisions), catalog,
                           auto_evidence=evidence)[0]

    def test_same_values_reuse_one_computation(self):
        store = SimpleNamespace()
        with patch.object(I, "_matching", wraps=I._matching) as spy:
            first = MS._matched(store, *self.inputs())
            # 값이 같은 새 객체(다음 회차가 다시 읽은 것)여도 다시 쓴다.
            second = MS._matched(store, *self.inputs())
        self.assertIs(first, second)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(_plain(first), _plain(self.direct(*self.inputs())))

    def test_every_input_change_recomputes_and_matches_direct(self):
        def rename_account(a, d, c, e):
            a[102]["account_name"] = "라마바"
        def flip_present(a, d, c, e):
            a[102]["present"] = 0
        def ad_number(a, d, c, e):
            a[101]["ad_account_no"] = 9101
        def decide_reject(a, d, c, e):
            d[0] = SimpleNamespace(possibility_id=12, customer_id=102, decision=M.DECISION_REJECTED)
        def decide_more(a, d, c, e):
            d.append(SimpleNamespace(possibility_id=13, customer_id=101, decision=M.DECISION_CONFIRMED))
        def decision_order(a, d, c, e):
            d.insert(0, SimpleNamespace(possibility_id=13, customer_id=101, decision=M.DECISION_CONFIRMED))
        def catalog_name(a, d, c, e):
            c["items"][1]["company_name"] = "라마바 마켓"
        def catalog_id(a, d, c, e):
            c["ids"][0]["customer_id_raw"] = "102"
        def catalog_vendor(a, d, c, e):
            c["ids"][0]["vendor"] = "other"
        def catalog_ad_raw(a, d, c, e):
            c["ids"][0]["ad_account_no_raw"] = "9001"
        def catalog_more(a, d, c, e):
            c["items"].append({"possibility_id": 14, "company_name": "가나다"})
        def evidence(a, d, c, e):
            e[(11, 101)] = "a" * 64
        changes = [rename_account, flip_present, ad_number, decide_reject, decide_more, decision_order, catalog_name,
                   catalog_id, catalog_vendor, catalog_ad_raw, catalog_more, evidence]
        for change in changes:
            with self.subTest(change=change.__name__):
                store = SimpleNamespace()
                with patch.object(I, "_matching", wraps=I._matching) as spy:
                    MS._matched(store, *self.inputs())
                    values = self.inputs()
                    change(*values)
                    got = MS._matched(store, *values)
                    self.assertEqual(spy.call_count, 2)
                self.assertEqual(_plain(got), _plain(self.direct(*values)))

    def test_fields_the_matcher_never_reads_do_not_invalidate(self):
        # 짝 맞추기는 현재 계정의 번호·이름 · 판단 세 칸 · 번호 행 네 칸 · 업체 두 칸만 본다(목록 시각·단계는 관리 판정이 따로 본다).
        store = SimpleNamespace()
        with patch.object(I, "_matching", wraps=I._matching) as spy:
            MS._matched(store, *self.inputs())
            a, d, c, e = self.inputs()
            a[103]["account_name"] = "바뀐 이름"     # 현재가 아닌 계정
            c["generated_at"] = "2026-10-06T10:00:00+09:00"
            c["items"][0]["stage"] = "진행중"
            got = MS._matched(store, a, d, c, e)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(_plain(got), _plain(self.direct(a, d, c, e)))

    def test_equal_but_different_type_is_not_reused(self):
        # 11 과 11.0 은 같다고 비교되지만 짝 규칙은 정수만 받는다 — 기억이 둘을 섞으면 오류가 정상 답으로 둔갑한다.
        store = SimpleNamespace()
        MS._matched(store, *self.inputs())
        a, d, c, e = self.inputs()
        c["items"][0]["possibility_id"] = 11.0
        with self.assertRaises(M.BadInput):
            self.direct(a, d, c, e)
        with self.assertRaises(M.BadInput):
            MS._matched(store, a, d, c, e)

    def test_failures_are_not_remembered(self):
        store = SimpleNamespace()
        a, d, c, e = self.inputs()
        d[0] = SimpleNamespace(possibility_id=12, customer_id=0, decision=M.DECISION_CONFIRMED)
        with patch.object(I, "_matching", wraps=I._matching) as spy:
            for _ in range(2):
                with self.assertRaises(M.BadInput):
                    MS._matched(store, a, d, c, e)
        self.assertEqual(spy.call_count, 2)
        self.assertFalse(hasattr(store, "_management_match_memo"))

    def test_unkeyable_inputs_fail_like_the_original(self):
        store = SimpleNamespace()
        a, d, c, e = self.inputs()
        del a[101]["account_name"]
        with self.assertRaises(KeyError):
            self.direct(a, d, c, e)
        with self.assertRaises(KeyError):
            MS._matched(store, a, d, c, e)
        self.assertFalse(hasattr(store, "_management_match_memo"))

    def test_swapped_matcher_is_not_bypassed(self):
        store = SimpleNamespace()
        MS._matched(store, *self.inputs())
        sentinel = (SimpleNamespace(pairs=()), set())
        with patch.object(I, "_matching", return_value=sentinel) as fake:
            self.assertIs(MS._matched(store, *self.inputs()), sentinel[0])
        self.assertEqual(fake.call_count, 1)
        with patch.object(M, "loose_name", wraps=M.loose_name) as spy:
            MS._matched(store, *self.inputs())
        self.assertGreater(spy.call_count, 0)

    def test_store_without_room_still_answers(self):
        got = MS._matched(_Plain(), *self.inputs())
        self.assertEqual(_plain(got), _plain(self.direct(*self.inputs())))


class WriterItemsAgainstA981b35Test(unittest.TestCase):
    """실제 Store(메모리 SQL): 판정 · 수집/구조 후보 · 보고서 · 표가 a981b35 사본과 같고, 같은 입력의 회차는 짝 맞추기를 다시 하지 않는다."""

    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)

    def fixture(self, accounts, managed, history):
        fixture = make_fixture(accounts, managed, history_days=history)
        self.addCleanup(fixture.store.close)
        store, now = fixture.store, fixture.clock.now()
        if history:
            # 재시도 대기 중인 지난 보충 기간을 계정 차례와 다르게(역순 · 섞어) 넣는다 — 이어 읽기 고리와 차례가 함께 걸린다.
            states, fingerprint = store.management_states(), store.decision_fingerprint()
            rows = []
            # 기간은 어제 회차의 재대조 기간(엔진이 이어 읽기를 허락하는 모양) 그대로.
            kind, cycle, start, end = MP.revalidation_periods(now.date() - timedelta(days=1), managed=True,
                                                             prior_managed=False)[0]
            for n in reversed(range(0, managed, 2)):
                cid = TM.A + n
                at = (now - timedelta(hours=3 + n % 5)).isoformat()
                rows.append((f"{cid}:{kind}:{cycle}:{start}:{end}", cid, kind, str(cycle), str(start), str(end),
                             at, at, states[cid]["stage_revision"], 11 + n, fingerprint, "retry", at, at, 1,
                             MP.generation_for(cycle)))
            store._conn.executemany("""INSERT INTO naver_auto_performance_job
                (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
                 stage_revision,possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts,generation)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        return fixture

    def rounds(self, store, now, old):
        perf = (lambda: OLD.performance_work(store, now, 24)) if old else (lambda: store.performance_work(now, 24))
        out = [("perf", perf()), ("struct", store.structure_work(now, 24)),
               ("sync", store.synchronize_management(now)), ("perf2", perf()),
               ("snapshot", MS.snapshot(store, now))]
        return [(name, _plain(value)) for name, value in out]

    def change_inputs(self, store, now, managed):
        # 사람 판단 · 전체 업체 목록(이름 · 번호 행) · 계정 이름 · 자동 근거 — 짝 맞추기 입력을 하나씩 바꾼다.
        store.record_decision(11, TM.A, "rejected", 0, now)
        names = {r["customer_id"]: r["account_name"] for r in store.accounts()}
        catalog = store.account_catalog()
        items = [TC.company(r["possibility_id"], "진행중", company_name=r["company_name"]) for r in catalog["items"]]
        items[1]["company_name"] = (items[1]["company_name"] or "") + "점"
        ids = [E.NaverIdRow(r["possibility_id"], r["vendor"], r["customer_id_raw"]) for r in catalog["ids"]]
        ids[2] = E.NaverIdRow(ids[2].possibility_id, ids[2].vendor, None)
        store.record_account_catalog({"generated_at": now.isoformat(), "total": len(items), "complete": True,
                                      "items": items}, ids, now)
        with store._tx() as c:
            # 계정 동기화는 더 늦은 수신만 받는다(시험 시계는 멈춰 있다) — 같은 원장 칸을 직접 바꾼다.
            c.execute("UPDATE naver_auto_account SET account_name=? WHERE customer_id=?",
                      (names[TM.A + 3] + "X", TM.A + 3))
            c.execute("""INSERT INTO naver_auto_link_memory(possibility_id,customer_id,link,first_matched_at,
                last_matched_at,auto_identity_fingerprint) VALUES(?,?,'auto',?,?,?)""",
                (11 + 4, TM.A + 4, now.isoformat(), now.isoformat(), "b" * 64))

    def test_same_answers_tables_and_one_pairing_per_input(self):
        for accounts, managed, history in ((12, 6, 0), (40, 20, 3)):
            with self.subTest(accounts=accounts, history=history):
                new, old = self.fixture(accounts, managed, history), self.fixture(accounts, managed, history)
                now = new.clock.now()
                with patch.object(I, "_matching", wraps=I._matching) as spy:
                    got = self.rounds(new.store, now, old=False)
                    # 입력이 그대로인 회차가 이어지면 짝 맞추기를 다시 하지 않는다(쓰기 줄 항목의 대부분이 여기였다).
                    first = spy.call_count
                    again = self.rounds(new.store, now, old=False)
                    self.assertEqual(spy.call_count, first)
                    self.assertLessEqual(first, 2)   # 처음 한 번 + 동기화가 근거를 새로 쓴 경우 한 번
                with patch.object(MS, "snapshot", OLD.snapshot):
                    want = self.rounds(old.store, now, old=True)
                    want_again = self.rounds(old.store, now, old=True)
                self.assertEqual(got, want)
                self.assertEqual(again, want_again)
                perf = next(value for name, value in got if name == "perf")[1]
                self.assertTrue(perf)
                if history:
                    # 재시도 대기 보충 기간을 실제로 이어 읽는다(계정별 묶음 고리가 결과에 닿는다).
                    self.assertGreater(len({dict(job[1])[("str", "kind")][1] for job in perf}), 1)
                self.assertEqual(_tables(new.store), _tables(old.store))

                self.change_inputs(new.store, now, managed)
                with patch.object(MS, "snapshot", OLD.snapshot):
                    self.change_inputs(old.store, now, managed)
                with patch.object(I, "_matching", wraps=I._matching) as spy:
                    got = self.rounds(new.store, now, old=False)
                    self.assertGreaterEqual(spy.call_count, 1)   # 입력이 바뀌었으니 다시 계산했다
                    reports = new.store.generate_reports(now)
                with patch.object(MS, "snapshot", OLD.snapshot):
                    want = self.rounds(old.store, now, old=True)
                    self.assertEqual(reports, old.store.generate_reports(now))
                self.assertEqual(got, want)
                self.assertEqual(_tables(new.store), _tables(old.store))


if __name__ == "__main__":
    unittest.main()
