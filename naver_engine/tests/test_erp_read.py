"""① 전산 읽기 관문(erp_read.py) 시험 — 가짜 ① 로만(네트워크 0). 번호·이름은 모두 지어낸 값이다.

돌리는 법(저장소 맨 위에서):  python3 -m unittest discover -s naver_engine/tests
"""
from __future__ import annotations

import json
import logging
import traceback
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from naver_engine import erp_read as E
from naver_engine import handles as H
from naver_engine.credentials import CredentialsMissing, Secret
from naver_engine.tests.fake_naver import FakeClock

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 29, 6, 10, tzinfo=KST)
MARK_KEY = "MARKERPKEY-1a2b3c4d-5e6f7a8b9c0d1e2f"
MARK_NAME = "MARKCOMPANYNAME"
MARK_MANAGER = "MARKMANAGERNAME"


def company(pid, stage, name="가게", ends=("2026-12-31",), **extra):
    it = {"possibility_id": pid, "company_name": name, "store_url": "https://x", "sales_manager": MARK_MANAGER,
          "stage": stage, "ad_center_registered": False,
          "contracts": [{"round": 1, "product": "정규300", "start_date": "2026-01-01", "end_date": e,
                         "amount": 3000000, "type": "일반"} for e in ends]}
    it.update(extra)
    return it


class FakeErp:
    """받은 요청을 기록하고, 단계 표기마다 정해 둔 목록을 돌려준다."""

    def __init__(self, stages=None, org=None, ids=None):
        self.stages = stages or {}
        self.org = org if org is not None else {"generated_at": "x", "teams": [], "employees": [], "owners": []}
        self.ids = ids if ids is not None else {"generated_at": "x", "items": []}
        self.calls = []
        self.override = {}   # (경로, 표기) → (상태, 본문 bytes)
        self.raise_on = None

    def send(self, req, timeout):
        u = urllib.parse.urlsplit(req.full_url)
        q = urllib.parse.parse_qs(u.query)
        self.calls.append({"method": req.get_method(), "scheme": u.scheme, "host": u.hostname, "path": u.path,
                           "query": q, "key_ok": req.get_header("X-api-key") == MARK_KEY,
                           "headers": sorted(k.lower() for k, _v in req.header_items()),
                           "has_body": req.data is not None})
        stage = q.get("stage", [None])[0]
        if self.raise_on == (u.path, stage):
            raise urllib.error.URLError("connection refused " + MARK_KEY)
        if (u.path, stage) in self.override:
            return self.override[(u.path, stage)]
        if u.path == E.PATH_CONTRACTS:
            items = self.stages.get(stage, [])
            return 200, json.dumps({"status": 200, "result": {"total": len(items), "items": items}}).encode()
        if u.path == E.PATH_ORG_SNAPSHOT:
            return 200, json.dumps({"status": 200, "result": self.org}).encode()
        if u.path == E.PATH_NAVER_IDS:
            return 200, json.dumps({"status": 200, "result": self.ids}).encode()
        return 404, b"{}"


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


class Base(unittest.TestCase):
    def setUp(self):
        self._new()
        self.logs = _Collect()
        logging.getLogger("naver_engine").addHandler(self.logs)
        logging.getLogger("naver_engine").setLevel(logging.DEBUG)

    def _new(self):
        self.fake = FakeErp()
        self.reader = E.ErpReader(Secret(MARK_KEY), self.fake, FakeClock(NOW))

    def tearDown(self):
        logging.getLogger("naver_engine").removeHandler(self.logs)
        for line in self.logs.lines:
            self.assertNotIn(MARK_KEY, line)
            self.assertNotIn(MARK_NAME, line)


