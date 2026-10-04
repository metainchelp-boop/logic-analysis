"""자동 연결 출처/숫자 근거의 순수 규칙 및 추가형 저장소 호환 회귀."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from app.naver_auto import matching as M
from naver_engine import store as S


class AutomaticIdentityRuleTest(unittest.TestCase):
    def setUp(self):
        self.people = [M.ErpProspect(11, "처음상호")]
        self.ids = [M.ErpCredential(11, M.VENDOR_NAVER, "12345")]
        self.accounts = {12345: {"customerId": 12345, "adAccountNo": 8000000, "adAccountName": "처음상호"}}
        result = M.match(self.people, self.ids, self.accounts, accounts_complete=True)
        self.evidence = {(11, 12345): result.pairs[0].auto_identity_fingerprint}
        self.renamed = [M.ErpProspect(11, "바뀐전산상호")]

    def match(self, *, people=None, ids=None, accounts=None, decisions=()):
        return M.match(self.renamed if people is None else people, self.ids if ids is None else ids,
                       self.accounts if accounts is None else accounts, decisions, accounts_complete=True,
                       auto_evidence=self.evidence)

    def test_opt_in_only_and_both_names_can_change_without_forging_relation(self):
        self.assertFalse(M.match(self.renamed, self.ids, self.accounts, accounts_complete=True).pairs)
        renamed_account = {12345: {**self.accounts[12345], "adAccountName": "바뀐네이버이름"}}
        pair = self.match(accounts=renamed_account).pairs[0]
        self.assertEqual((pair.link, pair.name_relation), ("auto", "different"))
        self.assertEqual(pair.auto_identity_fingerprint, self.evidence[(11, 12345)])
        normalized = self.match(ids=[M.ErpCredential(11, M.VENDOR_NAVER, " 12-345 ")]).pairs[0]
        self.assertEqual(normalized.auto_identity_fingerprint, pair.auto_identity_fingerprint)

    def test_current_numeric_and_human_guards_cannot_be_bypassed(self):
        other = M.ErpProspect(12, "별도업체")
        cases = {
            "identifier_removed": {"ids": []},
            "identifier_changed": {"ids": [M.ErpCredential(11, M.VENDOR_NAVER, "54321")]},
            "authority_lost": {"accounts": {}},
            "ad_account_changed": {"accounts": {12345: {**self.accounts[12345], "adAccountNo": 8000001}}},
            "duplicate_claim": {"people": self.renamed + [other], "ids": self.ids + [M.ErpCredential(12, M.VENDOR_NAVER, "12345")]},
            "rejected": {"decisions": [M.HumanDecision(11, 12345, M.DECISION_REJECTED)]},
            "confirmed_elsewhere": {"people": self.renamed + [other], "decisions": [M.HumanDecision(12, 12345)]},
            "name_elsewhere": {"people": self.renamed + [M.ErpProspect(12, "처음상호")]},
            "namespace_ambiguous": {"accounts": {**self.accounts, 54321: {"customerId": 54321, "adAccountNo": 12345, "adAccountName": "별도업체"}}},
            "numeric_conflict": {"ids": [M.ErpCredential(11, M.VENDOR_NAVER, "54321", ad_account_no_raw="8000000")]},
        }
        for reason, inputs in cases.items():
            with self.subTest(reason=reason):
                self.assertFalse(any(p.possibility_id == 11 for p in self.match(**inputs).pairs))

    def test_explicit_number_evidence_does_not_accept_changed_erp_claim(self):
        ids = [M.ErpCredential(11, M.VENDOR_NAVER, None, ad_account_no_raw="8000000")]
        pair = M.match(self.people, ids, self.accounts, accounts_complete=True).pairs[0]
        self.evidence = {(11, 12345): pair.auto_identity_fingerprint}
        self.assertEqual(self.match(ids=ids).pairs[0].link, "auto")
        self.assertFalse(self.match().pairs)  # 숫자 칸의 종류가 바뀌었으면 새 근거가 필요하다.

    def test_malformed_evidence_fails_closed(self):
        for value in ([], {"11:12345": "a" * 64}, {(True, 12345): "a" * 64}, {(11, 12345): "old"}):
            with self.subTest(value=value), self.assertRaises(M.BadInput):
                M.match(self.people, self.ids, self.accounts, accounts_complete=True, auto_evidence=value)


class AutomaticIdentityMigrationTest(unittest.TestCase):
    def test_nullable_migration_preserves_legacy_history_without_promoting_it(self):
        conn = sqlite3.connect(":memory:", isolation_level=None)
        for sql in S._SCHEMA:
            conn.execute(sql)
        conn.execute("INSERT INTO naver_auto_meta(key,value) VALUES ('schema_version',?)", (str(S.SCHEMA_VERSION),))
        conn.execute("""INSERT INTO naver_auto_link_memory
            (possibility_id,customer_id,link,first_matched_at,last_matched_at)
            VALUES (11,12345,'auto','2026-10-01T00:00:00+09:00','2026-10-02T00:00:00+09:00')""")
        store = S.Store(conn, ":memory:", None, writer=True)
        self.addCleanup(store.close)
        self.assertEqual(store.automatic_link_evidence(), {})  # writer 이관 전 reader도 strict로 동작
        before = list(conn.execute("SELECT * FROM naver_auto_link_memory"))[0]
        store._migrate()
        store._migrate()  # 반복 이관은 멱등
        self.assertEqual(list(conn.execute("SELECT * FROM naver_auto_link_memory"))[0], before + (None,))
        self.assertEqual(store.automatic_link_evidence(), {})
        self.assertEqual(store.matched_before("auto"), {(11, 12345)})
        self.assertEqual(conn.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()[0], str(S.SCHEMA_VERSION))

    @unittest.skipUnless(sys.platform == "linux", "실제 inode flock+WAL 계약은 Linux에서 검증")
    def test_nullable_column_preserves_reader_queries_and_single_writer_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "engine.sqlite")
            with S.open_writer(path) as writer:
                with self.assertRaises(S.StoreBusy):
                    S.open_writer(path)
                # 구판 writer가 사용하던 명시적 열 INSERT도 새 nullable 열을 무시한다.
                writer._conn.execute("""INSERT INTO naver_auto_link_memory
                    (possibility_id,customer_id,link,first_matched_at,last_matched_at)
                    VALUES (11,12345,'auto','2026-10-01T00:00:00+09:00','2026-10-02T00:00:00+09:00')""")
                with S.open_reader(path) as reader:
                    self.assertEqual(reader.automatic_link_evidence(), {})
                    self.assertEqual(reader.matched_before("auto"), {(11, 12345)})
                    self.assertEqual(reader.meta("schema_version"), str(S.SCHEMA_VERSION))
