"""저장 근거의 결손·변조를 세팅 오류나 정상으로 오인하지 않는 순수 projection."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import socket
import unittest
from unittest.mock import patch

from naver_engine import ad_reasons as A
from naver_engine import setup_checks as C


NOW = datetime(2026, 10, 10, 10, tzinfo=timezone(timedelta(hours=9)))


def observation(entity, identifier, reason="ELIGIBLE", *, parents=(), at=NOW):
    record = {A._ENTITY_IDS[entity]: identifier, "status": "ELIGIBLE", "statusReason": reason}
    return A.describe(entity, record, checked_at=at, parents=parents)


def structure():
    campaign = {"nccCampaignId": "cmp-one", "status": "ELIGIBLE", "statusReason": "ELIGIBLE"}
    group = {"nccAdgroupId": "grp-one", "status": "ELIGIBLE", "statusReason": "ELIGIBLE"}
    return {"status": "ok", "stale": False, "checked_at": NOW.isoformat(), "error_code": None,
            "reasons": [observation("campaign", "cmp-one"),
                observation("adgroup", "grp-one", parents=(("campaign", campaign, NOW),)),
                observation("ad", "ad-one", parents=(("adgroup", group, NOW), ("campaign", campaign, NOW)))]}


def campaigns():
    return [{"nccCampaignId": "cmp-one", "campaignTp": "WEB_SITE", "useDailyBudget": False,
             "dailyBudget": 0, "usePeriod": False}]


def campaign_source():
    return {"status": "ok", "complete": True, "stale": False, "checked_at": NOW.isoformat()}


def by_key(result):
    return {item["key"]: item for item in result["items"]}


class SetupChecksTest(unittest.TestCase):
    def test_absence_of_evidence_is_unknown_and_does_not_claim_incomplete_setup(self):
        result = C.project_setup(now=NOW)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["counts"], {"attention": 0, "unknown": 14, "verified": 0, "not_applicable": 0})
        self.assertIn("설정 미완료라는 뜻은 아닙니다", by_key(result)["structure"]["summary"])
        self.assertEqual(by_key(result)["setup_completeness"]["state"], "unknown")
        self.assertIsNone(result["source"]["structure"]["checked_at"])
        self.assertNotIn("projected_at", result["source"])
        self.assertNotIn("checked_at", result["source"])

    def test_projection_clock_does_not_change_business_payload_with_same_fresh_source(self):
        data, raw, source = structure(), campaigns(), campaign_source()
        first = C.project_setup(now=NOW, structure=data, campaigns=raw, campaign_source=source)
        later = C.project_setup(now=NOW+timedelta(minutes=5), structure=data, campaigns=raw, campaign_source=source)
        self.assertEqual(first, later)
        self.assertEqual(later["source"]["structure"]["checked_at"], NOW.isoformat())
        self.assertEqual(later["source"]["campaigns"]["checked_at"], NOW.isoformat())

    def test_complete_status_collection_is_not_complete_setup_and_defaults_are_normal(self):
        result = C.project_setup(now=NOW, structure=structure(), campaigns=campaigns(), campaign_source=campaign_source())
        items = by_key(result)
        for key in ("structure", "inspection", "suspension", "delivery", "campaign_budget", "campaign_period"):
            self.assertEqual(items[key]["state"], "verified", key)
        for key in ("time_targeting", "region_targeting", "age_targeting", "negative_keywords", "creative_copy", "setup_completeness"):
            self.assertEqual(items[key]["state"], "unknown", key)
        self.assertEqual(result["counts"]["attention"], 0)
        self.assertIn("오류가 아닙니다", items["campaign_budget"]["next_action"])
        self.assertIn("전체 시간·전체 지역 설정 자체는 오류가 아닙니다", items["time_targeting"]["next_action"])

    def test_only_observed_official_reasons_raise_attention_without_required_restart(self):
        data = structure()
        data["reasons"][2] = observation("ad", "ad-one", "AD_DISAPPROVED",
            parents=(("adgroup", {"nccAdgroupId": "grp-one", "status": "ELIGIBLE", "statusReason": "ELIGIBLE"}, NOW),
                     ("campaign", {"nccCampaignId": "cmp-one", "status": "ELIGIBLE", "statusReason": "ELIGIBLE"}, NOW)))
        data["reasons"].append(observation("business_channel", "chan-one", "BUSINESS_CHANNEL_PAUSED"))
        data["reasons"].append(observation("business_channel", "chan-two", "LACK_OF_ACCOUNT_BALANCE"))
        result = C.project_setup(now=NOW, structure=data)
        for key in ("inspection", "suspension", "delivery"):
            self.assertEqual(by_key(result)[key]["state"], "attention")
            self.assertIn("설정 오류나 재개 필요를 단정하지 않습니다", by_key(result)[key]["next_action"])
        self.assertEqual(result["counts"]["attention"], 3)
        self.assertIn("AD_DISAPPROVED", result["source"]["reason_codes"])

    def test_missing_or_future_reason_codes_are_not_inferred_from_status_or_suffix(self):
        for reason in (None, "", "NEW_AD_DISAPPROVED", "paused", " AD_PAUSED "):
            with self.subTest(reason=reason):
                data = {**structure(), "reasons": [observation("campaign", "cmp-one", reason)]}
                data["reasons"][0]["status"] = A.describe("campaign", {"nccCampaignId": "cmp-one", "status": "PAUSED"}, checked_at=NOW)["status"]
                result = C.project_setup(now=NOW, structure=data)
                self.assertEqual(result["counts"]["attention"], 0)
                for key in ("inspection", "suspension", "delivery"):
                    self.assertEqual(by_key(result)[key]["state"], "unknown")

    def test_partial_stale_missing_and_future_source_cannot_assert_setup_problems(self):
        base = {**structure(), "reasons": [observation("campaign", "cmp-one", "CAMPAIGN_PAUSED")]}
        cases = [{"status": "partial"}, {"status": "retry"}, {"complete": False}, {"stale": True},
                 {"stale": 0}, {"checked_at": None}, {"checked_at": "2026-10-10T10:00:00"},
                 {"checked_at": (NOW+timedelta(seconds=1)).isoformat()},
                 {"checked_at": (NOW-timedelta(days=8)).isoformat()}]
        for change in cases:
            with self.subTest(change=change):
                result = C.project_setup(now=NOW, structure={**base, **change})
                self.assertEqual(result["counts"]["attention"], 0)
                self.assertEqual(by_key(result)["structure"]["state"], "unknown")

    def test_tampered_interpretation_identity_time_and_parents_fail_to_unknown(self):
        def reason_meaning(data): data["reasons"][0]["reason"]["meaning"] = "임의 정상"
        def code_state(data): data["reasons"][0]["reason"]["code_state"] = "unknown"
        def missing_parent(data): data["reasons"][2]["parents"] = []
        def changed_parent(data): data["reasons"][2]["parents"][0]["entity_id"] = "grp-other"
        def future_observation(data): data["reasons"][0]["checked_at"] = (NOW+timedelta(seconds=1)).isoformat()
        def old_observation(data): data["reasons"][0]["checked_at"] = (NOW-timedelta(days=8)).isoformat()
        def duplicate(data): data["reasons"].append(deepcopy(data["reasons"][0]))
        def extra_private_field(data): data["reasons"][0]["private"] = "SECRET"
        def wrong_source(data): data["reasons"][0]["source"] = "manual_claim"
        for mutate in (reason_meaning, code_state, missing_parent, changed_parent, future_observation,
                       old_observation, duplicate, extra_private_field, wrong_source):
            with self.subTest(mutate=mutate.__name__):
                data = structure()
                mutate(data)
                result = C.project_setup(now=NOW, structure=data)
                self.assertEqual(result["counts"]["attention"], 0)
                self.assertEqual(by_key(result)["structure"]["state"], "unknown")
                self.assertNotIn("SECRET", json.dumps(result))

    def test_schedule_and_period_reason_alone_are_not_missing_setup(self):
        for reason in ("CAMPAIGN_PENDING", "CAMPAIGN_ENDED", "AD_EXTENSION_NOT_SCHEDULED", "AD_EXTENSION_PENDING"):
            data = {**structure(), "reasons": [observation("campaign", "cmp-one", reason)]}
            result = C.project_setup(now=NOW, structure=data)
            self.assertEqual(result["counts"]["attention"], 0, reason)
            self.assertEqual(by_key(result)["time_targeting"]["state"], "unknown")

    def test_shopping_region_is_not_applicable_only_with_fresh_complete_campaign_raw(self):
        raw = [{**campaigns()[0], "campaignTp": "SHOPPING"}]
        result = C.project_setup(now=NOW, campaigns=raw, campaign_source=campaign_source())
        self.assertEqual(by_key(result)["region_targeting"]["state"], "not_applicable")
        self.assertEqual(result["counts"]["not_applicable"], 1)
        for source in (None, {**campaign_source(), "stale": True}, {**campaign_source(), "complete": False},
                       {**campaign_source(), "status": "partial"}, {**campaign_source(), "checked_at": None}):
            result = C.project_setup(now=NOW, campaigns=raw, campaign_source=source)
            self.assertEqual(by_key(result)["region_targeting"]["state"], "unknown")
        for raw in ([], [{**campaigns()[0], "campaignTp": "NEW_TYPE"}],
                    [{**campaigns()[0], "campaignTp": "SHOPPING"}, {**campaigns()[0], "nccCampaignId": "cmp-two"}]):
            result = C.project_setup(now=NOW, campaigns=raw, campaign_source=campaign_source())
            self.assertEqual(by_key(result)["region_targeting"]["state"], "unknown")

    def test_budget_invalid_values_and_incomplete_campaign_snapshot_are_unknown(self):
        for value in (None, True, "100", float("nan"), float("inf"), -1, 10**1000):
            raw = [{**campaigns()[0], "useDailyBudget": True, "dailyBudget": value}]
            result = C.project_setup(now=NOW, campaigns=raw, campaign_source=campaign_source())
            self.assertEqual(by_key(result)["campaign_budget"]["state"], "unknown")
            self.assertEqual(result["counts"]["attention"], 0)
        for raw in ([campaigns()[0], campaigns()[0]], [{"nccCampaignId": "bad id"}]):
            result = C.project_setup(now=NOW, campaigns=raw, campaign_source=campaign_source())
            self.assertEqual(by_key(result)["campaign_budget"]["state"], "unknown")

    def test_valid_budget_and_period_observation_does_not_claim_adequacy_or_execution(self):
        for period in (("2026-11-01", "2026-11-30"), ("2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")):
            raw = [{**campaigns()[0], "useDailyBudget": True, "dailyBudget": 50000,
                    "usePeriod": True, "periodStartDt": period[0], "periodEndDt": period[1]}]
            result = C.project_setup(now=NOW, campaigns=raw, campaign_source=campaign_source())
            self.assertEqual(by_key(result)["campaign_budget"]["state"], "verified")
            self.assertEqual(by_key(result)["campaign_period"]["state"], "verified")
            self.assertEqual(result["counts"]["attention"], 0)
        raw[0]["periodStartDt"] = "2027-01-01"
        self.assertEqual(by_key(C.project_setup(now=NOW, campaigns=raw, campaign_source=campaign_source()))["campaign_period"]["state"], "unknown")

    def test_report_proposals_are_not_goal_budget_or_approval_evidence(self):
        plan = {"weekly_plan": [{"action": "예산 늘리기"}], "monthly_plan": [{"action": "전환 개선"}],
                "goal": {"made_up": "목표"}, "budget_plan": {"made_up": True}}
        result = C.project_setup(now=NOW, plan=plan)
        self.assertEqual(by_key(result)["goal"]["state"], "unknown")
        self.assertEqual(by_key(result)["budget_plan"]["state"], "unknown")
        result = C.project_setup(now=NOW, plan={"goal": "합의된 전환 목표", "budget_plan": {"monthly_budget": 1000000}})
        self.assertEqual(by_key(result)["goal"]["state"], "verified")
        self.assertEqual(by_key(result)["budget_plan"]["state"], "verified")
        self.assertIn("승인·집행·달성 확인은 별도", by_key(result)["goal"]["summary"])
        self.assertIn("대조한 결과는 아닙니다", by_key(result)["budget_plan"]["summary"])

    def test_projection_is_pure_bounded_and_does_not_emit_private_raw_fields(self):
        data, raw, source = structure(), campaigns(), campaign_source()
        raw[0].update(name="PRIVATE_CAMPAIGN", trackingUrl="PRIVATE_URL", timeTarget="ALL", regionTarget="ALL")
        original = deepcopy((data, raw, source))
        with patch.object(socket.socket, "connect", side_effect=AssertionError("네트워크 금지")), \
                patch("builtins.open", side_effect=AssertionError("파일 접근 금지")):
            result = C.project_setup(now=NOW, structure=data, campaigns=raw, campaign_source=source)
        self.assertEqual((data, raw, source), original)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(sum(result["counts"].values()), len(result["items"]))
        self.assertTrue(all(set(item) == {"key", "label", "state", "summary", "next_action"} for item in result["items"]))
        excessive = {**data, "reasons": [data["reasons"][0]]*10001}
        self.assertEqual(by_key(C.project_setup(now=NOW, structure=excessive))["structure"]["state"], "unknown")

    def test_empty_completed_collection_does_not_assert_ads_exist_or_setup_complete(self):
        result = C.project_setup(now=NOW, structure={**structure(), "reasons": []})
        self.assertEqual(by_key(result)["structure"]["state"], "verified")
        self.assertIn("0개", by_key(result)["structure"]["summary"])
        self.assertEqual(by_key(result)["inspection"]["state"], "unknown")
        self.assertEqual(by_key(result)["setup_completeness"]["state"], "unknown")

    def test_aware_projection_clock_is_required(self):
        for value in (None, "2026-10-10", NOW.replace(tzinfo=None)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                C.project_setup(now=value)


if __name__ == "__main__":
    unittest.main()