class GateTest(Base):
    def test_only_get_and_allowed_paths(self):
        with self.assertRaises(E.ErpWriteForbidden):
            self.reader._gate("POST", E.PATH_CONTRACTS, None)
        with self.assertRaises(E.ErpWriteForbidden):
            self.reader._gate("GET", "/api/ad-sync/contracts/../admin", None)
        with self.assertRaises(E.ErpWriteForbidden):
            self.reader._gate("GET", "/api/employee-management/my-profile", None)
        self.assertEqual(self.fake.calls, [], "거절은 요청을 만들기 전에")
        self.assertEqual(E._ALLOWED_METHODS, frozenset({"GET"}))

    def test_built_request_rechecked_before_send(self):
        real = urllib.request.Request
        for kind in ("method", "body"):
            class Bad(real):
                def get_method(self, _k=kind):
                    return "POST" if _k == "method" else super().get_method()

                @property
                def data(self, _k=kind):
                    return b"x" if _k == "body" else None

                @data.setter
                def data(self, v):
                    pass
            urllib.request.Request = Bad
            try:
                with self.assertRaises(E.ErpWriteForbidden):
                    self.reader.read_org_snapshot()
            finally:
                urllib.request.Request = real
        self.assertEqual(self.fake.calls, [])

    def test_params_allowed_only_for_contracts(self):
        bad = [
            (E.PATH_CONTRACTS, {"stage": "소각", "has_contract": "true"}),
            (E.PATH_CONTRACTS, {"stage": "진행중", "has_contract": "false"}),
            (E.PATH_CONTRACTS, {"stage": "진행중"}),
            (E.PATH_CONTRACTS, {"stage": "진행중", "has_contract": "true", "size": "5"}),
            (E.PATH_ORG_SNAPSHOT, {"stage": "진행중", "has_contract": "true"}),
        ]
        for path, params in bad:
            with self.subTest(params=params):
                with self.assertRaises(E.ErpWriteForbidden):
                    self.reader._gate("GET", path, params)
        self.assertEqual(self.fake.calls, [])

    def test_host_scheme_and_key_header(self):
        self.reader.read_org_snapshot()
        c = self.fake.calls[0]
        self.assertEqual((c["method"], c["scheme"], c["host"], c["path"]), ("GET", "http", E.ERP_HOST, E.PATH_ORG_SNAPSHOT))
        self.assertTrue(c["key_ok"])
        self.assertFalse(c["has_body"])
        self.assertEqual(c["headers"], ["accept", "x-api-key"])

    def test_host_is_pinned(self):
        old = E.BASE_URL
        try:
            E.BASE_URL = "http://evil.example"
            with self.assertRaises(E.ErpWriteForbidden):
                self.reader.read_org_snapshot()
            E.BASE_URL = "https://" + E.ERP_HOST
            with self.assertRaises(E.ErpWriteForbidden):
                self.reader.read_org_snapshot()
        finally:
            E.BASE_URL = old
        self.assertEqual(self.fake.calls, [])

    def test_call_cap(self):
        r = E.ErpReader(Secret(MARK_KEY), self.fake, FakeClock(NOW), max_calls=2)
        r.read_org_snapshot()
        r.read_org_snapshot()
        with self.assertRaises(E.ErpIncomplete):
            r.read_org_snapshot()

    def test_network_error_masked(self):
        self.fake.raise_on = (E.PATH_ORG_SNAPSHOT, None)
        with self.assertRaises(E.ErpError) as cm:
            self.reader.read_org_snapshot()
        e = cm.exception
        self.assertEqual(e.kind, "network")
        self.assertIsNone(e.__cause__)
        self.assertTrue(e.__suppress_context__)
        self.assertNotIn(MARK_KEY, "".join(traceback.format_exception(e)))

    def test_bad_responses(self):
        cases = [
            (500, b'{"status":500}', "status"),
            (302, b"", "status"),
            (204, b"", "status"),
            (200, b"not json", "not-json"),
            (200, b"\xff\xfe", "not-json"),
            (200, b'{"status":401,"result":{}}', "bad-shape"),
            (200, b'{"status":200,"result":[]}', "bad-shape"),
            (200, b"[]", "bad-shape"),
            (200, b"x" * (E.MAX_BODY + 1), "too-large"),
        ]
        for status, body, kind in cases:
            with self.subTest(kind=kind, status=status):
                self.fake.override[(E.PATH_ORG_SNAPSHOT, None)] = (status, body)
                with self.assertRaises(E.ErpError) as cm:
                    self.reader.read_org_snapshot()
                self.assertEqual(cm.exception.kind, kind)

    def test_repr_hides_key(self):
        self.assertNotIn(MARK_KEY, repr(self.reader))
        with self.assertRaises(CredentialsMissing):
            E.ErpReader(MARK_KEY, self.fake)   # 날 글자 키는 받지 않는다


