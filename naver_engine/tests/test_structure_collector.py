"""구조 수집: 실제 읽기 관문과 합성 HTTP만 사용한다."""
from copy import deepcopy
from datetime import datetime, timedelta
import socket
import unittest
from unittest.mock import patch

from naver_engine import structure_reads as R, naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import A, B, creds


NOW = datetime(2026, 10, 5, 9, tzinfo=S.KST)


class MemoryStructure:
    def __init__(self, clock):
        self.valid = True
        self.jobs = [{"customer_id": A, "kind": "daily", "cycle_day": "2026-10-05",
                      "period_start": "2026-10-04", "period_end": "2026-10-04",
                      "snapshot_at": clock.now(), "job_key": "structure:daily-test"}]
        self.progress, self.results = {}, {}

    def structure_work(self, now, limit):
        return deepcopy(self.jobs[:limit])

    def structure_account_valid(self, job, now):
        return self.valid and job in self.jobs

    def begin_structure_check(self, job, now):
        if not self.structure_account_valid(job, now):
            raise S.StoreRefused("시험 원천 변경")

    def structure_progress(self, job):
        return deepcopy(self.progress.get(job["job_key"]))

    def record_structure_progress(self, job, now, progress):
        self.begin_structure_check(job, now)
        R.validate_progress(progress, job)
        self.progress[job["job_key"]] = deepcopy(progress)

    def record_structure_check(self, job, now, values):
        self.begin_structure_check(job, now)
        self.results[job["job_key"]] = deepcopy(values)
        return values["status"]


class StructureCollectorTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = MemoryStructure(self.clock)
        self.reader = N.NaverReader(creds(), transport=self.http, clock=self.clock)
        self.campaigns = [{"customerId": A, "nccCampaignId": "cmp-one", "status": "PAUSED",
                           "statusReason": "CAMPAIGN_PAUSED", "name": "비공개이름"}]
        self.rows = {
            ("/ncc/channels", None): [{"customerId": A, "nccBusinessChannelId": "channel-one",
                "statusReason": "BUSINESS_CHANNEL_DISAPPROVED", "businessInfo": "비공개정보"}],
            ("/ncc/adgroups", "cmp-one"): [{"customerId": A, "nccCampaignId": "cmp-one",
                "nccAdgroupId": "group-one", "statusReason": "GROUP_PAUSED"}],
            ("/ncc/ads", "group-one"): [{"customerId": A, "nccAdgroupId": "group-one",
                "nccAdId": "ad-one", "statusReason": "AD_DISAPPROVED", "ad": "비공개문구"}],
            ("/ncc/keywords", "group-one"): [{"customerId": A, "nccAdgroupId": "group-one",
                "nccKeywordId": "keyword-one", "statusReason": "NEW_UNKNOWN", "keyword": "비공개키워드"}],
            ("/ncc/ad-extensions", "ad-one"): [{"customerId": A, "ownerId": "ad-one",
                "nccAdExtensionId": "extension-one", "statusReason": "AD_EXTENSION_DISAPPROVED"}],
        }
        self.http.route(r"/ncc/campaigns", lambda call: (200, deepcopy(self.campaigns)))
        self.http.route(r"/ncc/(channels|adgroups|ads|keywords|ad-extensions)", self.structure)

    def structure(self, call):
        parent = next((call.query[key][0] for key in ("nccCampaignId", "nccAdgroupId", "ownerId")
                       if key in call.query), None)
        rows = deepcopy(self.rows.get((call.path, parent), []))
        if call.path in ("/ncc/adgroups", "/ncc/keywords"):
            id_key = "nccAdgroupId" if call.path == "/ncc/adgroups" else "nccKeywordId"
            token = call.query.get("baseSearchId", [None])[0]
            start = next((i+1 for i, row in enumerate(rows) if row[id_key] == token), 0)
            rows = rows[start:start+N.PAGE_SIZE]
        return 200, rows

    def finish(self):
        for _ in range(12):
            result = R.run_structure(self.reader, self.store, self.clock.now)
            if result.counts.get("ok"):
                return self.store.results["structure:daily-test"]
            self.assertEqual(result.counts, {"partial": 1})
            self.clock.advance(60)
        self.fail("한정된 시험 구조의 이어읽기가 끝나지 않았습니다")

    def test_bounded_resume_covers_all_layers_and_actual_parent_reasons_without_private_fields(self):
        result = R.run_structure(self.reader, self.store, self.clock.now)
        self.assertEqual(result.counts, {"partial": 1})
        self.assertEqual(len(self.http.calls), 6)
        first = deepcopy(self.store.progress["structure:daily-test"])
        self.clock.advance(60)
        result = R.run_structure(self.reader, self.store, self.clock.now)
        self.assertEqual(result.counts, {"ok": 1})
        reasons = self.store.results["structure:daily-test"]["reasons"]
        self.assertEqual({r["entity"] for r in reasons},
                         {"campaign", "adgroup", "ad", "keyword", "ad_extension", "business_channel"})
        extension = next(r for r in reasons if r["entity"] == "ad_extension")
        self.assertEqual([r["entity"] for r in extension["parents"]], ["ad", "adgroup", "campaign"])
        campaign = extension["parents"][-1]
        self.assertEqual(campaign["reason"]["code"], "CAMPAIGN_PAUSED")
        self.assertEqual(campaign["checked_at"], first["records"]["campaign:cmp-one"]["checked_at"])
        self.assertLess(campaign["checked_at"], extension["checked_at"])
        keyword = next(r for r in reasons if r["entity"] == "keyword")
        self.assertEqual(keyword["reason"]["code_state"], "unknown")
        self.assertNotIn("비공개", str(self.store.progress)+str(reasons))
        pages = [(call.path, tuple(sorted((k, tuple(v)) for k, v in call.query.items())))
                 for call in self.http.calls if call.path != "/ncc/campaigns"]
        self.assertEqual(len(pages), len(set(pages)))
        self.assertTrue(all(call.method == "GET" for call in self.http.calls))

    def test_paged_groups_and_keywords_read_every_page_before_ok(self):
        self.rows[("/ncc/adgroups", "cmp-one")] = [
            {"customerId": A, "nccCampaignId": "cmp-one", "nccAdgroupId": f"group-{i}"} for i in range(3)]
        self.rows[("/ncc/keywords", "group-0")] = [
            {"customerId": A, "nccAdgroupId": "group-0", "nccKeywordId": f"keyword-{i}"} for i in range(3)]
        with patch.object(N, "PAGE_SIZE", 2):
            out = self.finish()
        self.assertEqual(sum(r["entity"] == "adgroup" for r in out["reasons"]), 3)
        self.assertEqual(sum(r["entity"] == "keyword" for r in out["reasons"]), 3)
        groups = [c for c in self.http.calls if c.path == "/ncc/adgroups"]
        keywords = [c for c in self.http.calls if c.path == "/ncc/keywords"
                    and c.query["nccAdgroupId"] == ["group-0"]]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[-1].query["baseSearchId"], ["group-1"])
        self.assertEqual(len(keywords), 2)
        self.assertEqual(keywords[-1].query["baseSearchId"], ["keyword-1"])

    def test_reused_entity_id_under_another_parent_is_not_complete(self):
        self.rows[("/ncc/adgroups", "cmp-one")].append(
            {"customerId": A, "nccCampaignId": "cmp-one", "nccAdgroupId": "group-other"})
        self.rows[("/ncc/ads", "group-other")] = [
            {"customerId": A, "nccAdgroupId": "group-other", "nccAdId": "ad-one"}]
        for _ in range(3):
            result = R.run_structure(self.reader, self.store, self.clock.now)
            if result.counts.get("retry"):
                break
        self.assertEqual(result.counts, {"retry": 1})
        self.assertEqual(self.store.results["structure:daily-test"]["error_code"], "STRUCTURE_INCOMPLETE")
        self.assertEqual(self.store.progress["structure:daily-test"]["records"]["ad:ad-one"]["parents"][0],
                         "adgroup:group-one")

    def test_empty_campaigns_still_require_channel_list_and_final_campaign_check(self):
        self.campaigns, self.rows = [], {}
        result = R.run_structure(self.reader, self.store, self.clock.now)
        self.assertEqual(result.counts, {"ok": 1})
        self.assertEqual(self.store.results["structure:daily-test"]["reasons"], [])
        self.assertEqual([c.path for c in self.http.calls], ["/ncc/campaigns", "/ncc/channels", "/ncc/campaigns"])

    def test_campaign_changes_at_finish_and_resume_do_not_keep_old_parents(self):
        self.campaigns, self.rows = [], {}
        changed = [{"customerId": A, "nccCampaignId": "cmp-new", "statusReason": "CAMPAIGN_PAUSED"}]
        self.http.script("/ncc/campaigns", (200, []), (200, changed))
        self.assertEqual(R.run_structure(self.reader, self.store, self.clock.now).counts, {"retry": 1})
        self.assertEqual(self.store.results["structure:daily-test"]["error_code"], "CAMPAIGNS_CHANGED")
        self.campaigns = changed
        self.assertEqual(R.run_structure(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        self.assertEqual(set(self.store.progress["structure:daily-test"]["records"]), {"campaign:cmp-new"})

    def test_current_authority_and_429_stop_before_another_account(self):
        self.http.tick = lambda call: setattr(self.store, "valid", False)
        self.assertEqual(R.run_structure(self.reader, self.store, self.clock.now).code, "SOURCE_CHANGED")
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(self.store.results, {})
        self.http.tick = None
        self.store.valid = True
        self.store.jobs.append(dict(self.store.jobs[0], customer_id=B, job_key="structure:other"))
        self.http.script("/ncc/campaigns", (429, {"code": 1016}))
        before = len(self.http.calls)
        self.assertEqual(R.run_structure(self.reader, self.store, self.clock.now, max_seconds=1).code, "BUDGET")
        self.assertEqual(len(self.http.calls)-before, 1)
        self.assertNotIn("structure:other", self.store.results)

    def test_deadline_and_account_eight_call_cap_hold_even_with_more_global_budget(self):
        self.http.tick = lambda call: self.clock.advance(2)
        result = R.run_structure(self.reader, self.store, self.clock.now, max_seconds=1)
        self.assertEqual(result.counts, {"retry": 1})
        self.assertEqual(len(self.http.calls), 1)
        self.http.tick = None
        before = len(self.http.calls)
        result = R.run_structure(self.reader, self.store, self.clock.now, max_calls=24, per_account_calls=8)
        self.assertEqual(result.counts, {"partial": 1})
        self.assertLessEqual(len(self.http.calls)-before, 8)

    def test_object_and_work_limits_leave_partial_evidence_never_complete(self):
        for name, maximum in (("MAX_OBJECTS", 2), ("MAX_TASKS", 5)):
            with self.subTest(name=name), patch.object(R, name, maximum):
                self.store.progress.clear()
                result = R.run_structure(self.reader, self.store, self.clock.now)
                self.assertEqual(result.counts, {"limited": 1})
                self.assertEqual(self.store.results["structure:daily-test"]["error_code"], "STRUCTURE_LIMIT")
                progress = self.store.progress["structure:daily-test"]
                self.assertLess(progress["next_index"], len(progress["queue"]))
                self.assertLessEqual(len(progress["records"]), R.MAX_OBJECTS)
                self.assertLessEqual(len(progress["queue"]), R.MAX_TASKS)

    def test_checkpoint_tampering_and_future_times_fail_before_http_without_private_error(self):
        R.run_structure(self.reader, self.store, self.clock.now)
        good = deepcopy(self.store.progress["structure:daily-test"])
        variants = []
        for key, value in (("customer_id", B), ("cycle_day", "2026-10-04"), ("next_index", True),
                           ("campaign_fingerprint", "비공개위조")):
            source = deepcopy(good)
            source[key] = value
            variants.append(source)
        for modify in (lambda p: p["records"]["ad:ad-one"].update(parents=["campaign:cmp-one"]),
                       lambda p: p["records"]["campaign:cmp-one"]["record"].update(private="비공개위조"),
                       lambda p: p["records"]["campaign:cmp-one"].update(
                           checked_at=(NOW+timedelta(days=1)).isoformat()),
                       lambda p: p["queue"][0].update(entity="private"),
                       lambda p: p["queue"].append(deepcopy(p["queue"][0]))):
            source = deepcopy(good)
            modify(source)
            variants.append(source)
        for source in variants:
            self.store.progress["structure:daily-test"] = source
            before = len(self.http.calls)
            result = R.run_structure(self.reader, self.store, self.clock.now)
            self.assertEqual(result.counts, {"limited": 1})
            self.assertEqual(len(self.http.calls), before)
            self.assertEqual(self.store.results["structure:daily-test"]["error_code"], "CHECKPOINT_INVALID")
            self.assertNotIn("비공개", str(self.store.results))

    def test_explicit_exclusions_skip_before_begin_and_validate_integer_customer_ids(self):
        result = R.run_structure(self.reader, self.store, self.clock.now, exclude_customers=frozenset({A}))
        self.assertEqual(result.counts, {})
        self.assertEqual((self.http.calls, self.store.progress, self.store.results), ([], {}, {}))
        for excluded in ([True], [str(A)], [-1], None):
            with self.assertRaises(ValueError):
                R.run_structure(self.reader, self.store, self.clock.now, exclude_customers=excluded)
        self.assertEqual(self.reader.called_customers, frozenset())
        R.run_structure(self.reader, self.store, self.clock.now)
        self.assertEqual(self.reader.called_customers, frozenset({A}))
        self.assertIsInstance(self.reader.called_customers, frozenset)


if __name__ == "__main__":
    unittest.main()
