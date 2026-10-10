"""Authorized cross-advertiser experience remains anonymous and narrowly applicable."""
from copy import deepcopy
import json
import sqlite3
import unittest

from naver_engine import learning_assets as L, learning_retrieval as R, marketing_strategy as M, store as S
from naver_engine.tests.test_learning_assets import performance, AT
from naver_engine.tests.test_report_enrichment import snapshot


class LearningRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        self.addCleanup(self.connection.close)

    def asset(self, pid, key, asset_id="same-local-id", *, metadata=None, reviewed=True, rejected=False):
        document = performance()
        if metadata is not None:
            document["metadata"].update(metadata)
        L.record(self.connection, pid, key, 10, AT, 0, asset_id, document)
        if reviewed or rejected:
            L.record(self.connection, pid, key, 20, AT, 1, asset_id, action="reject" if rejected else "review")
        return document

    def test_cross_account_reuse_is_scoped_anonymous_and_has_private_source_refs(self):
        self.asset(11, "account-a")
        self.asset(22, "account-b")
        self.asset(33, "PRIVATE-UNAUTHORIZED")
        result = R.retrieve_scoped(self.connection, [(11, "account-a"), (22, "account-b")], 11, "account-a")
        self.assertEqual(result["coverage"]["cross_selected"], 1)
        self.assertEqual({ref["possibility_id"] for ref in result["refs"]}, {11, 22})
        self.assertEqual(len({case["asset_id"] for case in result["context"]["cases"]}), 2)
        context = M.build_context(snapshot(), learning_context=result["context"])
        wire = json.dumps(context)
        for private in ("PRIVATE", "account-a", "account-b", "same-local-id", "possibility_id", "account_key"):
            self.assertNotIn(private, wire)
        self.assertEqual(result["coverage"]["scope"], "authorized")
        again = R.retrieve_scoped(self.connection, [(22, "account-b"), (11, "account-a")], 11, "account-a")
        self.assertEqual(result, again)

    def test_unknown_target_tags_disable_cross_reuse_without_invented_classification(self):
        self.asset(11, "a", metadata={key: None for key in L.METADATA_ENUMS})
        self.asset(22, "b")
        result = R.retrieve_scoped(self.connection, [(11, "a"), (22, "b")], 11, "a")
        self.assertFalse(result["coverage"]["cross_enabled"])
        self.assertEqual([ref["possibility_id"] for ref in result["refs"]], [11])
        self.assertEqual(result["coverage"]["scanned_accounts"], 1)

    def test_exact_industry_goal_and_ad_type_required_unknown_or_mismatch_excluded(self):
        self.asset(11, "a")
        for pid, metadata in ((22, {"industry": "pet"}), (23, {"goal": "cvr"}),
                              (24, {"ad_type": "powerlink"}), (25, {"industry": None})):
            self.asset(pid, str(pid), metadata=metadata)
        allowed = [(11, "a")] + [(pid, str(pid)) for pid in (22, 23, 24, 25)]
        result = R.retrieve_scoped(self.connection, allowed, 11, "a")
        self.assertEqual(result["coverage"]["cross_selected"], 0)
        self.assertEqual(len(result["context"]["cases"]), 1)

    def test_drafts_and_rejected_cases_never_reused_and_unknown_target_can_use_explicit_tags(self):
        self.asset(11, "a", metadata={key: None for key in L.METADATA_ENUMS})
        desired = self.asset(22, "b")["metadata"]
        self.asset(23, "c", reviewed=False)
        self.asset(24, "d", rejected=True)
        result = R.retrieve_scoped(self.connection, [(11, "a"), (22, "b"), (23, "c"), (24, "d")], 11, "a", desired)
        self.assertEqual(result["coverage"]["cross_selected"], 1)
        self.assertEqual({ref["possibility_id"] for ref in result["refs"]}, {11, 22})

    def test_invalid_scope_or_target_fails_before_querying(self):
        attempts = []
        self.connection.set_trace_callback(attempts.append)
        for allowed, pid, key in (([], 11, "a"), ([(11, "a")], 22, "b"),
                                  ([(True, "a")], 11, "a"), ([(11, "a", "b")], 11, "a"),
                                  ([(pid, str(pid)) for pid in range(1, R.MAX_ALLOWED_PAIRS+2)], 11, "11")):
            with self.subTest(pid=pid), self.assertRaises(S.StoreRefused):
                R.retrieve_scoped(self.connection, allowed, pid, key)
        self.assertEqual(attempts, [])

    def test_bounded_candidate_scan_reports_truncation(self):
        self.asset(11, "a")
        for i in range(4):
            self.asset(22, "b", asset_id="case-"+str(i))
        previous = R.MAX_CANDIDATES
        R.MAX_CANDIDATES = 2
        self.addCleanup(setattr, R, "MAX_CANDIDATES", previous)
        result = R.retrieve_scoped(self.connection, [(11, "a"), (22, "b")], 11, "a")
        self.assertTrue(result["coverage"]["truncated"])
        self.assertEqual(result["coverage"]["candidates"], 3)
        self.assertLessEqual(len(result["context"]["cases"]), 5)

    def test_many_own_cases_reserve_space_for_agency_experience(self):
        for i in range(6):
            self.asset(11, "a", asset_id="own-"+str(i))
        self.asset(22, "b", "other-1")
        self.asset(23, "c", "other-2")
        result = R.retrieve_scoped(self.connection, [(11, "a"), (22, "b"), (23, "c")], 11, "a")
        self.assertEqual(len(result["refs"]), 5)
        self.assertEqual(result["coverage"]["cross_selected"], 2)
        self.assertEqual(sum(ref["possibility_id"] == 11 for ref in result["refs"]), 3)


if __name__ == "__main__":
    unittest.main()