class StageTest(Base):
    def test_spellings_cover_monitored_stages(self):
        self.assertEqual(set(E.STAGE_SPELLINGS), set(H.MONITORED_STAGES))
        for key, sp in E.STAGE_SPELLINGS.items():
            self.assertEqual(len(sp), len(set(sp)))
            for s in sp:
                self.assertEqual(E._WS.sub("", s), key)
        # ① 코드에 실제로 있는 두 표기(2026-09-28)가 모두 들어 있다
        for s in ("사후관리", "사후 관리", "전략관리", "전략 관리", "계약만료", "계약 만료", "재계약진행중", "재계약 진행중",
                  "진행 중", "환불 중"):
            self.assertIn(s, E._ALL_SPELLINGS)

    def test_reads_every_spelling_in_order_and_merges(self):
        self.fake.stages = {
            "진행중": [company(101, "진행중", MARK_NAME, ("2026-10-01", "2027-03-31"))],
            "사후 관리": [company(102, "사후 관리")],
            "사후관리": [company(103, "사후관리", ends=())],
            "계약 만료": [company(104, "계약 만료", ends=("2026-09-20",))],
        }
        snap = self.reader.read_stages()
        asked = [c["query"]["stage"][0] for c in self.fake.calls]
        self.assertEqual(asked, [s for v in E.STAGE_SPELLINGS.values() for s in v], "표기 전부를 정해진 순서로 하나씩")
        self.assertTrue(all(c["query"]["has_contract"] == ["true"] for c in self.fake.calls))
        self.assertEqual(sorted(snap.rows), [101, 102, 103, 104])
        self.assertEqual(snap.rows[101].stage_key, "진행중")
        self.assertEqual(snap.rows[101].latest_end_date, date(2027, 3, 31))
        self.assertEqual(snap.rows[102].stage_key, "사후관리")
        self.assertEqual(snap.rows[103].stage_key, "사후관리")
        self.assertIsNone(snap.rows[103].latest_end_date)
        self.assertEqual(snap.rows[104].stage_key, "계약만료")
        self.assertEqual(snap.as_of, NOW)
        self.assertEqual(snap.per_spelling["사후 관리"], 1)
        self.assertNotIn(MARK_NAME, repr(snap))
        self.assertNotIn(MARK_NAME, repr(snap.rows[101]))
        self.assertEqual(E.handle_inputs(snap.rows[104]), ("계약만료", date(2026, 9, 20)))

    def test_only_needed_fields_kept(self):
        self.fake.stages = {"진행중": [company(101, "진행중", secret_new_field=MARK_MANAGER)]}
        snap = self.reader.read_stages()
        self.assertNotIn(MARK_MANAGER, repr(vars(snap.rows[101])))
        self.assertEqual(set(E.StageRow.__dataclass_fields__),
                         {"possibility_id", "stage_key", "name", "latest_end_date", "end_unreadable"})

    def test_any_failure_drops_everything(self):
        for path_stage, reply in [(("/api/ad-sync/contracts", "홀딩 중"), (500, b"{}")),
                                  (("/api/ad-sync/contracts", "계약만료"), (200, b"oops"))]:
            with self.subTest(at=path_stage):
                self._new()
                self.fake.stages = {"진행중": [company(101, "진행중")]}
                self.fake.override[path_stage] = reply
                with self.assertRaises(E.ErpIncomplete):
                    self.reader.read_stages()
        self._new()
        self.fake.raise_on = ("/api/ad-sync/contracts", "환불중")
        with self.assertRaises(E.ErpIncomplete) as cm:
            self.reader.read_stages()
        self.assertIsNone(cm.exception.__cause__)

    def test_shape_checks(self):
        bad = [
            {"total": 2, "items": [company(1, "진행중")]},                    # 합계가 다름
            {"total": True, "items": []},
            {"items": []},
            {"total": 1, "items": [company(0, "진행중")]},                     # 가망 번호
            {"total": 1, "items": [company(True, "진행중")]},
            {"total": 1, "items": [company(5, "홀딩중")]},                     # 단계가 요청과 다름
            {"total": 1, "items": [company(5, None)]},
            {"total": 1, "items": [company(5, "진행중", contracts="x")]},
            {"total": 1, "items": [company(5, "진행중", contracts=["x"])]},
            {"total": 2, "items": [company(5, "진행중"), company(5, "진행중")]},  # 한 목록 안 겹침
            {"total": 1, "items": ["x"]},
        ]
        for res in bad:
            with self.subTest(res=str(res)[:60]):
                self._new()
                self.fake.override[(E.PATH_CONTRACTS, "진행중")] = (
                    200, json.dumps({"status": 200, "result": res}).encode())
                with self.assertRaises(E.ErpIncomplete):
                    self.reader.read_stages()

    def test_stage_conflict_is_held_out(self):
        self.fake.stages = {"진행중": [company(101, "진행중"), company(102, "진행중")],
                            "환불중": [company(101, "환불중")],
                            "계약 만료": [company(101, "계약 만료")]}
        snap = self.reader.read_stages()
        self.assertEqual(sorted(snap.rows), [102])
        self.assertEqual(snap.stage_conflicts, (101,))

    def test_end_dates(self):
        self.fake.stages = {"진행중": [company(1, "진행중", ends=("2026-13-01",)),
                                      company(2, "진행중", ends=("2026/12/01", "2026-12-31")),
                                      company(3, "진행중", ends=(None, "", "2026-12-31")),
                                      company(4, "진행중", ends=(20261231,))]}
        snap = self.reader.read_stages()
        self.assertTrue(snap.rows[1].end_unreadable)
        self.assertTrue(snap.rows[2].end_unreadable)
        self.assertEqual(snap.rows[2].latest_end_date, date(2026, 12, 31))
        self.assertFalse(snap.rows[3].end_unreadable)
        self.assertEqual(snap.rows[3].latest_end_date, date(2026, 12, 31))
        self.assertTrue(snap.rows[4].end_unreadable)
        for pid in (1, 2, 4):
            self.assertIsNone(E.handle_inputs(snap.rows[pid]), "종료일을 못 읽으면 손잡이를 발급하지 않는다")
        self.assertEqual(E.handle_inputs(snap.rows[3]), ("진행중", date(2026, 12, 31)))

    def test_same_stage_other_spelling_merges(self):
        """① 이 빈칸 무시 매칭으로 바꿔 두 표기가 같은 가망을 주면 한 줄로 합친다 — 「중복」으로 영영 멈추지 않게(S7 검토)."""
        self.fake.stages = {"진행중": [company(101, "진행중", ends=("2027-01-31",)), company(102, "진행중")],
                            "진행 중": [company(101, "진행 중", MARK_NAME, ends=("2026-10-01",)),
                                      company(103, "진행 중", ends=())],
                            "홀딩중": [company(104, "홀딩중", ends=("2026-13-40",))],
                            "홀딩 중": [company(104, "홀딩 중", ends=("2026-12-01",))]}   # 먼저 부른 표기가 더 늦은 날 · 못 읽음
        snap = self.reader.read_stages()
        self.assertEqual(sorted(snap.rows), [101, 102, 103, 104])
        self.assertEqual(snap.stage_conflicts, ())
        self.assertEqual(snap.rows[101].latest_end_date, date(2027, 1, 31))     # 늦은 쪽
        self.assertTrue(snap.rows[104].end_unreadable)                          # 못 읽음은 하나라도
        self.assertEqual(snap.rows[101].name, "가게")                            # 이름은 먼저 것
        self.assertEqual((snap.per_spelling["진행중"], snap.per_spelling["진행 중"]), (2, 2))

    def test_duplicate_within_one_spelling_still_refused(self):
        self.fake.override[(E.PATH_CONTRACTS, "진행 중")] = (200, json.dumps({"status": 200, "result": {
            "total": 2, "items": [company(7, "진행 중"), company(7, "진행 중")]}}).encode())
        with self.assertRaises(E.ErpIncomplete) as cm:
            self.reader.read_stages()
        self.assertEqual(cm.exception.kind, "duplicate")

    def test_deadline_stops_before_next_call(self):
        clock = self.reader._clock
        real_send = self.fake.send

        def slow(req, timeout):   # 부를 때마다 1분씩 흐른다
            clock._now += timedelta(minutes=1)
            return real_send(req, timeout)
        self.fake.send = slow
        with self.assertRaises(E.ErpIncomplete) as cm:
            self.reader.read_stages(deadline=NOW + timedelta(minutes=5))
        self.assertEqual((cm.exception.kind, len(self.fake.calls)), ("deadline", 5))
        self._new()
        with self.assertRaises(E.ErpIncomplete):   # 마감이 이미 지났으면 한 번도 부르지 않는다
            self.reader.read_stages(deadline=NOW)
        self.assertEqual(self.fake.calls, [])
        self._new()
        self.assertEqual(len(self.reader.read_stages(deadline=NOW + timedelta(seconds=1)).per_spelling),
                         sum(len(v) for v in E.STAGE_SPELLINGS.values()))

    def test_deep_json_is_not_json_result(self):
        self.fake.override[(E.PATH_CONTRACTS, "진행중")] = (200, b"[" * 200_000 + b"]" * 200_000)
        with self.assertRaises(E.ErpIncomplete) as cm:
            self.reader.read_stages()
        self.assertEqual(cm.exception.kind, "not-json")

    def test_unstorable_company_name_dropped_row_kept(self):
        raw = ('{"status": 200, "result": {"total": 3, "items": ['
               + json.dumps(company(1, "진행중", "x" * 201)) + ", "
               + json.dumps(company(2, "진행중", "a\x00b")) + ", "
               + json.dumps(company(3, "진행중", "가게"), ensure_ascii=False).replace('"가게"', '"\\ud83d가게"') + "]}}")
        self.fake.override[(E.PATH_CONTRACTS, "진행중")] = (200, raw.encode())
        snap = self.reader.read_stages()
        self.assertEqual(sorted(snap.rows), [1, 2, 3])
        self.assertEqual([snap.rows[i].name for i in (1, 2, 3)], [None, None, None])

    def test_plausible(self):
        snap = E.StageSnapshot({i: E.StageRow(i, "진행중") for i in range(1, 941)}, NOW, {}, ())
        self.assertTrue(snap.plausible())
        self.assertFalse(E.StageSnapshot({i: E.StageRow(i, "진행중") for i in range(1, 700)}, NOW, {}, ()).plausible())
        self.assertFalse(E.StageSnapshot({i: E.StageRow(i, "진행중") for i in range(1, 1200)}, NOW, {}, ()).plausible())


