"""광고 상태 사유는 실제 응답을 보존하고 수집·매칭 사유를 추측하지 않는다."""
from datetime import datetime, timedelta, timezone
import pathlib
import sys
from types import SimpleNamespace
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import checks as C
from naver_engine import ad_reasons as R
from naver_engine import morning as M


AT = datetime(2026, 10, 2, 10, 0, tzinfo=timezone(timedelta(hours=9)))


class AdReasonsTest(unittest.TestCase):
    def test_new_codes_remain_unknown_with_original_target_and_read_time(self):
        record = {"nccCampaignId": "cmp-a001", "status": "FUTURE_STATUS",
                  "statusReason": "FUTURE_REASON"}
        result = R.describe("campaign", record, checked_at=AT)
        self.assertEqual(result, {
            "source": "naver_ad_status", "entity": "campaign", "entity_id": "cmp-a001",
            "checked_at": AT.isoformat(),
            "status": {"code": "FUTURE_STATUS", "meaning": "해석 미확인", "code_state": "unknown"},
            "reason": {"code": "FUTURE_REASON", "meaning": "해석 미확인", "code_state": "unknown"},
            "parents": [],
        })

    def test_missing_detail_is_not_an_unknown_code_or_inferred_from_status(self):
        for missing in (None, ""):
            with self.subTest(code=missing):
                record = {"nccCampaignId": "cmp-a001", "status": "ELIGIBLE", "statusReason": missing}
                result = R.describe("campaign", record, checked_at=AT)
                self.assertEqual(result["reason"], {
                    "code": missing, "meaning": "상세 사유 미제공", "code_state": "not_provided"})
        self.assertEqual(R.describe("campaign", {"nccCampaignId": "cmp-a001"}, checked_at=AT)["status"],
                         {"code": None, "meaning": "상태 미제공", "code_state": "not_provided"})

    def test_official_reasons_have_specific_meanings_without_normalizing_raw_codes(self):
        codes = {
            "ELIGIBLE": "노출 가능한 상태",
            "CAMPAIGN_DELETED": "캠페인 삭제 상태", "CAMPAIGN_PAUSED": "캠페인 사용자 중지",
            "CAMPAIGN_PENDING": "캠페인 노출 시작일 전", "CAMPAIGN_ENDED": "캠페인 노출 종료일 지남",
            "CAMPAIGN_LIMITED_BY_BUDGET": "캠페인 예산 한도 도달",
            "BUSINESS_CHANNEL_PAUSED": "사업채널 중지 상태",
            "BUSINESS_CHANNEL_DISAPPROVED": "사업채널 검수 보류 또는 반려",
            "BUSINESS_CHANNEL_UNDER_REVIEW": "사업채널 검수 등록 상태",
            "BUSINESS_CHANNEL_ABNORMAL_INTERLOCK": "사업채널 외부 연동 이상",
            "PC_BUSINESS_CHANNEL_APPROVED": "PC 사업채널 통과에 따른 일부 노출",
            "PC_BUSINESS_CHANNEL_DISAPPROVED": "PC 사업채널 검수 보류 또는 반려",
            "PC_BUSINESS_CHANNEL_ABNORMAL_INTERLOCK": "PC 사업채널 외부 연동 이상",
            "PC_BUSINESS_CHANNEL_UNDER_REVIEW": "PC 사업채널 검수 등록 상태",
            "MOBILE_BUSINESS_CHANNEL_APPROVED": "모바일 사업채널 통과에 따른 일부 노출",
            "MOBILE_BUSINESS_CHANNEL_DISAPPROVED": "모바일 사업채널 검수 보류 또는 반려",
            "MOBILE_BUSINESS_CHANNEL_ABNORMAL_INTERLOCK": "모바일 사업채널 외부 연동 이상",
            "MOBILE_BUSINESS_CHANNEL_UNDER_REVIEW": "모바일 사업채널 검수 등록 상태",
            "GROUP_DELETED": "광고그룹 삭제 상태", "GROUP_PAUSED": "광고그룹 사용자 중지",
            "GROUP_LIMITED_BY_BUDGET": "광고그룹 예산 한도 도달",
            "GROUP_PAUSED_BY_INVALID_TARGET": "광고그룹 타겟 설정 오류",
            "KEYWORD_DELETED": "키워드 삭제 상태", "KEYWORD_PAUSED": "키워드 사용자 중지",
            "KEYWORD_DISAPPROVED": "키워드 검수 보류", "KEYWORD_DENIED": "키워드 검수 반려",
            "KEYWORD_UNDER_REVIEW": "키워드 검수 등록 상태",
            "AD_DELETED": "소재 삭제 상태", "AD_PAUSED": "소재 사용자 중지",
            "AD_ABNORMAL_INTERLOCK": "소재 외부 연동 이상", "AD_DISAPPROVED": "소재 검수 보류 또는 반려",
            "AD_UNDER_REVIEW": "소재 검수 등록 상태", "AD_EXTENSION_DELETED": "확장소재 삭제 상태",
            "AD_EXTENSION_PAUSED": "확장소재 사용자 중지",
            "AD_EXTENSION_NOT_SCHEDULED": "확장소재 요일 또는 시간 설정에 따른 일시중지",
            "AD_EXTENSION_DISAPPROVED": "확장소재 검수 보류 또는 반려",
            "AD_EXTENSION_UNDER_REVIEW": "확장소재 검수 등록 상태",
            "AD_EXTENSION_PENDING": "확장소재 설정 노출 기간 밖",
            "AD_EXTENSION_ABNORMAL_INTERLOCK": "확장소재 외부 연동 이상",
            "LACK_OF_ACCOUNT_BALANCE": "계정 예산 부족", "REFUND_IN_PROGRESS": "계정 환불 진행 중",
        }
        for code, meaning in codes.items():
            with self.subTest(code=code):
                result = R.describe("campaign", {"nccCampaignId": "cmp-a001", "status": "ELIGIBLE",
                                                 "statusReason": code}, checked_at=AT)
                self.assertEqual(result["status"]["meaning"], "노출 가능한 상태")
                self.assertEqual(result["reason"], {"code": code, "meaning": meaning, "code_state": "known"})
        for raw in (" CAMPAIGN_PAUSED ", "campaign_paused", "STATUS_FROM_AUDIT", "KEY_REJECTED", "MATCH_REVIEW"):
            with self.subTest(raw=raw):
                reason = R.describe("campaign", {"nccCampaignId": "cmp-a001", "statusReason": raw},
                                    checked_at=AT)["reason"]
                self.assertEqual((reason["code"], reason["code_state"]), (raw, "unknown"))

    def test_each_target_and_observed_parent_preserve_their_own_status_and_time(self):
        keys = {"campaign": "nccCampaignId", "adgroup": "nccAdgroupId", "ad": "nccAdId",
                "keyword": "nccKeywordId", "ad_extension": "nccAdExtensionId",
                "business_channel": "nccBusinessChannelId"}
        for entity, key in keys.items():
            with self.subTest(entity=entity):
                row = R.describe(entity, {key: "example-id", "statusReason": "ELIGIBLE"}, checked_at=AT)
                self.assertEqual((row["entity"], row["entity_id"]), (entity, "example-id"))
        parent_at = AT - timedelta(minutes=2)
        parent = {"nccCampaignId": "cmp-a001", "status": "PAUSED", "statusReason": "CAMPAIGN_PAUSED"}
        record = {"nccAdgroupId": "grp-a001", "nccCampaignId": "cmp-a001", "status": "ELIGIBLE",
                  "statusReason": "ELIGIBLE", "ownerNaverId": "must-not-leak"}
        result = R.describe("adgroup", record, checked_at=AT, parents=(("campaign", parent, parent_at),))
        self.assertEqual(result["reason"]["code"], "ELIGIBLE")
        self.assertEqual(result["parents"], [R.describe("campaign", parent, checked_at=parent_at)])
        self.assertNotIn("must-not-leak", str(result))
        self.assertEqual(record["statusReason"], "ELIGIBLE")
        self.assertEqual(parent["statusReason"], "CAMPAIGN_PAUSED")

    def test_invalid_shapes_cannot_be_labeled_as_an_observed_ad_status(self):
        base = {"nccCampaignId": "cmp-a001", "status": "ELIGIBLE", "statusReason": "ELIGIBLE"}
        for record in ([], {}, dict(base, nccCampaignId=None), dict(base, status=1),
                       dict(base, statusReason=["CAMPAIGN_PAUSED"])):
            with self.subTest(record=record), self.assertRaises(ValueError):
                R.describe("campaign", record, checked_at=AT)
        for at in (None, "2026-10-02", AT.replace(tzinfo=None)):
            with self.subTest(at=at), self.assertRaises(ValueError):
                R.describe("campaign", base, checked_at=at)
        with self.assertRaises(ValueError):
            R.describe("collection", base, checked_at=AT)

    def test_morning_public_read_and_input_keep_reason_without_enabling_new_rules(self):
        raw = {"nccCampaignId": "cmp-a001", "customerId": 1234567, "campaignTp": "SHOPPING",
               "status": "ELIGIBLE", "statusReason": "FUTURE_REASON", "userLock": False}

        class Reader:
            def get_campaigns(self, _handle):
                return [dict(raw)]

            def get_bizmoney(self, _handle):
                return {"bizmoney": 10000, "budgetLock": True, "refundLock": True}

            def get_stats_summary(self, _handle, _ids, _since, _until, **_kw):
                return SimpleNamespace(rows={"cmp-a001": dict.fromkeys(M.STAT_FIELDS, 0)}, cycle_base_tm=AT)

        observed = M.read_account(Reader(), None, 1234567, AT.date(), lambda: AT, AT + timedelta(minutes=1))
        account, _ = M.account_input(1234567, observed, AT.date(), M.DEFAULTS)
        self.assertEqual((account.campaigns[0].status, account.campaigns[0].status_reason),
                         ("ELIGIBLE", "FUTURE_REASON"))
        observed.series = None  # 통계 실패 경로도 이미 조회한 광고 사유는 유지한다.
        partial, _ = M.account_input(1234567, observed, AT.date(), M.DEFAULTS)
        self.assertEqual(partial.campaigns[0].status_reason, "FUTURE_REASON")
        legacy = C.CampaignInfo("cmp-a001", "SHOPPING", "ELIGIBLE", False, False, False, None, False, 1, 7)
        self.assertEqual((legacy.yday_imp, legacy.week_imp, legacy.status_reason), (1, 7, None))
        report = C.run_checks(account, None, AT)
        self.assertFalse(C.DEFAULT_SWITCHES[C.R_BIZMONEY_LOCK])
        self.assertNotIn(C.R_BIZMONEY_LOCK, report.rules_run)
        self.assertFalse(any(f.code in {"budget_lock", "refund_lock", "FUTURE_REASON"} for f in report.findings))


if __name__ == "__main__":
    unittest.main()
