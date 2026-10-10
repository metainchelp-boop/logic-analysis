"""Narrowed sessions recheck live ownership at both sides of fake Claude calls."""
import unittest
from unittest.mock import patch

from app.naver_auto import scope as SC
from naver_engine.tests import test_learning_workflow_web as LW, test_alerts as TA


class LearningScopeRecheckTests(unittest.TestCase):
    setUp = LW.LearningWorkflowWebTest.setUp
    call = LW.LearningWorkflowWebTest.call
    get = LW.LearningWorkflowWebTest.get
    seed_report = LW.LearningWorkflowWebTest.seed_report
    prepare = LW.LearningWorkflowWebTest.prepare
    detail = LW.LearningWorkflowWebTest.detail
    provider = LW.LearningWorkflowWebTest.provider

    def narrowed_strategy(self):
        body = {"report_id": 1, "account_key": self.key,
                "revision_fingerprint": self.payload["revision_fingerprint"],
                "expected_version": 0, "action": "generate_claude"}
        token = self.signer.issue(100, self.clock.now(), narrowed=True)
        self.assertTrue(self.signer.verify(token, self.clock.now()).narrowed)
        return self.call("POST", "/reports/strategy", token, body=body)

    def move_owner(self):
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 101), TA.owner(12, 101), TA.owner(13, 100)]), now)
        return now

    def reservations(self):
        return self.store._conn.execute("SELECT COUNT(*) FROM naver_auto_meta WHERE key LIKE 'learning-call:%'").fetchone()[0]

    def draft_version(self):
        return self.store.report_strategy(1, self.key, self.payload["revision_fingerprint"])["version"]

    def test_narrowed_claim_is_preserved_through_reservation_and_draft_save(self):
        self.prepare()
        seen = self.provider()
        with patch.object(SC, "narrowed_scope_of", wraps=SC.narrowed_scope_of) as narrowed:
            status, result, *_ = self.narrowed_strategy()
        self.assertEqual(status, 200, result)
        self.assertEqual(len(seen), 1)
        self.assertGreaterEqual(narrowed.call_count, 3)
        self.assertTrue(all(call.args[1] == 100 for call in narrowed.call_args_list))
        self.assertEqual((self.reservations(), self.draft_version()), (1, 1))

    def test_ownership_change_while_queued_prevents_reservation_and_provider_call(self):
        self.prepare()
        seen = self.provider()
        moved = []
        def write(function):
            if function.__name__ == "reserve" and not moved:
                moved.append(self.move_owner())
            return function(self.store)
        self.app._write = write
        with patch.object(SC, "narrowed_scope_of", wraps=SC.narrowed_scope_of) as narrowed:
            status, *_ = self.narrowed_strategy()
        self.assertEqual(status, 404)
        self.assertEqual(seen, [])
        self.assertEqual((self.reservations(), self.draft_version()), (0, 0))
        self.assertTrue(any(call.args[0].generated_at == moved[0].isoformat() for call in narrowed.call_args_list))

    def test_ownership_change_during_provider_discards_result_and_keeps_reservation(self):
        self.prepare()
        moved = []
        seen = self.provider(lambda: moved.append(self.move_owner()))
        with patch.object(SC, "narrowed_scope_of", wraps=SC.narrowed_scope_of) as narrowed:
            status, *_ = self.narrowed_strategy()
        self.assertEqual(status, 404)
        self.assertEqual(len(seen), 1)
        self.assertEqual((self.reservations(), self.draft_version()), (1, 0))
        self.assertTrue(any(call.args[0].generated_at == moved[0].isoformat() for call in narrowed.call_args_list))


if __name__ == "__main__":
    unittest.main()