class OtherReadsTest(Base):
    def test_org_snapshot_passthrough(self):
        self.fake.org = {"generated_at": "t", "teams": [{"idx": 0}], "employees": [], "owners": []}
        self.assertEqual(self.reader.read_org_snapshot()["teams"], [{"idx": 0}])

    def test_naver_ad_account_only_and_legacy_rows(self):
        self.fake.ids = {"items": [
            {"possibility_id": 21, "vendor": None, "ad_account_no": "8123456", "api_key": MARK_KEY},
            {"possibility_id": 22, "vendor": "NAVER_SEARCHAD", "customer_id": "1234567"},
            {"possibility_id": 23, "vendor": "NAVER_SEARCHAD", "customer_id": "1234568", "ad_account_no": None},
        ]}
        rows = self.reader.read_naver_customer_ids()
        self.assertEqual([(r.customer_id_raw, r.ad_account_no_raw) for r in rows],
                         [(None, "8123456"), ("1234567", None), ("1234568", None)])
        self.assertEqual(rows[1], E.NaverIdRow(22, "NAVER_SEARCHAD", "1234567"))
        for hidden in ("8123456", "1234567", "1234568", MARK_KEY):
            self.assertNotIn(hidden, repr(rows))

    def test_naver_ids(self):
        self.fake.ids = {"generated_at": "t", "items": [
            {"possibility_id": 11, "vendor": "NAVER_SEARCHAD", "customer_id": " 123-4567 "},
            {"possibility_id": 12, "vendor": None, "customer_id": None},
            {"possibility_id": 13, "vendor": "NAVER_SEARCHAD", "api_key": MARK_KEY},
        ]}
        rows = self.reader.read_naver_customer_ids()
        self.assertEqual([(r.possibility_id, r.vendor, r.customer_id_raw) for r in rows],
                         [(11, "NAVER_SEARCHAD", " 123-4567 "), (12, None, None), (13, "NAVER_SEARCHAD", None)])
        self.assertNotIn("123-4567", repr(rows))
        self.assertEqual(set(E.NaverIdRow.__dataclass_fields__),
                         {"possibility_id", "vendor", "customer_id_raw", "ad_account_no_raw"})
        for bad in ({"items": "x"}, {"items": ["x"]}, {"items": [{"possibility_id": -1}]},
                    {"items": [{"possibility_id": 13, "customer_id": 1234567}]}, {}):
            with self.subTest(bad=bad):
                self.fake.ids = bad
                with self.assertRaises(E.ErpIncomplete):
                    self.reader.read_naver_customer_ids()

    def test_non_string_ad_account_number_drops_whole_list(self):
        for malformed in (8123456, True, 8.5, [], {"api_key": MARK_KEY}):
            with self.subTest(type=type(malformed).__name__):
                self.fake.ids = {"items": [
                    {"possibility_id": 21, "ad_account_no": "8123456"},
                    {"possibility_id": 22, "ad_account_no": malformed},
                ]}
                with self.assertRaises(E.ErpIncomplete) as cm:
                    self.reader.read_naver_customer_ids()
                self.assertEqual(cm.exception.kind, "bad-shape")
                self.assertNotIn(MARK_KEY, str(cm.exception))

    def test_non_string_customer_id_cannot_hide_conflict_with_valid_ad_account_number(self):
        for malformed in (1234567, True, 1.5, [], {"api_key": MARK_KEY}):
            with self.subTest(type=type(malformed).__name__):
                self.fake.ids = {"items": [
                    {"possibility_id": 21, "ad_account_no": "8123456", "customer_id": malformed},
                ]}
                with self.assertRaises(E.ErpIncomplete) as cm:
                    self.reader.read_naver_customer_ids()
                self.assertEqual(cm.exception.kind, "bad-shape")
                self.assertNotIn(MARK_KEY, str(cm.exception))


