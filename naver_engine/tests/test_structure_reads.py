"""광고 구조 GET 경계. 합성 HTTP만 사용한다."""
import unittest
import socket
from unittest.mock import patch
from datetime import datetime
from naver_engine import handles as H, naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import A, creds


class StructureReadTest(unittest.TestCase):
    def setUp(self):
        network=patch.object(socket.socket,"connect",side_effect=AssertionError("외부 송신 금지"))
        network.start()
        self.addCleanup(network.stop)
        self.clock=FakeClock(datetime(2026,10,2,10,tzinfo=S.KST))
        self.http=FakeNaver()
        self.reader=N.NaverReader(creds(),transport=self.http,clock=self.clock)
        self.handle=H.issue_inventory_handle(customer_id=A,snapshot_at=self.clock.now(),now=self.clock.now(),
                                             validate=lambda *args:True)

    def test_adgroup_get_keeps_raw_reason_and_drops_unneeded_fields(self):
        self.http.route(r"/ncc/adgroups",lambda call:(200,[{"customerId":A,"nccCampaignId":"cmp-test",
            "nccAdgroupId":"grp-test","status":"PAUSED","statusReason":"GROUP_LIMITED_BY_BUDGET",
            "private":"must-not-keep"}]))
        rows,cursor=self.reader.get_structure_page(self.handle,"adgroup","cmp-test")
        self.assertEqual(rows[0]["statusReason"],"GROUP_LIMITED_BY_BUDGET")
        self.assertNotIn("private",rows[0])
        self.assertIsNone(cursor)
        self.assertEqual(self.http.calls[0].query["nccCampaignId"],["cmp-test"])

    def test_wrong_customer_or_parent_never_becomes_an_observed_reason(self):
        for customer,parent in ((A+1,"grp-test"),(A,"grp-other")):
            self.http.route(r"/ncc/ads",lambda call:(200,[{"customerId":customer,"nccAdgroupId":parent,
                "nccAdId":"nad-test","statusReason":"AD_DISAPPROVED"}]))
            with self.assertRaises(N.NaverApiError):
                self.reader.get_structure_page(self.handle,"ad","grp-test")

    def test_unknown_entity_and_cursor_for_nonpaged_endpoint_are_rejected_before_request(self):
        for entity,parent,cursor in (("write","grp-test",None),("ad","grp-test","nad-other")):
            with self.assertRaises(ValueError):
                self.reader.get_structure_page(self.handle,entity,parent,page_token=cursor)
        self.assertEqual(self.http.calls,[])

    def test_full_page_returns_continuation_and_duplicate_page_is_not_completion(self):
        page=[{"customerId":A,"nccCampaignId":"cmp-test","nccAdgroupId":f"grp-{n}"} for n in range(1000)]
        self.http.route(r"/ncc/adgroups",lambda call:(200,page))
        rows,next_token=self.reader.get_structure_page(self.handle,"adgroup","cmp-test")
        self.assertEqual(len(rows),1000)
        self.assertEqual(next_token,"grp-999")
        with self.assertRaises(N.NaverApiError):
            self.reader.get_structure_page(self.handle,"adgroup","cmp-test",page_token=next_token)

    def test_authority_revocation_stops_before_http(self):
        valid=[True]
        handle=H.issue_inventory_handle(customer_id=A,snapshot_at=self.clock.now(),now=self.clock.now(),
                                        validate=lambda *args:valid[0])
        valid[0]=False
        with self.assertRaises(H.NotEligible):
            self.reader.get_structure_page(handle,"business_channel")
        self.assertEqual(self.http.calls,[])
