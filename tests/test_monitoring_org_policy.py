"""본인 담당 관제만 팀 계층 오류를 경고로 격리한다. 기존 조직 검증은 유지한다."""
from datetime import timedelta
import unittest

from app.naver_auto import org_snapshot as O, scope as SC
from naver_engine import sync as Y
from naver_engine.tests import test_sync as TS
from naver_engine.tests.test_catalog_links import make_fixture


class MonitoringOrgPolicyTest(unittest.TestCase):
    def setUp(self):
        self.prev = O.parse_org_snapshot(TS.org_payload(TS.T0))
        self.now = TS.T0+timedelta(hours=1)

    def test_team_only_problems_warn_without_changing_own_scope_or_default_rejection(self):
        changes = {
            "CYCLE": lambda body: body["teams"][2].update(parent_idx=11),
            "PARENT_LOST": lambda body: body["teams"].pop(2),
            "SYSTEM_TEAM_LOST": lambda body: body["teams"][1].update(name="변경팀", is_system=False),
            "MANAGER_SPIKE": lambda body: [row.update(is_manager=True) for row in body["employees"][2:6]],
            "EMPTY": lambda body: body.update(teams=[]),
        }
        for code, change in changes.items():
            with self.subTest(code=code):
                new = O.parse_org_snapshot(TS.org_payload(self.now, extra=change))
                self.assertIn(code, {finding.code for finding in O.check_snapshot(new, self.prev, self.now).reasons})
                check = O.check_monitoring_snapshot(new, self.prev, self.now)
                self.assertTrue(check.ok)
                warning = "TEAM_EMPTY" if code == "EMPTY" else code
                self.assertIn(warning, {finding.code for finding in check.warnings})
                scope = SC.scope_of(new, 100)
                self.assertEqual(scope.kind, SC.MINE)
                owns = {pid: SC.ownership_for_client(new, pid, pid, SC.MATCH_PID) for pid in (5000, 5001)}
                self.assertEqual(SC.clients_in(new, scope, owns), frozenset({5000}))
                self.assertEqual(SC.scope_of(new, 1).kind, SC.MINE)
                self.assertEqual(SC.scope_of(new, 0).kind, SC.ALL)

    def test_security_and_source_completeness_guards_remain_blocking(self):
        changes = {
            "EMPTY": lambda body: body.update(employees=[]),
            "TOP_MANAGER_NONE": lambda body: body["employees"][0].update(is_top_manager=False),
            "TOP_MANAGER_ADDED": lambda body: body["employees"][2].update(is_top_manager=True),
            "TOP_MANAGER_LIMIT": lambda body: [row.update(is_top_manager=True) for row in body["employees"][2:5]],
            "ACTIVE_DROP": lambda body: [row.update(status="RESIGNED") for row in body["employees"][2:12]],
            "OWNER_DROP": lambda body: body.update(owners=body["owners"][:20]),
            "OWNER_BLANK_SPIKE": lambda body: [row.update(manage_emp_idx=None, owner_source="none")
                                                for row in body["owners"][:10]],
            "FUTURE": lambda body: body.update(generated_at=(self.now+timedelta(minutes=11)).isoformat()),
            "STALE": lambda body: body.update(generated_at=TS.T0.isoformat()),
        }
        for code, change in changes.items():
            with self.subTest(code=code):
                new = O.parse_org_snapshot(TS.org_payload(self.now, extra=change))
                check = O.check_monitoring_snapshot(new, self.prev, self.now)
                self.assertFalse(check.ok)
                self.assertIn(code, {finding.code for finding in check.reasons})

    def test_retirement_deletion_and_nonmanagement_never_gain_own_scope(self):
        for change in (dict(status="RESIGNED"), dict(is_deleted=True), dict(is_management=False)):
            new = O.parse_org_snapshot(TS.org_payload(self.now,
                extra=lambda body: (body.update(teams=[]), body["employees"][2].update(change))))
            self.assertTrue(O.check_monitoring_snapshot(new, self.prev, self.now).ok)
            self.assertEqual(SC.scope_of(new, 100).kind, SC.NONE)

    def test_malformed_security_or_team_fields_are_not_silently_repaired(self):
        for field, value in (("is_top_manager", "true"), ("is_deleted", None), ("idx", -1)):
            body = TS.org_payload(self.now, extra=lambda body: body["employees"][2].update({field: value}))
            with self.assertRaises(O.SnapshotFormatError):
                O.parse_org_snapshot(body)
        body = TS.org_payload(self.now, extra=lambda body: body["teams"][2].update(parent_idx="wrong"))
        with self.assertRaises(O.SnapshotFormatError):
            O.parse_org_snapshot(body)

    def test_monitoring_sync_is_opt_in_and_keeps_manager_spike_as_warning_not_hold(self):
        fixture = make_fixture(accounts=1, managed=1, campaigns=0)
        self.addCleanup(fixture.store.close)
        clock, store = fixture.clock, fixture.store
        clock.advance(1)
        store.record_org(TS.org_payload(clock.now()), clock.now(), baseline=(32, 40, 2))
        clock.advance(1)
        body = TS.org_payload(clock.now(), extra=lambda body: [row.update(is_manager=True)
                                                              for row in body["employees"][2:6]])
        strict = Y.sync_org(TS.FakeErp(body), store, clock.now())
        self.assertEqual(strict.outcome, "refused")
        self.assertTrue(strict.needs_confirmation)
        result = Y.sync_org(TS.FakeErp(body), store, clock.now(), account_monitoring=True)
        self.assertEqual(result.outcome, "accepted")
        self.assertFalse(result.needs_confirmation)
        self.assertIn("MANAGER_SPIKE", result.codes)
        self.assertIn("MANAGER_SPIKE_BASELINE", result.codes)
        self.assertEqual(store.org_current()["body"]["employees"], body["employees"])
        self.assertEqual(store.last_sync("org")["outcome"], "accepted")


if __name__ == "__main__":
    unittest.main()