class KeyTest(unittest.TestCase):
    def test_load(self):
        self.assertEqual(E.load_erp_key({E.ENV_ERP_API_KEY: " " + MARK_KEY + " "}).reveal(), MARK_KEY)
        for env in ({}, {E.ENV_ERP_API_KEY: "  "}, {E.ENV_ERP_API_KEY: "short"}, {E.ENV_ERP_API_KEY: "has space key 12"},
                    {E.ENV_ERP_API_KEY: "한글키한글키한글키"}, {E.ENV_ERP_API_KEY: "k" * 31},
                    {E.ENV_ERP_API_KEY: "k" * 257}, {E.ENV_ERP_API_KEY: "has space " + "k" * 40},
                    # 옛 계약 동기화 키 이름만 있으면 읽지 않는다(엔진 전용 키로만 돈다).
                    {"ERP_SYNC_API_KEY": MARK_KEY}, {"AD_SYNC_API_KEY": MARK_KEY}):
            with self.subTest(env=list(env)):
                with self.assertRaises(CredentialsMissing) as cm:
                    E.load_erp_key(env)
                self.assertIn(E.ENV_ERP_API_KEY, str(cm.exception))
                for v in env.values():
                    if v.strip():
                        self.assertNotIn(v.strip(), str(cm.exception))

    def test_key_bounds_match_erp(self):
        self.assertEqual(E.ENV_ERP_API_KEY, "NAVER_ENGINE_ERP_KEY")
        self.assertEqual((E.KEY_MIN_LENGTH, E.KEY_MAX_LENGTH), (32, 256))
        for n in (32, 256):
            self.assertEqual(E.load_erp_key({E.ENV_ERP_API_KEY: "k" * n}).reveal(), "k" * n)


if __name__ == "__main__":
    unittest.main()
