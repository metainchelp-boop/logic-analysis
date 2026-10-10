"""Durable account-isolated evidence, honest measurement and conservative A/B gates."""
from copy import deepcopy
import json
import sqlite3
import tempfile
import unittest

from naver_engine import learning_assets as L, store as S

AT = "2026-10-11T12:00:00+09:00"
REGISTERED = "2026-09-01T12:00:00+09:00"


def performance():
    document = L.document_template("performance")
    document["title"] = "PRIVATE ADVERTISER / INTERNAL COMMENT"
    document["metadata"].update(industry="food", goal="ctr", ad_type="shopping", budget_band="300k_1m")
    document["source_refs"] = {"report_id": 91, "report_revision": "a" * 64}
    document["evidence"].update(period_start="2026-09-01", period_end="2026-09-30", impressions=1000,
        clicks=100, spend=35000, conversions=None, conversion_value=None)
    return document


def experiment():
    document = L.document_template("experiment")
    document["metadata"].update(industry="food", goal="ctr", ad_type="shopping", budget_band="300k_1m")
    document["evidence"].update(period_start="2026-09-02", period_end="2026-09-08", status="completed",
        min_sample_per_arm=10000, baseline_rate=0.1, mde_percent=20, randomized=True, independent_units=True, one_variable=True,
        measurement_complete=True, lag_mature=True, allocation_valid=True, preregistered_at=REGISTERED)
    document["evidence"]["control"].update(impressions=20000, clicks=2000, spend=100000)
    document["evidence"]["treatment"].update(impressions=20000, clicks=3000, spend=100000)
    return document


class LearningAssetsTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        self.addCleanup(self.connection.close)

    def save(self, document, *, version=0, asset_id="case-a", at=AT, actor=10, account="customer:101"):
        return L.record(self.connection, 11, account, actor, at, version, asset_id, document)

    def review(self, *, version=1, asset_id="case-a", action="review"):
        return L.record(self.connection, 11, "customer:101", 20, AT, version, asset_id, action=action)

    def registered_experiment(self, document=None):
        final = document or experiment()
        draft = deepcopy(final)
        draft["evidence"]["status"] = "running"
        for arm in ("control", "treatment"):
            draft["evidence"][arm] = {key: None for key in L.METRICS}
        self.save(draft, at=REGISTERED)
        self.save(final, version=1)
        return self.review(version=2)

    def test_append_only_versions_idempotence_conflicts_and_durable_reopen(self):
        first = self.save(performance())
        retry = self.save(performance(), at="2026-10-11T12:01:00+09:00")
        self.assertEqual(first, retry)
        reviewed = self.review()
        self.assertEqual((first["version"], reviewed["version"], reviewed["state"]), (1, 2, "reviewed"))
        changed = performance()
        changed["title"] = "updated"
        with self.assertRaises(S.StoreRefused):
            self.save(changed, version=1)
        new = self.save(changed, version=2)
        self.assertEqual((new["version"], new["state"]), (3, "draft"))
        history = L.list_assets(self.connection, 11, "customer:101", include_history=True)
        self.assertEqual([item["version"] for item in history], [3, 2, 1])
        self.assertEqual(history[-1], first)
        self.assertEqual(L.retrieve(self.connection, 11, "customer:101")["cases"], [])
        with tempfile.TemporaryDirectory() as directory:
            path = directory + "/assets.sqlite3"
            destination = sqlite3.connect(path)
            self.connection.backup(destination)
            destination.close()
            reopened = sqlite3.connect(path)
            self.addCleanup(reopened.close)
            self.assertEqual(L.get_asset(reopened, 11, "customer:101", "case-a"), new)

    def test_store_evidence_api_rolls_back_partial_history_without_committing_caller(self):
        self.connection.execute("INSERT INTO naver_auto_meta(key,value) VALUES('unrelated','keep')")
        self.assertTrue(self.connection.in_transaction)
        connection = self.connection
        class DenyHeadWrite:
            def execute(self, sql, values=()):
                if "ON CONFLICT" in sql:
                    raise sqlite3.OperationalError("synthetic head failure")
                return connection.execute(sql, values)
        repository = S.learning_asset_storage(DenyHeadWrite())
        with self.assertRaises(sqlite3.OperationalError):
            repository.record(11, "customer:101", 10, AT, 0, "atomic", performance())
        self.assertTrue(self.connection.in_transaction)
        self.assertEqual(self.connection.execute("SELECT value FROM naver_auto_meta WHERE key='unrelated'").fetchone()[0], "keep")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM naver_auto_meta WHERE key LIKE 'learning-%'").fetchone()[0], 0)

    def test_store_evidence_api_preserves_existing_read_connection_authorizer(self):
        first = self.save(performance())
        seen = []
        def readonly(action, *args):
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                seen.append(action)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.connection.set_authorizer(readonly)
        repository = S.learning_asset_storage(self.connection)
        self.assertIs(S.learning_asset_storage(repository), repository)
        self.assertEqual(repository.get_asset(11, "customer:101", "case-a"), first)
        with self.assertRaises(sqlite3.DatabaseError):
            repository.record(11, "customer:101", 20, AT, 1, "case-a", action="review")
        self.assertTrue(seen)
        self.assertEqual(repository.get_asset(11, "customer:101", "case-a"), first)
        self.assertEqual(len(repository.list_assets(11, "customer:101", include_history=True)), 1)

    def test_reviewed_retrieval_scope_privacy_known_metadata_and_null_not_zero(self):
        self.save(performance())
        self.review()
        self.save(performance(), account="customer:202", asset_id="elsewhere")
        L.record(self.connection, 22, "customer:101", 10, AT, 0, "other-client", performance())
        result = L.retrieve(self.connection, 11, "customer:101")
        self.assertEqual(len(result["cases"]), 1)
        case = result["cases"][0]
        self.assertIsNone(case["evidence"]["conversions"])
        self.assertIsNone(case["evidence"]["conversion_value"])
        self.assertFalse(case["assessment"]["causal_claim"])
        serialized = json.dumps(result)
        for private in ("PRIVATE", "customer:101", "report_id", "author", "source_refs", "possibility_id"):
            self.assertNotIn(private, serialized)
        self.assertEqual(L.retrieve(self.connection, 22, "customer:101")["cases"], [])
        metadata = performance()["metadata"]
        metadata["industry"] = "pet"
        self.assertEqual(L.retrieve(self.connection, 11, "customer:101", metadata)["cases"], [])
        self.assertIsNone(L.get_asset(self.connection, 11, "customer:202", "case-a"))

    def test_setting_plan_is_not_an_executed_change_or_causal_experiment(self):
        document = L.document_template("setting_change")
        document["evidence"].update(changed_variable="daily_spend_cap", before={"daily_spend_cap": None},
                                    after={"daily_spend_cap": 10000})
        self.save(document)
        reviewed = self.review()
        self.assertEqual(reviewed["assessment"]["outcome"], "observation")
        self.assertIn("planned_change", reviewed["assessment"]["reason_codes"])
        self.assertFalse(reviewed["assessment"]["causal_claim"])
        document["evidence"]["execution"] = "applied"
        with self.assertRaises(S.StoreRefused):
            self.save(document, version=2)
        document["evidence"]["observed_at"] = "2026-10-12T12:00:00+09:00"
        with self.assertRaises(S.StoreRefused):
            self.save(document, version=2)

    def test_only_fixed_horizon_preregistered_adequate_randomized_binary_difference_wins(self):
        reviewed = self.registered_experiment()
        assessment = reviewed["assessment"]
        self.assertEqual((assessment["outcome"], assessment["winner"]), ("winner", "treatment"))
        self.assertTrue(assessment["causal_claim"])
        self.assertGreater(assessment["confidence_interval"]["low"], 0)
        self.assertGreater(assessment["required_sample_per_arm"], 3000)
        self.assertEqual(L.retrieve(self.connection, 11, "customer:101")["cases"][0]["assessment"], assessment)

    def test_historical_import_cannot_forge_preregistration_or_review_override(self):
        self.save(experiment())
        reviewed = self.review()
        self.assertEqual(reviewed["assessment"]["outcome"], "invalid")
        self.assertIn("not_preregistered", reviewed["assessment"]["reason_codes"])
        self.assertIsNone(reviewed["assessment"]["winner"])
        self.assertFalse(reviewed["assessment"]["causal_claim"])
        self.assertEqual(len(L.retrieve(self.connection, 11, "customer:101")["cases"]), 1)
        with self.assertRaises(S.StoreRefused):
            L.record(self.connection, 11, "customer:101", 20, AT, 2, "case-a", {"outcome": "winner"}, "review")

    def test_changed_predeclared_protocol_does_not_silently_become_winner(self):
        draft = experiment()
        draft["evidence"]["status"] = "running"
        self.save(draft, at=REGISTERED)
        final = experiment()
        final["evidence"]["mde_percent"] = 10
        self.save(final, version=1)
        reviewed = self.review(version=2)
        self.assertEqual(reviewed["assessment"]["outcome"], "invalid")
        self.assertIn("protocol_changed", reviewed["assessment"]["reason_codes"])

    def test_unknown_inconclusive_invalid_and_stopped_are_preserved(self):
        cases = [
            ("measurement_complete", False, "unknown", "measurement_incomplete"),
            ("lag_mature", False, "unknown", "lag_not_mature"),
            ("randomized", False, "invalid", "not_randomized"),
            ("independent_units", False, "invalid", "independent_units_unknown"),
            ("one_variable", False, "invalid", "multiple_variables"),
            ("status", "stopped", "invalid", "stopped"),
            ("status", "running", "unknown", "running"),
            ("min_sample_per_arm", 1, "invalid", "predeclared_sample_below_power"),
        ]
        for field, value, outcome, reason in cases:
            with self.subTest(field=field, value=value):
                document = experiment()
                document["evidence"][field] = value
                registration = {"at": REGISTERED, "spec_hash": L._spec_hash(document)}
                assessment = L.assess(document, AT, registration)
                self.assertEqual(assessment["outcome"], outcome)
                self.assertIn(reason, assessment["reason_codes"])
                self.assertFalse(assessment["causal_claim"])
                self.assertIsNone(assessment["winner"])
        document = experiment()
        document["evidence"]["treatment"]["clicks"] = 2001
        result = L.assess(document, AT, {"at": REGISTERED, "spec_hash": L._spec_hash(document)})
        self.assertEqual(result["outcome"], "inconclusive")
        self.assertIn("no_statistical_separation", result["reason_codes"])

    def test_srm_binary_counts_missing_and_cpa_roas_aggregate_are_not_winners(self):
        variations = [
            ("srm", lambda e: e["treatment"].update(impressions=50000), "sample_ratio_mismatch"),
            ("missing", lambda e: e["control"].update(clicks=None), "missing_metrics"),
            ("multiple_events", lambda e: e["control"].update(clicks=21000), "invalid_binary_counts"),
            ("cpa", lambda e: e.update(goal="cpa", conversion_definition="platform"), "goal_requires_variance"),
            ("roas", lambda e: e.update(goal="roas", conversion_definition="purchase"), "goal_requires_variance"),
        ]
        for label, mutate, reason in variations:
            with self.subTest(label=label):
                document = experiment()
                mutate(document["evidence"])
                result = L.assess(document, AT, {"at": REGISTERED, "spec_hash": L._spec_hash(document)})
                self.assertIn(reason, result["reason_codes"])
                self.assertIsNone(result["winner"])

    def test_rejected_assets_are_not_retrieved_and_review_does_not_mutate_history(self):
        first = self.save(performance())
        rejected = self.review(action="reject")
        self.assertEqual(rejected["state"], "rejected")
        self.assertEqual(L.retrieve(self.connection, 11, "customer:101")["cases"], [])
        self.assertEqual(L.list_assets(self.connection, 11, "customer:101", include_history=True)[1], first)
        with self.assertRaises(S.StoreRefused):
            self.review(version=2)

    def test_whitelist_bounds_payload_corruption_and_system_observation(self):
        for mutate in (
            lambda d: d.update(outcome="winner"),
            lambda d: d["metadata"].update(industry="PRIVATE ACCOUNT"),
            lambda d: d["evidence"].update(spend=float("nan")),
            lambda d: d["evidence"].update(clicks=True),
            lambda d: d.update(title="<script>"),
            lambda d: d["source_refs"].update(api_key="secret"),
        ):
            document = performance()
            mutate(document)
            with self.assertRaises(S.StoreRefused):
                self.save(document)
        with self.assertRaises(S.StoreRefused):
            self.save(performance(), asset_id="unsafe:prefix")
        system = self.save(performance(), actor=None)
        self.assertIsNone(system["author"]["actor"])
        self.assertEqual(L.get_asset(self.connection, 11, "customer:101", "case-a"), system)
        with self.assertRaises(S.StoreRefused):
            L.record(self.connection, 11, "customer:101", None, AT, 1, "case-a", action="review")
        document = performance()
        document["source_refs"] = {}
        with self.assertRaises(S.StoreRefused):
            self.save(document, actor=None, asset_id="bad-system")
        self.connection.execute("UPDATE naver_auto_meta SET value=? WHERE key LIKE 'learning-head:%'", ("x" * (L.MAX_CHARS + 1),))
        with self.assertRaises(S.StoreError):
            L.list_assets(self.connection, 11, "customer:101")

    def test_copied_scope_payload_or_wrong_history_version_is_refused(self):
        self.save(performance())
        original_key, raw = self.connection.execute("SELECT key,value FROM naver_auto_meta WHERE key LIKE 'learning-head:%'").fetchone()
        other_key = "learning-head:" + L._identity(22, "customer:202") + "case-a"
        self.connection.execute("INSERT INTO naver_auto_meta(key,value) VALUES(?,?)", (other_key, raw))
        with self.assertRaises(S.StoreError):
            L.get_asset(self.connection, 22, "customer:202", "case-a")
        with self.assertRaises(S.StoreError):
            L.record(self.connection, 22, "customer:202", 10, AT, 1, "case-a", performance())
        wrong_version = "learning-version:" + L._identity(11, "customer:101") + "case-a:0000000000000002"
        self.connection.execute("INSERT INTO naver_auto_meta(key,value) VALUES(?,?)", (wrong_version, raw))
        with self.assertRaises(S.StoreError):
            self.review()
        self.assertEqual(self.connection.execute("SELECT value FROM naver_auto_meta WHERE key=?", (original_key,)).fetchone()[0], raw)

    def test_experiment_horizon_and_preregistration_use_korean_reporting_days(self):
        document = experiment()
        registration = {"at": REGISTERED, "spec_hash": L._spec_hash(document)}
        # UTC September 8 is already September 9 in the Korean report period.
        result = L.assess(document, "2026-09-08T16:00:00+00:00", registration)
        self.assertEqual(result["outcome"], "winner")
        still_open = L.assess(document, "2026-09-08T14:59:00+00:00", registration)
        self.assertEqual(still_open["outcome"], "unknown")
        self.assertIn("horizon_not_complete", still_open["reason_codes"])
        document["evidence"]["preregistered_at"] = "2026-09-01T16:00:00+00:00"
        registration = {"at": document["evidence"]["preregistered_at"], "spec_hash": L._spec_hash(document)}
        late = L.assess(document, AT, registration)
        self.assertEqual(late["outcome"], "invalid")
        self.assertIn("not_preregistered", late["reason_codes"])


if __name__ == "__main__":
    unittest.main()
